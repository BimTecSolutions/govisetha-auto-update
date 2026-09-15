```python
"""
Govisetha Lottery Auto-Update Script

Checks the NLB Govisetha results page for new draws and updates Firebase.

IMPORTANT:
- NLB uses a JavaScript "human" cookie challenge.
- This script handles that challenge without Selenium.
- The NLB results page is parsed using its actual HTML structure.
- If the website cannot be checked, the program FAILS instead of
  incorrectly saying "No updates needed".
"""

import os
import sys
import time
import json
import re
import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup

import firebase_admin
from firebase_admin import credentials, firestore


# ============================================================================
# LOGGING
# ============================================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)


# ============================================================================
# GOVISETHA AUTO UPDATER
# ============================================================================

class GovisethaAutoUpdater:
    """
    Auto-updater for Govisetha lottery results.

    NLB website:
        https://www.nlb.lk/results/govisetha

    Firestore structure:

        NLB_Results_All
            └── govisetha
                └── govisetha
                    ├── govisetha-4552
                    ├── govisetha-4551
                    └── ...
    """

    BASE_URL = "https://www.nlb.lk"

    LOTTERY_SLUG = "govisetha"
    LOTTERY_NAME = "Govisetha"

    COLLECTION_NAME = "NLB_Results_All"
    SUBSELECTION_NAME = "govisetha"

    # Change this only if you intentionally want more/less per workflow run.
    MAX_DRAWS_PER_RUN = 5

    REQUEST_TIMEOUT = 30

    # Delay between individual draw requests.
    REQUEST_DELAY = 1.0

    # Retry count for website requests.
    MAX_RETRIES = 3

    def __init__(self, firestore_client=None):

        self.firestore_client = firestore_client

        self.session = requests.Session()

        # Browser-like headers.
        #
        # Do NOT use an extremely old browser User-Agent.
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/140.0.0.0 Safari/537.36"
            ),
            "Accept": (
                "text/html,application/xhtml+xml,"
                "application/xml;q=0.9,image/avif,image/webp,"
                "*/*;q=0.8"
            ),
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        })

    # ------------------------------------------------------------------------
    # NLB REQUEST / HUMAN COOKIE HANDLING
    # ------------------------------------------------------------------------

    def _extract_human_cookie(self, html: str) -> Optional[str]:
        """
        Extract the temporary NLB 'human' cookie from the JavaScript challenge.

        NLB returns something similar to:

            setCookie('human','xxxxxxxxxxxxxxxx',1);
            location.reload();

        Returns:
            Cookie value, or None if not found.
        """

        if not html:
            return None

        patterns = [
            r"setCookie\s*\(\s*['\"]human['\"]\s*,\s*['\"]([^'\"]+)['\"]",
            r"document\.cookie\s*=\s*['\"]human=([^;'\" ]+)",
        ]

        for pattern in patterns:
            match = re.search(
                pattern,
                html,
                re.IGNORECASE
            )

            if match:
                return match.group(1).strip()

        return None

    def _is_human_challenge(self, html: str) -> bool:
        """
        Determine whether the response is the NLB JavaScript challenge.
        """

        if not html:
            return False

        lower = html.lower()

        return (
            "setcookie('human'" in lower
            or 'setcookie("human"' in lower
        )

    def _looks_like_govisetha_page(self, html: str) -> bool:
        """
        Determine whether HTML appears to be the actual Govisetha results page.
        """

        if not html:
            return False

        lower = html.lower()

        # These are characteristics of the real NLB page.
        return (
            "govisetha lottery results" in lower
            and 'title="letter"' in lower
            and 'title="number-1"' in lower
            and 'title="number-4"' in lower
        )

    def fetch_page(self, url: str) -> Optional[str]:
        """
        Fetch an NLB page.

        Handles the NLB JavaScript human-cookie challenge automatically.

        Process:

            Request page
                ↓
            Receive 363-byte challenge
                ↓
            Extract human cookie
                ↓
            Put cookie in Session
                ↓
            Request page again
                ↓
            Receive actual HTML
        """

        for attempt in range(1, self.MAX_RETRIES + 1):

            try:

                logger.info(
                    f"Fetching URL (attempt {attempt}/{self.MAX_RETRIES}): {url}"
                )

                response = self.session.get(
                    url,
                    timeout=self.REQUEST_TIMEOUT,
                    allow_redirects=True
                )

                logger.info(
                    f"HTTP {response.status_code} | "
                    f"{len(response.content)} bytes | "
                    f"{response.url}"
                )

                if response.status_code != 200:

                    logger.warning(
                        f"HTTP {response.status_code} received from {url}"
                    )

                    if attempt < self.MAX_RETRIES:
                        time.sleep(2 ** (attempt - 1))

                    continue

                html = response.text

                # ------------------------------------------------------------
                # Check for NLB human challenge
                # ------------------------------------------------------------

                if self._is_human_challenge(html):

                    logger.info(
                        "🛡️ NLB human-cookie challenge detected."
                    )

                    human_cookie = self._extract_human_cookie(html)

                    if not human_cookie:

                        logger.error(
                            "❌ NLB challenge detected but human cookie "
                            "could not be extracted."
                        )

                        if attempt < self.MAX_RETRIES:
                            time.sleep(2 ** (attempt - 1))

                        continue

                    logger.info(
                        "✅ NLB human cookie extracted successfully."
                    )

                    # Set cookie for www.nlb.lk.
                    self.session.cookies.set(
                        "human",
                        human_cookie,
                        domain="www.nlb.lk",
                        path="/"
                    )

                    logger.info(
                        "🔄 Reloading NLB page with human cookie..."
                    )

                    response = self.session.get(
                        url,
                        timeout=self.REQUEST_TIMEOUT,
                        allow_redirects=True
                    )

                    logger.info(
                        f"Reload response: HTTP {response.status_code} | "
                        f"{len(response.content)} bytes"
                    )

                    if response.status_code != 200:

                        logger.warning(
                            f"NLB reload returned HTTP "
                            f"{response.status_code}"
                        )

                        if attempt < self.MAX_RETRIES:
                            time.sleep(2 ** (attempt - 1))

                        continue

                    html = response.text

                # ------------------------------------------------------------
                # Validate actual page
                # ------------------------------------------------------------

                if self._looks_like_govisetha_page(html):

                    logger.info(
                        f"✅ Successfully obtained NLB Govisetha page "
                        f"({len(response.content)} bytes)"
                    )

                    return html

                # If this isn't the result page, don't silently accept it.
                logger.warning(
                    f"⚠️ Response received but it does not look like "
                    f"the Govisetha results page. "
                    f"Size={len(response.content)} bytes"
                )

                # Helpful diagnostic for unexpected NLB responses.
                logger.debug(
                    f"Response preview: {html[:500]}"
                )

                if attempt < self.MAX_RETRIES:
                    time.sleep(2 ** (attempt - 1))

            except requests.exceptions.Timeout:

                logger.warning(
                    f"⏱️ Timeout while fetching {url}"
                )

                if attempt < self.MAX_RETRIES:
                    time.sleep(2 ** (attempt - 1))

            except requests.exceptions.ConnectionError as e:

                logger.warning(
                    f"🌐 Connection error: {e}"
                )

                if attempt < self.MAX_RETRIES:
                    time.sleep(2 ** (attempt - 1))

            except requests.exceptions.RequestException as e:

                logger.warning(
                    f"⚠️ Request error: {e}"
                )

                if attempt < self.MAX_RETRIES:
                    time.sleep(2 ** (attempt - 1))

            except Exception as e:

                logger.error(
                    f"❌ Unexpected error fetching {url}: "
                    f"{type(e).__name__}: {e}"
                )

                if attempt < self.MAX_RETRIES:
                    time.sleep(2 ** (attempt - 1))

        logger.error(
            f"❌ Failed to fetch valid NLB page after "
            f"{self.MAX_RETRIES} attempts: {url}"
        )

        return None

    # ------------------------------------------------------------------------
    # GET LATEST DRAW
    # ------------------------------------------------------------------------

    def get_latest_draw_number(self) -> Optional[int]:
        """
        Get the latest Govisetha draw number.

        The NLB results page lists the newest result first.

        We therefore parse the first row of:

            table.w0.tbl

        and read the first <b> element.
        """

        url = f"{self.BASE_URL}/results/{self.LOTTERY_SLUG}"

        html = self.fetch_page(url)

        if not html:
            logger.error(
                "❌ Could not obtain Govisetha results page."
            )
            return None

        try:

            soup = BeautifulSoup(
                html,
                "html.parser"
            )

            # Find the Govisetha results table.
            table = soup.select_one("table.w0.tbl")

            if not table:

                # Fallback: find table containing "Draw/Date".
                for candidate in soup.find_all("table"):

                    header_text = candidate.get_text(
                        " ",
                        strip=True
                    ).lower()

                    if (
                        "draw/date" in header_text
                        and "results" in header_text
                    ):
                        table = candidate
                        break

            if not table:

                logger.error(
                    "❌ Could not find Govisetha results table."
                )

                return None

            # Find table rows.
            rows = table.find_all("tr")

            for row in rows:

                cells = row.find_all("td")

                if not cells:
                    continue

                # First cell should contain:
                #
                # 4552
                # Monday September 14, 2026
                #
                bold = cells[0].find("b")

                if not bold:
                    continue

                draw_text = bold.get_text(
                    " ",
                    strip=True
                )

                if not draw_text.isdigit():
                    continue

                draw_number = int(draw_text)

                # Validate that this really looks like a Govisetha result.
                result_items = row.select(
                    'li[title="Letter"], '
                    'li[title^="Number-"]'
                )

                if len(result_items) >= 5:

                    logger.info(
                        f"🏆 Latest Govisetha draw on website: "
                        f"{draw_number}"
                    )

                    return draw_number

            logger.error(
                "❌ Could not identify latest Govisetha draw "
                "from results table."
            )

            return None

        except Exception as e:

            logger.error(
                f"❌ Error parsing latest Govisetha draw: "
                f"{type(e).__name__}: {e}"
            )

            return None

    # ------------------------------------------------------------------------
    # FIRESTORE
    # ------------------------------------------------------------------------

    def get_existing_draws(self) -> List[int]:
        """
        Get all existing Govisetha draw numbers from Firestore.
        """

        if not self.firestore_client:

            raise RuntimeError(
                "Firestore client is not initialized."
            )

        try:

            subcollection_ref = (
                self.firestore_client
                .collection(self.COLLECTION_NAME)
                .document(self.SUBSELECTION_NAME)
                .collection(self.SUBSELECTION_NAME)
            )

            docs = subcollection_ref.stream()

            draw_numbers = []

            for doc in docs:

                data = doc.to_dict()

                if not data:
                    continue

                draw_value = data.get("draw_number")

                if draw_value is None:
                    continue

                try:

                    draw_numbers.append(
                        int(draw_value)
                    )

                except (ValueError, TypeError):

                    continue

            draw_numbers = sorted(
                set(draw_numbers)
            )

            logger.info(
                f"Found {len(draw_numbers)} existing draws in Firebase."
            )

            if draw_numbers:

                logger.info(
                    f"Latest Firebase draw: {max(draw_numbers)}"
                )

            return draw_numbers

        except Exception as e:

            logger.error(
                f"❌ Error reading existing Firebase draws: "
                f"{type(e).__name__}: {e}"
            )

            # IMPORTANT:
            # Do NOT return [] here.
            #
            # Returning [] could make the program think Firebase
            # is empty and potentially attempt a huge backfill.
            raise

    # ------------------------------------------------------------------------
    # PARSE RESULTS FROM RESULTS LIST PAGE
    # ------------------------------------------------------------------------

    def parse_result_row(
        self,
        row,
        expected_draw_number: Optional[int] = None
    ) -> Optional[Dict]:
        """
        Parse one Govisetha result row from the NLB results list.
        """

        try:

            cells = row.find_all("td")

            if len(cells) < 2:
                return None

            # ------------------------------------------------------------
            # Draw number
            # ------------------------------------------------------------

            bold = cells[0].find("b")

            if not bold:
                return None

            draw_text = bold.get_text(
                " ",
                strip=True
            )

            if not draw_text.isdigit():
                return None

            draw_number = int(draw_text)

            if (
                expected_draw_number is not None
                and draw_number != expected_draw_number
            ):
                return None

            # ------------------------------------------------------------
            # Date
            # ------------------------------------------------------------

            date = ""

            first_cell_text = cells[0].get_text(
                " ",
                strip=True
            )

            # Usually:
            #
            # 4552 Monday September 14, 2026
            #
            date_match = re.search(
                r"((?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)"
                r"\s+[A-Za-z]+\s+\d{1,2},\s+\d{4})",
                first_cell_text
            )

            if date_match:

                date = date_match.group(1)

            else:

                # Fallback: anything resembling Month DD, YYYY.
                date_match = re.search(
                    r"([A-Za-z]+\s+\d{1,2},\s+\d{4})",
                    first_cell_text
                )

                if date_match:
                    date = date_match.group(1)

            # ------------------------------------------------------------
            # Letter
            # ------------------------------------------------------------

            letter_element = row.select_one(
                'li[title="Letter"]'
            )

            if not letter_element:

                logger.warning(
                    f"Draw {draw_number}: Letter element not found."
                )

                return None

            symbol = letter_element.get_text(
                " ",
                strip=True
            )

            if not symbol:
                return None

            symbol = symbol.upper()

            # ------------------------------------------------------------
            # Four numbers
            # ------------------------------------------------------------

            number_elements = row.select(
                'li[title="Number-1"], '
                'li[title="Number-2"], '
                'li[title="Number-3"], '
                'li[title="Number-4"]'
            )

            if len(number_elements) < 4:

                logger.warning(
                    f"Draw {draw_number}: "
                    f"Expected 4 number elements, "
                    f"found {len(number_elements)}."
                )

                return None

            numbers = []

            for element in number_elements[:4]:

                value = element.get_text(
                    " ",
                    strip=True
                ).strip()

                # Validate numeric value.
                if not re.fullmatch(r"\d{1,2}", value):

                    logger.warning(
                        f"Draw {draw_number}: "
                        f"Invalid number value: {value}"
                    )

                    return None

                # Preserve two-digit format.
                numbers.append(
                    f"{int(value):02d}"
                )

            # ------------------------------------------------------------
            # Result URL
            # ------------------------------------------------------------

            result_url = (
                f"{self.BASE_URL}/results/"
                f"{self.LOTTERY_SLUG}/{draw_number}"
            )

            more_link = row.find(
                "a",
                href=True
            )

            if more_link:

                href = more_link.get("href", "")

                if "govisetha" in href.lower():

                    if href.startswith("http"):

                        result_url = href

                    else:

                        result_url = (
                            self.BASE_URL
                            + "/"
                            + href.lstrip("/")
                        )

            return {
                "lottery": self.LOTTERY_NAME,
                "draw_number": str(draw_number),
                "date": date,
                "symbol": symbol,
                "numbers": numbers,
                "found": True,
                "url": result_url
            }

        except Exception as e:

            logger.error(
                f"Error parsing result row: "
                f"{type(e).__name__}: {e}"
            )

            return None

    # ------------------------------------------------------------------------
    # FETCH SPECIFIC DRAW
    # ------------------------------------------------------------------------

    def fetch_draw_result(
        self,
        draw_number: int
    ) -> Optional[Dict]:
        """
        Fetch a specific Govisetha draw.

        First tries the individual result page.

        If necessary, falls back to the main results page.
        """

        draw_number = int(draw_number)

        url = (
            f"{self.BASE_URL}/results/"
            f"{self.LOTTERY_SLUG}/{draw_number}"
        )

        logger.info(
            f"🔎 Fetching draw {draw_number}..."
        )

        # ------------------------------------------------------------
        # First: individual result page
        # ------------------------------------------------------------

        html = self.fetch_page(url)

        if html:

            try:

                soup = BeautifulSoup(
                    html,
                    "html.parser"
                )

                # The individual page may have the result in
                # a result block/table.
                #
                # First try to find a row containing our draw number.
                rows = soup.find_all("tr")

                for row in rows:

                    result = self.parse_result_row(
                        row,
                        expected_draw_number=draw_number
                    )

                    if result:

                        logger.info(
                            f"✅ Parsed draw {draw_number}: "
                            f"{result['symbol']} "
                            f"{', '.join(result['numbers'])}"
                        )

                        return result

                # ----------------------------------------------------
                # Fallback: parse individual page using specific li
                # elements.
                # ----------------------------------------------------

                letter_element = soup.select_one(
                    'li[title="Letter"]'
                )

                number_elements = soup.select(
                    'li[title="Number-1"], '
                    'li[title="Number-2"], '
                    'li[title="Number-3"], '
                    'li[title="Number-4"]'
                )

                if (
                    letter_element
                    and len(number_elements) >= 4
                ):

                    symbol = letter_element.get_text(
                        " ",
                        strip=True
                    ).upper()

                    numbers = []

                    for element in number_elements[:4]:

                        value = element.get_text(
                            " ",
                            strip=True
                        )

                        if re.fullmatch(
                            r"\d{1,2}",
                            value
                        ):

                            numbers.append(
                                f"{int(value):02d}"
                            )

                    if len(numbers) == 4:

                        # Find date from page text.
                        page_text = soup.get_text(
                            " ",
                            strip=True
                        )

                        date = ""

                        date_match = re.search(
                            r"(?:Monday|Tuesday|Wednesday|Thursday|"
                            r"Friday|Saturday|Sunday)"
                            r"\s+[A-Za-z]+\s+\d{1,2},\s+\d{4}",
                            page_text
                        )

                        if date_match:
                            date = date_match.group(0)

                        result = {
                            "lottery": self.LOTTERY_NAME,
                            "draw_number": str(draw_number),
                            "date": date,
                            "symbol": symbol,
                            "numbers": numbers,
                            "found": True,
                            "url": url
                        }

                        logger.info(
                            f"✅ Parsed draw {draw_number}: "
                            f"{symbol} "
                            f"{', '.join(numbers)}"
                        )

                        return result

            except Exception as e:

                logger.warning(
                    f"Error parsing individual page for draw "
                    f"{draw_number}: {e}"
                )

        # ------------------------------------------------------------
        # Fallback: main results page
        # ------------------------------------------------------------

        logger.info(
            f"Trying Govisetha results list as fallback "
            f"for draw {draw_number}..."
        )

        list_url = (
            f"{self.BASE_URL}/results/{self.LOTTERY_SLUG}"
        )

        list_html = self.fetch_page(
            list_url
        )

        if list_html:

            try:

                soup = BeautifulSoup(
                    list_html,
                    "html.parser"
                )

                table = soup.select_one(
                    "table.w0.tbl"
                )

                if table:

                    for row in table.find_all("tr"):

                        result = self.parse_result_row(
                            row,
                            expected_draw_number=draw_number
                        )

                        if result:

                            logger.info(
                                f"✅ Parsed draw {draw_number} "
                                f"from results list: "
                                f"{result['symbol']} "
                                f"{', '.join(result['numbers'])}"
                            )

                            return result

            except Exception as e:

                logger.warning(
                    f"Error parsing fallback results page "
                    f"for draw {draw_number}: {e}"
                )

        logger.error(
            f"❌ Could not obtain valid result for draw "
            f"{draw_number}."
        )

        return None

    # ------------------------------------------------------------------------
    # SAVE TO FIRESTORE
    # ------------------------------------------------------------------------

    def save_to_firestore(
        self,
        result: Dict
    ) -> bool:
        """
        Save one Govisetha result to Firestore.

        Existing structure is preserved.
        """

        if not self.firestore_client:

            logger.error(
                "Firestore client is not initialized."
            )

            return False

        try:

            draw_number = result.get(
                "draw_number"
            )

            if draw_number is None:

                logger.error(
                    "Cannot save result without draw_number."
                )

                return False

            draw_number = str(draw_number)

            doc_id = (
                f"{self.LOTTERY_SLUG}-{draw_number}"
            )

            firestore_data = {
                "lottery": result.get(
                    "lottery",
                    self.LOTTERY_NAME
                ),

                "draw_number": draw_number,

                "date": result.get(
                    "date",
                    ""
                ),

                "symbol": result.get(
                    "symbol",
                    ""
                ),

                "numbers": result.get(
                    "numbers",
                    []
                ),

                "found": result.get(
                    "found",
                    True
                ),

                "url": result.get(
                    "url",
                    ""
                ),

                "timestamp": (
                    firestore.SERVER_TIMESTAMP
                ),

                "updated_at": (
                    datetime.now().isoformat()
                )
            }

            doc_ref = (
                self.firestore_client
                .collection(self.COLLECTION_NAME)
                .document(self.SUBSELECTION_NAME)
                .collection(self.SUBSELECTION_NAME)
                .document(doc_id)
            )

            doc_ref.set(
                firestore_data,
                merge=True
            )

            logger.info(
                f"✅ Saved draw {draw_number} "
                f"to Firestore."
            )

            return True

        except Exception as e:

            logger.error(
                f"❌ Error saving draw "
                f"{result.get('draw_number')}: "
                f"{type(e).__name__}: {e}"
            )

            return False

    # ------------------------------------------------------------------------
    # SUMMARY DOCUMENT
    # ------------------------------------------------------------------------

    def update_summary_document(
        self,
        new_draws: List[int],
        failed_draws: List[int]
    ):
        """
        Update the Govisetha summary document.
        """

        if not self.firestore_client:
            return

        try:

            summary_doc_id = (
                f"{self.LOTTERY_SLUG}-summary"
            )

            doc_ref = (
                self.firestore_client
                .collection(self.COLLECTION_NAME)
                .document(self.SUBSELECTION_NAME)
                .collection(self.SUBSELECTION_NAME)
                .document(summary_doc_id)
            )

            doc = doc_ref.get()

            existing_data = (
                doc.to_dict()
                if doc.exists
                else {}
            )

            previous_all_time = (
                existing_data.get(
                    "all_time_added",
                    []
                )
            )

            if not isinstance(
                previous_all_time,
                list
            ):
                previous_all_time = []

            summary_data = {
                "lottery": self.LOTTERY_NAME,

                "last_updated": (
                    firestore.SERVER_TIMESTAMP
                ),

                "last_updated_iso": (
                    datetime.now().isoformat()
                ),

                "last_updated_draws": (
                    new_draws[-5:]
                    if new_draws
                    else existing_data.get(
                        "last_updated_draws",
                        []
                    )
                ),

                "total_draws_added": (
                    existing_data.get(
                        "total_draws_added",
                        0
                    )
                    + len(new_draws)
                ),

                "failed_draws": failed_draws,

                "all_time_added": (
                    previous_all_time
                    + new_draws
                )
            }

            doc_ref.set(
                summary_data,
                merge=True
            )

            logger.info(
                "📊 Summary document updated in Firestore."
            )

        except Exception as e:

            logger.error(
                f"❌ Error updating summary: {e}"
            )

    # ------------------------------------------------------------------------
    # CHECK AND UPDATE
    # ------------------------------------------------------------------------

    def check_and_update(
        self,
        max_draws_per_run: int = MAX_DRAWS_PER_RUN
    ) -> Tuple[List[int], List[int]]:
        """
        Check website against Firebase and update missing draws.

        Returns:
            (new_draws_added, failed_draws)
        """

        logger.info("=" * 70)
        logger.info(
            "🚀 Starting Govisetha Auto-Update Check"
        )
        logger.info("=" * 70)

        # ------------------------------------------------------------
        # STEP 1: Website
        # ------------------------------------------------------------

        latest_website = (
            self.get_latest_draw_number()
        )

        if latest_website is None:

            # IMPORTANT:
            # Raise an exception instead of returning [], [].
            #
            # Otherwise main() could incorrectly say:
            # "No updates needed."
            raise RuntimeError(
                "Could not determine latest Govisetha draw "
                "from NLB website."
            )

        logger.info(
            f"🌐 Latest draw on website: "
            f"{latest_website}"
        )

        # ------------------------------------------------------------
        # STEP 2: Firebase
        # ------------------------------------------------------------

        existing_draws = (
            self.get_existing_draws()
        )

        # If there are no Firebase records, start from the
        # known historical starting point.
        #
        # The original program used 4534.
        #
        # We keep that behavior rather than silently changing
        # your database history.
        if not existing_draws:

            logger.warning(
                "⚠️ No existing Govisetha draws found "
                "in Firebase."
            )

            start_draw = 4534

        else:

            latest_firebase = max(
                existing_draws
            )

            logger.info(
                f"🔥 Latest draw in Firebase: "
                f"{latest_firebase}"
            )

            # --------------------------------------------------------
            # Already up to date
            # --------------------------------------------------------

            if latest_firebase >= latest_website:

                logger.info(
                    "✅ Firebase is already up to date."
                )

                return [], []

            start_draw = (
                latest_firebase + 1
            )

        # ------------------------------------------------------------
        # STEP 3: Missing draws
        # ------------------------------------------------------------

        if start_draw > latest_website:

            logger.info(
                "✅ No missing draws."
            )

            return [], []

        missing_draws = list(
            range(
                start_draw,
                latest_website + 1
            )
        )

        logger.info(
            f"📊 Found {len(missing_draws)} "
            f"draw(s) missing from Firebase."
        )

        logger.info(
            f"   Missing range: "
            f"{missing_draws[0]} → "
            f"{missing_draws[-1]}"
        )

        # ------------------------------------------------------------
        # STEP 4: Limit per run
        # ------------------------------------------------------------

        if (
            max_draws_per_run is not None
            and max_draws_per_run > 0
            and len(missing_draws) > max_draws_per_run
        ):

            missing_draws = (
                missing_draws[:max_draws_per_run]
            )

            logger.info(
                f"⏳ Limiting this run to "
                f"{max_draws_per_run} draw(s)."
            )

        # ------------------------------------------------------------
        # STEP 5: Fetch + save
        # ------------------------------------------------------------

        new_draws_added = []
        failed_draws = []

        for index, draw_num in enumerate(
            missing_draws,
            start=1
        ):

            logger.info("-" * 70)

            logger.info(
                f"Processing draw "
                f"{draw_num} "
                f"({index}/{len(missing_draws)})"
            )

            try:

                result = (
                    self.fetch_draw_result(
                        draw_num
                    )
                )

                if not result:

                    logger.error(
                        f"❌ Could not fetch "
                        f"draw {draw_num}"
                    )

                    failed_draws.append(
                        draw_num
                    )

                    continue

                # Safety check.
                if int(result["draw_number"]) != int(draw_num):

                    logger.error(
                        f"❌ Draw mismatch! "
                        f"Requested {draw_num}, "
                        f"received "
                        f"{result.get('draw_number')}"
                    )

                    failed_draws.append(
                        draw_num
                    )

                    continue

                success = (
                    self.save_to_firestore(
                        result
                    )
                )

                if success:

                    new_draws_added.append(
                        draw_num
                    )

                else:

                    failed_draws.append(
                        draw_num
                    )

                if index < len(missing_draws):

                    time.sleep(
                        self.REQUEST_DELAY
                    )

            except Exception as e:

                logger.error(
                    f"❌ Error processing "
                    f"draw {draw_num}: "
                    f"{type(e).__name__}: {e}"
                )

                failed_draws.append(
                    draw_num
                )

        # ------------------------------------------------------------
        # STEP 6: Summary
        # ------------------------------------------------------------

        if (
            new_draws_added
            or failed_draws
        ):

            self.update_summary_document(
                new_draws_added,
                failed_draws
            )

        logger.info("=" * 70)
        logger.info(
            "📊 UPDATE SUMMARY"
        )
        logger.info("=" * 70)

        logger.info(
            f"🌐 Website latest draw: "
            f"{latest_website}"
        )

        logger.info(
            f"✅ New draws added: "
            f"{len(new_draws_added)}"
        )

        if new_draws_added:

            logger.info(
                "   Added: "
                + ", ".join(
                    map(
                        str,
                        new_draws_added
                    )
                )
            )

        logger.info(
            f"❌ Failed draws: "
            f"{len(failed_draws)}"
        )

        if failed_draws:

            logger.info(
                "   Failed: "
                + ", ".join(
                    map(
                        str,
                        failed_draws
                    )
                )
            )

        logger.info("=" * 70)

        return (
            new_draws_added,
            failed_draws
        )

    # ------------------------------------------------------------------------
    # CLEANUP
    # ------------------------------------------------------------------------

    def cleanup(self):
        """
        Close HTTP session.
        """

        try:
            self.session.close()
        except Exception:
            pass


# ============================================================================
# FIREBASE INITIALIZATION
# ============================================================================

def initialize_firebase():
    """
    Initialize Firebase using FIREBASE_CREDENTIALS environment variable.

    The GitHub Actions secret should contain the complete Firebase
    service-account JSON.
    """

    try:

        cred_json = os.environ.get(
            "FIREBASE_CREDENTIALS"
        )

        if not cred_json:

            logger.error(
                "❌ FIREBASE_CREDENTIALS environment "
                "variable not found."
            )

            logger.error(
                "Please check your GitHub Secrets."
            )

            return None

        # Parse credentials JSON.
        try:

            cred_dict = json.loads(
                cred_json
            )

        except json.JSONDecodeError as e:

            logger.error(
                f"❌ Failed to parse "
                f"FIREBASE_CREDENTIALS JSON: {e}"
            )

            return None

        # Initialize Firebase only once.
        if not firebase_admin._apps:

            cred = credentials.Certificate(
                cred_dict
            )

            firebase_admin.initialize_app(
                cred
            )

            logger.info(
                "✅ Firebase initialized successfully."
            )

        else:

            logger.info(
                "✅ Firebase already initialized."
            )

        return firestore.client()

    except Exception as e:

        logger.error(
            f"❌ Firebase initialization error: "
            f"{type(e).__name__}: {e}"
        )

        return None


# ============================================================================
# MAIN
# ============================================================================

def main():
    """
    Main program.
    """

    logger.info("=" * 70)
    logger.info(
        "🏆 GOVISETHA AUTO-UPDATER (Selenium-Free)"
    )
    logger.info("=" * 70)

    logger.info(
        "NLB URL: "
        "https://www.nlb.lk/results/govisetha"
    )

    # ------------------------------------------------------------
    # Firebase
    # ------------------------------------------------------------

    db = initialize_firebase()

    if not db:

        logger.error(
            "❌ Firebase initialization failed."
        )

        return 1

    updater = GovisethaAutoUpdater(
        db
    )

    try:

        # --------------------------------------------------------
        # Run updater
        # --------------------------------------------------------

        new_draws, failed_draws = (
            updater.check_and_update(
                max_draws_per_run=5
            )
        )

        # --------------------------------------------------------
        # Final status
        # --------------------------------------------------------

        if failed_draws:

            logger.warning(
                f"⚠️ Update completed with "
                f"{len(failed_draws)} failed draw(s)."
            )

            logger.info(
                f"Successfully added "
                f"{len(new_draws)} draw(s)."
            )

            return 1

        if new_draws:

            logger.info(
                f"✅ Update complete!"
            )

            logger.info(
                f"Added {len(new_draws)} "
                f"new draw(s): "
                f"{', '.join(map(str, new_draws))}"
            )

        else:

            logger.info(
                "✅ No updates needed. "
                "Firebase is already up to date."
            )

        return 0

    except Exception as e:

        logger.error(
            "=" * 70
        )

        logger.error(
            "❌ PROGRAM FAILED"
        )

        logger.error(
            f"{type(e).__name__}: {e}"
        )

        logger.error(
            "=" * 70
        )

        # IMPORTANT:
        # Non-zero exit code makes GitHub Actions fail.
        return 1

    finally:

        updater.cleanup()

        logger.info(
            "=" * 70
        )

        logger.info(
            "PROGRAM COMPLETE"
        )

        logger.info(
            "=" * 70
        )


# ============================================================================
# ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    sys.exit(
        main()
    )
```

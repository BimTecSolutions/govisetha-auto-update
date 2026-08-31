```python
import os
import re
import time
from datetime import datetime
from typing import Dict, Optional, List

import requests
from bs4 import BeautifulSoup

import firebase_admin
from firebase_admin import credentials, firestore


# ============================================================
# CONFIGURATION
# ============================================================

BASE_URL = "https://www.nlb.lk"

LOTTERY_SLUG = "govisetha"
LOTTERY_NAME = "Govisetha"

FIRESTORE_COLLECTION = "NLB_Results_All"
FIRESTORE_SUBCOLLECTION = "govisetha"

# How many future draw numbers to check after the latest
# Firebase draw.
CHECK_AHEAD = 3

# Delay between NLB requests
REQUEST_DELAY = 1.0


# ============================================================
# GOVISETHA SCRAPER
# ============================================================

class GovisethaScraper:

    def __init__(self):
        self.session = requests.Session()

        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/151.0.0.0 Safari/537.36"
            ),
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;"
                "q=0.9,image/avif,image/webp,*/*;q=0.8"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        })

    # --------------------------------------------------------
    # FETCH PAGE
    # --------------------------------------------------------

    def fetch_page(self, url: str) -> Optional[str]:

        try:
            response = self.session.get(url, timeout=30)

            print(
                f"🌐 {url} | "
                f"HTTP {response.status_code} | "
                f"Size {len(response.text)}"
            )

            if response.status_code == 200 and len(response.text) > 100:
                return response.text

        except Exception as e:
            print(f"❌ Request error: {e}")

        return None

    # --------------------------------------------------------
    # EXTRACT DRAW DATE
    # --------------------------------------------------------

    def extract_draw_date(self, text: str) -> Optional[str]:

        date_patterns = [
            r'(?:Date|Draw Date)\s*:?\s*'
            r'([A-Za-z]+\s+\d{1,2},?\s+\d{4})',

            r'([A-Za-z]+\s+\d{1,2},?\s+\d{4})',
        ]

        for pattern in date_patterns:

            match = re.search(pattern, text, re.I)

            if match:
                return match.group(1)

        return None

    # --------------------------------------------------------
    # EXTRACT WINNING NUMBERS
    # --------------------------------------------------------

    def extract_winning_numbers(
        self,
        text: str,
        draw_number: str
    ) -> Dict:

        result = {
            "symbol": None,
            "numbers": [],
            "found": False
        }

        # Locate draw number
        draw_pattern = (
            rf'(?:Draw|Lottery)\s*'
            rf'(?:No|Number)?\.?\s*:?\s*'
            rf'{re.escape(draw_number)}'
        )

        draw_match = re.search(draw_pattern, text, re.I)

        if not draw_match:
            print(f"⚠️ Draw number {draw_number} not found on page")
            return result

        # ----------------------------------------------------
        # First method
        # Govisetha:
        # S 20 55 57 73
        # ----------------------------------------------------

        start = draw_match.end()

        section = text[start:start + 500]

        pattern = (
            r'\b([A-Z])\s+'
            r'(\d+)\s+'
            r'(\d+)\s+'
            r'(\d+)\s+'
            r'(\d+)\b'
        )

        matches = re.findall(pattern, section, re.I)

        if matches:

            for match in matches:

                symbol = match[0].upper()

                numbers = list(match[1:5])

                numbers = [
                    n for n in numbers
                    if 0 <= int(n) <= 99
                ]

                if len(numbers) == 4:

                    result["symbol"] = symbol

                    result["numbers"] = [
                        f"{int(n):02d}"
                        for n in numbers
                    ]

                    result["found"] = True

                    return result

        # ----------------------------------------------------
        # Second method
        # Allow 3-5 numbers
        # ----------------------------------------------------

        pattern = (
            r'\b([A-Z])\s+'
            r'(\d+)\s+'
            r'(\d+)\s+'
            r'(\d+)'
            r'(?:\s+(\d+))?'
            r'(?:\s+(\d+))?\b'
        )

        matches = re.findall(pattern, section, re.I)

        if matches:

            for match in matches:

                symbol = match[0].upper()

                numbers = [
                    n for n in match[1:]
                    if n and 0 <= int(n) <= 99
                ]

                if len(numbers) >= 4:

                    result["symbol"] = symbol

                    result["numbers"] = [
                        f"{int(n):02d}"
                        for n in numbers[:4]
                    ]

                    result["found"] = True

                    return result

        return result

    # --------------------------------------------------------
    # GET ONE RESULT
    # --------------------------------------------------------

    def get_result(
        self,
        draw_number: str
    ) -> Optional[Dict]:

        url = (
            f"{BASE_URL}/results/"
            f"{LOTTERY_SLUG}/"
            f"{draw_number}"
        )

        print(f"\n🔎 Checking draw {draw_number}")

        html = self.fetch_page(url)

        if not html:
            return None

        soup = BeautifulSoup(
            html,
            "html.parser"
        )

        all_text = soup.get_text(
            separator=" ",
            strip=True
        )

        date = self.extract_draw_date(all_text)

        extracted = self.extract_winning_numbers(
            all_text,
            draw_number
        )

        if extracted["found"]:

            result = {
                "lottery": LOTTERY_NAME,
                "draw_number": draw_number,
                "date": date,
                "symbol": extracted["symbol"],
                "numbers": extracted["numbers"],
                "url": url,
                "found": True
            }

            print(
                f"✅ Found draw {draw_number}: "
                f"{result['symbol']} "
                f"{' '.join(result['numbers'])} "
                f"({result['date']})"
            )

            return result

        print(
            f"⏳ Draw {draw_number} exists/page loaded, "
            f"but result data was not detected yet."
        )

        return None


# ============================================================
# FIREBASE
# ============================================================

def initialize_firebase():

    try:

        # GitHub Actions:
        # FIREBASE_CREDENTIALS contains the JSON credentials.

        firebase_credentials = os.environ.get(
            "FIREBASE_CREDENTIALS"
        )

        if not firebase_credentials:

            print(
                "❌ FIREBASE_CREDENTIALS environment variable "
                "was not found."
            )

            return None

        # Prevent multiple initialization attempts
        if not firebase_admin._apps:

            import json

            credential_data = json.loads(
                firebase_credentials
            )

            cred = credentials.Certificate(
                credential_data
            )

            firebase_admin.initialize_app(cred)

            print(
                "✅ Firebase initialized successfully"
            )

        return firestore.client()

    except Exception as e:

        print(
            f"❌ Firebase initialization error: {e}"
        )

        return None


# ============================================================
# FIRESTORE HELPERS
# ============================================================

def get_results_collection(db):

    return (
        db
        .collection(FIRESTORE_COLLECTION)
        .document(FIRESTORE_SUBCOLLECTION)
        .collection(FIRESTORE_SUBCOLLECTION)
    )


def get_latest_draw_number(db) -> Optional[int]:

    """
    Find the highest numeric draw number currently
    stored in Firestore.

    We intentionally read the documents and calculate
    the maximum because the draw_number is stored as a
    string in the existing database.
    """

    try:

        collection_ref = get_results_collection(db)

        docs = collection_ref.stream()

        highest_draw = None

        for doc in docs:

            data = doc.to_dict()

            draw_number = data.get("draw_number")

            if not draw_number:
                continue

            # Ignore summary/system documents
            if not str(draw_number).isdigit():
                continue

            draw_int = int(draw_number)

            if (
                highest_draw is None
                or draw_int > highest_draw
            ):
                highest_draw = draw_int

        return highest_draw

    except Exception as e:

        print(
            f"❌ Error reading latest Firestore draw: {e}"
        )

        return None


def document_exists(
    db,
    draw_number: str
) -> bool:

    doc_id = f"{LOTTERY_SLUG}-{draw_number}"

    doc_ref = (
        get_results_collection(db)
        .document(doc_id)
    )

    return doc_ref.get().exists


# ============================================================
# SAVE ONE RESULT
# ============================================================

def save_result_to_firestore(
    db,
    result: Dict
) -> bool:

    draw_number = result["draw_number"]

    doc_id = f"{LOTTERY_SLUG}-{draw_number}"

    doc_ref = (
        get_results_collection(db)
        .document(doc_id)
    )

    try:

        # ----------------------------------------------------
        # DUPLICATE PROTECTION
        # ----------------------------------------------------

        existing_doc = doc_ref.get()

        if existing_doc.exists:

            print(
                f"⏭️ Draw {draw_number} already exists. "
                f"Skipping."
            )

            return False

        # ----------------------------------------------------
        # FIRESTORE DATA
        # ----------------------------------------------------

        firestore_data = {

            "lottery": result.get(
                "lottery",
                LOTTERY_NAME
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

            "timestamp":
                firestore.SERVER_TIMESTAMP,

            "scraped_at":
                datetime.now().isoformat()
        }

        # ----------------------------------------------------
        # CREATE ONLY
        #
        # create() is intentionally used instead of set().
        #
        # If two GitHub Actions somehow run simultaneously,
        # Firestore will reject the second create instead of
        # overwriting the existing document.
        # ----------------------------------------------------

        doc_ref.create(firestore_data)

        print(
            f"🎉 NEW RESULT SAVED: "
            f"{doc_id}"
        )

        return True

    except Exception as e:

        error_message = str(e)

        # Firestore ALREADY_EXISTS
        # means another process created it first.

        if (
            "Already exists" in error_message
            or "already exists" in error_message.lower()
        ):

            print(
                f"⏭️ Draw {draw_number} was already "
                f"created by another process."
            )

            return False

        print(
            f"❌ Error saving draw {draw_number}: "
            f"{e}"
        )

        return False


# ============================================================
# MAIN UPDATE PROCESS
# ============================================================

def update_latest_results():

    print("\n" + "=" * 70)

    print(
        "🏆 NLB GOVISETHA AUTO UPDATER".center(70)
    )

    print("=" * 70)

    print(
        f"🕒 Run time: "
        f"{datetime.now().isoformat()}"
    )

    # --------------------------------------------------------
    # Firebase
    # --------------------------------------------------------

    print("\n🔌 Connecting to Firebase...")

    db = initialize_firebase()

    if not db:

        print(
            "❌ Firebase connection failed."
        )

        return False

    # --------------------------------------------------------
    # Find latest Firebase draw
    # --------------------------------------------------------

    print(
        "\n📊 Finding latest Govisetha draw "
        "in Firestore..."
    )

    latest_draw = get_latest_draw_number(db)

    if latest_draw is None:

        print(
            "❌ No existing Govisetha draws "
            "were found in Firestore."
        )

        print(
            "Please upload your initial historical "
            "data first."
        )

        return False

    print(
        f"✅ Latest Firebase draw: "
        f"{latest_draw}"
    )

    # --------------------------------------------------------
    # Check NLB
    # --------------------------------------------------------

    scraper = GovisethaScraper()

    new_results = []

    print(
        f"\n🌐 Checking NLB for draws "
        f"{latest_draw + 1} "
        f"to "
        f"{latest_draw + CHECK_AHEAD}"
    )

    for draw_number in range(
        latest_draw + 1,
        latest_draw + CHECK_AHEAD + 1
    ):

        draw_str = str(draw_number)

        # Check Firestore first
        # This is an additional duplicate protection layer.

        if document_exists(
            db,
            draw_str
        ):

            print(
                f"⏭️ Draw {draw_str} already "
                f"exists in Firestore."
            )

            continue

        result = scraper.get_result(
            draw_str
        )

        if result:

            new_results.append(result)

        else:

            print(
                f"ℹ️ No new result for "
                f"draw {draw_str}."
            )

        time.sleep(REQUEST_DELAY)

    # --------------------------------------------------------
    # Nothing new
    # --------------------------------------------------------

    if not new_results:

        print(
            "\n✅ No new Govisetha results found."
        )

        print(
            "ℹ️ Firebase is already up to date."
        )

        print("\n" + "=" * 70)

        return True

    # --------------------------------------------------------
    # Save new results
    # --------------------------------------------------------

    print(
        f"\n📤 Found "
        f"{len(new_results)} new result(s)."
    )

    uploaded = 0

    for result in new_results:

        if save_result_to_firestore(
            db,
            result
        ):

            uploaded += 1

    # --------------------------------------------------------
    # Summary
    # --------------------------------------------------------

    print("\n" + "=" * 70)

    print(
        "📊 UPDATE SUMMARY".center(70)
    )

    print("=" * 70)

    print(
        f"Latest Firebase draw before update: "
        f"{latest_draw}"
    )

    print(
        f"New results detected: "
        f"{len(new_results)}"
    )

    print(
        f"New results uploaded: "
        f"{uploaded}"
    )

    if uploaded > 0:

        for result in new_results:

            print(
                f"   🎉 Draw "
                f"{result['draw_number']}: "
                f"{result['symbol']} "
                f"{' '.join(result['numbers'])}"
            )

    print("=" * 70)

    return True


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":

    try:

        success = update_latest_results()

        if not success:
            raise SystemExit(1)

    except Exception as e:

        print(
            f"\n❌ Fatal error: {e}"
        )

        raise SystemExit(1)
```

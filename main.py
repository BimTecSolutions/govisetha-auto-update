"""
Govisetha Lottery Auto-Update Script
Periodically checks NLB website for new results and updates Firebase
"""

import os
import sys
import time
import json
import requests
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from bs4 import BeautifulSoup
import re
import firebase_admin
from firebase_admin import credentials, firestore
import logging
import random

# Try to import fake_useragent, fallback to a list of user agents if not available
try:
    from fake_useragent import UserAgent
    HAS_FAKE_USERAGENT = True
except ImportError:
    HAS_FAKE_USERAGENT = False
    logging.warning("fake-useragent not available, using fallback user agents")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Fallback user agents if fake-useragent is not available
FALLBACK_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
]


class GovisethaAutoUpdater:
    """
    Auto-updater for Govisetha lottery results.
    Checks latest draw numbers and updates missing results.
    """
    
    BASE_URL = "https://www.nlb.lk"
    LOTTERY_SLUG = "govisetha"
    LOTTERY_NAME = "Govisetha"
    COLLECTION_NAME = "NLB_Results_All"
    SUBSELECTION_NAME = "govisetha"
    
    def __init__(self, firestore_client=None):
        self.firestore_client = firestore_client
        self.session = requests.Session()
        self._init_user_agent()
        self._update_headers()
        
    def _init_user_agent(self):
        """Initialize user agent generator."""
        if HAS_FAKE_USERAGENT:
            try:
                self.ua = UserAgent()
                logger.info("✅ fake-useragent initialized successfully")
            except Exception as e:
                logger.warning(f"⚠️ fake-useragent initialization failed: {e}")
                self.ua = None
        else:
            self.ua = None
            logger.info("Using fallback user agents")
    
    def _get_random_user_agent(self) -> str:
        """Get a random user agent."""
        if self.ua:
            try:
                return self.ua.random
            except:
                return random.choice(FALLBACK_USER_AGENTS)
        else:
            return random.choice(FALLBACK_USER_AGENTS)
        
    def _update_headers(self):
        """Update headers with random user agent."""
        headers = {
            "User-Agent": self._get_random_user_agent(),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Cache-Control": "max-age=0",
            "Referer": "https://www.google.com/",
            "DNT": "1",
        }
        self.session.headers.update(headers)
        
    def fetch_page(self, url: str, retry_count: int = 3) -> Optional[str]:
        """
        Fetch page content with multiple methods.
        """
        # Try different methods
        methods = [
            self._fetch_with_requests,
            self._fetch_with_selenium,
        ]
        
        for method in methods:
            for attempt in range(retry_count):
                try:
                    logger.debug(f"Attempting {method.__name__} for {url} (attempt {attempt + 1})")
                    self._update_headers()  # Rotate headers on each attempt
                    content = method(url)
                    if content and len(content) > 1000:
                        logger.info(f"✅ Successfully fetched {url} ({len(content)} bytes)")
                        return content
                    elif content:
                        logger.warning(f"Content too short: {len(content)} bytes, retrying...")
                    time.sleep(random.uniform(2, 5))
                except Exception as e:
                    logger.warning(f"Method {method.__name__} failed: {e}")
                    time.sleep(random.uniform(2, 5))
        
        return None
    
    def _fetch_with_requests(self, url: str) -> Optional[str]:
        """Fetch using requests with anti-bot headers."""
        try:
            # Add cookies to appear more like a real browser
            self.session.cookies.set('nlbsession', 'active', domain='.nlb.lk')
            
            response = self.session.get(url, timeout=30, allow_redirects=True)
            
            if response.status_code == 200:
                content = response.text
                # Check if we got a real page
                if len(content) > 1000 and ('Govisetha' in content or 'NLB' in content or 'Lottery' in content):
                    return content
                elif 'captcha' in content.lower() or 'bot' in content.lower():
                    logger.warning("Bot detection triggered, trying different headers...")
                    # Try with Chrome mobile user agent
                    self.session.headers.update({
                        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1",
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    })
                    response = self.session.get(url, timeout=30)
                    if len(response.text) > 1000:
                        return response.text
                else:
                    return content
            elif response.status_code == 403:
                logger.warning("Access forbidden (403). Trying with different headers...")
                # Try with a different set of headers
                self.session.headers.update({
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                })
                response = self.session.get(url, timeout=30)
                if len(response.text) > 1000:
                    return response.text
        except Exception as e:
            logger.warning(f"Requests error: {e}")
        
        return None
    
    def _fetch_with_selenium(self, url: str) -> Optional[str]:
        """Fetch using Selenium if available."""
        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
            from selenium.webdriver.common.by import By
            from selenium.webdriver.support.ui import WebDriverWait
            from selenium.webdriver.support import expected_conditions as EC
            
            options = Options()
            options.add_argument('--headless')
            options.add_argument('--no-sandbox')
            options.add_argument('--disable-dev-shm-usage')
            options.add_argument('--disable-gpu')
            options.add_argument('--window-size=1920,1080')
            options.add_argument('--disable-blink-features=AutomationControlled')
            options.add_experimental_option("excludeSwitches", ["enable-automation"])
            options.add_experimental_option('useAutomationExtension', False)
            
            # Add random user agent
            options.add_argument(f'--user-agent={self._get_random_user_agent()}')
            
            driver = webdriver.Chrome(options=options)
            driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            
            driver.get(url)
            time.sleep(3)
            
            # Wait for content
            WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
            
            content = driver.page_source
            driver.quit()
            
            if content and len(content) > 1000:
                return content
            return None
            
        except Exception as e:
            logger.debug(f"Selenium not available: {e}")
            return None

    def get_latest_draw_number(self) -> Optional[int]:
        """
        Get the latest draw number from the NLB website.
        """
        try:
            # Try multiple approaches
            approaches = [
                self._get_latest_from_results_page,
                self._get_latest_from_homepage,
                self._get_latest_from_archive,
            ]
            
            for approach in approaches:
                result = approach()
                if result:
                    logger.info(f"Found latest draw number: {result}")
                    return result
                time.sleep(1)
            
            logger.warning("Could not find latest draw number using any approach")
            return None
            
        except Exception as e:
            logger.error(f"Error getting latest draw: {e}")
            return None
    
    def _get_latest_from_results_page(self) -> Optional[int]:
        """Get latest draw from the results page."""
        urls = [
            f"{self.BASE_URL}/results/{self.LOTTERY_SLUG}",
            f"{self.BASE_URL}/results",
            f"{self.BASE_URL}/lottery-results",
            f"{self.BASE_URL}/lottery/govisetha",
        ]
        
        for url in urls:
            logger.info(f"Checking URL: {url}")
            html = self.fetch_page(url)
            if not html:
                continue
            
            soup = BeautifulSoup(html, 'html.parser')
            text = soup.get_text(separator=" ", strip=True)
            
            # Look for draw numbers with various patterns
            patterns = [
                r'(?:Draw|Lottery|Result)\s*(?:No|Number)?\.?\s*:?\s*(\d{3,4})',
                r'Govisetha\s*(?:Draw|Lottery|Result)?\s*(?:No|Number)?\.?\s*:?\s*(\d{3,4})',
                r'Draw\s+(\d{3,4})',
                r'#\s*(\d{3,4})',
                r'Result\s+(\d{3,4})',
                r'(\d{3,4})\s*(?:th|nd|rd|st)\s*(?:Draw|Lottery)',
                r'[Dd]raw\s*[Nn]o\.?\s*[:]?\s*(\d{3,4})',
                r'[Ll]ottery\s*[Nn]o\.?\s*[:]?\s*(\d{3,4})',
            ]
            
            # Search in visible text
            for pattern in patterns:
                matches = re.findall(pattern, text, re.I)
                if matches:
                    draw_numbers = [int(m) for m in matches if m.isdigit()]
                    if draw_numbers:
                        latest = max(draw_numbers)
                        logger.info(f"Found draw number {latest} from pattern {pattern}")
                        return latest
            
            # Also look in links
            for link in soup.find_all('a', href=True):
                href = link['href']
                # Look for draw numbers in links
                link_patterns = [
                    r'/results/govisetha/(\d{3,4})',
                    r'/govisetha/(\d{3,4})',
                    r'/lottery/govisetha/(\d{3,4})',
                    r'/draw/(\d{3,4})',
                ]
                for pattern in link_patterns:
                    match = re.search(pattern, href)
                    if match:
                        return int(match.group(1))
                
                # Check link text
                link_text = link.get_text().strip()
                match = re.search(r'Draw\s*(\d{3,4})', link_text, re.I)
                if match:
                    return int(match.group(1))
        
        return None
    
    def _get_latest_from_homepage(self) -> Optional[int]:
        """Try to get latest draw from homepage."""
        logger.info("Checking homepage for latest draw")
        html = self.fetch_page(self.BASE_URL)
        if not html:
            return None
        
        # Look for links to recent results
        patterns = [
            r'/results/govisetha/(\d{3,4})',
            r'govisetha/(\d{3,4})',
            r'/lottery/govisetha/(\d{3,4})',
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, html, re.I)
            if matches:
                draw_numbers = [int(m) for m in matches if m.isdigit()]
                if draw_numbers:
                    return max(draw_numbers)
        
        # Look for draw number in visible text
        soup = BeautifulSoup(html, 'html.parser')
        text = soup.get_text(separator=" ", strip=True)
        
        patterns = [
            r'Latest\s+Draw\s*:?\s*(\d{3,4})',
            r'Current\s+Draw\s*:?\s*(\d{3,4})',
            r'Draw\s+No\s*:?\s*(\d{3,4})',
            r'Last\s+Draw\s*:?\s*(\d{3,4})',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.I)
            if match:
                return int(match.group(1))
        
        return None
    
    def _get_latest_from_archive(self) -> Optional[int]:
        """Try to get latest from archive or sitemap."""
        urls = [
            f"{self.BASE_URL}/sitemap.xml",
            f"{self.BASE_URL}/sitemap_index.xml",
            f"{self.BASE_URL}/robots.txt",
        ]
        
        for url in urls:
            try:
                logger.info(f"Checking archive: {url}")
                response = self.session.get(url, timeout=15)
                if response.status_code == 200:
                    content = response.text
                    # Look for draw numbers in sitemap
                    matches = re.findall(r'/results/govisetha/(\d{3,4})', content)
                    if matches:
                        return max([int(m) for m in matches])
            except Exception as e:
                logger.debug(f"Archive check failed for {url}: {e}")
                continue
        
        return None

    def get_existing_draws(self) -> List[int]:
        """Get all existing draw numbers from Firestore."""
        if not self.firestore_client:
            logger.error("Firestore client not initialized")
            return []
        
        try:
            subcollection_ref = self.firestore_client.collection(
                self.COLLECTION_NAME
            ).document(self.SUBSELECTION_NAME).collection(self.SUBSELECTION_NAME)
            
            # Get all documents
            docs = subcollection_ref.stream()
            
            draw_numbers = []
            for doc in docs:
                doc_data = doc.to_dict()
                if doc_data and 'draw_number' in doc_data:
                    try:
                        draw_numbers.append(int(doc_data['draw_number']))
                    except (ValueError, TypeError):
                        continue
            
            logger.info(f"Found {len(draw_numbers)} existing draws in Firebase")
            if draw_numbers:
                logger.info(f"Draw range: {min(draw_numbers)} to {max(draw_numbers)}")
            return draw_numbers
            
        except Exception as e:
            logger.error(f"Error getting existing draws: {e}")
            return []

    def extract_winning_numbers(self, text: str, draw_number: str) -> Dict:
        """Extract winning numbers for a specific draw number."""
        result = {
            "symbol": None,
            "numbers": [],
            "found": False
        }
        
        # First try to find the section with the draw number
        draw_patterns = [
            rf'(?:Draw|Lottery|Result)\s*(?:No|Number)?\.?\s*:?\s*{draw_number}',
            rf'{draw_number}\s*(?:th|nd|rd|st)\s*(?:Draw|Lottery)',
            rf'#{draw_number}',
            rf'Draw\s*{draw_number}',
            rf'Result\s*{draw_number}',
        ]
        
        draw_pos = -1
        for pattern in draw_patterns:
            match = re.search(pattern, text, re.I)
            if match:
                draw_pos = match.start()
                break
        
        if draw_pos == -1:
            # Try just the number
            match = re.search(rf'\b{draw_number}\b', text)
            if match:
                draw_pos = match.start()
            else:
                return result
        
        # Get context around the draw number
        start = max(0, draw_pos - 200)
        end = min(len(text), draw_pos + 500)
        section = text[start:end]
        
        logger.debug(f"Extracting numbers from section: {section[:200]}...")
        
        # Try different patterns for Govisetha format
        # Pattern 1: S 20 55 57 73 (letter + 4 numbers)
        pattern = r'\b([A-Z])\s+(\d{1,2})\s+(\d{1,2})\s+(\d{1,2})\s+(\d{1,2})\b'
        matches = re.findall(pattern, section, re.I)
        
        if matches:
            for match in matches:
                symbol = match[0]
                numbers = list(match[1:5])
                numbers = [n for n in numbers if n and 0 <= int(n) <= 99]
                if len(numbers) == 4:
                    result["symbol"] = symbol
                    result["numbers"] = [f"{int(n):02d}" for n in numbers]
                    result["found"] = True
                    logger.debug(f"Found numbers with pattern 1: {symbol} {result['numbers']}")
                    return result
        
        # Pattern 2: Letter with 3-4 numbers
        pattern = r'\b([A-Z])\s+(\d{1,2})\s+(\d{1,2})\s+(\d{1,2})(?:\s+(\d{1,2}))?\b'
        matches = re.findall(pattern, section, re.I)
        
        if matches:
            for match in matches:
                symbol = match[0]
                numbers = [n for n in match[1:] if n and 0 <= int(n) <= 99]
                if len(numbers) >= 3:
                    result["symbol"] = symbol
                    result["numbers"] = [f"{int(n):02d}" for n in numbers[:4]]
                    while len(result["numbers"]) < 4:
                        result["numbers"].append("00")
                    result["found"] = True
                    logger.debug(f"Found numbers with pattern 2: {symbol} {result['numbers']}")
                    return result
        
        # Pattern 3: Look for any numbers after the draw number
        # Sometimes the format is just the numbers
        numbers_after = re.findall(r'\b(\d{1,2})\b', section)
        numbers_after = [n for n in numbers_after if 0 <= int(n) <= 99]
        
        if len(numbers_after) >= 4:
            # Look for a letter before the numbers
            letter_match = re.search(r'\b([A-Z])\s+', section[:100])
            if letter_match:
                symbol = letter_match.group(1)
                result["symbol"] = symbol
                result["numbers"] = [f"{int(n):02d}" for n in numbers_after[:4]]
                result["found"] = True
                logger.debug(f"Found numbers with pattern 3: {symbol} {result['numbers']}")
                return result
        
        # Pattern 4: Special format for Govisetha
        # Sometimes the symbol is listed separately
        symbol_pattern = r'\b(S|s|L|l|F|f|D|d)\s+[Nn]o\.?\s*[:]?\s*\d+\s+'
        symbol_match = re.search(symbol_pattern, section)
        if symbol_match:
            symbol = symbol_match.group(1).upper()
            # Look for numbers after the symbol
            numbers_after_symbol = re.findall(r'\b(\d{1,2})\b', section[symbol_match.end():symbol_match.end()+100])
            numbers_after_symbol = [n for n in numbers_after_symbol if 0 <= int(n) <= 99]
            if len(numbers_after_symbol) >= 4:
                result["symbol"] = symbol
                result["numbers"] = [f"{int(n):02d}" for n in numbers_after_symbol[:4]]
                result["found"] = True
                logger.debug(f"Found numbers with pattern 4: {symbol} {result['numbers']}")
                return result
        
        return result

    def extract_draw_date(self, text: str) -> Optional[str]:
        """Extract the draw date from the page."""
        date_patterns = [
            r'(?:Date|Draw Date|Drawn Date)\s*:?\s*([A-Za-z]+\s+\d{1,2},?\s+\d{4})',
            r'([A-Za-z]+\s+\d{1,2},?\s+\d{4})',
            r'(\d{1,2}\s+[A-Za-z]+\s+\d{4})',
            r'(\d{4}-\d{2}-\d{2})',
            r'(\d{2}/\d{2}/\d{4})',
            r'(\d{2}\.\d{2}\.\d{4})',
        ]
        
        for pattern in date_patterns:
            match = re.search(pattern, text, re.I)
            if match:
                return match.group(1).strip()
        return None

    def fetch_draw_result(self, draw_number: int) -> Optional[Dict]:
        """Fetch and parse results for a specific draw number."""
        draw_str = str(draw_number)
        url = f"{self.BASE_URL}/results/{self.LOTTERY_SLUG}/{draw_str}"
        
        logger.info(f"Fetching draw {draw_number}...")
        html = self.fetch_page(url)
        
        if not html:
            logger.warning(f"Failed to fetch draw {draw_number}")
            return None
        
        try:
            # Parse the HTML
            soup = BeautifulSoup(html, 'html.parser')
            all_text = soup.get_text(separator=" ", strip=True)
            
            # Extract date
            date = self.extract_draw_date(all_text)
            
            # Extract winning numbers
            extracted = self.extract_winning_numbers(all_text, draw_str)
            
            if extracted["found"]:
                result = {
                    "lottery": self.LOTTERY_NAME,
                    "draw_number": draw_str,
                    "date": date,
                    "symbol": extracted["symbol"],
                    "numbers": extracted["numbers"],
                    "url": url,
                    "found": True
                }
                logger.info(f"✅ Found draw {draw_number}: {extracted['symbol']} {', '.join(extracted['numbers'])}")
                return result
            
            # If numbers not found, try looking in specific HTML elements
            result_containers = soup.find_all(['div', 'span', 'p', 'td', 'li'], 
                                            class_=re.compile(r'result|winning|number|draw', re.I))
            
            for container in result_containers:
                container_text = container.get_text(separator=" ", strip=True)
                extracted = self.extract_winning_numbers(container_text, draw_str)
                if extracted["found"]:
                    result = {
                        "lottery": self.LOTTERY_NAME,
                        "draw_number": draw_str,
                        "date": date,
                        "symbol": extracted["symbol"],
                        "numbers": extracted["numbers"],
                        "url": url,
                        "found": True
                    }
                    logger.info(f"✅ Found draw {draw_number} in container: {extracted['symbol']} {', '.join(extracted['numbers'])}")
                    return result
            
            logger.warning(f"No winning numbers found for draw {draw_number}")
            return None
            
        except Exception as e:
            logger.error(f"Error parsing draw {draw_number}: {e}")
            return None

    def save_to_firestore(self, result: Dict) -> bool:
        """Save a single result to Firestore."""
        if not self.firestore_client:
            logger.error("Firestore client not initialized")
            return False
        
        try:
            draw_number = result.get("draw_number")
            doc_id = f"{self.LOTTERY_SLUG}-{draw_number}"
            
            # Prepare data for Firestore
            firestore_data = {
                "lottery": result.get("lottery", self.LOTTERY_NAME),
                "draw_number": draw_number,
                "date": result.get("date", ""),
                "symbol": result.get("symbol", ""),
                "numbers": result.get("numbers", []),
                "found": result.get("found", True),
                "url": result.get("url", ""),
                "timestamp": firestore.SERVER_TIMESTAMP,
                "updated_at": datetime.now().isoformat()
            }
            
            # Set document in subcollection
            doc_ref = self.firestore_client.collection(
                self.COLLECTION_NAME
            ).document(self.SUBSELECTION_NAME).collection(
                self.SUBSELECTION_NAME
            ).document(doc_id)
            
            doc_ref.set(firestore_data, merge=True)
            logger.info(f"✅ Saved draw {draw_number} to Firestore")
            return True
            
        except Exception as e:
            logger.error(f"❌ Error saving draw {draw_number}: {e}")
            return False

    def check_and_update(self, max_draws_per_run: int = 3) -> Tuple[List[int], List[int]]:
        """Check for new draws and update Firebase."""
        logger.info("="*70)
        logger.info("🚀 Starting Govisetha Auto-Update Check")
        logger.info("="*70)
        
        # Get latest draw number from website
        latest_website = self.get_latest_draw_number()
        if not latest_website:
            logger.error("Failed to get latest draw number from website")
            return [], []
        
        logger.info(f"Latest draw on website: {latest_website}")
        
        # Get existing draws from Firebase
        existing_draws = self.get_existing_draws()
        
        if not existing_draws:
            # If no existing draws, start from a known recent draw
            logger.warning("No existing draws found in Firebase. Starting from draw 4534")
            start_draw = 4534
        else:
            latest_firebase = max(existing_draws)
            logger.info(f"Latest draw in Firebase: {latest_firebase}")
            
            # If we already have the latest, nothing to do
            if latest_firebase >= latest_website:
                logger.info("✅ All draws are up to date!")
                return [], []
            
            start_draw = latest_firebase + 1
        
        # Create list of missing draws
        missing_draws = list(range(start_draw, latest_website + 1))
        
        if not missing_draws:
            logger.info("✅ No new draws to update. All draws are up to date!")
            return [], []
        
        logger.info(f"📊 Found {len(missing_draws)} new draws to add")
        logger.info(f"   Range: {missing_draws[0]} to {missing_draws[-1]}")
        
        # Limit the number of draws per run
        if len(missing_draws) > max_draws_per_run:
            missing_draws = missing_draws[:max_draws_per_run]
            logger.info(f"   Limiting to {max_draws_per_run} draws per run")
        
        # Fetch and save missing draws
        new_draws_added = []
        failed_draws = []
        
        for draw_num in missing_draws:
            try:
                result = self.fetch_draw_result(draw_num)
                
                if result:
                    success = self.save_to_firestore(result)
                    if success:
                        new_draws_added.append(draw_num)
                    else:
                        failed_draws.append(draw_num)
                else:
                    logger.warning(f"❌ Could not fetch draw {draw_num}")
                    failed_draws.append(draw_num)
                
                # Random delay between requests
                time.sleep(random.uniform(2, 4))
                
            except Exception as e:
                logger.error(f"❌ Error processing draw {draw_num}: {e}")
                failed_draws.append(draw_num)
        
        # Update summary document
        if new_draws_added or failed_draws:
            self.update_summary_document(new_draws_added, failed_draws)
        
        # Log summary
        logger.info("="*70)
        logger.info("📊 UPDATE SUMMARY")
        logger.info("="*70)
        logger.info(f"✅ New draws added: {len(new_draws_added)}")
        if new_draws_added:
            logger.info(f"   {', '.join(map(str, new_draws_added))}")
        logger.info(f"❌ Failed draws: {len(failed_draws)}")
        if failed_draws:
            logger.info(f"   {', '.join(map(str, failed_draws))}")
        logger.info("="*70)
        
        return new_draws_added, failed_draws

    def update_summary_document(self, new_draws: List[int], failed_draws: List[int]):
        """Update the summary document in Firestore."""
        if not self.firestore_client:
            return
        
        try:
            summary_doc_id = f"{self.LOTTERY_SLUG}-summary"
            doc_ref = self.firestore_client.collection(
                self.COLLECTION_NAME
            ).document(self.SUBSELECTION_NAME).collection(
                self.SUBSELECTION_NAME
            ).document(summary_doc_id)
            
            # Get existing summary
            doc = doc_ref.get()
            existing_data = doc.to_dict() if doc.exists else {}
            
            # Update summary
            summary_data = {
                "lottery": self.LOTTERY_NAME,
                "last_updated": firestore.SERVER_TIMESTAMP,
                "last_updated_iso": datetime.now().isoformat(),
                "last_updated_draws": new_draws[-5:] if new_draws else existing_data.get('last_updated_draws', []),
                "total_draws_added": existing_data.get('total_draws_added', 0) + len(new_draws),
                "failed_draws": failed_draws,
                "all_time_added": existing_data.get('all_time_added', []) + new_draws,
            }
            
            doc_ref.set(summary_data, merge=True)
            logger.info("📊 Summary document updated in Firestore")
            
        except Exception as e:
            logger.error(f"Error updating summary: {e}")

    def cleanup(self):
        """Clean up resources."""
        pass


def initialize_firebase():
    """Initialize Firebase with credentials from environment variable."""
    try:
        # Get credentials from environment variable
        cred_json = os.environ.get('FIREBASE_CREDENTIALS')
        
        if not cred_json:
            logger.error("❌ FIREBASE_CREDENTIALS environment variable not found")
            logger.info("   Please set FIREBASE_CREDENTIALS in GitHub Secrets or environment")
            return None
        
        # Parse JSON credentials
        try:
            cred_dict = json.loads(cred_json)
            cred = credentials.Certificate(cred_dict)
        except json.JSONDecodeError as e:
            logger.error(f"❌ Failed to parse FIREBASE_CREDENTIALS JSON: {e}")
            return None
        
        # Initialize Firebase only if not already initialized
        if not firebase_admin._apps:
            firebase_admin.initialize_app(cred)
            logger.info("✅ Firebase initialized successfully")
        else:
            logger.info("✅ Firebase already initialized")
        
        return firestore.client()
        
    except Exception as e:
        logger.error(f"❌ Firebase initialization error: {e}")
        return None


def main():
    """Main function."""
    logger.info("="*70)
    logger.info("🏆 GOVISETHA AUTO-UPDATER (Enhanced)")
    logger.info("="*70)
    
    # Initialize Firebase
    db = initialize_firebase()
    
    if not db:
        logger.error("❌ Firebase initialization failed. Exiting.")
        sys.exit(1)
    
    # Initialize updater
    updater = GovisethaAutoUpdater(db)
    
    try:
        # Run the update check
        new_draws, failed_draws = updater.check_and_update(max_draws_per_run=3)
        
        # Print final status
        if new_draws or failed_draws:
            logger.info(f"\n✅ Update complete! Added {len(new_draws)} new draws.")
            if failed_draws:
                logger.warning(f"⚠️ {len(failed_draws)} draws failed.")
        else:
            logger.info("\n✅ No updates needed. All draws are up to date!")
        
        return 0 if not failed_draws else 1
        
    except Exception as e:
        logger.error(f"❌ Unexpected error: {e}")
        return 1
    finally:
        updater.cleanup()
        logger.info("\n" + "="*70)
        logger.info("PROGRAM COMPLETE")
        logger.info("="*70)


if __name__ == "__main__":
    sys.exit(main())

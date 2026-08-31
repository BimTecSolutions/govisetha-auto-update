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

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


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
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        })
        
    def fetch_page(self, url: str) -> Optional[str]:
        """
        Fetch page content using requests with retries.
        """
        max_retries = 3
        for attempt in range(max_retries):
            try:
                logger.debug(f"Fetching URL: {url} (attempt {attempt + 1}/{max_retries})")
                resp = self.session.get(url, timeout=30)
                
                if resp.status_code == 200:
                    # Check if we got meaningful content
                    if len(resp.text) > 1000:
                        logger.debug(f"Successfully fetched {url} ({len(resp.text)} bytes)")
                        return resp.text
                    else:
                        logger.warning(f"Response too short: {len(resp.text)} bytes")
                else:
                    logger.warning(f"HTTP {resp.status_code} for {url}")
                
                # Wait before retry
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)  # Exponential backoff
                    
            except requests.exceptions.RequestException as e:
                logger.warning(f"Request error (attempt {attempt + 1}): {e}")
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
                else:
                    logger.error(f"Failed to fetch {url} after {max_retries} attempts")
        
        return None

    def get_latest_draw_number(self) -> Optional[int]:
        """
        Get the latest draw number from the NLB website.
        """
        try:
            # Try multiple approaches to find latest draw
            approaches = [
                self._get_latest_from_results_page,
                self._get_latest_from_homepage,
                self._get_latest_from_api
            ]
            
            for approach in approaches:
                result = approach()
                if result:
                    logger.info(f"Found latest draw number: {result}")
                    return result
            
            logger.warning("Could not find latest draw number using any approach")
            return None
            
        except Exception as e:
            logger.error(f"Error getting latest draw: {e}")
            return None
    
    def _get_latest_from_results_page(self) -> Optional[int]:
        """Get latest draw from the results page."""
        url = f"{self.BASE_URL}/results/{self.LOTTERY_SLUG}"
        html = self.fetch_page(url)
        
        if not html:
            return None
        
        soup = BeautifulSoup(html, 'html.parser')
        text = soup.get_text(separator=" ", strip=True)
        
        # Look for draw numbers with various patterns
        patterns = [
            r'(?:Draw|Lottery)\s*(?:No|Number)?\.?\s*:?\s*(\d{3,4})',
            r'Govisetha\s*(?:Draw|Lottery)?\s*(?:No|Number)?\.?\s*:?\s*(\d{3,4})',
            r'Draw\s+(\d{3,4})',
            r'#\s*(\d{3,4})',
            r'Result\s+(\d{3,4})',
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, text, re.I)
            if matches:
                # Get the maximum draw number (latest)
                draw_numbers = [int(m) for m in matches if m.isdigit()]
                if draw_numbers:
                    return max(draw_numbers)
        
        # Also look in links
        for link in soup.find_all('a', href=True):
            href = link['href']
            match = re.search(r'/results/govisetha/(\d{3,4})', href)
            if match:
                return int(match.group(1))
        
        return None
    
    def _get_latest_from_homepage(self) -> Optional[int]:
        """Try to get latest draw from homepage."""
        url = f"{self.BASE_URL}"
        html = self.fetch_page(url)
        
        if not html:
            return None
        
        # Look for links to recent results
        patterns = [
            r'/results/govisetha/(\d{3,4})',
            r'govisetha/(\d{3,4})',
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, html, re.I)
            if matches:
                draw_numbers = [int(m) for m in matches if m.isdigit()]
                if draw_numbers:
                    return max(draw_numbers)
        
        return None
    
    def _get_latest_from_api(self) -> Optional[int]:
        """Try to get latest draw from any API endpoints."""
        # Some sites have hidden API endpoints
        api_urls = [
            f"{self.BASE_URL}/api/results/{self.LOTTERY_SLUG}/latest",
            f"{self.BASE_URL}/api/latest/{self.LOTTERY_SLUG}",
        ]
        
        for url in api_urls:
            try:
                resp = self.session.get(url, timeout=10)
                if resp.status_code == 200:
                    data = resp.json()
                    if 'draw_number' in data:
                        return int(data['draw_number'])
            except:
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
        
        # Find the draw number in the text
        draw_pattern = rf'(?:Draw|Lottery)\s*(?:No|Number)?\.?\s*:?\s*{draw_number}'
        draw_match = re.search(draw_pattern, text, re.I)
        
        if not draw_match:
            # Try with just the number
            draw_pattern = rf'\b{draw_number}\b'
            draw_match = re.search(draw_pattern, text)
            if not draw_match:
                return result
        
        # Get the text around the draw number
        start = max(0, draw_match.start() - 100)
        end = min(len(text), draw_match.end() + 400)
        section = text[start:end]
        
        # Pattern: Letter at the start of a sequence, followed by space and 4 numbers
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
                    return result
        
        # Try with 3 numbers
        pattern = r'\b([A-Z])\s+(\d{1,2})\s+(\d{1,2})\s+(\d{1,2})\b'
        matches = re.findall(pattern, section, re.I)
        
        if matches:
            for match in matches:
                symbol = match[0]
                numbers = list(match[1:4])
                numbers = [n for n in numbers if n and 0 <= int(n) <= 99]
                if len(numbers) >= 3:
                    result["symbol"] = symbol
                    result["numbers"] = [f"{int(n):02d}" for n in numbers[:4]]
                    # Pad with zeros if needed
                    while len(result["numbers"]) < 4:
                        result["numbers"].append("00")
                    result["found"] = True
                    return result
        
        # More flexible pattern for Govisetha format
        # Look for letter followed by numbers
        letter_pattern = r'\b([A-Z])\s+(\d+)\s+(\d+)\s+(\d+)\s*'
        matches = re.findall(letter_pattern, section, re.I)
        
        if matches:
            for match in matches:
                symbol = match[0]
                numbers = [n for n in match[1:4] if n and 0 <= int(n) <= 99]
                if numbers and len(numbers) >= 3:
                    result["symbol"] = symbol
                    result["numbers"] = [f"{int(n):02d}" for n in numbers[:4]]
                    while len(result["numbers"]) < 4:
                        result["numbers"].append("00")
                    result["found"] = True
                    return result
        
        return result

    def extract_draw_date(self, text: str) -> Optional[str]:
        """Extract the draw date from the page."""
        date_patterns = [
            r'(?:Date|Draw Date)\s*:?\s*([A-Za-z]+\s+\d{1,2},?\s+\d{4})',
            r'([A-Za-z]+\s+\d{1,2},?\s+\d{4})',
            r'(\d{1,2}\s+[A-Za-z]+\s+\d{4})',
            r'(\d{4}-\d{2}-\d{2})',
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
                return {
                    "lottery": self.LOTTERY_NAME,
                    "draw_number": draw_str,
                    "date": date,
                    "symbol": extracted["symbol"],
                    "numbers": extracted["numbers"],
                    "url": url,
                    "found": True
                }
            
            # If numbers not found, try looking in specific HTML elements
            # Look for result tables or containers
            result_containers = soup.find_all(['div', 'span', 'p'], class_=re.compile(r'result|winning|number', re.I))
            
            for container in result_containers:
                container_text = container.get_text(separator=" ", strip=True)
                extracted = self.extract_winning_numbers(container_text, draw_str)
                if extracted["found"]:
                    return {
                        "lottery": self.LOTTERY_NAME,
                        "draw_number": draw_str,
                        "date": date,
                        "symbol": extracted["symbol"],
                        "numbers": extracted["numbers"],
                        "url": url,
                        "found": True
                    }
            
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

    def check_and_update(self, max_draws_per_run: int = 5) -> Tuple[List[int], List[int]]:
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
            logger.warning("No existing draws found in Firebase. Starting from draw 4534")
            existing_draws = list(range(4534, min(latest_website + 1, 4540)))
        
        # Determine the range to check
        if existing_draws:
            latest_firebase = max(existing_draws)
            logger.info(f"Latest draw in Firebase: {latest_firebase}")
            
            # If we already have the latest, nothing to do
            if latest_firebase >= latest_website:
                logger.info("✅ All draws are up to date!")
                return [], []
            
            # Start from the next draw after the latest in Firebase
            start_draw = latest_firebase + 1
        else:
            start_draw = 4534  # Default start if no data
        
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
                
                # Small delay between requests
                time.sleep(1.0)
                
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
    logger.info("🏆 GOVISETHA AUTO-UPDATER (Selenium-Free)")
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
        new_draws, failed_draws = updater.check_and_update(max_draws_per_run=5)
        
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

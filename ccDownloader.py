"""
Card Conjurer Selenium Downloader - Canvas Capture Version

Captures card images directly from the canvas using toDataURL and zips them.
Inspired by Tampermonkey direct capture techniques for speed and reliability.

Requirements (install with apt):
- python3-selenium
- python3-pil (Pillow - optional, for image verification if needed, not used for saving here)
- chromium-driver (or google-chrome-stable)
"""

import os
import sys
import time
import json
import logging
import argparse
from datetime import datetime
from pathlib import Path
import zipfile
import base64
import hashlib
from typing import Optional, Tuple

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, ElementClickInterceptedException


class CardConjurerDownloader:
    def __init__(self, url="http://mtgproxy:4242", download_dir=None, log_level=logging.INFO):
        """Initialize the Card Conjurer downloader with logging."""
        self.url = url
        # Download directory is still used for logs and the final ZIP file
        self.download_dir = download_dir or os.path.join(os.path.expanduser("~"), "Downloads", "CardConjurer")
        self.driver = None
        self.cards = []

        self.delays = {
            'page_load': 0.1,
            'tab_switch': 0.1,
            'file_upload_wait': 10.0, 
            'card_load_js_ops': 0.2, # Minimal delay after JS load ops in load_card
            'frame_set': 0.1,
            'element_wait': 3.0, 
            'js_init': 0.1,
            'canvas_render_wait': 1.5 # Wait after load_card for canvas to be ready for capture (Increased from TM's 1.0s for safety)
        }

        Path(self.download_dir).mkdir(parents=True, exist_ok=True)
        self.setup_logging(log_level)
        self.logger.info(f"Initialized CardConjurerDownloader (Canvas Capture Version)")
        self.logger.info(f"URL: {self.url}")
        self.logger.info(f"Output directory (for ZIP and logs): {self.download_dir}")

    def setup_logging(self, log_level):
        log_dir = Path(self.download_dir) / "logs"
        log_dir.mkdir(exist_ok=True)
        self.logger = logging.getLogger('CardConjurer')
        self.logger.setLevel(logging.DEBUG) 
        if self.logger.handlers:
            self.logger.handlers.clear()
        detailed_formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s'
        )
        simple_formatter = logging.Formatter(
            '%(asctime)s - %(levelname)s - %(message)s'
        )
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file = log_dir / f"cardconjurer_{timestamp}.log"
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(detailed_formatter)
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(log_level)
        console_handler.setFormatter(simple_formatter)
        self.logger.addHandler(file_handler)
        self.logger.addHandler(console_handler)
        self.logger.info(f"Logging initialized. Log file: {log_file}")

    def setup_driver(self, headless=False):
        self.logger.info(f"Setting up Chrome driver (headless={headless})")
        chrome_options = Options()
        # No need for download directory prefs for image files anymore
        prefs = {
            "safebrowsing.enabled": False,
        }
        chrome_options.add_experimental_option("prefs", prefs)
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--window-size=1920,1080") # Canvas size can depend on window
        chrome_options.page_load_strategy = 'eager'

        if headless:
            chrome_options.add_argument("--headless=new")
            self.logger.info("Running in headless mode")

        chromedriver_paths = ["/usr/bin/chromedriver", "/usr/local/bin/chromedriver", "chromedriver"]
        chromedriver_path = None
        for path_attempt in chromedriver_paths:
            resolved_path = os.path.expanduser(path_attempt)
            if os.path.exists(resolved_path) or os.system(f"which {resolved_path} > /dev/null 2>&1") == 0:
                chromedriver_path = resolved_path
                self.logger.info(f"Found chromedriver at: {chromedriver_path}")
                break
        if not chromedriver_path:
            self.logger.error("ChromeDriver not found. Please install chromium-driver or ensure chromedriver is in PATH.")
            raise Exception("ChromeDriver not found.")

        service = Service(chromedriver_path)
        self.driver = webdriver.Chrome(service=service, options=chrome_options)
        self.logger.info("Browser setup complete")

    # --- wait_for_element, wait_for_clickable, click_element_safely remain the same ---
    def wait_for_element(self, selector, by=By.CSS_SELECTOR, timeout=None):
        if timeout is None:
            timeout = self.delays['element_wait']
        try:
            return WebDriverWait(self.driver, timeout).until(
                EC.presence_of_element_located((by, selector))
            )
        except TimeoutException:
            self.logger.debug(f"Timeout waiting for element: {by}='{selector}'")
            return None

    def wait_for_clickable(self, selector, by=By.CSS_SELECTOR, timeout=None):
        if timeout is None:
            timeout = self.delays['element_wait']
        try:
            return WebDriverWait(self.driver, timeout).until(
                EC.element_to_be_clickable((by, selector))
            )
        except TimeoutException:
            self.logger.debug(f"Timeout waiting for clickable element: {by}='{selector}'")
            return None

    def click_element_safely(self, element):
        try:
            element.click()
            return True
        except ElementClickInterceptedException:
            self.logger.warning("Element click intercepted, trying JS click.")
            try:
                self.driver.execute_script("arguments[0].scrollIntoView(true);", element)
                time.sleep(0.1)
                self.driver.execute_script("arguments[0].click();", element)
                return True
            except Exception as e_js_click:
                self.logger.error(f"JS click also failed: {e_js_click}")
                return False
        except Exception as e_click:
            self.logger.error(f"Other error clicking element: {e_click}")
            return False
    # --- End of unchanged helper methods ---

    def navigate_to_card_conjurer(self):
        self.logger.info(f"Navigating to Card Conjurer: {self.url}")
        self.driver.get(self.url)
        if self.wait_for_element("canvas", timeout=10): # Primary canvas is key
            self.logger.info("Canvas found, page appears ready.")
            return True
        self.logger.error("Canvas not found after page load. Card Conjurer may not have loaded correctly.")
        return False

    def navigate_to_import_page(self):
        self.logger.info("Navigating to import/save tab...")
        tab_selector = "h3[onclick*='toggleCreatorTabs(event, \"import\")']"
        self.logger.debug(f"Attempting to find import tab button with selector: {tab_selector}")
        import_tab_button = self.wait_for_clickable(tab_selector, timeout=5) 
        if import_tab_button:
            if self.click_element_safely(import_tab_button):
                self.logger.info("Successfully clicked the import tab.")
                time.sleep(self.delays['tab_switch'] + 0.5) 
                verification_selector = "input[type='file']" 
                self.logger.debug(f"Verifying import tab by looking for a visible '{verification_selector}'.")
                try:
                    WebDriverWait(self.driver, 7).until(
                        lambda driver: any(el.is_displayed() for el in driver.find_elements(By.CSS_SELECTOR, verification_selector))
                    )
                    self.logger.info("Import tab active (verified by visible file input).")
                    return True
                except TimeoutException:
                    self.logger.warning(f"Clicked import tab, but NO visible '{verification_selector}' found.")
                    return False 
            else:
                self.logger.error(f"Failed to click the import tab button ({tab_selector}).")
                return False
        else:
            self.logger.error(f"Import tab button ({tab_selector}) not found or not clickable.")
            return False

    def upload_cardconjurer_file(self, file_path):
        self.logger.info(f"Uploading file: {file_path}")
        if not os.path.exists(file_path):
            self.logger.error(f"File not found: {file_path}")
            return False
        if not self.navigate_to_import_page():
            self.logger.error("Failed to navigate to import page for file upload.")
            return False

        self.logger.info("Attempting to find the file input element on the import tab...")
        file_input_selectors = [
            "input#importProject[type='file']", 
            "input[type='file'][accept*='.cardconjurer']", 
            "input[type='file'][oninput*='uploadSavedCards']",
            "input[type='file']", 
        ]
        file_input_element = None
        for selector_type_pass in ["VISIBLE", "HIDDEN"]: # Two passes
            for selector in file_input_selectors:
                self.logger.debug(f"Trying {selector_type_pass} file input selector: {selector}")
                try:
                    elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                    for el in elements:
                        is_el_displayed = el.is_displayed()
                        if (selector_type_pass == "VISIBLE" and not is_el_displayed) or \
                           (selector_type_pass == "HIDDEN" and is_el_displayed):
                            continue # Skip if not matching current pass's visibility requirement

                        el_accept = el.get_attribute('accept') or ""
                        el_oninput = el.get_attribute('oninput') or ""
                        is_specific = ('.cardconjurer' in el_accept or '.txt' in el_accept) or \
                                      ('uploadSavedCards' in el_oninput)
                        
                        if is_specific:
                            file_input_element = el
                            self.logger.info(f"Found specific {selector_type_pass} file input: {selector}")
                            break 
                        elif not file_input_element: # Take first generic one of the current visibility pass
                            file_input_element = el
                            self.logger.info(f"Found generic {selector_type_pass} file input (candidate): {selector}")
                    if file_input_element and \
                       ((('.cardconjurer' in (file_input_element.get_attribute('accept') or "") or '.txt' in (file_input_element.get_attribute('accept') or "" )) or \
                         ('uploadSavedCards' in (file_input_element.get_attribute('oninput') or ""))) and \
                        (file_input_element.is_displayed() if selector_type_pass == "VISIBLE" else True)): # Check if it's a good specific match for this pass
                        break 
                except Exception as e_find:
                    self.logger.debug(f"Error or no elements for {selector_type_pass} selector {selector}: {e_find}")
            if file_input_element: break # Found one, stop passes

        if not file_input_element:
            self.logger.error("Could not find a suitable file input element.")
            return False
        if not file_input_element.is_displayed():
             self.logger.warning(f"Using a HIDDEN file input. Attempting to make it visible.")

        try:
            self.logger.info(f"Using file input: Tag={file_input_element.tag_name}, ID='{file_input_element.get_attribute('id')}', Class='{file_input_element.get_attribute('class')}', Accept='{file_input_element.get_attribute('accept')}', OnInput='{file_input_element.get_attribute('oninput')}'")
            self.driver.execute_script(
                "arguments[0].style.opacity=1; arguments[0].style.display='block'; arguments[0].style.visibility='visible'; arguments[0].disabled=false; arguments[0].removeAttribute('hidden');", 
                file_input_element
            )
            time.sleep(0.2) 
            file_input_element.send_keys(os.path.abspath(file_path)) 
            self.logger.info(f"File path sent to input element.")
        except Exception as e:
            self.logger.error(f"Error sending file path: {e}", exc_info=True)
            return False

        self.logger.info("Waiting for cards to load from file...")
        try:
            WebDriverWait(self.driver, self.delays['file_upload_wait']).until(self.check_cards_loaded)
            self.logger.info("Cards loaded successfully after file upload.")
            return True
        except TimeoutException: # Remainder of this try-except is for debugging upload failure
            self.logger.error("Timeout waiting for cards to load after file upload.")
            try:
                card_select_dbg = self.driver.find_element(By.ID, "load-card-options")
                options_dbg = card_select_dbg.find_elements(By.TAG_NAME, "option")
                valid_options_dbg = [opt.text for opt in options_dbg if opt.text.strip() and opt.text.strip().lower() not in ['none selected', 'load a saved card', '']]
                self.logger.info(f"Debug: Found {len(valid_options_dbg)} cards in dropdown during fail: {valid_options_dbg[:5]}")
            except: self.logger.info("Debug: Could not get card options for debugging during fail.")
            try:
                if self.driver.execute_script("return typeof uploadSavedCards === 'function';"):
                    self.logger.info("'uploadSavedCards' function EXISTS. Failure might be due to event not triggering this handler.")
                else: self.logger.info("'uploadSavedCards' function does NOT exist.") 
            except Exception as e_js_check_upload: self.logger.warning(f"Error checking for 'uploadSavedCards' JS function: {e_js_check_upload}")
            return False

    def check_cards_loaded(self, driver_instance=None): # driver_instance for WebDriverWait lambda if needed
        # This method is used as a callable for WebDriverWait
        driver_to_use = driver_instance if driver_instance else self.driver
        try:
            card_select = driver_to_use.find_element(By.ID, "load-card-options")
            options = card_select.find_elements(By.TAG_NAME, "option")
            valid_options = [opt for opt in options if opt.text.strip() and opt.text.strip().lower() not in ['none selected', 'load a saved card', '']]
            if len(valid_options) > 0:
                self.logger.debug(f"check_cards_loaded: Found {len(valid_options)} cards.")
                return True
        except NoSuchElementException:
            self.logger.debug("check_cards_loaded: 'load-card-options' not found.")
        except Exception as e:
            self.logger.debug(f"check_cards_loaded: Error checking cards: {e}")
        return False
        
    def get_saved_cards(self): # Remains largely the same
        self.logger.info("Getting list of saved cards...")
        try:
            card_select = self.wait_for_element("load-card-options", by=By.ID, timeout=5)
            if not card_select:
                self.logger.error("'load-card-options' select element not found.")
                self.cards = []
                return []
            options = card_select.find_elements(By.TAG_NAME, "option")
            cards_found = []
            for option in options:
                card_name = option.get_attribute("value").strip() 
                if card_name and card_name.lower() not in ['none selected', 'load a saved card', '']:
                    cards_found.append(card_name)
            self.logger.info(f"Found {len(cards_found)} saved cards: {cards_found[:5] if cards_found else 'None'}") 
            self.cards = cards_found
            return cards_found
        except Exception as e:
            self.logger.error(f"Error getting saved cards: {e}")
            self.cards = []
            return []

    def set_auto_frame(self, frame_option): # Remains the same
        if not frame_option: return True
        self.logger.info(f"Setting auto frame to: {frame_option}")
        frame_mapping = {'7th': 'Seventh', 'seventh': 'Seventh', '8th': 'Eighth', 'eighth': 'Eighth', 'm15': 'M15Eighth', 'ub': 'M15EighthUB'}
        dropdown_value = frame_mapping.get(frame_option.lower())
        if not dropdown_value:
            self.logger.error(f"Invalid frame option: {frame_option}.")
            return False
        try:
            select_element = self.wait_for_element("autoFrame", by=By.ID, timeout=5)
            if not select_element: return False
            Select(select_element).select_by_value(dropdown_value)
            self.logger.info(f"Successfully set auto frame to '{dropdown_value}' using Selenium Select.")
            time.sleep(self.delays['frame_set'] + 0.5)
            return True
        except Exception as e: # Fallback to JS
            self.logger.warning(f"Selenium Select for auto frame failed: {e}. Trying JS.")
            try:
                self.driver.execute_script(f"var s=document.getElementById('autoFrame'); s.value='{dropdown_value}'; s.dispatchEvent(new Event('change',{{'bubbles':true}}));")
                self.logger.info(f"Set auto frame via JS fallback.")
                time.sleep(self.delays['frame_set'] + 0.5)
                return True
            except Exception as e_js:
                self.logger.error(f"JS fallback for auto frame also failed: {e_js}")
                return False

    def load_card(self, card_name: str): # Remains the same as last successful version
        self.logger.info(f"Loading card: '{card_name}' using JavaScript method.")
        try:
            if not self.wait_for_element("load-card-options", By.ID, timeout=3): return False
            js_escaped_card_name = json.dumps(card_name)
            start_time = time.perf_counter()
            self.driver.execute_script(f"document.getElementById('load-card-options').value = {js_escaped_card_name};")
            self.logger.debug(f"JS: Set value took {time.perf_counter() - start_time:.4f}s")
            start_time = time.perf_counter()
            self.driver.execute_script(f"var s=document.getElementById('load-card-options'); s.dispatchEvent(new Event('change',{{'bubbles':true}}));")
            change_event_duration = time.perf_counter() - start_time
            self.logger.debug(f"JS: Dispatch 'change' event took {change_event_duration:.4f}s")
            if change_event_duration < 1.0 and self.driver.execute_script("return typeof loadCard === 'function';"):
                start_time = time.perf_counter()
                self.driver.execute_script(f"loadCard({js_escaped_card_name});")
                self.logger.debug(f"JS: Global loadCard() call took {time.perf_counter() - start_time:.4f}s")
            elif change_event_duration >= 1.0 : self.logger.info(f"JS: Dispatch 'change' was slow ({change_event_duration:.4f}s), assumed load handled.")
            time.sleep(self.delays['card_load_js_ops']) 
            self.logger.info(f"JS operations for card load '{card_name}' completed.")
            return True
        except Exception as e:
            self.logger.error(f"Error loading card '{card_name}': {e}", exc_info=True)
            return False

    def capture_card_image_data_from_canvas(self, card_name: str) -> Optional[bytes]:
        """Captures the current card image from the main canvas and returns image bytes."""
        self.logger.info(f"Preparing to capture canvas for: {card_name}")
        
        # Wait for canvas to render after load_card operations
        time.sleep(self.delays['canvas_render_wait'])
        self.logger.debug(f"Waited {self.delays['canvas_render_wait']}s for canvas render of '{card_name}'.")

        js_get_data_url = """
            const canvasSelectors = ['#mainCanvas', '#canvas', 'canvas']; // Try known selectors
            let canvas = null;
            for (let selector of canvasSelectors) {
                canvas = document.querySelector(selector);
                if (canvas) break;
            }
            if (!canvas) {
                console.error('CardConjurer Automation: Canvas element not found for capture.');
                return null;
            }
            try {
                // Check if canvas has non-zero dimensions
                if (canvas.width === 0 || canvas.height === 0) {
                    console.warn('CardConjurer Automation: Canvas has zero dimensions. Capture might be blank.');
                   // return null; // Optionally return null if zero dimensions is an error
                }
                return canvas.toDataURL('image/png');
            } catch (e) {
                console.error('CardConjurer Automation: Error calling toDataURL on canvas:', e);
                return null;
            }
        """
        try:
            self.logger.debug(f"Executing JS to get canvas data URL for '{card_name}'.")
            start_time = time.perf_counter()
            data_url = self.driver.execute_script(js_get_data_url)
            self.logger.debug(f"JS for canvas data URL took {time.perf_counter() - start_time:.4f}s.")

            if data_url and data_url.startswith('data:image/png;base64,'):
                base64_data = data_url.split(',', 1)[1]
                image_bytes = base64.b64decode(base64_data)
                if len(image_bytes) < 1024 : # Basic sanity check for very small/empty image
                    self.logger.warning(f"Captured image for '{card_name}' is very small ({len(image_bytes)} bytes). May be blank or error.")
                else:
                    self.logger.info(f"Successfully captured canvas image data for '{card_name}' ({len(image_bytes)} bytes).")
                return image_bytes
            else:
                self.logger.error(f"Failed to get valid image data URL from canvas for '{card_name}'. Received: {str(data_url)[:100]}")
                # Log any console messages from the browser if possible (requires specific setup)
                # For now, rely on the JS console.error messages.
                return None
        except Exception as e:
            self.logger.error(f"Error capturing canvas image for '{card_name}': {e}", exc_info=True)
            return None

    def create_zip_of_all_cards(self):
        self.logger.info("Starting ZIP creation process (Canvas Capture Method)")
        if not self.cards:
            self.logger.info("Card list is empty, fetching from page...")
            if not (self.driver.current_url.endswith("#import") or self.navigate_to_import_page()):
                self.logger.warning("Could not navigate to import page to get saved cards.")
            self.get_saved_cards()
        
        if not self.cards:
            self.logger.error("No cards found to process for ZIP file.")
            return None
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        zip_filename_path = Path(self.download_dir) / f"CardConjurer_Canvas_Cards_{timestamp}.zip"
        self.logger.info(f"Creating ZIP file: {zip_filename_path}")
        
        successful_cards = 0
        failed_cards = []
        
        try:
            with zipfile.ZipFile(zip_filename_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for i, card_name in enumerate(self.cards):
                    self.logger.info(f"Processing card {i+1}/{len(self.cards)}: '{card_name}'")
                    
                    if not self.load_card(card_name):
                        self.logger.warning(f"Failed to load card: {card_name}")
                        failed_cards.append(f"{card_name} (load failed)")
                        continue
                    
                    image_bytes = self.capture_card_image_data_from_canvas(card_name)
                    
                    if image_bytes:
                        sanitized_arcname = "".join(c for c in card_name if c.isalnum() or c in (' ', '-', '_')).rstrip()
                        # Default to .png as that's what toDataURL('image/png') produces
                        archive_filename = f"{sanitized_arcname}.png" 
                        
                        zipf.writestr(archive_filename, image_bytes)
                        self.logger.info(f"Added '{archive_filename}' to ZIP from canvas data.")
                        successful_cards += 1
                    else:
                        self.logger.warning(f"Failed to capture image data for card: {card_name}")
                        failed_cards.append(f"{card_name} (capture failed)")
        except Exception as e:
            self.logger.error(f"Error during ZIP file creation: {e}", exc_info=True)
            if os.path.exists(zip_filename_path): os.remove(zip_filename_path) # Clean up partial zip
            return None
        
        self.logger.info(f"ZIP creation summary: Successfully processed {successful_cards}/{len(self.cards)} cards.")
        if failed_cards:
            self.logger.warning(f"Failed cards ({len(failed_cards)}): {', '.join(failed_cards)}")
        
        return str(zip_filename_path) if successful_cards > 0 else None

    def run(self, cardconjurer_file=None, action="zip", headless=False, frame=None): # action arg retained for structure
        self.logger.info(f"Starting run (Canvas Capture) with action: {action}, headless: {headless}, frame: {frame}")
        try:
            self.setup_driver(headless=headless)
            if not self.navigate_to_card_conjurer(): return
            time.sleep(self.delays['js_init'])
            if frame and not self.set_auto_frame(frame):
                self.logger.warning(f"Failed to set auto frame to '{frame}'. Continuing...")
            if cardconjurer_file and not self.upload_cardconjurer_file(cardconjurer_file):
                self.logger.error(f"Failed to upload/load cards from file: {cardconjurer_file}. Aborting.")
                return
            # If no file, check for existing cards
            elif not cardconjurer_file:
                self.logger.info("No .cardconjurer file provided. Checking for already loaded cards...")
                on_import = "#import" in self.driver.current_url or self.navigate_to_import_page()
                if on_import and not self.check_cards_loaded(): self.logger.warning("No cards loaded (checked dropdown).")
                elif not on_import: self.logger.warning("Cannot check loaded cards, import page nav failed.")

            if action == "zip":
                if not self.cards: self.get_saved_cards() # get_saved_cards handles nav if needed
                if not self.cards:
                    self.logger.error("No cards available to zip.")
                    return
                result_zip_path = self.create_zip_of_all_cards()
                if result_zip_path: self.logger.info(f"Successfully created ZIP: {result_zip_path}")
                else: self.logger.error("Failed to create ZIP file or ZIP is empty.")
            
        except Exception as e:
            self.logger.error(f"Unhandled error during execution: {e}", exc_info=True)
        finally:
            if self.driver:
                if not headless and sys.stdin.isatty():
                    try: input("\nPress Enter to close the browser...")
                    except EOFError: self.logger.info("Non-interactive, closing browser.")
                self.driver.quit()
                self.logger.info("Browser closed.")


def main():
    parser = argparse.ArgumentParser(description='Card Conjurer Downloader - Canvas Capture Version')
    parser.add_argument('--file', '-f', required=True, help='Path to .cardconjurer file to load')
    parser.add_argument('--url', default='http://mtgproxy:4242', help='Card Conjurer URL')
    parser.add_argument('--output', default=None, help='Output directory for ZIP and logs')
    parser.add_argument('--headless', action='store_true', help='Run in headless mode')
    parser.add_argument('--frame', choices=['7th', 'seventh', '8th', 'eighth', 'm15', 'ub'], help='Auto frame setting')
    parser.add_argument('--log-level', default='INFO', choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'], help='Console logging level')
    
    args = parser.parse_args()
    if not os.path.exists(args.file):
        print(f"Error: File not found: {args.file}"); sys.exit(1)
    
    log_level_val = getattr(logging, args.log_level.upper(), logging.INFO)
    downloader = CardConjurerDownloader(url=args.url, download_dir=args.output, log_level=log_level_val)
    downloader.run(cardconjurer_file=args.file, headless=args.headless, frame=args.frame)

if __name__ == "__main__":
    main()
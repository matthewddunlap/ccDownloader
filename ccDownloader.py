# --- ccDownloader.py ---
"""
Card Conjurer Selenium Downloader - Smart Canvas Capture Version (v7.1 - Auto-Retry File Generation)

Captures card images directly from the canvas using toDataURL.
Can either save images to a local directory (via a temporary zip) or upload them directly to a WebDAV server.
Includes:
- Runs in Incognito mode for a clean slate each time.
- Enhanced post-upload priming: handles general first card quirk and {flavor} text rendering.
- Optional features for art and set symbol manipulation.
- Set Symbol Override now always uses live rarity, populating separate fields.
- Filename format: [name-with-dashes]_[set]_[number].png
- NEW: Automatically generates a .cardconjurer file for any failed cards, ready for a retry run.
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
from typing import Optional, Tuple, Dict, List

# --- Add requests dependency for uploading ---
# Note: This script now requires the 'requests' library for the upload feature.
# Install it using: pip install requests
try:
    import requests
except ImportError:
    print("Error: The 'requests' library is required for the --upload-to-server feature.")
    print("Please install it using: pip install requests")
    sys.exit(1)
# --- END ---

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, ElementClickInterceptedException

# --- Web Server Upload Functions (from MtgPng2Pdf.py) ---
def check_server_file_exists(url: str, debug: bool = False) -> bool:
    """Check if a file already exists at a given URL using a HEAD request."""
    if not url:
        return False
    if debug:
        print(f"DEBUG: Checking for file existence at: {url}")
    try:
        r = requests.head(url, timeout=15, allow_redirects=True)
        if r.status_code == 200:
            if debug: print(f"DEBUG: File exists (200 OK) at {url}")
            return True
        if r.status_code == 404:
            if debug: print(f"DEBUG: File not found (404) at {url}")
            return False
        print(f"Warning: Received status {r.status_code} when checking {url}. Assuming it does not exist.")
        return False
    except requests.exceptions.RequestException as e:
        print(f"Warning: Network error while checking {url}: {e}. Assuming it does not exist.")
        return False

def upload_file_to_server(url: str, file_bytes: bytes, mime_type: str, debug: bool = False) -> bool:
    """Uploads file content (bytes) to a server URL using PUT."""
    if not url:
        print("Error: Cannot upload file, server URL is not configured.")
        return False
    if not file_bytes:
        print("Warning: No file content (bytes) to upload.")
        return False

    print(f"Uploading to: {url}")
    headers = {'Content-Type': mime_type}
    try:
        r = requests.put(url, data=file_bytes, headers=headers, timeout=60)
        r.raise_for_status()  # Raises an exception for 4xx/5xx status codes
        if 200 <= r.status_code < 300:
            print(f"Successfully uploaded. URL: {url}")
            return True
        else:
            print(f"Error: Upload failed with status {r.status_code}.")
            if r.text: print(f"Server Response: {r.text}")
            return False
    except requests.exceptions.RequestException as e:
        print(f"Error: Upload failed due to a network error: {e}")
        if e.response is not None:
            print(f"Server Response Body: {e.response.text}")
        return False
# --- END ---

class CardConjurerDownloader:
    # --- MODIFIED: __init__ to accept server args and new attributes ---
    def __init__(self, url="https://cardconjurer.app:443", output_dir=None, log_level=logging.INFO, **kwargs):
        self.url = url
        self.output_dir = output_dir or os.path.join(os.path.expanduser("~"), "Downloads", "CardConjurer")
        self.driver = None
        self.cards = []
        self.parsed_card_data_map: Dict[str, Dict] = {}
        self._current_active_tab: Optional[str] = None 

        # --- NEW: Attributes for failed card file generation ---
        self.full_card_list_from_file: List[Dict] = []
        self.failed_card_keys: List[str] = []

        # Optional features
        self.auto_fit_art_enabled = False
        self.auto_fit_set_symbol_enabled = False
        self.set_symbol_override_code = None

        # --- Server upload attributes ---
        self.upload_to_server = kwargs.get('upload_to_server', False)
        self.image_server_base_url = kwargs.get('image_server_base_url', None)
        self.output_server_path = kwargs.get('output_server_path', None)
        self.overwrite_server_file = kwargs.get('overwrite_server_file', False)
        self.debug_mode = log_level == logging.DEBUG

        self.delays = {
            'page_load': 0.1, 'tab_switch': 0.1, 'file_upload_wait': 10.0, 
            'card_load_js_ops': 0.2, 'frame_set': 0.1, 'element_wait': 3.0, 
            'js_init': 0.1, 'canvas_stabilize_timeout': 15.0,
            'canvas_stability_checks': 3, 'canvas_stability_interval': 0.33,
            'art_fit_wait': 0.75, 'set_symbol_reset_wait': 0.75,  
            'set_symbol_fetch_wait': 1.5   
        }

        Path(self.output_dir).mkdir(parents=True, exist_ok=True)
        self.setup_logging(log_level)
        self.logger.info(f"Initialized CC Downloader (v7.1 - Auto-Retry File Generation)")
        self.logger.info(f"URL: {self.url}")
        if self.upload_to_server:
            self.logger.info(f"UPLOAD MODE: Enabled. Target server: {self.image_server_base_url}, Path: {self.output_server_path}")
        else:
            self.logger.info(f"LOCAL MODE: Output directory: {self.output_dir}")

    def setup_logging(self, log_level):
        log_dir = Path(self.output_dir) / "logs"
        log_dir.mkdir(exist_ok=True)
        self.logger = logging.getLogger('CardConjurer')
        self.logger.setLevel(logging.DEBUG) 
        if self.logger.handlers: self.logger.handlers.clear()
        dt_fmt = '%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s'
        s_fmt = '%(asctime)s - %(levelname)s - %(message)s'
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_fn = log_dir / f"cc_v7.1_retry_file_{ts}.log"
        fh = logging.FileHandler(log_fn); fh.setLevel(logging.DEBUG); fh.setFormatter(logging.Formatter(dt_fmt))
        ch = logging.StreamHandler(sys.stdout); ch.setLevel(log_level); ch.setFormatter(logging.Formatter(s_fmt))
        self.logger.addHandler(fh); self.logger.addHandler(ch)
        self.logger.info(f"Logging to: {log_fn}")

    # ... (setup_driver to navigate_to_card_conjurer are unchanged) ...
    def setup_driver(self, headless=False):
        self.logger.info(f"Setting up Chrome driver (headless={headless}) in INCOGNITO mode.")
        chrome_options = Options()
        chrome_options.add_argument("--incognito") 
        prefs = {"safebrowsing.enabled": False}
        chrome_options.add_experimental_option("prefs", prefs)
        chrome_options.add_argument("--no-sandbox"); chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--window-size=1920,1080"); chrome_options.page_load_strategy='eager'
        if headless: chrome_options.add_argument("--headless=new"); self.logger.info("Running in headless mode")
        
        chromedriver_paths = ["/usr/bin/chromedriver", "/usr/local/bin/chromedriver", "chromedriver"]
        chromedriver_path = next((os.path.expanduser(p) for p in chromedriver_paths if os.path.exists(os.path.expanduser(p)) or os.system(f"which {os.path.expanduser(p)} > /dev/null 2>&1") == 0), None)
        if not chromedriver_path: self.logger.error("ChromeDriver not found."); raise Exception("ChromeDriver not found.")
        self.logger.info(f"Found chromedriver at: {chromedriver_path}"); service = Service(chromedriver_path)
        self.driver = webdriver.Chrome(service=service, options=chrome_options)
        self.logger.info("Browser setup complete (Incognito).")

    def wait_for_element(self, selector, by=By.CSS_SELECTOR, timeout=None):
        timeout = timeout or self.delays['element_wait']
        try: return WebDriverWait(self.driver, timeout).until(EC.presence_of_element_located((by, selector)))
        except TimeoutException: self.logger.debug(f"Timeout: Elem {by}='{selector}'"); return None

    def wait_for_clickable(self, selector, by=By.CSS_SELECTOR, timeout=None):
        timeout = timeout or self.delays['element_wait']
        try: return WebDriverWait(self.driver, timeout).until(EC.element_to_be_clickable((by, selector)))
        except TimeoutException: self.logger.debug(f"Timeout: Clickable {by}='{selector}'"); return None

    def click_element_safely(self, element):
        try: element.click(); return True
        except ElementClickInterceptedException:
            self.logger.warning("Click intercepted, JS fallback.");tl=0.1
            try:self.driver.execute_script("arguments[0].scrollIntoView(true);",element);time.sleep(tl);self.driver.execute_script("arguments[0].click();",element);return True
            except Exception as e: self.logger.error(f"JS click fail: {e}"); return False
        except Exception as e: self.logger.error(f"Other click error: {e}"); return False

    def _navigate_to_creator_tab(self, target_tab_name: str) -> bool:
        if self._current_active_tab == target_tab_name:
            self.logger.debug(f"Already on '{target_tab_name}' tab.")
            return True
        self.logger.info(f"Navigating to '{target_tab_name}' tab...")
        tab_selector = f"h3[onclick*='toggleCreatorTabs(event, \"{target_tab_name}\")']"
        tab_button = self.wait_for_clickable(tab_selector, timeout=3)
        if tab_button and self.click_element_safely(tab_button):
            self.logger.info(f"Clicked '{target_tab_name}' tab.")
            self._current_active_tab = target_tab_name
            time.sleep(self.delays['tab_switch'] + 0.3) 
            return True
        self.logger.error(f"'{target_tab_name}' tab button ({tab_selector}) not found/clickable."); self._current_active_tab=None; return False

    def navigate_to_card_conjurer(self):
        self.logger.info(f"Navigating to: {self.url}"); self.driver.get(self.url)
        if self.wait_for_element("canvas",timeout=10):
            self.logger.info("Canvas found, page ready."); self._current_active_tab="art"; return True 
        self.logger.error("Canvas not found."); return False

    # --- MODIFIED: Now also stores the full original card list ---
    def _parse_cardconjurer_file_content(self, file_path: str) -> bool:
        self.logger.info(f"Parsing .cardconjurer file content from: {file_path}")
        self.parsed_card_data_map.clear()
        self.full_card_list_from_file.clear()
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                full_data_from_file = json.load(f) 
            
            card_list_to_parse = []
            if isinstance(full_data_from_file, list):
                card_list_to_parse = full_data_from_file
            elif isinstance(full_data_from_file, dict) and "key" in full_data_from_file: # Handle case where file is single card obj
                card_list_to_parse = [full_data_from_file]
            else:
                self.logger.error(f"Unsupported .cardconjurer structure in {file_path}. Expected a JSON list of card objects or a single card object with a 'key'.")
                return False

            # --- NEW: Store the original full list for potential filtering later ---
            self.full_card_list_from_file = card_list_to_parse

            name_key_in_file = "key" # As per example, this is the main card identifier

            for card_obj_wrapper in card_list_to_parse:
                if not isinstance(card_obj_wrapper, dict):
                    self.logger.warning(f"Skipping non-dict item in card list: {str(card_obj_wrapper)[:100]}")
                    continue
                if name_key_in_file in card_obj_wrapper:
                    card_name_val = card_obj_wrapper[name_key_in_file]
                    if "data" in card_obj_wrapper and isinstance(card_obj_wrapper["data"], dict):
                        self.parsed_card_data_map[card_name_val] = card_obj_wrapper["data"]
                    else:
                        self.logger.warning(f"Card '{card_name_val}' in {file_path} is missing 'data' block or 'data' is not a dict.")
                else:
                    self.logger.warning(f"Card object in {file_path} missing '{name_key_in_file}'. Cannot map for data access. Object: {str(card_obj_wrapper)[:100]}")
            
            self.logger.info(f"Parsed and mapped data for {len(self.parsed_card_data_map)} card objects from file.")
            return True
        except json.JSONDecodeError as e:
            self.logger.error(f"JSON decode error parsing {file_path}: {e}"); return False
        except Exception as e:
            self.logger.error(f"Error reading/parsing {file_path}: {e}", exc_info=True); return False

    # ... (upload_cardconjurer_file to _generate_filename are unchanged) ...
    def upload_cardconjurer_file(self, file_path: str) -> bool:
        self.logger.info(f"Starting file upload process for: {file_path}")
        if not os.path.exists(file_path): 
            self.logger.error(f"File not found: {file_path}"); return False
        if not self._navigate_to_creator_tab("import"):
            self.logger.error("Upload: Navigation to import tab failed before sending keys."); return False

        self.logger.info("Attempting to find the file input element on the import tab...")
        file_input_selectors = [
            "input#importProject[type='file']", "input[type='file'][accept*='.cardconjurer']", 
            "input[type='file'][oninput*='uploadSavedCards']", "input[type='file']", 
        ]
        file_input_element = None; found_specific_visible = False
        for pass_type in ["VISIBLE", "HIDDEN"]: 
            candidate_el_for_pass = None 
            for selector in file_input_selectors:
                self.logger.debug(f"Trying {pass_type} file input selector: {selector}")
                try:
                    elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                    for el in elements:
                        is_el_displayed = el.is_displayed()
                        if (pass_type == "VISIBLE" and not is_el_displayed) or \
                           (pass_type == "HIDDEN" and is_el_displayed and file_input_element and file_input_element.is_displayed()): 
                            continue
                        el_accept = el.get_attribute('accept') or ""; el_oninput = el.get_attribute('oninput') or ""
                        is_specific = ('.cardconjurer' in el_accept or '.txt' in el_accept) or ('uploadSavedCards' in el_oninput)
                        if is_el_displayed:
                            if is_specific: candidate_el_for_pass = el; found_specific_visible = True; break 
                            elif not candidate_el_for_pass: candidate_el_for_pass = el 
                        elif pass_type == "HIDDEN" and not found_specific_visible: 
                            if is_specific: 
                                if not candidate_el_for_pass or not ((candidate_el_for_pass.get_attribute('accept') or "").startswith('.')): 
                                     candidate_el_for_pass = el
                            elif not candidate_el_for_pass : candidate_el_for_pass = el 
                except Exception as e_find: self.logger.debug(f"Error finding {pass_type} selector {selector}: {e_find}")
                if candidate_el_for_pass and is_specific and (candidate_el_for_pass.is_displayed() if pass_type == "VISIBLE" else True): break 
            if candidate_el_for_pass: file_input_element = candidate_el_for_pass
            if found_specific_visible: break 
            if file_input_element and file_input_element.is_displayed() and not is_specific and pass_type == "VISIBLE": break 

        if not file_input_element:
            self.logger.error("Could not find a suitable file input element on the import tab."); return False
        if not file_input_element.is_displayed():
             self.logger.warning(f"Using a HIDDEN file input element. Attempting to make it visible for interaction.")
        try:
            self.logger.info(f"Using file input: Tag={file_input_element.tag_name}, ID='{file_input_element.get_attribute('id')}', Class='{file_input_element.get_attribute('class')}'")
            self.driver.execute_script("arguments[0].style.opacity=1;arguments[0].style.display='block';arguments[0].style.visibility='visible';arguments[0].disabled=false;arguments[0].removeAttribute('hidden');", file_input_element)
            time.sleep(0.2); file_input_element.send_keys(os.path.abspath(file_path)); self.logger.info(f"File path sent.")
        except Exception as e: self.logger.error(f"Error sending file path: {e}", exc_info=True); return False
        
        self.logger.info("Waiting for cards to load from file...")
        try:
            WebDriverWait(self.driver, self.delays['file_upload_wait']).until(self.check_cards_loaded) 
            self.logger.info("Cards loaded successfully after file upload.")
            self._current_active_tab = "import" 
            return True
        except TimeoutException: 
            self.logger.error("Timeout waiting for cards to load after file upload.")
            try:
                card_select_dbg = self.driver.find_element(By.ID, "load-card-options")
                options_dbg = card_select_dbg.find_elements(By.TAG_NAME, "option")
                valid_options_dbg = [opt.text for opt in options_dbg if opt.text.strip() and opt.text.strip().lower() not in ['none selected', 'load a saved card', '']]
                self.logger.info(f"Debug: Found {len(valid_options_dbg)} cards in dropdown during fail: {valid_options_dbg[:5]}")
            except: self.logger.info("Debug: Could not get card options for debugging during fail.")
            try:
                if self.driver.execute_script("return typeof uploadSavedCards === 'function';"):
                    self.logger.info("'uploadSavedCards' function EXISTS. Failure might be due to event not triggering.")
                else: self.logger.info("'uploadSavedCards' function does NOT exist.") 
            except Exception as e_js: self.logger.warning(f"Error checking for 'uploadSavedCards' JS function: {e_js}")
            return False

    def check_cards_loaded(self, driver_instance=None) -> bool:
        driver_to_use = driver_instance if driver_instance else self.driver
        try:
            card_select = driver_to_use.find_element(By.ID, "load-card-options")
            options = card_select.find_elements(By.TAG_NAME, "option")
            return any(opt.text.strip() and opt.text.strip().lower() not in ['none selected', 'load a saved card', ''] for opt in options)
        except NoSuchElementException: self.logger.debug("check_cards_loaded: 'load-card-options' not found."); return False
        except Exception as e: self.logger.debug(f"check_cards_loaded: Error: {e}"); return False
        
    def get_saved_cards(self) -> list:
        self.logger.info("Getting list of saved cards...")
        self.cards = [] 
        if not self._navigate_to_creator_tab("import"):
            self.logger.error("Cannot navigate to 'import' tab for get_saved_cards."); return []
        try:
            card_select = self.wait_for_element("load-card-options", by=By.ID, timeout=5)
            if not card_select: self.logger.error("'load-card-options' select element not found."); return []
            options = card_select.find_elements(By.TAG_NAME, "option")
            # The 'value' attribute of the options is what load_card uses.
            cards_found = [opt.get_attribute("value").strip() for opt in options if opt.get_attribute("value").strip() and opt.get_attribute("value").strip().lower() not in ['none selected', 'load a saved card', '']]
            self.logger.info(f"Found {len(cards_found)} saved cards (dropdown values): {cards_found[:5] if cards_found else 'None'}") 
            self.cards = cards_found; return cards_found
        except Exception as e: self.logger.error(f"Error getting saved cards: {e}", exc_info=True); return []

    def set_auto_frame(self, frame_option: str) -> bool:
        if not frame_option: return True 
        self.logger.info(f"Setting auto frame to: {frame_option}")
        if self._current_active_tab != "art": 
            self.logger.debug("Ensuring 'art' tab is active for set_auto_frame.")
            if not self._navigate_to_creator_tab("art"):
                 self.logger.warning("Cannot navigate to 'art' for set_auto_frame. It might fail.")
        frame_mapping = {'7th': 'Seventh', 'seventh': 'Seventh', '8th': 'Eighth', 'eighth': 'Eighth', 'm15': 'M15Eighth', 'ub': 'M15EighthUB'}
        dropdown_value = frame_mapping.get(frame_option.lower())
        if not dropdown_value: self.logger.error(f"Invalid frame option: {frame_option}."); return False
        try:
            self.logger.debug(f"Attempting to set auto frame to '{dropdown_value}' using Selenium Select.")
            select_element = self.wait_for_element("autoFrame", by=By.ID, timeout=5)
            if not select_element: self.logger.error("autoFrame select not found."); return False
            Select(select_element).select_by_value(dropdown_value)
            self.logger.info(f"Set auto frame to '{dropdown_value}' via Select."); time.sleep(self.delays['frame_set'] + 0.5); return True
        except Exception as e: 
            self.logger.warning(f"Select for auto frame failed: {e}. Trying JS.");
            try:
                self.driver.execute_script(f"var s=document.getElementById('autoFrame');s.value='{dropdown_value}';s.dispatchEvent(new Event('change',{{'bubbles':true}}));")
                self.logger.info(f"Set auto frame to '{dropdown_value}' via JS."); time.sleep(self.delays['frame_set'] + 0.5); return True
            except Exception as e_js: self.logger.error(f"JS for auto frame failed: {e_js}"); return False

    def load_card(self, card_name: str) -> bool:
        self.logger.info(f"Loading card: '{card_name}' using JavaScript method.")
        # Assumes 'import' tab is active.
        try:
            card_select_el = self.wait_for_element("load-card-options", By.ID, timeout=3)
            if not card_select_el: self.logger.error("'load-card-options' not found."); return False
            js_card = json.dumps(card_name) # card_name is from option.value, should be safe
            t=time.perf_counter(); self.driver.execute_script(f"document.getElementById('load-card-options').value = {js_card};"); self.logger.debug(f"JS: Set value took {time.perf_counter() - t:.4f}s")
            t=time.perf_counter(); self.driver.execute_script(f"var s=document.getElementById('load-card-options'); s.dispatchEvent(new Event('change',{{'bubbles':true}}));"); dur=time.perf_counter()-t; self.logger.debug(f"JS: Dispatch 'change' took {dur:.4f}s")
            if dur < 1.0 and self.driver.execute_script("return typeof loadCard === 'function';"):
                t=time.perf_counter(); self.driver.execute_script(f"loadCard({js_card});"); self.logger.debug(f"JS: Global loadCard() call took {time.perf_counter() - t:.4f}s")
            elif dur >= 1.0 : self.logger.info(f"JS: Dispatch 'change' was slow ({dur:.4f}s), assumed load handled.")
            time.sleep(self.delays['card_load_js_ops']); self.logger.info(f"JS operations for card load '{card_name}' completed."); return True
        except Exception as e: self.logger.error(f"Error loading card '{card_name}': {e}", exc_info=True); return False

    def get_live_rarity_from_page(self) -> Optional[str]:
        self.logger.info("Attempting to get live rarity from 'Collector' tab...")
        if not self._navigate_to_creator_tab("bottomInfo"): 
            self.logger.error("Failed to navigate to 'Collector' (bottomInfo) tab to get rarity."); return None
        rarity_input_selector = "input#info-rarity"
        rarity_input_element = self.wait_for_element(rarity_input_selector, timeout=3)
        if rarity_input_element:
            try:
                live_rarity_value = rarity_input_element.get_attribute("value")
                self.logger.info(f"Retrieved live rarity value from Collector tab: '{live_rarity_value}'"); return live_rarity_value
            except Exception as e: self.logger.error(f"Error getting value from rarity input ({rarity_input_selector}): {e}"); return None
        self.logger.error(f"Rarity input field ('{rarity_input_selector}') not found on 'Collector' tab."); return None

    def apply_auto_fit_art(self) -> bool:
        self.logger.info("Applying Auto Fit Art...")
        if not self._navigate_to_creator_tab("art"): return False
        button_selector = "button.input[onclick='autoFitArt();']"; auto_fit_button = self.wait_for_clickable(button_selector, timeout=3)
        if auto_fit_button and self.click_element_safely(auto_fit_button):
            self.logger.info("Clicked 'Auto Fit Art' button."); time.sleep(self.delays['art_fit_wait']); return True
        self.logger.error(f"'Auto Fit Art' button ({button_selector}) not found/clickable."); return False

    def apply_auto_fit_set_symbol(self) -> bool:
        self.logger.info("Applying Reset Set Symbol (Auto Fit)...")
        if not self._navigate_to_creator_tab("setSymbol"): return False
        button_selector = "button.input[onclick='resetSetSymbol();']"; reset_button = self.wait_for_clickable(button_selector, timeout=3)
        if reset_button and self.click_element_safely(reset_button):
            self.logger.info("Clicked 'Reset Set Symbol' button."); time.sleep(self.delays['set_symbol_reset_wait']); return True
        self.logger.error(f"'Reset Set Symbol' button ({button_selector}) not found/clickable."); return False

    def apply_set_symbol_override(self, base_set_code: str) -> bool:
        self.logger.info(f"Applying Set Symbol Override for code: '{base_set_code}' (will use live rarity).")
        live_rarity = self.get_live_rarity_from_page() # Navigates to 'bottomInfo'
        target_rarity_val = None
        if live_rarity is not None and live_rarity.strip(): target_rarity_val = live_rarity.strip().upper(); self.logger.info(f"Using live rarity '{target_rarity_val}'.")
        elif live_rarity == "": self.logger.warning("Live rarity empty; rarity field not explicitly set.")
        else: self.logger.warning("Could not get live rarity; rarity field not explicitly set.")
        
        if not self._navigate_to_creator_tab("setSymbol"): self.logger.error("Failed nav to 'Set Symbol' for override."); return False
        
        code_input_el = self.wait_for_element("input#set-symbol-code", timeout=3)
        if not code_input_el: self.logger.error("Set code input ('input#set-symbol-code') not found."); return False
        try:
            self.click_element_safely(code_input_el); code_input_el.clear(); code_input_el.send_keys(base_set_code)
            self.logger.info(f"Set 'set-symbol-code' to '{base_set_code}'.")
            self.driver.execute_script("arguments[0].dispatchEvent(new Event('change',{bubbles:true}));", code_input_el)
        except Exception as e: self.logger.error(f"Error with set code input: {e}"); return False
        
        if target_rarity_val:
            rarity_input_el = self.wait_for_element("input#set-symbol-rarity", timeout=3)
            if not rarity_input_el: self.logger.error("Set rarity input ('input#set-symbol-rarity') not found on Set Symbol tab.")
            else:
                try:
                    self.click_element_safely(rarity_input_el); rarity_input_el.clear(); rarity_input_el.send_keys(target_rarity_val)
                    self.logger.info(f"Set 'set-symbol-rarity' to '{target_rarity_val}'.")
                    self.driver.execute_script("arguments[0].dispatchEvent(new Event('change',{bubbles:true}));", rarity_input_el)
                except Exception as e: self.logger.error(f"Error with set rarity input: {e}")
        else: self.logger.info("No valid live rarity; 'set-symbol-rarity' not explicitly modified.")
        
        self.logger.info("Set symbol override ops complete. Waiting for fetch..."); time.sleep(self.delays['set_symbol_fetch_wait']); return True

    def wait_for_canvas_change_and_stabilization(self, initial_data_url_hash: Optional[str]) -> Optional[str]:
        self.logger.debug(f"Waiting for canvas to change (from hash: {str(initial_data_url_hash)[:10] if initial_data_url_hash else 'None'}) and stabilize...")
        start_time = time.perf_counter(); timeout = self.delays['canvas_stabilize_timeout']
        stability_checks_needed = self.delays['canvas_stability_checks']; interval = self.delays['canvas_stability_interval']
        js_get_data_url = """
            const cSels=['#mainCanvas','#canvas','canvas'];let c=null;for(let s of cSels){c=document.querySelector(s);if(c)break;}
            if(!c||c.width===0||c.height===0)return 'canvas_error:no_canvas_or_zero_dims';
            try{return c.toDataURL('image/png');}catch(e){console.error('CC Automation: Err toDataURL:',e);return 'canvas_error:to_data_url_failed';}"""
        last_hash = initial_data_url_hash; current_hash = None; stable_count = 0
        changed_from_initial = False if initial_data_url_hash is not None else True 
        first_valid_hash_obtained_this_call = False

        while time.perf_counter() - start_time < timeout:
            try:
                current_data_url = self.driver.execute_script(js_get_data_url)
                if isinstance(current_data_url, str) and current_data_url.startswith('canvas_error:'):
                    self.logger.warning(f"Canvas JS err: {current_data_url}");time.sleep(interval);continue
                if not current_data_url: self.logger.debug("Canvas dataURL null.");time.sleep(interval);continue
                current_hash = hashlib.md5(current_data_url.encode('utf-8')).hexdigest()
                if not first_valid_hash_obtained_this_call: 
                    last_hash = current_hash 
                    first_valid_hash_obtained_this_call = True
                    self.logger.debug(f"Canvas obtained first hash for this check: {current_hash[:10]}...")
                    if initial_data_url_hash is None: stable_count = 1 
            except Exception as e: self.logger.warning(f"Py ex get/hash canvas: {e}");time.sleep(interval);continue

            if not first_valid_hash_obtained_this_call: time.sleep(interval); continue 

            if initial_data_url_hash is not None: 
                if not changed_from_initial:
                    if current_hash != initial_data_url_hash:
                        self.logger.debug(f"Canvas changed from initial. New hash: {current_hash[:10]}...")
                        changed_from_initial = True; last_hash = current_hash; stable_count = 1
                    else: self.logger.debug(f"Canvas same as initial ({str(initial_data_url_hash)[:10]})."); stable_count = 0 
            
            if changed_from_initial:
                if current_hash == last_hash: 
                    stable_count += 1; self.logger.debug(f"Canvas hash stabilized ({stable_count}/{stability_checks_needed}): {current_hash[:10]}...")
                else: 
                    last_hash_str = str(last_hash[:10]) if last_hash else "None" 
                    self.logger.debug(f"Canvas hash changed: {current_hash[:10]} from {last_hash_str}. Reset."); stable_count = 1
                last_hash = current_hash
                if stable_count >= stability_checks_needed:
                    if initial_data_url_hash is not None and current_hash == initial_data_url_hash:
                        self.logger.warning(f"Canvas stabilized to SAME hash as initial ({initial_data_url_hash[:10]}). No change detected.")
                    else:
                        self.logger.info(f"Canvas stabilized to new hash: {current_hash[:10]}."); return current_hash
            time.sleep(interval)
        self.logger.warning("Timeout waiting for canvas to stabilize."); return None

    def capture_card_image_data_from_canvas(self, card_name: str, previous_canvas_hash: Optional[str]) -> Tuple[Optional[bytes], Optional[str]]:
        self.logger.info(f"Preparing to capture canvas for: {card_name}")
        new_stabilized_hash = self.wait_for_canvas_change_and_stabilization(previous_canvas_hash)
        
        if not new_stabilized_hash:
            self.logger.error(f"Canvas did not stabilize for '{card_name}'. Previous hash: {str(previous_canvas_hash)[:10]}")
            return None, previous_canvas_hash 
        if previous_canvas_hash and new_stabilized_hash == previous_canvas_hash:
            self.logger.warning(f"Canvas stabilized but to the SAME hash as previous for '{card_name}': {new_stabilized_hash[:10]}. Capturing current state anyway.")

        js_get_data_url = """
            const cSels=['#mainCanvas','#canvas','canvas']; let c=null; for(let s of cSels){c=document.querySelector(s);if(c)break;}
            if(!c||c.width===0||c.height===0)return null; try{return c.toDataURL('image/png');}catch(e){return 'error';}"""
        try:
            start_time_capture = time.perf_counter()
            data_url=self.driver.execute_script(js_get_data_url)
            self.logger.debug(f"JS FINAL canvas data URL call took: {time.perf_counter()-start_time_capture:.4f}s.")
            if data_url and data_url.startswith('data:image/png;base64,'):
                img_bytes = base64.b64decode(data_url.split(',',1)[1]); self.logger.info(f"Captured FINAL canvas for '{card_name}' ({len(img_bytes)} bytes)."); return img_bytes, new_stabilized_hash
            self.logger.error(f"Failed FINAL dataURL for '{card_name}'. Rx: {str(data_url)[:100]}"); return None, new_stabilized_hash 
        except Exception as e: self.logger.error(f"Error capturing FINAL canvas for '{card_name}': {e}",exc_info=True); return None, new_stabilized_hash

    def _generate_filename(self, card_name: str) -> str:
        """
        Generates a sanitized, lowercase filename based on card name, set, and collector number.
        Format: [card-name]_[set-code]_[collector-number].png
        Example: izzet-boilerworks_2x2_408.png
        
        Note: card_name parameter is the dropdown identifier, but we extract the actual
        card name from the CardConjurer data structure to avoid duplication.
        """
        # Default values if data is missing
        set_code_default = 'noset'
        collector_number_default = 'nonum'
        actual_card_name_default = 'unknown'
    
        set_code = set_code_default
        collector_number = collector_number_default
        actual_card_name = actual_card_name_default
    
        # Retrieve card-specific data from the parsed map
        card_data = self.parsed_card_data_map.get(card_name)
        if card_data:
            # Extract actual card name from CardConjurer data structure
            text_data = card_data.get('text', {})
            title_data = text_data.get('title', {}) if isinstance(text_data, dict) else {}
            actual_card_name = title_data.get('text', actual_card_name_default) if isinstance(title_data, dict) else actual_card_name_default
            
            # Extract set and collector number
            set_code = card_data.get('infoSet', set_code_default)
            collector_number = card_data.get('infoNumber', collector_number_default)
            
            self.logger.debug(f"For dropdown '{card_name}': actual name='{actual_card_name}', set='{set_code}', num='{collector_number}'.")
        else:
            self.logger.warning(f"Could not find parsed data for '{card_name}'. Using dropdown identifier as fallback.")
            # Fallback: use the dropdown identifier, but try to clean it if it's already formatted
            if '_' in card_name:
                # Assume it's already in format "name_set_number" and extract just the name part
                actual_card_name = card_name.split('_')[0]
                self.logger.debug(f"Extracted name part from formatted identifier: '{actual_card_name}'")
            else:
                actual_card_name = card_name
        
        # Sanitize actual card name: lowercase, replace spaces with dashes, remove special characters
        import re
        clean_name = re.sub(r'[^\w\s-]', '', actual_card_name.lower())  # Remove special chars except spaces and dashes
        clean_name = re.sub(r'\s+', '-', clean_name.strip())           # Replace spaces with dashes
        clean_name = re.sub(r'-+', '-', clean_name)                    # Collapse multiple dashes
        
        # Clean up set code and collector number
        set_code_clean = str(set_code).lower().strip()
        collector_number_clean = str(collector_number).lower().strip()
    
        # Assemble the filename parts, avoiding empty parts which could cause double delimiters
        parts = [clean_name]
        if set_code_clean and set_code_clean != set_code_default:
            parts.append(set_code_clean)
        if collector_number_clean and collector_number_clean != collector_number_default:
            parts.append(collector_number_clean)
        
        base_filename = "_".join(parts)  # Use underscore as the main delimiter
        
        # Final sanitization for any remaining invalid characters
        # Allow alphanumeric, dashes (for card name), and underscores (for delimiters)
        final_filename_base = "".join(c for c in base_filename if c.isalnum() or c == '-' or c == '_')
        
        return f"{final_filename_base}.png"

    def prime_rendering_quirks(self) -> Optional[str]: # MODIFIED
        if not self.cards: self.logger.info("No cards in list, skipping rendering priming."); return None
        self.logger.info("Applying rendering quirks workaround (flavor text and first card)...")
        
        initial_hash_for_priming: Optional[str] = None
        if self._current_active_tab != "art":
            if not self._navigate_to_creator_tab("art"):
                self.logger.warning("Priming: Could not switch to 'art' tab for initial hash.")
        if self._current_active_tab == "art":
             temp_js_get_url="""const cSels=['#mainCanvas','#canvas','canvas'];let c=null;for(let s of cSels){c=document.querySelector(s);if(c)break;}
                                if(!c||c.width===0||c.height===0)return null;try{return c.toDataURL('image/png');}catch(e){return 'error';}"""
             temp_url = self.driver.execute_script(temp_js_get_url)
             if temp_url and temp_url.startswith('data:image/png;base64,'):
                 initial_hash_for_priming = hashlib.md5(temp_url.encode('utf-8')).hexdigest()
                 self.logger.debug(f"Priming: Initial hash on 'art' tab: {initial_hash_for_priming[:10] if initial_hash_for_priming else 'None'}")

        hash_after_flavor_prime_ops = initial_hash_for_priming 

        if self.parsed_card_data_map:
            flavor_primer_card_name: Optional[str] = None; flavor_primer_card_index: Optional[int] = None
            rules_key_in_file = "rules" # From your example: card_obj["data"]["text"]["rules"]["text"]
            text_block_key = "text"     # Intermediate key

            for idx, card_name_from_dropdown in enumerate(self.cards):
                card_data_content = self.parsed_card_data_map.get(card_name_from_dropdown) # This is card_obj["data"]
                if card_data_content and \
                   isinstance(card_data_content.get(text_block_key), dict) and \
                   isinstance(card_data_content[text_block_key].get(rules_key_in_file), dict) and \
                   isinstance(card_data_content[text_block_key][rules_key_in_file].get("text"), str) and \
                   "{flavor}" in card_data_content[text_block_key][rules_key_in_file]["text"]:
                    flavor_primer_card_name = card_name_from_dropdown; flavor_primer_card_index = idx
                    self.logger.info(f"Found flavor text in '{flavor_primer_card_name}' (idx {idx})."); break
            
            if flavor_primer_card_name is not None and flavor_primer_card_index is not None:
                self.logger.info(f"Priming flavor text with '{flavor_primer_card_name}'...")
                if not self._navigate_to_creator_tab("import"): return None
                if not self.load_card(flavor_primer_card_name): self.logger.error(f"Flavor prime: Fail load '{flavor_primer_card_name}'."); return None
                if not self._navigate_to_creator_tab("art"): return None 
                _, hash_after_flavor_prime_ops = self.capture_card_image_data_from_canvas(flavor_primer_card_name, hash_after_flavor_prime_ops)
                if not hash_after_flavor_prime_ops: self.logger.error(f"Flavor prime: Fail capture '{flavor_primer_card_name}'."); return None
                
                if flavor_primer_card_index + 1 < len(self.cards):
                    next_card_name = self.cards[flavor_primer_card_index + 1]
                    self.logger.info(f"Flavor prime: Loading card after flavor: '{next_card_name}'...")
                    if not self._navigate_to_creator_tab("import"): return None
                    if not self.load_card(next_card_name): self.logger.error(f"Flavor prime: Fail load '{next_card_name}'.")
                    if not self._navigate_to_creator_tab("art"): return None
                    _, hash_after_flavor_prime_ops = self.capture_card_image_data_from_canvas(next_card_name, hash_after_flavor_prime_ops)
                    if not hash_after_flavor_prime_ops: self.logger.warning(f"Flavor prime: Failed capture for '{next_card_name}'. Hash may be stale.")
                else: self.logger.info(f"Flavor prime: '{flavor_primer_card_name}' was last card.")
                self.logger.info("Flavor text priming sequence complete.")
            else: self.logger.info("No {flavor} tag found or parsed data unavailable. Skipping specific flavor priming.")
        else: self.logger.warning("Parsed card data map empty. Skipping flavor text priming.")

        final_first_card_hash: Optional[str] = None
        current_hash_for_general_prime = hash_after_flavor_prime_ops

        if len(self.cards) >= 2:
            card1_name = self.cards[0]; card2_name = self.cards[1]
            # Only load card2 if it wasn't the one just loaded and captured by flavor priming's "next card"
            if not (flavor_primer_card_name and flavor_primer_card_index is not None and \
                    flavor_primer_card_index + 1 < len(self.cards) and self.cards[flavor_primer_card_index + 1] == card2_name and \
                    current_hash_for_general_prime is not None): # current_hash_for_general_prime would be hash of card2
                self.logger.info(f"General Prime: Loading second card '{card2_name}'...")
                if not self._navigate_to_creator_tab("import"): return None
                if not self.load_card(card2_name): self.logger.error(f"General Prime fail: load '{card2_name}'."); return None
                if not self._navigate_to_creator_tab("art"): return None 
                _, current_hash_for_general_prime = self.capture_card_image_data_from_canvas(card2_name, current_hash_for_general_prime) 
                if not current_hash_for_general_prime: self.logger.error(f"General Prime fail: capture '{card2_name}'."); return None
                self.logger.info(f"General Prime: '{card2_name}' loaded/stabilized (hash: {current_hash_for_general_prime[:10]}).")
            else:
                 self.logger.info(f"General Prime: Second card '{card2_name}' seems already processed by flavor prime. Using its hash: {current_hash_for_general_prime[:10] if current_hash_for_general_prime else 'None'}")
        elif len(self.cards) == 1: self.logger.info(f"General Prime: Only one card ('{self.cards[0]}').")
        
        card_to_finally_load = self.cards[0]
        needs_reload_card1 = True
        if flavor_primer_card_name == card_to_finally_load and \
           (flavor_primer_card_index is not None and flavor_primer_card_index + 1 >= len(self.cards)) and \
           current_hash_for_general_prime is not None : # If card1 was the flavor primer AND the last card loaded in that sequence
             self.logger.info(f"General Prime: First card '{card_to_finally_load}' was last in flavor prime. Using its hash.")
             needs_reload_card1 = False
             final_first_card_hash = current_hash_for_general_prime 
        
        if needs_reload_card1:
            self.logger.info(f"General Prime: (Re)Loading first/single card '{card_to_finally_load}'...")
            if not self._navigate_to_creator_tab("import"): return None
            if not self.load_card(card_to_finally_load): self.logger.error(f"General Prime fail: load '{card_to_finally_load}'."); return None
            if not self._navigate_to_creator_tab("art"): return None 
            _, final_first_card_hash = self.capture_card_image_data_from_canvas(card_to_finally_load, current_hash_for_general_prime) 
            if not final_first_card_hash: self.logger.error(f"General Prime fail: capture (re)loaded '{card_to_finally_load}'."); return None
        
        self.logger.info(f"All Priming complete. Card '{card_to_finally_load}' loaded/stabilized (hash: {final_first_card_hash[:10] if final_first_card_hash else 'None'}).")
        self._current_active_tab = "art" 
        return final_first_card_hash

    # --- MODIFIED: Now tracks failed card keys ---
    def process_and_output_all_cards(self) -> bool:
        if self.upload_to_server:
            self.logger.info("Starting image processing for SERVER UPLOAD.")
        else:
            self.logger.info("Starting image processing for LOCAL DIRECTORY output (via temp ZIP).")

        self.failed_card_keys = [] # Reset the list for this run
        current_canvas_hash: Optional[str] = None 
        if not self.cards: self.logger.info("Card list empty, fetching..."); self.get_saved_cards()
        if not self.cards: self.logger.error("No cards to process."); return False
        
        current_canvas_hash = self.prime_rendering_quirks()
        s_cards, f_cards_info = 0, []

        # --- Main processing loop ---
        for i, name in enumerate(self.cards):
            self.logger.info(f"Processing {i+1}/{len(self.cards)}: '{name}'")
            is_first_card_and_was_successfully_primed = (i == 0 and current_canvas_hash is not None)
            
            if not is_first_card_and_was_successfully_primed:
                if not self._navigate_to_creator_tab("import"):
                    f_cards_info.append(f"{name}(import nav fail)"); self.failed_card_keys.append(name); continue
                if not self.load_card(name):
                    f_cards_info.append(f"{name}(load fail)"); self.failed_card_keys.append(name); continue
            else:
                self.logger.info(f"Skipping explicit load for '{name}' (handled by priming). Ensuring 'art' tab.")
                if self._current_active_tab != "art": 
                    if not self._navigate_to_creator_tab("art"):
                        f_cards_info.append(f"{name}(art tab nav fail post-prime)"); self.failed_card_keys.append(name); continue
            
            # Apply optional features
            if self.set_symbol_override_code and not self.apply_set_symbol_override(self.set_symbol_override_code): self.logger.warning(f"Failed set symbol override for '{name}'.")
            if self.auto_fit_set_symbol_enabled and not self.apply_auto_fit_set_symbol(): self.logger.warning(f"Failed auto fit set symbol for '{name}'.")
            if self.auto_fit_art_enabled and not self.apply_auto_fit_art(): self.logger.warning(f"Failed auto fit art for '{name}'.")
            
            # Capture canvas
            capture_tab = "art" 
            if self._current_active_tab != capture_tab: 
                self.logger.info(f"Ensuring on '{capture_tab}' tab for canvas capture of '{name}'.")
                if not self._navigate_to_creator_tab(capture_tab):
                    f_cards_info.append(f"{name}(capture tab nav fail)"); self.failed_card_keys.append(name); continue
            
            img_bytes, new_hash_after_capture = self.capture_card_image_data_from_canvas(name, current_canvas_hash)
            current_canvas_hash = new_hash_after_capture 
            
            if not img_bytes:
                f_cards_info.append(f"{name}(capture fail)")
                self.failed_card_keys.append(name)
                continue

            output_filename = self._generate_filename(name)
            self.logger.info(f"Generated output filename: '{output_filename}'")

            if self.upload_to_server:
                path_parts = [self.output_server_path.strip('/'), output_filename.lstrip('/')]
                full_path = "/".join(p for p in path_parts if p)
                if not full_path.startswith('/'): full_path = '/' + full_path
                upload_url = f"{self.image_server_base_url.rstrip('/')}{full_path}"

                if not self.overwrite_server_file and check_server_file_exists(upload_url, self.debug_mode):
                    self.logger.warning(f"Skipping upload for '{output_filename}', file exists on server. Use --overwrite-server-file.")
                    f_cards_info.append(f"{name}(exists on server)")
                    continue
                
                if upload_file_to_server(upload_url, img_bytes, 'image/png', self.debug_mode):
                    s_cards += 1
                else:
                    f_cards_info.append(f"{name}(upload fail)")
                    self.failed_card_keys.append(name)
            else:
                f_cards_info.append({'name': output_filename, 'bytes': img_bytes})
                s_cards += 1

        # --- Post-loop processing for local mode ---
        if not self.upload_to_server:
            successful_local_cards = [c for c in f_cards_info if isinstance(c, dict)]
            failed_local_cards = [c for c in f_cards_info if isinstance(c, str)]
            
            if not successful_local_cards:
                self.logger.warning("No cards were successfully captured for local saving.")
                if failed_local_cards: self.logger.warning(f"Failed ops ({len(failed_local_cards)}): {', '.join(failed_local_cards)}")
                return False

            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            zip_temp_fp = Path(self.output_dir) / f"CC_Temp_v7.1_{ts}.zip"
            self.logger.info(f"Creating temporary ZIP for local extraction: {zip_temp_fp}")
            try:
                with zipfile.ZipFile(zip_temp_fp, 'w', zipfile.ZIP_DEFLATED) as zf:
                    for card_data in successful_local_cards:
                        zf.writestr(card_data['name'], card_data['bytes'])
                
                self.logger.info(f"Extracting {len(successful_local_cards)} images from {zip_temp_fp} to {self.output_dir}...")
                with zipfile.ZipFile(zip_temp_fp, 'r') as zf_read:
                    zf_read.extractall(self.output_dir)
                self.logger.info(f"Successfully extracted {len(successful_local_cards)} image(s).")

            except Exception as e_zip:
                self.logger.error(f"Temp ZIP/Extraction error: {e_zip}", exc_info=True)
                return False
            finally:
                if os.path.exists(zip_temp_fp):
                    try: os.remove(zip_temp_fp); self.logger.info(f"Deleted temp ZIP: {zip_temp_fp}")
                    except Exception as e_del: self.logger.error(f"Error deleting temp ZIP: {e_del}")
            
            if failed_local_cards: self.logger.warning(f"Failed ops ({len(failed_local_cards)}): {', '.join(failed_local_cards)}")
            return len(successful_local_cards) > 0

        if f_cards_info: self.logger.warning(f"Failed ops ({len(f_cards_info)}): {', '.join(f_cards_info)}")
        return s_cards > 0

    # --- NEW: Method to generate a .cardconjurer file for failed cards ---
    def _write_failed_cards_file(self, original_filepath: str):
        """Filters the original input file to create a new file containing only failed cards."""
        if not self.failed_card_keys:
            self.logger.info("No failed cards were recorded, skipping failed-file generation.")
            return

        if not self.full_card_list_from_file:
            self.logger.error("Cannot write failed cards file: original card data was not loaded or is empty.")
            return

        unique_failed_keys = sorted(list(set(self.failed_card_keys)))
        self.logger.info(f"Found {len(unique_failed_keys)} unique failed cards. Generating a new .cardconjurer file for them.")

        failed_keys_set = set(unique_failed_keys)
        failed_card_objects = [
            card_obj for card_obj in self.full_card_list_from_file
            if card_obj.get("key") in failed_keys_set
        ]

        if not failed_card_objects:
            self.logger.warning(f"Found {len(unique_failed_keys)} failed card keys, but couldn't match them to objects in the original file. No file will be written.")
            return

        p = Path(original_filepath)
        failed_filename = f"{p.stem}-failed{p.suffix}"
        failed_filepath = p.with_name(failed_filename)

        try:
            with open(failed_filepath, 'w', encoding='utf-8') as f:
                json.dump(failed_card_objects, f, indent=4)
            self.logger.info(f"Successfully wrote {len(failed_card_objects)} failed card objects to: {failed_filepath}")
        except Exception as e:
            self.logger.error(f"Failed to write failed cards file to {failed_filepath}: {e}", exc_info=True)

    # --- MODIFIED: Calls the new method to write failed cards file ---
    def run(self, cardconjurer_file=None, action="zip", headless=False, frame=None, args_for_optional_features=None):
        self.logger.info(f"Run (v7.1) action:{action} headless:{headless} frame:{frame}")
        if args_for_optional_features:
            self.auto_fit_art_enabled = getattr(args_for_optional_features, 'auto_fit_art', False)
            self.auto_fit_set_symbol_enabled = getattr(args_for_optional_features, 'auto_fit_set_symbol', False)
            self.set_symbol_override_code = getattr(args_for_optional_features, 'set_symbol_override', None)
            if self.auto_fit_art_enabled: self.logger.info("Opt Feature: Auto Fit Art ENABLED")
            if self.auto_fit_set_symbol_enabled: self.logger.info("Opt Feature: Auto Fit Set Symbol (Reset) ENABLED")
            if self.set_symbol_override_code: self.logger.info(f"Opt Feature: Set Symbol Override with code '{self.set_symbol_override_code}' (will use live rarity).")
        try:
            self.setup_driver(headless=headless) 
            if not self.navigate_to_card_conjurer(): return 
            time.sleep(self.delays['js_init'])
            
            if cardconjurer_file:
                if not self._parse_cardconjurer_file_content(cardconjurer_file):
                    self.logger.warning(f"Failed to parse {cardconjurer_file}. Data-dependent features may fail.")
            
            if frame: 
                if self._current_active_tab != "art": 
                    if not self._navigate_to_creator_tab("art"):
                        self.logger.warning("Could not navigate to 'art' for frame setting.")
                if self._current_active_tab == "art" and not self.set_auto_frame(frame):
                     self.logger.warning(f"Failed frame setting for '{frame}'.")
            
            if cardconjurer_file:
                if not self.upload_cardconjurer_file(file_path=cardconjurer_file): 
                    self.logger.error(f"Fail upload/load from: {cardconjurer_file}. Abort."); return
            elif not cardconjurer_file: 
                self.logger.info("No file. Check existing cards...");
                on_imp = self._navigate_to_creator_tab("import") 
                if on_imp and not self.check_cards_loaded(): self.logger.warning("No cards loaded (dropdown).")
                elif not on_imp: self.logger.warning("Cannot check cards, import nav fail.")

            if action=="zip": # "zip" action now means "process and output"
                if not self.cards: self.get_saved_cards() 
                if not self.cards: self.logger.error("No cards to process."); return 
                
                output_successful = self.process_and_output_all_cards() 
                
                if output_successful: 
                    if self.upload_to_server:
                        self.logger.info(f"Image upload process complete.")
                    else:
                        self.logger.info(f"Image extraction complete. Files are in: {self.output_dir}")
                else: 
                    self.logger.error("Image processing and output failed or no images were processed.")
            
            # --- NEW: Generate file for failed cards ---
            if cardconjurer_file:
                self._write_failed_cards_file(cardconjurer_file)
            # --- END NEW ---

        except Exception as e: self.logger.error(f"Unhandled run err: {e}",exc_info=True)
        finally:
            if self.driver:
                if not headless and sys.stdin.isatty():
                    try: input("Press Enter to close browser...")
                    except EOFError: self.logger.info("Non-interactive, closing.")
                self.driver.quit(); self.logger.info("Browser closed.")

def main():
    p = argparse.ArgumentParser(description='Card Conjurer Downloader - v7.1 with Local/Web Server Output and Auto-Retry File')
    p.add_argument('--file','-f',required=True,help='.cardconjurer file to load')
    p.add_argument('--url',default='https://cardconjurer.app:443',help='Card Conjurer URL')
    p.add_argument('--output-dir',default=None,help='Local output directory for extracted images and logs. Used if --upload-to-server is not specified.')
    p.add_argument('--headless',action='store_true',help='Run in headless mode')
    p.add_argument('--frame',choices=['7th','seventh','8th','eighth','m15','ub'],help='Auto frame setting')
    p.add_argument('--log-level',default='INFO',choices=['DEBUG','INFO','WARNING','ERROR'],help='Console logging level')
    
    opt_group = p.add_argument_group('Optional Card-Specific Features')
    opt_group.add_argument('--auto-fit-art', action='store_true', help='Enable Auto Fit Art feature.')
    opt_group.add_argument('--auto-fit-set-symbol', action='store_true', help='Enable Reset Set Symbol (auto fit) feature.')
    opt_group.add_argument('--set-symbol-override', type=str, default=None, metavar='CODE', 
                       help='Override set symbol with CODE (e.g., "MH2"). Live rarity from Collector tab will be used.')

    webserver_upload_group = p.add_argument_group('Web Server Upload Options')
    webserver_upload_group.add_argument(
        "--upload-to-server", action="store_true",
        help="Upload the generated PNGs to a WebDAV server instead of saving them locally."
    )
    webserver_upload_group.add_argument(
        "--image-server-base-url", type=str, default=None,
        help="Base URL of the WebDAV image server (e.g., http://localhost:8088). Required for upload."
    )
    webserver_upload_group.add_argument(
        "--output-server-path", type=str, default=None,
        help="Subdirectory on the server to upload the PNGs to (e.g., '/my-cards/new-set/'). Required for upload."
    )
    webserver_upload_group.add_argument(
        "--overwrite-server-file", action="store_true",
        help="If a file with the same name exists on the server, overwrite it. Default is to fail."
    )
    
    a = p.parse_args()
    if not os.path.exists(a.file): print(f"Error: File not found: {a.file}");sys.exit(1)
    
    if a.upload_to_server:
        if not a.image_server_base_url:
            p.error("--upload-to-server requires --image-server-base-url.")
        if not a.output_server_path:
            p.error("--upload-to-server requires --output-server-path.")

    log_lvl_val = getattr(logging, a.log_level.upper(), logging.INFO)
    
    downloader = CardConjurerDownloader(
        url=a.url,
        output_dir=a.output_dir,
        log_level=log_lvl_val,
        upload_to_server=a.upload_to_server,
        image_server_base_url=a.image_server_base_url,
        output_server_path=a.output_server_path,
        overwrite_server_file=a.overwrite_server_file
    )
    downloader.run(cardconjurer_file=a.file,headless=a.headless,frame=a.frame, args_for_optional_features=a)

if __name__ == "__main__":
    main()

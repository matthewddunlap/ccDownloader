"""
Card Conjurer Selenium Downloader - Smart Canvas Capture Version (v5 - Full Features, Readable)

Captures card images directly from the canvas using toDataURL and zips them.
Uses a smart wait to detect canvas changes and stabilization.
Includes optional features for art and set symbol manipulation.
Set Symbol Override now always uses live rarity from the Collector tab, populating separate fields.
This version prioritizes readability and careful integration of new features into the working baseline.
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
# from selenium.webdriver.common.keys import Keys # Not used in this version for onchange

class CardConjurerDownloader:
    def __init__(self, url="http://mtgproxy:4242", download_dir=None, log_level=logging.INFO):
        """Initialize the Card Conjurer downloader with logging."""
        self.url = url
        self.download_dir = download_dir or os.path.join(os.path.expanduser("~"), "Downloads", "CardConjurer")
        self.driver = None
        self.cards = []
        self._current_active_tab: Optional[str] = None # Tracks current tab like 'art', 'import', etc.

        # Optional features states - will be set in run()
        self.auto_fit_art_enabled = False
        self.auto_fit_set_symbol_enabled = False
        self.set_symbol_override_code = None
        # self.use_live_rarity_for_override flag removed, live rarity is now default for override

        self.delays = {
            'page_load': 0.1,
            'tab_switch': 0.1, 
            'file_upload_wait': 10.0, 
            'card_load_js_ops': 0.2, # Minimal delay after JS load ops in load_card
            'frame_set': 0.1,
            'element_wait': 3.0, 
            'js_init': 0.1,
            # 'canvas_render_wait': 1.5, # This is now replaced by wait_for_canvas_change_and_stabilization
            'canvas_stabilize_timeout': 15.0, # Max time for canvas to change & stabilize
            'canvas_stability_checks': 3,     # How many stable checks needed
            'canvas_stability_interval': 0.33, # Interval between stability checks
            'art_fit_wait': 0.75,             # Delay after clicking auto fit art
            'set_symbol_reset_wait': 0.75,  # Delay after clicking reset set symbol
            'set_symbol_fetch_wait': 1.5    # Delay after changing set symbol code/rarity for fetchSetSymbol()
        }

        Path(self.download_dir).mkdir(parents=True, exist_ok=True)
        self.setup_logging(log_level)
        self.logger.info(f"Initialized CardConjurerDownloader (Smart Canvas v5 - Full Features)")
        self.logger.info(f"URL: {self.url}")
        self.logger.info(f"Output directory (for ZIP and logs): {self.download_dir}")

    def setup_logging(self, log_level): # Unchanged from baseline
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
        log_file_name = log_dir / f"cc_v5_full_opts_{timestamp}.log" # Updated log name
        file_handler = logging.FileHandler(log_file_name)
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(detailed_formatter)
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(log_level)
        console_handler.setFormatter(simple_formatter)
        self.logger.addHandler(file_handler)
        self.logger.addHandler(console_handler)
        self.logger.info(f"Logging initialized. Log file: {log_file_name}")

    def setup_driver(self, headless=False): # Unchanged from baseline
        self.logger.info(f"Setting up Chrome driver (headless={headless})")
        chrome_options = Options()
        prefs = {"safebrowsing.enabled": False}
        chrome_options.add_experimental_option("prefs", prefs)
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--window-size=1920,1080") 
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
            self.logger.error("ChromeDriver not found. Please install or check PATH.")
            raise Exception("ChromeDriver not found.")
        service = Service(chromedriver_path)
        self.driver = webdriver.Chrome(service=service, options=chrome_options)
        self.logger.info("Browser setup complete")

    def wait_for_element(self, selector, by=By.CSS_SELECTOR, timeout=None): # Unchanged
        timeout = timeout or self.delays['element_wait']
        try: return WebDriverWait(self.driver, timeout).until(EC.presence_of_element_located((by, selector)))
        except TimeoutException: self.logger.debug(f"Timeout waiting for element: {by}='{selector}'"); return None

    def wait_for_clickable(self, selector, by=By.CSS_SELECTOR, timeout=None): # Unchanged
        timeout = timeout or self.delays['element_wait']
        try: return WebDriverWait(self.driver, timeout).until(EC.element_to_be_clickable((by, selector)))
        except TimeoutException: self.logger.debug(f"Timeout waiting for clickable element: {by}='{selector}'"); return None

    def click_element_safely(self, element): # Unchanged
        try: element.click(); return True
        except ElementClickInterceptedException:
            self.logger.warning("Element click intercepted, trying JS click.")
            try:
                self.driver.execute_script("arguments[0].scrollIntoView(true);", element); time.sleep(0.1) 
                self.driver.execute_script("arguments[0].click();", element); return True
            except Exception as e_js: self.logger.error(f"JS click also failed: {e_js}"); return False
        except Exception as e: self.logger.error(f"Other error clicking element: {e}"); return False

    def _navigate_to_creator_tab(self, target_tab_name: str) -> bool: # New Helper Method
        if self._current_active_tab == target_tab_name:
            self.logger.debug(f"Already on '{target_tab_name}' tab.")
            return True
        self.logger.info(f"Navigating to '{target_tab_name}' tab...")
        tab_selector = f"h3[onclick*='toggleCreatorTabs(event, \"{target_tab_name}\")']"
        tab_button = self.wait_for_clickable(tab_selector, timeout=3)
        if tab_button and self.click_element_safely(tab_button):
            self.logger.info(f"Successfully clicked the '{target_tab_name}' tab.")
            self._current_active_tab = target_tab_name
            time.sleep(self.delays['tab_switch'] + 0.3) # Allow tab content to potentially load
            return True
        self.logger.error(f"'{target_tab_name}' tab button ({tab_selector}) not found or not clickable.")
        self._current_active_tab = None # Tab state unknown if navigation fails
        return False

    def navigate_to_card_conjurer(self): # Modified to set initial tab
        self.logger.info(f"Navigating to Card Conjurer: {self.url}")
        self.driver.get(self.url)
        if self.wait_for_element("canvas", timeout=10): 
            self.logger.info("Canvas found, page appears ready.")
            self._current_active_tab = "art" # Assume 'art' or main view is default with canvas
            return True
        self.logger.error("Canvas not found after page load. Card Conjurer may not have loaded correctly.")
        return False

    def upload_cardconjurer_file(self, file_path): # Modified to use _navigate_to_creator_tab
        self.logger.info(f"Uploading file: {file_path}")
        if not os.path.exists(file_path): 
            self.logger.error(f"File not found: {file_path}"); return False
        
        if not self._navigate_to_creator_tab("import"): # Ensure on import tab
            self.logger.error("Failed to navigate to 'import' tab for file upload.")
            return False
        
        self.logger.info("Attempting to find the file input element on the import tab...")
        # File input finding logic restored from baseline (readable version)
        file_input_selectors = [
            "input#importProject[type='file']", 
            "input[type='file'][accept*='.cardconjurer']", 
            "input[type='file'][oninput*='uploadSavedCards']",
            "input[type='file']", 
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
             self.logger.warning(f"Using a HIDDEN file input. Attempting to make it visible.")
        try:
            self.logger.info(f"Using file input: Tag={file_input_element.tag_name}, ID='{file_input_element.get_attribute('id')}', Class='{file_input_element.get_attribute('class')}'")
            self.driver.execute_script("arguments[0].style.opacity=1;arguments[0].style.display='block';arguments[0].style.visibility='visible';arguments[0].disabled=false;arguments[0].removeAttribute('hidden');", file_input_element)
            time.sleep(0.2); file_input_element.send_keys(os.path.abspath(file_path)); self.logger.info(f"File path sent.")
        except Exception as e: self.logger.error(f"Error sending file path: {e}", exc_info=True); return False
        self.logger.info("Waiting for cards to load from file...")
        try:
            WebDriverWait(self.driver, self.delays['file_upload_wait']).until(self.check_cards_loaded) 
            self.logger.info("Cards loaded successfully after file upload."); return True
        except TimeoutException: 
            self.logger.error("Timeout waiting for cards to load after file upload.")
            # Debugging for upload failure (restored readability)
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

    def check_cards_loaded(self, driver_instance=None) -> bool: # Unchanged
        driver_to_use = driver_instance if driver_instance else self.driver
        try:
            card_select = driver_to_use.find_element(By.ID, "load-card-options")
            options = card_select.find_elements(By.TAG_NAME, "option")
            return any(opt.text.strip() and opt.text.strip().lower() not in ['none selected', 'load a saved card', ''] for opt in options)
        except NoSuchElementException: self.logger.debug("check_cards_loaded: 'load-card-options' not found."); return False
        except Exception as e: self.logger.debug(f"check_cards_loaded: Error: {e}"); return False
        
    def get_saved_cards(self) -> list: # Modified to use _navigate_to_creator_tab
        self.logger.info("Getting list of saved cards...")
        self.cards = [] 
        if not self._navigate_to_creator_tab("import"): # Ensure on import tab
            self.logger.error("Cannot navigate to 'import' tab for get_saved_cards.")
            return []
        try:
            card_select = self.wait_for_element("load-card-options", by=By.ID, timeout=5)
            if not card_select: self.logger.error("'load-card-options' select element not found."); return []
            options = card_select.find_elements(By.TAG_NAME, "option")
            cards_found = [opt.get_attribute("value").strip() for opt in options if opt.get_attribute("value").strip() and opt.get_attribute("value").strip().lower() not in ['none selected', 'load a saved card', '']]
            self.logger.info(f"Found {len(cards_found)} saved cards: {cards_found[:5] if cards_found else 'None'}") 
            self.cards = cards_found; return cards_found
        except Exception as e: self.logger.error(f"Error getting saved cards: {e}", exc_info=True); return []

    def set_auto_frame(self, frame_option: str) -> bool: # Unchanged
        if not frame_option: return True 
        self.logger.info(f"Setting auto frame to: {frame_option}")
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

    def load_card(self, card_name: str) -> bool: # Unchanged
        self.logger.info(f"Loading card: '{card_name}' using JavaScript method.")
        # Assumes 'import' tab is active.
        try:
            card_select_el = self.wait_for_element("load-card-options", By.ID, timeout=3)
            if not card_select_el: self.logger.error("'load-card-options' not found."); return False
            js_card = json.dumps(card_name)
            t=time.perf_counter(); self.driver.execute_script(f"document.getElementById('load-card-options').value = {js_card};"); self.logger.debug(f"JS: Set value took {time.perf_counter() - t:.4f}s")
            t=time.perf_counter(); self.driver.execute_script(f"var s=document.getElementById('load-card-options'); s.dispatchEvent(new Event('change',{{'bubbles':true}}));"); dur=time.perf_counter()-t; self.logger.debug(f"JS: Dispatch 'change' took {dur:.4f}s")
            if dur < 1.0 and self.driver.execute_script("return typeof loadCard === 'function';"):
                t=time.perf_counter(); self.driver.execute_script(f"loadCard({js_card});"); self.logger.debug(f"JS: Global loadCard() call took {time.perf_counter() - t:.4f}s")
            elif dur >= 1.0 : self.logger.info(f"JS: Dispatch 'change' was slow ({dur:.4f}s), assumed load handled.")
            time.sleep(self.delays['card_load_js_ops']); self.logger.info(f"JS operations for card load '{card_name}' completed."); return True
        except Exception as e: self.logger.error(f"Error loading card '{card_name}': {e}", exc_info=True); return False

    # --- New Optional Feature Methods ---
    def get_live_rarity_from_page(self) -> Optional[str]: # New
        self.logger.info("Attempting to get live rarity from 'Collector' tab...")
        if not self._navigate_to_creator_tab("bottomInfo"): # 'bottomInfo' is internal for 'Collector'
            self.logger.error("Failed to navigate to 'Collector' (bottomInfo) tab to get rarity.")
            return None
        rarity_input_selector = "input#info-rarity"
        rarity_input_element = self.wait_for_element(rarity_input_selector, timeout=3)
        if rarity_input_element:
            try:
                live_rarity_value = rarity_input_element.get_attribute("value")
                self.logger.info(f"Retrieved live rarity value from Collector tab: '{live_rarity_value}'")
                return live_rarity_value
            except Exception as e:
                self.logger.error(f"Error getting value from rarity input ({rarity_input_selector}): {e}")
                return None
        self.logger.error(f"Rarity input field ('{rarity_input_selector}') not found on 'Collector' tab."); return None

    def apply_auto_fit_art(self) -> bool: # New
        self.logger.info("Applying Auto Fit Art...")
        if not self._navigate_to_creator_tab("art"): return False # Ensure on Art tab
        button_selector = "button.input[onclick='autoFitArt();']"
        auto_fit_button = self.wait_for_clickable(button_selector, timeout=3)
        if auto_fit_button and self.click_element_safely(auto_fit_button):
            self.logger.info("Clicked 'Auto Fit Art' button.")
            time.sleep(self.delays['art_fit_wait']) # Wait for art to potentially adjust
            return True
        self.logger.error(f"'Auto Fit Art' button ({button_selector}) not found or not clickable."); return False

    def apply_auto_fit_set_symbol(self) -> bool: # New (for "Reset Set Symbol")
        self.logger.info("Applying Reset Set Symbol (Auto Fit)...")
        if not self._navigate_to_creator_tab("setSymbol"): return False # Ensure on Set Symbol tab
        button_selector = "button.input[onclick='resetSetSymbol();']"
        reset_button = self.wait_for_clickable(button_selector, timeout=3)
        if reset_button and self.click_element_safely(reset_button):
            self.logger.info("Clicked 'Reset Set Symbol' button.")
            time.sleep(self.delays['set_symbol_reset_wait']) # Wait for symbol to reset
            return True
        self.logger.error(f"'Reset Set Symbol' button ({button_selector}) not found/clickable."); return False

    def apply_set_symbol_override(self, base_set_code: str) -> bool: # New (modified for separate fields)
        self.logger.info(f"Applying Set Symbol Override for code: '{base_set_code}' (will use live rarity).")
        live_rarity = self.get_live_rarity_from_page() # Gets rarity from Collector tab, sets _current_active_tab to 'bottomInfo'
        
        target_rarity_value_for_set_symbol_tab = None
        if live_rarity is not None and live_rarity.strip():
            target_rarity_value_for_set_symbol_tab = live_rarity.strip().upper()
            self.logger.info(f"Using live rarity '{target_rarity_value_for_set_symbol_tab}' for Set Symbol tab.")
        elif live_rarity == "": self.logger.warning("Live rarity was empty; 'set-symbol-rarity' field won't be explicitly set by override.")
        else: self.logger.warning("Could not get live rarity; 'set-symbol-rarity' field won't be explicitly set by override.")

        if not self._navigate_to_creator_tab("setSymbol"): # Now navigate to Set Symbol tab
            self.logger.error("Failed to navigate to 'Set Symbol' tab for override."); return False
        
        # Populate Set Code field
        set_code_input_el = self.wait_for_element("input#set-symbol-code", timeout=3)
        if not set_code_input_el: self.logger.error("Set code input not found."); return False
        try:
            self.click_element_safely(set_code_input_el); set_code_input_el.clear()
            set_code_input_el.send_keys(base_set_code)
            self.logger.info(f"Set 'set-symbol-code' to '{base_set_code}'.")
            self.driver.execute_script("arguments[0].dispatchEvent(new Event('change', {bubbles: true}));", set_code_input_el)
        except Exception as e: self.logger.error(f"Error with set code input: {e}"); return False

        # Populate Rarity field on Set Symbol tab
        if target_rarity_value_for_set_symbol_tab:
            set_rarity_input_el = self.wait_for_element("input#set-symbol-rarity", timeout=3)
            if not set_rarity_input_el: self.logger.error("Set rarity input not found on Set Symbol tab.")
            else:
                try:
                    self.click_element_safely(set_rarity_input_el); set_rarity_input_el.clear()
                    set_rarity_input_el.send_keys(target_rarity_value_for_set_symbol_tab)
                    self.logger.info(f"Set 'set-symbol-rarity' to '{target_rarity_value_for_set_symbol_tab}'.")
                    self.driver.execute_script("arguments[0].dispatchEvent(new Event('change', {bubbles: true}));", set_rarity_input_el)
                except Exception as e: self.logger.error(f"Error with set rarity input: {e}")
        else: self.logger.info("No explicit target rarity; 'set-symbol-rarity' not modified by override logic.")
        
        self.logger.info("Set symbol override ops complete. Waiting for fetch..."); time.sleep(self.delays['set_symbol_fetch_wait']); return True
    # --- End of New Optional Feature Methods ---

    def wait_for_canvas_change_and_stabilization(self, initial_data_url_hash: Optional[str]) -> Optional[str]: # Unchanged
        self.logger.debug(f"Waiting for canvas to change (from hash: {str(initial_data_url_hash)[:10]}...) and stabilize...")
        start_time = time.perf_counter(); timeout = self.delays['canvas_stabilize_timeout']
        stability_checks_needed = self.delays['canvas_stability_checks']; interval = self.delays['canvas_stability_interval']
        js_get_data_url = """
            const cSels=['#mainCanvas','#canvas','canvas'];let c=null;for(let s of cSels){c=document.querySelector(s);if(c)break;}
            if(!c||c.width===0||c.height===0)return 'canvas_error:no_canvas_or_zero_dims';
            try{return c.toDataURL('image/png');}catch(e){console.error('CC Automation: Err toDataURL:',e);return 'canvas_error:to_data_url_failed';}"""
        last_hash = initial_data_url_hash; current_hash = initial_data_url_hash; stable_count = 0
        changed_from_initial = False if initial_data_url_hash is not None else True 
        while time.perf_counter() - start_time < timeout:
            try:
                current_data_url = self.driver.execute_script(js_get_data_url)
                if isinstance(current_data_url, str) and current_data_url.startswith('canvas_error:'):
                    self.logger.warning(f"Canvas JS err: {current_data_url}");time.sleep(interval);continue
                if not current_data_url: self.logger.debug("Canvas dataURL null.");time.sleep(interval);continue
                current_hash = hashlib.md5(current_data_url.encode('utf-8')).hexdigest()
            except Exception as e: self.logger.warning(f"Py ex get/hash canvas: {e}");time.sleep(interval);continue
            if not changed_from_initial: 
                if current_hash != initial_data_url_hash:
                    self.logger.debug(f"Canvas changed from initial. New hash: {current_hash[:10]}...")
                    changed_from_initial = True; last_hash = current_hash; stable_count = 1
                else: self.logger.debug(f"Canvas same as initial ({str(initial_data_url_hash)[:10]})."); last_hash = initial_data_url_hash; stable_count = 0
            if changed_from_initial:
                if current_hash == last_hash: stable_count += 1; self.logger.debug(f"Canvas hash stabilized ({stable_count}/{stability_checks_needed}): {current_hash[:10]}...")
                else: self.logger.debug(f"Canvas hash changed: {current_hash[:10]} from {last_hash[:10]}. Reset."); stable_count = 1
                last_hash = current_hash
                if stable_count >= stability_checks_needed: self.logger.info(f"Canvas stabilized to new hash: {current_hash[:10]}."); return current_hash
            time.sleep(interval)
        self.logger.warning("Timeout waiting for canvas to stabilize after change.");return None

    def capture_card_image_data_from_canvas(self, card_name: str, previous_canvas_hash: Optional[str]) -> Tuple[Optional[bytes], Optional[str]]: # Unchanged
        self.logger.info(f"Preparing to capture canvas for: {card_name}")
        # The wait for canvas_render_wait was removed here because wait_for_canvas_change_and_stabilization handles dynamic waiting.
        new_stabilized_hash = self.wait_for_canvas_change_and_stabilization(previous_canvas_hash)
        if not new_stabilized_hash or (previous_canvas_hash and new_stabilized_hash == previous_canvas_hash):
            self.logger.error(f"Canvas did not change/stabilize to NEW state for '{card_name}'. Prev: {str(previous_canvas_hash)[:10]}, New: {str(new_stabilized_hash)[:10]}"); return None, previous_canvas_hash 
        js_get_data_url = """
            const cSels=['#mainCanvas','#canvas','canvas']; let c=null; for(let s of cSels){c=document.querySelector(s);if(c)break;}
            if(!c||c.width===0||c.height===0)return null; try{return c.toDataURL('image/png');}catch(e){return 'error';}"""
        try:
            start_time_capture = time.perf_counter()
            data_url=self.driver.execute_script(js_get_data_url)
            self.logger.debug(f"JS FINAL canvas data URL call took: {time.perf_counter()-start_time_capture:.4f}s.")
            if data_url and data_url.startswith('data:image/png;base64,'):
                img_bytes = base64.b64decode(data_url.split(',',1)[1]); self.logger.info(f"Captured FINAL canvas for '{card_name}' ({len(img_bytes)} bytes)."); return img_bytes, new_stabilized_hash
            self.logger.error(f"Failed FINAL dataURL for '{card_name}'. Rx: {str(data_url)[:100]}"); return None, previous_canvas_hash
        except Exception as e: self.logger.error(f"Error capturing FINAL canvas for '{card_name}': {e}",exc_info=True); return None, previous_canvas_hash

    def create_zip_of_all_cards(self): # MODIFIED Workflow
        self.logger.info("Starting ZIP creation (Smart Canvas + Full Opt Features)")
        current_canvas_hash: Optional[str] = None 
        if not self.cards: self.logger.info("Card list empty, fetching..."); self.get_saved_cards() # Ensures 'import' tab
        if not self.cards: self.logger.error("No cards for ZIP."); return None

        capture_tab_for_initial_hash = "art" 
        self.logger.info(f"Attempting to capture initial canvas hash from '{capture_tab_for_initial_hash}' tab...")
        if self._navigate_to_creator_tab(capture_tab_for_initial_hash): # Switch to art tab
            init_js="""const cS=['#mainCanvas','#canvas','canvas'];let c=null;for(let s of cS){c=document.querySelector(s);if(c)break;}
                       if(!c||c.width===0||c.height===0)return null;try{return c.toDataURL('image/png');}catch(e){return 'error';}"""
            init_url=self.driver.execute_script(init_js)
            if init_url and init_url.startswith('data:image/png;base64,'):
                current_canvas_hash=hashlib.md5(init_url.encode('utf-8')).hexdigest()
                self.logger.info(f"Initial canvas hash ({self._current_active_tab} tab): {current_canvas_hash[:10]}...")
            else: self.logger.warning(f"Could not get valid initial canvas hash. Rx: {str(init_url)[:50]}")
        else: self.logger.warning(f"Failed nav to '{capture_tab_for_initial_hash}' for initial hash.")

        ts=datetime.now().strftime("%Y%m%d_%H%M%S");zip_fp=Path(self.download_dir)/f"CC_SmartCanvas_FullOpts_{ts}.zip"
        self.logger.info(f"Creating ZIP: {zip_fp}"); s_cards, f_cards = 0, []
        try:
            with zipfile.ZipFile(zip_fp,'w',zipfile.ZIP_DEFLATED) as zf:
                for i,name in enumerate(self.cards):
                    self.logger.info(f"Processing {i+1}/{len(self.cards)}: '{name}'")
                    
                    # 1. Ensure on Import tab to load card from dropdown
                    if not self._navigate_to_creator_tab("import"): 
                        self.logger.error(f"Failed nav to 'import' to load '{name}'. Skip.");f_cards.append(f"{name}(import nav fail)");continue
                    
                    # 2. Load card (this happens on the 'import' tab)
                    if not self.load_card(name): 
                        f_cards.append(f"{name}(load fail)");continue
                    
                    # --- 3. Apply optional features (these will navigate tabs internally) ---
                    if self.set_symbol_override_code and not self.apply_set_symbol_override(self.set_symbol_override_code): 
                        self.logger.warning(f"Failed set symbol override for '{name}'.")
                    if self.auto_fit_set_symbol_enabled and not self.apply_auto_fit_set_symbol(): 
                        self.logger.warning(f"Failed auto fit set symbol for '{name}'.")
                    if self.auto_fit_art_enabled and not self.apply_auto_fit_art(): 
                        self.logger.warning(f"Failed auto fit art for '{name}'.")
                    
                    # --- 4. Ensure on 'art' tab (or best canvas view tab) for capture ---
                    # This is the tab where the main canvas is expected to be fully rendered for capture.
                    final_capture_view_tab = "art" 
                    self.logger.info(f"Ensuring on '{final_capture_view_tab}' tab for canvas capture of '{name}'.")
                    if not self._navigate_to_creator_tab(final_capture_view_tab):
                        self.logger.error(f"Failed nav to '{final_capture_view_tab}' for capture. Skip.");f_cards.append(f"{name}(capture tab nav fail)");continue
                    
                    # --- 5. Capture Canvas for Card ---
                    img_bytes,new_hash=self.capture_card_image_data_from_canvas(name,current_canvas_hash)
                    current_canvas_hash = new_hash # Update for the next iteration
                    
                    if img_bytes: 
                        arc_name="".join(c for c in name if c.isalnum()or c in (' ','-','_')).rstrip()+".png"
                        zf.writestr(arc_name,img_bytes);self.logger.info(f"Added '{arc_name}'.");s_cards+=1
                    else: f_cards.append(f"{name}(capture fail)")
        except Exception as e: 
            self.logger.error(f"ZIP creation err: {e}",exc_info=True); (os.remove(zip_fp) if os.path.exists(zip_fp) else None); return None
        self.logger.info(f"ZIP summary: {s_cards}/{len(self.cards)} success.")
        if f_cards: self.logger.warning(f"Failed cards({len(f_cards)}): {', '.join(f_cards)}")
        return str(zip_fp) if s_cards > 0 else None

    def run(self, cardconjurer_file=None, action="zip", headless=False, frame=None, args_for_optional_features=None): # MODIFIED
        self.logger.info(f"Run (Smart Canvas + Full Opts v4) action:{action} headless:{headless} frame:{frame}") # Updated log
        if args_for_optional_features: # Set optional feature flags from parsed args
            self.auto_fit_art_enabled = getattr(args_for_optional_features, 'auto_fit_art', False)
            self.auto_fit_set_symbol_enabled = getattr(args_for_optional_features, 'auto_fit_set_symbol', False)
            self.set_symbol_override_code = getattr(args_for_optional_features, 'set_symbol_override', None)
            # self.use_live_rarity_for_override flag is removed from here and __init__

            if self.auto_fit_art_enabled: self.logger.info("Opt Feature: Auto Fit Art ENABLED")
            if self.auto_fit_set_symbol_enabled: self.logger.info("Opt Feature: Auto Fit Set Symbol (Reset) ENABLED")
            if self.set_symbol_override_code: 
                self.logger.info(f"Opt Feature: Set Symbol Override with code '{self.set_symbol_override_code}' (will use live rarity).")
        
        try:
            self.setup_driver(headless=headless)
            if not self.navigate_to_card_conjurer(): return # Sets _current_active_tab to 'art' or None
            time.sleep(self.delays['js_init'])
            if frame and not self.set_auto_frame(frame): self.logger.warning(f"Failed frame '{frame}'.")
            
            if cardconjurer_file:
                if not self.upload_cardconjurer_file(cardconjurer_file): 
                    self.logger.error(f"Fail upload/load from: {cardconjurer_file}. Abort."); return
            elif not cardconjurer_file: 
                self.logger.info("No file. Check existing cards...");
                on_imp = self._navigate_to_creator_tab("import") 
                if on_imp and not self.check_cards_loaded(): self.logger.warning("No cards loaded (dropdown).")
                elif not on_imp: self.logger.warning("Cannot check cards, import nav fail.")

            if action=="zip":
                if not self.cards: self.get_saved_cards() # Ensures 'import' tab
                if not self.cards: self.logger.error("No cards to zip."); return
                res_zip=self.create_zip_of_all_cards() # Handles its own tab navigation for capture
                if res_zip: self.logger.info(f"ZIP: {res_zip}")
                else: self.logger.error("ZIP fail/empty.")
        except Exception as e: self.logger.error(f"Unhandled run err: {e}",exc_info=True)
        finally:
            if self.driver:
                if not headless and sys.stdin.isatty():
                    try: input("Press Enter to close browser...")
                    except EOFError: self.logger.info("Non-interactive, closing.")
                self.driver.quit(); self.logger.info("Browser closed.")

def main():
    p = argparse.ArgumentParser(description='Card Conjurer Downloader - Smart Canvas Capture with Full Optional Features (v4)')
    p.add_argument('--file','-f',required=True,help='.cardconjurer file to load')
    p.add_argument('--url',default='http://mtgproxy:4242',help='Card Conjurer URL')
    p.add_argument('--output',default=None,help='Output directory for ZIP and logs')
    p.add_argument('--headless',action='store_true',help='Run in headless mode')
    p.add_argument('--frame',choices=['7th','seventh','8th','eighth','m15','ub'],help='Auto frame setting')
    p.add_argument('--log-level',default='INFO',choices=['DEBUG','INFO','WARNING','ERROR'],help='Console logging level')
    
    # New Optional Feature Arguments (use_live_rarity removed)
    p.add_argument('--auto-fit-art', action='store_true', help='Enable Auto Fit Art feature.')
    p.add_argument('--auto-fit-set-symbol', action='store_true', help='Enable Reset Set Symbol (auto fit) feature.')
    p.add_argument('--set-symbol-override', type=str, default=None, metavar='CODE', 
                       help='Override set symbol with CODE (e.g., "MH2"). Live rarity from Collector tab will be used.')
    
    a = p.parse_args()
    if not os.path.exists(a.file): print(f"Error: File not found: {a.file}");sys.exit(1)
    log_lvl_val = getattr(logging, a.log_level.upper(), logging.INFO)
    
    downloader = CardConjurerDownloader(url=a.url,download_dir=a.output,log_level=log_lvl_val)
    downloader.run(cardconjurer_file=a.file,headless=a.headless,frame=a.frame, args_for_optional_features=a)

if __name__ == "__main__":
    main()
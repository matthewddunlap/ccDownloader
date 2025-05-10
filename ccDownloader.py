"""
Card Conjurer Selenium Downloader - Smart Canvas Capture Version (with Optional Features)

Captures card images directly from the canvas using toDataURL and zips them.
Uses a smart wait to detect canvas changes and stabilization.
Includes optional features for art and set symbol manipulation.

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
# from selenium.webdriver.common.keys import Keys # Import if using send_keys(Keys.ENTER) for onchange trigger

class CardConjurerDownloader:
    def __init__(self, url="http://mtgproxy:4242", download_dir=None, log_level=logging.INFO):
        self.url = url
        self.download_dir = download_dir or os.path.join(os.path.expanduser("~"), "Downloads", "CardConjurer")
        self.driver = None
        self.cards = []
        self._current_active_tab: Optional[str] = None # Tracks 'art', 'setSymbol', 'import', etc. or None for main view

        # Optional features states - will be set in run()
        self.auto_fit_art_enabled = False
        self.auto_fit_set_symbol_enabled = False # This corresponds to "Reset Set Symbol"
        self.set_symbol_override_code = None

        self.delays = {
            'page_load': 0.1,
            'tab_switch': 0.1, # Base delay for tab switching animation/JS
            'file_upload_wait': 10.0, 
            'card_load_js_ops': 0.2, # Minimal delay after JS load ops in load_card
            'frame_set': 0.1,
            'element_wait': 3.0, 
            'js_init': 0.1,
            'canvas_stabilize_timeout': 15.0, # Max time for canvas to change & stabilize
            'canvas_stability_checks': 3,     # How many stable checks needed
            'canvas_stability_interval': 0.33, # Interval between stability checks
            'art_fit_wait': 0.75,             # Delay after clicking auto fit art
            'set_symbol_reset_wait': 0.75,  # Delay after clicking reset set symbol
            'set_symbol_fetch_wait': 1.5    # Delay after changing set symbol code for fetch
        }

        Path(self.download_dir).mkdir(parents=True, exist_ok=True)
        self.setup_logging(log_level)
        self.logger.info(f"Initialized CC Downloader (Smart Canvas Capture + Opt Features)")
        self.logger.info(f"URL: {self.url}")
        self.logger.info(f"Output directory: {self.download_dir}")

    def setup_logging(self, log_level):
        log_dir = Path(self.download_dir) / "logs"
        log_dir.mkdir(exist_ok=True)
        self.logger = logging.getLogger('CardConjurer')
        self.logger.setLevel(logging.DEBUG) 
        if self.logger.handlers: 
            self.logger.handlers.clear()
        detailed_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s')
        simple_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file_name = log_dir / f"cardconjurer_smart_opts_{timestamp}.log" # Updated log name
        file_handler = logging.FileHandler(log_file_name)
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(detailed_formatter)
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(log_level)
        console_handler.setFormatter(simple_formatter)
        self.logger.addHandler(file_handler)
        self.logger.addHandler(console_handler)
        self.logger.info(f"Logging initialized. Log file: {log_file_name}")

    def setup_driver(self, headless=False):
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

    def wait_for_element(self, selector, by=By.CSS_SELECTOR, timeout=None):
        timeout = timeout or self.delays['element_wait']
        try: 
            return WebDriverWait(self.driver, timeout).until(EC.presence_of_element_located((by, selector)))
        except TimeoutException: 
            self.logger.debug(f"Timeout waiting for element: {by}='{selector}'")
            return None

    def wait_for_clickable(self, selector, by=By.CSS_SELECTOR, timeout=None):
        timeout = timeout or self.delays['element_wait']
        try: 
            return WebDriverWait(self.driver, timeout).until(EC.element_to_be_clickable((by, selector)))
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
                time.sleep(0.1) # Brief pause after scroll
                self.driver.execute_script("arguments[0].click();", element)
                return True
            except Exception as e_js_click: 
                self.logger.error(f"JS click also failed: {e_js_click}")
                return False
        except Exception as e_click: 
            self.logger.error(f"Other error clicking element: {e_click}")
            return False

    def _navigate_to_creator_tab(self, target_tab_name: str) -> bool:
        """
        Navigates to a specific creator tab (e.g., 'art', 'setSymbol', 'import').
        Updates self._current_active_tab.
        """
        if self._current_active_tab == target_tab_name:
            self.logger.debug(f"Already on '{target_tab_name}' tab.")
            return True

        self.logger.info(f"Navigating to '{target_tab_name}' tab...")
        # Selector for tab buttons: h3[onclick*="toggleCreatorTabs(event, 'TARGET_TAB_NAME')"]
        tab_selector = f"h3[onclick*='toggleCreatorTabs(event, \"{target_tab_name}\")']"
        
        tab_button = self.wait_for_clickable(tab_selector, timeout=3)
        if tab_button:
            if self.click_element_safely(tab_button):
                self.logger.info(f"Successfully clicked the '{target_tab_name}' tab.")
                self._current_active_tab = target_tab_name
                time.sleep(self.delays['tab_switch'] + 0.3) # Increased delay for tab content
                return True
            else:
                self.logger.error(f"Failed to click the '{target_tab_name}' tab button ({tab_selector}).")
                self._current_active_tab = None # Tab state unknown
                return False
        else:
            self.logger.error(f"'{target_tab_name}' tab button ({tab_selector}) not found or not clickable.")
            self._current_active_tab = None # Tab state unknown
            return False

    def navigate_to_card_conjurer(self):
        self.logger.info(f"Navigating to Card Conjurer: {self.url}")
        self.driver.get(self.url)
        if self.wait_for_element("canvas", timeout=10): 
            self.logger.info("Canvas found, page appears ready.")
            self._current_active_tab = "art" # Assume 'art' or main view is default with canvas
            return True
        self.logger.error("Canvas not found after page load. Card Conjurer may not have loaded correctly.")
        return False

    def upload_cardconjurer_file(self, file_path):
        self.logger.info(f"Uploading file: {file_path}")
        if not os.path.exists(file_path): 
            self.logger.error(f"File not found: {file_path}"); return False
        
        # Ensure on import tab for upload
        if not self._navigate_to_creator_tab("import"):
            self.logger.error("Failed to navigate to 'import' tab for file upload.")
            return False
        
        self.logger.info("Attempting to find the file input element on the import tab...")
        file_input_selectors = [
            "input#importProject[type='file']", 
            "input[type='file'][accept*='.cardconjurer']", 
            "input[type='file'][oninput*='uploadSavedCards']",
            "input[type='file']", 
        ]
        file_input_element = None
        # Refined finding logic (two passes: visible then hidden, prioritizing specific)
        for pass_type in ["VISIBLE", "HIDDEN"]:
            found_in_pass = False
            for selector in file_input_selectors:
                self.logger.debug(f"Trying {pass_type} file input selector: {selector}")
                try:
                    elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                    for el in elements:
                        is_el_displayed = el.is_displayed()
                        if (pass_type == "VISIBLE" and not is_el_displayed) or \
                           (pass_type == "HIDDEN" and is_el_displayed and file_input_element and file_input_element.is_displayed()): # If already found a visible one, skip hidden pass for this selector
                            continue

                        el_accept = el.get_attribute('accept') or ""
                        el_oninput = el.get_attribute('oninput') or ""
                        is_specific = ('.cardconjurer' in el_accept or '.txt' in el_accept) or \
                                      ('uploadSavedCards' in el_oninput)
                        
                        current_candidate = None
                        if is_specific: current_candidate = el
                        elif not file_input_element: current_candidate = el # Take first generic if no specific found yet in this pass

                        if current_candidate:
                            if not file_input_element or \
                               (is_specific and (not file_input_element.get_attribute('oninput') or 'uploadSavedCards' not in file_input_element.get_attribute('oninput'))) or \
                               (is_el_displayed and not file_input_element.is_displayed()): # Prioritize specific, then visible
                                file_input_element = current_candidate
                                self.logger.info(f"Found candidate {pass_type} file input (specific: {is_specific}): {selector}")
                        
                        if file_input_element and is_specific and (is_el_displayed if pass_type == "VISIBLE" else True):
                            found_in_pass = True; break # Found best possible for this selector type
                except Exception as e_find:
                    self.logger.debug(f"Error finding {pass_type} selector {selector}: {e_find}")
                if found_in_pass and file_input_element and (file_input_element.is_displayed() if pass_type == "VISIBLE" else True) : break # Found best for this pass type
            if file_input_element and file_input_element.is_displayed(): break # If a visible one was found, stop.
            elif file_input_element and pass_type == "HIDDEN": break # If only hidden found, use it.


        if not file_input_element:
            self.logger.error("Could not find a suitable file input element on the import tab.")
            return False
        
        if not file_input_element.is_displayed():
             self.logger.warning(f"Using a HIDDEN file input element. Attempting to make it visible for interaction.")

        try:
            self.logger.info(f"Using file input element: Tag={file_input_element.tag_name}, ID='{file_input_element.get_attribute('id')}', Class='{file_input_element.get_attribute('class')}', Accept='{file_input_element.get_attribute('accept')}', OnInput='{file_input_element.get_attribute('oninput')}'")
            self.driver.execute_script(
                "arguments[0].style.opacity=1; arguments[0].style.display='block'; arguments[0].style.visibility='visible'; arguments[0].disabled=false; arguments[0].removeAttribute('hidden');", 
                file_input_element
            )
            time.sleep(0.2) 
            file_input_element.send_keys(os.path.abspath(file_path)) 
            self.logger.info(f"File path '{os.path.abspath(file_path)}' sent to input element.")
        except Exception as e:
            self.logger.error(f"Error sending file path: {e}", exc_info=True)
            return False

        self.logger.info("Waiting for cards to load from file...")
        try:
            WebDriverWait(self.driver, self.delays['file_upload_wait']).until(self.check_cards_loaded) # Pass method directly
            self.logger.info("Cards loaded successfully after file upload.")
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
                    self.logger.info("'uploadSavedCards' function EXISTS. Failure might be due to event not triggering this handler.")
                else: self.logger.info("'uploadSavedCards' function does NOT exist.") 
            except Exception as e_js_check_upload: self.logger.warning(f"Error checking for 'uploadSavedCards' JS function: {e_js_check_upload}")
            return False

    def check_cards_loaded(self, driver_instance=None) -> bool:
        driver_to_use = driver_instance if driver_instance else self.driver
        try:
            card_select = driver_to_use.find_element(By.ID, "load-card-options")
            options = card_select.find_elements(By.TAG_NAME, "option")
            # Check if there's at least one valid card option beyond placeholders
            return any(opt.text.strip() and opt.text.strip().lower() not in ['none selected', 'load a saved card', ''] for opt in options)
        except NoSuchElementException:
            self.logger.debug("check_cards_loaded: 'load-card-options' not found.")
            return False
        except Exception as e:
            self.logger.debug(f"check_cards_loaded: Error checking cards: {e}")
            return False
        
    def get_saved_cards(self) -> list:
        self.logger.info("Getting list of saved cards...")
        self.cards = [] # Reset internal list
        
        # Ensure on import tab to access card list
        if not self._navigate_to_creator_tab("import"):
            self.logger.error("Cannot navigate to 'import' tab for get_saved_cards.")
            return [] # Return empty list if navigation fails

        try:
            card_select = self.wait_for_element("load-card-options", by=By.ID, timeout=5)
            if not card_select:
                self.logger.error("'load-card-options' select element not found.")
                return []
            options = card_select.find_elements(By.TAG_NAME, "option")
            cards_found = []
            for option in options:
                card_name = option.get_attribute("value").strip() 
                if card_name and card_name.lower() not in ['none selected', 'load a saved card', '']:
                    cards_found.append(card_name)
            self.logger.info(f"Found {len(cards_found)} saved cards: {cards_found[:5] if cards_found else 'None'}") 
            self.cards = cards_found # Update instance variable
            return cards_found
        except Exception as e:
            self.logger.error(f"Error getting saved cards: {e}", exc_info=True)
            return [] # Return empty on error

    def set_auto_frame(self, frame_option: str) -> bool:
        if not frame_option: return True # No option, success
        self.logger.info(f"Setting auto frame to: {frame_option}")
        frame_mapping = {'7th': 'Seventh', 'seventh': 'Seventh', '8th': 'Eighth', 'eighth': 'Eighth', 'm15': 'M15Eighth', 'ub': 'M15EighthUB'}
        dropdown_value = frame_mapping.get(frame_option.lower())
        if not dropdown_value:
            self.logger.error(f"Invalid frame option: {frame_option}. Mapped value not found.")
            return False
        try:
            self.logger.debug(f"Attempting to set auto frame to '{dropdown_value}' using Selenium Select.")
            select_element = self.wait_for_element("autoFrame", by=By.ID, timeout=5)
            if not select_element: self.logger.error("autoFrame select element not found."); return False
            Select(select_element).select_by_value(dropdown_value)
            self.logger.info(f"Successfully set auto frame to '{dropdown_value}' using Selenium Select.")
            time.sleep(self.delays['frame_set'] + 0.5)
            return True
        except Exception as e: 
            self.logger.warning(f"Selenium Select for auto frame failed: {e}. Trying JS fallback.")
            try:
                self.driver.execute_script(f"var s=document.getElementById('autoFrame'); s.value='{dropdown_value}'; s.dispatchEvent(new Event('change',{{'bubbles':true}}));")
                self.logger.info(f"Set auto frame to '{dropdown_value}' via JS fallback.")
                time.sleep(self.delays['frame_set'] + 0.5)
                return True
            except Exception as e_js:
                self.logger.error(f"JS fallback for auto frame also failed: {e_js}")
                return False

    def load_card(self, card_name: str) -> bool:
        self.logger.info(f"Loading card: '{card_name}' using JavaScript method.")
        # This method assumes it's being called when the 'import' tab is active
        # and 'load-card-options' is present.
        try:
            card_select_element = self.wait_for_element("load-card-options", By.ID, timeout=3)
            if not card_select_element:
                self.logger.error("Cannot find 'load-card-options' dropdown to load card.")
                return False

            js_escaped_card_name = json.dumps(card_name)
            
            self.logger.debug(f"JS: Setting 'load-card-options' value to {js_escaped_card_name}")
            start_time_val_set = time.perf_counter()
            self.driver.execute_script(f"document.getElementById('load-card-options').value = {js_escaped_card_name};")
            self.logger.debug(f"JS: Set value took {time.perf_counter() - start_time_val_set:.4f}s")

            self.logger.debug(f"JS: Dispatching 'change' event on 'load-card-options' for {js_escaped_card_name}")
            start_time_dispatch = time.perf_counter()
            self.driver.execute_script(f"""
                var select = document.getElementById('load-card-options');
                var event = new Event('change', {{ 'bubbles': true }});
                select.dispatchEvent(event);
            """)
            change_event_duration = time.perf_counter() - start_time_dispatch
            self.logger.debug(f"JS: Dispatch 'change' event took {change_event_duration:.4f}s")

            if change_event_duration < 1.0: 
                self.logger.debug("Change event was fast, checking/calling global loadCard().")
                if self.driver.execute_script("return typeof loadCard === 'function';"):
                    start_time_global_call = time.perf_counter()
                    self.driver.execute_script(f"loadCard({js_escaped_card_name});")
                    self.logger.debug(f"JS: Global loadCard() call took {time.perf_counter() - start_time_global_call:.4f}s")
                else:
                    self.logger.debug("JS: Global loadCard() function not found.")
            else:
                self.logger.info(f"JS: Dispatch 'change' event was slow ({change_event_duration:.4f}s), assuming it handled card loading.")

            time.sleep(self.delays['card_load_js_ops']) 
            self.logger.info(f"JS operations for card load '{card_name}' completed.")
            # After loading, the active tab might implicitly change in CC, or stay on 'import'.
            # We will explicitly navigate to 'art' (or other capture tab) before canvas capture.
            # Do not set self._current_active_tab here, let subsequent operations manage it.
            return True
        except Exception as e:
            self.logger.error(f"Error during JavaScript-based loading of card '{card_name}': {e}", exc_info=True)
            return False

    def apply_auto_fit_art(self) -> bool:
        self.logger.info("Applying Auto Fit Art...")
        if not self._navigate_to_creator_tab("art"): return False
        button_selector = "button.input[onclick='autoFitArt();']"
        auto_fit_button = self.wait_for_clickable(button_selector, timeout=3)
        if auto_fit_button and self.click_element_safely(auto_fit_button):
            self.logger.info("Clicked 'Auto Fit Art' button.")
            time.sleep(self.delays['art_fit_wait'])
            return True
        self.logger.error(f"'Auto Fit Art' button ({button_selector}) not found/clickable."); return False

    def apply_auto_fit_set_symbol(self) -> bool: # This is "Reset Set Symbol"
        self.logger.info("Applying Reset Set Symbol (Auto Fit)...")
        if not self._navigate_to_creator_tab("setSymbol"): return False
        button_selector = "button.input[onclick='resetSetSymbol();']"
        reset_button = self.wait_for_clickable(button_selector, timeout=3)
        if reset_button and self.click_element_safely(reset_button):
            self.logger.info("Clicked 'Reset Set Symbol' button.")
            time.sleep(self.delays['set_symbol_reset_wait'])
            return True
        self.logger.error(f"'Reset Set Symbol' button ({button_selector}) not found/clickable."); return False

    def apply_set_symbol_override(self, set_code: str) -> bool:
        self.logger.info(f"Applying Set Symbol Override with code: '{set_code}'")
        if not self._navigate_to_creator_tab("setSymbol"): return False
        input_selector = "input#set-symbol-code[onchange='fetchSetSymbol();']"
        code_input = self.wait_for_element(input_selector, timeout=3)
        if code_input:
            try:
                self.click_element_safely(code_input) 
                code_input.clear()
                self.logger.debug("Cleared set symbol code input.")
                code_input.send_keys(set_code)
                self.logger.info(f"Entered '{set_code}' into set symbol code input.")
                self.driver.execute_script("arguments[0].dispatchEvent(new Event('change', {bubbles: true}));", code_input)
                self.logger.info("Dispatched 'change' event for set symbol code input.")
                time.sleep(self.delays['set_symbol_fetch_wait'])
                return True
            except Exception as e:
                self.logger.error(f"Error interacting with set symbol code input ({input_selector}): {e}")
                return False
        self.logger.error(f"Set symbol code input ({input_selector}) not found."); return False

    def wait_for_canvas_change_and_stabilization(self, initial_data_url_hash: Optional[str]) -> Optional[str]:
        self.logger.debug(f"Waiting for canvas to change (from hash: {str(initial_data_url_hash)[:10]}...) and stabilize...")
        start_time = time.perf_counter()
        timeout = self.delays['canvas_stabilize_timeout']
        stability_checks_needed = self.delays['canvas_stability_checks']
        interval = self.delays['canvas_stability_interval']

        js_get_data_url = """
            const canvasSelectors = ['#mainCanvas', '#canvas', 'canvas'];
            let canvas = null;
            for (let selector of canvasSelectors) {
                canvas = document.querySelector(selector);
                if (canvas) break;
            }
            if (!canvas || canvas.width === 0 || canvas.height === 0) return 'canvas_error:no_canvas_or_zero_dims';
            try { return canvas.toDataURL('image/png'); }
            catch (e) { console.error('CardConjurer Automation: Error in toDataURL during wait: ', e); return 'canvas_error:to_data_url_failed'; }
        """
        last_hash = initial_data_url_hash
        current_hash = initial_data_url_hash # Ensure it's initialized
        stable_count = 0
        # If initial_data_url_hash is None (first card), we need to establish a baseline first, then detect change from that or just stabilize.
        # For simplicity: if initial_hash is None, first stable state is the "changed" state.
        changed_from_initial = False if initial_data_url_hash is not None else True 

        while time.perf_counter() - start_time < timeout:
            try:
                current_data_url = self.driver.execute_script(js_get_data_url)
                if isinstance(current_data_url, str) and current_data_url.startswith('canvas_error:'):
                    self.logger.warning(f"Canvas JS error during stabilization: {current_data_url}")
                    time.sleep(interval); continue
                if not current_data_url:
                    self.logger.debug("Canvas data URL is null during stabilization wait.")
                    time.sleep(interval); continue
                
                current_hash = hashlib.md5(current_data_url.encode('utf-8')).hexdigest()
            except Exception as e:
                self.logger.warning(f"Python exception getting/hashing canvas data: {e}"); time.sleep(interval); continue

            if not changed_from_initial: # Only if we have an initial hash to compare against
                if current_hash != initial_data_url_hash:
                    self.logger.debug(f"Canvas content changed from initial. New hash: {current_hash[:10]}...")
                    changed_from_initial = True
                    last_hash = current_hash # This new hash is now the one we check for stability
                    stable_count = 1 # First check of a new state counts as 1 stable
                else: # Still same as initial, keep waiting for change
                    self.logger.debug(f"Canvas still same as initial ({initial_data_url_hash[:10]}). Waiting for change.")
                    last_hash = initial_data_url_hash # Ensure last_hash remains initial_hash
                    stable_count = 0 # Not yet stable in a *new* state
            
            # This block executes if changed_from_initial is True (either was set above or started as True)
            if changed_from_initial:
                if current_hash == last_hash:
                    stable_count += 1
                    self.logger.debug(f"Canvas hash stabilized ({stable_count}/{stability_checks_needed}): {current_hash[:10]}...")
                    if stable_count >= stability_checks_needed:
                        self.logger.info(f"Canvas stabilized to new hash: {current_hash[:10]}.")
                        return current_hash
                else: # Hash changed again, reset stability
                    self.logger.debug(f"Canvas hash changed: {current_hash[:10]} from {last_hash[:10]}. Resetting stability.")
                    stable_count = 1 # This new hash is the first stable check
                last_hash = current_hash
            
            time.sleep(interval)

        self.logger.warning("Timeout waiting for canvas to stabilize after change."); return None

    def capture_card_image_data_from_canvas(self, card_name: str, previous_canvas_hash: Optional[str]) -> Tuple[Optional[bytes], Optional[str]]:
        self.logger.info(f"Preparing to capture canvas for: {card_name}")
        new_stabilized_hash = self.wait_for_canvas_change_and_stabilization(previous_canvas_hash)

        # If stabilization failed OR it stabilized to the SAME hash as before (meaning no change was detected)
        if not new_stabilized_hash or (previous_canvas_hash and new_stabilized_hash == previous_canvas_hash):
            self.logger.error(f"Canvas did not change and stabilize to a NEW state for '{card_name}'. Previous hash: {str(previous_canvas_hash)[:10]}, New hash attempt: {str(new_stabilized_hash)[:10]}")
            return None, previous_canvas_hash # Return old hash as state hasn't meaningfully changed for capture

        # Now that it's stable at a NEW hash, get the final data URL
        js_get_data_url = """
            const cSels=['#mainCanvas','#canvas','canvas']; let c=null; for(let s of cSels){c=document.querySelector(s);if(c)break;}
            if(!c||c.width===0||c.height===0)return null; try{return c.toDataURL('image/png');}catch(e){return 'error';}
        """
        try:
            self.logger.debug(f"Executing JS to get FINAL canvas data URL for '{card_name}'.")
            start_time_final_capture = time.perf_counter()
            data_url = self.driver.execute_script(js_get_data_url)
            self.logger.debug(f"JS for FINAL canvas data URL took {time.perf_counter() - start_time_final_capture:.4f}s.")

            if data_url and data_url.startswith('data:image/png;base64,'):
                base64_data = data_url.split(',', 1)[1]
                image_bytes = base64.b64decode(base64_data)
                if len(image_bytes) < 1024 : # Basic sanity check
                    self.logger.warning(f"Captured image for '{card_name}' is very small ({len(image_bytes)} bytes). May be blank or error.")
                else:
                    self.logger.info(f"Successfully captured FINAL canvas image data for '{card_name}' ({len(image_bytes)} bytes).")
                return image_bytes, new_stabilized_hash 
            elif data_url == 'error':
                 self.logger.error(f"JS error during FINAL toDataURL for '{card_name}'.")
                 return None, previous_canvas_hash 
            else:
                self.logger.error(f"Failed to get valid FINAL image data URL from canvas for '{card_name}'. Received: {str(data_url)[:100]}")
                return None, previous_canvas_hash
        except Exception as e:
            self.logger.error(f"Error capturing FINAL canvas image for '{card_name}': {e}", exc_info=True)
            return None, previous_canvas_hash

    def create_zip_of_all_cards(self):
        self.logger.info("Starting ZIP creation (Smart Canvas + Opt Features)")
        current_canvas_hash: Optional[str] = None 
        
        if not self.cards:
            self.logger.info("Card list is empty, attempting to fetch from dropdown...")
            self.get_saved_cards() # get_saved_cards ensures it navigates to "import"
        
        if not self.cards:
            self.logger.error("No cards found to process for ZIP file.")
            return None
        
        # Capture initial canvas hash from the 'art' tab (main card view) before processing cards
        # This helps the first card's change detection.
        self.logger.info("Attempting to capture initial canvas hash from 'art' tab...")
        if self._navigate_to_creator_tab("art"): # Switch to art tab
            initial_wait_js = """
                const cSels=['#mainCanvas','#canvas','canvas']; let c=null; for(let s of cSels){c=document.querySelector(s);if(c)break;}
                if(!c||c.width===0||c.height===0)return null; try{return c.toDataURL('image/png');}catch(e){return 'error';}
            """
            initial_data_url = self.driver.execute_script(initial_wait_js)
            if initial_data_url and initial_data_url.startswith('data:image/png;base64,'):
                 current_canvas_hash = hashlib.md5(initial_data_url.encode('utf-8')).hexdigest()
                 self.logger.info(f"Captured initial canvas hash from 'art' tab: {current_canvas_hash[:10]}...")
            else:
                self.logger.warning(f"Could not capture a valid initial canvas hash from 'art' tab. Received: {str(initial_data_url)[:50]}")
        else:
            self.logger.warning("Failed to navigate to 'art' tab for initial canvas hash. First card may use simpler stabilization.")

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        zip_filename_path = Path(self.download_dir) / f"CardConjurer_SmartCanvasOpt_{timestamp}.zip"
        self.logger.info(f"Creating ZIP file: {zip_filename_path}")
        
        successful_cards = 0
        failed_cards = []
        
        try:
            with zipfile.ZipFile(zip_filename_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for i, card_name in enumerate(self.cards):
                    self.logger.info(f"Processing card {i+1}/{len(self.cards)}: '{card_name}'")
                    
                    # 1. Ensure on Import tab to load card from dropdown
                    if not self._navigate_to_creator_tab("import"):
                        self.logger.error(f"Failed to navigate to 'import' tab to load '{card_name}'. Skipping.")
                        failed_cards.append(f"{card_name} (import tab nav failed)")
                        continue

                    # 2. Load the card (this happens on the 'import' tab)
                    if not self.load_card(card_name):
                        self.logger.warning(f"Failed to load card: {card_name}")
                        failed_cards.append(f"{card_name} (load failed)")
                        continue # Skip to next card
                    
                    # --- 3. Apply optional features (these will navigate tabs as needed) ---
                    if self.set_symbol_override_code:
                        if not self.apply_set_symbol_override(self.set_symbol_override_code):
                            self.logger.warning(f"Failed to apply set symbol override for '{card_name}'.")
                    
                    if self.auto_fit_set_symbol_enabled: # This is "Reset Set Symbol"
                        if not self.apply_auto_fit_set_symbol():
                            self.logger.warning(f"Failed to apply auto fit (reset) set symbol for '{card_name}'.")

                    if self.auto_fit_art_enabled:
                        if not self.apply_auto_fit_art():
                            self.logger.warning(f"Failed to apply auto fit art for '{card_name}'.")
                    
                    # --- 4. Navigate to 'art' tab (or best canvas view tab) for capture ---
                    capture_tab_name = "art" # Define your primary canvas viewing tab here
                    self.logger.info(f"Ensuring on '{capture_tab_name}' tab for canvas capture of '{card_name}'.")
                    if not self._navigate_to_creator_tab(capture_tab_name):
                        self.logger.error(f"Failed to navigate to '{capture_tab_name}' tab for capture. Skipping capture.")
                        failed_cards.append(f"{card_name} (capture tab nav failed)")
                        continue 
                    
                    # --- 5. Capture Canvas for Card ---
                    image_bytes, new_hash = self.capture_card_image_data_from_canvas(card_name, current_canvas_hash)
                    current_canvas_hash = new_hash # Update for the next iteration
                    
                    if image_bytes:
                        sanitized_arcname = "".join(c for c in card_name if c.isalnum() or c in (' ', '-', '_')).rstrip()
                        archive_filename = f"{sanitized_arcname}.png" 
                        zipf.writestr(archive_filename, image_bytes)
                        self.logger.info(f"Added '{archive_filename}' to ZIP from canvas data.")
                        successful_cards += 1
                    else:
                        self.logger.warning(f"Failed to capture image data for card: {card_name}")
                        failed_cards.append(f"{card_name} (capture failed)")
        except Exception as e:
            self.logger.error(f"Error during ZIP file creation: {e}", exc_info=True)
            if os.path.exists(zip_filename_path): os.remove(zip_filename_path)
            return None
        
        self.logger.info(f"ZIP creation summary: Successfully processed {successful_cards}/{len(self.cards)} cards.")
        if failed_cards: self.logger.warning(f"Failed cards ({len(failed_cards)}): {', '.join(failed_cards)}")
        
        return str(zip_filename_path) if successful_cards > 0 else None

    def run(self, cardconjurer_file=None, action="zip", headless=False, frame=None, args_for_optional_features=None):
        self.logger.info(f"Run (Smart Canvas + Opts) action:{action} headless:{headless} frame:{frame}")
        
        if args_for_optional_features: # Set optional feature flags from parsed args
            self.auto_fit_art_enabled = getattr(args_for_optional_features, 'auto_fit_art', False)
            self.auto_fit_set_symbol_enabled = getattr(args_for_optional_features, 'auto_fit_set_symbol', False)
            self.set_symbol_override_code = getattr(args_for_optional_features, 'set_symbol_override', None)

            if self.auto_fit_art_enabled: self.logger.info("Optional Feature Enabled: Auto Fit Art")
            if self.auto_fit_set_symbol_enabled: self.logger.info("Optional Feature Enabled: Auto Fit Set Symbol (Reset)")
            if self.set_symbol_override_code: self.logger.info(f"Optional Feature Enabled: Set Symbol Override with code '{self.set_symbol_override_code}'")
        
        try:
            self.setup_driver(headless=headless)
            if not self.navigate_to_card_conjurer(): return # Sets _current_active_tab to 'art' or None
            time.sleep(self.delays['js_init'])

            if frame and not self.set_auto_frame(frame): 
                self.logger.warning(f"Failed to set auto frame to '{frame}'. Continuing...")
            
            if cardconjurer_file:
                if not self.upload_cardconjurer_file(cardconjurer_file): # Navigates to 'import'
                    self.logger.error(f"Failed to upload/load cards from file: {cardconjurer_file}. Aborting.")
                    return
            elif not cardconjurer_file: # No file provided, check for existing cards
                self.logger.info("No .cardconjurer file provided. Checking for already loaded cards...")
                # Ensure on import tab to check_cards_loaded (which checks dropdown)
                on_import_tab_for_check = self._navigate_to_creator_tab("import")
                if on_import_tab_for_check and not self.check_cards_loaded(): 
                    self.logger.warning("No cards seem to be loaded in Card Conjurer (checked dropdown).")
                elif not on_import_tab_for_check: 
                    self.logger.warning("Cannot check for loaded cards as import page navigation failed.")

            if action == "zip":
                # get_saved_cards ensures it's on 'import' tab before trying to read the dropdown
                if not self.cards: self.get_saved_cards() 
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
                if not headless and sys.stdin.isatty(): # Check if running in interactive terminal
                    try: input("\nPress Enter to close the browser...")
                    except EOFError: self.logger.info("Non-interactive session or input redirected, closing browser automatically.")
                self.driver.quit()
                self.logger.info("Browser closed.")

def main():
    parser = argparse.ArgumentParser(description='Card Conjurer Downloader - Smart Canvas Capture Version with Optional Features')
    parser.add_argument('--file', '-f', required=True, help='Path to .cardconjurer file to load')
    parser.add_argument('--url', default='http://mtgproxy:4242', help='Card Conjurer URL')
    parser.add_argument('--output', default=None, help='Output directory for ZIP and logs (default: ~/Downloads/CardConjurer)')
    parser.add_argument('--headless', action='store_true', help='Run in headless mode')
    parser.add_argument('--frame', choices=['7th', 'seventh', '8th', 'eighth', 'm15', 'ub'], help='Auto frame setting to use')
    parser.add_argument('--log-level', default='INFO', choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'], help='Set logging level for console')
    
    # New Optional Feature Arguments
    parser.add_argument('--auto-fit-art', action='store_true', 
                        help='Enable Auto Fit Art feature after loading each card.')
    parser.add_argument('--auto-fit-set-symbol', action='store_true', 
                        help='Enable Reset Set Symbol (auto fit) feature after loading each card.')
    parser.add_argument('--set-symbol-override', type=str, default=None, metavar='CODE',
                        help='Override the set symbol with the provided set code (e.g., "MH2").')
    
    args = parser.parse_args()
    
    if not os.path.exists(args.file):
        print(f"Error: File not found: {args.file}"); sys.exit(1)
    
    log_level_val = getattr(logging, args.log_level.upper(), logging.INFO)

    downloader = CardConjurerDownloader(url=args.url, download_dir=args.output, log_level=log_level_val)
    downloader.run(
        cardconjurer_file=args.file,
        headless=args.headless,
        frame=args.frame,
        args_for_optional_features=args # Pass the whole args namespace
    )

if __name__ == "__main__":
    main()
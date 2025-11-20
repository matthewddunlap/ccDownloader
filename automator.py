import time
import re
import os
import base64
import sys
import hashlib
import random
import requests
from urllib.parse import urljoin
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from datetime import datetime, timedelta, timezone
from pathlib import Path
from gradio_client import Client, file as gradio_file
from PIL import Image
import io
import unicodedata
from typing import Optional, Tuple, List

# Import utilities
from automator_utils import (
    parse_time_string,
    check_server_file_details,
    generate_safe_filename,
    get_image_mime_type_and_extension,
)

# Import Mixins
from mixins import CanvasMixin, TextMixin, ImageMixin, PrintMixin

# Import Scryfall API utilities from the local package
try:
    from scryfall_utils import ScryfallAPI
except ImportError:
    print("FATAL: Could not import ScryfallAPI from local 'scryfall_utils.py'.", file=sys.stderr)
    sys.exit(1)

class CardConjurerAutomator(CanvasMixin, TextMixin, ImageMixin, PrintMixin):
    """
    A class to automate interactions with the Card Conjurer web application.
    """
    def __init__(self, url, download_dir='.', headless=True, include_sets=None,
                 exclude_sets=None, card_selection_strategy='cardconjurer', set_selection_strategy='earliest',
                 no_match_selection='earliest', render_delay=1.5, white_border=False,
                 pt_bold=False, pt_shadow=None, pt_font_size=None, pt_kerning=None, pt_up=None,
                 title_font_size=None, title_shadow=None, title_kerning=None, title_left=None,
                 type_font_size=None, type_shadow=None, type_kerning=None, type_left=None,
                 flavor_font=None, rules_down=None, rules_bounds_y=None, rules_bounds_height=None,
                 hide_reminder_text=False,
                 image_server=None, image_server_path=None, art_path='/art/', autofit_art=False,
                 upscale_art=False, ilaria_url=None, upscaler_model='RealESRGAN_x2plus', upscaler_factor=4,
                 upload_path=None, upload_secret=None,
                 overwrite=False, overwrite_older_than=None, overwrite_newer_than=None):
        """
        Initializes the WebDriver and stores the automation strategy.
        """
        self.download_dir = download_dir
        # Only create the directory if a path was actually provided
        if self.download_dir and not os.path.exists(self.download_dir):
            os.makedirs(self.download_dir)

        chrome_options = Options()
        if headless:
            chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--window-size=1200,900")
        self.driver = webdriver.Chrome(options=chrome_options)
        self.driver.get(url)
        self.wait = WebDriverWait(self.driver, 15)
        self.wait.until(EC.presence_of_element_located((By.ID, 'creator-menu-tabs')))
        
        self.include_sets = {s.strip().lower() for s in include_sets.split(',')} if include_sets else set()
        self.exclude_sets = {s.strip().lower() for s in exclude_sets.split(',')} if exclude_sets else set()
        self.card_selection_strategy = card_selection_strategy
        self.set_selection_strategy = set_selection_strategy
        self.no_match_selection = no_match_selection
        self.render_delay = render_delay
        self.apply_white_border_on_capture = white_border

        self.pt_bold = pt_bold
        self.pt_shadow = pt_shadow
        self.pt_font_size = pt_font_size
        self.pt_kerning = pt_kerning
        self.pt_up = pt_up

        self.title_font_size = title_font_size
        self.title_shadow = title_shadow
        self.title_kerning = title_kerning
        self.title_left = title_left

        self.flavor_font = flavor_font
        self.rules_down = rules_down
        self.rules_bounds_y = rules_bounds_y
        self.rules_bounds_height = rules_bounds_height
        self.hide_reminder_text = hide_reminder_text

        self.type_font_size = type_font_size
        self.type_shadow = type_shadow
        self.type_kerning = type_kerning
        self.type_left = type_left

        self.app_url = url
        self.image_server_url = image_server
        self.image_server_path = image_server_path if image_server_path else ''
        self.art_path = art_path
        self.autofit_art = autofit_art
        self.upscale_art = upscale_art
        self.ilaria_url = ilaria_url
        self.upscaler_model = upscaler_model
        self.upscaler_factor = upscaler_factor
        self.overwrite = overwrite
        self.overwrite_older_than_str = overwrite_older_than
        self.overwrite_newer_than_str = overwrite_newer_than

        self.overwrite_older_than_dt: Optional[datetime] = None
        self.overwrite_newer_than_dt: Optional[datetime] = None
        if self.overwrite_older_than_str:
            self.overwrite_older_than_dt = parse_time_string(self.overwrite_older_than_str)
        if self.overwrite_newer_than_str:
            self.overwrite_newer_than_dt = parse_time_string(self.overwrite_newer_than_str)
        self.upload_path = upload_path
        self.upload_secret = upload_secret # This can be None, which is fine

        # Initialize the Scryfall API client
        self.scryfall_api = ScryfallAPI()
        
        self.current_canvas_hash = None
        self.STABILIZE_TIMEOUT = 10
        self.STABILITY_CHECKS = 3
        self.STABILITY_INTERVAL = 0.3

        self.import_save_tab = self.wait.until(EC.element_to_be_clickable((By.XPATH, '//*[@id="creator-menu-tabs"]/h3[7]')))
        self.text_tab = self.wait.until(EC.element_to_be_clickable((By.XPATH, "//h3[text()='Text']")))
        self.art_tab = self.wait.until(EC.element_to_be_clickable((By.XPATH, "//h3[text()='Art']")))
        
        try:
            import_save_tab = self.wait.until(EC.element_to_be_clickable((By.XPATH, '//*[@id="creator-menu-tabs"]/h3[7]')))
            import_save_tab.click()
            all_art_checkbox_input = self.wait.until(EC.presence_of_element_located((By.ID, 'importAllPrints')))
            if not all_art_checkbox_input.is_selected():
                label_for_checkbox = self.driver.find_element(By.XPATH, "//label[.//input[@id='importAllPrints']]")
                label_for_checkbox.click()
                print("Set 'All Art Version' checkbox to ON.")
        except (TimeoutException, NoSuchElementException) as e:
            print(f"Error setting 'All Art Version' on init: {e}", file=sys.stderr)
            raise

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def _generate_safe_filename(self, value: str):
        return generate_safe_filename(value)

    def _generate_final_filename(self, card_name, set_name, collector_number):
        safe_card = self._generate_safe_filename(card_name)
        safe_set = self._generate_safe_filename(set_name) if set_name else 'unknown-set'
        safe_num = self._generate_safe_filename(collector_number) if collector_number else 'no-num'
        return f"{safe_card}_{safe_set}_{safe_num}.png"

    def process_and_capture_card(self, card_name, is_priming=False):
        # Step 1: Get all possible prints from the UI, bypassing filters if priming.
        all_cc_prints, include_filter_failed_cc = self._get_and_filter_prints(card_name, is_priming=is_priming)

        # --- Priming ---
        # If priming, just select the first available print and return.
        if is_priming:
            if all_cc_prints:
                dropdown = Select(self.driver.find_element(By.ID, 'import-index'))
                dropdown.select_by_value(all_cc_prints[0]['index'])
                time.sleep(self.render_delay)
            else:
                print(f"   Error: No prints found for priming card '{card_name}'.", file=sys.stderr)
            return

        prints_to_capture = []
        
        # --- Card Conjurer Mode ---
        if self.card_selection_strategy == 'cardconjurer':
            print(f"--- Card Conjurer Mode for '{card_name}' ---")
            strategy_to_use = self.set_selection_strategy
            
            # If the include filter failed in _get_and_filter_prints, we use the no_match_selection strategy.
            if include_filter_failed_cc:
                if self.no_match_selection == 'skip':
                    print(f"   Skipping card because no prints matched the include filter and --no-match-selection is 'skip'.", file=sys.stderr)
                    return
                strategy_to_use = self.no_match_selection
            
            prints_to_capture = self._select_prints_from_candidate(all_cc_prints, strategy_to_use)

        # --- Scryfall Mode ---
        elif self.card_selection_strategy == 'scryfall':
            print(f"--- Scryfall Mode for '{card_name}' ---")
            
            # 1. Initial Scryfall Query (with set filters)
            base_query_parts = [f'!\"{card_name}\"', 'unique:art', 'game:paper', 'not:covered']
            query_parts = list(base_query_parts) # Make a copy

            # Add include/exclude set filters for the initial query
            if self.include_sets:
                include_query = " OR ".join([f"set:{s}" for s in self.include_sets])
                query_parts.append(f"({include_query})")
            if self.exclude_sets:
                exclude_query = " ".join([f"-set:{s}" for s in self.exclude_sets])
                query_parts.append(f" {exclude_query}")

            full_query = " ".join(query_parts)
            print(f"   Scryfall query (with filters): {full_query}")
            scryfall_results = self.scryfall_api.search_cards(full_query, unique="art", order_by="released", direction="asc")

            selection_strategy = self.set_selection_strategy # Default to set_selection_strategy

            # 2. Fallback Scryfall Query if initial one yields no results
            if not scryfall_results:
                if self.no_match_selection == 'skip':
                    print(f"   Warning: Initial Scryfall query found no matches. Skipping card as per --no-match-selection.", file=sys.stderr)
                    return

                print(f"   Warning: Initial query found no matches. Stripping set filters and retrying a broader Scryfall search.", file=sys.stderr)
                
                # Construct fallback query without set filters, applying prefer:newest/oldest if specified
                fallback_query_parts = list(base_query_parts)
                if self.no_match_selection == 'latest':
                    fallback_query_parts.append('prefer:newest')
                elif self.no_match_selection == 'earliest':
                    fallback_query_parts.append('prefer:oldest')
                
                fallback_query = " ".join(fallback_query_parts)
                print(f"   Scryfall fallback query: {fallback_query}")
                scryfall_results = self.scryfall_api.search_cards(fallback_query, unique="art", order_by="released", direction="asc")

                if not scryfall_results:
                    print(f"   Error: Fallback Scryfall query also found no results for '{card_name}'. Skipping card.", file=sys.stderr)
                    return

                # If fallback query was used, the selection strategy shifts to no_match_selection
                selection_strategy = self.no_match_selection

            # 3. Match Scryfall results against Card Conjurer UI prints
            matched_prints = []
            for sr in scryfall_results:
                scryfall_set = sr.get('set')
                scryfall_cn = sr.get('collector_number')
                if scryfall_set and scryfall_cn:
                    for cc_print in all_cc_prints:
                        if cc_print.get('set_name', '').lower() == scryfall_set.lower() and cc_print.get('collector_number', '').lower() == str(scryfall_cn).lower():
                            matched_prints.append(cc_print)
                            break
            
            # 4. Apply Final Selection from matched prints or fallback to all CC prints
            if not matched_prints:
                if self.no_match_selection == 'skip':
                    print(f"   Warning: Found {len(scryfall_results)} print(s) on Scryfall, but none were available in the UI. Skipping card as per --no-match-selection.", file=sys.stderr)
                    return
                
                print(f"   Warning: Found {len(scryfall_results)} print(s) on Scryfall, but none matched in the Card Conjurer UI.", file=sys.stderr)
                print(f"   Applying fallback selection '{self.no_match_selection}' to all available Card Conjurer prints.", file=sys.stderr)
                prints_to_capture = self._select_prints_from_candidate(all_cc_prints, self.no_match_selection)
            else:
                print(f"   Found {len(matched_prints)} matching prints in UI from {len(scryfall_results)} Scryfall results.")
                
                if selection_strategy == 'latest':
                    prints_to_capture = [matched_prints[-1]] # Last item from sorted list is newest (Scryfall results are oldest-to-newest)
                elif selection_strategy == 'earliest':
                    prints_to_capture = [matched_prints[0]] # First item is oldest (Scryfall results are oldest-to-newest)
                elif selection_strategy == 'random':
                    prints_to_capture = [random.choice(matched_prints)]
                else: # 'all'
                    prints_to_capture = matched_prints
        
        # --- Final Check ---
        if not prints_to_capture:
            print(f"Error: No prints selected for '{card_name}' after applying all filters and strategies.", file=sys.stderr)
            return

        # --- Main Capture Loop ---
        print(f"Preparing to capture {len(prints_to_capture)} print(s) for '{card_name}'.")
        dropdown = Select(self.driver.find_element(By.ID, 'import-index'))
        for i, print_data in enumerate(prints_to_capture, 1):
            print(f"-> Capturing {i}/{len(prints_to_capture)}: '{print_data['text']}'")

            # --- OVERWRITE PRE-CHECK ---
            should_skip = False
            if self.upload_path: # Only check for overwrites if we are in an upload mode
                output_filename = self._generate_final_filename(card_name, print_data['set_name'], print_data['collector_number'])
                check_url = urljoin(self.image_server_url, os.path.join(self.upload_path, output_filename))
                
                exists, last_modified = check_server_file_details(check_url)
                
                if exists:
                    if self.overwrite:
                        should_skip = False # Unconditional overwrite
                    elif self.overwrite_older_than_dt:
                        if last_modified and last_modified < self.overwrite_older_than_dt:
                            print(f"   Overwriting '{output_filename}' as server file is older than {self.overwrite_older_than_str}.")
                            should_skip = False
                        else:
                            print(f"   Skipping '{output_filename}', server file is not older than {self.overwrite_older_than_str} (or has no timestamp).")
                            should_skip = True
                    elif self.overwrite_newer_than_dt:
                        if last_modified and last_modified > self.overwrite_newer_than_dt:
                            print(f"   Overwriting '{output_filename}' as server file is newer than {self.overwrite_newer_than_str}.")
                            should_skip = False
                        else:
                            print(f"   Skipping '{output_filename}', server file is not newer than {self.overwrite_newer_than_str} (or has no timestamp).")
                            should_skip = True
                    else: # Default behavior: skip if exists and no overwrite flag
                        print(f"   Skipping '{output_filename}', file exists on server.")
                        should_skip = True
            
            if should_skip:
                continue # Skip to the next print

            self.import_save_tab.click()
            dropdown.select_by_value(print_data['index'])

            # --- NEW: PREPARE AND APPLY CUSTOM ART RIGHT AFTER IMPORT ---
            final_art_url, type_line = None, None
            if self.image_server_url or self.download_dir: # Only prepare art if image server or local download is configured
                final_art_url, type_line = self._prepare_art_asset(card_name, print_data['set_name'], print_data['collector_number'])
            
            if final_art_url:
                self._apply_custom_art(card_name, print_data['set_name'], print_data['collector_number'], final_art_url)
            else:
                print(f"   No custom art URL available for '{card_name}'. Using default art.")

            # Set a flag to see if we need a final delay at the end
            mods_applied = False

            self._apply_text_mods(
                "Title", self.title_font_size, self.title_shadow, self.title_kerning, self.title_left)
            
            self._apply_text_mods(
                "Type", self.type_font_size, self.type_shadow, self.type_kerning, self.type_left)

            self._apply_text_mods(
                 "Power/Toughness", self.pt_font_size, self.pt_shadow, self.pt_kerning, bold=self.pt_bold, up=self.pt_up)

            # --- NEW: Basic Land Rules Text Handling ---
            is_basic_land = False
            if type_line and 'Basic' in type_line and 'Land' in type_line:
                is_basic_land = True

            if is_basic_land:
                mana_symbol = ''
                if 'Plains' in card_name: mana_symbol = '{w}'
                elif 'Island' in card_name: mana_symbol = '{u}'
                elif 'Swamp' in card_name: mana_symbol = '{b}'
                elif 'Mountain' in card_name: mana_symbol = '{r}'
                elif 'Forest' in card_name: mana_symbol = '{g}'
                
                if mana_symbol:
                    rules_text = f"{{down80}}{{fontsize64pt}}{{center}}{mana_symbol}"
                    self._set_rules_text(rules_text)
                else:
                    # Fallback for other basic lands if any
                    self._apply_text_mods("Rules Text", down=self.rules_down)
                    self._apply_flavor_font_mod()
                    self._apply_rules_text_bounds_mods()
                    self._apply_hide_reminder_text()
            else:
                self._apply_text_mods("Rules Text", down=self.rules_down)
                self._apply_flavor_font_mod()
                self._apply_rules_text_bounds_mods()
                self._apply_hide_reminder_text()
            if self.apply_white_border_on_capture:
                self.apply_white_border()
                mods_applied = True

            # If no modifications were made that include their own delays,
            # we must add the default render delay here.
            if not mods_applied:
                time.sleep(self.render_delay)

            data_url = self._get_canvas_data_url()
            if not data_url or not data_url.startswith('data:image/png;base64,'):
                print(f"   Error: Could not capture canvas.", file=sys.stderr); continue
            try:
                img_data = base64.b64decode(data_url.split(',', 1)[1])
                filename = self._generate_final_filename(card_name, print_data['set_name'], print_data['collector_number'])
                # --- REVISED, CLEANER LOGIC ---
                if self.upload_path:
                    # Upload mode is active
                    self._upload_image(img_data, filename)
                else:
                    # Local save mode is active
                    output_path = os.path.join(self.download_dir, filename)
                    with open(output_path, 'wb') as f:
                        f.write(img_data)
                    print(f"   Saved locally to '{output_path}'.")
                # --- END OF REVISED LOGIC ---

            except Exception as e:
                print(f"   Error processing or saving/uploading image data: {e}", file=sys.stderr)



    def close(self):
        if self.driver:
            try:
                self.driver.quit()
            except:
                pass

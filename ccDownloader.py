"""
Card Conjurer Selenium Downloader - Optimized Version

This script automates downloading cards from Card Conjurer using Selenium.
Features optimized delays and configurable timing.

Requirements (install with apt):
- python3-selenium
- python3-pil 
- chromium-driver (or google-chrome-stable)
"""

import os
import sys
import time
import json
import zipfile
import base64
import logging
import argparse
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from PIL import Image
from io import BytesIO


class CardConjurerDownloader:
    def __init__(self, url="http://mtgproxy:4242", download_dir=None, log_level=logging.INFO):
        """Initialize the Card Conjurer downloader with logging."""
        self.url = url
        self.download_dir = download_dir or os.path.join(os.path.expanduser("~"), "Downloads", "CardConjurer")
        self.driver = None
        self.cards = []
        
        # Configurable delays (in seconds)
        self.delays = {
            'page_load': 1.0,      # Reduced from 3
            'tab_switch': 0.3,     # Reduced from 1
            'file_upload': 1.0,    # Reduced from 3  
            'card_load': 0.5,      # Reduced from 2
            'frame_set': 0.3,      # Reduced from 1
            'download_wait': 5.0,  # Reduced from 10
            'element_wait': 5.0,   # Reduced from 10
            'js_init': 1.0         # Reduced from 2
        }
        
        # Create download directory if it doesn't exist
        Path(self.download_dir).mkdir(parents=True, exist_ok=True)
        
        # Set up logging
        self.setup_logging(log_level)
        self.logger.info(f"Initialized CardConjurerDownloader")
        self.logger.info(f"URL: {self.url}")
        self.logger.info(f"Download directory: {self.download_dir}")
        
    def setup_logging(self, log_level):
        """Set up logging with both file and console handlers."""
        # Create logs directory
        log_dir = Path(self.download_dir) / "logs"
        log_dir.mkdir(exist_ok=True)
        
        # Create logger
        self.logger = logging.getLogger('CardConjurer')
        self.logger.setLevel(log_level)
        
        # Clear any existing handlers
        if self.logger.handlers:
            self.logger.handlers.clear()
        
        # Create formatters
        detailed_formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s'
        )
        simple_formatter = logging.Formatter(
            '%(asctime)s - %(levelname)s - %(message)s'
        )
        
        # File handler with detailed formatting
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file = log_dir / f"cardconjurer_{timestamp}.log"
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(detailed_formatter)
        
        # Console handler with simple formatting
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(simple_formatter)
        
        # Add handlers to logger
        self.logger.addHandler(file_handler)
        self.logger.addHandler(console_handler)
        
        self.logger.info(f"Logging initialized. Log file: {log_file}")
        
    def setup_driver(self, headless=False):
        """Set up Chrome WebDriver with appropriate options."""
        self.logger.info(f"Setting up Chrome driver (headless={headless})")
        
        chrome_options = Options()
        
        # Set download directory
        prefs = {
            "download.default_directory": self.download_dir,
            "download.prompt_for_download": False,
            "download.directory_upgrade": True,
            "safebrowsing.enabled": False
        }
        chrome_options.add_experimental_option("prefs", prefs)
        
        # Add other options
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")
        
        # Enable browser logging
        chrome_options.add_argument("--enable-logging")
        chrome_options.add_argument("--v=1")
        
        if headless:
            chrome_options.add_argument("--headless")
            self.logger.info("Running in headless mode")
        
        # Try to find the chromedriver binary
        chromedriver_paths = [
            "/usr/bin/chromedriver",  # Debian/Ubuntu default location
            "/usr/local/bin/chromedriver",
            "chromedriver"  # In PATH
        ]
        
        chromedriver_path = None
        for path in chromedriver_paths:
            if os.path.exists(path) or os.system(f"which {path} > /dev/null 2>&1") == 0:
                chromedriver_path = path
                self.logger.info(f"Found chromedriver at: {path}")
                break
        
        if not chromedriver_path:
            self.logger.error("ChromeDriver not found. Please install chromium-driver package.")
            raise Exception("ChromeDriver not found. Please install chromium-driver package.")
        
        # Initialize driver with service
        service = Service(chromedriver_path)
        
        # Try Chromium first, then Chrome
        browser_attempts = [
            ("/usr/bin/chromium", "Chromium"),
            ("/usr/bin/google-chrome", "Google Chrome"),
            (None, "Default Chrome/Chromium")
        ]
        
        for binary_path, browser_name in browser_attempts:
            try:
                self.logger.info(f"Attempting to start {browser_name}")
                chrome_options.binary_location = binary_path
                self.driver = webdriver.Chrome(service=service, options=chrome_options)
                self.logger.info(f"Successfully started {browser_name}")
                break
            except Exception as e:
                self.logger.warning(f"Failed to start {browser_name}: {e}")
        
        if not self.driver:
            self.logger.error("Failed to initialize any browser")
            raise Exception("Could not initialize Chrome or Chromium")
        
        self.driver.maximize_window()
        self.logger.info("Browser setup complete")
        
    def wait_for_element(self, selector, by=By.CSS_SELECTOR, timeout=None):
        """Wait for an element to be present and return it."""
        if timeout is None:
            timeout = self.delays['element_wait']
            
        self.logger.debug(f"Waiting for element: {selector} (timeout={timeout}s)")
        try:
            element = WebDriverWait(self.driver, timeout).until(
                EC.presence_of_element_located((by, selector))
            )
            self.logger.debug(f"Found element: {selector}")
            return element
        except TimeoutException:
            self.logger.warning(f"Timeout waiting for element: {selector}")
            return None
    
    def wait_for_clickable(self, selector, by=By.CSS_SELECTOR, timeout=None):
        """Wait for an element to be clickable and return it."""
        if timeout is None:
            timeout = self.delays['element_wait']
            
        self.logger.debug(f"Waiting for clickable element: {selector} (timeout={timeout}s)")
        try:
            element = WebDriverWait(self.driver, timeout).until(
                EC.element_to_be_clickable((by, selector))
            )
            self.logger.debug(f"Element is clickable: {selector}")
            return element
        except TimeoutException:
            self.logger.warning(f"Timeout waiting for clickable element: {selector}")
            return None
    
    def navigate_to_card_conjurer(self):
        """Navigate to Card Conjurer and wait for it to load."""
        self.logger.info(f"Navigating to Card Conjurer: {self.url}")
        
        try:
            self.driver.get(self.url)
        except Exception as e:
            self.logger.error(f"Failed to navigate to {self.url}: {e}")
            raise
        
        # Wait for key elements to load
        self.logger.info("Waiting for Card Conjurer to load...")
        
        # Wait for multiple indicators that the page is ready
        indicators = [
            "canvas",
            "#mainCanvas",
            "#load-card-options",
            ".download",
            "[onclick*='toggleCreatorTabs']"  # Tab buttons
        ]
        
        loaded = False
        for indicator in indicators:
            element = self.wait_for_element(indicator, timeout=self.delays['page_load'] * 3)
            if element:
                self.logger.info(f"Found page indicator: {indicator}")
                loaded = True
                break
        
        if not loaded:
            self.logger.warning("Could not verify page is fully loaded")
        
        # Give the JavaScript time to initialize (reduced delay)
        self.logger.info("Waiting for JavaScript initialization...")
        time.sleep(self.delays['js_init'])
        
        # Check which tab we're on
        try:
            # Look for visible tab content
            visible_tabs = self.driver.find_elements(By.CSS_SELECTOR, "[id$='Tab']:not([style*='display: none'])")
            if visible_tabs:
                self.logger.info(f"Currently on tab: {visible_tabs[0].get_attribute('id')}")
        except:
            pass
        
        # Try to wait for download function to be available
        try:
            result = self.driver.execute_script("return typeof downloadCard === 'function'")
            if result:
                self.logger.info("downloadCard function is available")
            else:
                self.logger.warning("downloadCard function not found")
        except Exception as e:
            self.logger.warning(f"Error checking for downloadCard function: {e}")
        
        # Check for toggleCreatorTabs function
        try:
            result = self.driver.execute_script("return typeof toggleCreatorTabs === 'function'")
            if result:
                self.logger.info("toggleCreatorTabs function is available")
            else:
                self.logger.warning("toggleCreatorTabs function not found")
        except Exception as e:
            self.logger.warning(f"Error checking for toggleCreatorTabs function: {e}")
        
        return loaded
    
    def navigate_to_import_page(self):
        """Navigate to the import/save tab."""
        self.logger.info("Navigating to import/save tab...")
        
        # Try to find and click the Import/Save tab
        # Based on the onclick attribute you provided: onclick="toggleCreatorTabs(event, 'import')"
        tab_selectors = [
            # Primary selector based on onclick attribute
            "[onclick*=\"toggleCreatorTabs(event, 'import')\"]",
            "[onclick*='toggleCreatorTabs'][onclick*='import']",
            
            # Secondary selectors
            "[onclick*='import']",
            "button[onclick*='import']",
            "a[onclick*='import']",
            "div[onclick*='import']",
            
            # Text-based selectors
            "//*[contains(text(), 'Import/Save')]",
            "//*[contains(text(), 'Import')]",
            "//*[contains(text(), 'Save')]",
            
            # ID/class based
            "#importTab",
            ".importTab",
            ".import-tab",
            "#import",
            
            # Other possible selectors
            "a[onclick*='tabImportExport']",
            "button[onclick*='tabImportExport']",
            "#tabImportExport"
        ]
        
        # Try CSS selectors first
        for selector in tab_selectors:
            if selector.startswith("//"):
                # Skip XPath selectors in this loop
                continue
                
            try:
                tab = self.wait_for_clickable(selector, timeout=1)
                if tab:
                    self.logger.info(f"Found import tab using selector: {selector}")
                    tab.click()
                    time.sleep(self.delays['tab_switch'])
                    return True
            except Exception as e:
                self.logger.debug(f"Selector {selector} failed: {e}")
        
        # Try XPath selectors
        for selector in tab_selectors:
            if not selector.startswith("//"):
                # Skip CSS selectors in this loop
                continue
                
            try:
                tab = self.wait_for_clickable(selector, by=By.XPATH, timeout=1)
                if tab:
                    self.logger.info(f"Found import tab using XPath: {selector}")
                    tab.click()
                    time.sleep(self.delays['tab_switch'])
                    return True
            except Exception as e:
                self.logger.debug(f"XPath {selector} failed: {e}")
        
        # Try finding tabs by partial onclick text
        try:
            elements = self.driver.find_elements(By.XPATH, "//*[@onclick]")
            for element in elements:
                onclick = element.get_attribute("onclick")
                if onclick and "toggleCreatorTabs" in onclick and "import" in onclick:
                    self.logger.info(f"Found import tab by onclick attribute: {onclick}")
                    element.click()
                    time.sleep(self.delays['tab_switch'])
                    return True
        except Exception as e:
            self.logger.warning(f"Error searching for onclick attributes: {e}")
        
        # If we can't find the tab, see if we're already on the import page
        file_input = self.driver.find_elements(By.CSS_SELECTOR, "input[type='file']")
        if file_input:
            self.logger.info("Already on import page")
            return True
        
        # Last resort: try to execute JavaScript directly
        javascript_attempts = [
            "toggleCreatorTabs(event, 'import')",
            "toggleCreatorTabs(null, 'import')",
            "toggleCreatorTabs({}, 'import')",
            "tabImportExport()",
            "openImportTab()"
        ]
        
        for js_code in javascript_attempts:
            try:
                self.driver.execute_script(js_code)
                self.logger.info(f"Navigated to import tab using JavaScript: {js_code}")
                time.sleep(self.delays['tab_switch'])
                
                # Check if we're now on the import page
                file_input = self.driver.find_elements(By.CSS_SELECTOR, "input[type='file']")
                if file_input:
                    return True
            except Exception as e:
                self.logger.debug(f"JavaScript attempt failed: {js_code} - {e}")
        
        self.logger.error("Could not find or navigate to import tab")
        return False
    
    def wait_for_initial_load(self):
        """Wait for Card Conjurer to fully load and be ready for interaction."""
        self.logger.info("Waiting for Card Conjurer to be fully loaded...")
        
        # Wait for the canvas to be visible
        canvas = self.wait_for_element("#mainCanvas, canvas", timeout=self.delays['element_wait'])
        if not canvas:
            self.logger.warning("Canvas not found during initial load")
        
        # Wait for any loading indicators to disappear
        try:
            loading_indicators = [".loading", "#loading", ".spinner", "#spinner"]
            for indicator in loading_indicators:
                try:
                    WebDriverWait(self.driver, 2).until(
                        EC.invisibility_of_element_located((By.CSS_SELECTOR, indicator))
                    )
                except:
                    pass
        except:
            pass
        
        # Give JavaScript a moment to initialize (reduced delay)
        time.sleep(self.delays['js_init'])
        
        self.logger.info("Initial load complete")
    
    def upload_cardconjurer_file(self, file_path):
        """Upload a .cardconjurer file."""
        self.logger.info(f"Uploading file: {file_path}")
        
        if not os.path.exists(file_path):
            self.logger.error(f"File not found: {file_path}")
            return False
        
        # Wait for initial load
        self.wait_for_initial_load()
        
        # Navigate to import page
        if not self.navigate_to_import_page():
            return False
        
        # Find the file input element
        # Try multiple selectors as the input might be hidden
        file_input_selectors = [
            "input[type='file']",
            "input[accept*='.cardconjurer']",
            "#fileInput",
            "#uploadInput",
            "#file-upload"
        ]
        
        file_input = None
        for selector in file_input_selectors:
            try:
                # Try both visible and hidden inputs
                elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                for element in elements:
                    # Check if this is the right input by looking at its surroundings
                    try:
                        parent = element.find_element(By.XPATH, "..")
                        parent_text = parent.text.lower()
                        if any(word in parent_text for word in ['upload', 'import', 'load', 'choose file']):
                            file_input = element
                            self.logger.info(f"Found file input using selector: {selector}")
                            break
                    except:
                        pass
                    
                    # If no context, use the first file input we find
                    if not file_input and element:
                        file_input = element
                
                if file_input:
                    break
            except:
                continue
        
        if not file_input:
            self.logger.error("Could not find file input element")
            return False
        
        # Make the input visible if it's hidden (some sites hide the actual input)
        try:
            self.driver.execute_script("""
                arguments[0].style.display = 'block';
                arguments[0].style.visibility = 'visible';
                arguments[0].style.opacity = '1';
            """, file_input)
        except:
            pass
        
        # Send the file path to the input
        try:
            file_input.send_keys(file_path)
            self.logger.info("File path sent to input element")
        except Exception as e:
            self.logger.error(f"Error sending file path: {e}")
            return False
        
        # Wait for the upload to process (reduced delay)
        self.logger.info("Waiting for file to process...")
        time.sleep(self.delays['file_upload'])
        
        # Check if cards were loaded
        if self.check_cards_loaded():
            self.logger.info("Cards loaded successfully")
            return True
        
        # Try to trigger uploadSavedCards manually if needed
        try:
            self.driver.execute_script("""
                var event = {
                    target: {
                        files: [new File([''], '%s')]
                    }
                };
                uploadSavedCards(event);
            """ % os.path.basename(file_path))
            self.logger.info("Triggered uploadSavedCards function manually")
            time.sleep(self.delays['file_upload'])
            return self.check_cards_loaded()
        except Exception as e:
            self.logger.warning(f"Could not trigger uploadSavedCards manually: {e}")
        
        return False
    
    def check_cards_loaded(self):
        """Check if cards have been loaded."""
        # Check the card dropdown
        try:
            card_select = self.driver.find_element(By.ID, "load-card-options")
            options = card_select.find_elements(By.TAG_NAME, "option")
            
            # Filter out empty options
            valid_options = [opt for opt in options if opt.text.strip()]
            
            if len(valid_options) > 0:
                self.logger.info(f"Found {len(valid_options)} cards in dropdown")
                return True
        except:
            pass
        
        # Check if any cards are visible in the UI
        try:
            cards_in_list = self.driver.find_elements(By.CSS_SELECTOR, ".card-in-list, .saved-card")
            if cards_in_list:
                self.logger.info(f"Found {len(cards_in_list)} cards in list")
                return True
        except:
            pass
        
        self.logger.warning("No cards found after upload")
        return False
    
    def get_saved_cards(self):
        """Get list of saved cards from the dropdown."""
        self.logger.info("Getting list of saved cards...")
        
        # Try multiple selectors for the card list
        selectors = [
            "#load-card-options",
            "select[onchange*='loadCard']",
            "select[id*='load-card']"
        ]
        
        card_select = None
        for selector in selectors:
            card_select = self.wait_for_element(selector, timeout=2)
            if card_select:
                self.logger.info(f"Found card list using selector: {selector}")
                break
        
        if not card_select:
            self.logger.error("Could not find card list dropdown")
            return []
        
        # Get all options
        try:
            options = card_select.find_elements(By.TAG_NAME, "option")
            self.logger.info(f"Found {len(options)} options in dropdown")
        except Exception as e:
            self.logger.error(f"Error getting options: {e}")
            return []
        
        # Filter out empty/default options
        cards = []
        for i, option in enumerate(options):
            try:
                card_name = option.text.strip() or option.get_attribute("value")
                if card_name and card_name != "Load a saved card":  # Skip placeholder text
                    cards.append(card_name)
                    self.logger.debug(f"Card {i}: {card_name}")
            except Exception as e:
                self.logger.warning(f"Error processing option {i}: {e}")
        
        self.logger.info(f"Found {len(cards)} saved cards")
        self.cards = cards
        return cards
    
    def set_auto_frame(self, frame_option):
        """Set the auto frame dropdown value."""
        if not frame_option:
            return True  # No frame specified, nothing to do
            
        self.logger.info(f"Setting auto frame to: {frame_option}")
        
        # Mapping from script options to dropdown values
        frame_mapping = {
            '7th': 'Seventh',
            'seventh': 'Seventh',
            '8th': '8th',
            'eighth': '8th',
            'm15': 'M15Eighth',
            'ub': 'M15EighthUB'
        }
        
        dropdown_value = frame_mapping.get(frame_option.lower())
        if not dropdown_value:
            self.logger.error(f"Invalid frame option: {frame_option}")
            return False
        
        self.logger.info(f"Mapped '{frame_option}' to dropdown value: '{dropdown_value}'")
        
        # Find the auto frame dropdown
        dropdown_selectors = [
            "#autoFrame",
            "select#autoFrame",
            "[id='autoFrame']",
            "select[onchange*='setAutoFrame']"
        ]
        
        dropdown = None
        for selector in dropdown_selectors:
            try:
                dropdown = self.wait_for_element(selector, timeout=2)
                if dropdown:
                    self.logger.info(f"Found auto frame dropdown using selector: {selector}")
                    break
            except:
                continue
        
        if not dropdown:
            self.logger.error("Could not find auto frame dropdown")
            return False
        
        # Set the dropdown value
        try:
            # Use JavaScript to set the value
            self.driver.execute_script(f"""
                var select = arguments[0];
                select.value = '{dropdown_value}';
                // Trigger change event
                var event = new Event('change', {{ bubbles: true }});
                select.dispatchEvent(event);
            """, dropdown)
            
            self.logger.info(f"Set auto frame dropdown to: {dropdown_value}")
            
            # Also try to call the onChange function directly
            try:
                self.driver.execute_script("setAutoFrame()")
                self.logger.info("Called setAutoFrame() function")
            except:
                pass
            
            # Wait a moment for the change to take effect (reduced delay)
            time.sleep(self.delays['frame_set'])
            
            # Verify the value was set
            current_value = dropdown.get_attribute('value')
            if current_value == dropdown_value:
                self.logger.info(f"Successfully verified auto frame is set to: {current_value}")
                return True
            else:
                self.logger.warning(f"Auto frame value mismatch. Expected: {dropdown_value}, Got: {current_value}")
                
        except Exception as e:
            self.logger.error(f"Error setting auto frame dropdown: {e}")
            return False
        
        return True
    
    def load_card(self, card_name):
        """Load a specific card by name."""
        self.logger.info(f"Loading card: {card_name}")
        
        try:
            # Find the select element
            card_select = self.driver.find_element(By.ID, "load-card-options")
            
            # Set the select value
            self.driver.execute_script(f"""
                var select = document.getElementById('load-card-options');
                select.value = '{card_name}';
            """)
            self.logger.debug("Set select value")
            
            # Trigger the change event
            self.driver.execute_script("""
                var select = document.getElementById('load-card-options');
                var event = new Event('change', { bubbles: true });
                select.dispatchEvent(event);
            """)
            self.logger.debug("Triggered change event")
            
            # Try to call loadCard directly
            try:
                self.driver.execute_script(f"loadCard('{card_name}')")
                self.logger.debug("Called loadCard function directly")
            except Exception as e:
                self.logger.debug(f"Could not call loadCard directly: {e}")
            
        except Exception as e:
            self.logger.error(f"Error loading card '{card_name}': {e}")
            return False
        
        # Wait for card to load (reduced delay)
        self.logger.debug("Waiting for card to load...")
        time.sleep(self.delays['card_load'])
        return True
    
    def download_card_with_button(self, card_name):
        """Download card using the 'Download your card' button."""
        self.logger.info(f"Downloading card using button: {card_name}")
        
        # Try to find the download button
        download_selectors = [
            # Primary selector based on onclick
            "[onclick=\"downloadCard();\"]",
            "[onclick='downloadCard();']",
            "[onclick*='downloadCard()']",
            
            # Text-based selectors
            "//*[contains(text(), 'Download your card')]",
            "//*[contains(text(), 'Download')][@onclick]",
            
            # Class-based selectors
            ".download[onclick*='downloadCard']",
            "h3.download",
            ".download.padding",
            
            # Generic download button selectors
            "[onclick*='downloadCard']",
            ".download-button",
            "#downloadButton"
        ]
        
        download_button = None
        
        # Try CSS selectors first
        for selector in download_selectors:
            if selector.startswith("//"):
                continue
                
            try:
                button = self.wait_for_clickable(selector, timeout=1)
                if button:
                    self.logger.info(f"Found download button using selector: {selector}")
                    download_button = button
                    break
            except Exception as e:
                self.logger.debug(f"Selector {selector} failed: {e}")
        
        # Try XPath selectors if CSS didn't work
        if not download_button:
            for selector in download_selectors:
                if not selector.startswith("//"):
                    continue
                    
                try:
                    button = self.wait_for_clickable(selector, by=By.XPATH, timeout=1)
                    if button:
                        self.logger.info(f"Found download button using XPath: {selector}")
                        download_button = button
                        break
                except Exception as e:
                    self.logger.debug(f"XPath {selector} failed: {e}")
        
        # Try finding elements with downloadCard in onclick
        if not download_button:
            try:
                elements = self.driver.find_elements(By.XPATH, "//*[@onclick]")
                for element in elements:
                    onclick = element.get_attribute("onclick")
                    if onclick and "downloadCard" in onclick:
                        self.logger.info(f"Found download button by onclick: {onclick}")
                        download_button = element
                        break
            except Exception as e:
                self.logger.warning(f"Error searching for onclick attributes: {e}")
        
        if not download_button:
            self.logger.error("Could not find download button")
            return None
        
        # Get list of existing files in download directory
        existing_files = set()
        if os.path.exists(self.download_dir):
            existing_files = set(os.listdir(self.download_dir))
        
        # Click the download button
        try:
            download_button.click()
            self.logger.info("Clicked download button")
        except Exception as e:
            self.logger.error(f"Error clicking download button: {e}")
            # Try JavaScript click as fallback
            try:
                self.driver.execute_script("arguments[0].click();", download_button)
                self.logger.info("Clicked download button using JavaScript")
            except Exception as e2:
                self.logger.error(f"JavaScript click also failed: {e2}")
                return None
        
        # Wait for download to complete (reduced timeout)
        self.logger.info("Waiting for download to complete...")
        
        # Wait for a new file to appear
        downloaded_file = None
        max_wait_time = self.delays['download_wait']
        wait_interval = 0.2  # Reduced from 0.5
        elapsed_time = 0
        
        while elapsed_time < max_wait_time:
            time.sleep(wait_interval)
            elapsed_time += wait_interval
            
            current_files = set(os.listdir(self.download_dir))
            new_files = current_files - existing_files
            
            if new_files:
                # Found new file(s)
                for filename in new_files:
                    if filename.endswith('.png') or filename.endswith('.jpg') or filename.endswith('.jpeg'):
                        downloaded_file = os.path.join(self.download_dir, filename)
                        self.logger.info(f"Found downloaded file: {filename}")
                        break
                
                if downloaded_file and os.path.exists(downloaded_file):
                    # Wait a brief moment to ensure download is complete
                    time.sleep(0.3)
                    # Check if file size is stable
                    size1 = os.path.getsize(downloaded_file)
                    time.sleep(0.2)
                    size2 = os.path.getsize(downloaded_file)
                    
                    if size1 == size2 and size1 > 0:
                        self.logger.info(f"Download complete: {downloaded_file}")
                        return downloaded_file
        
        self.logger.error(f"Download did not complete within {max_wait_time} seconds")
        return None
    
    def create_zip_of_all_cards(self):
        """Create a ZIP file containing all cards."""
        self.logger.info("Starting ZIP creation process")
        
        if not self.cards:
            self.logger.info("No cards list available, fetching from page...")
            self.get_saved_cards()
        
        if not self.cards:
            self.logger.error("No cards found to download")
            return None
        
        # Create ZIP file
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        zip_filename = os.path.join(self.download_dir, f"CardConjurer_Cards_{timestamp}.zip")
        self.logger.info(f"Creating ZIP file: {zip_filename}")
        
        successful_cards = 0
        failed_cards = []
        temp_files = []  # Keep track of downloaded files to clean up
        
        try:
            with zipfile.ZipFile(zip_filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for i, card_name in enumerate(self.cards):
                    self.logger.info(f"Processing card {i+1}/{len(self.cards)}: {card_name}")
                    
                    # Load the card
                    if not self.load_card(card_name):
                        self.logger.error(f"Failed to load card: {card_name}")
                        failed_cards.append(card_name)
                        continue
                    
                    # Download the card using the button
                    downloaded_file = self.download_card_with_button(card_name)
                    
                    if downloaded_file and os.path.exists(downloaded_file):
                        # Add to ZIP with sanitized name
                        sanitized_name = "".join(c for c in card_name if c.isalnum() or c in (' ', '-', '_')).rstrip()
                        
                        # Get file extension from downloaded file
                        _, ext = os.path.splitext(downloaded_file)
                        if not ext:
                            ext = '.png'  # Default to PNG
                        
                        zip_filename_in_archive = f"{sanitized_name}{ext}"
                        
                        # Add file to ZIP
                        zipf.write(downloaded_file, arcname=zip_filename_in_archive)
                        self.logger.info(f"Added {zip_filename_in_archive} to ZIP")
                        successful_cards += 1
                        
                        # Add to temp files list for cleanup
                        temp_files.append(downloaded_file)
                    else:
                        self.logger.error(f"Failed to download card: {card_name}")
                        failed_cards.append(card_name)
        
        except Exception as e:
            self.logger.error(f"Error creating ZIP file: {e}")
            return None
        
        finally:
            # Clean up temporary downloaded files
            for temp_file in temp_files:
                try:
                    os.remove(temp_file)
                    self.logger.debug(f"Removed temporary file: {temp_file}")
                except Exception as e:
                    self.logger.warning(f"Could not remove temporary file {temp_file}: {e}")
        
        # Log summary
        self.logger.info(f"ZIP creation complete")
        self.logger.info(f"Successfully processed: {successful_cards}/{len(self.cards)} cards")
        if failed_cards:
            self.logger.warning(f"Failed cards: {', '.join(failed_cards)}")
        
        self.logger.info(f"ZIP file created: {zip_filename}")
        return zip_filename
    
    def run(self, cardconjurer_file=None, action="zip", headless=False, frame=None, optimize_delays=True):
        """Run the downloader with specified action."""
        self.logger.info(f"Starting run with action: {action}, headless: {headless}, frame: {frame}")
        
        # Apply optimization if requested
        if optimize_delays:
            # These are even more aggressive optimizations
            self.delays = {
                'page_load': 0.5,
                'tab_switch': 0.2,
                'file_upload': 0.5,
                'card_load': 0.3,
                'frame_set': 0.2,
                'download_wait': 3.0,
                'element_wait': 3.0,
                'js_init': 0.5
            }
            self.logger.info("Using optimized delays for faster operation")
        
        try:
            # Setup driver
            self.setup_driver(headless=headless)
            
            # Navigate to Card Conjurer
            if not self.navigate_to_card_conjurer():
                self.logger.error("Failed to load Card Conjurer properly")
                return
            
            # Set frame option if specified (before uploading file)
            if frame:
                if not self.set_auto_frame(frame):
                    self.logger.warning("Failed to set auto frame, continuing anyway...")
            
            # Upload file if provided
            if cardconjurer_file:
                if not self.upload_cardconjurer_file(cardconjurer_file):
                    self.logger.error(f"Failed to upload file: {cardconjurer_file}")
                    return
            
            # Perform requested action
            self.logger.info(f"Performing action: {action}")
            
            if action == "zip":
                result = self.create_zip_of_all_cards()
                if result:
                    self.logger.info(f"Successfully created ZIP: {result}")
            else:
                self.logger.error(f"Unknown action: {action}")
            
        except Exception as e:
            self.logger.error(f"Error during execution: {e}")
            self.logger.exception("Full traceback:")
            raise
        
        finally:
            # Close browser
            if self.driver:
                if not headless:
                    input("\nPress Enter to close the browser...")
                self.logger.info("Closing browser")
                self.driver.quit()
                self.logger.info("Browser closed")


def main():
    """Main entry point for the script."""
    parser = argparse.ArgumentParser(description='Card Conjurer Downloader')
    parser.add_argument('--file', '-f', required=True,
                        help='Path to .cardconjurer file to load')
    parser.add_argument('--url', default='http://mtgproxy:4242',
                        help='Card Conjurer URL')
    parser.add_argument('--output', default=None,
                        help='Output directory')
    parser.add_argument('--headless', action='store_true',
                        help='Run in headless mode')
    parser.add_argument('--action', default='zip',
                        choices=['zip'],
                        help='Action to perform (currently only zip is supported)')
    parser.add_argument('--frame', 
                        choices=['7th', 'seventh', '8th', 'eighth', 'm15', 'ub'],
                        help='Auto frame setting to use')
    parser.add_argument('--slow', action='store_true',
                        help='Use slower, more conservative delays')
    
    args = parser.parse_args()
    
    # Validate file exists
    if not os.path.exists(args.file):
        print(f"Error: File not found: {args.file}")
        sys.exit(1)
    
    # Create downloader
    downloader = CardConjurerDownloader(url=args.url, download_dir=args.output)
    
    # Run the downloader
    downloader.run(
        cardconjurer_file=args.file,
        action=args.action,
        headless=args.headless,
        frame=args.frame,
        optimize_delays=not args.slow
    )


if __name__ == "__main__":
    main()
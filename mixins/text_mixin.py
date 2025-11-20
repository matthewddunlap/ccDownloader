import time
import sys
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

class TextMixin:
    def _apply_flavor_font_mod(self):
        """
        Specifically handles inserting a font size tag after a {flavor} tag
        in the 'Rules' text box.
        """
        if self.flavor_font is None:
            return

        print("   Checking for flavor text font modification...")
        try:
            self.text_tab.click()
            
            field_button_selector = "//h4[text()='Rules Text']"
            text_editor_id = "text-editor"

            field_button = self.wait.until(EC.element_to_be_clickable((By.XPATH, field_button_selector)))
            field_button.click()
            
            time.sleep(0.5)

            text_input = self.wait.until(EC.presence_of_element_located((By.ID, text_editor_id)))
            current_text = text_input.get_attribute('value')

            # Only proceed if the {flavor} tag exists
            if '{flavor}' in current_text:
                font_tag = f"{{fontsize{self.flavor_font}}}"
                # Replace the first occurrence of {flavor} with itself plus the new tag
                new_text = current_text.replace('{flavor}', f'{{flavor}}{font_tag}', 1)

                self.driver.execute_script("arguments[0].value = arguments[1];", text_input, new_text)
                self.driver.execute_script("arguments[0].dispatchEvent(new Event('input'))", text_input)
                print(f"      Found {{flavor}} tag. Injected font size tag.")
                
                time.sleep(self.render_delay)
            else:
                print("      No {flavor} tag found. Skipping.")

        except Exception as e:
            print(f"      An error occurred while applying flavor text mods: {e}", file=sys.stderr)

    def _apply_text_mods(self, field_name, font_size=None, shadow=None, kerning=None, left=None, bold=False, up=None, down=None):
        """
        Generic method to apply modifications to a specific text field (e.g., Title, Type).
        """
        # If no modifications are specified for this field, do nothing.
        if all(arg is None for arg in [font_size, shadow, kerning, left, up, down]) and not bold:
            return

        print(f"   Applying text modifications to '{field_name}'...")
        try:
            self.text_tab.click()
            
            field_button_selector = f"//h4[text()='{field_name}']"
            text_editor_id = "text-editor"

            field_button = self.wait.until(EC.element_to_be_clickable((By.XPATH, field_button_selector)))
            field_button.click()
            
            # Brief pause to let the textarea populate
            time.sleep(0.5)

            text_input = self.wait.until(EC.presence_of_element_located((By.ID, text_editor_id)))
            current_text = text_input.get_attribute('value')

            # Build the prefix tags
            tags = []
            if font_size is not None: tags.append(f"{{fontsize{font_size}}}")
            if shadow is not None: tags.append(f"{{shadow{shadow}}}")
            if kerning is not None: tags.append(f"{{kerning{kerning}}}")
            if left is not None: tags.append(f"{{left{left}}}")
            if up is not None: tags.append(f"{{up{up}}}")
            if down is not None: tags.append(f"{{down{down}}}")
            if bold: tags.append("{bold}")
            
            prefix = "".join(tags)
            suffix = "{/bold}" if bold else ""

            if current_text and current_text.strip():
                new_text = f"{prefix}{current_text}{suffix}"
                
                self.driver.execute_script("arguments[0].value = arguments[1];", text_input, new_text)
                self.driver.execute_script("arguments[0].dispatchEvent(new Event('input'))", text_input)
                print(f"      '{field_name}' changed from '{current_text}' to '{new_text}'.")

            # Wait for the change to render on a canvas
            time.sleep(self.render_delay)

        except Exception as e:
            print(f"      An error occurred while applying mods to '{field_name}': {e}", file=sys.stderr)

    def _set_rules_text(self, new_text: str):
        """
        Sets the 'Rules Text' to the provided new_text.
        """
        print(f"   Setting Rules Text to: '{new_text}'")
        try:
            self.text_tab.click()
            
            field_button_selector = "//h4[text()='Rules Text']"
            text_editor_id = "text-editor"

            field_button = self.wait.until(EC.element_to_be_clickable((By.XPATH, field_button_selector)))
            field_button.click()
            
            time.sleep(0.5)

            text_input = self.wait.until(EC.presence_of_element_located((By.ID, text_editor_id)))
            
            self.driver.execute_script("arguments[0].value = arguments[1];", text_input, new_text)
            self.driver.execute_script("arguments[0].dispatchEvent(new Event('input'))", text_input)
            
            time.sleep(self.render_delay)
        except Exception as e:
            print(f"      An error occurred while setting Rules Text: {e}", file=sys.stderr)

    def _apply_rules_text_bounds_mods(self):
        """
        Modifies the Y position and height of the rules text box by opening the
        'Edit Bounds' dialog and adjusting the values.
        """
        if self.rules_bounds_y is None and self.rules_bounds_height is None:
            return

        print("   Applying rules text bounds modifications...")
        try:
            # 1. Ensure the 'Rules Text' editor is open (it should be from previous steps)
            #    and click the 'Edit Bounds' button.
            edit_bounds_button_selector = "//button[contains(text(), 'Edit Bounds')]"
            edit_bounds_button = self.wait.until(EC.element_to_be_clickable((By.XPATH, edit_bounds_button_selector)))
            edit_bounds_button.click()

            # 2. Wait for the textbox editor modal to appear.
            textbox_editor_selector = "div#textbox-editor.opened"
            self.wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, textbox_editor_selector)))
            print("      'Edit Bounds' dialog opened.")

            # 3. Modify the 'Y' value if provided.
            if self.rules_bounds_y is not None:
                y_input = self.driver.find_element(By.ID, 'textbox-editor-y')
                current_y = int(y_input.get_attribute('value') or 0)
                new_y = current_y + self.rules_bounds_y
                
                # Use send_keys to ensure events are triggered and hit Enter
                y_input.clear()
                y_input.send_keys(str(new_y))
                y_input.send_keys(Keys.RETURN)
                print(f"      Adjusted Rules Bounds Y from {current_y} to {new_y} (delta: {self.rules_bounds_y}).")

            # 4. Modify the 'Height' value if provided.
            if self.rules_bounds_height is not None:
                height_input = self.driver.find_element(By.ID, 'textbox-editor-height')
                current_height = int(height_input.get_attribute('value') or 0)
                new_height = current_height + self.rules_bounds_height

                # Use send_keys to ensure events are triggered and hit Enter
                height_input.clear()
                height_input.send_keys(str(new_height))
                height_input.send_keys(Keys.RETURN)
                print(f"      Adjusted Rules Bounds Height from {current_height} to {new_height} (delta: {self.rules_bounds_height}).")

            # Wait for a fraction of a second before closing
            time.sleep(0.5)

            # 5. Close the textbox editor.
            close_button_selector = "h2.textbox-editor-close"
            close_button = self.driver.find_element(By.CSS_SELECTOR, close_button_selector)
            close_button.click()
            print("      Closed 'Edit Bounds' dialog.")

            # 6. Wait for the changes to render.
            time.sleep(self.render_delay)

        except (TimeoutException, NoSuchElementException) as e:
            print(f"      An error occurred while modifying rules text bounds: {e}", file=sys.stderr)
        except Exception as e:
            print(f"      An unexpected error occurred in _apply_rules_text_bounds_mods: {e}", file=sys.stderr)

    def _apply_hide_reminder_text(self):
        """
        Clicks the 'Hide reminder text' checkbox if the flag is enabled.
        """
        if not self.hide_reminder_text:
            return

        print("   Applying hide reminder text setting...")
        try:
            # 1. Ensure we're on the Text tab
            self.text_tab.click()
            time.sleep(0.5)  # Wait for tab to fully load

            # 2. Find the checkbox
            checkbox = self.wait.until(EC.presence_of_element_located((By.ID, 'hide-reminder-text')))
            
            # 3. Check if it's already checked using JavaScript
            is_checked = self.driver.execute_script("return arguments[0].checked;", checkbox)
            
            # 4. Click if not already checked - use JavaScript since the checkbox is styled
            if not is_checked:
                # Use JavaScript to click and trigger the onchange event
                self.driver.execute_script("""
                    arguments[0].checked = true;
                    arguments[0].dispatchEvent(new Event('change'));
                """, checkbox)
                print("      'Hide reminder text' checkbox enabled.")
                
                # 5. Wait for rendering
                time.sleep(0.5)
            else:
                print("      'Hide reminder text' checkbox already enabled.")

        except (TimeoutException, NoSuchElementException) as e:
            print(f"      An error occurred while applying hide reminder text: {e}", file=sys.stderr)
        except Exception as e:
            print(f"      An unexpected error occurred in _apply_hide_reminder_text: {e}", file=sys.stderr)


    def _process_all_text_modifications(self):
        """
        Orchestrator for all text modifications to prevent race conditions.
        Returns True if a modified was successfully made.
        """
        # --- UPDATED: Check for new parameters ---
        has_mods_to_apply = any([
            self.title_font_size, self.title_shadow, self.title_kerning, self.title_left,
            self.type_font_size, self.type_shadow, self.type_kerning, self.type_left,
            self.pt_font_size, self.pt_shadow, self.pt_kerning, self.pt_bold, self.pt_up,
            self.flavor_font, self.rules_down
        ])
        if not has_mods_to_apply:
            return False

        self.text_tab.click()
        
        any_text_mod_made = False
        if self._apply_text_mods("Title", self.title_font_size, self.title_shadow, self.title_kerning, self.title_left): any_text_mod_made = True
        if self._apply_text_mods("Type", self.type_font_size, self.type_shadow, self.type_kerning, self.type_left): any_text_mod_made = True
        # --- UPDATED: Pass the 'up' parameter for Power/Toughness ---
        if self._apply_text_mods("Power/Toughness", self.pt_font_size, self.pt_shadow, self.pt_kerning, bold=self.pt_bold, up=self.pt_up): any_text_mod_made = True
        # --- NEW: Add a call for prepending to Rules Text ---
        if self._apply_text_mods("Rules Text", down=self.rules_down): any_text_mod_made = True
        # Flavor font mod is called separately as it has unique logic (inserting, not prepending)
        if self._apply_flavor_font_mod(): any_text_mod_made = True
        
        return any_text_mod_made

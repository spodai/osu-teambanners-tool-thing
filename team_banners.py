#!/usr/bin/env python3
# -*- coding: utf-8 -*-

## All written with GPT and Gemini (honestly Gemini did the harder cooking), but hey it works :D
# A tool to fetch files from a public Google Drive, upload them to s-ul.eu via API, and manage the process.
# - Saves Google Drive ID, API key, color, and logging preferences in a Config file.
# - Creates a CSV log with: Timestamp, Original Filename, Renamed Filename, s-ul.eu URL.
# - Allows deleting and renaming/reuploading specific uploaded files.
# - Subsequent runs skip files already processed and logged in the CSV.
# - Conditionally logs activity to script_activity.log based on settings.
# - Conditionally uses console colors based on settings.

## Usage:
# 1. Create a new directory (e.g., "team banners").
# 2. Place this script (team_banners.py) inside the new directory.
# 3. Run the script.
# 4. Follow the prompts to enter the public Google Drive folder ID or URL, API key, and color/logging preferences.
# 5. Select option 4 from the main menu to start the file processing.

## Directory structure created by the script:
# .
# ├── settings.conf      (Configuration file)
# ├── team_banners.py    (This script)
# ├── index.csv          (Log of processed files)
# ├── script_activity.log(Activity log file - if enabled)
# ├── Images import/     (Downloaded files from Google Drive)
# │   ├── image_01.jpg
# │   ├── image_02.jpg
# │   └── ...
# └── Images export/     (Renamed files for s-ul.eu upload)
#     ├── TEAM1.jpg
#     ├── TEAM2.jpg
#     └── ...

## Install required libraries:
# pip install requests gdown tabulate configparser colorama

import os
import shutil
import requests
import gdown
import csv
import configparser
from datetime import datetime
from tabulate import tabulate
import sys
import logging # Added for logging
import traceback # Added for detailed error logging
import re # For stripping ANSI codes

# --- Globals & Constants ---
CONFIG_FILE = "settings.conf"
IMPORT_FOLDER = "Images import"
EXPORT_FOLDER = "Images export"
CSV_FILENAME = "index.csv"
LOG_FILENAME = "script_activity.log"

# --- ANSI Color Code Definitions ---
# These are the raw codes
_COLOR_CODE_RESET = "\033[0m"
_COLOR_CODE_RED = "\033[91m"
_COLOR_CODE_GREEN = "\033[92m"
_COLOR_CODE_YELLOW = "\033[93m"
_COLOR_CODE_BLUE = "\033[94m"
_COLOR_CODE_CYAN = "\033[96m"
_COLOR_CODE_MAGENTA = "\033[95m"

# --- Global Color Variables (will be updated based on settings) ---
# These will hold either the codes above or empty strings
C_RESET = ""
C_RED = ""
C_GREEN = ""
C_YELLOW = ""
C_BLUE = ""
C_CYAN = ""
C_MAGENTA = ""

# --- Setup Colorama (Optional but recommended for Windows) ---
try:
    import colorama
    # Initialize only if colors are likely to be enabled later
    # We'll call init() properly in apply_color_settings if needed
except ImportError:
    print(f"{_COLOR_CODE_YELLOW}Optional library 'colorama' not found. Colors might not work correctly on older Windows versions.{_COLOR_CODE_RESET}")
    print(f"{_COLOR_CODE_YELLOW}Install with: pip install colorama{_COLOR_CODE_RESET}")
    colorama = None # Set to None if not available

# --- Setup Logging ---
logger = logging.getLogger(__name__) # Get logger instance
# Prevent adding multiple handlers if script is reloaded in some environments
if not logger.handlers:
    logger.addHandler(logging.NullHandler()) # Add NullHandler initially
logger.setLevel(logging.INFO) # Set base level for the logger

def setup_file_logging(base_dir, enable_logging):
    """Configures or removes file logging based on the enable_logging flag."""
    log_file_path = os.path.join(base_dir, LOG_FILENAME)
    # Remove existing file handler if present
    file_handler = None
    for handler in logger.handlers[:]:
        if isinstance(handler, logging.FileHandler):
            file_handler = handler
            logger.removeHandler(handler)
            handler.close() # Ensure it's closed before removing
            break # Assume only one file handler

    if str(enable_logging).lower() == 'true':
        # Create and add the file handler only if logging is enabled
        fh = logging.FileHandler(log_file_path, encoding='utf-8')
        fh.setLevel(logging.INFO)
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
        fh.setFormatter(formatter)
        logger.addHandler(fh)
        # Log enabling message *after* adding the handler
        logger.info(f"File logging enabled. Log file: {log_file_path}")
    else:
        # Log disabling message *before* potentially removing the handler (if it existed)
        if file_handler:
            logger.info("File logging disabled and handler removed.")
        else:
            # This message won't go to file if logging was already disabled
            logger.info("File logging is disabled. No file handler configured.")


def apply_color_settings(enable_colors):
    """Updates global color variables based on the setting."""
    global C_RESET, C_RED, C_GREEN, C_YELLOW, C_BLUE, C_CYAN, C_MAGENTA
    use_colors = str(enable_colors).lower() == 'true'

    if use_colors:
        C_RESET = _COLOR_CODE_RESET
        C_RED = _COLOR_CODE_RED
        C_GREEN = _COLOR_CODE_GREEN
        C_YELLOW = _COLOR_CODE_YELLOW
        C_BLUE = _COLOR_CODE_BLUE
        C_CYAN = _COLOR_CODE_CYAN
        C_MAGENTA = _COLOR_CODE_MAGENTA
        # Initialize colorama if available and colors enabled
        if colorama:
            try:
                colorama.init(autoreset=True)
            except Exception as e:
                # Non-critical error, proceed without colorama
                print(f"Warning: Failed to initialize colorama: {e}")
    else:
        C_RESET = ""
        C_RED = ""
        C_GREEN = ""
        C_YELLOW = ""
        C_BLUE = ""
        C_CYAN = ""
        C_MAGENTA = ""
        # Deinitialize colorama if colors are disabled
        if colorama:
            try:
                colorama.deinit()
            except Exception as e:
                 # Non-critical error
                print(f"Warning: Failed to deinitialize colorama: {e}")

# --- Utility Functions ---

def clear_screen():
    """Clears the terminal screen."""
    os.system('cls' if os.name == 'nt' else 'clear')

def pause(message="Press Enter to continue..."):
    """Pauses execution and waits for user to press Enter."""
    input(f"\n{C_MAGENTA}{message}{C_RESET}")

# --- Print functions remain for direct user feedback, logging functions handle file logging ---
def print_title(title):
    """Prints a formatted title in blue (if colors enabled)."""
    print(f"\n{C_BLUE}=== {title} ==={C_RESET}\n")

def print_success(message):
    """Prints a success message in green (if colors enabled)."""
    print(f"{C_GREEN}[OK] {message}{C_RESET}")
    logger.info(f"OK: {strip_ansi_codes(message)}") # Log clean message

def print_warning(message):
    """Prints a warning message in yellow (if colors enabled)."""
    print(f"{C_YELLOW}[WARN] {message}{C_RESET}")
    logger.warning(strip_ansi_codes(message)) # Log clean message

def print_error(message, log_exception=False):
    """Prints an error message in red (if colors enabled) and logs it."""
    print(f"{C_RED}[ERROR] {message}{C_RESET}")
    clean_message = strip_ansi_codes(message)
    logger.error(clean_message) # Log clean message
    if log_exception:
        # Logs the current exception traceback to the log file
        logger.exception(f"An exception occurred related to error: {clean_message}")

def print_info(message):
    """Prints an informational message in cyan (if colors enabled). Does not log."""
    print(f"{C_CYAN}[INFO] {message}{C_RESET}")

# --- Configuration ---

def get_yes_no_input(prompt):
    """Gets a 'y' or 'n' input from the user."""
    while True:
        # Use temporary colors for this prompt as global settings might not be applied yet
        choice = input(f"{prompt} ({_COLOR_CODE_GREEN}y{_COLOR_CODE_RESET}/{_COLOR_CODE_RED}n{_COLOR_CODE_RESET}): ").strip().lower()
        if choice in ['y', 'n']:
            return choice == 'y'
        else:
            # Use temporary color for error
            print(f"{_COLOR_CODE_RED}[ERROR] Invalid input. Please enter 'y' or 'n'.{_COLOR_CODE_RESET}")

def init_config():
    """Initializes the configuration file if it doesn't exist."""
    if not os.path.exists(CONFIG_FILE):
        # Use temporary colors before settings are loaded/applied
        print(f"{_COLOR_CODE_CYAN}[INFO] Config file not found. Let's set it up.{_COLOR_CODE_RESET}")
        drive_id = input("Enter Google Drive folder ID or URL: ").strip()
        api_key = input("Enter s-ul.eu API key: ").strip()
        # Ask for color and logging preferences
        enable_colors = get_yes_no_input("Enable console colors?")
        enable_logging = get_yes_no_input("Enable file logging?")

        # Use the script's directory as the default base directory
        base_dir = os.path.dirname(os.path.abspath(__file__))

        # Apply settings immediately for feedback during setup
        apply_color_settings(enable_colors)
        # Setup logging based on choice *before* trying to log
        setup_file_logging(base_dir, enable_logging)

        logger.info("Attempting to initialize configuration file.")

        config = configparser.ConfigParser()
        config['DEFAULT'] = {
            'drive_id': drive_id,
            'api_key': api_key,
            'base_dir': base_dir,
            'enable_colors': str(enable_colors).lower(), # Store as 'true'/'false'
            'enable_logging': str(enable_logging).lower() # Store as 'true'/'false'
        }

        try:
            with open(CONFIG_FILE, 'w', encoding='utf-8') as configfile:
                config.write(configfile)
            print_success("Config saved.") # Uses applied color settings
            logger.info(f"Config file '{CONFIG_FILE}' created and saved successfully.")
            # Create necessary folders after saving config
            os.makedirs(os.path.join(base_dir, IMPORT_FOLDER), exist_ok=True)
            os.makedirs(os.path.join(base_dir, EXPORT_FOLDER), exist_ok=True)
            print_success(f"Created folders: '{IMPORT_FOLDER}' and '{EXPORT_FOLDER}'.")
            logger.info(f"Ensured directories exist: '{IMPORT_FOLDER}', '{EXPORT_FOLDER}'.")
            pause()
        except IOError as e:
            message = f"Could not write config file: {e}"
            print_error(message, log_exception=True) # Uses applied color settings
            logger.critical(f"CRITICAL: Failed to initialize config file '{CONFIG_FILE}'. Exiting.")
            sys.exit(1) # Exit if config cannot be saved initially
        except Exception as e: # Catch potential logging setup errors
            message = f"An error occurred during initial setup: {e}"
            print_error(message, log_exception=True) # Uses applied color settings
            logger.critical(f"CRITICAL: Failed during initial setup: {e}", exc_info=True)
            sys.exit(1)

def load_config():
    """Loads configuration from the file, handling defaults for new settings."""
    if not os.path.exists(CONFIG_FILE):
        # Use temporary colors as settings aren't loaded yet
        print(f"{_COLOR_CODE_RED}[ERROR] Configuration file '{CONFIG_FILE}' not found.{_COLOR_CODE_RESET}")
        print(f"{_COLOR_CODE_CYAN}[INFO] Please run the script again to initialize the configuration.{_COLOR_CODE_RESET}")
        sys.exit(1)

    config = configparser.ConfigParser()
    base_dir_from_config = None
    enable_colors = 'true' # Default if missing
    enable_logging = 'true' # Default if missing

    try:
        config.read(CONFIG_FILE, encoding='utf-8')
        if 'DEFAULT' not in config:
            raise configparser.Error("Missing [DEFAULT] section in config.")

        # Check for essential keys first
        required_keys = ['drive_id', 'api_key', 'base_dir']
        for key in required_keys:
            if key not in config['DEFAULT'] or not config['DEFAULT'][key]: # Check if key exists and is not empty
                raise configparser.Error(f"Missing or empty essential key '{key}' in config.")

        base_dir_from_config = config['DEFAULT']['base_dir']

        # Get color/logging settings, defaulting to 'true' if missing
        enable_colors = config['DEFAULT'].get('enable_colors', 'true').lower()
        enable_logging = config['DEFAULT'].get('enable_logging', 'true').lower()

        # Apply settings based on loaded/defaulted values *before* logging/printing
        apply_color_settings(enable_colors)
        # Setup logging using the loaded base_dir and enable_logging flag
        setup_file_logging(base_dir_from_config, enable_logging)

        # Verify base_dir exists *after* setting up logging
        if not os.path.isdir(base_dir_from_config):
            message = f"Base directory specified in config does not exist: {base_dir_from_config}"
            print_error(message) # Error logged
            print_info("Please check settings.conf or delete it and run again.")
            sys.exit(1)

        logger.info("Configuration loaded successfully.")
        # Return the full dictionary including the potentially defaulted color/log settings
        loaded_config = dict(config['DEFAULT'])
        loaded_config['enable_colors'] = enable_colors
        loaded_config['enable_logging'] = enable_logging
        return loaded_config

    except (configparser.Error, IOError) as e:
        message = f"Failed to load or parse configuration file: {e}"
        apply_color_settings('true') # Assume colors OK for critical error
        print_error(message)
        # Attempt to log critical failure
        try:
            if base_dir_from_config:
                 setup_file_logging(base_dir_from_config, 'true')
            logger.critical(f"CRITICAL: Failed to load configuration: {e}", exc_info=True)
        except Exception as log_e:
             print(f"Additionally, failed to log critical error: {log_e}") # Print logging error if it occurs
        sys.exit(1)
    except Exception as e: # Catch other unexpected errors
        message = f"An unexpected error occurred loading configuration: {e}"
        apply_color_settings('true') # Assume colors OK for critical error
        print_error(message)
        try:
            logger.critical(f"CRITICAL: Unexpected error loading config: {e}", exc_info=True)
        except Exception as log_e:
             print(f"Additionally, failed to log critical error: {log_e}")
        sys.exit(1)


def update_settings():
    """Allows the user to update settings in the config file."""
    config_proxy = configparser.ConfigParser() # Use a proxy to manage changes
    logger.info("Entered settings menu.")

    while True:
        clear_screen()
        print_title("Settings Menu")
        current_drive_id = 'Not Set'
        current_api_key = 'Not Set'
        current_base_dir = 'Not Set'
        current_colors = 'true' # Default display
        current_logging = 'true' # Default display
        base_dir_for_logging = None # Track base dir for logging setup

        try:
            # Read config fresh each time to show current values
            config_proxy.read(CONFIG_FILE, encoding='utf-8')
            # Ensure DEFAULT section exists after read
            if 'DEFAULT' not in config_proxy:
                raise configparser.Error("Config file is missing [DEFAULT] section.")
            current = config_proxy['DEFAULT']
            current_drive_id = current.get('drive_id', 'Not Set')
            current_api_key = current.get('api_key', 'Not Set')
            current_base_dir = current.get('base_dir', 'Not Set')
            # Get current color/logging settings, default to 'true' if missing
            current_colors = current.get('enable_colors', 'true').lower()
            current_logging = current.get('enable_logging', 'true').lower()
            base_dir_for_logging = current_base_dir # Get base dir for potential logging change

            color_status = f"{C_GREEN}Enabled{C_RESET}" if current_colors == 'true' else f"{C_RED}Disabled{C_RESET}"
            logging_status = f"{C_GREEN}Enabled{C_RESET}" if current_logging == 'true' else f"{C_RED}Disabled{C_RESET}"

            print(f"1. Google Drive Folder ID/URL: {C_YELLOW}{current_drive_id}{C_RESET}")
            print(f"2. S-UL API Key: {C_YELLOW}{current_api_key}{C_RESET}")
            print(f"3. Base Folder: {C_YELLOW}{current_base_dir}{C_RESET}")
            print(f"4. Console Colors: {color_status}")
            print(f"5. File Logging: {logging_status}")
            print(f"\n{C_YELLOW}0{C_RESET}. Back to Main Menu")

        except (configparser.Error, IOError) as e:
            print_error(f"Could not read config file: {e}", log_exception=True)
            pause()
            return # Return to main menu if config is broken

        choice = input(f"\nChoose setting to change ({C_YELLOW}1-5{C_RESET}, or {C_YELLOW}0{C_RESET} to exit): ").strip()

        setting_changed = False
        setting_key = None
        old_value = None
        new_value = None

        if choice == '1':
            setting_key = 'drive_id'
            old_value = current_drive_id
            new_value_input = input(f"Enter new Google Drive Folder ID or URL (current: {old_value}): ").strip()
            if new_value_input:
                new_value = new_value_input
                config_proxy['DEFAULT'][setting_key] = new_value
                setting_changed = True
            else:
                 print_warning("Input cannot be empty.")
                 pause()
        elif choice == '2':
            setting_key = 'api_key'
            old_value = current_api_key
            new_value_input = input(f"Enter new S-UL API key (current: {old_value}): ").strip()
            if new_value_input:
                new_value = new_value_input
                config_proxy['DEFAULT'][setting_key] = new_value
                setting_changed = True
            else:
                 print_warning("Input cannot be empty.")
                 pause()
        elif choice == '3':
            setting_key = 'base_dir'
            old_value = current_base_dir
            new_value_input = input(f"Enter new base folder path (current: {old_value}): ").strip()
            if os.path.isdir(new_value_input):
                new_value = os.path.abspath(new_value_input)
                config_proxy['DEFAULT'][setting_key] = new_value
                setting_changed = True
            elif not new_value_input:
                 print_warning("Input cannot be empty.")
                 pause()
            else:
                print_error("Invalid folder path.")
                pause()
        elif choice == '4':
            setting_key = 'enable_colors'
            old_value = current_colors
            new_value = 'false' if old_value == 'true' else 'true' # Toggle
            config_proxy['DEFAULT'][setting_key] = new_value
            apply_color_settings(new_value) # Apply change immediately for UI feedback
            print_info(f"Console colors set to: {'Enabled' if new_value == 'true' else 'Disabled'}")
            setting_changed = True
            pause("Setting toggled. Press Enter to save or choose another option.") # Give feedback
        elif choice == '5':
            setting_key = 'enable_logging'
            old_value = current_logging
            new_value = 'false' if old_value == 'true' else 'true' # Toggle
            config_proxy['DEFAULT'][setting_key] = new_value
            # Re-setup logging based on the new value and current base directory
            if base_dir_for_logging and base_dir_for_logging != 'Not Set':
                 setup_file_logging(base_dir_for_logging, new_value)
                 print_info(f"File logging set to: {'Enabled' if new_value == 'true' else 'Disabled'}")
                 setting_changed = True
                 pause("Setting toggled. Press Enter to save or choose another option.") # Give feedback
            else:
                 print_error("Cannot toggle logging: Base directory not set.")
                 config_proxy['DEFAULT'][setting_key] = old_value # Revert toggle
                 pause()

        elif choice == '0':
            logger.info("Exited settings menu.")
            break # Exit loop to return to main menu
        else:
            print_error("Invalid option.")
            logger.warning(f"Invalid settings menu choice: {choice}")
            pause()

        # Save changes if any setting was modified
        if setting_changed:
            try:
                with open(CONFIG_FILE, 'w', encoding='utf-8') as configfile:
                    config_proxy.write(configfile)
                # Only log if it wasn't just a toggle feedback pause
                if choice not in ['4', '5']:
                    print_success("Setting updated!")
                logger.info(f"Setting '{setting_key}' updated from '{old_value}' to '{new_value}'. Config saved.")
                # If base_dir changed, re-setup logging for the new path
                if setting_key == 'base_dir' and old_value != new_value:
                     logger.info("Base directory changed, re-initializing logger.")
                     # Get the current logging state before setting up for new dir
                     current_logging_state = config_proxy['DEFAULT'].get('enable_logging', 'true')
                     setup_file_logging(new_value, current_logging_state)

                # Pause only if it wasn't a toggle that already paused
                if choice not in ['4', '5']:
                    pause()

            except IOError as e:
                print_error(f"Could not save config file: {e}", log_exception=True)
                # Attempt to revert in-memory config change if save failed
                if setting_key:
                     config_proxy['DEFAULT'][setting_key] = old_value
                     # Also revert color/logging application if toggle failed to save
                     if setting_key == 'enable_colors': apply_color_settings(old_value)
                     if setting_key == 'enable_logging' and base_dir_for_logging: setup_file_logging(base_dir_for_logging, old_value)
                logger.error(f"Failed to save updated setting '{setting_key}'. Reverted in memory.")
                pause()

# --- Core Functionality ---

def read_uploaded_originals(csv_path):
    """Reads original filenames (column 2) from the CSV log."""
    originals = set()
    if not os.path.exists(csv_path):
        logger.info(f"CSV file '{csv_path}' not found. Assuming no previously uploaded files.")
        return originals

    logger.info(f"Reading previously uploaded original filenames from '{csv_path}'.")
    try:
        with open(csv_path, 'r', newline='', encoding="utf-8") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            original_col_index = 1

            if not header:
                logger.warning(f"CSV file '{csv_path}' is empty or has no header.")
                return originals

            if len(header) <= original_col_index:
                 logger.warning(f"CSV file '{csv_path}' header does not have expected 'Original' column at index {original_col_index}.")
                 return originals

            processed_rows = 0
            malformed_rows = 0
            for i, row in enumerate(reader):
                if len(row) > original_col_index:
                    originals.add(row[original_col_index])
                    processed_rows += 1
                else:
                    logger.warning(f"Skipping malformed row {i+1} in CSV '{csv_path}': {row}")
                    malformed_rows += 1

            logger.info(f"Found {len(originals)} unique original filenames in CSV. Processed {processed_rows} rows, skipped {malformed_rows} malformed rows.")

    except (IOError, csv.Error) as e:
        print_error(f"Could not read CSV file '{csv_path}': {e}", log_exception=True)
    except StopIteration:
        logger.info(f"CSV file '{csv_path}' contains only a header.")
        pass

    return originals

def download_drive_folder(drive_id, download_path, csv_path):
    """Downloads files from Google Drive folder using gdown and filters against CSV."""
    clear_screen()
    print_title("Download from Google Drive")
    logger.info("Starting Google Drive download process.")

    if not drive_id:
        print_error("Google Drive ID/URL is not set in configuration.")
        pause()
        return []

    url = f"https://drive.google.com/drive/folders/{drive_id}" if "drive.google.com" not in drive_id else drive_id
    print_info(f"Attempting download from: {url}")
    print_info(f"Downloading to: {download_path}")
    logger.info(f"Drive URL/ID: {drive_id}")
    logger.info(f"Download path: {download_path}")

    os.makedirs(download_path, exist_ok=True)
    uploaded_originals = read_uploaded_originals(csv_path)
    logger.info(f"Found {len(uploaded_originals)} files previously logged in CSV.")
    files_before_download = {f for f in os.listdir(download_path) if os.path.isfile(os.path.join(download_path, f))}
    logger.info(f"Found {len(files_before_download)} files in import directory before download.")
    files_to_process = []

    try:
        print_info("Starting gdown download/sync (this might take a while)...")
        logger.info(f"Calling gdown.download_folder for URL: {url}")
        gdown.download_folder(url, output=download_path, quiet=False, use_cookies=False, remaining_ok=True)
        logger.info("gdown.download_folder process finished.")
        print_info("gdown download/sync process finished.")

        files_after_download = {f for f in os.listdir(download_path) if os.path.isfile(os.path.join(download_path, f))}
        logger.info(f"Found {len(files_after_download)} files in import directory after download.")
        processed_count = 0
        skipped_logged_count = 0

        print_info("Filtering downloaded files...")
        logger.info("Filtering downloaded files against CSV log...")
        for file in sorted(list(files_after_download)):
            if file not in uploaded_originals:
                files_to_process.append(file)
                if file not in files_before_download:
                    logger.info(f"Identified new file for processing: {file}")
                else:
                    logger.info(f"Identified existing local file for processing (not in CSV): {file}")
                processed_count += 1
            else:
                logger.info(f"Skipping file (already logged in CSV): {file}")
                skipped_logged_count += 1

        print_success("Download and filtering complete.")
        logger.info("Download and filtering complete.")
        if files_to_process:
            print_info(f"Identified {len(files_to_process)} file(s) needing processing (rename/upload).")
            logger.info(f"{len(files_to_process)} file(s) identified for processing.")
        else:
            print_info("No new files found requiring processing.")
            logger.info("No new files identified for processing.")
        if skipped_logged_count > 0:
            print_info(f"Skipped {skipped_logged_count} file(s) already present in the log.")

        return files_to_process

    except Exception as e:
        print_error(f"An error occurred during download/filtering: {e}", log_exception=True)
        print_info("Check the Google Drive ID/URL, folder permissions, and network connection.")
        pause()
        return []


def prompt_rename_images(import_path, export_path, files_to_process):
    """Prompts user to rename downloaded files and copies them to export path."""
    if not files_to_process:
        print_info("No files require renaming.")
        logger.info("Skipping rename step: No files to process.")
        return []

    clear_screen()
    print_title("Rename New Files")
    logger.info(f"Starting rename process for {len(files_to_process)} file(s).")
    os.makedirs(export_path, exist_ok=True)
    renamed_list = []
    skipped_count = 0
    renamed_count = 0

    print_info(f"Found {len(files_to_process)} file(s) to rename.")
    print_info("Enter a new name without the extension.")
    print_info("Leave blank and press Enter to keep the original filename.")

    for original_filename in sorted(files_to_process):
        src_path = os.path.join(import_path, original_filename)
        if not os.path.isfile(src_path):
            print_warning(f"Source file not found, skipping: {original_filename}")
            logger.warning(f"Rename skipped: Source file not found at '{src_path}'.")
            skipped_count += 1
            continue

        print(f"\nOriginal filename: {C_YELLOW}{original_filename}{C_RESET}")
        new_name_base = input("Enter new name (no extension, blank to keep original): ").strip()

        _, ext = os.path.splitext(original_filename)
        new_filename = f"{new_name_base}{ext}" if new_name_base else original_filename
        dest_path = os.path.join(export_path, new_filename)
        logger.info(f"Processing rename for '{original_filename}' -> '{new_filename}'.")

        counter = 1
        while os.path.exists(dest_path) and dest_path != src_path:
            print_warning(f"File '{new_filename}' already exists in export folder.")
            logger.warning(f"Rename conflict: '{new_filename}' already exists at '{dest_path}'.")
            overwrite_choice = input(f"Overwrite? ({C_GREEN}y{C_RESET}/{C_RED}n{C_RESET}, default n): ").strip().lower()
            if overwrite_choice == 'y':
                print_info(f"Overwriting existing file: {new_filename}")
                logger.info(f"User chose to overwrite existing file '{new_filename}'.")
                break
            else:
                 base = new_name_base if new_name_base else os.path.splitext(original_filename)[0]
                 new_filename = f"{base}_{counter}{ext}"
                 dest_path = os.path.join(export_path, new_filename)
                 print_info(f"Trying new name: {new_filename}")
                 logger.info(f"Rename conflict: Trying new name '{new_filename}'.")
                 counter += 1
                 if counter > 10:
                      print_error("Too many filename conflicts, skipping this file.")
                      logger.error(f"Rename skipped: Too many filename conflicts for '{original_filename}'.")
                      new_filename = None
                      break

        if new_filename is None:
             skipped_count += 1
             continue

        try:
            shutil.copy2(src_path, dest_path)
            print_success(f"Copied and renamed to: {new_filename}")
            logger.info(f"Successfully copied '{src_path}' to '{dest_path}'.")
            renamed_list.append((original_filename, new_filename, dest_path))
            renamed_count += 1
        except IOError as e:
            print_error(f"Could not copy file '{original_filename}' to '{dest_path}': {e}", log_exception=True)
            skipped_count += 1
        except Exception as e:
            print_error(f"An unexpected error occurred during copy: {e}", log_exception=True)
            skipped_count += 1

    logger.info(f"Rename process finished. Renamed: {renamed_count}, Skipped: {skipped_count}.")
    return renamed_list


def upload_to_sul(file_path, api_key):
    """Uploads a file to s-ul.eu and returns the URL."""
    filename = os.path.basename(file_path)
    if not api_key:
        logger.error(f"Upload skipped for '{filename}': API key is missing.")
        raise ValueError("S-UL API key is missing.")
    if not os.path.exists(file_path):
         logger.error(f"Upload skipped for '{filename}': File not found at '{file_path}'.")
         raise FileNotFoundError(f"File to upload not found: {file_path}")

    print_info(f"Uploading '{filename}' to s-ul.eu...")
    logger.info(f"Attempting upload for '{filename}' from '{file_path}'.")
    try:
        with open(file_path, "rb") as f:
            files = {"file": (filename, f)}
            data = {"wizard": "true", "key": str(api_key)}
            res = requests.post("https://s-ul.eu/api/v1/upload", data=data, files=files, timeout=60)

            logger.info(f"Upload request for '{filename}' completed with status code: {res.status_code}.")
            response_json = {}
            try:
                 response_json = res.json()
                 logger.debug(f"API Response JSON for '{filename}': {response_json}")
            except requests.exceptions.JSONDecodeError:
                 logger.warning(f"Could not decode JSON response for '{filename}'. Response text: {res.text[:200]}...")

            res.raise_for_status()

            if "url" in response_json:
                url = response_json["url"]
                print_success(f"Upload successful: {url}")
                logger.info(f"Upload successful for '{filename}'. URL: {url}")
                return url
            else:
                error_msg = response_json.get("error", "Unknown error from API (URL missing in 200 OK response)")
                logger.error(f"API Error for '{filename}': {error_msg}")
                raise requests.exceptions.RequestException(f"API Error: {error_msg}")

    except requests.exceptions.Timeout:
        print_error(f"Upload timed out for '{filename}'.")
        return None
    except requests.exceptions.ConnectionError as e:
         print_error(f"Connection error during upload for '{filename}': {e}", log_exception=True)
         return None
    except requests.exceptions.RequestException as e:
        print_error(f"Upload failed for '{filename}': {e}")
        try:
            error_detail = res.json().get('error', f'(status code: {res.status_code})')
            logger.error(f"API Response Detail for failed upload '{filename}': {error_detail}")
        except:
            logger.error(f"Could not get error details from API response for '{filename}'. Status: {res.status_code}, Text: {res.text[:200]}...")
        return None
    except IOError as e:
        print_error(f"Could not read file for upload '{filename}': {e}", log_exception=True)
        return None
    except Exception as e:
        print_error(f"An unexpected error occurred during upload of '{filename}': {e}", log_exception=True)
        return None


def write_to_csv(csv_path, upload_data):
    """Appends successfully uploaded file information to the CSV log."""
    if not upload_data:
        logger.info("No successful uploads to write to CSV.")
        return

    logger.info(f"Attempting to write {len(upload_data)} new entries to CSV: '{csv_path}'.")
    header = ["Timestamp", "Original", "Renamed", "URL"]
    write_header = not os.path.exists(csv_path) or os.path.getsize(csv_path) == 0
    try:
        with open(csv_path, "a", newline='', encoding="utf-8") as f:
            writer = csv.writer(f)
            if write_header:
                writer.writerow(header)
                logger.info("Writing header to new CSV file.")
            written_count = 0
            for timestamp, original, renamed, url in upload_data:
                writer.writerow([timestamp, original, renamed, url])
                written_count += 1
        print_success(f"Successfully added {written_count} entries to '{os.path.basename(csv_path)}'.")
        logger.info(f"Successfully wrote {written_count} entries to '{csv_path}'.")
    except (IOError, csv.Error) as e:
        print_error(f"Could not write to CSV file '{csv_path}': {e}", log_exception=True)

def strip_ansi_codes(text):
    """Removes ANSI escape codes from a string."""
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    return ansi_escape.sub('', text)

def get_csv_data(csv_path, add_color=False):
    """Reads all data from the CSV file. Validates row length."""
    if not os.path.exists(csv_path):
        return None, []

    logger.debug(f"Reading CSV data from '{csv_path}', add_color={add_color}.")
    try:
        with open(csv_path, 'r', newline='', encoding='utf-8') as csvfile:
            reader = csv.reader(csvfile)
            header = next(reader, None)
            if not header:
                 logger.warning(f"CSV file is empty: {csv_path}")
                 return None, []

            data = list(reader)
            num_columns = len(header)
            validated_data = []
            malformed_count = 0
            for i, row in enumerate(data):
                 if len(row) == num_columns:
                      validated_data.append(row)
                 else:
                      malformed_count += 1
                      logger.warning(f"CSV row {i+1} in '{csv_path}' has incorrect number of columns ({len(row)} instead of {num_columns}). Skipping row: {row}")

            if malformed_count > 0:
                 print_warning(f"Skipped {malformed_count} malformed row(s) in CSV. Check '{LOG_FILENAME}' for details.")

            logger.debug(f"Read {len(validated_data)} valid data rows from CSV.")

            if add_color:
                colored_header = [f"{C_CYAN}{h}{C_RESET}" for h in header]
                return colored_header, validated_data
            else:
                return header, validated_data

    except (IOError, csv.Error) as e:
        print_error(f"Could not read or parse CSV file '{csv_path}': {e}", log_exception=True)
        return None, []
    except StopIteration:
        logger.info(f"CSV file '{csv_path}' contains only a header.")
        if add_color:
            colored_header = [f"{C_CYAN}{h}{C_RESET}" for h in header]
            return colored_header, []
        else:
            return header, []


def show_csv(csv_path):
    """Displays the contents of the CSV log file using fancy_grid."""
    clear_screen()
    print_title("CSV Log Data (index.csv)")
    logger.info("Displaying CSV data.")

    header, data = get_csv_data(csv_path, add_color=True)

    if header is None:
        pass
    elif not data:
        print_info("CSV file is empty or contains only a header.")
        if header:
             print(tabulate([], headers=header, tablefmt="fancy_grid"))
    else:
        print(tabulate(data, headers=header, tablefmt="fancy_grid"))

    pause("Press Enter to return to the main menu...")


def rename_existing_item(csv_path, base_dir, config):
    """Allows renaming an item already logged in the CSV and optionally re-uploading."""
    api_key = config.get('api_key')
    export_path_base = os.path.join(base_dir, EXPORT_FOLDER)
    logger.info("Entered rename item menu.")

    while True:
        clear_screen()
        print_title("Rename Logged Item")

        header_colored, data = get_csv_data(csv_path, add_color=True)

        if header_colored is None:
            pause()
            return
        if not data:
            print_info("No entries found in the CSV log.")
            logger.info("No CSV entries found to rename.")
            pause()
            return

        display_header = [f"{C_CYAN}#{C_RESET}"] + header_colored
        display_data = [[idx + 1] + row for idx, row in enumerate(data)]

        print(tabulate(display_data, headers=display_header, tablefmt="fancy_grid"))
        print(f"\n{C_YELLOW}0{C_RESET}. Back to Main Menu")
        choice = input(f"Enter the number ({C_YELLOW}#{C_RESET}) of the item to rename (or 0 to exit): ").strip()

        if choice == '0':
            logger.info("Exited rename item menu.")
            break

        try:
            item_index = int(choice) - 1
            if not 0 <= item_index < len(data):
                raise ValueError("Index out of range.")
        except ValueError:
            print_error("Invalid number.")
            logger.warning(f"Invalid rename choice: {choice}")
            pause("Press Enter to try again...")
            continue

        selected_row = data[item_index]
        try:
             if len(selected_row) >= 4:
                 timestamp, original_name, old_renamed_name, old_url = selected_row[:4]
                 logger.info(f"Attempting to rename item #{item_index+1}: '{old_renamed_name}' (Original: '{original_name}')")
             else:
                 raise ValueError("Row does not have enough columns.")
        except ValueError as e:
             print_error(f"CSV row has unexpected format ({e}). Cannot proceed.")
             pause()
             continue

        print(f"\nSelected item: {old_renamed_name} (Original: {original_name})")
        _, ext = os.path.splitext(old_renamed_name)
        new_name_base = input(f"Enter the new name for '{old_renamed_name}' (without extension): ").strip()

        if not new_name_base:
            print_warning("New name cannot be empty.")
            pause("Press Enter to try again...")
            continue

        new_renamed_name = f"{new_name_base}{ext}"
        old_export_path = os.path.join(export_path_base, old_renamed_name)
        new_export_path = os.path.join(export_path_base, new_renamed_name)
        logger.info(f"User provided new name: '{new_renamed_name}'. Old path: '{old_export_path}', New path: '{new_export_path}'")

        if new_renamed_name != old_renamed_name and os.path.exists(new_export_path):
            print_error(f"A file named '{new_renamed_name}' already exists in '{EXPORT_FOLDER}'.")
            logger.warning(f"Rename conflict: Target file '{new_export_path}' already exists.")
            print_info("Please choose a different name or manually resolve the conflict.")
            pause()
            continue

        renamed_locally = False
        local_rename_skipped = False
        if os.path.exists(old_export_path):
            if new_renamed_name != old_renamed_name:
                try:
                    os.rename(old_export_path, new_export_path)
                    print_success(f"Renamed local file to '{new_renamed_name}'")
                    renamed_locally = True
                except OSError as e:
                    print_error(f"Failed to rename local file: {e}", log_exception=True)
                    pause()
                    continue
            else:
                 print_info("New name is the same as the old name. Skipping local file rename.")
                 logger.info("New name is same as old, skipping local file rename.")
                 renamed_locally = True
                 local_rename_skipped = True
        else:
            print_warning(f"Original renamed file '{old_renamed_name}' not found in '{EXPORT_FOLDER}'.")
            logger.warning(f"Local file '{old_export_path}' not found for renaming.")
            print_info("CSV entry will be updated, but no local file was renamed.")
            renamed_locally = True

        reupload_url = old_url
        if renamed_locally:
            if not local_rename_skipped or not os.path.exists(old_export_path):
                print_warning("Manually delete the old file on s-ul.eu if you want to replace it.")
                reupload_choice = input(f"Re-upload '{new_renamed_name}' to s-ul.eu? ({C_GREEN}y{C_RESET}/{C_RED}n{C_RESET}): ").strip().lower()
                if reupload_choice == 'y':
                    logger.info(f"User chose to re-upload '{new_renamed_name}'.")
                    if not api_key:
                         print_error("Cannot re-upload: S-UL API key is missing in config.")
                    elif not os.path.exists(new_export_path):
                         print_error(f"Cannot re-upload: File '{new_renamed_name}' not found at '{new_export_path}'.")
                    else:
                        try:
                            new_url = upload_to_sul(new_export_path, api_key)
                            if new_url:
                                reupload_url = new_url
                            else:
                                print_warning("Re-upload failed. Keeping the old URL in the log.")
                        except (FileNotFoundError, ValueError) as e:
                             print_error(f"Re-upload pre-check failed: {e}")
                        except Exception as e:
                             print_error(f"An unexpected error occurred during re-upload: {e}", log_exception=True)
                else:
                     print_info("Skipping re-upload. Keeping the old URL in the log.")
                     logger.info(f"User chose not to re-upload '{new_renamed_name}'.")
            else:
                 print_info("Skipping re-upload prompt as filename did not change.")
                 logger.info("Skipping re-upload prompt as filename did not change.")

        data[item_index][2] = new_renamed_name
        data[item_index][3] = reupload_url
        new_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
        data[item_index][0] = new_timestamp

        try:
            header_clean, _ = get_csv_data(csv_path, add_color=False)
            if header_clean is None:
                 header_clean = ["Timestamp", "Original", "Renamed", "URL"]
                 print_warning("Could not reread original header, using default for saving.")

            with open(csv_path, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.writer(csvfile)
                writer.writerow(header_clean)
                writer.writerows(data)
            print_success("CSV log updated successfully.")
            logger.info(f"CSV log updated successfully after renaming item #{item_index+1} to '{new_renamed_name}'.")
        except (IOError, csv.Error) as e:
            print_error(f"Failed to save updated CSV: {e}", log_exception=True)
            if renamed_locally and os.path.exists(new_export_path) and new_export_path != old_export_path:
                 print_warning("Local file was renamed, but CSV update failed. You may need to manually revert the rename or fix the CSV.")
            elif not renamed_locally:
                 print_warning("CSV update failed.")

        pause("Press Enter to rename another item or 0 to return...")


def delete_entry(csv_path, base_dir):
    """Deletes an entry from the CSV and optionally the corresponding local files."""
    export_path_base = os.path.join(base_dir, EXPORT_FOLDER)
    import_path_base = os.path.join(base_dir, IMPORT_FOLDER)
    logger.info("Entered delete item menu.")

    while True:
        clear_screen()
        print_title("Delete Logged Item")
        print_warning("This only removes the entry from the log and local files.")
        print_warning(f"{C_RED}It does NOT delete the file from s-ul.eu.{C_RESET}")

        header_colored, data = get_csv_data(csv_path, add_color=True)

        if header_colored is None:
            pause()
            return
        if not data:
            print_info("No entries found in the CSV log to delete.")
            logger.info("No CSV entries found to delete.")
            pause()
            return

        display_header = [f"{C_CYAN}#{C_RESET}"] + header_colored
        display_data = [[idx + 1] + row for idx, row in enumerate(data)]

        print(tabulate(display_data, headers=display_header, tablefmt="fancy_grid"))
        print(f"\n{C_YELLOW}0{C_RESET}. Back to Main Menu")
        choice = input(f"Enter the number ({C_YELLOW}#{C_RESET}) of the item to delete (or 0 to exit): ").strip()

        if choice == '0':
            logger.info("Exited delete item menu.")
            break

        try:
            item_index = int(choice) - 1
            if not 0 <= item_index < len(data):
                raise ValueError("Index out of range.")
        except ValueError:
            print_error("Invalid number.")
            logger.warning(f"Invalid delete choice: {choice}")
            pause("Press Enter to try again...")
            continue

        removed_row = data.pop(item_index)
        original_name = None
        renamed_name = None
        try:
             if len(removed_row) >= 4:
                 timestamp, original_name, renamed_name, url = removed_row[:4]
                 print_success(f"Removed entry for '{renamed_name}' (Original: {original_name}) from log.")
                 logger.info(f"Removed item #{item_index+1} ('{renamed_name}', Original: '{original_name}') from in-memory list.")
             else:
                 raise ValueError("Row does not have enough columns.")
        except ValueError as e:
             print_error(f"Removed row had unexpected format ({e}). Cannot reliably delete local files.")
             logger.error(f"Removed row #{item_index+1} had unexpected format: {removed_row}. Cannot determine filenames for local deletion.")

        delete_files_choice = input(f"Delete corresponding local files (Import/Export)? ({C_GREEN}y{C_RESET}/{C_RED}n{C_RESET}): ").strip().lower()
        if delete_files_choice == 'y':
            logger.info(f"User chose to delete local files for removed item #{item_index+1}.")
            files_to_delete = []
            if renamed_name:
                 files_to_delete.append(os.path.join(export_path_base, renamed_name))
            if original_name:
                 files_to_delete.append(os.path.join(import_path_base, original_name))

            if not files_to_delete:
                 print_info("Could not determine filenames to delete.")
                 logger.warning("Could not determine local filenames to delete based on removed row.")
            else:
                deleted_count = 0
                for file_path in files_to_delete:
                     logger.info(f"Attempting to delete local file: {file_path}")
                     if os.path.exists(file_path):
                         try:
                             os.remove(file_path)
                             print_success(f"Deleted local file: {file_path}")
                             deleted_count += 1
                         except OSError as e:
                             print_error(f"Failed to delete local file {file_path}: {e}", log_exception=True)
                     else:
                        print_info(f"Local file not found, skipping: {file_path}")
                        logger.info(f"Local file not found for deletion, skipping: {file_path}")

                if deleted_count == 0 and files_to_delete:
                     print_info("No corresponding local files were found to delete.")
                     logger.info("No corresponding local files found for deletion.")
                elif deleted_count > 0:
                     logger.info(f"Deleted {deleted_count} local file(s).")
        else:
            logger.info(f"User chose not to delete local files for removed item #{item_index+1}.")

        try:
            header_clean, _ = get_csv_data(csv_path, add_color=False)
            if header_clean is None:
                 header_clean = ["Timestamp", "Original", "Renamed", "URL"]
                 print_warning("Could not reread original header, using default for saving.")

            with open(csv_path, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.writer(csvfile)
                writer.writerow(header_clean)
                writer.writerows(data)
            print_success("CSV log updated successfully.")
            logger.info(f"CSV log updated successfully after deleting item #{item_index+1}.")
        except (IOError, csv.Error) as e:
            print_error(f"Failed to save updated CSV: {e}", log_exception=True)
            print_warning("Log entry was removed in this session, but failed to save to disk.")

        pause("Press Enter to delete another item or 0 to return...")


def start_script(config):
    """Main workflow: download, rename, upload, log."""
    clear_screen()
    print_title("Start Processing Files")
    logger.info("Starting main script execution (Option 4).")
    base_dir = config.get("base_dir")
    drive_id = config.get("drive_id")
    api_key = config.get("api_key")

    if not base_dir:
         print_error("Base directory is not set in configuration.")
         pause()
         return
    if not drive_id:
         print_error("Google Drive ID/URL is not set in configuration.")
         pause()
         return
    if not api_key:
         print_warning("S-UL API key is not set. Uploading will be skipped.")

    import_path = os.path.join(base_dir, IMPORT_FOLDER)
    export_path = os.path.join(base_dir, EXPORT_FOLDER)
    csv_path = os.path.join(base_dir, CSV_FILENAME)

    try:
        os.makedirs(import_path, exist_ok=True)
        os.makedirs(export_path, exist_ok=True)
        logger.debug(f"Ensured import/export directories exist: '{import_path}', '{export_path}'")
    except OSError as e:
        print_error(f"Could not create required directories: {e}", log_exception=True)
        pause()
        return

    files_to_process = download_drive_folder(drive_id, import_path, csv_path)

    if not files_to_process:
        logger.info("No files identified for processing after download step.")
        pause()
        return

    renamed_files_info = prompt_rename_images(import_path, export_path, files_to_process)

    if not renamed_files_info:
        logger.info("No files were renamed or copied to export folder.")
        pause()
        return

    successful_uploads = []
    if not api_key:
         print_warning("Skipping upload step as API key is not configured.")
         logger.warning("Skipping upload step: API key not configured.")
    else:
        clear_screen()
        print_title("Uploading Files")
        logger.info(f"Starting upload process for {len(renamed_files_info)} file(s).")
        upload_count = 0
        total_files = len(renamed_files_info)
        failed_uploads = 0
        for original_name, new_name, file_to_upload_path in renamed_files_info:
            upload_count += 1
            print(f"\n--- Uploading file {upload_count} of {total_files} ---")
            try:
                url = upload_to_sul(file_to_upload_path, api_key)
                if url:
                    successful_uploads.append((datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f"), original_name, new_name, url))
                else:
                    print_warning(f"Skipping logging for failed upload: {new_name}")
                    failed_uploads += 1
            except (FileNotFoundError, ValueError) as e:
                 print_error(f"Cannot upload {new_name}: {e}")
                 failed_uploads += 1
            except Exception as e:
                 print_error(f"Unexpected error uploading {new_name}: {e}", log_exception=True)
                 failed_uploads += 1
        logger.info(f"Upload process finished. Successful: {len(successful_uploads)}, Failed: {failed_uploads}.")

    if successful_uploads:
        write_to_csv(csv_path, successful_uploads)
    elif api_key:
        print_info("No files were successfully uploaded.")
        logger.info("No files were successfully uploaded in this run.")

    print_info("\nProcessing complete.")
    logger.info("Main script execution (Option 4) finished.")
    pause()


# --- Informational / Destructive Actions ---

def get_folder_tree_with_sizes(folder_path):
    """Generates a list of tuples (item_path, size_readable) for a folder tree."""
    logger.debug(f"Generating folder tree for: {folder_path}")
    tree_data = []

    def get_size(path):
        """Safely gets size of a file."""
        try:
            if os.path.isfile(path):
                return os.path.getsize(path)
            return 0
        except OSError as e:
            logger.warning(f"Could not get size for '{path}': {e}")
            return 0

    def format_size(size_bytes):
        """Formats bytes into a human-readable string."""
        if size_bytes < 0: return "N/A"
        if size_bytes < 1024:
            return f"{size_bytes} B"
        for unit in ['B', 'KB', 'MB', 'GB', 'TB', 'PB']:
            if size_bytes < 1024.0:
                return f"{size_bytes:.2f} {unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:.2f} PB"

    def build_tree(directory, prefix=""):
        """Recursively builds the tree structure."""
        try:
            items = sorted(os.listdir(directory))
        except OSError as e:
             logger.warning(f"Cannot list directory '{directory}': {e}")
             items = []

        num_items = len(items)
        for i, item in enumerate(items):
            path = os.path.join(directory, item)
            is_last = i == num_items - 1
            indicator = "└── " if is_last else "├── "
            connector = "    " if is_last else "│   "

            try:
                is_dir = os.path.isdir(path)
                is_file = os.path.isfile(path)
            except OSError as e:
                is_dir = False
                is_file = False
                logger.warning(f"Cannot access item type '{path}': {e}")

            if is_dir:
                item_display = f"{C_BLUE}{item}{C_RESET}"
                size_readable = "<DIR>"
                tree_data.append((prefix + indicator + item_display, size_readable))
                new_prefix = prefix + connector
                build_tree(path, new_prefix)
            elif is_file:
                 size_bytes = get_size(path)
                 size_readable = format_size(size_bytes)
                 tree_data.append((prefix + indicator + item, size_readable))

    root_total_bytes = 0
    try:
        for dirpath, dirnames, filenames in os.walk(folder_path):
             for f in filenames:
                  fp = os.path.join(dirpath, f)
                  if os.path.isfile(fp) and not os.path.islink(fp):
                       root_total_bytes += get_size(fp)
    except OSError as e:
         logger.error(f"Could not traverse directory '{folder_path}' for size calculation: {e}")
         root_total_bytes = -1

    root_display_name = f"{C_BLUE}{os.path.basename(folder_path)}{C_RESET}"
    tree_data.append((root_display_name, format_size(root_total_bytes)))
    build_tree(folder_path)
    logger.debug(f"Folder tree generation complete for: {folder_path}")
    return tree_data


def show_folder_structure(config):
    """Displays the folder structure of the base directory."""
    logger.info("Displaying folder structure.")
    base_dir = config.get('base_dir')
    if not base_dir or not os.path.isdir(base_dir):
        print_error("Base directory is not set or invalid.")
        pause()
        return

    clear_screen()
    abs_base_dir = os.path.abspath(base_dir)
    print_title(f"Folder Structure ({abs_base_dir})")
    try:
        folder_tree = get_folder_tree_with_sizes(base_dir)
        headers = [f"{C_CYAN}Name{C_RESET}", f"{C_CYAN}Size{C_RESET}"]
        print(tabulate(folder_tree, headers=headers, tablefmt="plain"))
    except Exception as e:
        print_error(f"Could not generate folder structure: {e}", log_exception=True)

    pause("Press Enter to return to the main menu...")


def nuke_everything(base_dir):
    """Deletes the entire base directory after double confirmation."""
    clear_screen()
    print_title("Nuke Everything")
    logger.warning("NUKE EVERYTHING option selected.")
    print(f"{C_RED}=== WARNING: DESTRUCTIVE ACTION ==={C_RESET}")
    print_warning("This action will PERMANENTLY delete the script's")
    print_warning(f"working folder and ALL its contents:")
    abs_base_dir = os.path.abspath(base_dir)
    print(f"\nFolder to be deleted: {C_YELLOW}{abs_base_dir}{C_RESET}\n")
    logger.warning(f"Target folder for nuke: {abs_base_dir}")

    if not os.path.isdir(abs_base_dir):
        print_error(f"The specified base directory does not exist: {abs_base_dir}")
        pause()
        return

    confirm1 = input(f"Are you ABSOLUTELY sure? Type '{C_YELLOW}yes{C_RESET}' to confirm: ").strip().lower()
    if confirm1 == 'yes':
        logger.info("Nuke first confirmation successful.")
        folder_name = os.path.basename(abs_base_dir)
        confirm2 = input(f"Type '{C_YELLOW}yes{C_RESET}' again to PERMANENTLY delete '{C_YELLOW}{folder_name}{C_RESET}': ").strip().lower()
        if confirm2 == 'yes':
            logger.warning(f"NUKE SECOND CONFIRMATION SUCCESSFUL. Proceeding with deletion of '{abs_base_dir}'.")
            print(f"\n{C_RED}[NUKE INITIATED]{C_RESET} Deleting folder '{abs_base_dir}'...")

            # --- FIX: Close log handler BEFORE deleting ---
            log_handler_closed = False
            for handler in logger.handlers[:]:
                if isinstance(handler, logging.FileHandler):
                    try:
                        handler.close()
                        logger.removeHandler(handler)
                        log_handler_closed = True
                        logger.info("Closed log file handler before nuke.")
                        break # Assume only one file handler
                    except Exception as log_close_e:
                        logger.error(f"Error closing log handler before nuke: {log_close_e}")
                        # Proceed with nuke attempt anyway? Or abort? Let's proceed.
                        print_warning(f"Could not close log file handle: {log_close_e}. Nuke might still fail.")

            if not log_handler_closed:
                 logger.warning("No active file handler found to close before nuke.")
            # --- End FIX ---

            try:
                shutil.rmtree(abs_base_dir)
                # If successful, logging won't work anymore, just print
                print(f"{C_GREEN}[OK] Successfully deleted folder: {abs_base_dir}{C_RESET}")
                print(f"{C_CYAN}[INFO] Exiting program as its working directory is gone.{C_RESET}")
                pause("Press Enter to exit.")
                sys.exit(0)
            except Exception as e:
                # Try to log the failure if logging was re-enabled somehow, otherwise just print
                print_error(f"Nuking FAILED: {e}") # Prints and tries to log
                logger.critical(f"NUKE FAILED for '{abs_base_dir}': {e}", exc_info=True)
                print_info("Some files or folders might still remain.")
                # Attempt to re-establish logging if it was closed
                try:
                    config = load_config() # Reload to get logging state
                    setup_file_logging(abs_base_dir, config.get('enable_logging', 'true'))
                    logger.info("Attempted to re-establish logging after failed nuke.")
                except Exception as post_nuke_log_e:
                    print_warning(f"Could not re-establish logging after failed nuke: {post_nuke_log_e}")

        else:
            print_info("Nuking aborted (second confirmation was not 'yes').")
            logger.info("Nuke aborted by user (second confirmation failed).")
    else:
        print_info("Nuking aborted (first confirmation was not 'yes').")
        logger.info("Nuke aborted by user (first confirmation failed).")

    pause()


def show_explanation():
    """Displays an explanation of the program."""
    clear_screen()
    print_title("How This Program Works")
    logger.info("Displaying explanation.")
    print("This tool automates fetching, renaming, and uploading images to s-ul.eu.")
    print("It keeps track of processed files in 'index.csv'.\n")

    explanation = [
        (f"{C_YELLOW}0{C_RESET}. How this works", "Displays this explanation."),
        (f"{C_YELLOW}1{C_RESET}. Show CSV data", "Shows the log of processed files ('index.csv')."),
        (f"{C_YELLOW}2{C_RESET}. Show folder structure", "Displays files/folders in the script's directory."),
        (f"{C_YELLOW}3{C_RESET}. Change settings", "Update Drive ID, API key, base folder, colors, logging."),
        (f"{C_YELLOW}4{C_RESET}. Start script", "Runs the main process: Download > Filter > Rename > Upload > Log."),
        (f"{C_YELLOW}5{C_RESET}. Rename item", "Renames a logged file locally and in the CSV, allows re-upload."),
        (f"{C_YELLOW}6{C_RESET}. Delete item", f"Removes an entry from CSV and deletes local files ({C_RED}not from s-ul.eu{C_RESET})."),
        (f"{C_YELLOW}7{C_RESET}. {C_RED}Nuke{C_RESET}", f"[{C_RED}DANGER{C_RESET}] Deletes the entire working folder after confirmation."),
        (f"{C_YELLOW}8{C_RESET}. Exit", "Terminates the program.")
    ]

    print(tabulate(explanation, headers=[f"{C_CYAN}Option{C_RESET}", f"{C_CYAN}Description{C_RESET}"], tablefmt="fancy_grid"))

    print("\nKey Folders:")
    print(f"- '{IMPORT_FOLDER}': Where files are downloaded from Google Drive.")
    print(f"- '{EXPORT_FOLDER}': Where renamed files are stored before/after upload.")
    print("\nKey Files:")
    print(f"- '{CONFIG_FILE}': Stores your settings.")
    print(f"- '{CSV_FILENAME}': Logs successfully processed files.")
    print(f"- '{LOG_FILENAME}': Detailed log of script activity (if enabled).")

    print("\nFor the latest version and more information, visit:")
    print(f"{C_CYAN}https://github.com/spodai/stuff/blob/main/team_banners.py{C_RESET}")

    pause("Press Enter to return to the main menu...")

# --- Main Menu ---

def menu():
    """Displays the main menu and handles user choices."""
    init_config()
    config = load_config()
    logger.info("="*30 + " Script Execution Started " + "="*30)

    while True:
        clear_screen()
        try:
             config = load_config()
             base_dir = config.get("base_dir", "Not Set")
             csv_path = os.path.join(base_dir, CSV_FILENAME) if base_dir != "Not Set" else None
             logger.debug("Main menu loop started. Config reloaded.")
        except SystemExit:
             return

        print_title("Main Menu")
        print(f"Base Directory: {C_YELLOW}{base_dir}{C_RESET}")
        print("-" * (len("Base Directory: ") + len(str(base_dir))))

        print(f"{C_YELLOW}0{C_RESET}. How this program works")
        print(f"{C_YELLOW}1{C_RESET}. Show CSV data")
        print(f"{C_YELLOW}2{C_RESET}. Show folder structure")
        print(f"{C_YELLOW}3{C_RESET}. Change settings")
        print(f"{C_YELLOW}4{C_RESET}. Start script (Download > Rename > Upload)")
        print(f"{C_YELLOW}5{C_RESET}. Rename logged item")
        print(f"{C_YELLOW}6{C_RESET}. Delete logged item")
        print(f"{C_YELLOW}7{C_RESET}. {C_RED}Nuke working directory{C_RESET}")
        print(f"{C_YELLOW}8{C_RESET}. Exit")

        choice = input(f"\nEnter your choice ({C_YELLOW}0-8{C_RESET}): ").strip()
        logger.info(f"User chose main menu option: {strip_ansi_codes(choice)}")

        if choice == "0":
            show_explanation()
        elif choice == "1":
            if csv_path:
                show_csv(csv_path)
            else:
                print_error("Base directory not set, cannot locate CSV.")
                pause()
        elif choice == "2":
            show_folder_structure(config)
        elif choice == "3":
            update_settings()
        elif choice == "4":
            start_script(config)
        elif choice == "5":
             if csv_path and base_dir != "Not Set":
                rename_existing_item(csv_path, base_dir, config)
             else:
                print_error("Base directory not set or CSV path invalid, cannot rename items.")
                pause()
        elif choice == "6":
             if csv_path and base_dir != "Not Set":
                delete_entry(csv_path, base_dir)
             else:
                print_error("Base directory not set or CSV path invalid, cannot delete items.")
                pause()
        elif choice == "7":
            if base_dir != "Not Set":
                 nuke_everything(base_dir)
            else:
                 print_error("Base directory not set, cannot nuke.")
                 pause()
        elif choice == "8":
            clear_screen()
            print_info("Exiting program.")
            logger.info("User chose to exit.")
            break
        else:
            print_error("Invalid choice.")
            logger.warning(f"Invalid main menu choice: {choice}")
            pause("Press Enter to try again...")

# --- Main Execution Block ---
if __name__ == "__main__":
    try:
        menu()
    except KeyboardInterrupt:
        clear_screen()
        print(f"{C_CYAN}\nOperation cancelled by user. Exiting.{C_RESET}")
        try:
            logger.warning("Operation cancelled by user (KeyboardInterrupt).")
        except Exception:
            pass
    except Exception as e:
        print(f"{C_RED}\nAn unexpected critical error occurred: {e}{C_RESET}")
        try:
            logger.critical(f"An unexpected critical error occurred: {e}", exc_info=True)
        except Exception:
             print(f"{C_RED}Traceback:{C_RESET}")
             traceback.print_exc()
        pause(f"{C_YELLOW}An critical error occurred. Check '{LOG_FILENAME}' if logging was enabled. Press Enter to exit.{C_RESET}")
    finally:
        try:
            logger.info("="*30 + " Script Execution Finished " + "="*30 + "\n")
            # Ensure all handlers are closed on exit
            for handler in logger.handlers[:]:
                try:
                    handler.close()
                    logger.removeHandler(handler)
                except Exception as e:
                    print(f"Warning: Error closing log handler during shutdown: {e}")
        except Exception:
            pass
        if colorama:
            try:
                colorama.deinit()
            except Exception:
                pass # Ignore errors during final cleanup

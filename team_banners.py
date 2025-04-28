#!/usr/bin/env python3
# -*- coding: utf-8 -*-

## All written with GPT and Gemini (honestly Gemini did the harder cooking), but hey it works :D
# A tool to fetch files from Google Drive OR local folder, upload them to s-ul.eu via API, and manage the process.
# - Saves Google Drive ID, API key, color, logging, and upload preferences in a Config file.
# - Creates a CSV log with: Timestamp, Original Filename, Renamed Filename, s-ul.eu URL.
# - Allows editing entries (rename, re-upload, edit URL, delete).
# - Allows bulk renaming of existing items in the CSV and bulk uploading of processed files.
# - Subsequent runs skip files already processed and logged in the CSV.
# - Conditionally logs activity to script_activity.log based on settings.
# - Conditionally uses console colors based on settings.
# - Conditionally uploads files based on settings.

## Usage:
# 1. Create a new directory (e.g., "team banners").
# 2. Place this script (team_banners.py) inside the new directory.
# 3. Run the script.
# 4. Follow the prompts (Drive ID, API key, color/logging/upload preferences).
# 5. Select desired action from the main menu.

## Note:
# You may wanna run this in pwsh or cmd or mobaxterm or termius or whatnot, the python cli itself wasn't stable in my testings :^)

## Directory structure created by the script:
# .
# ├── settings.conf      (Configuration file)
# ├── team_banners.py    (This script)
# ├── index.csv          (Log of processed files)
# ├── script_activity.log(Activity log file - if enabled)
# ├── Images import/     (Downloaded files from GDrive OR where user places local files)
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
_COLOR_CODE_RESET = "\033[0m"
_COLOR_CODE_RED = "\033[91m"
_COLOR_CODE_GREEN = "\033[92m"
_COLOR_CODE_YELLOW = "\033[93m"
_COLOR_CODE_BLUE = "\033[94m"
_COLOR_CODE_CYAN = "\033[96m"
_COLOR_CODE_MAGENTA = "\033[95m"

# --- Global Color Variables ---
C_RESET, C_RED, C_GREEN, C_YELLOW, C_BLUE, C_CYAN, C_MAGENTA = ("",)*7

# --- Setup Colorama ---
try:
    import colorama
except ImportError:
    print(f"{_COLOR_CODE_YELLOW}Optional library 'colorama' not found. Colors might not work correctly on older Windows versions.{_COLOR_CODE_RESET}")
    print(f"{_COLOR_CODE_YELLOW}Install with: pip install colorama{_COLOR_CODE_RESET}")
    colorama = None

# --- Setup Logging ---
logger = logging.getLogger(__name__)
if not logger.handlers:
    logger.addHandler(logging.NullHandler())
logger.setLevel(logging.INFO)

def setup_file_logging(base_dir, enable_logging):
    """Configures or removes file logging based on the enable_logging flag."""
    log_file_path = os.path.join(base_dir, LOG_FILENAME)
    file_handler = None
    for handler in logger.handlers[:]:
        if isinstance(handler, logging.FileHandler):
            if getattr(handler, 'baseFilename', None) == log_file_path:
                file_handler = handler
            logger.removeHandler(handler)
            handler.close()

    if str(enable_logging).lower() == 'true':
        fh = logging.FileHandler(log_file_path, encoding='utf-8')
        fh.setLevel(logging.INFO)
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
        fh.setFormatter(formatter)
        logger.addHandler(fh)
        if not file_handler:
             logger.info(f"File logging enabled. Log file: {log_file_path}")
    else:
        if file_handler:
            logger.info("File logging disabled and handler removed.")


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
        if colorama:
            try:
                colorama.init(autoreset=True)
            except Exception as e:
                print(f"Warning: Failed to initialize colorama: {e}")
    else:
        C_RESET, C_RED, C_GREEN, C_YELLOW, C_BLUE, C_CYAN, C_MAGENTA = ("",)*7
        if colorama:
            try:
                colorama.deinit()
            except Exception as e:
                print(f"Warning: Failed to deinitialize colorama: {e}")

# --- Utility Functions ---

def clear_screen():
    """Clears the terminal screen."""
    os.system('cls' if os.name == 'nt' else 'clear')

def pause(message="Press Enter to continue..."):
    """Pauses execution and waits for user to press Enter."""
    input(f"\n{C_MAGENTA}{message}{C_RESET}")

def print_title(title):
    """Prints a formatted title."""
    print(f"\n{C_BLUE}=== {title} ==={C_RESET}\n")

def print_success(message):
    """Prints a success message."""
    print(f"{C_GREEN}[OK] {message}{C_RESET}")
    logger.info(f"OK: {strip_ansi_codes(message)}")

def print_warning(message):
    """Prints a warning message."""
    print(f"{C_YELLOW}[WARN] {message}{C_RESET}")
    logger.warning(strip_ansi_codes(message))

def print_error(message, log_exception=False):
    """Prints an error message and logs it."""
    print(f"{C_RED}[ERROR] {message}{C_RESET}")
    clean_message = strip_ansi_codes(message)
    logger.error(clean_message)
    if log_exception:
        logger.exception(f"An exception occurred related to error: {clean_message}")

def print_info(message):
    """Prints an informational message. Does not log."""
    print(f"{C_CYAN}[INFO] {message}{C_RESET}")

# --- Configuration ---

def get_yes_no_input(prompt, default_yes=False):
    """Gets a 'y' or 'n' input from the user, with an optional default."""
    yes_opt = f"[{C_GREEN}Y{C_RESET}]" if default_yes else f"{C_GREEN}y{C_RESET}"
    no_opt = f"{C_RED}n{C_RESET}" if default_yes else f"[{C_RED}N{C_RESET}]"
    prompt_with_opts = f"{prompt} ({yes_opt}/{no_opt}): "

    while True:
        choice = input(prompt_with_opts).strip().lower()
        if not choice: # User pressed Enter
            return default_yes
        if choice in ['y', 'n']:
            return choice == 'y'
        else:
            # Use temporary color for error as global settings might not be applied yet
            print(f"{_COLOR_CODE_RED}[ERROR] Invalid input. Please enter 'y' or 'n'.{_COLOR_CODE_RESET}")


def init_config():
    """Initializes the configuration file if it doesn't exist."""
    if not os.path.exists(CONFIG_FILE):
        print(f"{_COLOR_CODE_CYAN}[INFO] Config file not found. Let's set it up.{_COLOR_CODE_RESET}")
        drive_id = input("Enter Google Drive folder ID or URL (leave blank if unused): ").strip()
        api_key = input("Enter s-ul.eu API key (leave blank if unused): ").strip()
        # Ask for preferences with defaults
        enable_colors = get_yes_no_input("Enable console colors?", default_yes=True)
        enable_logging = get_yes_no_input("Enable file logging?", default_yes=True)
        # Only allow enabling upload if API key is provided
        enable_upload = False
        if api_key:
            enable_upload = get_yes_no_input("Enable upload to s-ul.eu?", default_yes=True)
        else:
            print(f"{_COLOR_CODE_YELLOW}[WARN] API Key not provided. Uploads will be disabled by default.{_COLOR_CODE_RESET}")


        base_dir = os.path.dirname(os.path.abspath(__file__))

        # Apply settings immediately for feedback during setup
        apply_color_settings(enable_colors)
        setup_file_logging(base_dir, enable_logging)

        logger.info("Attempting to initialize configuration file.")

        config = configparser.ConfigParser()
        config['DEFAULT'] = {
            'drive_id': drive_id,
            'api_key': api_key,
            'base_dir': base_dir,
            'enable_colors': str(enable_colors).lower(),
            'enable_logging': str(enable_logging).lower(),
            'enable_upload': str(enable_upload).lower() # Added upload setting
        }

        try:
            with open(CONFIG_FILE, 'w', encoding='utf-8') as configfile:
                config.write(configfile)
            print_success("Config saved.")
            logger.info(f"Config file '{CONFIG_FILE}' created and saved successfully.")
            os.makedirs(os.path.join(base_dir, IMPORT_FOLDER), exist_ok=True)
            os.makedirs(os.path.join(base_dir, EXPORT_FOLDER), exist_ok=True)
            print_success(f"Created folders: '{IMPORT_FOLDER}' and '{EXPORT_FOLDER}'.")
            logger.info(f"Ensured directories exist: '{IMPORT_FOLDER}', '{EXPORT_FOLDER}'.")
            pause()
        except IOError as e:
            message = f"Could not write config file: {e}"
            print_error(message, log_exception=True)
            logger.critical(f"CRITICAL: Failed to initialize config file '{CONFIG_FILE}'. Exiting.")
            sys.exit(1)
        except Exception as e:
            message = f"An error occurred during initial setup: {e}"
            print_error(message, log_exception=True)
            logger.critical(f"CRITICAL: Failed during initial setup: {e}", exc_info=True)
            sys.exit(1)

def load_config():
    """Loads configuration from the file, handling defaults for new settings."""
    if not os.path.exists(CONFIG_FILE):
        print(f"{_COLOR_CODE_RED}[ERROR] Configuration file '{CONFIG_FILE}' not found.{_COLOR_CODE_RESET}")
        print(f"{_COLOR_CODE_CYAN}[INFO] Please run the script again to initialize the configuration.{_COLOR_CODE_RESET}")
        sys.exit(1)

    config = configparser.ConfigParser()
    base_dir_from_config = None
    # Set defaults for potentially missing keys
    enable_colors = 'true'
    enable_logging = 'true'
    enable_upload = 'true'

    try:
        config.read(CONFIG_FILE, encoding='utf-8')
        if 'DEFAULT' not in config:
            raise configparser.Error("Missing [DEFAULT] section in config.")

        # Check for essential keys (allow drive_id and api_key to be blank)
        required_keys = ['base_dir']
        for key in required_keys:
            if key not in config['DEFAULT'] or not config['DEFAULT'][key]:
                raise configparser.Error(f"Missing or empty essential key '{key}' in config.")

        base_dir_from_config = config['DEFAULT']['base_dir']

        # Get settings, applying defaults if missing
        enable_colors = config['DEFAULT'].get('enable_colors', enable_colors).lower()
        enable_logging = config['DEFAULT'].get('enable_logging', enable_logging).lower()
        enable_upload = config['DEFAULT'].get('enable_upload', enable_upload).lower() # Added upload setting

        # Apply settings *before* logging/printing
        apply_color_settings(enable_colors)
        setup_file_logging(base_dir_from_config, enable_logging)

        if not os.path.isdir(base_dir_from_config):
            message = f"Base directory specified in config does not exist: {base_dir_from_config}"
            print_error(message)
            print_info("Please check settings.conf or delete it and run again.")
            sys.exit(1)

        logger.info("Configuration loaded successfully.")
        # Return the full dictionary reflecting the actual state
        loaded_config = dict(config['DEFAULT'])
        loaded_config['enable_colors'] = enable_colors
        loaded_config['enable_logging'] = enable_logging
        loaded_config['enable_upload'] = enable_upload # Ensure returned config has upload setting
        return loaded_config

    except (configparser.Error, IOError) as e:
        message = f"Failed to load or parse configuration file: {e}"
        apply_color_settings('true') # Assume colors OK for critical error
        print_error(message)
        try:
            if base_dir_from_config:
                 setup_file_logging(base_dir_from_config, 'true') # Try to log
            logger.critical(f"CRITICAL: Failed to load configuration: {e}", exc_info=True)
        except Exception as log_e:
             print(f"Additionally, failed to log critical error: {log_e}")
        sys.exit(1)
    except Exception as e:
        message = f"An unexpected error occurred loading configuration: {e}"
        apply_color_settings('true')
        print_error(message)
        try:
            logger.critical(f"CRITICAL: Unexpected error loading config: {e}", exc_info=True)
        except Exception as log_e:
             print(f"Additionally, failed to log critical error: {log_e}")
        sys.exit(1)


def update_settings(config): # Accept config dictionary
    """Allows the user to update settings in the config file."""
    config_parser = configparser.ConfigParser() # Use a parser to write changes
    config_parser['DEFAULT'] = config # Load current config into parser

    logger.info("Entered settings menu.")

    while True:
        clear_screen()
        print_title("Settings Menu")
        # Read values directly from the passed config dictionary
        current_drive_id = config.get('drive_id', '')
        current_api_key = config.get('api_key', '')
        current_base_dir = config.get('base_dir', 'Not Set')
        current_colors = config.get('enable_colors', 'true').lower()
        current_logging = config.get('enable_logging', 'true').lower()
        current_upload = config.get('enable_upload', 'true').lower()
        base_dir_for_logging = current_base_dir # For logging setup on change

        color_status = f"{C_GREEN}Enabled{C_RESET}" if current_colors == 'true' else f"{C_RED}Disabled{C_RESET}"
        logging_status = f"{C_GREEN}Enabled{C_RESET}" if current_logging == 'true' else f"{C_RED}Disabled{C_RESET}"
        upload_status = f"{C_GREEN}Enabled{C_RESET}" if current_upload == 'true' else f"{C_RED}Disabled{C_RESET}"

        print(f"1. Google Drive Folder ID/URL: {C_YELLOW}{current_drive_id or '(blank)'}{C_RESET}")
        print(f"2. S-UL API Key: {C_YELLOW}{current_api_key or '(blank)'}{C_RESET}")
        print(f"3. Base Folder: {C_YELLOW}{current_base_dir}{C_RESET}")
        print(f"4. Console Colors: {color_status}")
        print(f"5. File Logging: {logging_status}")
        print(f"6. Enable Uploads: {upload_status}")
        print(f"\n{C_YELLOW}0{C_RESET}. Back to Main Menu")

        choice = input(f"\nChoose setting to change ({C_YELLOW}1-6{C_RESET}, or {C_YELLOW}0{C_RESET} to exit): ").strip()

        setting_changed = False
        setting_key = None
        old_value = None
        new_value = None

        if choice == '1':
            setting_key = 'drive_id'
            old_value = current_drive_id
            new_value_input = input(f"Enter new Google Drive Folder ID or URL (current: {old_value or '(blank)'}): ").strip()
            new_value = new_value_input
            config[setting_key] = new_value # Update in-memory dict
            config_parser['DEFAULT'][setting_key] = new_value # Update parser for saving
            setting_changed = True
        elif choice == '2':
            setting_key = 'api_key'
            old_value = current_api_key
            new_value_input = input(f"Enter new S-UL API key (current: {old_value or '(blank)'}): ").strip()
            new_value = new_value_input
            # If API key is removed, disable uploads automatically
            if not new_value and config.get('enable_upload', 'true').lower() == 'true':
                 config['enable_upload'] = 'false' # Update in-memory dict
                 config_parser['DEFAULT']['enable_upload'] = 'false' # Update parser
                 print_warning("API key removed, automatically disabling uploads.")
                 logger.warning("API key removed, automatically disabling uploads.")
            config[setting_key] = new_value # Update in-memory dict
            config_parser['DEFAULT'][setting_key] = new_value # Update parser
            setting_changed = True
        elif choice == '3':
            setting_key = 'base_dir'
            old_value = current_base_dir
            new_value_input = input(f"Enter new base folder path (current: {old_value}): ").strip()
            if os.path.isdir(new_value_input):
                new_value = os.path.abspath(new_value_input)
                config[setting_key] = new_value # Update in-memory dict
                config_parser['DEFAULT'][setting_key] = new_value # Update parser
                setting_changed = True
            elif not new_value_input:
                 print_warning("Base directory cannot be empty.")
                 pause()
            else:
                print_error("Invalid folder path.")
                pause()
        elif choice == '4':
            setting_key = 'enable_colors'
            old_value = current_colors
            new_value = 'false' if old_value == 'true' else 'true'
            config[setting_key] = new_value # Update in-memory dict
            config_parser['DEFAULT'][setting_key] = new_value # Update parser
            apply_color_settings(new_value)
            print_info(f"Console colors set to: {'Enabled' if new_value == 'true' else 'Disabled'}")
            setting_changed = True
            pause("Setting toggled. Press Enter to save or choose another option.")
        elif choice == '5':
            setting_key = 'enable_logging'
            old_value = current_logging
            new_value = 'false' if old_value == 'true' else 'true'
            config[setting_key] = new_value # Update in-memory dict
            config_parser['DEFAULT'][setting_key] = new_value # Update parser
            if base_dir_for_logging and base_dir_for_logging != 'Not Set':
                 setup_file_logging(base_dir_for_logging, new_value)
                 print_info(f"File logging set to: {'Enabled' if new_value == 'true' else 'Disabled'}")
                 setting_changed = True
                 pause("Setting toggled. Press Enter to save or choose another option.")
            else:
                 print_error("Cannot toggle logging: Base directory not set.")
                 config[setting_key] = old_value # Revert in-memory
                 config_parser['DEFAULT'][setting_key] = old_value # Revert parser
                 pause()
        elif choice == '6': # Upload toggle
            setting_key = 'enable_upload'
            old_value = current_upload
            new_value = 'false' if old_value == 'true' else 'true'
            # Prevent enabling uploads if API key is missing
            api_key_present = bool(config.get('api_key', ''))
            if new_value == 'true' and not api_key_present:
                 print_error("Cannot enable uploads: S-UL API Key is not set (Option 2).")
                 pause()
                 setting_key = None # Prevent logging/saving this attempt
            else:
                config[setting_key] = new_value # Update in-memory dict
                config_parser['DEFAULT'][setting_key] = new_value # Update parser
                print_info(f"Uploads set to: {'Enabled' if new_value == 'true' else 'Disabled'}")
                setting_changed = True
                pause("Setting toggled. Press Enter to save or choose another option.")

        elif choice == '0':
            logger.info("Exited settings menu.")
            break
        else:
            print_error("Invalid option.")
            logger.warning(f"Invalid settings menu choice: {choice}")
            pause()

        if setting_changed and setting_key: # Ensure setting_key is set before saving
            try:
                with open(CONFIG_FILE, 'w', encoding='utf-8') as configfile:
                    config_parser.write(configfile) # Save changes from parser
                if choice not in ['4', '5', '6']:
                    print_success("Setting updated!")
                logger.info(f"Setting '{setting_key}' updated from '{old_value}' to '{new_value}'. Config saved.")
                # If base_dir changed, re-setup logging for the new path
                if setting_key == 'base_dir' and old_value != new_value:
                     logger.info("Base directory changed, re-initializing logger.")
                     current_logging_state = config.get('enable_logging', 'true') # Use updated in-memory config
                     setup_file_logging(new_value, current_logging_state)
                if choice not in ['4', '5', '6']:
                    pause()
            except IOError as e:
                print_error(f"Could not save config file: {e}", log_exception=True)
                # Attempt to revert in-memory config change if save failed
                if setting_key:
                     config[setting_key] = old_value # Revert in-memory dict
                     # Also revert color/logging application if toggle failed to save
                     if setting_key == 'enable_colors': apply_color_settings(old_value)
                     if setting_key == 'enable_logging' and base_dir_for_logging: setup_file_logging(base_dir_for_logging, old_value)
                     # No immediate action needed for enable_upload revert
                logger.error(f"Failed to save updated setting '{setting_key}'. Reverted in memory.")
                pause()

# --- Core Functionality ---
# (Functions now generally accept `config` dictionary where needed)

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
    """Prompts user to rename downloaded files individually and copies them."""
    if not files_to_process:
        logger.info("prompt_rename_images called with no files to process.")
        return []

    clear_screen()
    print_title("Rename New Files Individually")
    logger.info(f"Starting individual rename process for {len(files_to_process)} file(s).")
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

    logger.info(f"Individual rename process finished. Renamed: {renamed_count}, Skipped: {skipped_count}.")
    return renamed_list

def bulk_rename_files(import_path, export_path, files_to_process):
    """Renames files sequentially using a base name and copies them."""
    if not files_to_process:
        logger.info("bulk_rename_files called with no files to process.")
        return []

    clear_screen()
    print_title("Bulk Rename New Files")
    logger.info(f"Starting bulk rename process for {len(files_to_process)} file(s).")
    os.makedirs(export_path, exist_ok=True)
    renamed_list = []
    skipped_count = 0
    renamed_count = 0

    while True:
        base_name = input("Enter base name for renaming (e.g., 'TEAM'): ").strip()
        if base_name:
            break
        else:
            print_error("Base name cannot be empty.")

    start_number = 1 # Start numbering from 01
    num_digits = 2 # Use 2 digits by default (01, 02...) Adjust if needed

    print_info(f"Renaming files using base '{base_name}' starting from {start_number:0{num_digits}d}...")
    logger.info(f"Bulk renaming with base '{base_name}', starting number {start_number}, digits {num_digits}.")

    for i, original_filename in enumerate(sorted(files_to_process)):
        src_path = os.path.join(import_path, original_filename)
        if not os.path.isfile(src_path):
            print_warning(f"Source file not found, skipping: {original_filename}")
            logger.warning(f"Bulk rename skipped: Source file not found at '{src_path}'.")
            skipped_count += 1
            continue

        _, ext = os.path.splitext(original_filename)
        # Format number with leading zeros
        new_filename_base = f"{base_name}{i + start_number:0{num_digits}d}"
        new_filename = f"{new_filename_base}{ext}"
        dest_path = os.path.join(export_path, new_filename)
        logger.info(f"Processing bulk rename: '{original_filename}' -> '{new_filename}'.")

        # Handle potential filename conflicts (less likely with sequential names, but possible)
        counter = 1
        while os.path.exists(dest_path):
            print_warning(f"File '{new_filename}' already exists in export folder (conflict during bulk rename).")
            logger.warning(f"Bulk rename conflict: '{new_filename}' already exists at '{dest_path}'.")
            # Append _conflict_counter to avoid overwriting in bulk mode
            new_filename = f"{new_filename_base}_conflict_{counter}{ext}"
            dest_path = os.path.join(export_path, new_filename)
            print_info(f"Trying new name: {new_filename}")
            logger.info(f"Bulk rename conflict: Trying new name '{new_filename}'.")
            counter += 1
            if counter > 5: # Limit conflict resolution attempts
                 print_error(f"Too many conflicts for '{original_filename}', skipping.")
                 logger.error(f"Bulk rename skipped: Too many conflicts for '{original_filename}'.")
                 new_filename = None
                 break

        if new_filename is None:
            skipped_count += 1
            continue

        try:
            shutil.copy2(src_path, dest_path)
            print(f"  {original_filename} -> {C_GREEN}{new_filename}{C_RESET}") # Show rename mapping
            logger.info(f"Successfully copied '{src_path}' to '{dest_path}'.")
            renamed_list.append((original_filename, new_filename, dest_path))
            renamed_count += 1
        except IOError as e:
            print_error(f"Could not copy file '{original_filename}' to '{dest_path}': {e}", log_exception=True)
            skipped_count += 1
        except Exception as e:
            print_error(f"An unexpected error occurred during copy: {e}", log_exception=True)
            skipped_count += 1

    print_success(f"\nBulk rename complete. Renamed: {renamed_count}, Skipped: {skipped_count}.")
    logger.info(f"Bulk rename process finished. Renamed: {renamed_count}, Skipped: {skipped_count}.")
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
        logger.info("No successful uploads/processed files to write to CSV.")
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
                writer.writerow([timestamp, original, renamed, str(url)])
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

# --- Edit Entry Functionality ---

def edit_entry(csv_path, base_dir, config):
    """Allows editing (rename, re-upload, edit URL, delete) an existing CSV entry."""
    api_key = config.get('api_key')
    uploads_enabled = str(config.get('enable_upload', 'true')).lower() == 'true'
    export_path_base = os.path.join(base_dir, EXPORT_FOLDER)
    import_path_base = os.path.join(base_dir, IMPORT_FOLDER)
    logger.info("Entered Edit Entry menu.")

    # --- Optimization: Read CSV data only once at the start ---
    header_clean, data = get_csv_data(csv_path, add_color=False)
    if header_clean is None:
        print_error("Could not read CSV file or file is invalid.")
        pause()
        return
    if not data:
        print_info("No entries found in the CSV log.")
        logger.info("No CSV entries found to edit.")
        pause()
        return
    # Create colored header for display
    header_colored = [f"{C_CYAN}{h}{C_RESET}" for h in header_clean]
    # --- End Optimization ---

    while True: # Loop for selecting entry
        clear_screen()
        print_title("Edit CSV Entry")

        # --- Optimization: Use in-memory data for display ---
        display_header = [f"{C_CYAN}#{C_RESET}"] + header_colored
        display_data = [[idx + 1] + row for idx, row in enumerate(data)]
        # --- End Optimization ---

        print(tabulate(display_data, headers=display_header, tablefmt="fancy_grid"))
        print(f"\n{C_YELLOW}0{C_RESET}. Back to Main Menu")
        choice = input(f"Enter the number ({C_YELLOW}#{C_RESET}) of the entry to edit (or 0 to exit): ").strip()

        if choice == '0':
            logger.info("Exited Edit Entry menu.")
            break # Exit entry selection loop

        try:
            item_index = int(choice) - 1
            if not 0 <= item_index < len(data):
                raise ValueError("Index out of range.")
        except ValueError:
            print_error("Invalid number.")
            logger.warning(f"Invalid edit entry choice: {choice}")
            pause("Press Enter to try again...")
            continue

        # --- Entry Selected - Show Sub-Menu ---
        # Work on a copy of the selected row to handle potential save failures
        original_row_data = list(data[item_index])
        current_row_copy = list(original_row_data) # Copy for modifications

        try:
            if len(current_row_copy) >= 4:
                # Get initial values from the copy
                timestamp, original_name, renamed_name, current_url = current_row_copy[:4]
            else:
                raise ValueError("Row does not have enough columns.")
        except ValueError as e:
             print_error(f"CSV row has unexpected format ({e}). Cannot proceed.")
             pause()
             continue

        action_loop_active = True
        while action_loop_active: # Loop for actions on selected entry
            clear_screen()
            # Display current data for the entry being edited (from current_row_copy)
            current_timestamp, current_original_name, current_renamed_name, current_url_display = current_row_copy[:4]
            print_title(f"Editing Entry #{item_index + 1}")
            print(f"  Original: {current_original_name}")
            print(f"  Renamed:  {current_renamed_name}")
            print(f"  URL:      {current_url_display or '(none)'}")
            print(f"  Timestamp:{current_timestamp}")
            print("-" * 30)
            print("Choose an action:")
            print("1. Change Renamed File (and optionally re-upload)")
            print("2. Re-upload File")
            print("3. Manually Edit URL")
            print(f"4. {C_RED}Delete Entry{C_RESET}")
            print("\n0. Select Different Entry / Back")

            action_choice = input("> ").strip()
            save_needed = False # Flag to indicate CSV needs saving for this action

            if action_choice == '1': # Change Renamed File
                logger.info(f"Editing Entry #{item_index + 1}: Action 'Change Renamed File' selected.")
                _, ext = os.path.splitext(current_renamed_name) # Use current name from copy
                new_name_base = input(f"Enter the new name for '{current_renamed_name}' (without extension): ").strip()

                if not new_name_base:
                    print_warning("New name cannot be empty.")
                    pause()
                    continue

                new_renamed_name = f"{new_name_base}{ext}"
                old_export_path = os.path.join(export_path_base, current_renamed_name)
                new_export_path = os.path.join(export_path_base, new_renamed_name)
                logger.info(f"User provided new name: '{new_renamed_name}'.")

                if new_renamed_name != current_renamed_name and os.path.exists(new_export_path):
                    print_error(f"A file named '{new_renamed_name}' already exists in '{EXPORT_FOLDER}'.")
                    logger.warning(f"Rename conflict: Target file '{new_export_path}' already exists.")
                    pause()
                    continue

                # Rename local file
                renamed_locally = False
                if os.path.exists(old_export_path):
                    if new_renamed_name != current_renamed_name:
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
                        renamed_locally = True
                else:
                    print_warning(f"Original renamed file '{current_renamed_name}' not found in '{EXPORT_FOLDER}'.")
                    renamed_locally = True

                # Optionally re-upload
                new_url_after_rename = "" if not uploads_enabled else current_url_display
                if renamed_locally and uploads_enabled:
                    reupload_choice = get_yes_no_input(f"Re-upload '{new_renamed_name}' now?")
                    if reupload_choice:
                        if not api_key: print_error("Cannot re-upload: API key missing.")
                        elif not os.path.exists(new_export_path): print_error(f"Cannot re-upload: File not found '{new_export_path}'.")
                        else:
                            uploaded_url = upload_to_sul(new_export_path, api_key)
                            if uploaded_url: new_url_after_rename = uploaded_url
                            else: print_warning("Re-upload failed. Keeping previous URL (if any).")
                    else:
                        logger.info("User chose not to re-upload after rename.")
                        new_url_after_rename = current_url_display
                elif not uploads_enabled:
                     new_url_after_rename = ""

                # Update current_row_copy in memory
                current_row_copy[2] = new_renamed_name
                current_row_copy[3] = str(new_url_after_rename)
                current_row_copy[0] = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
                save_needed = True

            elif action_choice == '2': # Re-upload File
                 logger.info(f"Editing Entry #{item_index + 1}: Action 'Re-upload File' selected.")
                 if not uploads_enabled:
                      print_error("Cannot re-upload: Uploads are disabled in settings.")
                      pause()
                      continue
                 if not api_key:
                      print_error("Cannot re-upload: API key missing.")
                      pause()
                      continue

                 file_to_upload = os.path.join(export_path_base, current_renamed_name)
                 if not os.path.exists(file_to_upload):
                      print_error(f"Cannot re-upload: File '{current_renamed_name}' not found in '{EXPORT_FOLDER}'.")
                      pause()
                      continue

                 print_info(f"Attempting to re-upload '{current_renamed_name}'...")
                 new_url_after_reupload = upload_to_sul(file_to_upload, api_key)

                 if new_url_after_reupload:
                      # Update current_row_copy in memory
                      current_row_copy[3] = new_url_after_reupload
                      current_row_copy[0] = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
                      save_needed = True
                 else:
                      print_error("Re-upload failed. CSV not updated.")

            elif action_choice == '3': # Manually Edit URL
                 logger.info(f"Editing Entry #{item_index + 1}: Action 'Manually Edit URL' selected.")
                 print_info(f"Current URL: {current_url_display or '(none)'}")
                 manual_url = input("Enter new URL (leave blank to remove): ").strip()

                 # Update current_row_copy in memory
                 current_row_copy[3] = manual_url
                 current_row_copy[0] = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
                 save_needed = True

            elif action_choice == '4': # Delete Entry
                 logger.info(f"Editing Entry #{item_index + 1}: Action 'Delete Entry' selected.")
                 print_warning(f"This will delete the entry for '{current_renamed_name}' from the CSV.")
                 delete_files_choice = get_yes_no_input("Also delete corresponding local files (Import/Export)?")

                 # Remove from main data list (not the copy)
                 removed_row_data = data.pop(item_index)
                 print_success(f"Removed entry for '{current_renamed_name}' (Original: {current_original_name}).")
                 logger.info(f"Removed item #{item_index+1} ('{current_renamed_name}', Original: '{current_original_name}') from main data list.")

                 if delete_files_choice:
                     logger.info(f"User chose to delete local files for removed item #{item_index+1}.")
                     files_to_delete = []
                     if current_renamed_name: files_to_delete.append(os.path.join(export_path_base, current_renamed_name))
                     if current_original_name: files_to_delete.append(os.path.join(import_path_base, current_original_name))

                     if not files_to_delete: logger.warning("Could not determine local filenames to delete.")
                     else:
                         deleted_count = 0
                         for file_path in files_to_delete:
                             logger.info(f"Attempting to delete local file: {file_path}")
                             if os.path.exists(file_path):
                                 try:
                                     os.remove(file_path)
                                     print_success(f"Deleted local file: {file_path}")
                                     deleted_count += 1
                                 except OSError as e: print_error(f"Failed to delete local file {file_path}: {e}", log_exception=True)
                             else: logger.info(f"Local file not found for deletion, skipping: {file_path}")
                         if deleted_count > 0: logger.info(f"Deleted {deleted_count} local file(s).")
                 else:
                     logger.info(f"User chose not to delete local files.")

                 # Save the modified (shorter) main data list back to CSV
                 try:
                     with open(csv_path, 'w', newline='', encoding='utf-8') as f:
                         writer = csv.writer(f)
                         writer.writerow(header_clean)
                         writer.writerows(data) # Write the main data list
                     print_success("CSV log updated successfully.")
                     logger.info(f"CSV log updated successfully after deleting item #{item_index+1}.")
                     action_loop_active = False # Exit action loop after deletion
                     pause("Entry deleted. Press Enter...")
                 except (IOError, csv.Error) as e:
                     print_error(f"Failed to save updated CSV after deletion: {e}", log_exception=True)
                     print_warning("Log entry was removed in this session, but failed to save to disk.")
                     # Attempt to restore the removed row in the main data list
                     data.insert(item_index, original_row_data)
                     pause()

                 continue # Go back to entry selection after delete attempt

            elif action_choice == '0':
                 logger.debug("User chose to go back from action sub-menu.")
                 action_loop_active = False # Exit action sub-menu loop
                 continue # Go back to entry selection loop
            else:
                 print_error("Invalid action choice.")
                 logger.warning(f"Invalid edit action choice: {action_choice}")
                 pause() # Pause on invalid choice

            # Save CSV if an action other than delete was performed successfully
            if save_needed:
                try:
                    # Update the main data list with the modified row copy
                    data[item_index] = list(current_row_copy)
                    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
                        writer = csv.writer(f)
                        writer.writerow(header_clean) # Write clean header
                        writer.writerows(data) # Write updated main data list
                    print_success("CSV log updated successfully.")
                    logger.info(f"CSV log updated successfully after action '{action_choice}' on item #{item_index + 1}.")
                    pause("Action complete. Press Enter...") # Pause after successful action
                except (IOError, csv.Error) as e:
                    print_error(f"Failed to save updated CSV: {e}", log_exception=True)
                    print_warning("CSV update failed. Changes might be lost.")
                    # Main data list was already updated, difficult to revert cleanly here.
                    pause() # Pause after save error

                # Reset flag and potentially break inner loop if needed, or just let it loop
                save_needed = False
                # Optionally break action_loop_active here if you want to go back to entry selection after each successful action
                # action_loop_active = False


# --- Bulk Upload Function ---
def bulk_upload_from_csv(config):
    """Uploads files listed in the CSV from the export folder, skipping those with existing URLs."""
    clear_screen()
    print_title("Bulk Upload Existing Items")
    logger.info("Starting bulk upload process (Option 7).") # Corrected option number

    base_dir = config.get("base_dir")
    api_key = config.get("api_key")
    uploads_enabled = str(config.get('enable_upload', 'true')).lower() == 'true'
    csv_path = os.path.join(base_dir, CSV_FILENAME) if base_dir != "Not Set" else None
    export_path_base = os.path.join(base_dir, EXPORT_FOLDER) if base_dir != "Not Set" else None

    if not base_dir or not csv_path or not export_path_base:
        print_error("Base directory not set, cannot perform bulk upload.")
        pause()
        return

    if not uploads_enabled:
        print_warning("Uploads are disabled in settings (Option 3). Cannot perform bulk upload.")
        logger.warning("Bulk upload aborted: Uploads disabled in settings.")
        pause()
        return

    if not api_key:
        print_error("S-UL API Key is not set in configuration (Option 3). Cannot perform bulk upload.")
        logger.error("Bulk upload aborted: API key not set.")
        pause()
        return

    header, data = get_csv_data(csv_path, add_color=False) # Get clean data

    if header is None:
        print_error("Could not read CSV file or file is invalid.")
        pause()
        return
    if not data:
        print_info("No entries found in the CSV log to upload.")
        logger.info("Bulk upload: No CSV entries found.")
        pause()
        return

    print_info(f"Found {len(data)} entries in CSV. Checking export folder and uploading...")
    logger.info(f"Starting bulk upload for {len(data)} CSV entries.")

    updated_rows_indices = [] # Store indices of rows that got a new URL
    upload_attempts = 0
    successful_uploads = 0
    failed_uploads = 0
    skipped_missing = 0
    skipped_has_url = 0 # Counter for skipped items with existing URLs

    # Define column indices based on standard header
    try:
        ts_idx, orig_idx, renamed_idx, url_idx = 0, 1, 2, 3
        if not (header[ts_idx] == "Timestamp" and header[orig_idx] == "Original" and
                header[renamed_idx] == "Renamed" and header[url_idx] == "URL"):
            raise ValueError("CSV header mismatch")
    except (IndexError, ValueError):
        print_error("CSV file header does not match expected format (Timestamp, Original, Renamed, URL).")
        logger.error("Bulk upload aborted: CSV header mismatch.")
        pause()
        return


    for idx, row in enumerate(data):
        try:
            renamed_name = row[renamed_idx]
            current_url = row[url_idx]
            file_path = os.path.join(export_path_base, renamed_name)

            # --- Skip if URL already exists ---
            if current_url:
                print_info(f"Skipping '{renamed_name}': Already has URL.")
                logger.info(f"Bulk upload skip: '{renamed_name}' already has URL.")
                skipped_has_url += 1
                continue
            # --- End Skip ---

            if not os.path.exists(file_path):
                print_warning(f"Skipping '{renamed_name}': File not found in '{EXPORT_FOLDER}'.")
                logger.warning(f"Bulk upload skip: File not found at '{file_path}'.")
                skipped_missing += 1
                continue

            upload_attempts += 1
            print(f"\n--- Uploading {renamed_name} ({upload_attempts}/{len(data) - skipped_missing - skipped_has_url}) ---")
            new_url = upload_to_sul(file_path, api_key)

            if new_url:
                successful_uploads += 1
                # Update URL and timestamp in the data list
                data[idx][url_idx] = new_url
                data[idx][ts_idx] = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
                updated_rows_indices.append(idx)
                logger.info(f"Bulk upload success for '{renamed_name}'. URL updated.")
            else:
                failed_uploads += 1
                logger.warning(f"Bulk upload failed for '{renamed_name}'.")

        except IndexError:
            print_error(f"Skipping row {idx+1}: Incorrect number of columns.")
            logger.error(f"Bulk upload skip: Row {idx+1} has incorrect column count: {row}")
            failed_uploads += 1
        except Exception as e:
             print_error(f"Unexpected error processing row {idx+1} for '{renamed_name}': {e}", log_exception=True)
             failed_uploads += 1


    # --- Save updated CSV if any URLs were changed ---
    if updated_rows_indices:
        print_info(f"\nSaving updated URLs to '{CSV_FILENAME}'...")
        logger.info(f"Attempting to save CSV after bulk upload. {len(updated_rows_indices)} rows updated.")
        try:
            with open(csv_path, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.writer(csvfile)
                writer.writerow(header)
                writer.writerows(data)
            print_success("CSV log updated successfully.")
            logger.info("CSV log saved successfully after bulk upload.")
        except (IOError, csv.Error) as e:
            print_error(f"Failed to save updated CSV after bulk upload: {e}", log_exception=True)
    elif successful_uploads > 0 or failed_uploads > 0:
         print_info("\nNo new URLs obtained or CSV update needed.")
         logger.info("No CSV updates required after bulk upload.")


    # --- Summary ---
    print_title("Bulk Upload Summary")
    print_info(f"Total CSV Entries: {len(data)}")
    print_info(f"Entries Already Having URL: {skipped_has_url}")
    print_info(f"Files Found in Export Folder (without URL): {len(data) - skipped_missing - skipped_has_url}")
    print_info(f"Uploads Attempted: {upload_attempts}")
    print_success(f"Successful Uploads: {successful_uploads}")
    if updated_rows_indices:
        print_success(f"CSV Rows Updated: {len(updated_rows_indices)}")
    if failed_uploads > 0:
        print_error(f"Failed Uploads: {failed_uploads}")
    if skipped_missing > 0:
        print_warning(f"Skipped (File Not Found): {skipped_missing}")

    logger.info(f"Bulk upload summary: TotalEntries={len(data)}, SkippedURL={skipped_has_url}, Found={len(data)-skipped_missing-skipped_has_url}, Attempted={upload_attempts}, Success={successful_uploads}, Failed={failed_uploads}, SkippedNotFound={skipped_missing}, CSVUpdated={len(updated_rows_indices)}")
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

            # --- Close log handler BEFORE deleting ---
            log_handler_closed = False
            for handler in logger.handlers[:]:
                if isinstance(handler, logging.FileHandler):
                    try:
                        handler.close()
                        logger.removeHandler(handler)
                        log_handler_closed = True
                        logger.info("Closed log file handler before nuke.")
                        break
                    except Exception as log_close_e:
                        logger.error(f"Error closing log handler before nuke: {log_close_e}")
                        print_warning(f"Could not close log file handle: {log_close_e}. Nuke might still fail.")

            if not log_handler_closed:
                 logger.warning("No active file handler found to close before nuke.")
            # --- End Close Log Handler ---

            try:
                shutil.rmtree(abs_base_dir)
                print(f"{C_GREEN}[OK] Successfully deleted folder: {abs_base_dir}{C_RESET}")
                print(f"{C_CYAN}[INFO] Exiting program as its working directory is gone.{C_RESET}")
                pause("Press Enter to exit.")
                sys.exit(0)
            except Exception as e:
                print_error(f"Nuking FAILED: {e}")
                logger.critical(f"NUKE FAILED for '{abs_base_dir}': {e}", exc_info=True)
                print_info("Some files or folders might still remain.")
                # Attempt to re-establish logging if it was closed
                try:
                    # Need to reload config to know if logging should be enabled
                    # This might fail if config was deleted, hence the outer try-except
                    temp_config = load_config()
                    setup_file_logging(abs_base_dir, temp_config.get('enable_logging', 'true'))
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
    print("This tool automates fetching (Drive/Local), renaming, and uploading images to s-ul.eu.")
    print("It keeps track of processed files in 'index.csv'.\n")

    # Corrected numbering for options
    explanation = [
        (f"{C_YELLOW}0{C_RESET}. How this works", "Displays this explanation."),
        (f"{C_YELLOW}1{C_RESET}. Show CSV data", "Shows the log of processed files ('index.csv')."),
        (f"{C_YELLOW}2{C_RESET}. Show folder structure", "Displays files/folders in the script's directory."),
        (f"{C_YELLOW}3{C_RESET}. Change settings", "Update Drive ID, API key, base folder, colors, logging, uploads."),
        (f"{C_YELLOW}4{C_RESET}. Start script", "Choose source (Drive/Local), then Download/Filter > Rename > Upload > Log."),
        (f"{C_YELLOW}5{C_RESET}. Edit Entry", "Select a CSV entry to rename, re-upload, edit URL, or delete."),
        (f"{C_YELLOW}6{C_RESET}. Bulk Rename Existing Items", "Rename all files listed in CSV sequentially."), # Updated description
        (f"{C_YELLOW}7{C_RESET}. Bulk Upload Existing Items", "Uploads files from Export folder listed in CSV (skips existing URLs)."), # Updated description
        (f"{C_YELLOW}8{C_RESET}. {C_RED}Nuke{C_RESET}", f"[{C_RED}DANGER{C_RESET}] Deletes the entire working folder after confirmation."),
        (f"{C_YELLOW}9{C_RESET}. Exit", "Terminates the program.")
    ]

    print(tabulate(explanation, headers=[f"{C_CYAN}Option{C_RESET}", f"{C_CYAN}Description{C_RESET}"], tablefmt="fancy_grid"))

    print("\nKey Folders:")
    print(f"- '{IMPORT_FOLDER}': Source for local import / Destination for Drive download.")
    print(f"- '{EXPORT_FOLDER}': Where renamed files are stored before/after upload.")
    print("\nKey Files:")
    print(f"- '{CONFIG_FILE}': Stores your settings.")
    print(f"- '{CSV_FILENAME}': Logs successfully processed files.")
    print(f"- '{LOG_FILENAME}': Detailed log of script activity (if enabled).")

    print("\nFor the latest version and more information, visit:")
    print(f"{C_CYAN}https://github.com/spodai/stuff/blob/main/team_banners.py{C_RESET}")

    pause("Press Enter to return to the main menu...")

# --- Start Script Function (Restored & Updated) ---
def start_script(config):
    """Main workflow: Choose source, get files, choose rename method, upload, log."""
    clear_screen()
    print_title("Start Processing Files")
    logger.info("Starting main script execution (Option 4).")
    base_dir = config.get("base_dir")
    drive_id = config.get("drive_id")
    api_key = config.get("api_key")
    uploads_enabled = str(config.get('enable_upload', 'true')).lower() == 'true'

    if not base_dir:
         print_error("Base directory is not set in configuration.")
         pause()
         return

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

    # --- Choose Import Source ---
    files_to_process = []
    print_info("Choose import source:")
    print(f"1. Google Drive (uses ID: {drive_id or C_RED+'Not Set'+C_RESET})")
    print(f"2. Local Folder ('{IMPORT_FOLDER}')")
    print(f"{C_YELLOW}0{C_RESET}. Cancel")

    while True:
        import_choice = input(f"Enter choice ({C_YELLOW}1, 2, or 0{C_RESET}): ").strip()
        if import_choice == '1':
            logger.info("User chose Google Drive import.")
            if not drive_id:
                 print_error("Google Drive ID is not set in configuration (Option 3).")
                 pause()
                 return # Cancel if no Drive ID set
            files_to_process = download_drive_folder(drive_id, import_path, csv_path)
            break
        elif import_choice == '2':
            logger.info("User chose Local Folder import.")
            clear_screen()
            print_title("Local Folder Import")
            print_info(f"Please place the image files you want to process into the")
            print(f"{C_YELLOW}{import_path}{C_RESET}")
            print_info(f"folder.")
            pause("Press Enter when you have placed the files and are ready to continue...")

            logger.info(f"Scanning local import folder: {import_path}")
            try:
                local_files = [f for f in os.listdir(import_path) if os.path.isfile(os.path.join(import_path, f))]
                logger.info(f"Found {len(local_files)} files in local import folder.")
                if not local_files:
                     print_info("No files found in the import folder.")
                     logger.info("No files found in local import folder.")
                else:
                     uploaded_originals = read_uploaded_originals(csv_path)
                     files_to_process = [f for f in local_files if f not in uploaded_originals]
                     skipped_count = len(local_files) - len(files_to_process)
                     print_info(f"Found {len(files_to_process)} new file(s) to process.")
                     logger.info(f"Identified {len(files_to_process)} new local files for processing.")
                     if skipped_count > 0:
                          print_info(f"Skipped {skipped_count} file(s) already present in the log.")
                          logger.info(f"Skipped {skipped_count} local files already present in CSV log.")
            except Exception as e:
                 print_error(f"Error reading local import folder: {e}", log_exception=True)
            break
        elif import_choice == '0':
            logger.info("User cancelled script execution.")
            print_info("Operation cancelled.")
            return
        else:
            print_error("Invalid choice.")

    # --- Proceed with processing if files were found ---
    if not files_to_process:
        logger.info("No new files identified for processing.")
        print_info("\nNo new files found to process.")
        pause()
        return

    # --- Choose Rename Method ---
    renamed_files_info = []
    print_info(f"\nFound {len(files_to_process)} file(s) to rename.")
    print("Choose renaming method:")
    print("1. Rename files individually")
    print("2. Bulk rename files sequentially (e.g., TEAM01, TEAM02...)")
    print(f"{C_YELLOW}0{C_RESET}. Cancel")

    while True:
        rename_choice = input(f"Enter choice ({C_YELLOW}1, 2, or 0{C_RESET}): ").strip()
        if rename_choice == '1':
            logger.info("User chose individual renaming.")
            renamed_files_info = prompt_rename_images(import_path, export_path, files_to_process)
            break
        elif rename_choice == '2':
            logger.info("User chose bulk renaming.")
            renamed_files_info = bulk_rename_files(import_path, export_path, files_to_process)
            break
        elif rename_choice == '0':
            logger.info("User cancelled renaming.")
            print_info("Renaming cancelled.")
            # Don't proceed if renaming is cancelled
            return
        else:
            print_error("Invalid choice.")

    # --- Proceed if renaming was successful ---
    if not renamed_files_info:
        logger.info("No files were successfully renamed or copied.")
        print_info("\nNo files were renamed.")
        pause()
        return

    # --- Upload and Log ---
    processed_for_csv = []
    if not uploads_enabled:
         print_warning("\nSkipping upload step as uploads are disabled in settings.")
         logger.warning("Skipping upload step: Uploads disabled in settings.")
         for original_name, new_name, file_path in renamed_files_info:
              processed_for_csv.append((datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f"), original_name, new_name, ""))
    elif not api_key:
         print_warning("\nSkipping upload step as API key is not configured.")
         logger.warning("Skipping upload step: API key not configured.")
         for original_name, new_name, file_path in renamed_files_info:
              processed_for_csv.append((datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f"), original_name, new_name, ""))
    else:
        # Proceed with upload
        clear_screen()
        print_title("Uploading Files")
        logger.info(f"Starting upload process for {len(renamed_files_info)} file(s).")
        upload_count = 0
        total_files = len(renamed_files_info)
        successful_uploads = 0
        failed_uploads = 0
        for original_name, new_name, file_to_upload_path in renamed_files_info:
            upload_count += 1
            print(f"\n--- Uploading file {upload_count} of {total_files} ---")
            url = None
            try:
                url = upload_to_sul(file_to_upload_path, api_key)
                if url:
                    successful_uploads += 1
                else:
                    # Warning/error printed by upload_to_sul
                    failed_uploads += 1
            except (FileNotFoundError, ValueError) as e:
                 print_error(f"Cannot upload {new_name}: {e}")
                 failed_uploads += 1
            except Exception as e:
                 print_error(f"Unexpected error uploading {new_name}: {e}", log_exception=True)
                 failed_uploads += 1
            # Add entry to CSV data regardless of upload success
            processed_for_csv.append((datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f"), original_name, new_name, str(url or "")))

        logger.info(f"Upload process finished. Successful: {successful_uploads}, Failed: {failed_uploads}.")
        if failed_uploads == 0 and successful_uploads > 0:
             print_success("All files uploaded successfully.")
        elif successful_uploads > 0:
             print_warning(f"{failed_uploads} file(s) failed to upload.")

    if processed_for_csv:
        write_to_csv(csv_path, processed_for_csv)
    else:
        logger.info("No file data prepared for CSV writing.")

    print_info("\nProcessing complete.")
    logger.info("Main script execution (Option 4) finished.")
    pause()

# --- Bulk Rename Existing Items Function (Added) ---
def run_bulk_rename_existing(config):
    """Renames all items listed in the CSV sequentially."""
    clear_screen()
    print_title("Bulk Rename Existing Items")
    logger.info("Starting Bulk Rename Existing Items process (Option 6).")

    base_dir = config.get("base_dir")
    if not base_dir:
         print_error("Base directory is not set in configuration.")
         pause()
         return

    export_path_base = os.path.join(base_dir, EXPORT_FOLDER)
    csv_path = os.path.join(base_dir, CSV_FILENAME)

    # Read existing CSV data
    header_clean, data = get_csv_data(csv_path, add_color=False)
    if header_clean is None:
        print_error("Could not read CSV file or file is invalid.")
        pause()
        return
    if not data:
        print_info("No entries found in the CSV log to rename.")
        logger.info("Bulk rename: No CSV entries found.")
        pause()
        return

    print_info(f"Found {len(data)} entries in CSV.")
    while True:
        base_name = input("Enter base name for renaming (e.g., 'IMAGE'): ").strip()
        if base_name:
            break
        else:
            print_error("Base name cannot be empty.")

    start_number = 1
    # Calculate number of digits needed for padding based on total items
    num_digits = len(str(len(data) + start_number - 1))
    print_info(f"Renaming {len(data)} items using base '{base_name}' starting from {start_number:0{num_digits}d}...")
    logger.info(f"Bulk renaming {len(data)} existing items with base '{base_name}', start {start_number}, digits {num_digits}.")

    renamed_count = 0
    skipped_count = 0
    error_count = 0
    updated_data = [] # Store updated rows separately

    # Define column indices based on standard header
    try:
        ts_idx, orig_idx, renamed_idx, url_idx = 0, 1, 2, 3
        if not (header_clean[ts_idx] == "Timestamp" and header_clean[orig_idx] == "Original" and
                header_clean[renamed_idx] == "Renamed" and header_clean[url_idx] == "URL"):
            raise ValueError("CSV header mismatch")
    except (IndexError, ValueError):
        print_error("CSV file header does not match expected format (Timestamp, Original, Renamed, URL).")
        logger.error("Bulk rename aborted: CSV header mismatch.")
        pause()
        return

    temp_export_files = {} # Track temporary renames to avoid self-collision

    # First pass: Generate new names and check for immediate target conflicts
    potential_renames = []
    target_filenames = set()
    valid_process = True
    for i, row in enumerate(data):
        try:
            old_renamed_name = row[renamed_idx]
            _, ext = os.path.splitext(old_renamed_name)
            # Ensure extension is preserved, handle cases with no extension
            ext = ext if ext else ""
            new_filename_base = f"{base_name}{i + start_number:0{num_digits}d}"
            new_filename = f"{new_filename_base}{ext}"

            if new_filename in target_filenames:
                 print_error(f"Conflict detected: Multiple items would be renamed to '{new_filename}'. Aborting.")
                 logger.error(f"Bulk rename conflict: Multiple items target '{new_filename}'. Aborting.")
                 valid_process = False
                 break
            target_filenames.add(new_filename)
            potential_renames.append({
                "index": i,
                "old_name": old_renamed_name,
                "new_name": new_filename,
                "old_path": os.path.join(export_path_base, old_renamed_name),
                "new_path": os.path.join(export_path_base, new_filename)
            })
        except IndexError:
            print_error(f"Skipping row {i+1} due to incorrect column count.")
            logger.error(f"Bulk rename skip: Row {i+1} has incorrect column count: {row}")
            skipped_count += 1

    if not valid_process:
        pause()
        return

    # Second pass: Perform renames, using temporary names if needed
    final_data = [list(row) for row in data] # Create a mutable copy for final output
    rename_log = [] # Track actual renames performed
    for rename_info in potential_renames:
        old_path = rename_info["old_path"]
        new_path = rename_info["new_path"]
        old_name = rename_info["old_name"]
        new_name = rename_info["new_name"]
        item_index = rename_info["index"]
        temp_path = None

        if not os.path.exists(old_path):
            print_warning(f"Skipping '{old_name}': File not found in '{EXPORT_FOLDER}'.")
            logger.warning(f"Bulk rename skip: File not found at '{old_path}'.")
            skipped_count += 1
            continue # Keep original row data in final_data

        if old_path == new_path:
            print_info(f"Skipping '{old_name}': Name is already correct.")
            logger.info(f"Bulk rename skip: '{old_name}' already has the target name.")
            continue # Keep original row data

        # Check if the target *new* path exists AND is not the same as the *current* old path
        if os.path.exists(new_path):
            # Use a temporary name to avoid collision during the process
            temp_suffix = f"__bulk_rename_temp_{datetime.now().strftime('%f')}"
            temp_path = old_path + temp_suffix
            try:
                os.rename(old_path, temp_path)
                logger.info(f"Renamed '{old_name}' to temporary '{os.path.basename(temp_path)}' to avoid collision.")
                temp_export_files[new_path] = temp_path # Record that the target file is now at temp_path
                # Mark this rename as pending finalization from temp
                rename_info["status"] = "pending_temp"
            except OSError as e:
                print_error(f"Failed to rename '{old_name}' to temporary path: {e}", log_exception=True)
                error_count += 1
                rename_info["status"] = "error"
                continue # Keep original row data on error
        else:
            # Directly rename if no conflict
            try:
                os.rename(old_path, new_path)
                rename_log.append(f"'{old_name}' -> '{new_name}'")
                logger.info(f"Bulk rename: Renamed '{old_name}' to '{new_name}'.")
                renamed_count += 1
                rename_info["status"] = "renamed"
            except OSError as e:
                print_error(f"Failed to rename '{old_name}' to '{new_name}': {e}", log_exception=True)
                error_count += 1
                rename_info["status"] = "error"
                continue # Keep original row data on error

        # Update the row data in the final list
        final_data[item_index][renamed_idx] = new_name # Set new name
        final_data[item_index][ts_idx] = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f") # Update timestamp

    # Third pass: Rename temporary files to their final names
    temp_rename_errors = 0
    for final_target_path, temp_source_path in temp_export_files.items():
        try:
            os.rename(temp_source_path, final_target_path)
            temp_base = os.path.basename(temp_source_path)
            final_base = os.path.basename(final_target_path)
            rename_log.append(f"'{temp_base}' (temp) -> '{final_base}'")
            logger.info(f"Bulk rename: Renamed temporary '{temp_base}' to final '{final_base}'.")
            # Find the corresponding entry in potential_renames to mark as fully renamed
            for info in potential_renames:
                if info.get("status") == "pending_temp" and info["new_path"] == final_target_path:
                    info["status"] = "renamed"
                    renamed_count += 1
                    break
        except OSError as e:
            print_error(f"Failed to rename temporary file '{temp_source_path}' to '{final_target_path}': {e}", log_exception=True)
            temp_rename_errors += 1
            error_count += 1 # Increment overall error count
            # Mark the corresponding entry as error
            for info in potential_renames:
                if info.get("status") == "pending_temp" and info["new_path"] == final_target_path:
                    info["status"] = "error_temp_rename"
                    # Revert the name change in final_data for this entry
                    final_data[info["index"]][renamed_idx] = info["old_name"]
                    break


    # Save the final data back to CSV
    if renamed_count > 0 or skipped_count > 0 or error_count > 0: # Save if anything changed or errors occurred
        print_info("\nSaving updated names to CSV...")
        try:
            with open(csv_path, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.writer(csvfile)
                writer.writerow(header_clean)
                writer.writerows(final_data) # Write the potentially modified data
            print_success("CSV log updated successfully.")
            logger.info(f"CSV log saved after bulk rename. Renamed: {renamed_count}, Skipped: {skipped_count}, Errors: {error_count}.")
        except (IOError, csv.Error) as e:
            print_error(f"Failed to save updated CSV after bulk rename: {e}", log_exception=True)
    else:
        print_info("\nNo changes made to CSV.")
        logger.info("No changes made during bulk rename.")

    print_title("Bulk Rename Summary")
    print_info(f"Total CSV Entries Processed: {len(data)}")
    print_success(f"Files Successfully Renamed: {renamed_count}")
    if skipped_count > 0:
        print_warning(f"Files Skipped (Not Found/No Change): {skipped_count}")
    if error_count > 0:
        print_error(f"Errors During Rename: {error_count}")
    if temp_rename_errors > 0:
         print_error(f"Errors renaming temporary files: {temp_rename_errors}")


    logger.info(f"Bulk Rename Existing summary: Total={len(data)}, Renamed={renamed_count}, Skipped={skipped_count}, Errors={error_count}")
    pause()


# --- Main Menu ---

def menu():
    """Displays the main menu and handles user choices."""
    init_config()
    config = load_config() # Load config once
    logger.info("="*30 + " Script Execution Started " + "="*30)

    while True:
        clear_screen()
        # No need to reload config here anymore unless explicitly changed
        base_dir = config.get("base_dir", "Not Set")
        csv_path = os.path.join(base_dir, CSV_FILENAME) if base_dir != "Not Set" else None
        logger.debug("Displaying main menu.")

        print_title("Main Menu")
        print(f"Base Directory: {C_YELLOW}{base_dir}{C_RESET}")
        print("-" * (len("Base Directory: ") + len(str(base_dir))))

        # Corrected numbering
        print(f"{C_YELLOW}0{C_RESET}. How this program works")
        print(f"{C_YELLOW}1{C_RESET}. Show CSV data")
        print(f"{C_YELLOW}2{C_RESET}. Show folder structure")
        print(f"{C_YELLOW}3{C_RESET}. Change settings")
        print(f"{C_YELLOW}4{C_RESET}. Start script (Import > Rename > Upload)")
        print(f"{C_YELLOW}5{C_RESET}. Edit Entry")
        print(f"{C_YELLOW}6{C_RESET}. Bulk Rename Existing Items") # New option
        print(f"{C_YELLOW}7{C_RESET}. Bulk Upload Existing Items") # Re-numbered
        print(f"{C_YELLOW}8{C_RESET}. {C_RED}Nuke working directory{C_RESET}") # Re-numbered
        print(f"{C_YELLOW}9{C_RESET}. Exit") # Re-numbered

        choice = input(f"\nEnter your choice ({C_YELLOW}0-9{C_RESET}): ").strip() # Corrected prompt range
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
            show_folder_structure(config) # Pass config
        elif choice == "3":
            update_settings(config) # Pass config, updates it in-place
            # No need to reload here, changes are reflected in the passed dict
        elif choice == "4":
            start_script(config) # Pass config
        elif choice == "5":
             if csv_path and base_dir != "Not Set":
                edit_entry(csv_path, base_dir, config) # Pass config
             else:
                print_error("Base directory not set or CSV path invalid, cannot edit entries.")
                pause()
        elif choice == "6": # New Bulk Rename action
             if csv_path and base_dir != "Not Set":
                 run_bulk_rename_existing(config) # Pass config
             else:
                 print_error("Base directory not set or CSV path invalid, cannot bulk rename.")
                 pause()
        elif choice == "7": # Corrected Bulk Upload action
             if csv_path and base_dir != "Not Set":
                 bulk_upload_from_csv(config) # Pass config
             else:
                 print_error("Base directory not set or CSV path invalid, cannot bulk upload.")
                 pause()
        elif choice == "8": # Corrected Nuke action
            if base_dir != "Not Set":
                 nuke_everything(base_dir) # Doesn't strictly need config, just base_dir
            else:
                 print_error("Base directory not set, cannot nuke.")
                 pause()
        elif choice == "9": # Corrected Exit action
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
        except Exception: pass
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
            for handler in logger.handlers[:]:
                try:
                    handler.close()
                    logger.removeHandler(handler)
                except Exception as e:
                    print(f"{C_YELLOW}Warning: Error closing log handler during shutdown: {e}{C_RESET}")
        except Exception: pass
        if colorama:
            try:
                colorama.deinit()
            except Exception: pass


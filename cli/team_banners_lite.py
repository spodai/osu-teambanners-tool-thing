#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Lite CLI tool: Fetches from Google Drive, renames, uploads (optional), logs to CSV.

## Install required libraries:
# pip install requests gdown configparser

import os
import shutil
import requests
import gdown
import csv
import configparser
from datetime import datetime
import sys
import logging
import traceback
import re # For stripping potential ANSI codes in logs

# --- Globals & Constants ---
CONFIG_FILE = "settings.conf"
IMPORT_FOLDER = "Images import"
EXPORT_FOLDER = "Images export"
CSV_FILENAME = "index.csv"
LOG_FILENAME = "script_activity.log"

# --- Setup Logging ---
logger = logging.getLogger(__name__)
if not logger.handlers:
    logger.addHandler(logging.NullHandler()) # Add NullHandler initially
logger.setLevel(logging.INFO)

def setup_file_logging(base_dir):
    """Configures file logging."""
    log_file_path = os.path.join(base_dir, LOG_FILENAME)
    # Remove existing file handler if present to avoid duplicates
    for handler in logger.handlers[:]:
        if isinstance(handler, logging.FileHandler):
            logger.removeHandler(handler)
            handler.close()
            break

    # Add the file handler
    fh = logging.FileHandler(log_file_path, encoding='utf-8')
    fh.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
    fh.setFormatter(formatter)
    logger.addHandler(fh)
    logger.info(f"File logging enabled. Log file: {log_file_path}")

def strip_ansi_codes(text):
    """Removes ANSI escape codes from a string."""
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    return ansi_escape.sub('', text)

# --- Simplified Print/Log Helpers ---
def log_print(level, message, log_exception=False):
    """Prints message to console and logs it."""
    print(message) # Print directly without color codes
    clean_message = strip_ansi_codes(message) # Ensure clean message for log
    if level == logging.INFO:
        logger.info(clean_message)
    elif level == logging.WARNING:
        logger.warning(clean_message)
    elif level == logging.ERROR:
        logger.error(clean_message)
        if log_exception:
            logger.exception(f"Exception related to error: {clean_message}")
    elif level == logging.CRITICAL:
         logger.critical(clean_message, exc_info=log_exception)


# --- Configuration ---
def init_config():
    """Initializes the configuration file if it doesn't exist."""
    if not os.path.exists(CONFIG_FILE):
        print("[INFO] Config file not found. Let's set it up.")
        drive_id = input("Enter Google Drive folder ID or URL: ").strip()
        api_key = input("Enter s-ul.eu API key (leave blank to disable uploads): ").strip()
        base_dir = os.path.dirname(os.path.abspath(__file__))

        # Setup logging *before* writing config
        setup_file_logging(base_dir)
        logger.info("Attempting to initialize configuration file.")

        config = configparser.ConfigParser()
        config['DEFAULT'] = {
            'drive_id': drive_id,
            'api_key': api_key,
            'base_dir': base_dir
        }

        try:
            with open(CONFIG_FILE, 'w', encoding='utf-8') as configfile:
                config.write(configfile)
            log_print(logging.INFO, "[OK] Config saved.")
            logger.info(f"Config file '{CONFIG_FILE}' created and saved successfully.")
            os.makedirs(os.path.join(base_dir, IMPORT_FOLDER), exist_ok=True)
            os.makedirs(os.path.join(base_dir, EXPORT_FOLDER), exist_ok=True)
            log_print(logging.INFO, f"[OK] Created folders: '{IMPORT_FOLDER}' and '{EXPORT_FOLDER}'.")
            logger.info(f"Ensured directories exist: '{IMPORT_FOLDER}', '{EXPORT_FOLDER}'.")
        except IOError as e:
            log_print(logging.CRITICAL, f"[CRITICAL] Could not write config file: {e}", log_exception=True)
            sys.exit(1)
        except Exception as e:
            log_print(logging.CRITICAL, f"[CRITICAL] An error occurred during initial setup: {e}", log_exception=True)
            sys.exit(1)

def load_config():
    """Loads configuration from the file."""
    if not os.path.exists(CONFIG_FILE):
        print("[ERROR] Configuration file not found. Run script again to initialize.")
        sys.exit(1)

    config = configparser.ConfigParser()
    base_dir_from_config = None
    try:
        config.read(CONFIG_FILE, encoding='utf-8')
        if 'DEFAULT' not in config:
            raise configparser.Error("Missing [DEFAULT] section in config.")

        required_keys = ['drive_id', 'api_key', 'base_dir']
        for key in required_keys:
            if key not in config['DEFAULT']:
                 # Allow drive_id and api_key to be missing/blank, but base_dir is essential
                 if key == 'base_dir':
                      raise configparser.Error(f"Missing essential key '{key}' in config.")
                 else:
                      config['DEFAULT'][key] = '' # Ensure key exists even if blank

        base_dir_from_config = config['DEFAULT']['base_dir']
        if not base_dir_from_config or not os.path.isdir(base_dir_from_config):
             raise configparser.Error(f"Invalid or missing base_dir in config: {base_dir_from_config}")

        # Setup logging using the loaded base_dir
        setup_file_logging(base_dir_from_config)
        logger.info("Configuration loaded successfully.")
        return dict(config['DEFAULT'])

    except (configparser.Error, IOError) as e:
        print(f"[ERROR] Failed to load or parse configuration file: {e}")
        # Attempt to log critical failure
        try:
            if base_dir_from_config: setup_file_logging(base_dir_from_config)
            logger.critical(f"CRITICAL: Failed to load configuration: {e}", exc_info=True)
        except Exception as log_e: print(f"Additionally, failed to log critical error: {log_e}")
        sys.exit(1)
    except Exception as e:
        print(f"[ERROR] An unexpected error occurred loading configuration: {e}")
        try: logger.critical(f"CRITICAL: Unexpected error loading config: {e}", exc_info=True)
        except Exception as log_e: print(f"Additionally, failed to log critical error: {log_e}")
        sys.exit(1)

# --- Core Functionality ---

def read_uploaded_originals(csv_path):
    """Reads original filenames (column 2) from the CSV log."""
    originals = set()
    if not os.path.exists(csv_path):
        logger.info(f"CSV file '{csv_path}' not found. Assuming no previously logged files.")
        return originals

    logger.info(f"Reading previously logged original filenames from '{csv_path}'.")
    try:
        with open(csv_path, 'r', newline='', encoding="utf-8") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            original_col_index = 1
            if not header or len(header) <= original_col_index:
                 logger.warning(f"CSV file '{csv_path}' header invalid or missing 'Original' column.")
                 return originals

            for i, row in enumerate(reader):
                if len(row) > original_col_index: originals.add(row[original_col_index])
                else: logger.warning(f"Skipping malformed row {i+1} in CSV '{csv_path}': {row}")
            logger.info(f"Found {len(originals)} unique original filenames in CSV.")
    except (IOError, csv.Error) as e:
        log_print(logging.ERROR, f"[ERROR] Could not read CSV file '{csv_path}': {e}", log_exception=True)
    except StopIteration: logger.info(f"CSV file '{csv_path}' contains only a header.")
    return originals

def download_drive_folder(drive_id, download_path, csv_path):
    """Downloads files from Google Drive folder using gdown and filters against CSV."""
    print("\n=== Download from Google Drive ===")
    logger.info("Starting Google Drive download process.")

    if not drive_id:
        log_print(logging.ERROR, "[ERROR] Google Drive ID/URL is not set in configuration.")
        return []

    url = f"https://drive.google.com/drive/folders/{drive_id}" if "drive.google.com" not in drive_id else drive_id
    print(f"[INFO] Attempting download from: {url}")
    print(f"[INFO] Downloading to: {download_path}")
    logger.info(f"Drive URL/ID: {drive_id}")
    logger.info(f"Download path: {download_path}")

    os.makedirs(download_path, exist_ok=True)
    uploaded_originals = read_uploaded_originals(csv_path)
    files_before_download = {f for f in os.listdir(download_path) if os.path.isfile(os.path.join(download_path, f))}
    files_to_process = []

    try:
        print("[INFO] Starting gdown download/sync (this might take a while)...")
        logger.info(f"Calling gdown.download_folder for URL: {url}")
        gdown.download_folder(url, output=download_path, quiet=False, use_cookies=False, remaining_ok=True)
        logger.info("gdown.download_folder process finished.")
        print("[INFO] gdown download/sync process finished.")

        files_after_download = {f for f in os.listdir(download_path) if os.path.isfile(os.path.join(download_path, f))}
        logger.info(f"Found {len(files_after_download)} files in import directory after download.")
        skipped_logged_count = 0

        print("[INFO] Filtering downloaded files...")
        logger.info("Filtering downloaded files against CSV log...")
        for file in sorted(list(files_after_download)):
            if file not in uploaded_originals:
                files_to_process.append(file)
                logger.info(f"Identified file for processing: {file}")
            else:
                logger.info(f"Skipping file (already logged in CSV): {file}")
                skipped_logged_count += 1

        log_print(logging.INFO, "[OK] Download and filtering complete.")
        if files_to_process:
            log_print(logging.INFO, f"[INFO] Identified {len(files_to_process)} file(s) needing processing.")
        else:
            log_print(logging.INFO, "[INFO] No new files found requiring processing.")
        if skipped_logged_count > 0:
            log_print(logging.INFO, f"[INFO] Skipped {skipped_logged_count} file(s) already present in the log.")
        return files_to_process

    except Exception as e:
        log_print(logging.ERROR, f"[ERROR] An error occurred during download/filtering: {e}", log_exception=True)
        print("[INFO] Check the Google Drive ID/URL, folder permissions, and network connection.")
        return []


def prompt_rename_images(import_path, export_path, files_to_process):
    """Prompts user to rename downloaded files individually and copies them."""
    if not files_to_process:
        logger.info("prompt_rename_images called with no files to process.")
        return []

    print("\n=== Rename New Files ===")
    logger.info(f"Starting rename process for {len(files_to_process)} file(s).")
    os.makedirs(export_path, exist_ok=True)
    renamed_list = []
    skipped_count = 0
    renamed_count = 0

    print(f"[INFO] Found {len(files_to_process)} file(s) to rename.")
    print("[INFO] Enter a new name without the extension.")
    print("[INFO] Leave blank and press Enter to keep the original filename.")

    for original_filename in sorted(files_to_process):
        src_path = os.path.join(import_path, original_filename)
        if not os.path.isfile(src_path):
            log_print(logging.WARNING, f"[WARN] Source file not found, skipping: {original_filename}")
            skipped_count += 1
            continue

        print(f"\nOriginal filename: {original_filename}")
        new_name_base = input("Enter new name (no extension, blank to keep original): ").strip()

        _, ext = os.path.splitext(original_filename)
        new_filename = f"{new_name_base}{ext}" if new_name_base else original_filename
        dest_path = os.path.join(export_path, new_filename)
        logger.info(f"Processing rename for '{original_filename}' -> '{new_filename}'.")

        counter = 1
        while os.path.exists(dest_path) and dest_path != src_path:
            log_print(logging.WARNING, f"[WARN] File '{new_filename}' already exists in export folder.")
            overwrite_choice = input(f"Overwrite? (y/n, default n): ").strip().lower()
            if overwrite_choice == 'y':
                print("[INFO] Overwriting existing file.")
                logger.info(f"User chose to overwrite existing file '{new_filename}'.")
                break
            else:
                 base = new_name_base if new_name_base else os.path.splitext(original_filename)[0]
                 new_filename = f"{base}_{counter}{ext}"
                 dest_path = os.path.join(export_path, new_filename)
                 print(f"[INFO] Trying new name: {new_filename}")
                 logger.info(f"Rename conflict: Trying new name '{new_filename}'.")
                 counter += 1
                 if counter > 10:
                      log_print(logging.ERROR, "[ERROR] Too many filename conflicts, skipping this file.")
                      new_filename = None
                      break

        if new_filename is None:
             skipped_count += 1
             continue

        try:
            shutil.copy2(src_path, dest_path)
            log_print(logging.INFO, f"[OK] Copied and renamed to: {new_filename}")
            renamed_list.append((original_filename, new_filename, dest_path))
            renamed_count += 1
        except IOError as e:
            log_print(logging.ERROR, f"[ERROR] Could not copy file '{original_filename}' to '{dest_path}': {e}", log_exception=True)
            skipped_count += 1
        except Exception as e:
            log_print(logging.ERROR, f"[ERROR] An unexpected error occurred during copy: {e}", log_exception=True)
            skipped_count += 1

    log_print(logging.INFO, f"[OK] Rename process finished. Renamed: {renamed_count}, Skipped: {skipped_count}.")
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

    print(f"[INFO] Uploading '{filename}' to s-ul.eu...")
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
                log_print(logging.INFO, f"[OK] Upload successful: {url}")
                return url
            else:
                error_msg = response_json.get("error", "Unknown error from API (URL missing in 200 OK response)")
                logger.error(f"API Error for '{filename}': {error_msg}")
                raise requests.exceptions.RequestException(f"API Error: {error_msg}")

    except requests.exceptions.Timeout:
        log_print(logging.ERROR, f"[ERROR] Upload timed out for '{filename}'.")
        return None
    except requests.exceptions.ConnectionError as e:
         log_print(logging.ERROR, f"[ERROR] Connection error during upload for '{filename}': {e}", log_exception=True)
         return None
    except requests.exceptions.RequestException as e:
        log_print(logging.ERROR, f"[ERROR] Upload failed for '{filename}': {e}")
        try:
            error_detail = res.json().get('error', f'(status code: {res.status_code})')
            logger.error(f"API Response Detail for failed upload '{filename}': {error_detail}")
        except:
            logger.error(f"Could not get error details from API response for '{filename}'. Status: {res.status_code}, Text: {res.text[:200]}...")
        return None
    except IOError as e:
        log_print(logging.ERROR, f"[ERROR] Could not read file for upload '{filename}': {e}", log_exception=True)
        return None
    except Exception as e:
        log_print(logging.ERROR, f"[ERROR] An unexpected error occurred during upload of '{filename}': {e}", log_exception=True)
        return None


def write_to_csv(csv_path, processed_data):
    """Appends processed file information to the CSV log."""
    if not processed_data:
        logger.info("No processed files to write to CSV.")
        return

    logger.info(f"Attempting to write {len(processed_data)} new entries to CSV: '{csv_path}'.")
    header = ["Timestamp", "Original", "Renamed", "URL"]
    write_header = not os.path.exists(csv_path) or os.path.getsize(csv_path) == 0
    try:
        with open(csv_path, "a", newline='', encoding="utf-8") as f:
            writer = csv.writer(f)
            if write_header:
                writer.writerow(header)
                logger.info("Writing header to new CSV file.")
            written_count = 0
            for timestamp, original, renamed, url in processed_data:
                writer.writerow([timestamp, original, renamed, str(url)])
                written_count += 1
        log_print(logging.INFO, f"[OK] Successfully added {written_count} entries to '{os.path.basename(csv_path)}'.")
    except (IOError, csv.Error) as e:
        log_print(logging.ERROR, f"[ERROR] Could not write to CSV file '{csv_path}': {e}", log_exception=True)


# --- Main Execution Block ---
if __name__ == "__main__":
    try:
        init_config() # Ensure config exists or is created
        config = load_config() # Load config and setup logging/colors

        logger.info("="*30 + " Script Execution Started " + "="*30)

        base_dir = config.get("base_dir")
        drive_id = config.get("drive_id")
        api_key = config.get("api_key")
        # Determine if uploads should happen (API key exists?)
        uploads_enabled = bool(api_key) # Simplified: upload if key exists

        if not base_dir:
             log_print(logging.CRITICAL, "[CRITICAL] Base directory not set in configuration. Exiting.")
             sys.exit(1)

        import_path = os.path.join(base_dir, IMPORT_FOLDER)
        export_path = os.path.join(base_dir, EXPORT_FOLDER)
        csv_path = os.path.join(base_dir, CSV_FILENAME)

        # Ensure directories exist
        try:
            os.makedirs(import_path, exist_ok=True)
            os.makedirs(export_path, exist_ok=True)
            logger.debug(f"Ensured import/export directories exist: '{import_path}', '{export_path}'")
        except OSError as e:
            log_print(logging.CRITICAL, f"[CRITICAL] Could not create required directories: {e}", log_exception=True)
            sys.exit(1)

        # 1. Download/Filter Files
        files_to_process = download_drive_folder(drive_id, import_path, csv_path)

        if not files_to_process:
            log_print(logging.INFO, "[INFO] No new files identified for processing.")
        else:
            # 2. Rename Files
            renamed_files_info = prompt_rename_images(import_path, export_path, files_to_process)

            if renamed_files_info:
                # 3. Upload and Log
                processed_for_csv = []
                if not uploads_enabled:
                     log_print(logging.WARNING, "\n[WARN] Skipping upload step as API key is not configured.")
                     for original_name, new_name, file_path in renamed_files_info:
                          processed_for_csv.append((datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f"), original_name, new_name, ""))
                else:
                    print("\n=== Uploading Files ===")
                    logger.info(f"Starting upload process for {len(renamed_files_info)} file(s).")
                    upload_count = 0
                    successful_uploads = 0
                    failed_uploads = 0
                    for original_name, new_name, file_to_upload_path in renamed_files_info:
                        upload_count += 1
                        print(f"\n--- Uploading file {upload_count} of {len(renamed_files_info)} ---")
                        url = None
                        try:
                            url = upload_to_sul(file_to_upload_path, api_key)
                            if url: successful_uploads += 1
                            else: failed_uploads += 1
                        except (FileNotFoundError, ValueError) as e:
                             log_print(logging.ERROR, f"[ERROR] Cannot upload {new_name}: {e}")
                             failed_uploads += 1
                        except Exception as e:
                             log_print(logging.ERROR, f"[ERROR] Unexpected error uploading {new_name}: {e}", log_exception=True)
                             failed_uploads += 1
                        processed_for_csv.append((datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f"), original_name, new_name, str(url or "")))

                    logger.info(f"Upload process finished. Successful: {successful_uploads}, Failed: {failed_uploads}.")
                    if failed_uploads == 0 and successful_uploads > 0: log_print(logging.INFO, "[OK] All files uploaded successfully.")
                    elif successful_uploads > 0: log_print(logging.WARNING, f"[WARN] {failed_uploads} file(s) failed to upload.")

                # 4. Write to CSV
                if processed_for_csv:
                    write_to_csv(csv_path, processed_for_csv)
                else:
                    logger.info("No file data prepared for CSV writing.")
            else:
                 log_print(logging.INFO, "[INFO] No files were successfully renamed.")

        log_print(logging.INFO, "\nProcessing complete.")

    except KeyboardInterrupt:
        print("\n[INFO] Operation cancelled by user. Exiting.")
        logger.warning("Operation cancelled by user (KeyboardInterrupt).")
    except Exception as e:
        log_print(logging.CRITICAL, f"\n[CRITICAL] An unexpected critical error occurred: {e}", log_exception=True)
        traceback.print_exc() # Also print traceback to console for critical errors
        print(f"[INFO] Check '{LOG_FILENAME}' for details.")
    finally:
        logger.info("="*30 + " Script Execution Finished " + "="*30 + "\n")
        # Ensure all handlers are closed on exit
        for handler in logger.handlers[:]:
            try:
                if isinstance(handler, logging.FileHandler):
                    handler.close()
                    logger.removeHandler(handler)
            except Exception as e:
                print(f"[WARN] Warning: Error closing log handler during shutdown: {e}")


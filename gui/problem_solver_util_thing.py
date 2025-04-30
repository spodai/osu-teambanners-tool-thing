#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Problem Fixer Script for the Google Drive to S-UL Uploader using Tkinter (Empty Rename Fix)

## Install required libraries:
# pip install requests gdown configparser colorama

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
import re
import threading # To prevent GUI freezing during long tasks
import queue # For communication between threads
import time # For small delays
import subprocess # For opening log file cross-platform
from pathlib import Path # For easier path handling

# --- GUI Imports ---
import tkinter as tk
from tkinter import ttk # Themed widgets
from tkinter import messagebox
from tkinter import filedialog # Although not strictly needed here, keep for consistency

# --- Globals & Constants ---
CONFIG_FILE = "settings.conf"
IMPORT_FOLDER = "Images import"
EXPORT_FOLDER = "Images export"
CSV_FILENAME = "index.csv"
LOG_FILENAME = "problem_fixer.log" # Separate log file for this tool

# --- ANSI Color Code Definitions (Used only for stripping in logs) ---
_COLOR_CODE_RESET = "\033[0m"
_COLOR_CODE_RED = "\033[91m"
_COLOR_CODE_GREEN = "\033[92m"
_COLOR_CODE_YELLOW = "\033[93m"
_COLOR_CODE_BLUE = "\033[94m"
_COLOR_CODE_CYAN = "\033[96m"
_COLOR_CODE_MAGENTA = "\033[95m"

# --- Setup Logging ---
logger = logging.getLogger(__name__)
if not logger.handlers:
    logger.addHandler(logging.NullHandler())
logger.setLevel(logging.INFO)

# --- Global variable to hold configuration ---
app_config = {}
# Determine base path more robustly
if getattr(sys, 'frozen', False):
    base_dir_path = os.path.dirname(sys.executable)
else:
    base_dir_path = os.path.dirname(os.path.abspath(__file__))

# --- Utility Functions ---

def strip_ansi_codes(text):
    """Removes ANSI escape codes from a string."""
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    return ansi_escape.sub('', str(text))

def setup_file_logging(base_dir, enable_logging):
    """Configures or removes file logging based on the enable_logging flag."""
    global logger
    try:
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
            is_new_handler = len(logger.handlers) <= 2
            if is_new_handler:
                 logger.info(f"File logging enabled. Log file: {log_file_path}")
        else:
            if file_handler:
                logger.info("File logging disabled and handler removed.")
    except Exception as e:
        print(f"ERROR setting up logging: {e}")

# --- GUI Status Update Function ---
status_queue = queue.Queue()

def update_status_display(text_widget):
    """Checks the queue and updates the status text widget."""
    try:
        while True:
            level, message = status_queue.get_nowait()
            clean_message = strip_ansi_codes(message)
            # Define tags for colors (standard theme colors)
            text_widget.tag_config("INFO", foreground="blue")
            text_widget.tag_config("SUCCESS", foreground="green")
            text_widget.tag_config("WARNING", foreground="orange")
            text_widget.tag_config("ERROR", foreground="red", font=('TkDefaultFont', 9, 'bold'))
            text_widget.tag_config("CRITICAL", foreground="red", background="yellow", font=('TkDefaultFont', 9, 'bold'))
            text_widget.tag_config("PRINT", foreground="black")

            tag = "PRINT"
            log_level_int = logging.INFO
            if isinstance(level, int):
                log_level_int = level
                if level == logging.INFO: tag = "INFO"
                elif level == logging.WARNING: tag = "WARNING"
                elif level == logging.ERROR: tag = "ERROR"
                elif level == logging.CRITICAL: tag = "CRITICAL"
                elif level == logging.DEBUG: tag = "PRINT"
            elif isinstance(level, str):
                if level == "SUCCESS":
                     tag = "SUCCESS"; log_level_int = logging.INFO
                     logger.info(f"OK: {clean_message}")
                elif level == "PRINT":
                     tag = "PRINT"; log_level_int = logging.DEBUG
                     logger.debug(clean_message)
                else: tag = "PRINT"; logger.info(clean_message)

            if isinstance(level, int): logger.log(log_level_int, clean_message)

            text_widget.config(state=tk.NORMAL)
            text_widget.insert(tk.END, f"{message}\n", tag)
            text_widget.config(state=tk.DISABLED)
            text_widget.see(tk.END)
            text_widget.update_idletasks()

    except queue.Empty: pass
    text_widget.after(100, lambda: update_status_display(text_widget))

def log_status(level, message):
    """Puts a message into the queue for the GUI status display."""
    status_queue.put((level, message))

# --- Configuration Handling (Read-Only) ---

def load_config_readonly():
    """Loads config but does not modify it or create if missing."""
    global app_config, base_dir_path
    config_parser = configparser.ConfigParser()
    # Ensure base_dir_path is set before using it
    if not base_dir_path or not os.path.isdir(base_dir_path):
         base_dir_path = os.path.dirname(os.path.abspath(__file__))

    defaults = {
        'drive_id': '', 'api_key': '', 'base_dir': base_dir_path,
        'enable_colors': 'true', 'enable_logging': 'true', 'enable_upload': 'true'
    }
    config_file_path = os.path.join(base_dir_path, CONFIG_FILE)

    if os.path.exists(config_file_path):
        try:
            config_parser.read(config_file_path, encoding='utf-8')
            if 'DEFAULT' in config_parser:
                for key in defaults: defaults[key] = config_parser['DEFAULT'].get(key, defaults[key])
            else: print(f"WARNING: Config file '{config_file_path}' found but missing [DEFAULT]. Using defaults.")
        except Exception as e: print(f"ERROR: Error reading config file '{config_file_path}': {e}. Using defaults.")
    else:
        print(f"ERROR: Config file '{config_file_path}' not found. Cannot load settings.")
        # Return defaults but log error
        log_status(logging.ERROR, f"Config file '{config_file_path}' not found.")
        app_config = defaults
        return app_config # Return defaults so app doesn't crash immediately

    # Validate base_dir again after loading
    loaded_base_dir = defaults['base_dir']
    if not os.path.isdir(loaded_base_dir):
        print(f"WARNING: Base directory '{loaded_base_dir}' from config is invalid. Resetting to script directory.")
        loaded_base_dir = os.path.dirname(os.path.abspath(__file__))
        defaults['base_dir'] = loaded_base_dir
    base_dir_path = loaded_base_dir

    # Setup logging based on loaded/default value (use separate log file)
    setup_file_logging(base_dir_path, defaults['enable_logging'])
    logger.info("Configuration loaded (read-only).")
    app_config = defaults
    return app_config

# --- Core Logic Functions ---

def upload_to_sul(file_path, api_key):
    """Uploads a file to s-ul.eu and returns the URL (synchronous version for direct calls)."""
    filename = os.path.basename(file_path)
    if not api_key:
        logger.error(f"Upload skipped for '{filename}': API key is missing.")
        raise ValueError("S-UL API key is missing.")
    if not os.path.exists(file_path):
         logger.error(f"Upload skipped for '{filename}': File not found at '{file_path}'.")
         raise FileNotFoundError(f"File to upload not found: {file_path}")

    log_status(logging.INFO, f"Uploading '{filename}' to s-ul.eu...")
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
                url_result = response_json["url"]
                log_status("SUCCESS", f"Upload successful for '{filename}': {url_result}")
                logger.info(f"Upload successful for '{filename}'. URL: {url_result}")
                return url_result
            else:
                error_msg = response_json.get("error", "Unknown error from API (URL missing in 200 OK response)")
                logger.error(f"API Error for '{filename}': {error_msg}")
                raise requests.exceptions.RequestException(f"API Error: {error_msg}")

    except requests.exceptions.Timeout:
        log_status(logging.ERROR, f"Upload timed out for '{filename}'.")
        return None
    except requests.exceptions.ConnectionError as e:
         log_status(logging.ERROR, f"Connection error during upload for '{filename}': {e}")
         logger.exception("Connection error during upload")
         return None
    except requests.exceptions.RequestException as e:
        log_status(logging.ERROR, f"Upload failed for '{filename}': {e}")
        try:
            error_detail = res.json().get('error', f'(status code: {res.status_code})')
            logger.error(f"API Response Detail for failed upload '{filename}': {error_detail}")
        except:
            logger.error(f"Could not get error details from API response for '{filename}'. Status: {res.status_code}, Text: {res.text[:200]}...")
        return None
    except IOError as e:
        log_status(logging.ERROR, f"Could not read file for upload '{filename}': {e}")
        logger.exception("IOError during upload")
        return None
    except Exception as e:
        log_status(logging.ERROR, f"An unexpected error occurred during upload of '{filename}': {e}")
        logger.exception("Unexpected error during upload")
        return None

def upload_to_sul_thread(file_path, api_key, result_queue):
    """Worker function for uploading a single file in a thread."""
    filename = os.path.basename(file_path)
    url = None
    error = None
    try:
        url = upload_to_sul(file_path, api_key) # Call the original synchronous function
    except Exception as e:
        error = f"Failed to upload {filename}: {e}"
        logger.exception(f"Upload error for {filename}")
    result_queue.put({"file": filename, "url": url, "error": error})

def get_csv_data(csv_path):
    """Reads all data from the CSV file. Validates row length."""
    if not os.path.exists(csv_path):
        return None, []

    logger.debug(f"Reading CSV data from '{csv_path}'.")
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
                 log_status(logging.WARNING, f"Skipped {malformed_count} malformed row(s) in CSV. Check log file for details.")

            logger.debug(f"Read {len(validated_data)} valid data rows from CSV.")
            return header, validated_data # Return plain header and data

    except (IOError, csv.Error) as e:
        log_status(logging.ERROR, f"Could not read or parse CSV file '{csv_path}': {e}")
        logger.exception("CSV Read/Parse Error")
        return None, []
    except StopIteration:
        logger.info(f"CSV file '{csv_path}' contains only a header.")
        return header, []


# --- Problem Fixer GUI Application Class ---

class ProblemFixerApp:
    instance = None # Class variable to hold the single instance

    def __init__(self, root):
        if ProblemFixerApp.instance is not None:
             raise Exception("Only one instance of ProblemFixerApp can exist!")
        ProblemFixerApp.instance = self

        self.root = root
        self.root.title("Uploader Problem Fixer")
        self.root.geometry("700x600") # Adjusted size

        # --- Apply Default Theme ---
        self.style = ttk.Style(self.root)
        # Use the default theme (removed dark theme loading)

        # Load configuration (read-only)
        global app_config
        app_config = load_config_readonly()

        # --- Build GUI ---
        self.create_widgets()

        # Start the status display updater
        self.status_text.after(100, lambda: update_status_display(self.status_text))
        log_status(logging.INFO, "Problem Fixer initialized.")
        self.scan_for_problems() # Initial scan on startup

    def create_widgets(self):
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(0, weight=1) # Problem text area expands
        main_frame.rowconfigure(1, weight=0) # Buttons fixed height
        main_frame.rowconfigure(2, weight=1) # Status area expands

        # --- Problem Display Frame ---
        problem_display_frame = ttk.LabelFrame(main_frame, text="Detected Problems", padding="10")
        problem_display_frame.grid(row=0, column=0, sticky="nsew", pady=(0, 10))
        problem_display_frame.rowconfigure(0, weight=1)
        problem_display_frame.columnconfigure(0, weight=1)

        self.problem_text = tk.Text(problem_display_frame, height=15, width=80, state=tk.DISABLED, wrap=tk.WORD, borderwidth=1, relief="sunken", foreground="red") # Keep red for problems
        problem_scrollbar = ttk.Scrollbar(problem_display_frame, orient=tk.VERTICAL, command=self.problem_text.yview)
        self.problem_text.config(yscrollcommand=problem_scrollbar.set)
        self.problem_text.grid(row=0, column=0, sticky="nsew")
        problem_scrollbar.grid(row=0, column=1, sticky="ns")

        # --- Button Frame ---
        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=1, column=0, pady=5, sticky="ew")
        button_frame.columnconfigure(0, weight=1)
        button_frame.columnconfigure(1, weight=1)
        button_frame.columnconfigure(2, weight=1)

        scan_button = ttk.Button(button_frame, text="Re-Scan for Problems", command=self.scan_for_problems)
        scan_button.grid(row=0, column=0, padx=5, pady=5, sticky="ew")
        self.fix_button = ttk.Button(button_frame, text="Attempt Quick Fixes", command=self.attempt_quick_fixes, state=tk.DISABLED)
        self.fix_button.grid(row=0, column=1, padx=5, pady=5, sticky="ew")
        help_button = ttk.Button(button_frame, text="Help / Info", command=self.show_help_info)
        help_button.grid(row=0, column=2, padx=5, pady=5, sticky="ew")

        # --- Status Frame ---
        status_frame = ttk.LabelFrame(main_frame, text="Status / Log", padding="10")
        status_frame.grid(row=2, column=0, sticky="nsew", pady=(5, 0))
        status_frame.rowconfigure(0, weight=1)
        status_frame.columnconfigure(0, weight=1)

        self.status_text = tk.Text(status_frame, height=8, width=80, state=tk.DISABLED, wrap=tk.WORD, borderwidth=1, relief="sunken") # Default colors
        status_scrollbar = ttk.Scrollbar(status_frame, orient=tk.VERTICAL, command=self.status_text.yview)
        self.status_text.config(yscrollcommand=status_scrollbar.set)
        self.status_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        status_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

    def show_help_info(self):
        """Displays help information."""
        help_text = """
Problem Fixer Tool Help:

This tool scans your CSV file and associated image folders ('Images import', 'Images export') based on the settings in 'settings.conf' to find common problems.

Scan for Problems:
- Checks if import/export files listed in the CSV actually exist.
- Checks if CSV entries that should have a URL (based on existing export file and uploads enabled) are missing one.
- Checks for files in the 'Images import' folder that are not listed in the CSV.
- Checks for CSV entries where the 'Renamed' field is empty.

Attempt Quick Fixes:
- Copies missing export files from the import folder if the import file exists.
- Copies missing import files from the export folder if the export file exists.
- Copies the 'Original' filename to the 'Renamed' field if it's empty in the CSV.
- Uploads files listed in the CSV that have an export file but no URL (if uploads are enabled in settings.conf).
- NOTE: This does NOT automatically process unlisted import files or delete missing files from the CSV. Use the main uploader script for full processing.

Status Colors:
- Green: OK / All Found
- Orange: Partially Uploaded / Some Missing
- Red: Errors / Missing Files / No Uploads
"""
        messagebox.showinfo("Help / Information", help_text, parent=self.root)

    def run_in_thread(self, target_func, *args):
        """Runs a function in a separate thread."""
        thread = threading.Thread(target=target_func, args=args, daemon=True)
        thread.start()
        return thread

    def scan_for_problems(self):
        """Scans CSV and folders for potential problems."""
        log_status(logging.INFO, "Scanning for problems...")
        self.problem_text.config(state=tk.NORMAL)
        self.problem_text.delete('1.0', tk.END)
        self.fix_button.config(state=tk.DISABLED) # Disable until scan complete

        # Run scan in a thread to avoid blocking GUI
        self.run_in_thread(self.scan_worker)

    def scan_worker(self):
        """Background worker for scanning problems."""
        problems_found = []
        fixable_problems_exist = False # Flag to enable fix button
        csv_path = os.path.join(app_config.get('base_dir', base_dir_path), CSV_FILENAME)
        import_path_base = os.path.join(app_config.get('base_dir', base_dir_path), IMPORT_FOLDER)
        export_path_base = os.path.join(app_config.get('base_dir', base_dir_path), EXPORT_FOLDER)
        uploads_enabled = str(app_config.get('enable_upload', 'true')).lower() == 'true'

        header, data = get_csv_data(csv_path)

        if header is None:
            problems_found.append("ERROR: Cannot read or parse CSV file.")
        else:
            try:
                orig_idx, renamed_idx, url_idx = 1, 2, 3
                if not (header[orig_idx] == "Original" and header[renamed_idx] == "Renamed" and header[url_idx] == "URL"):
                    raise ValueError("CSV header mismatch")

                csv_originals = set()
                for i, row in enumerate(data):
                    original_name = row[orig_idx]
                    renamed_name = row[renamed_idx]
                    url = row[url_idx]
                    csv_originals.add(original_name)

                    import_file = os.path.join(import_path_base, original_name)
                    export_file = os.path.join(export_path_base, renamed_name)

                    import_exists = os.path.exists(import_file)
                    export_exists = os.path.exists(export_file)

                    if not import_exists:
                        problems_found.append(f"Missing import file: {original_name} (Row {i+2})")
                        if export_exists: fixable_problems_exist = True # Fixable if export exists
                    if not export_exists:
                        problems_found.append(f"Missing export file: {renamed_name} (Row {i+2})")
                        if import_exists: fixable_problems_exist = True # Fixable if import exists
                    if not renamed_name: # Check for empty renamed field
                        problems_found.append(f"Empty Renamed field: (Row {i+2}, Original: {original_name})")
                        if original_name: fixable_problems_exist = True # Fixable if original exists
                    if not url and uploads_enabled:
                         if export_exists: # Only flag missing URL if export file exists
                            problems_found.append(f"Missing URL: {renamed_name} (Row {i+2})")
                            fixable_problems_exist = True # Fixable by uploading

                # Check for unlisted import files
                if os.path.isdir(import_path_base):
                    for item in os.listdir(import_path_base):
                        item_path = os.path.join(import_path_base, item)
                        if os.path.isfile(item_path) and item not in csv_originals:
                            problems_found.append(f"Unlisted import file: {item} (Not fixable by this tool)")

            except (IndexError, ValueError):
                problems_found.append("ERROR: CSV header mismatch or invalid row structure.")

        # Update GUI from main thread using `after`
        def update_gui():
            self.problem_text.config(state=tk.NORMAL)
            if problems_found:
                self.problem_text.insert(tk.END, "Problems Found:\n" + "\n".join(problems_found))
                if fixable_problems_exist:
                    self.fix_button.config(state=tk.NORMAL) # Enable fix button
            else:
                self.problem_text.insert(tk.END, "No problems found.")
            self.problem_text.config(state=tk.DISABLED)
            log_status(logging.INFO, f"Problem scan complete. Found {len(problems_found)} issues.")

        self.root.after(0, update_gui)


    def attempt_quick_fixes(self):
        """Attempts to automatically fix detected problems."""
        log_status(logging.INFO, "Attempting quick fixes...")
        self.fix_button.config(state=tk.DISABLED) # Disable while running

        # Run fixing logic in a thread
        self.run_in_thread(self.quick_fix_worker)

    def quick_fix_worker(self):
        """Background worker for attempting quick fixes."""
        csv_path = os.path.join(app_config.get('base_dir', base_dir_path), CSV_FILENAME)
        import_path_base = os.path.join(app_config.get('base_dir', base_dir_path), IMPORT_FOLDER)
        export_path_base = os.path.join(app_config.get('base_dir', base_dir_path), EXPORT_FOLDER)
        api_key = app_config.get('api_key')
        uploads_enabled = str(app_config.get('enable_upload', 'true')).lower() == 'true'

        header, data = get_csv_data(csv_path)
        if header is None:
            log_status(logging.ERROR, "Quick Fix failed: Cannot read CSV.")
            return

        fixed_exports = 0
        fixed_imports = 0
        fixed_renames = 0 # Track fixed empty renames
        uploads_to_attempt = []
        needs_csv_save = False

        try:
            orig_idx, renamed_idx, url_idx = 1, 2, 3
            if not (header[orig_idx] == "Original" and header[renamed_idx] == "Renamed" and header[url_idx] == "URL"):
                 raise ValueError("CSV header mismatch")

            for i, row in enumerate(data):
                original_name = row[orig_idx]
                renamed_name = row[renamed_idx]
                url = row[url_idx]
                import_file = os.path.join(import_path_base, original_name)
                export_file = os.path.join(export_path_base, renamed_name)
                import_exists = os.path.exists(import_file)
                export_exists = os.path.exists(export_file)

                # Fix 1: Missing export file, but import exists
                if not export_exists and import_exists:
                    # Only copy if renamed_name is not empty (otherwise Fix 3 handles it)
                    if renamed_name:
                        try:
                            shutil.copy2(import_file, export_file)
                            log_status("SUCCESS", f"Quick Fix: Copied '{original_name}' to '{renamed_name}' in export folder.")
                            fixed_exports += 1
                            export_exists = True # Mark as existing for potential upload check
                        except Exception as e:
                            log_status(logging.ERROR, f"Quick Fix Error: Could not copy '{original_name}' to export: {e}")
                # Fix 2: Missing import file, but export exists
                elif not import_exists and export_exists:
                    # Only copy if original_name is not empty (shouldn't happen but check)
                    if original_name:
                        try:
                            shutil.copy2(export_file, import_file)
                            log_status("SUCCESS", f"Quick Fix: Copied '{renamed_name}' to '{original_name}' in import folder.")
                            fixed_imports += 1
                        except Exception as e:
                            log_status(logging.ERROR, f"Quick Fix Error: Could not copy '{renamed_name}' to import: {e}")

                # Fix 3: Empty Renamed field
                if not renamed_name and original_name:
                    data[i][renamed_idx] = original_name # Update data list directly
                    log_status("SUCCESS", f"Quick Fix: Copied Original '{original_name}' to Renamed field (Row {i+2}).")
                    fixed_renames += 1
                    needs_csv_save = True
                    renamed_name = original_name # Update local var for subsequent checks
                    export_file = os.path.join(export_path_base, renamed_name) # Update export path
                    export_exists = os.path.exists(export_file) # Re-check export existence

                # Fix 4: Missing URL, export exists, uploads enabled
                if not url and export_exists and uploads_enabled and api_key:
                    uploads_to_attempt.append({"index": i, "file_path": export_file, "renamed_name": renamed_name, "original_name": original_name})

        except (IndexError, ValueError):
            log_status(logging.ERROR, "Quick Fix failed: CSV header mismatch or invalid row structure.")
            return

        # Perform uploads if needed
        successful_uploads = 0
        failed_uploads = 0
        if uploads_to_attempt:
            log_status(logging.INFO, f"Quick Fix: Attempting to upload {len(uploads_to_attempt)} missing URLs...")
            upload_queue = queue.Queue()
            threads = []
            for item in uploads_to_attempt:
                thread = threading.Thread(target=upload_to_sul_thread,
                                          args=(item["file_path"], api_key, upload_queue),
                                          daemon=True)
                threads.append(thread); thread.start()

            completed_files = 0
            while completed_files < len(uploads_to_attempt):
                try:
                    result = upload_queue.get(timeout=0.2)
                    completed_files += 1
                    item_index = next((item["index"] for item in uploads_to_attempt if item["renamed_name"] == result["file"]), -1)

                    if item_index != -1:
                        if result["url"]:
                            successful_uploads += 1
                            data[item_index][url_idx] = result["url"] # Update data list
                            data[item_index][0] = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f") # Update timestamp
                            needs_csv_save = True
                            log_status("SUCCESS", f"Quick Fix: Uploaded '{result['file']}'")
                        else:
                            failed_uploads += 1
                            log_status(logging.ERROR, f"Quick Fix Upload Failed for {result['file']}: {result['error']}")
                    else:
                        failed_uploads += 1
                        log_status(logging.ERROR, f"Quick Fix: Could not map upload result {result['file']} back to index.")
                    log_status(logging.INFO, f"Quick Fix upload progress: {completed_files}/{len(uploads_to_attempt)}")
                except queue.Empty:
                    if not any(t.is_alive() for t in threads): break
                    time.sleep(0.1)

            log_status(logging.INFO, f"Quick Fix upload finished. Successful: {successful_uploads}, Failed: {failed_uploads}.")

        # Save CSV if any URLs were added OR Renamed fields were fixed
        if needs_csv_save:
            log_status(logging.INFO, "Quick Fix: Saving updated CSV...")
            try:
                with open(csv_path, 'w', newline='', encoding='utf-8') as csvfile:
                    writer = csv.writer(csvfile); writer.writerow(header); writer.writerows(data)
                log_status("SUCCESS", "Quick Fix: CSV log updated successfully.")
            except (IOError, csv.Error) as e:
                log_status(logging.ERROR, f"Quick Fix: Failed to save updated CSV: {e}")

        # Final summary and re-scan
        summary = f"Quick Fix Attempt Complete."
        summary += f"\nCopied missing import files: {fixed_imports}"
        summary += f"\nCopied missing export files: {fixed_exports}"
        summary += f"\nFixed empty Renamed fields: {fixed_renames}"
        summary += f"\nUploads attempted: {len(uploads_to_attempt)}"
        summary += f"\nSuccessful uploads: {successful_uploads}"
        summary += f"\nFailed uploads: {failed_uploads}"
        log_status("INFO", summary.replace("\n", " | ")) # Log summary on one line

        # Use root.after to schedule messagebox and re-scan in main thread
        if ProblemFixerApp.instance and ProblemFixerApp.instance.root: # Check instance of this class
            ProblemFixerApp.instance.root.after(0, lambda: messagebox.showinfo("Quick Fix Complete", summary, parent=self.root))
            ProblemFixerApp.instance.root.after(100, self.scan_for_problems) # Re-scan after a short delay


# --- Main Execution Block ---
if __name__ == "__main__":
    # Setup basic console handler for initial errors before file logging is set
    plain_formatter = logging.Formatter('%(levelname)s: %(message)s')
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(plain_formatter)
    logger.addHandler(console_handler) # Add temporarily

    try:
        root = tk.Tk()
        # Remove temporary console handler once GUI starts and file logging is configured
        logger.removeHandler(console_handler)
        # Store app instance for potential use by threads needing mainloop access (like dialogs)
        ProblemFixerApp.instance = ProblemFixerApp(root) # Instantiate the fixer app
        root.mainloop()
    except KeyboardInterrupt:
        print("\nOperation cancelled by user.")
        try: logger.warning("Operation cancelled by user (KeyboardInterrupt).")
        except: pass
    except Exception as e:
        print(f"\nCRITICAL ERROR: {e}")
        traceback.print_exc()
        try: logger.critical(f"An unexpected critical error occurred: {e}", exc_info=True)
        except: pass
        input("Critical error occurred. Check log file if possible. Exiting.")
    finally:
        try:
            logger.info("="*30 + " Problem Fixer Execution Finished " + "="*30 + "\n")
            for handler in logger.handlers[:]:
                try:
                    handler.close()
                    logger.removeHandler(handler)
                except Exception: pass
        except Exception: pass
        # No need to deinit colorama


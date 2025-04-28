#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# GUI Version of the Google Drive to S-UL Uploader Script using Tkinter

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
import logging
import traceback
import re
import threading # To prevent GUI freezing during long tasks
import queue # For communication between threads
import time # For small delays
import subprocess # For opening log file cross-platform

# --- GUI Imports ---
import tkinter as tk
from tkinter import ttk # Themed widgets
from tkinter import messagebox
from tkinter import simpledialog
from tkinter import filedialog

# --- Globals & Constants ---
CONFIG_FILE = "settings.conf"
IMPORT_FOLDER = "Images import"
EXPORT_FOLDER = "Images export"
CSV_FILENAME = "index.csv"
LOG_FILENAME = "script_activity.log"

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
# This will be loaded once at the start
app_config = {}
base_dir_path = os.path.dirname(os.path.abspath(__file__)) # Default base dir

# --- Utility Functions (Modified for GUI/Logging) ---

def strip_ansi_codes(text):
    """Removes ANSI escape codes from a string."""
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    return ansi_escape.sub('', str(text)) # Ensure input is string

def setup_file_logging(base_dir, enable_logging):
    """Configures or removes file logging based on the enable_logging flag."""
    global logger # Need to modify global logger
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

# --- GUI Status Update Function ---
# Use a queue to safely update GUI from other threads
status_queue = queue.Queue()

def update_status_display(text_widget):
    """Checks the queue and updates the status text widget."""
    try:
        while True:
            level, message = status_queue.get_nowait()
            clean_message = strip_ansi_codes(message)
            # Define tags for colors
            text_widget.tag_config("INFO", foreground="blue")
            text_widget.tag_config("SUCCESS", foreground="green")
            text_widget.tag_config("WARNING", foreground="orange")
            text_widget.tag_config("ERROR", foreground="red", font=('TkDefaultFont', 9, 'bold'))
            text_widget.tag_config("CRITICAL", foreground="red", background="yellow", font=('TkDefaultFont', 9, 'bold'))
            text_widget.tag_config("PRINT", foreground="black") # Default for simple prints

            tag = "PRINT" # Default
            if level == logging.INFO:
                tag = "INFO"
                logger.info(clean_message)
            elif level == logging.WARNING:
                tag = "WARNING"
                logger.warning(clean_message)
            elif level == logging.ERROR:
                tag = "ERROR"
                logger.error(clean_message)
            elif level == logging.CRITICAL:
                 tag = "CRITICAL"
                 logger.critical(clean_message)
            elif level == "SUCCESS": # Custom level for green GUI messages
                 tag = "SUCCESS"
                 logger.info(f"OK: {clean_message}")

            # Insert message with appropriate tag
            text_widget.config(state=tk.NORMAL)
            text_widget.insert(tk.END, f"{message}\n", tag)
            text_widget.config(state=tk.DISABLED)
            text_widget.see(tk.END) # Scroll to the end
            text_widget.update_idletasks() # Ensure update happens

    except queue.Empty:
        pass # No messages in queue
    # Schedule the next check
    text_widget.after(100, lambda: update_status_display(text_widget))

def log_status(level, message):
    """Puts a message into the queue for the GUI status display."""
    status_queue.put((level, message))

# --- Configuration Handling (Modified for GUI) ---

def load_config_gui():
    """Loads config or sets defaults if file missing/invalid. Returns config dict."""
    global app_config, base_dir_path
    config_parser = configparser.ConfigParser()
    defaults = {
        'drive_id': '',
        'api_key': '',
        'base_dir': base_dir_path, # Default to script location initially
        'enable_colors': 'true', # GUI doesn't use console colors directly
        'enable_logging': 'true',
        'enable_upload': 'true'
    }

    if os.path.exists(CONFIG_FILE):
        try:
            config_parser.read(CONFIG_FILE, encoding='utf-8')
            if 'DEFAULT' in config_parser:
                # Update defaults with values from file
                for key in defaults:
                    defaults[key] = config_parser['DEFAULT'].get(key, defaults[key])
            else:
                # Use temporary print as logging/colors might not be set
                print(f"WARNING: Config file '{CONFIG_FILE}' found but missing [DEFAULT] section. Using defaults.")
        except Exception as e:
            print(f"ERROR: Error reading config file '{CONFIG_FILE}': {e}. Using defaults.")
            # Keep defaults
    else:
        print(f"INFO: Config file '{CONFIG_FILE}' not found. Using defaults and will create on save.")

    # Validate base_dir
    base_dir_path = defaults['base_dir']
    if not os.path.isdir(base_dir_path):
        print(f"WARNING: Base directory '{base_dir_path}' from config/default is invalid. Resetting to script directory.")
        base_dir_path = os.path.dirname(os.path.abspath(__file__))
        defaults['base_dir'] = base_dir_path

    # Setup logging based on loaded/default value
    setup_file_logging(base_dir_path, defaults['enable_logging'])
    logger.info("Configuration loaded/defaults applied.")
    app_config = defaults # Store loaded/default config globally
    return app_config

def save_config_gui(show_success_popup=False): # Added parameter
    """Saves the current app_config to the config file."""
    global app_config
    config_parser = configparser.ConfigParser()
    # Ensure all keys are strings for saving
    config_to_save = {k: str(v) for k, v in app_config.items()}
    config_parser['DEFAULT'] = config_to_save

    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as configfile:
            config_parser.write(configfile)
        log_status("SUCCESS", f"Configuration saved to '{CONFIG_FILE}'.")
        logger.info(f"Configuration saved to '{CONFIG_FILE}'.")
        # Ensure directories exist after potentially changing base_dir
        base_dir = app_config.get('base_dir', '.')
        os.makedirs(os.path.join(base_dir, IMPORT_FOLDER), exist_ok=True)
        os.makedirs(os.path.join(base_dir, EXPORT_FOLDER), exist_ok=True)
        if show_success_popup: # Check parameter
             messagebox.showinfo("Config Saved", "Configuration saved successfully.")
        return True
    except IOError as e:
        log_status(logging.ERROR, f"Could not save config file: {e}")
        messagebox.showerror("Config Save Error", f"Could not save config file:\n{e}")
        return False
    except Exception as e:
         log_status(logging.ERROR, f"Unexpected error saving config: {e}")
         messagebox.showerror("Config Save Error", f"An unexpected error occurred:\n{e}")
         return False

# --- Core Logic Functions (Adapted for GUI feedback via log_status) ---

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
        log_status(logging.ERROR, f"Could not read CSV file '{csv_path}': {e}")
        logger.exception("CSV Read Error") # Log full traceback
    except StopIteration:
        logger.info(f"CSV file '{csv_path}' contains only a header.")
        pass

    return originals

def download_drive_folder_thread(drive_id, download_path, csv_path, callback):
    """Worker function for downloading in a separate thread."""
    log_status(logging.INFO, "Starting Google Drive download process in background thread.")
    files_to_process = []
    error_message = None
    try:
        if not drive_id:
            raise ValueError("Google Drive ID/URL is not set in configuration.")

        url = f"https://drive.google.com/drive/folders/{drive_id}" if "drive.google.com" not in drive_id else drive_id
        log_status(logging.INFO, f"Attempting download from: {url}")
        log_status(logging.INFO, f"Downloading to: {download_path}")
        logger.info(f"Drive URL/ID: {drive_id}")
        logger.info(f"Download path: {download_path}")

        os.makedirs(download_path, exist_ok=True)
        uploaded_originals = read_uploaded_originals(csv_path) # Read originals in this thread
        logger.info(f"Found {len(uploaded_originals)} files previously logged in CSV.")
        files_before_download = {f for f in os.listdir(download_path) if os.path.isfile(os.path.join(download_path, f))}
        logger.info(f"Found {len(files_before_download)} files in import directory before download.")

        log_status(logging.INFO, "Starting gdown download/sync (this might take a while)...")
        logger.info(f"Calling gdown.download_folder for URL: {url}")
        # NOTE: gdown might print directly to console, unavoidable without modifying gdown
        gdown.download_folder(url, output=download_path, quiet=False, use_cookies=False, remaining_ok=True)
        logger.info("gdown.download_folder process finished.")
        log_status(logging.INFO,"gdown download/sync process finished.")

        files_after_download = {f for f in os.listdir(download_path) if os.path.isfile(os.path.join(download_path, f))}
        logger.info(f"Found {len(files_after_download)} files in import directory after download.")
        processed_count = 0
        skipped_logged_count = 0

        log_status(logging.INFO, "Filtering downloaded files...")
        logger.info("Filtering downloaded files against CSV log...")
        for file in sorted(list(files_after_download)):
            if file not in uploaded_originals:
                files_to_process.append(file)
                logger.info(f"Identified file for processing: {file}")
                processed_count += 1
            else:
                logger.info(f"Skipping file (already logged in CSV): {file}")
                skipped_logged_count += 1

        log_status("SUCCESS", "Download and filtering complete.")
        logger.info("Download and filtering complete.")
        if files_to_process:
            log_status(logging.INFO, f"Identified {len(files_to_process)} file(s) needing processing.")
        else:
            log_status(logging.INFO, "No new files found requiring processing.")
        if skipped_logged_count > 0:
            log_status(logging.INFO, f"Skipped {skipped_logged_count} file(s) already present in the log.")

    except Exception as e:
        error_message = f"An error occurred during download/filtering: {e}"
        log_status(logging.ERROR, error_message)
        logger.exception("Download/Filter Error")
        files_to_process = [] # Ensure empty list on error

    # Use callback to return results to the main thread
    if callback:
        callback(files_to_process, error_message)


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

def write_to_csv(csv_path, processed_data):
    """Appends processed file information to the CSV log."""
    if not processed_data:
        logger.info("No processed files to write to CSV.")
        return

    logger.info(f"Attempting to write {len(processed_data)} entries to CSV: '{csv_path}'.")
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
        log_status("SUCCESS", f"Successfully added {written_count} entries to '{os.path.basename(csv_path)}'.")
        logger.info(f"Successfully wrote {written_count} entries to '{csv_path}'.")
    except (IOError, csv.Error) as e:
        log_status(logging.ERROR, f"Could not write to CSV file '{csv_path}': {e}")
        logger.exception("CSV Write Error")

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


# --- GUI Application Class ---

class UploaderApp:
    instance = None # Class variable to hold the single instance

    def __init__(self, root):
        if UploaderApp.instance is not None:
             raise Exception("Only one instance of UploaderApp can exist!")
        UploaderApp.instance = self

        self.root = root
        self.root.title("Google Drive to S-UL Uploader")
        # Make window slightly larger
        self.root.geometry("750x650")

        # Load initial configuration
        global app_config
        app_config = load_config_gui()

        # --- Variables for GUI elements ---
        self.drive_id_var = tk.StringVar(value=app_config.get('drive_id', ''))
        self.api_key_var = tk.StringVar(value=app_config.get('api_key', ''))
        self.base_dir_var = tk.StringVar(value=app_config.get('base_dir', ''))
        self.enable_logging_var = tk.BooleanVar(value=str(app_config.get('enable_logging', 'true')).lower() == 'true')
        self.enable_upload_var = tk.BooleanVar(value=str(app_config.get('enable_upload', 'true')).lower() == 'true')
        # GUI doesn't use console colors, but keep var for config consistency
        self.enable_colors_var = tk.BooleanVar(value=str(app_config.get('enable_colors', 'true')).lower() == 'true')

        # --- Build GUI ---
        self.create_widgets()
        self.update_widget_states() # Initial state update

        # Start the status display updater
        self.status_text.after(100, lambda: update_status_display(self.status_text))
        log_status(logging.INFO, "Application initialized.")

    def create_widgets(self):
        # Main frame
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # --- Configuration Frame ---
        config_frame = ttk.LabelFrame(main_frame, text="Configuration", padding="10")
        config_frame.pack(fill=tk.X, pady=5)
        config_frame.columnconfigure(1, weight=1) # Make entry fields expand

        ttk.Label(config_frame, text="Google Drive ID/URL:").grid(row=0, column=0, padx=5, pady=5, sticky=tk.W)
        drive_entry = ttk.Entry(config_frame, textvariable=self.drive_id_var, width=60)
        drive_entry.grid(row=0, column=1, padx=5, pady=5, sticky=tk.EW)

        ttk.Label(config_frame, text="S-UL API Key:").grid(row=1, column=0, padx=5, pady=5, sticky=tk.W)
        api_key_entry = ttk.Entry(config_frame, textvariable=self.api_key_var, width=60, show="*") # Hide API key
        api_key_entry.grid(row=1, column=1, padx=5, pady=5, sticky=tk.EW)

        ttk.Label(config_frame, text="Base Directory:").grid(row=2, column=0, padx=5, pady=5, sticky=tk.W)
        base_dir_entry = ttk.Entry(config_frame, textvariable=self.base_dir_var, width=60)
        base_dir_entry.grid(row=2, column=1, padx=5, pady=5, sticky=tk.EW)
        browse_button = ttk.Button(config_frame, text="Browse...", command=self.browse_base_dir)
        browse_button.grid(row=2, column=2, padx=5, pady=5)

        # --- Toggles Frame ---
        toggles_frame = ttk.Frame(config_frame)
        toggles_frame.grid(row=3, column=0, columnspan=3, pady=5, sticky=tk.W)

        log_check = ttk.Checkbutton(toggles_frame, text="Enable File Logging", variable=self.enable_logging_var, command=self.toggle_logging)
        log_check.pack(side=tk.LEFT, padx=10)

        upload_check = ttk.Checkbutton(toggles_frame, text="Enable Uploads", variable=self.enable_upload_var, command=self.toggle_uploads)
        upload_check.pack(side=tk.LEFT, padx=10)

        # --- Added Open Log/CSV Buttons ---
        file_button_frame = ttk.Frame(toggles_frame) # New frame for file buttons
        file_button_frame.pack(side=tk.LEFT, padx=10)

        open_log_button = ttk.Button(file_button_frame, text="Open Log File", command=self.open_log_file)
        open_log_button.pack(side=tk.LEFT, padx=5)
        open_csv_button = ttk.Button(file_button_frame, text="Open CSV File", command=self.open_csv_file)
        open_csv_button.pack(side=tk.LEFT, padx=5)


        # Save Config Button
        save_button = ttk.Button(config_frame, text="Save Configuration", command=self.save_config_action_with_popup) # Changed command
        save_button.grid(row=4, column=0, columnspan=3, pady=10)

        # --- Actions Frame ---
        actions_frame = ttk.LabelFrame(main_frame, text="Actions", padding="10")
        actions_frame.pack(fill=tk.X, pady=5)
        # Configure columns to expand equally
        actions_frame.columnconfigure(0, weight=1)
        actions_frame.columnconfigure(1, weight=1)
        actions_frame.columnconfigure(2, weight=1)


        start_button = ttk.Button(actions_frame, text="Start Script (Import/Rename/Upload)", command=self.start_script_action)
        start_button.grid(row=0, column=0, padx=5, pady=5, sticky=tk.EW)

        edit_button = ttk.Button(actions_frame, text="Edit CSV Entry", command=self.edit_entry_action)
        edit_button.grid(row=0, column=1, padx=5, pady=5, sticky=tk.EW)

        bulk_rename_button = ttk.Button(actions_frame, text="Bulk Rename Existing Items", command=self.bulk_rename_action)
        bulk_rename_button.grid(row=1, column=0, padx=5, pady=5, sticky=tk.EW)

        bulk_upload_button = ttk.Button(actions_frame, text="Bulk Upload Existing Items", command=self.bulk_upload_action)
        bulk_upload_button.grid(row=1, column=1, padx=5, pady=5, sticky=tk.EW)

        nuke_button = ttk.Button(actions_frame, text="NUKE Directory", command=self.nuke_action)
        nuke_button.grid(row=1, column=2, padx=5, pady=5, sticky=tk.EW)
        # Add style for Nuke button
        style = ttk.Style()
        style.configure("Nuke.TButton", foreground="red", font=('TkDefaultFont', 9, 'bold'))
        nuke_button.configure(style="Nuke.TButton")


        # --- Status Frame ---
        status_frame = ttk.LabelFrame(main_frame, text="Status / Log", padding="10")
        status_frame.pack(fill=tk.BOTH, expand=True, pady=5)

        self.status_text = tk.Text(status_frame, height=15, width=80, state=tk.DISABLED, wrap=tk.WORD, borderwidth=1, relief="sunken")
        self.status_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        scrollbar = ttk.Scrollbar(status_frame, orient=tk.VERTICAL, command=self.status_text.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.status_text.config(yscrollcommand=scrollbar.set)

    # --- GUI Action Handlers ---

    def browse_base_dir(self):
        directory = filedialog.askdirectory(initialdir=self.base_dir_var.get() or base_dir_path)
        if directory: # Only update if a directory was selected
            self.base_dir_var.set(directory)
            log_status(logging.INFO, f"Base directory selected: {directory}")

    def update_widget_states(self):
        """Enable/disable widgets based on current config state."""
        # Example: Disable upload-related buttons if API key missing or uploads disabled
        api_key_present = bool(self.api_key_var.get())
        uploads_enabled_state = self.enable_upload_var.get()
        can_upload = api_key_present and uploads_enabled_state

        # Find buttons (this is a bit fragile, assumes button text doesn't change drastically)
        # A better way is to store button references, but this works for now
        for frame in self.root.winfo_children():
             if isinstance(frame, ttk.Frame): # Main frame
                 for sub_frame in frame.winfo_children():
                      if isinstance(sub_frame, ttk.LabelFrame) and "Actions" in sub_frame.cget("text"):
                           for widget in sub_frame.winfo_children():
                                if isinstance(widget, ttk.Button):
                                    button_text = widget.cget("text")
                                    if "Bulk Upload" in button_text:
                                         widget.config(state=tk.NORMAL if can_upload else tk.DISABLED)
                                    # Add other button state logic here if needed
                                    # e.g., disable Start Script if base dir invalid?
                                    # base_ok = os.path.isdir(self.base_dir_var.get())
                                    # if "Start Script" in button_text:
                                    #     widget.config(state=tk.NORMAL if base_ok else tk.DISABLED)


    def save_config_action(self, show_success_popup=False): # Modified to accept parameter
        """Handles saving the configuration from the GUI."""
        global app_config, base_dir_path
        log_status(logging.INFO, "Saving configuration...")
        # Update app_config from GUI variables before saving
        app_config['drive_id'] = self.drive_id_var.get()
        app_config['api_key'] = self.api_key_var.get()
        new_base_dir = self.base_dir_var.get()
        app_config['enable_colors'] = str(self.enable_colors_var.get()).lower()
        app_config['enable_logging'] = str(self.enable_logging_var.get()).lower()
        app_config['enable_upload'] = str(self.enable_upload_var.get()).lower()

        # Validate and update base directory
        if not os.path.isdir(new_base_dir):
            log_status(logging.ERROR, f"Invalid Base Directory: '{new_base_dir}'. Cannot save.")
            messagebox.showerror("Save Error", f"Invalid Base Directory:\n{new_base_dir}\nPlease select a valid folder.")
            return False # Indicate save failure

        # If base dir changed, update global path and re-setup logging
        if new_base_dir != app_config.get('base_dir'):
             log_status(logging.INFO, f"Base directory changed from '{app_config.get('base_dir')}' to '{new_base_dir}'.")
             base_dir_path = new_base_dir
             app_config['base_dir'] = new_base_dir
             setup_file_logging(base_dir_path, app_config['enable_logging']) # Use updated path

        if save_config_gui(show_success_popup): # Pass parameter here
             self.update_widget_states() # Update button states after save
             return True
        else:
             return False # Indicate save failure

    def save_config_action_with_popup(self):
        """Wrapper to call save_config_action with popup enabled."""
        self.save_config_action(show_success_popup=True)


    def toggle_logging(self):
        """Handles toggling file logging."""
        global app_config
        is_enabled = self.enable_logging_var.get()
        app_config['enable_logging'] = str(is_enabled).lower()
        base_dir = app_config.get('base_dir')
        if base_dir and os.path.isdir(base_dir):
            setup_file_logging(base_dir, is_enabled)
            log_status(logging.INFO, f"File logging {'enabled' if is_enabled else 'disabled'}.")
            # Auto-save config after toggle
            save_config_gui(show_success_popup=False)
        else:
             log_status(logging.ERROR, "Cannot toggle logging: Base directory not valid.")
             messagebox.showerror("Error", "Cannot toggle logging: Base directory is not set or invalid.")
             self.enable_logging_var.set(not is_enabled) # Revert toggle visually

    def toggle_uploads(self):
        """Handles toggling uploads, checking for API key."""
        global app_config
        is_enabled = self.enable_upload_var.get()
        api_key_present = bool(app_config.get('api_key', ''))

        if is_enabled and not api_key_present:
            log_status(logging.WARNING, "Cannot enable uploads: API Key is not set.")
            messagebox.showwarning("Cannot Enable Uploads", "API Key is not set in the configuration.\nPlease add an API key before enabling uploads.")
            self.enable_upload_var.set(False) # Revert toggle visually
        else:
            app_config['enable_upload'] = str(is_enabled).lower()
            log_status(logging.INFO, f"Uploads {'enabled' if is_enabled else 'disabled'}.")
            # Auto-save config after toggle
            save_config_gui(show_success_popup=False)
        self.update_widget_states() # Update button states

    def open_log_file(self):
        """Opens the log file using the default system application."""
        log_file_path = os.path.join(app_config.get('base_dir', '.'), LOG_FILENAME)
        log_status(logging.INFO, f"Attempting to open log file: {log_file_path}")
        if not os.path.exists(log_file_path):
            log_status(logging.ERROR, "Log file does not exist yet.")
            messagebox.showerror("Error", f"Log file not found:\n{log_file_path}")
            return

        try:
            if sys.platform == "win32":
                os.startfile(log_file_path)
            elif sys.platform == "darwin": # macOS
                subprocess.Popen(['open', log_file_path])
            else: # Linux and other Unix-like
                subprocess.Popen(['xdg-open', log_file_path])
        except FileNotFoundError:
             log_status(logging.ERROR, f"Could not find application to open log file (xdg-open or open).")
             messagebox.showerror("Error", "Could not find a default application to open the log file.")
        except Exception as e:
            log_status(logging.ERROR, f"Failed to open log file: {e}")
            messagebox.showerror("Error", f"Failed to open log file:\n{e}")
            logger.exception("Failed to open log file")

    def open_csv_file(self):
        """Opens the CSV file using the default system application."""
        csv_file_path = os.path.join(app_config.get('base_dir', '.'), CSV_FILENAME)
        log_status(logging.INFO, f"Attempting to open CSV file: {csv_file_path}")
        if not os.path.exists(csv_file_path):
            log_status(logging.ERROR, "CSV file does not exist yet.")
            messagebox.showerror("Error", f"CSV file not found:\n{csv_file_path}")
            return

        try:
            if sys.platform == "win32":
                os.startfile(csv_file_path)
            elif sys.platform == "darwin": # macOS
                subprocess.Popen(['open', csv_file_path])
            else: # Linux and other Unix-like
                subprocess.Popen(['xdg-open', csv_file_path])
        except FileNotFoundError:
             log_status(logging.ERROR, f"Could not find application to open CSV file (xdg-open or open).")
             messagebox.showerror("Error", "Could not find a default application to open the CSV file.")
        except Exception as e:
            log_status(logging.ERROR, f"Failed to open CSV file: {e}")
            messagebox.showerror("Error", f"Failed to open CSV file:\n{e}")
            logger.exception("Failed to open CSV file")


    def run_in_thread(self, target_func, *args):
        """Runs a function in a separate thread to avoid freezing the GUI."""
        thread = threading.Thread(target=target_func, args=args, daemon=True)
        thread.start()
        return thread

    # --- Action Button Callbacks ---

    def start_script_action(self):
        """Handles the 'Start Script' button click."""
        log_status(logging.INFO, "'Start Script' button clicked.")
        # Save config without popup before starting
        if not self.save_config_action(show_success_popup=False):
             log_status(logging.ERROR, "Config save failed. Aborting script start.")
             return
        if not os.path.isdir(app_config.get('base_dir')):
             messagebox.showerror("Error", "Base directory is invalid. Please set it correctly.")
             return

        # Ask for import source via dialog
        source_choice = simpledialog.askinteger("Import Source",
                                                "Choose import source:\n\n"
                                                "1: Google Drive\n"
                                                "2: Local Folder\n\n"
                                                "Enter number (1 or 2):",
                                                parent=self.root, minvalue=1, maxvalue=2)

        if source_choice == 1:
            log_status(logging.INFO, "User chose Google Drive import.")
            drive_id = app_config.get('drive_id')
            if not drive_id:
                log_status(logging.ERROR, "Google Drive ID is not set.")
                messagebox.showerror("Error", "Google Drive ID is not set in configuration.")
                return
            # Run download in thread
            log_status(logging.INFO, "Starting Google Drive download...")
            self.run_in_thread(download_drive_folder_thread,
                               drive_id,
                               os.path.join(app_config['base_dir'], IMPORT_FOLDER),
                               os.path.join(app_config['base_dir'], CSV_FILENAME),
                               self.handle_download_complete)
        elif source_choice == 2:
            log_status(logging.INFO, "User chose Local Folder import.")
            import_path = os.path.join(app_config['base_dir'], IMPORT_FOLDER)
            messagebox.showinfo("Local Import", f"Please place files into:\n{import_path}\n\nClick OK when ready.")
            self.process_local_folder()
        else:
            log_status(logging.INFO, "Import cancelled by user.")

    def handle_download_complete(self, files_to_process, error_message):
        """Callback function after download thread finishes."""
        if error_message:
            messagebox.showerror("Download Error", error_message)
            return
        if not files_to_process:
            log_status(logging.INFO, "No new files found from Google Drive to process.")
            messagebox.showinfo("Download Complete", "No new files found to process.")
            return

        log_status(logging.INFO, f"Download complete. Found {len(files_to_process)} files to process.")
        # Schedule GUI update in main thread
        self.root.after(0, lambda: self.ask_rename_method(files_to_process))

    def process_local_folder(self):
        """Scans local folder and proceeds to rename prompt."""
        import_path = os.path.join(app_config['base_dir'], IMPORT_FOLDER)
        csv_path = os.path.join(app_config['base_dir'], CSV_FILENAME)
        files_to_process = []
        try:
            local_files = [f for f in os.listdir(import_path) if os.path.isfile(os.path.join(import_path, f))]
            if not local_files:
                log_status(logging.INFO, "No files found in the local import folder.")
                messagebox.showinfo("Local Import", "No files found in the import folder.")
                return

            uploaded_originals = read_uploaded_originals(csv_path)
            files_to_process = [f for f in local_files if f not in uploaded_originals]
            skipped_count = len(local_files) - len(files_to_process)

            if not files_to_process:
                 log_status(logging.INFO, "No new files found in local import folder.")
                 msg = "No new files found to process."
                 if skipped_count > 0: msg += f"\n({skipped_count} file(s) already logged were ignored)."
                 messagebox.showinfo("Local Import", msg)
                 return

            log_status(logging.INFO, f"Found {len(files_to_process)} new local files.")
            if skipped_count > 0: log_status(logging.INFO, f"Skipped {skipped_count} already logged files.")
            self.ask_rename_method(files_to_process)

        except Exception as e:
            log_status(logging.ERROR, f"Error reading local import folder: {e}")
            messagebox.showerror("Error", f"Error reading local import folder:\n{e}")
            logger.exception("Local folder read error")

    def ask_rename_method(self, files_to_process):
        """Asks user how to rename files."""
        rename_choice = simpledialog.askinteger("Rename Method",
                                                f"Found {len(files_to_process)} files to rename.\n\n"
                                                "Choose method:\n"
                                                "1: Rename individually\n"
                                                "2: Bulk rename sequentially\n\n"
                                                "Enter number (1 or 2):",
                                                parent=self.root, minvalue=1, maxvalue=2)

        renamed_files_info = []
        import_path = os.path.join(app_config['base_dir'], IMPORT_FOLDER)
        export_path = os.path.join(app_config['base_dir'], EXPORT_FOLDER)

        if rename_choice == 1:
            # --- Implement Individual Rename GUI Flow ---
            log_status(logging.INFO, "Starting individual rename...")
            # This needs to run in the main thread because of simpledialog
            self.individual_rename_gui(import_path, export_path, files_to_process)

        elif rename_choice == 2:
            # Bulk rename can be done more easily
            base_name = simpledialog.askstring("Bulk Rename", "Enter base name (e.g., TEAM):", parent=self.root)
            if base_name:
                log_status(logging.INFO, f"Starting bulk rename with base '{base_name}'...")
                # Run bulk rename in thread
                self.run_in_thread(self.bulk_rename_new_files_thread, import_path, export_path, files_to_process, base_name)
            else:
                log_status(logging.INFO, "Bulk rename cancelled (no base name).")
        else:
            log_status(logging.INFO, "Renaming cancelled.")

    def individual_rename_gui(self, import_path, export_path, files_to_process):
        """Handles individual renaming using GUI dialogs (runs in main thread)."""
        renamed_list_gui = []
        skipped_count = 0
        renamed_count = 0
        os.makedirs(export_path, exist_ok=True)
        log_status(logging.INFO, f"Starting individual rename for {len(files_to_process)} files...")

        for i, original_filename in enumerate(sorted(files_to_process)):
            src_path = os.path.join(import_path, original_filename)
            if not os.path.isfile(src_path):
                log_status(logging.WARNING, f"Source file not found, skipping: {original_filename}")
                skipped_count += 1
                continue

            # Use askstring for each file
            prompt = f"File {i+1}/{len(files_to_process)}: {original_filename}\nEnter new name (no ext, blank to keep):"
            new_name_base = simpledialog.askstring("Rename File", prompt, parent=self.root)

            if new_name_base is None: # User cancelled dialog
                 log_status(logging.WARNING, "Individual rename cancelled by user.")
                 messagebox.showwarning("Cancelled", "Rename process cancelled.")
                 return # Abort the whole process

            _, ext = os.path.splitext(original_filename)
            new_filename = f"{new_name_base.strip()}{ext}" if new_name_base.strip() else original_filename
            dest_path = os.path.join(export_path, new_filename)
            logger.info(f"Processing individual rename: '{original_filename}' -> '{new_filename}'.")

            # Handle conflicts
            counter = 1
            while os.path.exists(dest_path) and dest_path != src_path:
                log_status(logging.WARNING, f"Conflict: '{new_filename}' exists.")
                if messagebox.askyesno("Conflict", f"File '{new_filename}' already exists.\nOverwrite?", parent=self.root):
                    log_status(logging.INFO, f"User chose to overwrite '{new_filename}'.")
                    break
                else:
                    # Try alternative name (simple _1, _2 suffix)
                    alt_base = new_name_base if new_name_base else os.path.splitext(original_filename)[0]
                    new_filename = f"{alt_base}_{counter}{ext}"
                    dest_path = os.path.join(export_path, new_filename)
                    log_status(logging.INFO, f"Trying alternative name: {new_filename}")
                    counter += 1
                    if counter > 10:
                         log_status(logging.ERROR, f"Too many conflicts for '{original_filename}', skipping.")
                         messagebox.showerror("Error", f"Too many conflicts for {original_filename}. Skipping file.", parent=self.root)
                         new_filename = None
                         break

            if new_filename is None:
                skipped_count += 1
                continue

            try:
                shutil.copy2(src_path, dest_path)
                log_status("SUCCESS", f"Copied '{original_filename}' to '{new_filename}'")
                renamed_list_gui.append((original_filename, new_filename, dest_path))
                renamed_count += 1
            except Exception as e:
                 log_status(logging.ERROR, f"Error copying {original_filename} to export folder: {e}")
                 messagebox.showerror("Copy Error", f"Error copying {original_filename}:\n{e}", parent=self.root)
                 skipped_count += 1

        log_status(logging.INFO, f"Individual rename finished. Processed: {renamed_count}, Skipped: {skipped_count}.")
        if renamed_list_gui:
            # Proceed to upload/log
            self.process_uploads_and_log(renamed_list_gui)
        else:
             log_status(logging.INFO, "No files were successfully processed during individual rename.")


    def bulk_rename_new_files_thread(self, import_path, export_path, files_to_process, base_name):
        """Handles bulk renaming of NEW files in a thread."""
        renamed_list_gui = []
        skipped_count = 0
        renamed_count = 0
        os.makedirs(export_path, exist_ok=True)
        start_number = 1
        num_digits = len(str(len(files_to_process) + start_number - 1))

        for i, original_filename in enumerate(sorted(files_to_process)):
            src_path = os.path.join(import_path, original_filename)
            if not os.path.isfile(src_path):
                log_status(logging.WARNING, f"Source file not found, skipping: {original_filename}")
                skipped_count += 1
                continue

            _, ext = os.path.splitext(original_filename)
            ext = ext if ext else "" # Handle no extension
            new_filename_base = f"{base_name}{i + start_number:0{num_digits}d}"
            new_filename = f"{new_filename_base}{ext}"
            dest_path = os.path.join(export_path, new_filename)
            logger.info(f"Processing bulk rename: '{original_filename}' -> '{new_filename}'.")

            # Handle conflicts
            counter = 1
            while os.path.exists(dest_path):
                log_status(logging.WARNING, f"Conflict: '{new_filename}' exists. Trying alternative.")
                new_filename = f"{new_filename_base}_conflict_{counter}{ext}"
                dest_path = os.path.join(export_path, new_filename)
                counter += 1
                if counter > 5:
                    log_status(logging.ERROR, f"Too many conflicts for '{original_filename}', skipping.")
                    new_filename = None
                    break

            if new_filename is None:
                skipped_count += 1
                continue

            try:
                shutil.copy2(src_path, dest_path)
                log_status(logging.INFO, f"  {original_filename} -> {new_filename}")
                renamed_list_gui.append((original_filename, new_filename, dest_path))
                renamed_count += 1
            except Exception as e:
                log_status(logging.ERROR, f"Error copying '{original_filename}' to '{dest_path}': {e}")
                logger.exception("Bulk rename copy error")
                skipped_count += 1

        log_status("SUCCESS", f"Bulk rename complete. Renamed: {renamed_count}, Skipped: {skipped_count}.")
        if renamed_list_gui:
            # Schedule upload/log processing back in the main thread
            self.root.after(0, lambda: self.process_uploads_and_log(renamed_list_gui))
        else:
             log_status(logging.INFO, "No files were successfully processed during bulk rename.")


    def process_uploads_and_log(self, renamed_files_info):
        """Handles uploading (if enabled) and logging to CSV."""
        if not renamed_files_info: return

        uploads_enabled = str(app_config.get('enable_upload', 'true')).lower() == 'true'
        api_key = app_config.get('api_key')
        csv_path = os.path.join(app_config['base_dir'], CSV_FILENAME)
        processed_for_csv = []

        if not uploads_enabled or not api_key:
            log_status(logging.WARNING, "Uploads skipped (disabled or no API key).")
            for original_name, new_name, file_path in renamed_files_info:
                processed_for_csv.append((datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f"), original_name, new_name, ""))
            write_to_csv(csv_path, processed_for_csv)
            log_status(logging.INFO, "Processing complete (uploads skipped).")
            messagebox.showinfo("Processing Complete", f"{len(processed_for_csv)} files processed and logged (uploads skipped).")
        else:
            log_status(logging.INFO, f"Starting upload process for {len(renamed_files_info)} files...")
            # --- Run uploads in threads ---
            upload_queue = queue.Queue()
            threads = []
            for original_name, new_name, file_path in renamed_files_info:
                thread = threading.Thread(target=upload_to_sul_thread,
                                          args=(file_path, api_key, upload_queue),
                                          daemon=True)
                threads.append(thread)
                thread.start()

            # --- Monitor upload threads ---
            total_files = len(threads)
            completed_files = 0
            successful_uploads = 0
            failed_uploads = 0

            def check_upload_queue():
                nonlocal completed_files, successful_uploads, failed_uploads, processed_for_csv
                try:
                    while True: # Process all available results
                        result = upload_queue.get_nowait()
                        completed_files += 1
                        # Find corresponding entry in renamed_files_info to get original name
                        original_name = ""
                        new_name = result["file"]
                        for orig, renamed, fpath in renamed_files_info:
                             if os.path.basename(fpath) == new_name:
                                 original_name = orig
                                 break

                        if result["url"]:
                            successful_uploads += 1
                            processed_for_csv.append((datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f"), original_name, new_name, result["url"]))
                        else:
                            failed_uploads += 1
                            processed_for_csv.append((datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f"), original_name, new_name, "")) # Log with blank URL
                            log_status(logging.ERROR, f"Upload failed for {new_name}: {result['error']}")

                        # Update progress (optional)
                        log_status(logging.INFO, f"Upload progress: {completed_files}/{total_files}")

                except queue.Empty:
                    pass # No more results for now

                if completed_files < total_files:
                    # Schedule next check
                    self.root.after(200, check_upload_queue)
                else:
                    # All uploads finished
                    log_status(logging.INFO, f"Upload process finished. Successful: {successful_uploads}, Failed: {failed_uploads}.")
                    if processed_for_csv:
                        write_to_csv(csv_path, processed_for_csv)
                    log_status(logging.INFO, "Processing complete.")
                    summary = f"{len(processed_for_csv)} files processed.\nSuccessful uploads: {successful_uploads}\nFailed uploads: {failed_uploads}"
                    messagebox.showinfo("Processing Complete", summary)

            # Start checking the queue
            self.root.after(100, check_upload_queue)

    def edit_entry_action(self):
        """Handles the 'Edit Entry' button click."""
        log_status(logging.INFO, "'Edit Entry' button clicked.")
        # Ensure config is up-to-date
        if not self.save_config_action(show_success_popup=False): return # Abort if save fails

        csv_path = os.path.join(app_config['base_dir'], CSV_FILENAME)
        if not os.path.exists(csv_path):
             messagebox.showerror("Error", f"CSV file not found:\n{csv_path}")
             return

        # --- Launch Edit Window ---
        try:
            # Pass the main app instance so the EditWindow can access its methods if needed
            # Although direct data modification might be simpler here
            edit_window = EditWindow(self.root, csv_path, app_config)
            # The main window will wait until the edit window is closed
            # The edit window handles its own logic and saving
        except Exception as e:
             log_status(logging.ERROR, f"Failed to open Edit window: {e}")
             messagebox.showerror("Error", f"Failed to open Edit window:\n{e}")
             logger.exception("Edit Window Error")


    def bulk_rename_action(self):
        """Handles the 'Bulk Rename Existing' button click."""
        log_status(logging.INFO, "'Bulk Rename Existing' button clicked.")
        if not self.save_config_action(show_success_popup=False): return # Abort if save fails
        # Run in thread
        self.run_in_thread(run_bulk_rename_existing_thread, app_config)


    def bulk_upload_action(self):
        """Handles the 'Bulk Upload Existing' button click."""
        log_status(logging.INFO, "'Bulk Upload Existing' button clicked.")
        if not self.save_config_action(show_success_popup=False): return # Abort if save fails
        # Run in thread
        self.run_in_thread(bulk_upload_from_csv_thread, app_config)


    def nuke_action(self):
        """Handles the 'NUKE' button click."""
        log_status(logging.WARNING, "NUKE button clicked.")
        base_dir = app_config.get('base_dir')
        if not base_dir or not os.path.isdir(base_dir):
            messagebox.showerror("Nuke Error", "Base directory is not set or invalid.")
            return

        abs_base_dir = os.path.abspath(base_dir)
        msg1 = f"Are you ABSOLUTELY sure you want to permanently delete the entire working directory?\n\n{abs_base_dir}"
        if not messagebox.askyesno("NUKE Confirmation", msg1, icon='warning'):
            log_status(logging.INFO, "Nuke cancelled by user (first confirmation).")
            return

        folder_name = os.path.basename(abs_base_dir)
        msg2 = f"Final confirmation: Permanently delete '{folder_name}' and ALL its contents?"
        if not messagebox.askyesno("NUKE Final Confirmation", msg2, icon='error'):
            log_status(logging.INFO, "Nuke cancelled by user (second confirmation).")
            return

        log_status(logging.WARNING, f"NUKE INITIATED for directory: {abs_base_dir}")
        log_status(logging.INFO, "Closing log handler before nuke...")
        # Close log handler
        for handler in logger.handlers[:]:
            if isinstance(handler, logging.FileHandler):
                try:
                    handler.close()
                    logger.removeHandler(handler)
                    log_status(logging.INFO, "Log handler closed.")
                    break
                except Exception as log_close_e:
                    log_status(logging.ERROR, f"Error closing log handler: {log_close_e}")
                    messagebox.showwarning("Nuke Warning", f"Could not close log file handle:\n{log_close_e}\n\nNuke might fail.")

        try:
            shutil.rmtree(abs_base_dir)
            log_status("SUCCESS", f"Successfully deleted folder: {abs_base_dir}")
            messagebox.showinfo("Nuke Complete", f"Successfully deleted folder:\n{abs_base_dir}\n\nExiting application.")
            self.root.quit() # Exit app
        except Exception as e:
            log_status(logging.CRITICAL, f"Nuke FAILED: {e}")
            logger.exception("Nuke failed")
            messagebox.showerror("Nuke Failed", f"Failed to delete directory:\n{e}\n\nSome files might remain.")
            # Try to re-establish logging
            try:
                setup_file_logging(abs_base_dir, 'true') # Assume logging should be on after failure
                logger.info("Attempted to re-establish logging after failed nuke.")
            except: pass # Ignore errors here

# --- Edit Entry Window Class ---
class EditWindow(tk.Toplevel):
    def __init__(self, parent, csv_path, current_config):
        super().__init__(parent)
        self.title("Edit CSV Entry")
        self.geometry("700x550") # Made wider and taller
        self.transient(parent) # Keep window on top of parent
        self.grab_set() # Modal behavior

        self.csv_path = csv_path
        self.config = current_config
        self.base_dir = current_config.get('base_dir')
        self.export_path_base = os.path.join(self.base_dir, EXPORT_FOLDER)
        self.import_path_base = os.path.join(self.base_dir, IMPORT_FOLDER)
        self.api_key = current_config.get('api_key')
        self.uploads_enabled = str(current_config.get('enable_upload', 'true')).lower() == 'true'

        self.header, self.data = get_csv_data(self.csv_path) # Load data on init
        # Store original data for potential revert on save failure
        self.original_data_on_load = [list(row) for row in self.data]

        if self.header is None or not self.data:
             messagebox.showerror("Error", "Could not load CSV data or CSV is empty.", parent=self)
             self.destroy()
             return

        self.create_edit_widgets()

    def create_edit_widgets(self):
        main_frame = ttk.Frame(self, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # --- Define StringVars FIRST ---
        self.detail_original_var = tk.StringVar()
        self.detail_renamed_var = tk.StringVar()
        self.detail_url_var = tk.StringVar()
        self.detail_ts_var = tk.StringVar()
        # --- End Define StringVars ---

        # --- Listbox Frame (Allowing Multi-Select) ---
        list_frame = ttk.Frame(main_frame)
        list_frame.pack(pady=5, fill=tk.BOTH, expand=True) # Expand listbox vertically
        ttk.Label(list_frame, text="Select Entry (Ctrl/Shift+Click for multiple):").pack(side=tk.TOP, padx=5, anchor=tk.W)

        self.entry_listbox = tk.Listbox(list_frame, height=15, exportselection=False, selectmode=tk.EXTENDED) # Changed height and selectmode
        self.entry_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5)
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.entry_listbox.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.entry_listbox.config(yscrollcommand=scrollbar.set)

        self.entry_listbox.bind('<<ListboxSelect>>', self.on_listbox_select)

        # --- Details Frame (Improved Layout) ---
        self.details_frame = ttk.LabelFrame(main_frame, text="Selected Item Details", padding="10")
        self.details_frame.pack(pady=10, fill=tk.X) # Fill X only
        self.details_frame.columnconfigure(1, weight=1) # Allow value label to expand

        ttk.Label(self.details_frame, text="Original:").grid(row=0, column=0, sticky=tk.NW, padx=5, pady=2)
        ttk.Label(self.details_frame, textvariable=self.detail_original_var, wraplength=450, justify=tk.LEFT).grid(row=0, column=1, sticky=tk.W, padx=5, pady=2)
        ttk.Label(self.details_frame, text="Renamed:").grid(row=1, column=0, sticky=tk.NW, padx=5, pady=2)
        ttk.Label(self.details_frame, textvariable=self.detail_renamed_var, wraplength=450, justify=tk.LEFT).grid(row=1, column=1, sticky=tk.W, padx=5, pady=2)
        ttk.Label(self.details_frame, text="URL:").grid(row=2, column=0, sticky=tk.NW, padx=5, pady=2)
        ttk.Label(self.details_frame, textvariable=self.detail_url_var, wraplength=450, justify=tk.LEFT).grid(row=2, column=1, sticky=tk.W, padx=5, pady=2)
        ttk.Label(self.details_frame, text="Timestamp:").grid(row=3, column=0, sticky=tk.NW, padx=5, pady=2)
        ttk.Label(self.details_frame, textvariable=self.detail_ts_var).grid(row=3, column=1, sticky=tk.W, padx=5, pady=2)

        # --- Action Buttons Frame ---
        action_button_frame = ttk.Frame(main_frame) # Use a simple frame
        action_button_frame.pack(pady=5, fill=tk.X)

        # Single Item Actions (Left)
        single_item_frame = ttk.Frame(action_button_frame)
        single_item_frame.pack(side=tk.LEFT, padx=5)
        ttk.Label(single_item_frame, text="Single Item Actions:").pack(anchor=tk.W)
        self.rename_button = ttk.Button(single_item_frame, text="Change Renamed", command=self.action_rename, state=tk.DISABLED)
        self.rename_button.pack(side=tk.LEFT, padx=2, pady=2)
        self.reupload_button = ttk.Button(single_item_frame, text="Re-upload", command=self.action_reupload, state=tk.DISABLED)
        self.reupload_button.pack(side=tk.LEFT, padx=2, pady=2)
        self.editurl_button = ttk.Button(single_item_frame, text="Edit URL", command=self.action_edit_url, state=tk.DISABLED)
        self.editurl_button.pack(side=tk.LEFT, padx=2, pady=2)

        # Multi Item Actions (Right)
        multi_item_frame = ttk.Frame(action_button_frame)
        multi_item_frame.pack(side=tk.RIGHT, padx=5)
        ttk.Label(multi_item_frame, text="Multi-Item Actions:").pack(anchor=tk.W)
        self.bulk_rename_sel_button = ttk.Button(multi_item_frame, text="Bulk Rename Selected", command=self.action_bulk_rename_selected, state=tk.DISABLED)
        self.bulk_rename_sel_button.pack(side=tk.LEFT, padx=2, pady=2)
        self.bulk_reupload_sel_button = ttk.Button(multi_item_frame, text="Re-upload Selected", command=self.action_reupload_selected, state=tk.DISABLED)
        self.bulk_reupload_sel_button.pack(side=tk.LEFT, padx=2, pady=2)
        self.delete_sel_button = ttk.Button(multi_item_frame, text="Delete Selected", command=self.action_delete_selected, state=tk.DISABLED, style="Nuke.TButton")
        self.delete_sel_button.pack(side=tk.LEFT, padx=2, pady=2)

        # Close button (Bottom Center)
        close_button = ttk.Button(main_frame, text="Close", command=self.destroy)
        close_button.pack(pady=10)

        # --- Populate listbox AFTER all widgets are created ---
        self.refresh_listbox() # Now safe to call

    def on_listbox_select(self, event):
        """Updates details and enables/disables buttons based on selection."""
        self.selected_indices = self.entry_listbox.curselection() # Get tuple of selected indices

        if not self.selected_indices:
            self.clear_details()
            self.disable_all_action_buttons()
            return

        if len(self.selected_indices) == 1:
            # Single item selected
            index = self.selected_indices[0]
            try:
                row_data = self.data[index]
                self.detail_ts_var.set(row_data[0])
                self.detail_original_var.set(row_data[1])
                self.detail_renamed_var.set(row_data[2])
                self.detail_url_var.set(row_data[3] or "(none)")
                self.enable_single_action_buttons()
                self.disable_multi_action_buttons()
            except IndexError:
                self.clear_details()
                self.disable_all_action_buttons()
                log_status(logging.ERROR, f"Selected row {index+1} has invalid data.")
                messagebox.showerror("Error", "Selected row has invalid data.", parent=self)
        else:
            # Multiple items selected
            self.clear_details() # Clear details view
            self.detail_original_var.set(f"({len(self.selected_indices)} items selected)") # Indicate multiple selection
            self.disable_single_action_buttons()
            self.enable_multi_action_buttons()

    def clear_details(self):
        self.detail_ts_var.set("")
        self.detail_original_var.set("")
        self.detail_renamed_var.set("")
        self.detail_url_var.set("")

    def disable_all_action_buttons(self):
        self.disable_single_action_buttons()
        self.disable_multi_action_buttons()

    def disable_single_action_buttons(self):
        self.rename_button.config(state=tk.DISABLED)
        self.reupload_button.config(state=tk.DISABLED)
        self.editurl_button.config(state=tk.DISABLED)
        # Keep delete separate as it might apply to single too? No, use multi-delete.
        # self.delete_button.config(state=tk.DISABLED)

    def enable_single_action_buttons(self):
        self.rename_button.config(state=tk.NORMAL)
        can_upload = self.uploads_enabled and self.api_key
        self.reupload_button.config(state=tk.NORMAL if can_upload else tk.DISABLED)
        self.editurl_button.config(state=tk.NORMAL)
        # self.delete_button.config(state=tk.NORMAL)

    def disable_multi_action_buttons(self):
        self.bulk_rename_sel_button.config(state=tk.DISABLED)
        self.bulk_reupload_sel_button.config(state=tk.DISABLED)
        self.delete_sel_button.config(state=tk.DISABLED)

    def enable_multi_action_buttons(self):
        self.bulk_rename_sel_button.config(state=tk.NORMAL)
        can_upload = self.uploads_enabled and self.api_key
        self.bulk_reupload_sel_button.config(state=tk.NORMAL if can_upload else tk.DISABLED)
        self.delete_sel_button.config(state=tk.NORMAL)


    def save_csv_data(self):
        """Saves the current state of self.data back to the CSV file."""
        try:
            with open(self.csv_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(self.header) # Write clean header
                writer.writerows(self.data) # Write updated data
            log_status("SUCCESS", "CSV log updated successfully.")
            logger.info(f"CSV log saved successfully from Edit window.")
            return True
        except (IOError, csv.Error) as e:
            log_status(logging.ERROR, f"Failed to save updated CSV: {e}")
            messagebox.showerror("Save Error", f"Failed to save CSV:\n{e}", parent=self)
            logger.exception("CSV Save Error from Edit Window")
            return False

    def refresh_listbox(self):
        """Clears and repopulates the listbox from self.data."""
        current_selection_indices = self.entry_listbox.curselection() # Remember selection
        self.entry_listbox.delete(0, tk.END)
        for idx, row in enumerate(self.data):
             try:
                 # Display Renamed (Original)
                 display_text = f"{idx+1}: {row[2]} (Orig: {row[1]})"
                 self.entry_listbox.insert(tk.END, display_text)
             except IndexError:
                 self.entry_listbox.insert(tk.END, f"{idx+1}: Error - Malformed Row")

        # Attempt to reselect previously selected items if they still exist
        new_selection = []
        if current_selection_indices:
             max_index = self.entry_listbox.size() - 1
             for index in current_selection_indices:
                  if 0 <= index <= max_index:
                       new_selection.append(index)

        if new_selection:
             for index in new_selection:
                  self.entry_listbox.selection_set(index)
             # Activate and see the first item in the new selection
             self.entry_listbox.activate(new_selection[0])
             self.entry_listbox.see(new_selection[0])
             self.on_listbox_select(None) # Trigger detail update based on new selection
        else:
             self.clear_details()
             self.disable_all_action_buttons()


    # --- Action Methods for Edit Window ---

    def action_rename(self):
        # This action only makes sense for a single selection
        if not self.selected_indices or len(self.selected_indices) != 1:
             messagebox.showwarning("Action Error", "Please select exactly one item to rename.", parent=self)
             return
        idx = self.selected_indices[0] # Get the single selected index

        current_renamed_name = self.data[idx][2]
        _, ext = os.path.splitext(current_renamed_name)

        new_name_base = simpledialog.askstring("Change Renamed File",
                                               f"Enter new base name for:\n'{current_renamed_name}'",
                                               parent=self)
        if not new_name_base: return # User cancelled

        new_renamed_name = f"{new_name_base}{ext}"
        old_export_path = os.path.join(self.export_path_base, current_renamed_name)
        new_export_path = os.path.join(self.export_path_base, new_renamed_name)

        if new_renamed_name != current_renamed_name and os.path.exists(new_export_path):
            messagebox.showerror("Error", f"File '{new_renamed_name}' already exists.", parent=self)
            return

        # Rename local file
        renamed_locally = False
        if os.path.exists(old_export_path):
            if new_renamed_name != current_renamed_name:
                try:
                    os.rename(old_export_path, new_export_path)
                    log_status("SUCCESS", f"Renamed local file to '{new_renamed_name}'")
                    renamed_locally = True
                except OSError as e:
                    log_status(logging.ERROR, f"Failed to rename local file: {e}")
                    messagebox.showerror("Error", f"Failed to rename local file:\n{e}", parent=self)
                    return
            else:
                log_status(logging.INFO,"New name is same as old, skipping local file rename.")
                renamed_locally = True
        else:
            log_status(logging.WARNING, f"Original file '{current_renamed_name}' not found in export folder.")
            renamed_locally = True # Allow CSV update

        # Optionally re-upload
        new_url = "" if not self.uploads_enabled else self.data[idx][3] # Default
        if renamed_locally and self.uploads_enabled:
            if messagebox.askyesno("Re-upload?", f"File renamed to '{new_renamed_name}'.\nRe-upload to s-ul.eu?", parent=self):
                if not self.api_key: messagebox.showerror("Error", "API Key missing.", parent=self)
                elif not os.path.exists(new_export_path): messagebox.showerror("Error", f"File not found: {new_export_path}", parent=self)
                else:
                    # Run upload in thread to avoid blocking edit window
                    upload_q = queue.Queue()
                    log_status(logging.INFO, f"Starting re-upload for {new_renamed_name}...")
                    thread = threading.Thread(target=upload_to_sul_thread, args=(new_export_path, self.api_key, upload_q), daemon=True)
                    thread.start()
                    # Simple wait mechanism (could be improved with progress bar)
                    self.master.config(cursor="watch") # Use master (main window) cursor
                    while thread.is_alive():
                        self.master.update()
                        time.sleep(0.1)
                    self.master.config(cursor="")
                    try:
                        result = upload_q.get_nowait()
                        if result["url"]: new_url = result["url"]
                        else: messagebox.showerror("Upload Failed", result["error"] or "Unknown upload error.", parent=self)
                    except queue.Empty:
                         messagebox.showerror("Upload Failed", "No result from upload thread.", parent=self)
            else:
                 new_url = self.data[idx][3] # Keep old URL

        # Update data and save
        self.data[idx][2] = new_renamed_name
        self.data[idx][3] = str(new_url)
        self.data[idx][0] = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
        if self.save_csv_data():
             self.refresh_listbox() # Refresh list display

    def action_reupload(self):
        # This action only makes sense for a single selection
        if not self.selected_indices or len(self.selected_indices) != 1:
             messagebox.showwarning("Action Error", "Please select exactly one item to re-upload.", parent=self)
             return
        idx = self.selected_indices[0]

        if not self.uploads_enabled or not self.api_key:
             messagebox.showerror("Error", "Uploads disabled or API Key missing.", parent=self)
             return

        renamed_name = self.data[idx][2]
        file_path = os.path.join(self.export_path_base, renamed_name)
        if not os.path.exists(file_path):
             messagebox.showerror("Error", f"File not found: {file_path}", parent=self)
             return

        # Run upload in thread
        upload_q = queue.Queue()
        log_status(logging.INFO, f"Starting re-upload for {renamed_name}...")
        thread = threading.Thread(target=upload_to_sul_thread, args=(file_path, self.api_key, upload_q), daemon=True)
        thread.start()
        self.master.config(cursor="watch") # Use master (main window) cursor
        while thread.is_alive():
            self.master.update()
            time.sleep(0.1)
        self.master.config(cursor="")
        try:
            result = upload_q.get_nowait()
            if result["url"]:
                # Update self.data before saving
                self.data[idx][3] = result["url"]
                self.data[idx][0] = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
                if self.save_csv_data():
                    self.refresh_listbox() # Refresh list display
            else:
                messagebox.showerror("Upload Failed", result["error"] or "Unknown upload error.", parent=self)
        except queue.Empty:
             messagebox.showerror("Upload Failed", "No result from upload thread.", parent=self)


    def action_edit_url(self):
        # This action only makes sense for a single selection
        if not self.selected_indices or len(self.selected_indices) != 1:
             messagebox.showwarning("Action Error", "Please select exactly one item to edit its URL.", parent=self)
             return
        idx = self.selected_indices[0]

        current_url = self.data[idx][3]
        new_url = simpledialog.askstring("Edit URL", "Enter new URL (blank to remove):",
                                         initialvalue=current_url, parent=self)
        if new_url is None: return # User cancelled

        self.data[idx][3] = new_url.strip()
        self.data[idx][0] = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
        if self.save_csv_data():
             self.refresh_listbox() # Refresh list display

    def action_delete_selected(self):
        """Deletes all currently selected entries."""
        selected_indices = self.entry_listbox.curselection()
        if not selected_indices:
             messagebox.showwarning("Action Error", "Please select one or more items to delete.", parent=self)
             return

        count = len(selected_indices)
        if not messagebox.askyesno("Confirm Delete", f"Delete {count} selected entries from CSV?", icon='warning', parent=self):
            return

        delete_files = messagebox.askyesno("Delete Files?", "Also delete corresponding local files (Import/Export)?", icon='question', parent=self)

        # Important: Delete from the end of the list to avoid index shifting issues
        indices_to_delete = sorted(list(selected_indices), reverse=True)
        deleted_count_files = 0
        deleted_rows = 0

        for idx in indices_to_delete:
            try:
                renamed_name = self.data[idx][2]
                original_name = self.data[idx][1]

                # Delete local files if requested
                if delete_files:
                    files_to_delete_paths = []
                    if renamed_name: files_to_delete_paths.append(os.path.join(self.export_path_base, renamed_name))
                    if original_name: files_to_delete_paths.append(os.path.join(self.import_path_base, original_name))

                    for file_path in files_to_delete_paths:
                         if os.path.exists(file_path):
                             try:
                                 os.remove(file_path)
                                 log_status("SUCCESS", f"Deleted local file: {file_path}")
                                 deleted_count_files += 1
                             except OSError as e:
                                 log_status(logging.ERROR, f"Failed to delete local file {file_path}: {e}")
                                 messagebox.showerror("File Delete Error", f"Failed to delete:\n{file_path}\n{e}", parent=self)
                         else:
                              logger.info(f"Local file not found for deletion, skipping: {file_path}")

                # Remove row from data list
                self.data.pop(idx)
                deleted_rows += 1
                logger.info(f"Removed item #{idx+1} ('{renamed_name}') from data list.")

            except IndexError:
                 log_status(logging.ERROR, f"Error processing index {idx} for deletion (index out of bounds?).")
            except Exception as e:
                 log_status(logging.ERROR, f"Unexpected error during deletion of item at index {idx}: {e}")
                 logger.exception(f"Deletion error for index {idx}")

        # Save the modified data list back to CSV
        if deleted_rows > 0:
            if self.save_csv_data():
                self.refresh_listbox() # Refresh list display
            log_status("SUCCESS", f"Deleted {deleted_rows} entries from CSV.")
            if delete_files:
                 log_status("INFO", f"Deleted {deleted_count_files} associated local files.")
        else:
             log_status(logging.WARNING, "No rows were actually deleted.")


    def action_reupload_selected(self):
        """Re-uploads all selected items that have a file in export folder."""
        selected_indices = self.entry_listbox.curselection()
        if not selected_indices:
             messagebox.showwarning("Action Error", "Please select one or more items to re-upload.", parent=self)
             return

        if not self.uploads_enabled or not self.api_key:
             messagebox.showerror("Error", "Uploads disabled or API Key missing.", parent=self)
             return

        items_to_upload = []
        for idx in selected_indices:
             try:
                 renamed_name = self.data[idx][2]
                 file_path = os.path.join(self.export_path_base, renamed_name)
                 if os.path.exists(file_path):
                      items_to_upload.append({"index": idx, "file_path": file_path, "renamed_name": renamed_name})
                 else:
                      log_status(logging.WARNING, f"Skipping re-upload for '{renamed_name}': File not found.")
             except IndexError:
                  log_status(logging.ERROR, f"Skipping re-upload for index {idx}: Invalid row data.")

        if not items_to_upload:
             messagebox.showinfo("Re-upload", "No valid files found for selected entries to re-upload.", parent=self)
             return

        log_status(logging.INFO, f"Starting re-upload for {len(items_to_upload)} selected items...")

        # Upload in threads
        upload_queue = queue.Queue()
        threads = []
        for item in items_to_upload:
            thread = threading.Thread(target=upload_to_sul_thread,
                                      args=(item["file_path"], self.api_key, upload_queue),
                                      daemon=True)
            threads.append(thread)
            thread.start()

        # Monitor results
        total_files = len(threads)
        completed_files = 0
        successful_uploads = 0
        failed_uploads = 0
        updated_indices = []

        while completed_files < total_files:
            try:
                result = upload_queue.get(timeout=1.0)
                completed_files += 1
                original_index = -1
                for item in items_to_upload:
                     if item["renamed_name"] == result["file"]:
                          original_index = item["index"]
                          break

                if original_index != -1:
                    if result["url"]:
                        successful_uploads += 1
                        self.data[original_index][3] = result["url"]
                        self.data[original_index][0] = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
                        updated_indices.append(original_index)
                    else:
                        failed_uploads += 1
                        log_status(logging.ERROR, f"Re-upload Failed for {result['file']}: {result['error']}")
                else:
                     log_status(logging.ERROR, f"Could not map result file {result['file']} back to index.")
                     failed_uploads += 1
                log_status(logging.INFO, f"Re-upload progress: {completed_files}/{total_files}")

            except queue.Empty:
                if not any(t.is_alive() for t in threads): break
                continue

        # Save CSV if changes were made
        if updated_indices:
            log_status(logging.INFO, "Saving updated URLs after re-upload...")
            if self.save_csv_data():
                 self.refresh_listbox() # Refresh list display

        log_status(logging.INFO, f"Re-upload finished. Successful: {successful_uploads}, Failed: {failed_uploads}.")
        messagebox.showinfo("Re-upload Complete", f"Re-upload Finished.\nSuccessful: {successful_uploads}\nFailed: {failed_uploads}", parent=self)

    def action_bulk_rename_selected(self):
        """Bulk renames selected items sequentially."""
        selected_indices = self.entry_listbox.curselection()
        if not selected_indices:
             messagebox.showwarning("Action Error", "Please select two or more items to bulk rename.", parent=self)
             return

        base_name = simpledialog.askstring("Bulk Rename Selected", "Enter base name (e.g., IMAGE):", parent=self)
        if not base_name:
            log_status(logging.INFO, "Bulk rename selected cancelled (no base name).")
            return

        log_status(logging.INFO, f"Starting bulk rename for {len(selected_indices)} selected items with base '{base_name}'...")

        items_to_rename = []
        for idx in selected_indices:
             try:
                 items_to_rename.append({"index": idx, "old_name": self.data[idx][2]})
             except IndexError:
                  log_status(logging.ERROR, f"Skipping index {idx} in bulk rename: Invalid row data.")

        if not items_to_rename:
             messagebox.showerror("Error", "No valid items selected for renaming.", parent=self)
             return

        # Sort by original index to maintain some order if desired, though numbering is sequential
        items_to_rename.sort(key=lambda x: x["index"])

        start_number = 1
        num_digits = len(str(len(items_to_rename) + start_number - 1))
        renamed_count = 0
        error_count = 0
        skipped_count = 0
        temp_files = {}
        potential_renames = []
        target_filenames = set()
        valid_process = True

        # Pass 1: Generate new names and check conflicts
        for i, item in enumerate(items_to_rename):
            old_name = item["old_name"]
            _, ext = os.path.splitext(old_name)
            ext = ext if ext else ""
            new_filename_base = f"{base_name}{i + start_number:0{num_digits}d}"
            new_filename = f"{new_filename_base}{ext}"

            if new_filename in target_filenames:
                 log_status(logging.ERROR, f"Conflict: Multiple selected items target '{new_filename}'. Aborting.")
                 messagebox.showerror("Error", f"Conflict detected: Multiple items would be renamed to '{new_filename}'. Aborting.", parent=self)
                 valid_process = False
                 break
            target_filenames.add(new_filename)
            item["new_name"] = new_filename
            item["old_path"] = os.path.join(self.export_path_base, old_name)
            item["new_path"] = os.path.join(self.export_path_base, new_filename)
            potential_renames.append(item)

        if not valid_process: return

        # Pass 2 & 3: Perform renames (similar logic to run_bulk_rename_existing_thread)
        # This part runs synchronously within the EditWindow for simplicity,
        # could be threaded if dealing with huge selections.
        rename_log_list = []
        for rename_info in potential_renames:
            old_path, new_path = rename_info["old_path"], rename_info["new_path"]
            old_name, new_name = rename_info["old_name"], rename_info["new_name"]
            item_index = rename_info["index"]

            if not os.path.exists(old_path):
                log_status(logging.WARNING, f"Skipping '{old_name}': File not found.")
                skipped_count += 1
                continue
            if old_path == new_path:
                log_status(logging.INFO, f"Skipping '{old_name}': Name already correct.")
                continue

            temp_path = None
            if os.path.exists(new_path):
                temp_suffix = f"__bulk_rename_temp_{datetime.now().strftime('%f')}"
                temp_path = old_path + temp_suffix
                try:
                    os.rename(old_path, temp_path)
                    temp_files[new_path] = temp_path
                    rename_info["status"] = "pending_temp"
                except OSError as e:
                    log_status(logging.ERROR, f"Failed to rename '{old_name}' to temp path: {e}")
                    error_count += 1; rename_info["status"] = "error"; continue
            else:
                try:
                    os.rename(old_path, new_path)
                    rename_log_list.append(f"'{old_name}' -> '{new_name}'")
                    renamed_count += 1; rename_info["status"] = "renamed"
                except OSError as e:
                    log_status(logging.ERROR, f"Failed to rename '{old_name}' to '{new_name}': {e}")
                    error_count += 1; rename_info["status"] = "error"; continue

            # Update main data list immediately if rename started
            self.data[item_index][2] = new_name
            self.data[item_index][0] = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")

        # Pass 3: Rename temporary files
        temp_rename_errors = 0
        for final_target_path, temp_source_path in temp_files.items():
            try:
                os.rename(temp_source_path, final_target_path)
                temp_base = os.path.basename(temp_source_path)
                final_base = os.path.basename(final_target_path)
                rename_log_list.append(f"'{temp_base}' (temp) -> '{final_base}'")
                for info in potential_renames:
                     if info.get("status") == "pending_temp" and info["new_path"] == final_target_path:
                          info["status"] = "renamed"; renamed_count += 1; break
            except OSError as e:
                log_status(logging.ERROR, f"Failed to rename temp file '{temp_source_path}' to '{final_target_path}': {e}")
                temp_rename_errors += 1; error_count += 1
                for info in potential_renames:
                     if info.get("status") == "pending_temp" and info["new_path"] == final_target_path:
                          self.data[info["index"]][2] = info["old_name"]; break # Revert name

        # Save CSV
        if renamed_count > 0 or error_count > 0:
            if self.save_csv_data():
                 self.refresh_listbox()

        log_status("PRINT", f"\n--- Bulk Rename Selected Summary ---")
        log_status("SUCCESS", f"Successfully Renamed: {renamed_count}")
        if skipped_count > 0: log_status("WARNING", f"Skipped: {skipped_count}")
        if error_count > 0: log_status("ERROR", f"Errors: {error_count}")
        messagebox.showinfo("Bulk Rename Complete", f"Renamed: {renamed_count}\nSkipped: {skipped_count}\nErrors: {error_count}", parent=self)


# --- Bulk Rename Existing Items Function (Threaded & Implemented) ---
def run_bulk_rename_existing_thread(config):
    """Worker thread for bulk renaming existing CSV items."""
    log_status(logging.INFO, "Starting Bulk Rename Existing Items process (Thread).")
    base_dir = config.get("base_dir")
    export_path_base = os.path.join(base_dir, EXPORT_FOLDER)
    csv_path = os.path.join(base_dir, CSV_FILENAME)

    header_clean, data = get_csv_data(csv_path) # Get clean data
    if header_clean is None or not data:
        log_status(logging.ERROR if header_clean is None else logging.INFO,
                   "Bulk Rename: Could not read CSV or no entries found.")
        return

    # --- Get base name via queue/callback ---
    base_name_queue = queue.Queue()
    def ask_base_name():
         # Need to ensure the main window instance is accessible
         if UploaderApp.instance and UploaderApp.instance.root:
              name = simpledialog.askstring("Bulk Rename Base Name", "Enter base name (e.g., IMAGE):", parent=UploaderApp.instance.root)
              base_name_queue.put(name)
         else:
              log_status(logging.ERROR, "Cannot ask for base name: Main window not accessible.")
              base_name_queue.put(None) # Signal error

    # Schedule the dialog in the main thread
    if UploaderApp.instance and UploaderApp.instance.root:
        UploaderApp.instance.root.after(0, ask_base_name)
        base_name = base_name_queue.get() # Wait for the result from the main thread
    else:
        base_name = None # Cannot ask

    if not base_name:
        log_status(logging.WARNING, "Bulk Rename cancelled by user or failed to get base name.")
        return
    # --- End Get base name ---

    start_number = 1
    num_digits = len(str(len(data) + start_number - 1))
    log_status(logging.INFO, f"Bulk renaming {len(data)} items using base '{base_name}' starting from {start_number:0{num_digits}d}...")

    renamed_count = 0
    skipped_count = 0
    error_count = 0
    temp_export_files = {}
    potential_renames = []
    target_filenames = set()
    valid_process = True

    # Define column indices
    try:
        ts_idx, orig_idx, renamed_idx, url_idx = 0, 1, 2, 3
        if not (header_clean[ts_idx] == "Timestamp" and header_clean[orig_idx] == "Original" and
                header_clean[renamed_idx] == "Renamed" and header_clean[url_idx] == "URL"):
            raise ValueError("CSV header mismatch")
    except (IndexError, ValueError):
        log_status(logging.ERROR,"Bulk rename aborted: CSV header mismatch.")
        return

    # Pass 1: Check for conflicts
    for i, row in enumerate(data):
        try:
            old_renamed_name = row[renamed_idx]
            _, ext = os.path.splitext(old_renamed_name)
            ext = ext if ext else ""
            new_filename_base = f"{base_name}{i + start_number:0{num_digits}d}"
            new_filename = f"{new_filename_base}{ext}"

            if new_filename in target_filenames:
                 log_status(logging.ERROR, f"Conflict detected: Multiple items would be renamed to '{new_filename}'. Aborting.")
                 valid_process = False
                 break
            target_filenames.add(new_filename)
            potential_renames.append({
                "index": i, "old_name": old_renamed_name, "new_name": new_filename,
                "old_path": os.path.join(export_path_base, old_renamed_name),
                "new_path": os.path.join(export_path_base, new_filename)
            })
        except IndexError:
            log_status(logging.ERROR, f"Skipping row {i+1} due to incorrect column count.")
            skipped_count += 1

    if not valid_process: return

    # Pass 2: Perform initial renames (use temp if target exists)
    final_data = [list(row) for row in data] # Mutable copy
    rename_log = []
    for rename_info in potential_renames:
        old_path, new_path = rename_info["old_path"], rename_info["new_path"]
        old_name, new_name = rename_info["old_name"], rename_info["new_name"]
        item_index = rename_info["index"]

        if not os.path.exists(old_path):
            log_status(logging.WARNING, f"Skipping '{old_name}': File not found.")
            skipped_count += 1
            continue
        if old_path == new_path:
            log_status(logging.INFO, f"Skipping '{old_name}': Name already correct.")
            continue

        temp_path = None
        if os.path.exists(new_path):
            temp_suffix = f"__bulk_rename_temp_{datetime.now().strftime('%f')}"
            temp_path = old_path + temp_suffix
            try:
                os.rename(old_path, temp_path)
                logger.info(f"Renamed '{old_name}' to temporary '{os.path.basename(temp_path)}'.")
                temp_export_files[new_path] = temp_path
                rename_info["status"] = "pending_temp"
            except OSError as e:
                log_status(logging.ERROR, f"Failed to rename '{old_name}' to temp path: {e}")
                error_count += 1
                rename_info["status"] = "error"
                continue
        else:
            try:
                os.rename(old_path, new_path)
                rename_log.append(f"'{old_name}' -> '{new_name}'")
                logger.info(f"Bulk rename: Renamed '{old_name}' to '{new_name}'.")
                renamed_count += 1
                rename_info["status"] = "renamed"
            except OSError as e:
                log_status(logging.ERROR, f"Failed to rename '{old_name}' to '{new_name}': {e}")
                error_count += 1
                rename_info["status"] = "error"
                continue

        # Update final_data only if rename (direct or temp) was initiated
        final_data[item_index][renamed_idx] = new_name
        final_data[item_index][ts_idx] = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")

    # Pass 3: Rename temporary files
    temp_rename_errors = 0
    for final_target_path, temp_source_path in temp_export_files.items():
        try:
            os.rename(temp_source_path, final_target_path)
            temp_base = os.path.basename(temp_source_path)
            final_base = os.path.basename(final_target_path)
            rename_log.append(f"'{temp_base}' (temp) -> '{final_base}'")
            logger.info(f"Bulk rename: Finalized '{final_base}'.")
            # Update status from pending_temp to renamed
            for info in potential_renames:
                if info.get("status") == "pending_temp" and info["new_path"] == final_target_path:
                    info["status"] = "renamed"
                    renamed_count += 1
                    break
        except OSError as e:
            log_status(logging.ERROR, f"Failed to rename temp file '{temp_source_path}' to '{final_target_path}': {e}")
            temp_rename_errors += 1
            error_count += 1
            # Revert name in final_data if temp rename failed
            for info in potential_renames:
                if info.get("status") == "pending_temp" and info["new_path"] == final_target_path:
                    final_data[info["index"]][renamed_idx] = info["old_name"]
                    break

    # Save final data
    if renamed_count > 0 or skipped_count > 0 or error_count > 0:
        log_status(logging.INFO, "Saving updated names to CSV...")
        try:
            with open(csv_path, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.writer(csvfile)
                writer.writerow(header_clean)
                writer.writerows(final_data)
            log_status("SUCCESS", "CSV log updated successfully.")
        except (IOError, csv.Error) as e:
            log_status(logging.ERROR, f"Failed to save updated CSV after bulk rename: {e}")

    # Summary
    log_status("PRINT", "\n--- Bulk Rename Summary ---")
    log_status("PRINT", f"Total CSV Entries Processed: {len(data)}")
    log_status("SUCCESS", f"Files Successfully Renamed: {renamed_count}")
    if skipped_count > 0: log_status("WARNING", f"Files Skipped: {skipped_count}")
    if error_count > 0: log_status("ERROR", f"Errors During Rename: {error_count}")
    logger.info(f"Bulk Rename Existing summary: Total={len(data)}, Renamed={renamed_count}, Skipped={skipped_count}, Errors={error_count}")


# --- Bulk Upload Function ---
def bulk_upload_from_csv_thread(config):
    """Worker thread for bulk uploading existing CSV items."""
    log_status(logging.INFO, "Starting Bulk Upload Existing Items process (Thread).")
    base_dir = config.get("base_dir")
    api_key = config.get("api_key")
    uploads_enabled = str(config.get('enable_upload', 'true')).lower() == 'true'
    csv_path = os.path.join(base_dir, CSV_FILENAME)
    export_path_base = os.path.join(base_dir, EXPORT_FOLDER)

    if not uploads_enabled or not api_key:
        log_status(logging.WARNING, "Bulk Upload skipped: Uploads disabled or API Key missing.")
        return

    header, data = get_csv_data(csv_path)
    if header is None or not data:
        log_status(logging.ERROR if header is None else logging.INFO,
                   "Bulk Upload: Could not read CSV or no entries found.")
        return

    log_status(logging.INFO, f"Bulk Upload: Found {len(data)} entries. Checking files...")

    items_to_upload = []
    try:
        ts_idx, orig_idx, renamed_idx, url_idx = 0, 1, 2, 3
        if not (header[ts_idx] == "Timestamp" and header[orig_idx] == "Original" and
                header[renamed_idx] == "Renamed" and header[url_idx] == "URL"):
            raise ValueError("CSV header mismatch")

        for idx, row in enumerate(data):
            renamed_name = row[renamed_idx]
            current_url = row[url_idx]
            file_path = os.path.join(export_path_base, renamed_name)
            if not current_url and os.path.exists(file_path):
                items_to_upload.append({"index": idx, "file_path": file_path, "renamed_name": renamed_name})
            elif current_url:
                 logger.info(f"Bulk Upload: Skipping '{renamed_name}' (already has URL).")
            elif not os.path.exists(file_path):
                 log_status(logging.WARNING, f"Bulk Upload: Skipping '{renamed_name}' (file not found).")

    except (IndexError, ValueError) as e:
        log_status(logging.ERROR, f"Bulk Upload aborted: CSV header mismatch or row error: {e}")
        return

    if not items_to_upload:
        log_status(logging.INFO, "Bulk Upload: No items found needing upload.")
        return

    log_status(logging.INFO, f"Bulk Upload: Starting upload for {len(items_to_upload)} items...")

    # Upload in threads
    upload_queue = queue.Queue()
    threads = []
    for item in items_to_upload:
        thread = threading.Thread(target=upload_to_sul_thread,
                                  args=(item["file_path"], api_key, upload_queue),
                                  daemon=True)
        threads.append(thread)
        thread.start()

    # Monitor results
    total_files = len(threads)
    completed_files = 0
    successful_uploads = 0
    failed_uploads = 0
    updated_indices = [] # Track indices in original 'data' that were updated

    while completed_files < total_files:
        try:
            result = upload_queue.get(timeout=1.0) # Wait up to 1 sec for a result
            completed_files += 1
            # Find original index
            original_index = -1
            for item in items_to_upload:
                 if item["renamed_name"] == result["file"]:
                      original_index = item["index"]
                      break

            if original_index != -1:
                if result["url"]:
                    successful_uploads += 1
                    data[original_index][3] = result["url"] # Update URL in main data list
                    data[original_index][0] = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f") # Update timestamp
                    updated_indices.append(original_index)
                else:
                    failed_uploads += 1
                    log_status(logging.ERROR, f"Bulk Upload: Failed for {result['file']}: {result['error']}")
            else:
                 log_status(logging.ERROR, f"Bulk Upload: Could not find original index for uploaded file {result['file']}")
                 failed_uploads +=1 # Count as failed if we can't map it back

            log_status(logging.INFO, f"Bulk Upload progress: {completed_files}/{total_files}")

        except queue.Empty:
            # Check if threads are still running
            if not any(t.is_alive() for t in threads):
                log_status(logging.WARNING, "Bulk Upload: Upload queue empty but threads finished unexpectedly.")
                break # Exit if threads died
            continue # Continue waiting if threads are alive

    # Save CSV if changes were made
    if updated_indices:
        log_status(logging.INFO, "Bulk Upload: Saving updated CSV...")
        try:
            with open(csv_path, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.writer(csvfile)
                writer.writerow(header)
                writer.writerows(data)
            log_status("SUCCESS", "Bulk Upload: CSV log updated successfully.")
        except (IOError, csv.Error) as e:
            log_status(logging.ERROR, f"Bulk Upload: Failed to save updated CSV: {e}")
            logger.exception("Bulk Upload CSV Save Error")

    log_status(logging.INFO, f"Bulk Upload finished. Successful: {successful_uploads}, Failed: {failed_uploads}.")
    messagebox.showinfo("Bulk Upload Complete", f"Bulk Upload Finished.\nSuccessful: {successful_uploads}\nFailed: {failed_uploads}")


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
        UploaderApp.instance = UploaderApp(root)
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
        input("Critical error occurred. Press Enter to exit.")
    finally:
        try:
            logger.info("="*30 + " Script Execution Finished " + "="*30 + "\n")
            for handler in logger.handlers[:]:
                try:
                    handler.close()
                    logger.removeHandler(handler)
                except Exception: pass
        except Exception: pass
        if colorama:
            try: colorama.deinit()
            except Exception: pass


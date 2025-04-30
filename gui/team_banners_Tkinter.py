#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# GUI Version of the Google Drive to S-UL Uploader Script using Tkinter (Layout v5)

## Install required libraries:
# pip install requests gdown configparser colorama Pillow pyperclip

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
from tkinter import simpledialog
from tkinter import filedialog
try:
    # Check if Pillow is available and functional
    from PIL import Image, ImageTk, UnidentifiedImageError
    # Attempt a basic operation to catch potential deeper issues early
    try:
        Image.new('RGB', (1, 1))
        PIL_AVAILABLE = True
    except Exception as pil_err:
        print(f"WARNING: Pillow installed but failed basic test ({pil_err}). Image preview disabled.")
        PIL_AVAILABLE = False
except ImportError:
    PIL_AVAILABLE = False
    # Use print for startup warnings as GUI/logging might not be ready
    print("WARNING: Pillow library not found. Image preview will be disabled.")
    print("Install with: pip install Pillow")
try:
    import pyperclip # For copying CSV data
    PYPERCLIP_AVAILABLE = True
except ImportError:
    PYPERCLIP_AVAILABLE = False
    print("WARNING: pyperclip library not found. 'Copy CSV' button will be disabled.")
    print("Install with: pip install pyperclip")


# --- Globals & Constants ---
CONFIG_FILE = "settings.conf"
IMPORT_FOLDER = "Images import"
EXPORT_FOLDER = "Images export"
CSV_FILENAME = "index.csv"
LOG_FILENAME = "script_activity.log"
PREVIEW_MAX_WIDTH = 250
PREVIEW_MAX_HEIGHT = 250

# --- ANSI Color Code Definitions (Used only for stripping in logs) ---
# These are kept for stripping potential color codes from external sources if needed
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
            # Define tags for colors
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

# --- Configuration Handling ---

def load_config_gui():
    """Loads config or sets defaults if file missing/invalid. Returns config dict."""
    global app_config, base_dir_path
    config_parser = configparser.ConfigParser()
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
    else: print(f"INFO: Config file '{config_file_path}' not found. Using defaults.")

    loaded_base_dir = defaults['base_dir']
    if not os.path.isdir(loaded_base_dir):
        print(f"WARNING: Base directory '{loaded_base_dir}' invalid. Resetting to script directory.")
        loaded_base_dir = os.path.dirname(os.path.abspath(__file__))
        defaults['base_dir'] = loaded_base_dir
    base_dir_path = loaded_base_dir

    setup_file_logging(base_dir_path, defaults['enable_logging'])
    logger.info("Configuration loaded/defaults applied.")
    app_config = defaults
    return app_config

def save_config_gui(show_success_popup=False):
    """Saves the current app_config to the config file."""
    global app_config
    config_parser = configparser.ConfigParser()
    config_to_save = {k: str(v) for k, v in app_config.items()}
    config_parser['DEFAULT'] = config_to_save
    config_file_path = os.path.join(app_config.get('base_dir', base_dir_path), CONFIG_FILE)

    try:
        with open(config_file_path, 'w', encoding='utf-8') as configfile:
            config_parser.write(configfile)
        log_status("SUCCESS", f"Configuration saved to '{config_file_path}'.")
        logger.info(f"Configuration saved to '{config_file_path}'.")
        base_dir = app_config.get('base_dir', '.')
        os.makedirs(os.path.join(base_dir, IMPORT_FOLDER), exist_ok=True)
        os.makedirs(os.path.join(base_dir, EXPORT_FOLDER), exist_ok=True)
        if show_success_popup: messagebox.showinfo("Config Saved", "Configuration saved successfully.")
        return True
    except IOError as e:
        log_status(logging.ERROR, f"Could not save config file: {e}")
        messagebox.showerror("Config Save Error", f"Could not save config file:\n{e}")
        return False
    except Exception as e:
         log_status(logging.ERROR, f"Unexpected error saving config: {e}")
         messagebox.showerror("Config Save Error", f"An unexpected error occurred:\n{e}")
         return False

# --- Core Logic Functions ---

def read_uploaded_originals(csv_path):
    """Reads original filenames (column 2) from the CSV log."""
    originals = set()
    if not os.path.exists(csv_path):
        logger.info(f"CSV file '{csv_path}' not found. Assuming no previously logged files.")
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
        # Use root.after to schedule the callback in the main GUI thread
        if UploaderApp.instance and UploaderApp.instance.root:
             UploaderApp.instance.root.after(0, lambda: callback(files_to_process, error_message))
        else:
             logger.error("Cannot execute callback: Main GUI window not found.")


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


# --- Main GUI Application Class ---

class UploaderApp:
    instance = None # Class variable to hold the single instance

    def __init__(self, root):
        if UploaderApp.instance is not None:
             raise Exception("Only one instance of UploaderApp can exist!")
        UploaderApp.instance = self

        self.root = root
        self.root.title("Google Drive to S-UL Uploader")
        # Set new default size
        self.root.geometry("950x650") # Wider
        self.root.columnconfigure(0, weight=1) # Allow main frame to expand
        self.root.rowconfigure(0, weight=1)

        # Load initial configuration
        global app_config
        app_config = load_config_gui() # Call the corrected function name

        # --- Variables for GUI elements ---
        self.drive_id_var = tk.StringVar(value=app_config.get('drive_id', ''))
        self.api_key_var = tk.StringVar(value=app_config.get('api_key', ''))
        self.base_dir_var = tk.StringVar(value=app_config.get('base_dir', ''))
        self.enable_logging_var = tk.BooleanVar(value=str(app_config.get('enable_logging', 'true')).lower() == 'true')
        self.enable_upload_var = tk.BooleanVar(value=str(app_config.get('enable_upload', 'true')).lower() == 'true')
        # GUI doesn't use console colors, but keep var for config consistency
        self.enable_colors_var = tk.BooleanVar(value=str(app_config.get('enable_colors', 'true')).lower() == 'true')

        # --- Stats Variables ---
        self.total_entries_var = tk.StringVar(value="Total Entries: N/A")
        self.import_files_var = tk.StringVar(value="Import Files Found: N/A")
        self.export_files_var = tk.StringVar(value="Export Files Found: N/A")
        self.url_entries_var = tk.StringVar(value="Entries with URL: N/A")
        self.import_status_var = tk.StringVar(value="?")
        self.export_status_var = tk.StringVar(value="?")
        self.url_status_var = tk.StringVar(value="?")

        # --- Build GUI ---
        self.create_widgets()
        self.update_widget_states() # Initial state update
        self.update_stats() # Initial stats update

        # Start the status display updater
        self.status_text.after(100, lambda: update_status_display(self.status_text))
        log_status(logging.INFO, "Application initialized.")

    def run_problem_fixer_script(self):
        """Launches the problem_fixer.py script as a separate process."""
        fixer_script_name = "problem_solver.py"
        # Construct the path relative to the main script's directory
        script_dir = os.path.dirname(os.path.abspath(__file__))
        fixer_script_path = os.path.join(script_dir, fixer_script_name)

        if not os.path.exists(fixer_script_path):
            log_status(logging.ERROR, f"Problem Fixer script '{fixer_script_name}' not found in the script directory.")
            messagebox.showerror("Error", f"Could not find the fixer script:\n{fixer_script_path}")
            return

        log_status(logging.INFO, f"Launching Problem Fixer script: {fixer_script_path}")
        try:
            # Use sys.executable to ensure it runs with the same Python interpreter
            # Use Popen for non-blocking execution
            subprocess.Popen([sys.executable, fixer_script_path])
        except Exception as e:
            log_status(logging.ERROR, f"Failed to launch Problem Fixer script: {e}")
            messagebox.showerror("Launch Error", f"Failed to launch the fixer script:\n{e}")
            logger.exception("Problem Fixer launch error")

    # --- GUI Creation Methods ---
    def create_widgets(self):
        # Define consistent padding
        PAD_X = 5
        PAD_Y = 5
        FRAME_PAD = 10 # Padding inside LabelFrames
        INTER_FRAME_PADX = (0, 5) # Pad between left and right frames
        INTER_FRAME_PADY = (0, 5) # Pad between top and bottom frames

        # Main frame using grid
        main_frame = ttk.Frame(self.root, padding=FRAME_PAD)
        main_frame.grid(row=0, column=0, sticky="nsew")
        # Make main_frame's container (the root window) expandable
        # Ensure these lines are run *outside* create_widgets, maybe in __init__ after root creation:
        # self.root.columnconfigure(0, weight=1)
        # self.root.rowconfigure(0, weight=1)
        # It's okay if they are here too, but logically belong in __init__

        # Configure grid weights for the 2x2 layout within main_frame
        main_frame.columnconfigure(0, weight=2, minsize=420) # Config/Actions column
        main_frame.columnconfigure(1, weight=3)             # Stats/Status column
        main_frame.rowconfigure(0, weight=0)                # Config/Stats row (fixed height)
        main_frame.rowconfigure(1, weight=1)                # Actions/Status row (expandable)

        # --- Configuration Frame (Top-Left) ---
        config_frame = ttk.LabelFrame(main_frame, text="Configuration", padding=FRAME_PAD)
        config_frame.grid(row=0, column=0, padx=INTER_FRAME_PADX, pady=INTER_FRAME_PADY, sticky="nsew")
        config_frame.columnconfigure(1, weight=1) # Make entry fields expand

        ttk.Label(config_frame, text="Google Drive ID/URL:").grid(row=0, column=0, padx=PAD_X, pady=PAD_Y, sticky=tk.W)
        drive_entry = ttk.Entry(config_frame, textvariable=self.drive_id_var, width=40)
        drive_entry.grid(row=0, column=1, columnspan=2, padx=PAD_X, pady=PAD_Y, sticky=tk.EW)

        ttk.Label(config_frame, text="S-UL API Key:").grid(row=1, column=0, padx=PAD_X, pady=PAD_Y, sticky=tk.W)
        self.api_key_entry = ttk.Entry(config_frame, textvariable=self.api_key_var, width=40, show="*")
        self.api_key_entry.grid(row=1, column=1, columnspan=2, padx=PAD_X, pady=PAD_Y, sticky=tk.EW)

        ttk.Label(config_frame, text="Base Directory:").grid(row=2, column=0, padx=PAD_X, pady=PAD_Y, sticky=tk.W)
        base_dir_entry = ttk.Entry(config_frame, textvariable=self.base_dir_var, width=40)
        base_dir_entry.grid(row=2, column=1, padx=PAD_X, pady=PAD_Y, sticky=tk.EW)
        browse_button = ttk.Button(config_frame, text="Browse...", command=self.browse_base_dir, width=8)
        browse_button.grid(row=2, column=2, padx=PAD_X, pady=PAD_Y, sticky=tk.E)

        # --- Toggles Frame ---
        toggles_frame = ttk.Frame(config_frame)
        toggles_frame.grid(row=3, column=0, columnspan=3, padx=PAD_X, pady=PAD_Y, sticky=tk.W)
        self.log_check = ttk.Checkbutton(toggles_frame, text="Enable Logging", variable=self.enable_logging_var, command=self.toggle_logging)
        self.log_check.pack(side=tk.LEFT, padx=(0, 10))
        self.upload_check = ttk.Checkbutton(toggles_frame, text="Enable Uploads", variable=self.enable_upload_var, command=self.toggle_uploads)
        self.upload_check.pack(side=tk.LEFT)

        # --- Save Config Button ---
        save_button = ttk.Button(config_frame, text="Save Configuration", command=self.save_config_action_with_popup)
        save_button.grid(row=4, column=0, columnspan=3, padx=PAD_X, pady=PAD_Y, sticky=tk.EW)

        # --- Stats Frame (Top-Right) ---
        stats_frame = ttk.LabelFrame(main_frame, text="Stats", padding=FRAME_PAD)
        stats_frame.grid(row=0, column=1, padx=INTER_FRAME_PADX, pady=INTER_FRAME_PADY, sticky="nsew")
        stats_frame.columnconfigure(1, weight=0) # Status indicator column fixed width via Label width
        stats_frame.columnconfigure(2, weight=1) # Text label expands

        ttk.Label(stats_frame, textvariable=self.total_entries_var).grid(row=0, column=0, columnspan=3, sticky=tk.W, padx=PAD_X, pady=PAD_Y)

        ttk.Label(stats_frame, text="Import Files:").grid(row=1, column=0, sticky=tk.W, padx=PAD_X, pady=PAD_Y)
        self.import_status_label = ttk.Label(stats_frame, textvariable=self.import_status_var, width=5, anchor="center", relief="groove", borderwidth=1) # Style like screenshot
        self.import_status_label.grid(row=1, column=1, sticky="ew", padx=PAD_X, pady=PAD_Y) # Let it stretch horizontally slightly
        ttk.Label(stats_frame, textvariable=self.import_files_var).grid(row=1, column=2, sticky=tk.W, padx=PAD_X, pady=PAD_Y)

        ttk.Label(stats_frame, text="Export Files:").grid(row=2, column=0, sticky=tk.W, padx=PAD_X, pady=PAD_Y)
        self.export_status_label = ttk.Label(stats_frame, textvariable=self.export_status_var, width=5, anchor="center", relief="groove", borderwidth=1)
        self.export_status_label.grid(row=2, column=1, sticky="ew", padx=PAD_X, pady=PAD_Y)
        ttk.Label(stats_frame, textvariable=self.export_files_var).grid(row=2, column=2, sticky=tk.W, padx=PAD_X, pady=PAD_Y)

        ttk.Label(stats_frame, text="Upload Status:").grid(row=3, column=0, sticky=tk.W, padx=PAD_X, pady=PAD_Y)
        self.url_status_label = ttk.Label(stats_frame, textvariable=self.url_status_var, width=5, anchor="center", relief="groove", borderwidth=1)
        self.url_status_label.grid(row=3, column=1, sticky="ew", padx=PAD_X, pady=PAD_Y)
        ttk.Label(stats_frame, textvariable=self.url_entries_var).grid(row=3, column=2, sticky=tk.W, padx=PAD_X, pady=PAD_Y)

        refresh_stats_button = ttk.Button(stats_frame, text="Refresh Stats", command=self.update_stats)
        refresh_stats_button.grid(row=4, column=0, columnspan=3, pady=(PAD_Y*2, PAD_Y), padx=PAD_X, sticky=tk.EW)

        # --- Actions Frame (Bottom-Left) ---
        actions_frame = ttk.LabelFrame(main_frame, text="Actions", padding=FRAME_PAD)
        actions_frame.grid(row=1, column=0, padx=INTER_FRAME_PADX, pady=INTER_FRAME_PADY, sticky="nsew")
        # We only need one column in actions_frame now, as each row's frame will span it.
        actions_frame.columnconfigure(0, weight=1)

        # Define padding for buttons inside the row frames
        ROW_INTERNAL_PADY = 2 # Small vertical padding within rows with multiple buttons
        ROW_INTER_BTN_PADX = 2 # Small horizontal padding between buttons within a row

        # Row 0: Start Button (Keep it simple, spans the single column)
        self.start_button = ttk.Button(actions_frame, text="Start Script", command=self.start_script_action)
        self.start_button.grid(row=0, column=0, padx=PAD_X, pady=PAD_Y, sticky=tk.EW) # Uses standard PAD_X/Y

        # --- Row 1: Edit and Fixer Buttons Frame ---
        row1_frame = ttk.Frame(actions_frame)
        row1_frame.grid(row=1, column=0, padx=0, pady=PAD_Y, sticky=tk.EW) # Use PAD_Y for vertical spacing between rows
        row1_frame.columnconfigure(0, weight=1, uniform="actions_buttons_2col") # Uniform group for 2-button rows
        row1_frame.columnconfigure(1, weight=1, uniform="actions_buttons_2col")

        self.edit_button = ttk.Button(row1_frame, text="Edit CSV Entry", command=self.edit_entry_action)
        self.edit_button.grid(row=0, column=0, padx=(PAD_X, ROW_INTER_BTN_PADX), pady=ROW_INTERNAL_PADY, sticky=tk.EW) # Pad outside left, between right
        self.fixer_button = ttk.Button(row1_frame, text="Run Problem Fixer", command=self.run_problem_fixer_script)
        self.fixer_button.grid(row=0, column=1, padx=(ROW_INTER_BTN_PADX, PAD_X), pady=ROW_INTERNAL_PADY, sticky=tk.EW) # Pad between left, outside right

        # --- Row 2: Bulk Action Buttons Frame ---
        row2_frame = ttk.Frame(actions_frame)
        row2_frame.grid(row=2, column=0, padx=0, pady=PAD_Y, sticky=tk.EW) # Use PAD_Y for vertical spacing
        row2_frame.columnconfigure(0, weight=1, uniform="actions_buttons_2col") # Use same uniform group
        row2_frame.columnconfigure(1, weight=1, uniform="actions_buttons_2col")

        self.bulk_rename_button = ttk.Button(row2_frame, text="Bulk Rename Existing Items", command=self.bulk_rename_action)
        self.bulk_rename_button.grid(row=0, column=0, padx=(PAD_X, ROW_INTER_BTN_PADX), pady=ROW_INTERNAL_PADY, sticky=tk.EW)
        self.bulk_upload_button = ttk.Button(row2_frame, text="Bulk Upload Existing Items", command=self.bulk_upload_action)
        self.bulk_upload_button.grid(row=0, column=1, padx=(ROW_INTER_BTN_PADX, PAD_X), pady=ROW_INTERNAL_PADY, sticky=tk.EW)

        # --- Row 3: File Buttons Frame ---
        # Reuse existing variable name, but it's now just like row1/row2_frame conceptually
        file_button_frame = ttk.Frame(actions_frame)
        file_button_frame.grid(row=3, column=0, padx=0, pady=PAD_Y, sticky=tk.EW) # Use PAD_Y for vertical spacing
        # Configure 3 equal columns using a different uniform group
        file_button_frame.columnconfigure(0, weight=1, uniform="actions_buttons_3col")
        file_button_frame.columnconfigure(1, weight=1, uniform="actions_buttons_3col")
        file_button_frame.columnconfigure(2, weight=1, uniform="actions_buttons_3col")

        open_log_button = ttk.Button(file_button_frame, text="Open Log", command=self.open_log_file)
        open_log_button.grid(row=0, column=0, padx=(PAD_X, ROW_INTER_BTN_PADX), pady=ROW_INTERNAL_PADY, sticky=tk.EW) # Pad outside left
        open_csv_button = ttk.Button(file_button_frame, text="Open CSV", command=self.open_csv_file)
        open_csv_button.grid(row=0, column=1, padx=ROW_INTER_BTN_PADX, pady=ROW_INTERNAL_PADY, sticky=tk.EW) # Pad between both sides
        self.copy_csv_button = ttk.Button(file_button_frame, text="Copy CSV", command=self.copy_csv_data_to_clipboard)
        self.copy_csv_button.grid(row=0, column=2, padx=(ROW_INTER_BTN_PADX, PAD_X), pady=ROW_INTERNAL_PADY, sticky=tk.EW) # Pad outside right
        try:
            if not PYPERCLIP_AVAILABLE: self.copy_csv_button.config(state=tk.DISABLED)
        except NameError: pass # Or handle defensively

        # --- Row 4: Help and Nuke Buttons Frame ---
        # Reuse existing variable name
        bottom_button_frame = ttk.Frame(actions_frame)
        bottom_button_frame.grid(row=4, column=0, padx=0, pady=PAD_Y, sticky=tk.EW) # Use PAD_Y for vertical spacing
        # Configure 2 equal columns, same uniform group as rows 1 & 2
        bottom_button_frame.columnconfigure(0, weight=1, uniform="actions_buttons_2col")
        bottom_button_frame.columnconfigure(1, weight=1, uniform="actions_buttons_2col")

        self.help_button = ttk.Button(bottom_button_frame, text="Help/Info", command=self.show_help_info)
        self.help_button.grid(row=0, column=0, padx=(PAD_X, ROW_INTER_BTN_PADX), pady=ROW_INTERNAL_PADY, sticky=tk.EW)

        self.nuke_button = ttk.Button(bottom_button_frame, text="NUKE Directory", command=self.nuke_action)
        # Apply the style configuration (Red text, default background)
        style = ttk.Style()
        style.configure("Nuke.TButton", foreground="red", font=('TkDefaultFont', 9, 'bold'))
        style.map("Nuke.TButton", foreground=[('active', '#A00000'), ('disabled', 'grey')])
        self.nuke_button.configure(style="Nuke.TButton")
        self.nuke_button.grid(row=0, column=1, padx=(ROW_INTER_BTN_PADX, PAD_X), pady=ROW_INTERNAL_PADY, sticky=tk.EW)

        # --- Status Frame (Bottom-Right) ---
        status_frame = ttk.LabelFrame(main_frame, text="Status / Log", padding=FRAME_PAD)
        status_frame.grid(row=1, column=1, padx=INTER_FRAME_PADX, pady=INTER_FRAME_PADY, sticky="nsew")
        status_frame.rowconfigure(0, weight=1) # Make text widget expand vertically
        status_frame.columnconfigure(0, weight=1) # Make text widget expand horizontally

        self.status_text = tk.Text(status_frame, height=10, width=50, state=tk.DISABLED, wrap=tk.WORD, borderwidth=1, relief="sunken", font=("Consolas", 9))
        status_scrollbar = ttk.Scrollbar(status_frame, orient=tk.VERTICAL, command=self.status_text.yview)
        self.status_text.config(yscrollcommand=status_scrollbar.set)
        self.status_text.grid(row=0, column=0, sticky="nsew")
        status_scrollbar.grid(row=0, column=1, sticky="ns")

        # REMOVED the calls to self.log_status and self.update_status_colors
        # You should handle log initialization and status color updates
        # elsewhere in your code, likely after create_widgets is called
        # or within the methods that change the status (like update_stats).

    # --- Stats Update Method ---
    def update_stats(self):
        """Reads CSV and checks files to update the stats labels."""
        log_status(logging.INFO, "Refreshing stats...")
        csv_path = os.path.join(app_config.get('base_dir', base_dir_path), CSV_FILENAME)
        import_path_base = os.path.join(app_config.get('base_dir', base_dir_path), IMPORT_FOLDER)
        export_path_base = os.path.join(app_config.get('base_dir', base_dir_path), EXPORT_FOLDER)

        header, data = get_csv_data(csv_path)

        if header is None:
            self.total_entries_var.set("Total Entries: Error reading CSV")
            self.import_files_var.set("Import Files Found: N/A")
            self.export_files_var.set("Export Files Found: N/A")
            self.url_entries_var.set("Entries with URL: N/A")
            self.import_status_var.set("ERR")
            self.export_status_var.set("ERR")
            self.url_status_var.set("ERR")
            self.import_status_label.config(foreground="white", background="red") # Use colors for status
            self.export_status_label.config(foreground="white", background="red")
            self.url_status_label.config(foreground="white", background="red")
            return

        total_entries = len(data)
        import_found = 0
        export_found = 0
        url_found = 0
        import_missing = False
        export_missing = False

        try:
            orig_idx, renamed_idx, url_idx = 1, 2, 3 # Assuming standard column order
            if not (header[orig_idx] == "Original" and header[renamed_idx] == "Renamed" and header[url_idx] == "URL"):
                 raise ValueError("CSV header mismatch")

            for row in data:
                if os.path.exists(os.path.join(import_path_base, row[orig_idx])):
                    import_found += 1
                else:
                    import_missing = True # Mark if any import file is missing

                if os.path.exists(os.path.join(export_path_base, row[renamed_idx])):
                    export_found += 1
                else:
                    export_missing = True # Mark if any export file is missing

                if row[url_idx]:
                    url_found += 1

        except (IndexError, ValueError):
            log_status(logging.ERROR, "Error processing CSV for stats: Header mismatch or row error.")
            messagebox.showerror("Stats Error", "Could not process CSV data for stats due to invalid format.")
            # Reset stats to error state
            self.total_entries_var.set("Total Entries: CSV Format Error")
            self.import_files_var.set("Import Files Found: N/A")
            self.export_files_var.set("Export Files Found: N/A")
            self.url_entries_var.set("Entries with URL: N/A")
            self.import_status_var.set("ERR"); self.import_status_label.config(foreground="white", background="red")
            self.export_status_var.set("ERR"); self.export_status_label.config(foreground="white", background="red")
            self.url_status_var.set("ERR"); self.url_status_label.config(foreground="white", background="red")
            return

        # Update variables
        self.total_entries_var.set(f"Total Entries: {total_entries}")
        self.import_files_var.set(f"Import Files Found: {import_found}/{total_entries}")
        self.export_files_var.set(f"Export Files Found: {export_found}/{total_entries}")
        self.url_entries_var.set(f"Entries with URL: {url_found}/{total_entries}")

        # Update status indicators
        if total_entries == 0:
            self.import_status_var.set("N/A"); self.import_status_label.config(foreground="grey", background="SystemButtonFace")
            self.export_status_var.set("N/A"); self.export_status_label.config(foreground="grey", background="SystemButtonFace")
            self.url_status_var.set("N/A"); self.url_status_label.config(foreground="grey", background="SystemButtonFace")
        else:
            if import_missing:
                self.import_status_var.set("MISS"); self.import_status_label.config(foreground="white", background="red")
            else:
                self.import_status_var.set("OK"); self.import_status_label.config(foreground="white", background="green")

            if export_missing:
                self.export_status_var.set("MISS"); self.export_status_label.config(foreground="white", background="red")
            else:
                self.export_status_var.set("OK"); self.export_status_label.config(foreground="white", background="green")

            if url_found == total_entries:
                 self.url_status_var.set("ALL"); self.url_status_label.config(foreground="white", background="green")
            elif url_found > 0:
                 self.url_status_var.set("PART"); self.url_status_label.config(foreground="black", background="orange")
            else:
                 self.url_status_var.set("NONE"); self.url_status_label.config(foreground="white", background="red")

        log_status(logging.INFO, "Stats refreshed.")


    # --- GUI Action Handlers ---
    # (Keep browse_base_dir, update_widget_states, save_config_action, save_config_action_with_popup,
    #  toggle_logging, toggle_uploads, open_log_file, open_csv_file, copy_csv_data_to_clipboard,
    #  show_help_info, run_in_thread, start_script_action, handle_download_complete,
    #  process_local_folder, ask_rename_method, individual_rename_gui, bulk_rename_new_files_thread,
    #  process_uploads_and_log, edit_entry_action, bulk_rename_action, bulk_upload_action, nuke_action)
    # ... (These methods omitted for brevity but should be included here) ...
    def browse_base_dir(self):
        directory = filedialog.askdirectory(initialdir=self.base_dir_var.get() or base_dir_path)
        if directory: # Only update if a directory was selected
            self.base_dir_var.set(directory)
            log_status(logging.INFO, f"Base directory selected: {directory}")

    def update_widget_states(self):
        """Enable/disable widgets based on current config state."""
        api_key_present = bool(self.api_key_var.get()) # Use var here
        uploads_enabled_state = self.enable_upload_var.get()
        can_upload = api_key_present and uploads_enabled_state

        # Find buttons (this is fragile, better to store references)
        # Storing references would be cleaner:
        # self.bulk_upload_button.config(state=tk.NORMAL if can_upload else tk.DISABLED)
        # ... but requires defining buttons as instance vars earlier
        for frame in self.root.winfo_children():
             if isinstance(frame, ttk.Frame): # Main frame
                 for sub_frame in frame.winfo_children():
                      if isinstance(sub_frame, ttk.LabelFrame) and "Actions" in sub_frame.cget("text"):
                           for widget in sub_frame.winfo_children():
                                if isinstance(widget, ttk.Button):
                                    button_text = widget.cget("text")
                                    if "Bulk Upload" in button_text:
                                         widget.config(state=tk.NORMAL if can_upload else tk.DISABLED)


    def save_config_action(self, show_success_popup=False):
        """Handles saving the configuration from the GUI."""
        global app_config, base_dir_path
        log_status(logging.INFO, "Saving configuration...")
        # Update app_config from GUI variables before saving
        app_config['drive_id'] = self.drive_id_var.get()
        app_config['api_key'] = self.api_key_var.get() # Use var here
        new_base_dir = self.base_dir_var.get()
        app_config['enable_colors'] = str(True).lower() # Colors not used in GUI itself
        app_config['enable_logging'] = str(self.enable_logging_var.get()).lower()
        app_config['enable_upload'] = str(self.enable_upload_var.get()).lower()

        # Validate and update base directory
        if not os.path.isdir(new_base_dir):
            log_status(logging.ERROR, f"Invalid Base Directory: '{new_base_dir}'. Cannot save.")
            messagebox.showerror("Save Error", f"Invalid Base Directory:\n{new_base_dir}\nPlease select a valid folder.")
            return False

        # If base dir changed, update global path and re-setup logging
        if new_base_dir != app_config.get('base_dir'):
             log_status(logging.INFO, f"Base directory changed from '{app_config.get('base_dir')}' to '{new_base_dir}'.")
             base_dir_path = new_base_dir
             app_config['base_dir'] = new_base_dir
             setup_file_logging(base_dir_path, app_config['enable_logging'])

        if save_config_gui(show_success_popup):
             self.update_widget_states()
             return True
        else:
             return False

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
        api_key_present = bool(self.api_key_var.get()) # Use var here

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
        log_file_path = os.path.join(app_config.get('base_dir', base_dir_path), LOG_FILENAME)
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
        csv_file_path = os.path.join(app_config.get('base_dir', base_dir_path), CSV_FILENAME)
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

    def copy_csv_data_to_clipboard(self):
        """Reads CSV data and copies it to the clipboard."""
        if not PYPERCLIP_AVAILABLE:
            messagebox.showerror("Error", "pyperclip library not found. Cannot copy.\nInstall with: pip install pyperclip")
            return

        csv_path = os.path.join(app_config.get('base_dir', base_dir_path), CSV_FILENAME)
        log_status(logging.INFO, f"Attempting to copy CSV data from: {csv_path}")
        if not os.path.exists(csv_path):
            log_status(logging.ERROR, "CSV file does not exist yet.")
            messagebox.showerror("Error", f"CSV file not found:\n{csv_path}")
            return

        try:
            with open(csv_path, 'r', newline='', encoding='utf-8') as f:
                csv_content = f.read()
            pyperclip.copy(csv_content)
            log_status("SUCCESS", "CSV data copied to clipboard.")
            messagebox.showinfo("Copied", "CSV data copied to clipboard.")
        except Exception as e:
            log_status(logging.ERROR, f"Failed to read or copy CSV data: {e}")
            messagebox.showerror("Error", f"Failed to read or copy CSV data:\n{e}")
            logger.exception("Failed to copy CSV data")

    def show_help_info(self):
        """Displays the help/explanation text in a message box."""
        log_status(logging.INFO, "Showing help/info.")
        help_text = """
How This Program Works:
This tool automates fetching (Drive/Local), renaming, and uploading images to s-ul.eu.
It keeps track of processed files in 'index.csv'.

Key Folders:
- Images import: Source for local import / Destination for Drive download.
- Images export: Where renamed files are stored before/after upload.

Key Files:
- settings.conf: Stores your settings.
- index.csv: Logs successfully processed files.
- script_activity.log: Detailed log of script activity (if enabled).

Main Actions:
- Start Script: Begins the import/rename/upload workflow.
- Edit CSV Entry: Allows modifying or deleting individual log entries.
- Bulk Rename Existing: Renames all logged files sequentially.
- Bulk Upload Existing: Uploads logged files that don't have a URL yet.
- Nuke Directory: Permanently deletes the entire working folder (use with caution!).

Settings:
- Drive ID/URL: Target Google Drive folder.
- API Key: Your s-ul.eu key (required for uploads).
- Base Directory: Where the script operates and stores files.
- Enable Logging: Toggles saving activity to script_activity.log.
- Enable Uploads: Toggles the s-ul.eu upload feature globally.

File Buttons:
- Open Log/CSV: Opens the respective file using your system's default app.
- Copy CSV Data: Copies the entire CSV content to your clipboard.

GitHub: https://github.com/spodai/stuff/blob/main/team_banners.py
"""
        # Use a read-only text widget in a Toplevel for better formatting
        help_win = tk.Toplevel(self.root)
        help_win.title("Help / Information")
        help_win.geometry("650x550")
        help_win.transient(self.root)
        help_win.grab_set()

        text_frame = ttk.Frame(help_win, padding=10)
        text_frame.pack(fill=tk.BOTH, expand=True)

        help_text_widget = tk.Text(text_frame, wrap=tk.WORD, height=25, width=80)
        help_text_widget.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar = ttk.Scrollbar(text_frame, orient=tk.VERTICAL, command=help_text_widget.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        help_text_widget.config(yscrollcommand=scrollbar.set)

        help_text_widget.insert(tk.END, help_text.strip())
        help_text_widget.config(state=tk.DISABLED) # Make read-only

        close_button = ttk.Button(help_win, text="Close", command=help_win.destroy)
        close_button.pack(pady=10)


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
        user_cancelled = False
        os.makedirs(export_path, exist_ok=True)
        log_status(logging.INFO, f"Starting individual rename for {len(files_to_process)} files...")

        for i, original_filename in enumerate(sorted(files_to_process)):
            src_path = os.path.join(import_path, original_filename)
            if not os.path.isfile(src_path):
                log_status(logging.WARNING, f"Source file not found, skipping: {original_filename}")
                skipped_count += 1
                continue

            # --- Use Custom Rename Dialog ---
            dialog = RenameDialog(self.root, original_filename, src_path) # Pass root window as parent
            # wait_window is implicitly handled by simpledialog.Dialog inheritance
            # self.root.wait_window(dialog) # REMOVED - This was likely the cause of the error
            new_name_base = dialog.new_name_base # Get result from dialog attribute after it closes

            if new_name_base is None: # User cancelled dialog
                 log_status(logging.WARNING, "Individual rename cancelled by user.")
                 messagebox.showwarning("Cancelled", "Rename process cancelled.")
                 user_cancelled = True
                 break # Abort the whole process

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

        if not user_cancelled:
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
                # Pass result queue to thread
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
                    # Refresh stats after processing is complete
                    self.update_stats()

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
            # Refresh stats after edit window closes
            self.root.wait_window(edit_window)
            self.update_stats()

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

    def show_help_info(self):
        """Displays the help/explanation text in a message box."""
        log_status(logging.INFO, "Showing help/info.")
        help_text = """
How This Program Works:
This tool automates fetching (Drive/Local), renaming, and uploading images to s-ul.eu.
It keeps track of processed files in 'index.csv'.

Key Folders:
- Images import: Source for local import / Destination for Drive download.
- Images export: Where renamed files are stored before/after upload.

Key Files:
- settings.conf: Stores your settings.
- index.csv: Logs successfully processed files.
- script_activity.log: Detailed log of script activity (if enabled).

Main Actions:
- Start Script: Begins the import/rename/upload workflow.
- Edit CSV Entry: Allows modifying or deleting individual log entries.
- Bulk Rename Existing: Renames all logged files sequentially.
- Bulk Upload Existing: Uploads logged files that don't have a URL yet.
- Nuke Directory: Permanently deletes the entire working folder (use with caution!).

Settings:
- Drive ID/URL: Target Google Drive folder.
- API Key: Your s-ul.eu key (required for uploads).
- Base Directory: Where the script operates and stores files.
- Enable Logging: Toggles saving activity to script_activity.log.
- Enable Uploads: Toggles the s-ul.eu upload feature globally.

File Buttons:
- Open Log/CSV: Opens the respective file using your system's default app.
- Copy CSV Data: Copies the entire CSV content to your clipboard.

GitHub: https://github.com/spodai/stuff/blob/main/team_banners.py
"""
        # Use a read-only text widget in a Toplevel for better formatting
        help_win = tk.Toplevel(self.root)
        help_win.title("Help / Information")
        help_win.geometry("650x550")
        help_win.transient(self.root)
        help_win.grab_set()

        text_frame = ttk.Frame(help_win, padding=10)
        text_frame.pack(fill=tk.BOTH, expand=True)

        help_text_widget = tk.Text(text_frame, wrap=tk.WORD, height=25, width=80)
        help_text_widget.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar = ttk.Scrollbar(text_frame, orient=tk.VERTICAL, command=help_text_widget.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        help_text_widget.config(yscrollcommand=scrollbar.set)

        help_text_widget.insert(tk.END, help_text.strip())
        help_text_widget.config(state=tk.DISABLED) # Make read-only

        close_button = ttk.Button(help_win, text="Close", command=help_win.destroy)
        close_button.pack(pady=10)


# --- Edit Entry Window Class ---
class EditWindow(tk.Toplevel):
    def __init__(self, parent, csv_path, current_config):
        super().__init__(parent)
        self.title("Edit CSV Entry")
        self.geometry("850x650") # Made wider and taller
        self.transient(parent)
        self.grab_set()

        self.csv_path = csv_path
        self.config = current_config
        self.base_dir = current_config.get('base_dir')
        self.export_path_base = os.path.join(self.base_dir, EXPORT_FOLDER)
        self.import_path_base = os.path.join(self.base_dir, IMPORT_FOLDER)
        self.api_key = current_config.get('api_key')
        self.uploads_enabled = str(current_config.get('enable_upload', 'true')).lower() == 'true'

        self.header, self.data = get_csv_data(self.csv_path)
        self.original_data_on_load = [list(row) for row in self.data] # Store original state

        if self.header is None or not self.data:
             messagebox.showerror("Error", "Could not load CSV data or CSV is empty.", parent=self)
             self.destroy()
             return

        self.create_edit_widgets() # Call this AFTER initializing data

    def create_edit_widgets(self):
        main_frame = ttk.Frame(self, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        main_frame.columnconfigure(1, weight=3, minsize=PREVIEW_MAX_WIDTH*2 + 40) # Make preview area expand more, give minsize
        main_frame.columnconfigure(0, weight=1, minsize=300) # Give listbox reasonable min width (Increased)
        main_frame.rowconfigure(0, weight=3) # Give listbox/preview more weight
        main_frame.rowconfigure(1, weight=1) # Give details less weight
        main_frame.rowconfigure(2, weight=0) # Action buttons fixed height
        main_frame.rowconfigure(3, weight=0) # Close button fixed height


        # --- Top Frame for List and Preview ---
        top_frame = ttk.Frame(main_frame)
        top_frame.grid(row=0, column=0, columnspan=2, sticky="nsew", pady=(0,10))
        top_frame.columnconfigure(0, weight=1, minsize=300) # Listbox column (Increased)
        top_frame.columnconfigure(1, weight=3) # Preview column (matches main_frame config)
        top_frame.rowconfigure(0, weight=1)

        # --- Listbox Frame (Allowing Multi-Select) ---
        list_frame = ttk.Frame(top_frame)
        list_frame.grid(row=0, column=0, padx=(0, 10), pady=5, sticky="nsew")
        ttk.Label(list_frame, text="Select Entry/Entries:").pack(side=tk.TOP, padx=5, anchor=tk.W)

        listbox_inner_frame = ttk.Frame(list_frame) # Frame for listbox + scrollbar
        listbox_inner_frame.pack(fill=tk.BOTH, expand=True)

        self.entry_listbox = tk.Listbox(listbox_inner_frame, height=15, exportselection=False, selectmode=tk.EXTENDED)
        self.entry_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar = ttk.Scrollbar(listbox_inner_frame, orient=tk.VERTICAL, command=self.entry_listbox.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.entry_listbox.config(yscrollcommand=scrollbar.set)
        self.entry_listbox.bind('<<ListboxSelect>>', self.on_listbox_select)

        # --- Preview Frame ---
        preview_frame = ttk.LabelFrame(top_frame, text="Image Preview", padding="5")
        preview_frame.grid(row=0, column=1, pady=5, sticky="nsew")
        preview_frame.columnconfigure(0, weight=1)
        preview_frame.columnconfigure(1, weight=1)
        preview_frame.rowconfigure(1, weight=1)

        ttk.Label(preview_frame, text="Import File").grid(row=0, column=0, pady=(0,5))
        ttk.Label(preview_frame, text="Export File").grid(row=0, column=1, pady=(0,5))

        # Use Labels to display images
        self.import_image_label = ttk.Label(preview_frame, text="Preview N/A" if not PIL_AVAILABLE else "Select single item", relief="sunken", anchor="center")
        self.import_image_label.grid(row=1, column=0, sticky="nsew", padx=5, pady=5)
        self.export_image_label = ttk.Label(preview_frame, text="Preview N/A" if not PIL_AVAILABLE else "Select single item", relief="sunken", anchor="center")
        self.export_image_label.grid(row=1, column=1, sticky="nsew", padx=5, pady=5)
        self.import_photo = None # Keep reference
        self.export_photo = None # Keep reference


        # --- Details Frame (Improved Layout) ---
        self.details_frame = ttk.LabelFrame(main_frame, text="Selected Item Details", padding="10")
        self.details_frame.grid(row=1, column=0, columnspan=2, pady=5, sticky="ew") # Span both columns, fill x
        self.details_frame.columnconfigure(1, weight=1) # Allow value label to expand
        self.details_frame.columnconfigure(3, weight=1) # Allow URL label to expand

        self.detail_original_var = tk.StringVar()
        self.detail_renamed_var = tk.StringVar()
        self.detail_url_var = tk.StringVar()
        self.detail_ts_var = tk.StringVar()

        ttk.Label(self.details_frame, text="Original:").grid(row=0, column=0, sticky=tk.W, padx=5, pady=1)
        ttk.Label(self.details_frame, textvariable=self.detail_original_var, anchor="w").grid(row=0, column=1, sticky=tk.EW, padx=5, pady=1)
        ttk.Label(self.details_frame, text="Timestamp:").grid(row=0, column=2, sticky=tk.W, padx=5, pady=1)
        ttk.Label(self.details_frame, textvariable=self.detail_ts_var, anchor="w").grid(row=0, column=3, sticky=tk.EW, padx=5, pady=1)

        ttk.Label(self.details_frame, text="Renamed:").grid(row=1, column=0, sticky=tk.W, padx=5, pady=1)
        ttk.Label(self.details_frame, textvariable=self.detail_renamed_var, anchor="w").grid(row=1, column=1, sticky=tk.EW, padx=5, pady=1)
        ttk.Label(self.details_frame, text="URL:").grid(row=1, column=2, sticky=tk.W, padx=5, pady=1)
        ttk.Label(self.details_frame, textvariable=self.detail_url_var, anchor="w").grid(row=1, column=3, sticky=tk.EW, padx=5, pady=1)


        # --- Action Buttons Frame ---
        action_button_frame = ttk.Frame(main_frame)
        action_button_frame.grid(row=2, column=0, columnspan=2, pady=5, sticky="ew")

        # Single Item Actions
        single_item_frame = ttk.Frame(action_button_frame)
        single_item_frame.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
        ttk.Label(single_item_frame, text="Single Item Actions:").pack(anchor=tk.W, pady=(0,2))
        single_btn_row1 = ttk.Frame(single_item_frame)
        single_btn_row1.pack(fill=tk.X)
        self.rename_button = ttk.Button(single_btn_row1, text="Change Name", command=self.action_rename, state=tk.DISABLED)
        self.rename_button.pack(side=tk.LEFT, padx=2)
        self.upload_button = ttk.Button(single_btn_row1, text="Upload / Re-upload", command=self.action_upload_single, state=tk.DISABLED) # Combined button
        self.upload_button.pack(side=tk.LEFT, padx=2)
        self.editurl_button = ttk.Button(single_btn_row1, text="Edit URL", command=self.action_edit_url, state=tk.DISABLED)
        self.editurl_button.pack(side=tk.LEFT, padx=2)
        self.removeurl_button = ttk.Button(single_btn_row1, text="Remove URL", command=self.action_remove_url, state=tk.DISABLED)
        self.removeurl_button.pack(side=tk.LEFT, padx=2)
        # Add single delete button here (calls same action as multi-delete)
        self.delete_single_button = ttk.Button(single_btn_row1, text="Delete Entry", command=self.action_delete_selected, state=tk.DISABLED, style="Nuke.TButton")
        self.delete_single_button.pack(side=tk.LEFT, padx=2)


        # Multi Item Actions
        multi_item_frame = ttk.Frame(action_button_frame)
        multi_item_frame.pack(side=tk.LEFT, padx=15, fill=tk.X, expand=True)
        ttk.Label(multi_item_frame, text="Selected Items Actions:").pack(anchor=tk.W, pady=(0,2))
        multi_btn_row1 = ttk.Frame(multi_item_frame)
        multi_btn_row1.pack(fill=tk.X)
        self.bulk_rename_sel_button = ttk.Button(multi_btn_row1, text="Bulk Rename", command=self.action_bulk_rename_selected, state=tk.DISABLED)
        self.bulk_rename_sel_button.pack(side=tk.LEFT, padx=2)
        self.bulk_reupload_sel_button = ttk.Button(multi_btn_row1, text="Re-upload", command=self.action_reupload_selected, state=tk.DISABLED)
        self.bulk_reupload_sel_button.pack(side=tk.LEFT, padx=2)
        self.delete_exp_sel_button = ttk.Button(multi_btn_row1, text="Delete Export Files", command=self.action_delete_export_selected, state=tk.DISABLED)
        self.delete_exp_sel_button.pack(side=tk.LEFT, padx=2)
        self.delete_sel_button = ttk.Button(multi_btn_row1, text="Delete Entries", command=self.action_delete_selected, state=tk.DISABLED, style="Nuke.TButton")
        self.delete_sel_button.pack(side=tk.LEFT, padx=2)


        # Close button (Bottom Right)
        close_button_frame = ttk.Frame(main_frame)
        close_button_frame.grid(row=3, column=1, pady=(10,0), sticky="e")
        close_button = ttk.Button(close_button_frame, text="Close", command=self.destroy)
        close_button.pack()

        # --- Populate listbox AFTER all widgets are created ---
        # Moved refresh_listbox call to the end after all buttons are defined
        self.refresh_listbox()


    def on_listbox_select(self, event):
        """Updates details and enables/disables buttons based on selection."""
        self.selected_indices = self.entry_listbox.curselection() # Get tuple of selected indices

        if not self.selected_indices:
            self.clear_details()
            self.disable_all_action_buttons()
            self.clear_previews()
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
                self.enable_single_action_buttons(row_data[3]) # Pass URL to enable/disable remove URL
                self.disable_multi_action_buttons()
                self.load_previews(row_data[1], row_data[2]) # Load preview images
            except IndexError:
                self.clear_details()
                self.disable_all_action_buttons()
                self.clear_previews()
                log_status(logging.ERROR, f"Selected row {index+1} has invalid data.")
                messagebox.showerror("Error", "Selected row has invalid data.", parent=self)
        else:
            # Multiple items selected
            self.clear_details() # Clear details view
            self.detail_original_var.set(f"({len(self.selected_indices)} items selected)") # Indicate multiple selection
            self.disable_single_action_buttons()
            self.enable_multi_action_buttons()
            self.clear_previews()

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
        self.upload_button.config(state=tk.DISABLED)
        self.editurl_button.config(state=tk.DISABLED)
        self.removeurl_button.config(state=tk.DISABLED)
        self.delete_single_button.config(state=tk.DISABLED) # Disable single delete


    def enable_single_action_buttons(self, current_url):
        self.rename_button.config(state=tk.NORMAL)
        can_upload = self.uploads_enabled and self.api_key
        self.upload_button.config(state=tk.NORMAL if can_upload else tk.DISABLED)
        # Change text based on if URL exists
        self.upload_button.config(text="Re-upload" if current_url else "Upload")
        self.editurl_button.config(state=tk.NORMAL)
        self.removeurl_button.config(state=tk.NORMAL if current_url else tk.DISABLED) # Enable only if URL exists
        self.delete_single_button.config(state=tk.NORMAL) # Enable single delete


    def disable_multi_action_buttons(self):
        self.bulk_rename_sel_button.config(state=tk.DISABLED)
        self.bulk_reupload_sel_button.config(state=tk.DISABLED)
        self.delete_sel_button.config(state=tk.DISABLED)
        self.delete_exp_sel_button.config(state=tk.DISABLED)

    def enable_multi_action_buttons(self):
        self.bulk_rename_sel_button.config(state=tk.NORMAL)
        can_upload = self.uploads_enabled and self.api_key
        self.bulk_reupload_sel_button.config(state=tk.NORMAL if can_upload else tk.DISABLED)
        self.delete_sel_button.config(state=tk.NORMAL)
        self.delete_exp_sel_button.config(state=tk.NORMAL)

    def clear_previews(self):
        self.import_image_label.config(image='', text="Select single item" if PIL_AVAILABLE else "Preview N/A")
        self.export_image_label.config(image='', text="Select single item" if PIL_AVAILABLE else "Preview N/A")
        self.import_photo = None
        self.export_photo = None

    def load_previews(self, original_name, renamed_name):
        """Loads and displays preview images for the selected item."""
        if not PIL_AVAILABLE:
            return # Do nothing if Pillow is not installed

        self.clear_previews() # Clear previous previews

        # Load import image
        import_path = os.path.join(self.import_path_base, original_name)
        if os.path.exists(import_path):
            try:
                img = Image.open(import_path)
                img.thumbnail((PREVIEW_MAX_WIDTH, PREVIEW_MAX_HEIGHT))
                self.import_photo = ImageTk.PhotoImage(img)
                self.import_image_label.config(image=self.import_photo, text="")
            except UnidentifiedImageError:
                 self.import_image_label.config(image='', text="Cannot preview (format?)")
            except Exception as e:
                self.import_image_label.config(image='', text="Preview Error")
                logger.warning(f"Error loading import preview '{import_path}': {e}")
        else:
            self.import_image_label.config(image='', text="Import file missing")

        # Load export image
        export_path = os.path.join(self.export_path_base, renamed_name)
        if os.path.exists(export_path):
            try:
                img = Image.open(export_path)
                img.thumbnail((PREVIEW_MAX_WIDTH, PREVIEW_MAX_HEIGHT))
                self.export_photo = ImageTk.PhotoImage(img)
                self.export_image_label.config(image=self.export_photo, text="")
            except UnidentifiedImageError:
                 self.export_image_label.config(image='', text="Cannot preview (format?)")
            except Exception as e:
                self.export_image_label.config(image='', text="Preview Error")
                logger.warning(f"Error loading export preview '{export_path}': {e}")
        else:
            self.export_image_label.config(image='', text="Export file missing")


    def save_csv_data(self):
        """Saves the current state of self.data back to the CSV file."""
        try:
            with open(self.csv_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(self.header) # Write clean header
                writer.writerows(self.data) # Write updated data
            log_status("SUCCESS", "CSV log updated successfully.")
            logger.info(f"CSV log saved successfully from Edit window.")
            # Store the saved data as the new "original" state for potential reverts
            self.original_data_on_load = [list(row) for row in self.data]
            return True
        except (IOError, csv.Error) as e:
            log_status(logging.ERROR, f"Failed to save updated CSV: {e}")
            messagebox.showerror("Save Error", f"Failed to save CSV:\n{e}", parent=self)
            logger.exception("CSV Save Error from Edit Window")
            # Attempt to restore in-memory data from the last known good state
            self.data = [list(row) for row in self.original_data_on_load]
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
             # Trigger update of details and buttons based on new selection
             self.on_listbox_select(None)
        else:
             self.clear_details()
             self.disable_all_action_buttons()
             self.clear_previews()


    # --- Action Methods for Edit Window ---

    def get_selected_indices(self):
        """Returns a sorted list of selected row indices."""
        # Tkinter listbox curselection returns tuple, convert to list
        return sorted(list(self.entry_listbox.curselection()))


    def action_rename(self):
        selected_indices = self.get_selected_indices()
        if len(selected_indices) != 1:
             messagebox.showwarning("Action Error", "Please select exactly one item to rename.", parent=self)
             return
        idx = selected_indices[0] # Get the single selected index

        current_renamed_name = self.data[idx][2]
        _, ext = os.path.splitext(current_renamed_name)

        new_name_base = simpledialog.askstring("Change Renamed File",
                                               f"Enter new base name for:\n'{current_renamed_name}'",
                                               parent=self)
        if not new_name_base: return # User cancelled

        new_renamed_name = f"{new_name_base.strip()}{ext}"
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
             reply = messagebox.askyesno("Re-upload?", f"File renamed to '{new_renamed_name}'.\nRe-upload to s-ul.eu?", parent=self)
             if reply: # User clicked Yes
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
        elif not self.uploads_enabled:
             new_url = "" # Clear URL if uploads disabled

        # Update data and save
        self.data[idx][2] = new_renamed_name
        self.data[idx][3] = str(new_url)
        self.data[idx][0] = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
        if self.save_csv_data():
             self.refresh_listbox() # Refresh list display

    def action_upload_single(self):
        """Handles the 'Upload' or 'Re-upload' button click for a single item."""
        selected_indices = self.get_selected_indices()
        if len(selected_indices) != 1:
             messagebox.showwarning("Action Error", "Please select exactly one item to upload/re-upload.", parent=self)
             return
        idx = selected_indices[0]
        self.action_reupload_selected_indices([idx]) # Call multi-upload logic

    def action_edit_url(self):
        # Single item URL edit
        selected_indices = self.get_selected_indices()
        if len(selected_indices) != 1:
             messagebox.showwarning("Action Error", "Please select exactly one item to edit its URL.", parent=self)
             return
        idx = selected_indices[0]

        current_url = self.data[idx][3]
        new_url = simpledialog.askstring("Edit URL", "Enter new URL (blank to remove):",
                                         initialvalue=current_url, parent=self)
        if new_url is None: return # User cancelled

        self.data[idx][3] = new_url.strip()
        self.data[idx][0] = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
        if self.save_csv_data():
             self.refresh_listbox() # Refresh list display

    def action_remove_url(self):
        """Removes the URL for the selected single item."""
        selected_indices = self.get_selected_indices()
        if len(selected_indices) != 1:
            messagebox.showwarning("Action Error", "Please select exactly one item to remove its URL.", parent=self)
            return
        idx = selected_indices[0]

        if not self.data[idx][3]: # No URL to remove
             messagebox.showinfo("Remove URL", "Selected item does not have a URL.", parent=self)
             return

        if messagebox.askyesno("Confirm Remove URL", "Are you sure you want to remove the URL for this entry?", parent=self):
            self.data[idx][3] = "" # Clear URL
            self.data[idx][0] = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f") # Update timestamp
            if self.save_csv_data():
                self.refresh_listbox()

    def action_delete_export_selected(self):
        """Deletes only the export file(s) for selected entries."""
        selected_indices = self.get_selected_indices()
        if not selected_indices:
             messagebox.showwarning("Action Error", "Please select one or more items to delete their export files.", parent=self)
             return

        count = len(selected_indices)
        if not messagebox.askyesno("Confirm Delete Export Files", f"Delete {count} export file(s) (from '{EXPORT_FOLDER}') for the selected entries?\n(This will NOT delete the CSV entry or import file)", icon='warning', parent=self):
            return

        deleted_count = 0
        failed_count = 0
        for idx in selected_indices:
            try:
                renamed_name = self.data[idx][2]
                export_file_path = os.path.join(self.export_path_base, renamed_name)
                if os.path.exists(export_file_path):
                    try:
                        os.remove(export_file_path)
                        log_status("SUCCESS", f"Deleted export file: {export_file_path}")
                        deleted_count += 1
                    except OSError as e:
                        log_status(logging.ERROR, f"Failed to delete export file {export_file_path}: {e}")
                        messagebox.showerror("File Delete Error", f"Failed to delete:\n{export_file_path}\n{e}", parent=self)
                        failed_count += 1
                else:
                    log_status(logging.WARNING, f"Export file not found, skipping delete: {export_file_path}")
            except IndexError:
                 log_status(logging.ERROR, f"Error processing index {idx} for export file deletion.")
                 failed_count += 1
            except Exception as e:
                 log_status(logging.ERROR, f"Unexpected error during export file deletion for index {idx}: {e}")
                 logger.exception(f"Export deletion error for index {idx}")
                 failed_count += 1

        summary = f"Deleted {deleted_count} export files."
        if failed_count > 0:
            summary += f"\nFailed to delete {failed_count} files (see log/status)."
        messagebox.showinfo("Delete Export Files Complete", summary, parent=self)


    def action_delete_selected(self):
        """Deletes all currently selected entries."""
        selected_indices = self.get_selected_indices() # Use helper
        if not selected_indices:
             messagebox.showwarning("Action Error", "Please select one or more items to delete.", parent=self)
             return

        count = len(selected_indices)
        if not messagebox.askyesno("Confirm Delete", f"Delete {count} selected entries from CSV?", icon='warning', parent=self):
            return

        delete_files = messagebox.askyesno("Delete Files?", "Also delete corresponding local files (Import/Export)?", icon='question', parent=self)

        indices_to_delete = sorted(selected_indices, reverse=True)
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

                # Remove row from data list
                self.data.pop(idx)
                deleted_rows += 1
                logger.info(f"Removed item at original index {idx} ('{renamed_name}') from data list.")

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
        selected_indices = self.get_selected_indices() # Use helper
        if not selected_indices:
             messagebox.showwarning("Action Error", "Please select one or more items to re-upload.", parent=self)
             return
        self.action_reupload_selected_indices(selected_indices)


    def action_reupload_selected_indices(self, indices_to_upload):
        """Helper to re-upload specific indices."""
        if not self.uploads_enabled or not self.api_key:
             messagebox.showerror("Error", "Uploads disabled or API Key missing.", parent=self)
             return

        items_to_upload = []
        items_with_urls = [] # Track items that already have URLs
        for idx in indices_to_upload:
             try:
                 renamed_name = self.data[idx][2]
                 file_path = os.path.join(self.export_path_base, renamed_name)
                 current_url = self.data[idx][3]

                 if os.path.exists(file_path):
                      if current_url:
                           items_with_urls.append(renamed_name) # Add to list for confirmation
                      items_to_upload.append({"index": idx, "file_path": file_path, "renamed_name": renamed_name})
                 else:
                      log_status(logging.WARNING, f"Skipping re-upload for '{renamed_name}': File not found.")
             except IndexError:
                  log_status(logging.ERROR, f"Skipping re-upload for index {idx}: Invalid row data.")

        if not items_to_upload:
             messagebox.showinfo("Re-upload", "No valid files found for selected entries to re-upload.", parent=self)
             return

        # Confirm overwrite if any selected items already have URLs
        if items_with_urls:
             confirm_msg = f"The following selected item(s) already have URLs:\n\n"
             confirm_msg += "\n".join(f"- {name}" for name in items_with_urls[:5]) # Show first 5
             if len(items_with_urls) > 5: confirm_msg += "\n..."
             confirm_msg += "\n\nRe-uploading will overwrite existing URLs. Continue?"
             if not messagebox.askyesno("Confirm Re-upload", confirm_msg, parent=self):
                  log_status(logging.INFO, "Re-upload cancelled by user due to existing URLs.")
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

        # Monitor results (using a progress dialog might be better here)
        total_files = len(threads)
        completed_files = 0
        successful_uploads = 0
        failed_uploads = 0
        updated_indices = []

        # Simple blocking wait loop (can freeze GUI slightly, better with QProgressDialog)
        self.master.config(cursor="watch")
        while completed_files < total_files:
            try:
                result = upload_queue.get(timeout=0.1) # Short timeout
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
                self.master.update() # Process GUI events during wait

            except queue.Empty:
                self.master.update() # Process GUI events
                if not any(t.is_alive() for t in threads): break # Exit if threads died
                continue

        self.master.config(cursor="") # Restore cursor

        # Save CSV if changes were made
        if updated_indices:
            log_status(logging.INFO, "Saving updated URLs after re-upload...")
            if self.save_csv_data():
                 self.refresh_listbox() # Refresh list display

        log_status(logging.INFO, f"Re-upload finished. Successful: {successful_uploads}, Failed: {failed_uploads}.")
        messagebox.showinfo("Re-upload Complete", f"Re-upload Finished.\nSuccessful: {successful_uploads}\nFailed: {failed_uploads}", parent=self)

    def action_bulk_rename_selected(self):
        """Bulk renames selected items sequentially."""
        selected_indices = self.get_selected_indices() # Use helper
        if not selected_indices:
             messagebox.showwarning("Action Error", "Please select one or more items to bulk rename.", parent=self)
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

        # Sort by original index to process in table order
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

        # Pass 2 & 3: Perform renames (synchronous for simplicity in dialog)
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
        # Emit finished signal with error status or empty result
        if UploaderApp.instance: # Check if main app instance exists
             # Need to define the signal on the worker instance before emitting
             # This structure needs adjustment - signals belong to QObject/QThread
             # For simplicity, we'll log and show messagebox from thread end
             # UploaderApp.instance.bulk_rename_worker.signals.finished.emit({"error": "Could not read CSV or no entries found."})
             log_status(logging.ERROR, "Bulk Rename Error: Could not read CSV or no entries found.")
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
        # if UploaderApp.instance: # Check if main app instance exists
        #      UploaderApp.instance.bulk_rename_worker.signals.finished.emit({"message": "Operation cancelled."}) # Signal completion
        return
    # --- End Get base name ---

    start_number = 1
    num_digits = len(str(len(data) + start_number - 1))
    log_status(logging.INFO, f"Bulk renaming {len(data)} items using base '{base_name}' starting from {start_number:0{num_digits}d}...")

    renamed_count = 0; skipped_count = 0; error_count = 0
    temp_export_files = {}; potential_renames = []; target_filenames = set()
    valid_process = True

    try:
        ts_idx, orig_idx, renamed_idx, url_idx = 0, 1, 2, 3
        if not (header_clean[ts_idx] == "Timestamp" and header_clean[orig_idx] == "Original" and
                header_clean[renamed_idx] == "Renamed" and header_clean[url_idx] == "URL"):
            raise ValueError("CSV header mismatch")
    except (IndexError, ValueError):
        log_status(logging.ERROR,"Bulk rename aborted: CSV header mismatch.")
        # if UploaderApp.instance:
        #      UploaderApp.instance.bulk_rename_worker.signals.error.emit("Bulk Rename Error", "CSV header mismatch.")
        return

    # Pass 1
    for i, row in enumerate(data):
        try:
            old_renamed_name = row[renamed_idx]
            _, ext = os.path.splitext(old_renamed_name); ext = ext if ext else ""
            new_filename_base = f"{base_name}{i + start_number:0{num_digits}d}"
            new_filename = f"{new_filename_base}{ext}"
            if new_filename in target_filenames:
                log_status(logging.ERROR, f"Conflict detected: Multiple items target '{new_filename}'. Aborting.")
                # if UploaderApp.instance:
                #      UploaderApp.instance.bulk_rename_worker.signals.error.emit("Bulk Rename Error", f"Conflict detected: Multiple items target '{new_filename}'.")
                valid_process = False; break
            target_filenames.add(new_filename)
            potential_renames.append({
                "index": i, "old_name": old_renamed_name, "new_name": new_filename,
                "old_path": os.path.join(export_path_base, old_renamed_name),
                "new_path": os.path.join(export_path_base, new_filename)})
        except IndexError: skipped_count += 1; logger.warning(f"Skipping row {i+1} due to column count.")

    if not valid_process: return

    # Pass 2 & 3
    final_data = [list(row) for row in data]
    rename_log = []
    for rename_info in potential_renames:
        old_path, new_path = rename_info["old_path"], rename_info["new_path"]
        old_name, new_name = rename_info["old_name"], rename_info["new_name"]
        item_index = rename_info["index"]
        if not os.path.exists(old_path): skipped_count += 1; continue
        if old_path == new_path: continue
        temp_path = None
        try:
            if os.path.exists(new_path):
                temp_suffix = f"__bulk_rename_temp_{datetime.now().strftime('%f')}"
                temp_path = old_path + temp_suffix
                os.rename(old_path, temp_path); temp_export_files[new_path] = temp_path
                rename_info["status"] = "pending_temp"
            else:
                os.rename(old_path, new_path); renamed_count += 1; rename_info["status"] = "renamed"
            final_data[item_index][renamed_idx] = new_name
            final_data[item_index][ts_idx] = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
        except OSError as e: error_count += 1; logger.error(f"Rename error for {old_name}: {e}")

    temp_rename_errors = 0
    for final_target_path, temp_source_path in temp_export_files.items():
        try:
            os.rename(temp_source_path, final_target_path)
            for info in potential_renames:
                 if info.get("status") == "pending_temp" and info["new_path"] == final_target_path:
                      info["status"] = "renamed"; renamed_count += 1; break
        except OSError as e:
            temp_rename_errors += 1; error_count += 1
            logger.error(f"Failed to rename temp file {temp_source_path} to {final_target_path}: {e}")
            for info in potential_renames:
                 if info.get("status") == "pending_temp" and info["new_path"] == final_target_path:
                      final_data[info["index"]][renamed_idx] = info["old_name"]; break

    # Save final data
    if renamed_count > 0 or error_count > 0: # Only save if changes or errors occurred
        log_status(logging.INFO, "Saving updated names to CSV...")
        try:
            with open(csv_path, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.writer(csvfile); writer.writerow(header_clean); writer.writerows(final_data)
            log_status("SUCCESS", "CSV log updated successfully.")
        except (IOError, csv.Error) as e:
            log_status(logging.ERROR, f"Failed to save updated CSV after bulk rename: {e}")
            # if UploaderApp.instance:
            #     UploaderApp.instance.bulk_rename_worker.signals.error.emit("CSV Save Error", f"Failed to save updated CSV: {e}")


    result_data = {"renamed_count": renamed_count, "skipped_count": skipped_count, "error_count": error_count}
    # if UploaderApp.instance:
         # UploaderApp.instance.bulk_rename_worker.signals.finished.emit(result_data)
    # Since this runs in a basic thread, show results via log_status/messagebox from here
    log_status("PRINT", "\n--- Bulk Rename Summary ---")
    log_status("PRINT", f"Total CSV Entries Processed: {len(data)}")
    log_status("SUCCESS", f"Files Successfully Renamed: {renamed_count}")
    if skipped_count > 0: log_status("WARNING", f"Files Skipped: {skipped_count}")
    if error_count > 0: log_status("ERROR", f"Errors During Rename: {error_count}")
    logger.info(f"Bulk Rename Existing summary: Total={len(data)}, Renamed={renamed_count}, Skipped={skipped_count}, Errors={error_count}")
    # Can't reliably show messagebox from thread, rely on status log


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
        # if UploaderApp.instance: UploaderApp.instance.bulk_upload_worker.signals.finished.emit({"message": "Uploads disabled or API Key missing."})
        return

    header, data = get_csv_data(csv_path)
    if header is None or not data:
        log_status(logging.ERROR if header is None else logging.INFO,
                   "Bulk Upload: Could not read CSV or no entries found.")
        # if UploaderApp.instance: UploaderApp.instance.bulk_upload_worker.signals.finished.emit({"message": "Could not read CSV or no entries found."})
        return

    log_status(logging.INFO, f"Bulk Upload: Found {len(data)} entries. Checking files...")

    items_to_upload = []
    skipped_has_url = 0; skipped_missing = 0
    try:
        ts_idx, orig_idx, renamed_idx, url_idx = 0, 1, 2, 3
        if not (header[ts_idx] == "Timestamp" and header[orig_idx] == "Original" and
                header[renamed_idx] == "Renamed" and header[url_idx] == "URL"):
            raise ValueError("CSV header mismatch")
        for idx, row in enumerate(data):
            renamed_name = row[renamed_idx]; current_url = row[url_idx]
            file_path = os.path.join(export_path_base, renamed_name)
            if not current_url and os.path.exists(file_path): items_to_upload.append({"index": idx, "file_path": file_path, "renamed_name": renamed_name})
            elif current_url: skipped_has_url += 1
            elif not os.path.exists(file_path): skipped_missing += 1; log_status(logging.WARNING, f"Bulk Upload: Skipping '{renamed_name}' (file not found).")
    except (IndexError, ValueError) as e:
        log_status(logging.ERROR, f"Bulk Upload aborted: CSV header mismatch or row error: {e}")
        # if UploaderApp.instance: UploaderApp.instance.bulk_upload_worker.signals.error.emit("Bulk Upload Error", f"CSV header mismatch or row error: {e}")
        return

    if not items_to_upload:
        log_status(logging.INFO, "Bulk Upload: No items found needing upload.")
        # if UploaderApp.instance: UploaderApp.instance.bulk_upload_worker.signals.finished.emit({"message": "No items found needing upload."})
        return

    log_status(logging.INFO, f"Bulk Upload: Starting upload for {len(items_to_upload)} items...")

    upload_queue = queue.Queue()
    threads = []
    for item in items_to_upload:
        thread = threading.Thread(target=upload_to_sul_thread, args=(item["file_path"], api_key, upload_queue), daemon=True)
        threads.append(thread); thread.start()

    total_files = len(threads); completed_files = 0; successful_uploads = 0; failed_uploads = 0; updated_indices = []
    while completed_files < total_files:
        try:
            result = upload_queue.get(timeout=0.2)
            completed_files += 1
            original_index = next((item["index"] for item in items_to_upload if item["renamed_name"] == result["file"]), -1)
            if original_index != -1:
                if result["url"]:
                    successful_uploads += 1; data[original_index][3] = result["url"]
                    data[original_index][0] = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f"); updated_indices.append(original_index)
                else: failed_uploads += 1; log_status(logging.ERROR, f"Bulk Upload: Failed for {result['file']}: {result['error']}")
            else: failed_uploads += 1; log_status(logging.ERROR, f"Bulk Upload: Could not map result file {result['file']} back to index.")
            log_status(logging.INFO, f"Bulk Upload progress: {completed_files}/{total_files}")
        except queue.Empty:
            if not any(t.is_alive() for t in threads): break
            time.sleep(0.1)

    if updated_indices:
        log_status(logging.INFO, "Bulk Upload: Saving updated CSV...")
        try:
            with open(csv_path, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.writer(csvfile); writer.writerow(header); writer.writerows(data)
            log_status("SUCCESS", "Bulk Upload: CSV log updated successfully.")
        except (IOError, csv.Error) as e:
            log_status(logging.ERROR, f"Bulk Upload: Failed to save updated CSV: {e}")
            # if UploaderApp.instance: UploaderApp.instance.bulk_upload_worker.signals.error.emit("CSV Save Error", f"Bulk Upload: Failed to save updated CSV: {e}")


    result_data = {"successful_uploads": successful_uploads, "failed_uploads": failed_uploads, "skipped_has_url": skipped_has_url, "skipped_missing": skipped_missing, "updated_rows": len(updated_indices)}
    # Show results via messagebox scheduled in main thread
    if UploaderApp.instance:
        summary = f"Bulk Upload Finished.\nSuccessful: {successful_uploads}\nFailed: {failed_uploads}\nSkipped (URL): {skipped_has_url}\nSkipped (Missing): {skipped_missing}\nCSV Rows Updated: {len(updated_indices)}"
        UploaderApp.instance.root.after(0, lambda: messagebox.showinfo("Bulk Upload Complete", summary))
    # if UploaderApp.instance: UploaderApp.instance.bulk_upload_worker.signals.finished.emit(result_data)


# --- Custom Rename Dialog Class ---
class RenameDialog(simpledialog.Dialog):
    def __init__(self, parent, original_filename, image_path):
        self.original_filename = original_filename
        self.image_path = image_path
        self.new_name_base = None # Store result here
        self.img_preview = None # To hold PhotoImage reference
        super().__init__(parent, title="Rename File")

    def body(self, master):
        ttk.Label(master, text=f"Original: {self.original_filename}", wraplength=350).pack(pady=5)

        # Image Preview
        if PIL_AVAILABLE:
            # Removed fixed width/height from ttk.Label
            preview_label = ttk.Label(master, text="Loading preview...", relief="sunken", anchor="center")
            preview_label.pack(pady=5)
            try:
                if os.path.exists(self.image_path):
                    img = Image.open(self.image_path)
                    img.thumbnail((PREVIEW_MAX_WIDTH, PREVIEW_MAX_HEIGHT - 50)) # Adjust size for dialog
                    self.img_preview = ImageTk.PhotoImage(img)
                    preview_label.config(image=self.img_preview, text="")
                else:
                    preview_label.config(text="Import file missing")
            except UnidentifiedImageError:
                 preview_label.config(text="Cannot preview (format?)")
            except Exception as e:
                preview_label.config(text="Preview Error")
                logger.warning(f"Error loading preview in dialog '{self.image_path}': {e}")
        else:
             ttk.Label(master, text="Image preview requires Pillow (pip install Pillow)").pack(pady=5)


        ttk.Label(master, text="Enter new name (no extension, blank to keep original):").pack()
        self.entry = ttk.Entry(master, width=50)
        self.entry.pack(pady=5)
        return self.entry # initial focus

    def apply(self):
        self.new_name_base = self.entry.get() # Store the entered value


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
        input("Critical error occurred. Check log file if possible. Exiting.")
    finally:
        try:
            logger.info("="*30 + " Script Execution Finished " + "="*30 + "\n")
            for handler in logger.handlers[:]:
                try:
                    handler.close()
                    logger.removeHandler(handler)
                except Exception: pass
        except Exception: pass
        # No need to deinit colorama for PyQt


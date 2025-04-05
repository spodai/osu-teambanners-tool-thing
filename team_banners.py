# all written with gpt, but hey it works :D
# rundown what it does:
## downloads all files from a public Google folder
## puts them in an import folder
## slaps that data into a CSV: DATE | ORIGINAL FILE NAME | NEW FILE NAME | S-UL.EU URL
## asks for user input to rename files that are not listed yet in the CSV
## copies those renamed files to an export folder
## uploads the files that were renamed to s-ul.eu
## fills on the CSV with the renames and URLs


import os
import shutil
import requests
import gdown
import csv
from datetime import datetime

# --- CONFIG ---
DRIVE_FOLDER_ID = ''
IMPORT_FOLDER = ""
EXPORT_FOLDER = ""
CSV_PATH = ""

SUL_UPLOAD_URL = "https://s-ul.eu/api/v1/upload"
SUL_API_KEY = ""

# --- FUNCTIONS ---
def create_folder_if_not_exists(folder_path):
    """Creates the folder if it does not exist."""
    if not os.path.exists(folder_path):
        os.makedirs(folder_path)

def download_drive_folder(folder_id, download_path):
    create_folder_if_not_exists(download_path)
    url = f"https://drive.google.com/drive/folders/{folder_id}"
    print(f"Downloading from {url}")
    gdown.download_folder(url, quiet=False, use_cookies=False, output=download_path)

def read_csv_for_uploaded_files(csv_path):
    """Reads the CSV file and returns a list of already uploaded filenames."""
    uploaded_files = set()
    if os.path.exists(csv_path):
        with open(csv_path, mode="r", encoding="utf-8") as f:
            reader = csv.reader(f)
            next(reader)  # Skip the header
            for row in reader:
                uploaded_files.add(row[1])  # The original filename is at index 1
    return uploaded_files

def prompt_rename_images(import_path, export_path, uploaded_files):
    create_folder_if_not_exists(export_path)
    renamed_files = []

    for filename in os.listdir(import_path):
        full_path = os.path.join(import_path, filename)
        if not os.path.isfile(full_path):
            continue

        if filename in uploaded_files:
            print(f"Skipping {filename}, already uploaded.")
            continue

        print(f"\nOriginal filename: {filename}")
        new_name = input("Enter new name (without extension): ").strip()
        ext = os.path.splitext(filename)[1]
        new_filename = new_name + ext
        new_path = os.path.join(export_path, new_filename)
        shutil.copy(full_path, new_path)

        renamed_files.append((filename, new_filename, new_path))
    return renamed_files

def upload_to_sul(file_path):
    with open(file_path, "rb") as f:
        files = {"file": f}
        data = {
            "wizard": "true",
            "key": SUL_API_KEY
        }
        response = requests.post(SUL_UPLOAD_URL, data=data, files=files)
        response.raise_for_status()
        return response.json()["url"]

def write_to_csv(csv_path, rows):
    file_exists = os.path.isfile(csv_path)
    with open(csv_path, mode="a", newline='', encoding="utf-8") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["date_downloaded", "original_filename", "renamed_filename", "s-ul.eu_url"])
        for row in rows:
            writer.writerow(row)

# --- MAIN ---
def main():
    print(">> Step 1: Downloading Google Drive folder...")
    download_drive_folder(DRIVE_FOLDER_ID, IMPORT_FOLDER)

    # Read the existing uploaded files from CSV
    uploaded_files = read_csv_for_uploaded_files(CSV_PATH)

    print("\n>> Step 2: Renaming files...")
    renamed = prompt_rename_images(IMPORT_FOLDER, EXPORT_FOLDER, uploaded_files)

    print("\n>> Step 3: Uploading to s-ul.eu...")
    log_rows = []
    for orig_name, renamed_name, path in renamed:
        print(f"Uploading {renamed_name}...")
        try:
            url = upload_to_sul(path)
            log_rows.append([
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                orig_name,
                renamed_name,
                url
            ])
        except Exception as e:
            print(f"Failed to upload {renamed_name}: {e}")

    print("\n>> Step 4: Writing index CSV...")
    write_to_csv(CSV_PATH, log_rows)

    print("\n✅ All done!")

if __name__ == "__main__":
    main()

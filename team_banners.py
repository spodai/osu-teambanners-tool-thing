## All written with GPT and Gemini (honestly Gemini did the harder cooking), but hey it works :D
# This is a tool for fetching files from a public Google Drive and then uploading them to s-ul.eu using API
# It makes a Config file for saving the drive ID and API key 
# It also makes a CSV file with: Timestamp,Original,Renamed,URL
# It also includes ways to delete and rename/reupload specific files
# You can run the main script multiple times, as it skips over all files already in the CSV file. 

## Usage:
# 1. Make a new folder, name it "team banners" or however you like
# 2. Copy paste this team_banners.py in this folder
# 3.1 Execute the script
# 3.2 Enter the public Google Drive folder ID or URL
# 3.3 Enter the s-ul.eu API key (found here: https://s-ul.eu/account/configurations)
# 4. Enter 1 to exececute the main script

## The dir the script makes looks like this:
# .
# ├── settings.conf
# ├── script.py
# ├── index.csv
# ├── Images import
# │   ├── image_01.jpg
# │   ├── image_02.jpg
# │   ├── image_03.jpg
# │   ├── image_04.jpg
# │   └── image_5.jpg
# └── Images export
#     ├── TEAM1.jpg
#     ├── TEAM2.jpg
#     ├── TEAM3.jpg
#     ├── TEAM4.jpg
#     └── TEAM5.jpg

## Download all the libraries:
# pip install requests gdown tabulate configparser

import os
import shutil
import requests
import gdown
import csv
import configparser
from datetime import datetime
from tabulate import tabulate

CONFIG_FILE = "settings.conf"

def init_config():
    if not os.path.exists(CONFIG_FILE):
        print("Config not found. Let's set it up.")
        drive_id = input("Enter Google Drive folder ID or URL: ").strip()
        api_key = input("Enter s-ul.eu API key: ").strip()
        base_dir = os.path.dirname(os.path.abspath(__file__))

        config = configparser.ConfigParser()
        config['DEFAULT'] = {
            'drive_id': drive_id,
            'api_key': api_key,
            'base_dir': base_dir
        }

        with open(CONFIG_FILE, 'w') as configfile:
            config.write(configfile)
        print("Config saved.\n")

def load_config():
    config = configparser.ConfigParser()
    config.read(CONFIG_FILE)
    return config['DEFAULT']

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

def update_settings():
    config = configparser.ConfigParser()
    config.read(CONFIG_FILE)

    while True:
        clear_screen()
        current = config['DEFAULT']
        print("=== Settings Menu ===\n")
        print(f"1. Google Drive Folder ID/URL: {current['drive_id']}")
        print(f"2. S-UL API Key: {current['api_key']}")
        print(f"3. Base Folder: {current['base_dir']}")
        print("4. Exit Settings Menu")

        choice = input("\nChoose setting to change (1-4): ").strip()

        if choice == '1':
            new_id = input("Enter new Google Drive Folder ID or URL: ").strip()
            config['DEFAULT']['drive_id'] = new_id
        elif choice == '2':
            new_key = input("Enter new S-UL API key: ").strip()
            config['DEFAULT']['api_key'] = new_key
        elif choice == '3':
            new_path = input("Enter new base folder path: ").strip()
            if os.path.isdir(new_path):
                config['DEFAULT']['base_dir'] = new_path
            else:
                input("[ERROR] Invalid folder path. Press Enter to continue...")
                continue
        elif choice == '4':
            clear_screen()
            break
        else:
            input("Invalid option. Press Enter to continue...")
            continue

        with open(CONFIG_FILE, 'w') as configfile:
            config.write(configfile)
        input("[OK] Setting updated! Press Enter to continue...")


def download_drive_folder(drive_id, download_path):
    os.makedirs(download_path, exist_ok=True)
    url = f"https://drive.google.com/drive/folders/{drive_id}" if "drive.google.com" not in drive_id else drive_id
    print(f"Downloading from {url}")
    gdown.download_folder(url, quiet=False, use_cookies=False, output=download_path)

def prompt_rename_images(import_path, export_path, uploaded_files, csv_path):
    os.makedirs(export_path, exist_ok=True)
    renamed = []
    existing_renamed = set()
    if os.path.exists(csv_path):
        with open(csv_path, 'r', newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                existing_renamed.add(row['Original'])

    for file in os.listdir(import_path):
        if file in uploaded_files or file in existing_renamed:
            continue
        src = os.path.join(import_path, file)
        if not os.path.isfile(src):
            continue
        print(f"\nOriginal filename: {file}")
        new_name = input("New name (no ext): ").strip()
        ext = os.path.splitext(file)[1]
        dest = os.path.join(export_path, new_name + ext)
        shutil.copy(src, dest)
        renamed.append((file, new_name + ext, dest))
    return renamed

def upload_to_sul(file_path, api_key):
    with open(file_path, "rb") as f:
        files = {"file": f}
        data = {"wizard": "true", "key": api_key}
        res = requests.post("https://s-ul.eu/api/v1/upload", data=data, files=files)
        res.raise_for_status()
        return res.json()["url"]

def write_to_csv(csv_path, data):
    write_header = not os.path.exists(csv_path)
    with open(csv_path, "a", newline='', encoding="utf-8") as f:
        writer = csv.writer(f)
        if write_header:
            writer.writerow(["Timestamp", "Original", "Renamed", "URL"])
        for row in data:
            writer.writerow([datetime.now(), row[0], row[1], row[2]])

def read_uploaded_files(csv_path):
    if not os.path.exists(csv_path):
        return set()
    with open(csv_path, newline='', encoding="utf-8") as f:
        return {row[0] for i, row in enumerate(csv.reader(f)) if i != 0}

def show_csv(csv_path):
    clear_screen()
    print("=== index.csv ===")
    if not os.path.exists(csv_path):
        print("No CSV data yet.")
        return
    with open(csv_path, encoding="utf-8") as f:
        table = list(csv.reader(f))
    print("\n" + tabulate(table[1:], headers=table[0], tablefmt="grid"))

def rename_existing_item(csv_path, base_dir, config):
    while True:  # Keep the rename menu active until the user chooses to exit
        clear_screen()
        if not os.path.exists(csv_path):
            print("CSV file not found.")
            input("Press Enter to return to the main menu...")
            return

        with open(csv_path, 'r', newline='', encoding='utf-8') as csvfile:
            reader = list(csv.DictReader(csvfile))

        if not reader:
            print("No entries found in the CSV.")
            input("Press Enter to return to the main menu...")
            return

        print("\n=== Existing Items ===")
        for idx, row in enumerate(reader, start=1):
            print(f"{idx}. {row['Renamed']} (Original: {row['Original']})")

        print("\n0. Back to Main Menu")  # Option to exit the rename menu

        choice = input("\nEnter the number of the item you want to rename: ").strip()

        if choice == '0':
            break  # Exit the rename menu loop

        try:
            item_number = int(choice) - 1
            if item_number < 0 or item_number >= len(reader):
                print("Invalid choice.")
                input("Press Enter to try again...")
                continue
        except ValueError:
            print("Please enter a valid number.")
            input("Press Enter to try again...")
            continue

        selected_row = reader[item_number]
        old_name = selected_row['Renamed']
        original_name = selected_row['Original']
        old_url = selected_row['URL']
        _, ext = os.path.splitext(old_name)

        new_name_input = input(f"Enter the new name for '{old_name}' (without extension): ").strip()
        if not new_name_input:
            print("Name cannot be empty.")
            input("Press Enter to try again...")
            continue

        new_name = f"{new_name_input}{ext}"

        old_path = os.path.join(base_dir, "Images export", old_name)
        new_path = os.path.join(base_dir, "Images export", new_name)

        renamed_success = False
        try:
            if os.path.exists(old_path):
                os.rename(old_path, new_path)
                renamed_success = True
            else:
                print(f"File not found: {old_path}")
                input("Press Enter to continue...")
                continue
        except Exception as e:
            print(f"Failed to rename file: {e}")
            input("Press Enter to continue...")
            continue

        if renamed_success:
            # Update the row
            reader[item_number]['Renamed'] = new_name

            print("[WARNING] First manually delete the already uploaded file before re-uploading! Else the original URL will return without changes to it's name.")
            print("[WARNING] Uploaded files cannot be renamed in s-ul frontend.")
            reupload = input("Do you want to re-upload this file? (y/n): ").strip().lower()
            if reupload == 'y':
                try:
                    url = upload_to_sul(new_path, config['api_key'])
                    reader[item_number]['URL'] = url
                    print(f"[OK] File re-uploaded. New URL: {url}")
                except requests.exceptions.RequestException as e:
                    print(f"[ERROR] re-upload failed: {e}")
                except KeyError:
                    print("[ERROR] Could not retrieve upload URL.")
            elif reupload == 'n':
                print("Skipping re-upload.")
            else:
                print("Invalid choice. Skipping re-upload.")

            # Save back to CSV
            with open(csv_path, 'w', newline='', encoding='utf-8') as csvfile:
                fieldnames = reader[0].keys()
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(reader)

            print("[OK] File renamed and CSV updated.")
            input("Press Enter to continue renaming, then 0 to go back to the main menu...") # Keep the menu active

def delete_entry(csv_path, base_dir):
    clear_screen()
    print("=== Delete file ===")
    print("[WARNING] This script cannot delete file using the s-ul API.")
    if not os.path.exists(csv_path):
        print("CSV file not found.")
        return

    with open(csv_path, newline='', encoding="utf-8") as f:
        rows = list(csv.reader(f))

    for idx, row in enumerate(rows[1:], 1):
        print(f"{idx}. {row[2]}")

    choice = input("Which entry to delete (number): ")
    try:
        i = int(choice)
        removed = rows.pop(i)
        print(f"Removed: {removed}")
        for folder in ["Images import", "Images export"]:
            path = os.path.join(base_dir, folder, removed[2])
            if os.path.exists(path):
                os.remove(path)
    except:
        print("Invalid input.")
        return

    with open(csv_path, "w", newline='', encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerows(rows)

def start_script(config):
    base_dir = config["base_dir"]
    import_path = os.path.join(base_dir, "Images import")
    export_path = os.path.join(base_dir, "Images export")
    csv_path = os.path.join(base_dir, "index.csv")

    download_drive_folder(config["drive_id"], import_path)
    uploaded = read_uploaded_files(csv_path)
    renamed = prompt_rename_images(import_path, export_path, uploaded, csv_path)

    new_rows = []
    for original, new_name, path in renamed:
        url = upload_to_sul(path, config["api_key"])
        new_rows.append((original, new_name, url))
        print(f"Uploaded: {url}")

    write_to_csv(csv_path, new_rows)

def menu():
    init_config()
    config = load_config()
    base_dir = config["base_dir"]
    csv_path = os.path.join(base_dir, "index.csv")

    while True:
        print("\n=== Main Menu ===")
        print("1. Start script")
        print("2. Show CSV data")
        print("3. Change settings")
        print("4. Delete item")
        print("5. Rename item")
        print("6. Exit")

        choice = input("> ").strip()

        if choice == "1":
            start_script(config)
        elif choice == "2":
            show_csv(csv_path)
        elif choice == "3":
            update_settings()
            config = load_config()
        elif choice == "4":
            delete_entry(csv_path, base_dir)
        elif choice == "5":
            rename_existing_item(csv_path, base_dir, config)
        elif choice == "6":
            break
        else:
            print("Invalid choice.")


if __name__ == "__main__":
    menu()

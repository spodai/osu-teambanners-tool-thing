## All written with GPT and Gemini (honestly Gemini did the harder cooking), but hey it works :D
# A tool to fetch files from a public Google Drive, upload them to s-ul.eu via API, and manage the process.
# - Saves Google Drive ID and API key in a Config file.
# - Creates a CSV log with: Timestamp, Original Filename, Renamed Filename, s-ul.eu URL.
# - Allows deleting and renaming/reuploading specific uploaded files.
# - Subsequent runs skip files already processed and logged in the CSV.

## Usage:
# 1. Create a new directory (e.g., "team banners").
# 2. Place this script (team_banners.py) inside the new directory.
# 3. Run the script.
# 4. Follow the prompts to enter the public Google Drive folder ID or URL.
# 5. Enter your s-ul.eu API key (found at https://s-ul.eu/account/configurations).
# 6. Select option 4 from the main menu to start the file processing.

## Directory structure created by the script:
# .
# ├── settings.conf       (Configuration file)
# ├── team_banners.py     (This script)
# ├── index.csv           (Log of processed files)
# ├── Images import/      (Downloaded files from Google Drive)
# │   ├── image_01.jpg
# │   ├── image_02.jpg
# │   └── ...
# └── Images export/      (Renamed files for s-ul.eu upload)
#     ├── TEAM1.jpg
#     ├── TEAM2.jpg
#     └── ...

## Install required libraries:
# pip install requests gdown tabulate configparser

import os
import shutil
import requests
import gdown
import csv
import configparser
import shutil
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
        print("0. Back to Main Menu")  # Changed from 4 to 0

        choice = input("\nChoose setting to change (1-3, or 0 to exit): ").strip()

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
        elif choice == '0':  # Changed from '4' to '0'
            clear_screen()
            break
        else:
            input("[ERROR] Invalid option. Press Enter to continue...")
            continue

        with open(CONFIG_FILE, 'w') as configfile:
            config.write(configfile)
        input("[OK] Setting updated! Press Enter to continue...")


def download_drive_folder(drive_id, download_path, csv_path):
    clear_screen()
    print("=== Download from Google Drive ===")

    url = f"https://drive.google.com/drive/folders/{drive_id}" if "drive.google.com" not in drive_id else drive_id
    print(f"Downloading from {url}")

    os.makedirs(download_path, exist_ok=True)
    existing_files_import = set(os.listdir(download_path))
    uploaded_originals = read_uploaded_originals(csv_path)
    newly_downloaded = []
    skipped_count = 0

    try:
        gdown.download_folder(url, output=download_path, quiet=True, use_cookies=False, remaining_ok=True)
        current_files_import = set(os.listdir(download_path))
        for file in current_files_import:
            if file not in existing_files_import and file not in uploaded_originals:
                newly_downloaded.append(file)
            elif file in existing_files_import or file in uploaded_originals:
                skipped_count += 1

        print(f"\n[OK] Download attempt complete.")
        if newly_downloaded:
            print(f"Downloaded {len(newly_downloaded)} new files.")
            print(f"Press Enter to rename the following new files:")
            for file in newly_downloaded:
                print(f"- {file}")
            input()
            clear_screen()
            return newly_downloaded  # Return the list of new files
        else:
            print("[OK] No new files downloaded.")
            # Don't prompt to return here, the renaming logic in start_script will handle it
            return [] # Return an empty list

    except Exception as e:
        print(f"[ERROR] An error occurred during download: {e}")
        input("\nPress Enter to return to the main menu...")
        clear_screen()
        return [] # Return an empty list if an error occurred

def read_uploaded_originals(csv_path):
    if not os.path.exists(csv_path):
        return set()
    with open(csv_path, newline='', encoding="utf-8") as f:
        reader = csv.reader(f)
        next(reader, None)  # Skip the header row
        return {row[1] for row in reader}  # Collect original filenames

def prompt_rename_images(import_path, export_path, uploaded_files, csv_path, new_files):
    os.makedirs(export_path, exist_ok=True)
    renamed = []
    existing_renamed = set()
    if os.path.exists(csv_path):
        with open(csv_path, 'r', newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                existing_renamed.add(row['Original'])

    files_to_rename = list(new_files) if new_files else [f for f in os.listdir(import_path) if f not in uploaded_files and f not in existing_renamed and os.path.isfile(os.path.join(import_path, f))]

    if files_to_rename:
        if new_files:
            print("=== New filenames ===")
        else:
            print("=== Renaming Images ===")

        for file in files_to_rename:
            src = os.path.join(import_path, file)
            if not os.path.isfile(src):
                continue
            print(f"\nOriginal filename: {file}")
            new_name_base = input("New name (no ext, leave blank for original): ").strip()
            _, ext = os.path.splitext(file)
            if not new_name_base:
                new_name = file
            else:
                new_name = new_name_base + ext
            dest = os.path.join(export_path, new_name)
            shutil.copy(src, dest)
            renamed.append((file, new_name, dest))
    else:
        print("No new images to rename.")

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
            # Use the datetime class within the datetime module to get the current time
            writer.writerow([datetime.datetime.now(), row[0], row[1], row[2]])

def read_uploaded_files(csv_path):
    if not os.path.exists(csv_path):
        return set()
    with open(csv_path, newline='', encoding="utf-8") as f:
        return {row[0] for i, row in enumerate(csv.reader(f)) if i != 0}

def show_csv(csv_path):
    while True:
        clear_screen()
        print("=== index.csv ===")
        if not os.path.exists(csv_path):
            print("No CSV data yet.")
        else:
            with open(csv_path, encoding="utf-8") as f:
                table = list(csv.reader(f))
            if table:
                print("\n" + tabulate(table[1:], headers=table[0], tablefmt="grid"))
            else:
                print("CSV file is empty.")

        print("\n0. Back to Main Menu")
        choice = input("> ").strip()

        if choice == '0':
            clear_screen()
            break
        else:
            print("[ERROR] Invalid choice. Press Enter to try again...")
            input()

def rename_existing_item(csv_path, base_dir, config):
    while True:
        clear_screen()
        if not os.path.exists(csv_path):
            print("[ERROR] CSV file not found.")
            input("Press Enter to return to the main menu...")
            clear_screen()  # Clear screen before returning
            return

        with open(csv_path, 'r', newline='', encoding='utf-8') as csvfile:
            reader = list(csv.DictReader(csvfile))

        if not reader:
            print("No entries found in the CSV.")
            input("Press Enter to return to the main menu...")
            clear_screen()  # Clear screen before returning
            return

        print("\n=== Existing Items ===")
        for idx, row in enumerate(reader, start=1):
            print(f"{idx}. {row['Renamed']} (Original: {row['Original']})")

        print("\n0. Back to Main Menu")
        choice = input("\nEnter the number of the item you want to rename: ").strip()

        if choice == '0':
            clear_screen()  # Clear screen before breaking out of the loop
            break

        try:
            item_number = int(choice) - 1
            if item_number < 0 or item_number >= len(reader):
                print("[ERROR] Invalid choice.")
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
                print(f"[ERROR] File not found: {old_path}")
                input("Press Enter to continue...")
                continue
        except Exception as e:
            print(f"[ERROR] Failed to rename file: {e}")
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
                print("[OK] Skipping re-upload.")
            else:
                print("[ERROR] Invalid choice. Skipping re-upload.")

            # Save back to CSV
            with open(csv_path, 'w', newline='', encoding='utf-8') as csvfile:
                fieldnames = reader[0].keys()
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(reader)

            print("[OK] File renamed and CSV updated.")
            input("Press Enter to continue renaming or enter and then 0 to go back...")

def delete_entry(csv_path, base_dir):
    while True:
        clear_screen()
        print("=== Delete file ===")
        print("[WARNING] Deleting items here only removes them locally and NOT on s-ul.eu.")
        if not os.path.exists(csv_path):
            print("[ERROR] CSV file not found.")
            input("Press Enter to return to the main menu...")
            clear_screen()  # Clear screen before returning
            return

        with open(csv_path, newline='', encoding="utf-8") as f:
            rows = list(csv.reader(f))

        if len(rows) <= 1:
            print("[ERROR] No entries found in the CSV to delete.")
            input("Press Enter to return to the main menu...")
            clear_screen()  # Clear screen before returning
            return

        print("\n=== Existing Items ===")
        for idx, row in enumerate(rows[1:], 1):
            print(f"{idx}. {row[2]}")

        print("\n0. Back to Main Menu")
        choice = input("Which entry to delete (number): ").strip()

        if choice == '0':
            clear_screen()  # Clear screen before breaking out of the loop
            break

        try:
            i = int(choice)
            if 1 <= i < len(rows):
                removed = rows.pop(i)
                print(f"Removed: {removed[2]} from the CSV.")
                for folder in ["Images import", "Images export"]:
                    path = os.path.join(base_dir, folder, removed[2])
                    if os.path.exists(path):
                        try:
                            os.remove(path)
                            print(f"Deleted local file: {path}")
                        except Exception as e:
                            print(f"[ERROR] failed to delete local file {path}: {e}")
                with open(csv_path, "w", newline='', encoding="utf-8") as f:
                    writer = csv.writer(f)
                    writer.writerows(rows)
                input("Press Enter to continue deleting or enter and then 0 to go back...")
            else:
                print("[ERROR] Invalid choice.")
                input("Press Enter to try again...")
        except ValueError:
            print("[ERROR] Invalid input.")
            input("Press Enter to try again...")

def start_script(config):
    base_dir = config["base_dir"]
    import_path = os.path.join(base_dir, "Images import")
    export_path = os.path.join(base_dir, "Images export")
    csv_path = os.path.join(base_dir, "index.csv")

    os.makedirs(import_path, exist_ok=True)
    newly_downloaded_files = download_drive_folder(config["drive_id"], import_path, csv_path)
    uploaded = read_uploaded_files(csv_path)
    files_to_rename = list(newly_downloaded_files) + [
        f for f in os.listdir(import_path)
        if f not in uploaded and os.path.isfile(os.path.join(import_path, f))
    ]

    if files_to_rename:
        renamed = prompt_rename_images(import_path, export_path, uploaded, csv_path, newly_downloaded_files)

        new_rows = []
        for original, new_name, path in renamed:
            url = upload_to_sul(path, config["api_key"])
            new_rows.append((original, new_name, url))
            print(f"Uploaded: {url}")

        write_to_csv(csv_path, new_rows)
        input("\nPress Enter to return to the main menu...")
        clear_screen()
    else:
        input("\nNo new files to download or rename. Press Enter to return to the main menu...")
        clear_screen()

def get_folder_tree_with_sizes(folder_path):
    tree_data = []
    total_size = 0

    def get_size(path):
        try:
            return os.path.getsize(path)
        except OSError:
            return 0

    def build_tree(directory, prefix=""):
        nonlocal total_size
        items = os.listdir(directory)
        num_items = len(items)
        for i, item in enumerate(items):
            path = os.path.join(directory, item)
            is_last = i == num_items - 1
            indicator = "└── " if is_last else "├── "
            size_bytes = get_size(path)
            size_readable = format_size(size_bytes)
            tree_data.append((prefix + indicator + item, size_readable))
            total_size += size_bytes
            if os.path.isdir(path):
                build_tree(path, prefix + ("    " if is_last else "│   "))

    def format_size(bytes):
        if bytes == 0:
            return "0 B"
        units = ['B', 'KB', 'MB', 'GB', 'TB']
        i = 0
        while bytes >= 1024 and i < len(units) - 1:
            bytes /= 1024
            i += 1
        return f"{bytes:.2f} {units[i]}"

    # Add the root directory with its total size first
    root_size = sum(get_size(os.path.join(folder_path, item)) for item in os.listdir(folder_path))
    tree_data.append((os.path.abspath(folder_path), format_size(root_size)))
    build_tree(folder_path)
    return tree_data

def show_folder_structure(config):
    base_dir = config['base_dir']
    while True:
        clear_screen()
        print("=== Folder Structure ===")
        folder_tree = get_folder_tree_with_sizes(base_dir)
        headers = ["Name", "Size"]
        print(tabulate(folder_tree, headers=headers, tablefmt="plain"))
        print("\nPress Enter to return to the main menu...")
        input()
        clear_screen()
        break

def nuke_everything(base_dir):
    clear_screen()
    print("=== Nuke Everything ===")
    print(f"[WARNING] This action will PERMANENTLY delete the following folder and all its contents:")
    print(f"- Folder: {base_dir}")

    confirmation = input("Are you sure? Type 'yes' to confirm: ").strip()
    if confirmation == 'yes':
        confirmation2 = input("Type 'yes' again to to proceed with deleting '{base_dir}': ").strip()
        if confirmation2 == 'yes':
            print("\nInitiating nuking sequence...")
            try:
                parent_dir = os.path.dirname(base_dir)
                folder_to_delete = base_dir

                if os.path.exists(folder_to_delete):
                    shutil.rmtree(folder_to_delete)
                    print(f"Deleted folder: {folder_to_delete}")
                else:
                    print(f"Folder not found: {folder_to_delete}")
                print("\nNuking complete. The program's working folder and its contents have been deleted.")
                exit()
            except Exception as e:
                print(f"\nP[ERROR] Nuking has failed: {e}")
        else:
            print("\nNuking aborted.")
    else:
        print("\n Nuking aborted.")
    input("\nPress Enter to return to the main menu...")
    clear_screen()

def show_explanation():
    clear_screen()
    print("=== How This Program Works ===")
    print("\nThis tool automates fetching, renaming, and uploading images to s-ul.eu.")
    print("Here's how the menu options correspond to the program's steps and data:\n")

    print("0. How this program works:")
    print("   └── Displays this detailed explanation of the program's")
    print("       features and workflow.")

    print("1. Show CSV data:")
    print("   └── Data Display:")
    print("       └── Presents the contents of the 'index.csv' file, showing")
    print("           the logged information.")

    print("2. Show folder structure:")
    print("   └── System Information:")
    print("       └── Displays a tree-like view of the script's working")
    print("           directory, including file sizes.")

    print("3. Change settings:")
    print("   └── Configuration:")
    print("       ├── Google Drive ID/URL:")
    print("       │   └── The source of the images to download.")
    print("       ├── s-ul.eu API key:")
    print("       │   └── Your authentication key for uploading.")
    print("       └── Base folder:")
    print("           └── The main directory where the script operates and")
    print("               stores its files and configuration.")

    print("4. Start script:")
    print("   ├── Downloading:")
    print("   │   └── Fetches new files from the configured Google Drive")
    print("   │       folder ('Images import'), skipping existing ones.")
    print("   ├── Renaming:")
    print("   │   └── Prompts you to rename the newly downloaded files")
    print("   │       ('Images export').")
    print("   ├── Uploading:")
    print("   │   └── Uploads the renamed files to s-ul.eu.")
    print("   └── Logging:")
    print("       └── Records the original name, new name, and s-ul.eu URL")
    print("           in 'index.csv'.")

    print("5. Rename item:")
    print("   └── Local File and 'index.csv' Management:")
    print("       ├── Renames a local image file in 'Images export'.")
    print("       ├── Updates the corresponding entry in 'index.csv'.")
    print("       └── Offers the option to re-upload the renamed file.")

    print("6. Delete item:")
    print("   └── 'index.csv' Management:")
    print("       ├── Removes a specific entry from the log file.")
    print("       └── Deletes the corresponding local image files (Import and Export folders).")

    print("7. Nuke:")
    print("   └── WARNING: Deletes all downloaded and exported images,")
    print("       the CSV log, the configuration file, and the script's")
    print("       containing folder. Has double conformation.")

    print("8. Exit:")
    print("   └── Terminates the program.")

    print("\nFor the latest version and more information, visit the repository:")
    print("https://github.com/spodai/stuff/blob/main/team_banners.py")
    input("\nPress Enter to return to the main menu...")
    clear_screen()

def menu():
    init_config()
    config = load_config()
    base_dir = config["base_dir"]
    csv_path = os.path.join(base_dir, "index.csv")

    while True:
        print("\n=== Main Menu ===")
        print("0. How this program works")
        print("1. Show CSV data")
        print("2. Show folder structure")
        print("3. Change settings")
        print("4. Start script")
        print("5. Rename item")
        print("6. Delete item")
        print("7. Nuke")
        print("8. Exit")

        choice = input("> ").strip()

        if choice == "0":
            show_explanation()
        elif choice == "1":
            show_csv(csv_path)
        elif choice == "2":
            show_folder_structure(config)
        elif choice == "3":
            update_settings()
            config = load_config()
        elif choice == "4":
            start_script(config)
        elif choice == "5":
            rename_existing_item(csv_path, base_dir, config)
        elif choice == "6":
            delete_entry(csv_path, base_dir)
        elif choice == "7":
            nuke_everything(base_dir)
        elif choice == "8":
            clear_screen()
            break
        else:
            print("Invalid choice.")

if __name__ == "__main__":
    clear_screen()
    import datetime
    menu()

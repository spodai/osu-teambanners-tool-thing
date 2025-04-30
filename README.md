# Team Banner Processing Scripts

This repository contains Python scripts for fetching images (from Google Drive or locally), renaming them, optionally uploading them to s-ul.eu, and logging the process.

## Folder Structure

-   **/cli**: Contains the Command Line Interface (CLI) versions of the script.
    -   `team_banners.py`: Full-featured CLI script with menus, color support, logging, configuration, CSV editing, and bulk actions.
    -   `team_banners_lite.py`: A simplified, automatic CLI version focused on download, rename, upload, and logging.
-   **/gui**: Contains the Graphical User Interface (GUI) versions built with Tkinter.
    -   `team_banners_Tkinter.py`: The main GUI application providing the same core features as the full CLI script in a graphical window.
    -   `problem_solver_util_thing.py`: A utility GUI tool launched from the main GUI app to help diagnose and fix common issues with the CSV file or image files.

## Setup

Requires Python 3 and necessary libraries. You can typically install them using pip:

```bash
# For GUI versions (includes CLI requirements)
pip install requests gdown configparser colorama \
            Pillow pyperclip

# For CLI versions only
pip install requests gdown tabulate \
            configparser colorama
UsageCLI ScriptsCreate a new directory for the script (e.g., "team_banners_cli").Place the desired script (team_banners.py or team_banners_lite.py) inside the new directory.Run the script from your terminal (e.g., python team_banners.py).Follow the prompts for configuration (Google Drive ID, API key, preferences) on the first run.For team_banners.py, select actions from the menu. team_banners_lite.py runs automatically after setup.GUI ScriptsEnsure all required libraries (including Pillow and pyperclip) are installed.Run team_banners_Tkinter.py (e.g., python team_banners_Tkinter.py).Use the graphical interface to configure settings and perform actions.The "Problem Fixer" utility can be launched via a button in the main GUI.Directory Structure (Created by Scripts)When run, the scripts will create the following structure within their directory:.
├── settings.conf         # Configuration file
├── team_banners*.py      # The script file itself
├── index.csv             # Log of processed files
├── script_activity.log   # Activity log file (if enabled)
├── Images import/        # Downloaded/User-placed source images
│   ├── image_01.jpg
│   └── ...
└── Images export/        # Renamed images ready for upload
    ├── TEAM1.jpg
    └── ...
(Note: The GUI Problem Fixer creates problem_fixer.log)NotesTerminal Recommendation (CLI): For the CLI scripts, using terminals like Windows PowerShell, cmd, MobaXterm, or Termius might provide a more stable experience than the default Python IDLE shell.Configuration: Settings are stored in settings.conf. You can edit this file directly or use the settings menu in the full CLI/GUI

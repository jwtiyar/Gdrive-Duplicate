# DriveCleaner

A fast, unified tool to clean up your Google Drive. It can act as a **Deduplicator** or a **Selective Deleter** (searching by name/MIME type). Features a gorgeous, responsive web-based GUI built on FastAPI and a zero-dependency vanilla JS/CSS frontend.

This application runs **strictly locally** on your own machine. It accesses the Google Drive API directly using your own developer credentials, meaning no third party ever has access to your files or tokens.

---

## Setup Guide

### 1. Get Google API Credentials
Because the app is run locally, you need to create your own Google Cloud project and API credentials to authenticate:

1. Go to the [Google Cloud Console](https://console.cloud.google.com/).
2. Create a new project (e.g., `DriveCleaner`).
3. In the sidebar, navigate to **APIs & Services** > **Library**, search for **Google Drive API**, and click **Enable**.
4. Configure the **OAuth Consent Screen**:
   - Choose **External** user type.
   - Enter your email and basic app details.
   - Under **Scopes**, click **Add or Remove Scopes** and add the `https://www.googleapis.com/auth/drive` scope (or `.../auth/drive.metadata.readonly` if you only want to scan without deleting).
   - Add your own Google email address as a **Test User** (since the app is in Testing mode).
5. Generate credentials:
   - Navigate to **APIs & Services** > **Credentials**.
   - Click **Create Credentials** > **OAuth Client ID**.
   - Select **Desktop Application** as the application type, name it, and click **Create**.
6. Download the JSON credentials file:
   - Find your new Client ID under *OAuth 2.0 Client IDs* and click the **Download JSON** icon.
   - Save this file as **`credentials.json`** in the root directory of this project.

---

### 2. Install & Run the Application

This project uses `uv` for fast dependency and virtual environment management.

1. Ensure you have [uv](https://github.com/astral-sh/uv) installed.
2. Start the application:
   ```bash
   uv run python app.py
   ```
   *(This will automatically set up the virtual environment, install dependencies, and start the FastAPI server.)*
3. Open your browser and navigate to:
   👉 **[http://localhost:8080](http://localhost:8080)**

---

### 3. Authenticate & Clean
1. On the application homepage under the **Settings & Status** tab, click **Connect Google Account**.
2. A browser tab will open asking you to sign in with your Google account.
3. Since your Google Cloud project is not verified, you will see a warning screen ("Google hasn't verified this app"). Click **Advanced** and then click **Go to [Project Name] (unsafe)** to proceed.
4. Grant the requested Drive permissions.
5. Once authorized, a **`token.json`** file will be saved locally in your project folder, and you can close the authentication tab and return to the dashboard to start scanning.
6. *To log out or switch accounts, click **Disconnect Google Account** in the settings page to remove the local token.*

---

## Features & UI

* **Duplicate Finder:** Groups duplicate files by exact MD5 checksum and file size. Toggles are available to require exact name matches.
* **Selective Deleter:** Mass filters and deletes files by name patterns, file size boundaries (min/max MB), or MIME type categories (Images, Videos, Documents, Archives, Audio, etc.).
* **Safe Deletions:** Supports moving files to the Google Drive Trash (recoverable) or purging them permanently.
* **Local Deletion Logs:** Generates a local, timestamped log file (e.g., `deletion_history_20260624_120000.txt`) for auditing all operations.

---

## CLI Usage (Command Line)

The backend engine (`gdrive_dedup.py`) can also be run headlessly from the terminal:

```bash
# Dry-run: Just print a report of duplicates and how much space you'll save
uv run python gdrive_dedup.py

# Move all duplicates to the Google Drive Trash (Recoverable)
uv run python gdrive_dedup.py --delete

# Selective Delete: Preview all files containing 'temp' or 'backup' in their name
uv run python gdrive_dedup.py --names "temp,backup"

# Selective Delete: Trash all images in your Drive
uv run python gdrive_dedup.py --types "Images" --delete

# Selective Delete: Trash all files larger than 100 MB and smaller than 500 MB
uv run python gdrive_dedup.py --min-size-mb 100 --max-size-mb 500 --delete
```

### CLI Flags
* `--delete`: Move files to the Google Drive Trash.
* `--purge`: Permanently purge files from your drive (Irreversible).
* `--export-csv`: Generates a detailed CSV log of what was kept/deleted, including exact folder paths.
* `--shared-drives`: Includes files inside Google Shared Drives during the scan.
* `--min-size-mb`: Minimum file size in MB for selective filtering.
* `--max-size-mb`: Maximum file size in MB for selective filtering.

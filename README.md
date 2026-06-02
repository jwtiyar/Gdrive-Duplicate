# DriveCleaner

A fast, unified tool to clean up your Google Drive. It can act as a **Deduplicator** or a **Selective Deleter** (searching by name/MIME type). Features a gorgeous, responsive web-based GUI and pre-compiled executables for ease of use.

## Setup & Execution

### Option 1: Use the Pre-compiled Executables (Recommended)
You do not need Python installed! Simply download the latest release for your OS from the Releases page (built automatically via GitHub Actions & GitLab CI):
- `DriveCleaner-Windows.exe` (Windows)
- `DriveCleaner-Linux` (Linux Binary)

### Option 2: Run from Source
This tool uses `uv` for fast dependency management.
1. Ensure you have [uv](https://github.com/astral-sh/uv) installed.
2. Run the application:
   ```bash
   uv run uvicorn app:app --port 8000 --host 127.0.0.1
   ```

## Using the Application

1. **Get Google Credentials:**
   Before running the app, you must generate an OAuth 2.0 Client ID for a Desktop Application in the Google Cloud Console. 
   Download the file and save it as `credentials.json` in the same directory as the executable/script.
2. **Launch & Authenticate:**
   Open the application in your browser (usually `http://127.0.0.1:8000`).
   Click **Connect Google Account** to authorize the app. A `token.json` will be saved locally so you stay logged in.
3. **Clean Your Drive:**
   - **Duplicate Finder:** Finds and groups exact duplicates by MD5 hash and file size. You can optionally toggle "Require Exact File Name Match" if you only want to group files that share the exact same filename. Use the "Select All" / "Deselect All" shortcuts to quickly manage hundreds of duplicates.
    - **Selective Deleter:** Mass delete files by name, MIME type category (e.g., delete all `Images`, or all files containing `temp`), or file size boundaries (e.g., minimum/maximum size in MB).
4. **Deletion Logs:**
   Every deletion run (in both GUI and CLI modes) generates a local, timestamped log file (e.g., `deletion_history_20260602_153000.txt`) listing all successfully processed files, their Google Drive ID, and their sizes for safety and auditing.

## CLI Usage (Command Line)

The backend engine (`gdrive_dedup.py`) can also be run entirely headlessly from the terminal for automation purposes.

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
- `--delete`: Move files to the Google Drive Trash.
- `--purge`: Permanently purge files from your drive (Irreversible).
- `--export-csv`: Generates a detailed CSV log of what was kept/deleted, including exact folder paths.
- `--shared-drives`: Includes files inside Google Shared Drives during the scan.
- `--min-size-mb`: Minimum file size in MB for selective filtering.
- `--max-size-mb`: Maximum file size in MB for selective filtering.

## Architecture Highlights
- **Crash-Proof Engine**: Uses exponential backoff. If you have 500,000 files, it won't crash when Google rate-limits the API.
- **Full Path Resolution**: Safely resolves nested directory structures so you know exactly which folder a duplicate lives in before deleting it.
- **FastAPI Backend**: The app uses a fast async backend and serves a zero-dependency vanilla JS/CSS frontend.

# Google Drive Cleaner

A fast, unified tool to clean up your Google Drive. It can act as a **Deduplicator** or a **Selective Deleter** (searching by name/MIME type). 

## Setup

This tool uses [uv](https://github.com/astral-sh/uv) to manage dependencies quickly.

1. Ensure you have `uv` installed.
2. Put your Google Drive `credentials.json` in this folder (downloaded from Google Cloud Console).
3. The first time you run it, it will open a browser to authenticate and create a `token.json`.

## Usage

You can use the `uv run` command to run the script. It automatically handles all Python packages for you.

### 1. Duplicate Finder (Default Mode)
Finds and deletes exact duplicate files across your Drive. It keeps the oldest file and deletes the rest.

```bash
# Dry-run: Just print a report of duplicates and how much space you'll save
uv run python gdrive_dedup.py

# Move all duplicates to the Google Drive Trash (Recoverable)
uv run python gdrive_dedup.py --delete

# Permanently purge duplicates from your drive (Irreversible)
uv run python gdrive_dedup.py --purge
```

### 2. Selective Deleter Mode
Search for specific files by name or type and mass-delete them. If you use `--names` or `--types`, duplicate detection is bypassed.

```bash
# Preview all files containing 'temp' or 'backup' in their name
uv run python gdrive_dedup.py --names "temp,backup"

# Trash all images in your Drive
uv run python gdrive_dedup.py --types "Images" --delete

# Trash any videos or pdfs named 'draft'
uv run python gdrive_dedup.py --names "draft" --types "Videos,application/pdf" --delete
```

### Additional Flags
- `--export-csv`: Generates a detailed CSV log of what was kept/deleted, including exact folder paths. (CSV is automatically generated when using `--delete` or `--purge`).
- `--shared-drives`: Includes files inside Google Shared Drives during the scan.

## Features
- **Crash-Proof**: Uses exponential backoff. If you have 500,000 files, it won't crash when Google limits the API rate.
- **Path Resolution**: Caches folder structures so you see exactly where a file lives (e.g. `/Documents/Work/`).

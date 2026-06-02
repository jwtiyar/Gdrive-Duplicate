#!/usr/bin/env python3
"""
Google Drive Duplicate File Cleaner
====================================
Finds and deletes duplicate files in your Google Drive using the Google Drive API.

Strategy:
  1. List ALL files in Drive (excluding Google-native formats)
  2. Group by (size + md5Checksum) — to find duplicates even if renamed
  3. Keep the OLDEST copy per group, mark the rest for deletion
  4. Show full report + save CSV before touching anything
  5. Require explicit "YES" confirmation before any deletion

Setup (one-time):
  pip install --upgrade google-api-python-client google-auth-httplib2 google-auth-oauthlib

  Enable Drive API and download credentials.json:
  https://console.cloud.google.com/apis/library/drive.googleapis.com

Usage:
  python gdrive_dedup.py                        # Dry-run: report only, no deletions
  python gdrive_dedup.py --export-csv           # Dry-run + save CSV
  python gdrive_dedup.py --delete               # Move duplicates to Trash (recoverable)
  python gdrive_dedup.py --purge                # Permanently delete (IRREVERSIBLE)
  python gdrive_dedup.py --delete --shared-drives  # Include Shared Drives too

New in this version:
  - Full folder path shown in report and CSV (e.g. /Documents/2026/)
  - Exponential backoff on the scan phase (large drives won't crash on rate limits)
"""

import argparse
import os
import sys
import time
from collections import defaultdict
from datetime import datetime

# -- third-party --------------------------------------------------------------
try:
    from google.auth.transport.requests import Request
    from google.auth.exceptions import TransportError
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
except ImportError:
    print("Missing dependencies. Run:\n  pip install google-api-python-client google-auth-oauthlib google-auth-httplib2")
    sys.exit(1)

# -- constants ----------------------------------------------------------------
SCOPES     = ["https://www.googleapis.com/auth/drive"]
TOKEN_FILE = "token.json"
CREDS_FILE = "credentials.json"
PAGE_SIZE  = 1000  # maximum allowed by Drive API

GOOGLE_NATIVE_MIMES = {
    "application/vnd.google-apps.document",
    "application/vnd.google-apps.spreadsheet",
    "application/vnd.google-apps.presentation",
    "application/vnd.google-apps.form",
    "application/vnd.google-apps.drawing",
    "application/vnd.google-apps.map",
    "application/vnd.google-apps.site",
    "application/vnd.google-apps.script",
    "application/vnd.google-apps.shortcut",
    "application/vnd.google-apps.folder",
}

# Common MIME type categories for selective deletion
MIME_CATEGORIES = {
    "Images": ["image/png", "image/jpeg", "image/gif", "image/webp", "image/svg+xml", "image/bmp"],
    "Videos": ["video/mp4", "video/avi", "video/mkv", "video/mov", "video/wmv", "video/flv", "video/webm"],
    "Audio": ["audio/mpeg", "audio/wav", "audio/ogg", "audio/flac", "audio/aac", "audio/mp3"],
    "Documents": ["application/pdf", "application/msword", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"],
    "Archives": ["application/zip", "application/x-rar-compressed", "application/x-7z-compressed", "application/x-tar", "application/gzip"],
    "Code": ["text/x-python", "text/x-java", "text/javascript", "application/javascript", "text/html", "text/css"],
}


# -- auth ---------------------------------------------------------------------
def authenticate():
    """
    OAuth2 flow.
    - First run: opens browser, saves token.json
    - Later runs: reuses token.json, refreshes automatically
    - Handles expired/revoked tokens with a clean error message
    """
    creds = None

    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except TransportError as e:
                print(f"\n[ERROR] Could not refresh token: {e}")
                print(f"Delete '{TOKEN_FILE}' and run again to re-authenticate.")
                sys.exit(1)
        else:
            if not os.path.exists(CREDS_FILE):
                print(
                    f"[ERROR] '{CREDS_FILE}' not found.\n"
                    "Download it from: https://console.cloud.google.com/apis/credentials\n"
                    "Place it in the same folder as this script."
                )
                sys.exit(1)
            flow = InstalledAppFlow.from_client_secrets_file(CREDS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)

        with open(TOKEN_FILE, "w") as fh:
            fh.write(creds.to_json())
        print(f"[OK] Token saved to {TOKEN_FILE}")

    return build("drive", "v3", credentials=creds)


# -- file listing -------------------------------------------------------------
def list_all_files(service, include_shared=False, progress_callback=None, cancel_check=None):
    """
    Page through the entire Drive and return:
      - real_files : list of non-trashed, non-Google-native file dicts
      - folder_cache: dict mapping folder_id -> folder dict (id, name, parents)

    Folders are captured during the same pass at no extra cost.
    Backoff is applied per page so large drives don't crash on rate limits.
    """
    fields = (
        "nextPageToken, "
        "files(id, name, size, md5Checksum, mimeType, "
        "createdTime, modifiedTime, parents, webViewLink)"
    )

    all_items    = []
    folder_cache = {}   # id -> {id, name, parents}
    page_token   = None
    page_num     = 0

    print("Scanning Google Drive...", end="", flush=True)

    while True:
        # Check for cancellation before each page fetch
        if cancel_check and cancel_check():
            raise InterruptedError("Scan cancelled by user.")

        params = {
            "pageSize": PAGE_SIZE,
            "fields":   fields,
            "q":        "trashed = false",
            "spaces":   "drive",
        }
        if include_shared:
            params["includeItemsFromAllDrives"] = True
            params["supportsAllDrives"]         = True
        if page_token:
            params["pageToken"] = page_token

        # backoff on listing pages — large drives can trigger 429 here too
        result = None
        for attempt in range(5):
            try:
                result = service.files().list(**params).execute()
                break
            except HttpError as e:
                if e.resp.status in (429, 403) and attempt < 4:
                    wait = 2 ** attempt
                    print(f"\n  [!] Rate limited during scan. Retrying in {wait}s...", end="", flush=True)
                    time.sleep(wait)
                else:
                    print(f"\n[ERROR] Drive API error during listing: {e}")
                    sys.exit(1)

        batch = result.get("files", [])

        for item in batch:
            mime = item.get("mimeType", "")
            if mime == "application/vnd.google-apps.folder":
                # capture every folder for path resolution — even if we filter it later
                folder_cache[item["id"]] = {
                    "id":      item["id"],
                    "name":    item.get("name", "Unknown"),
                    "parents": item.get("parents", []),
                }
            all_items.append(item)

        page_num += 1
        print(f"\rScanning Google Drive... {len(all_items):,} items (page {page_num})", end="", flush=True)
        if progress_callback:
            progress_callback(len(all_items), page_num, len(folder_cache))

        page_token = result.get("nextPageToken")
        if not page_token:
            break

    print()

    # Keep only real files (non-native, non-folder)
    FOLDER_MIME = "application/vnd.google-apps.folder"
    real_files = [
        f for f in all_items
        if f.get("mimeType") not in GOOGLE_NATIVE_MIMES
        and f.get("mimeType") != FOLDER_MIME
    ]

    native_skipped = len(all_items) - len(real_files) - len(folder_cache)
    print(
        f"   -> {len(real_files):,} real files  |  "
        f"{len(folder_cache):,} folders cached  |  "
        f"{native_skipped:,} Google-native skipped\n"
    )

    return real_files, folder_cache


# -- duplicate detection ------------------------------------------------------
def find_duplicates(files, strict_name=False):
    """
    Group files by (size, md5Checksum) by default.
    If strict_name is True, group by (size, md5Checksum, name).
    Files missing an md5Checksum are skipped entirely to avoid false positives.
    Returns only groups with 2+ members.
    """
    groups = defaultdict(list)

    for f in files:
        md5 = f.get("md5Checksum")
        if not md5:                          # no checksum = can't safely deduplicate
            continue

        size_raw = f.get("size")
        size     = int(size_raw) if size_raw else 0

        if strict_name:
            name = f.get("name", "Unknown")
            groups[(size, md5, name)].append(f)
        else:
            groups[(size, md5)].append(f)

    return {k: v for k, v in groups.items() if len(v) > 1}


# -- helpers ------------------------------------------------------------------
def bytes_human(n):
    try:
        n = int(n)
    except (ValueError, TypeError):
        return "0 B"
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


# -- folder path resolution ---------------------------------------------------
def get_folder_path(folder_id, folder_cache, path_memo=None, _visited=None):
    """
    Recursively walk up the folder tree to build a full path string.

    Args:
        folder_id   : the folder ID to resolve
        folder_cache: dict of id -> {id, name, parents}
        path_memo   : dict used to cache already-resolved paths (pass {} once)
        _visited    : internal set used to detect circular parent references

    Returns a string like "/Documents/2026/" or "/" if root/unknown.
    """
    if path_memo is None:
        path_memo = {}
    if _visited is None:
        _visited = set()

    # already resolved
    if folder_id in path_memo:
        return path_memo[folder_id]

    # circular reference guard
    if folder_id in _visited:
        path_memo[folder_id] = "/"
        return "/"
    _visited.add(folder_id)

    folder = folder_cache.get(folder_id)
    if not folder:
        # unknown folder (shared drive root, "My Drive" root, or missing metadata)
        path_memo[folder_id] = "/"
        return "/"

    parents = folder.get("parents", [])
    name    = folder.get("name", "Unknown")

    if not parents:
        # this IS the root
        result = f"/{name}/"
    else:
        parent_path = get_folder_path(parents[0], folder_cache, path_memo, _visited)
        # avoid double-slash when parent_path is already "/"
        if parent_path == "/":
            result = f"/{name}/"
        else:
            result = f"{parent_path}{name}/"

    path_memo[folder_id] = result
    return result


def resolve_file_path(file_dict, folder_cache, path_memo):
    """
    Return the folder path of a file (not including the filename itself).
    Falls back to "/" if the file has no parents.
    """
    parents = file_dict.get("parents", [])
    if not parents:
        return "/"
    return get_folder_path(parents[0], folder_cache, path_memo)


def print_report(duplicate_groups, folder_cache):
    """
    Print a full duplicate report to stdout including resolved folder paths.
    Returns (files_to_delete, path_memo):
      - files_to_delete : list of (file_dict, size_int) tuples
      - path_memo       : already-resolved path cache (reused by CSV export)
    Within each group the OLDEST file (earliest createdTime) is kept.
    """
    files_to_delete = []
    estimated_bytes = 0
    group_count     = 0
    path_memo       = {}   # shared across all groups for maximum reuse

    print("=" * 70)
    print("  DUPLICATE FILE REPORT")
    print("=" * 70)

    for (size, md5), copies in sorted(
        duplicate_groups.items(), key=lambda x: x[1][0].get("name", "").lower()
    ):
        group_count += 1
        copies_sorted = sorted(copies, key=lambda f: f.get("createdTime", ""))
        keeper = copies_sorted[0]
        dupes  = copies_sorted[1:]
        group_name = keeper.get("name", "Unknown")

        print(f"\n[{group_count}] {group_name}")
        print(f"     Size : {bytes_human(size)}   MD5: {md5}")
        print(f"     Copies: {len(copies_sorted)}  ->  Keep 1, Delete {len(dupes)}")

        keeper_path = resolve_file_path(keeper, folder_cache, path_memo)
        print(f"     KEEP  : {keeper.get('createdTime', 'Unknown')[:19]}  "
              f"path={keeper_path}  id={keeper['id']}")

        for d in dupes:
            dupe_path = resolve_file_path(d, folder_cache, path_memo)
            print(f"     DELETE: {d.get('createdTime', 'Unknown')[:19]}  "
                  f"path={dupe_path}  id={d['id']}")
            files_to_delete.append((d, size))
            estimated_bytes += size

    print("\n" + "=" * 70)
    print("  SUMMARY (pre-deletion estimate)")
    print(f"  Duplicate groups : {group_count:,}")
    print(f"  Files to delete  : {len(files_to_delete):,}")
    print(f"  Space to reclaim : {bytes_human(estimated_bytes)}")
    print("=" * 70 + "\n")

    return files_to_delete, path_memo


# -- CSV export ---------------------------------------------------------------
def export_report_csv(duplicate_groups, files_to_delete_tuples, folder_cache, path_memo):
    """Write a full keep/delete log to a timestamped CSV file, including folder paths."""
    import csv

    delete_ids = {f["id"] for f, _ in files_to_delete_tuples}
    filename   = f"gdrive_duplicates_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

    with open(filename, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["group", "action", "name", "path", "size_bytes", "md5",
                         "created", "id", "webViewLink"])

        for group_num, ((size, md5), copies) in enumerate(
            sorted(duplicate_groups.items(), key=lambda x: x[1][0].get("name", "").lower()), 1
        ):
            for f in sorted(copies, key=lambda f: f.get("createdTime", "")):
                path = resolve_file_path(f, folder_cache, path_memo)
                writer.writerow([
                    group_num,
                    "DELETE" if f["id"] in delete_ids else "KEEP",
                    f.get("name", "Unknown"),
                    path,
                    size, md5,
                    f.get("createdTime", ""),
                    f["id"],
                    f.get("webViewLink", ""),
                ])

    print(f"[CSV] Report saved -> {filename}\n")


# -- API execution with exponential backoff -----------------------------------
def execute_with_backoff(build_request, file_name, max_retries=4):
    """
    Call build_request() to get a fresh HttpRequest, then .execute() it.
    build_request must be a zero-arg callable (lambda) so each retry
    creates a brand-new HttpRequest object — consumed objects cannot be retried.
    Retries on HTTP 429 (Too Many Requests) and 403 rate-limit errors.
    """
    for attempt in range(max_retries):
        try:
            build_request().execute()
            return True
        except HttpError as e:
            status = e.resp.status
            is_rate_limit = status in (429, 403)
            if is_rate_limit and attempt < max_retries - 1:
                wait = 2 ** attempt          # 1s, 2s, 4s, 8s
                print(f"  [!] Rate limited ({status}) on '{file_name}'. Retrying in {wait}s...")
                time.sleep(wait)
            else:
                print(f"  [X] FAILED ({status}): '{file_name}' -- {e}")
                return False
    return False


# -- selective filtering ------------------------------------------------------
def match_name(file_name, search_terms):
    if not search_terms:
        return True
    file_name_lower = file_name.lower()
    for term in search_terms:
        if term.lower() in file_name_lower:
            return True
    return False

def match_mime_types(file_mime, mime_types):
    if not mime_types:
        return True
    expanded_types = set()
    for mt in mime_types:
        mt = mt.strip()
        if mt in MIME_CATEGORIES:
            expanded_types.update(MIME_CATEGORIES[mt])
        else:
            expanded_types.add(mt)
    return file_mime in expanded_types

def filter_files(files, name_patterns, mime_types):
    filtered = []
    for f in files:
        if not match_name(f.get("name", ""), name_patterns):
            continue
        if not match_mime_types(f.get("mimeType", ""), mime_types):
            continue
        filtered.append(f)
    return filtered

def print_preview(files, name_patterns, mime_types, folder_cache, path_memo):
    print("\n" + "=" * 70)
    print("  PREVIEW: Files to be deleted")
    print("=" * 70)
    if name_patterns:
        print(f"  Search terms: {', '.join(name_patterns)}")
    if mime_types:
        print(f"  MIME types  : {', '.join(mime_types)}")
    print(f"  Files found : {len(files):,}")
    if files:
        print(f"  Total size  : {bytes_human(sum(int(f.get('size', 0)) for f in files))}")
    print()

    by_mime = defaultdict(list)
    for f in files:
        by_mime[f.get("mimeType", "unknown")].append(f)

    for mime, mime_files in sorted(by_mime.items()):
        print(f"\n  [{mime}] ({len(mime_files)} files)")
        for f in mime_files[:10]:
            size = bytes_human(int(f.get("size", 0)))
            path = resolve_file_path(f, folder_cache, path_memo)
            print(f"    - {f.get('name', 'Unknown')} ({size})  path={path}")
        if len(mime_files) > 10:
            print(f"    ... and {len(mime_files) - 10} more")
    print("\n" + "=" * 70)

def export_preview_csv(files, folder_cache, path_memo):
    import csv
    filename = f"gdrive_selective_preview_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    with open(filename, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["name", "path", "size_bytes", "mimeType", "created", "id"])
        for f in files:
            writer.writerow([
                f.get("name", ""),
                resolve_file_path(f, folder_cache, path_memo),
                f.get("size", 0),
                f.get("mimeType", ""),
                f.get("createdTime", ""),
                f["id"],
            ])
    print(f"[CSV] Preview saved -> {filename}\n")


# -- deletion loops -----------------------------------------------------------
def trash_files(service, files_to_delete, progress_callback=None, cancel_check=None):
    """Move files to Trash. Recoverable from Drive UI."""
    success = failed = actual_bytes = 0
    total = len(files_to_delete)

    for i, (f, size) in enumerate(files_to_delete, 1):
        if cancel_check and cancel_check():
            raise InterruptedError("Deletion cancelled by user.")
            
        fid   = f["id"]
        fname = f.get("name", "Unknown")
        if execute_with_backoff(
            lambda fid=fid: service.files().update(
                fileId=fid, body={"trashed": True}, supportsAllDrives=True
            ),
            fname,
        ):
            print(f"  [{i}/{total}] Trashed: {fname}")
            success      += 1
            actual_bytes += size
        else:
            failed += 1
        if progress_callback:
            progress_callback(i, total, success, failed, actual_bytes)

    return success, failed, actual_bytes


def purge_files(service, files_to_delete, progress_callback=None, cancel_check=None):
    """Permanently delete files. NOT recoverable."""
    success = failed = actual_bytes = 0
    total = len(files_to_delete)

    for i, (f, size) in enumerate(files_to_delete, 1):
        if cancel_check and cancel_check():
            raise InterruptedError("Deletion cancelled by user.")
            
        fid   = f["id"]
        fname = f.get("name", "Unknown")
        if execute_with_backoff(
            lambda fid=fid: service.files().delete(
                fileId=fid, supportsAllDrives=True
            ),
            fname,
        ):
            print(f"  [{i}/{total}] Purged : {fname}")
            success      += 1
            actual_bytes += size
        else:
            failed += 1
        if progress_callback:
            progress_callback(i, total, success, failed, actual_bytes)

    return success, failed, actual_bytes


# -- main ---------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Clean Google Drive by finding duplicates or deleting specific files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python gdrive_dedup.py                  # dry-run deduplication\n"
            "  python gdrive_dedup.py --delete         # trash duplicates\n"
            "  python gdrive_dedup.py --names \"temp\" --delete   # trash files with 'temp' in name\n"
            "  python gdrive_dedup.py --types \"Images\" --delete # trash all images\n"
        ),
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--delete", action="store_true", help="Move matched files to Trash (recoverable).")
    mode.add_argument("--purge",  action="store_true", help="Permanently delete files. CANNOT be undone.")
    
    parser.add_argument("--export-csv",     action="store_true", help="Save a CSV report even during a dry-run.")
    parser.add_argument("--shared-drives",  action="store_true", help="Include files in Shared Drives.")
    
    # Selective arguments
    parser.add_argument("--names", type=str, help="Comma-separated search terms for selective deletion.")
    parser.add_argument("--types", type=str, help="Comma-separated MIME types or categories (e.g. 'Images').")

    args = parser.parse_args()

    print("\nAuthenticating with Google Drive...")
    service = authenticate()
    print("Authenticated.\n")

    all_files, folder_cache = list_all_files(service, include_shared=args.shared_drives)
    if not all_files:
        print("No files found. Nothing to do.")
        return

    is_selective = bool(args.names or args.types)
    path_memo = {}

    if is_selective:
        name_patterns = [p.strip() for p in args.names.split(",")] if args.names else []
        mime_types    = [p.strip() for p in args.types.split(",")] if args.types else []
        
        filtered_files = filter_files(all_files, name_patterns, mime_types)
        if not filtered_files:
            print("No files matched your filters.")
            return

        print_preview(filtered_files, name_patterns, mime_types, folder_cache, path_memo)
        if args.export_csv or args.delete or args.purge:
            export_preview_csv(filtered_files, folder_cache, path_memo)
            
        files_to_delete_for_action = [(f, int(f.get("size", 0))) for f in filtered_files]
        
    else:
        duplicate_groups = find_duplicates(all_files)
        if not duplicate_groups:
            print("No duplicates found! Your Drive is clean.")
            return

        files_to_delete, path_memo = print_report(duplicate_groups, folder_cache)
        if args.delete or args.purge or args.export_csv:
            export_report_csv(duplicate_groups, files_to_delete, folder_cache, path_memo)
            
        files_to_delete_for_action = files_to_delete

    if not args.delete and not args.purge:
        print("DRY-RUN — no files were changed.")
        print("  --delete    move to Trash")
        print("  --purge     permanently delete\n")
        return

    action_label = "PERMANENTLY DELETE" if args.purge else "TRASH"
    print(f"WARNING: About to {action_label} {len(files_to_delete_for_action):,} files.")
    if args.purge:
        print("  This is IRREVERSIBLE. Files will NOT go to Trash.")
    if input("  Type YES to continue: ").strip() != "YES":
        print("Aborted. Nothing was deleted.")
        return

    print(f"\n{'Purging' if args.purge else 'Trashing'} {len(files_to_delete_for_action):,} files...\n")
    if args.purge:
        ok, fail, actual_bytes = purge_files(service, files_to_delete_for_action)
    else:
        ok, fail, actual_bytes = trash_files(service, files_to_delete_for_action)

    print()
    print("=" * 70)
    print(f"  Done.  {ok:,} deleted   {fail:,} failed")
    print(f"  Actual space reclaimed: {bytes_human(actual_bytes)}")
    print("=" * 70 + "\n")



if __name__ == "__main__":
    main()

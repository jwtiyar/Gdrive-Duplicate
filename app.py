#!/usr/bin/env python3
import os
import sys
import time
import threading
import webbrowser
import json
from typing import List, Optional
from fastapi import FastAPI, BackgroundTasks, HTTPException, status
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, FileResponse, HTMLResponse
from pydantic import BaseModel
from google_auth_oauthlib.flow import InstalledAppFlow

# Import functions from existing script
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import gdrive_dedup

app = FastAPI(title="Google Drive Cleaner GUI")

# -- Models -------------------------------------------------------------------
class LoginRequest(BaseModel):
    username: str
    password: str

class ScanRequest(BaseModel):
    names: Optional[str] = None
    types: Optional[str] = None
    include_shared: bool = False

class DeleteRequest(BaseModel):
    file_ids: List[str]
    purge: bool = False

# -- Bundled Credentials for Customers ----------------------------------------
from dotenv import load_dotenv
load_dotenv()

def ensure_credentials_file():
    """Ensure the credentials.json file exists with the bundled credentials."""
    client_id = os.environ.get("GOOGLE_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")
    
    if not client_id or not client_secret:
        print("Warning: GOOGLE_CLIENT_ID or GOOGLE_CLIENT_SECRET missing from environment/.env")
        return

    data = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            "redirect_uris": ["http://localhost"]
        }
    }
    try:
        with open(gdrive_dedup.CREDS_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"Warning: Failed to write bundled credentials: {e}")

# Ensure the credentials file is written immediately on module load
ensure_credentials_file()

# -- App State ----------------------------------------------------------------
scan_state = {
    "status": "idle",  # idle, scanning, completed, error
    "progress": {
        "scanned_count": 0,
        "page_num": 0,
        "folders_cached": 0
    },
    "results": None,        # Scan results
    "folder_cache": None,   # Folder cache for path resolving
    "error": None,
    "mode": "demo"          # demo or real
}

delete_state = {
    "status": "idle",  # idle, deleting, completed, error
    "progress": {
        "current": 0,
        "total": 0,
        "success": 0,
        "failed": 0,
        "actual_bytes": 0
    },
    "error": None
}

# In-memory storage for scanned files list (needed to process deletions later)
scanned_files_cache = []
folder_cache_global = {}

# Session state
logged_in_users = set()
active_oauth_flows = {}

# -- Authentication Checkers -------------------------------------------------
def is_credentials_present() -> bool:
    return True

def is_token_present() -> bool:
    return os.path.exists(gdrive_dedup.TOKEN_FILE)

# -- Background Scan Task (Real Mode) ----------------------------------------
def bg_scan_real(include_shared: bool):
    global scanned_files_cache, folder_cache_global
    scan_state["status"] = "scanning"
    scan_state["progress"] = {"scanned_count": 0, "page_num": 0, "folders_cached": 0}
    scan_state["error"] = None
    scan_state["results"] = None
    scan_state["mode"] = "real"

    def progress_callback(scanned, pages, folders):
        scan_state["progress"] = {
            "scanned_count": scanned,
            "page_num": pages,
            "folders_cached": folders
        }

    try:
        service = gdrive_dedup.authenticate()
        real_files, folders = gdrive_dedup.list_all_files(
            service, 
            include_shared=include_shared, 
            progress_callback=progress_callback
        )
        
        scanned_files_cache = real_files
        folder_cache_global = folders
        
        # Prepare duplicates report structure
        duplicate_groups = gdrive_dedup.find_duplicates(real_files)
        
        # Format the duplicates into a JSON-serializable list
        formatted_groups = []
        path_memo = {}
        
        for (name, size, md5), copies in sorted(duplicate_groups.items(), key=lambda x: x[0][0].lower()):
            copies_sorted = sorted(copies, key=lambda f: f.get("createdTime", ""))
            keeper = copies_sorted[0]
            dupes = copies_sorted[1:]
            
            group_copies = []
            for item in copies_sorted:
                path = gdrive_dedup.resolve_file_path(item, folders, path_memo)
                group_copies.append({
                    "id": item["id"],
                    "name": item.get("name", "Unknown"),
                    "path": path,
                    "size": int(item.get("size", 0)),
                    "md5": item.get("md5Checksum"),
                    "createdTime": item.get("createdTime", "Unknown"),
                    "webViewLink": item.get("webViewLink", ""),
                    "isKeeper": item["id"] == keeper["id"]
                })
            
            formatted_groups.append({
                "name": name,
                "size": size,
                "md5": md5,
                "copies": group_copies
            })
            
        scan_state["results"] = {
            "duplicates": formatted_groups,
            "total_files": len(real_files)
        }
        scan_state["status"] = "completed"
        
    except Exception as e:
        scan_state["status"] = "error"
        scan_state["error"] = str(e)

# -- Background Scan Task (Demo Mode) ----------------------------------------
def bg_scan_demo(names_filter: Optional[str] = None, types_filter: Optional[str] = None):
    global scanned_files_cache, folder_cache_global
    scan_state["status"] = "scanning"
    scan_state["error"] = None
    scan_state["results"] = None
    scan_state["mode"] = "demo"

    # Simulate network delays and paging
    steps = [
        (352, 1, 15),
        (721, 2, 38),
        (1094, 3, 54),
        (1245, 4, 62)
    ]
    
    for scanned, pages, folders in steps:
        time.sleep(0.5)
        scan_state["progress"] = {
            "scanned_count": scanned,
            "page_num": pages,
            "folders_cached": folders
        }

    # Generate Mock Folder Cache
    folder_cache_global = {
        "root": {"id": "root", "name": "My Drive", "parents": []},
        "f1": {"id": "f1", "name": "Photos", "parents": ["root"]},
        "f2": {"id": "f2", "name": "2025", "parents": ["f1"]},
        "f3": {"id": "f3", "name": "Work", "parents": ["root"]},
        "f4": {"id": "f4", "name": "Projects", "parents": ["f3"]},
        "f5": {"id": "f5", "name": "Backups", "parents": ["root"]},
        "f6": {"id": "f6", "name": "Videos", "parents": ["root"]},
        "f7": {"id": "f7", "name": "Temp", "parents": ["root"]}
    }

    # Define standard mock files
    mock_files = [
        # Photo duplicates
        {"id": "img1", "name": "DSC_0124.JPG", "size": 4404019, "md5Checksum": "ab81f729b71e1a8a25c192d192c719e0", "mimeType": "image/jpeg", "createdTime": "2025-06-15T12:00:00Z", "parents": ["f2"], "webViewLink": "#"},
        {"id": "img1_d1", "name": "DSC_0124.JPG", "size": 4404019, "md5Checksum": "ab81f729b71e1a8a25c192d192c719e0", "mimeType": "image/jpeg", "createdTime": "2025-06-16T14:30:00Z", "parents": ["f5"], "webViewLink": "#"},
        {"id": "img1_d2", "name": "DSC_0124.JPG", "size": 4404019, "md5Checksum": "ab81f729b71e1a8a25c192d192c719e0", "mimeType": "image/jpeg", "createdTime": "2026-01-10T09:15:00Z", "parents": ["root"], "webViewLink": "#"},
        
        # PPTX duplicates
        {"id": "ppt1", "name": "Project_Presentation_Final_v2.pptx", "size": 19398656, "md5Checksum": "c89bfa81f1b0a88ef11b10b001a1c9e8", "mimeType": "application/vnd.openxmlformats-officedocument.presentationml.presentation", "createdTime": "2026-03-01T10:00:00Z", "parents": ["f4"], "webViewLink": "#"},
        {"id": "ppt1_d1", "name": "Project_Presentation_Final_v2.pptx", "size": 19398656, "md5Checksum": "c89bfa81f1b0a88ef11b10b001a1c9e8", "mimeType": "application/vnd.openxmlformats-officedocument.presentationml.presentation", "createdTime": "2026-03-05T18:22:00Z", "parents": ["root"], "webViewLink": "#"},
        
        # Heavy Video duplicates
        {"id": "vid1", "name": "vacation_video_draft.mp4", "size": 257744896, "md5Checksum": "fb12c8b749a1bc9a25b1fcd34d28e7e1", "mimeType": "video/mp4", "createdTime": "2025-08-20T11:00:00Z", "parents": ["f6"], "webViewLink": "#"},
        {"id": "vid1_d1", "name": "vacation_video_draft.mp4", "size": 257744896, "md5Checksum": "fb12c8b749a1bc9a25b1fcd34d28e7e1", "mimeType": "video/mp4", "createdTime": "2025-08-22T08:00:00Z", "parents": ["f7"], "webViewLink": "#"},
        
        # Archive ZIP duplicates
        {"id": "zip1", "name": "archive_backup_2025.zip", "size": 1288490188, "md5Checksum": "7a8b9c10d11e12f13a14b15c16d17e18", "mimeType": "application/zip", "createdTime": "2025-12-31T23:59:59Z", "parents": ["f5"], "webViewLink": "#"},
        {"id": "zip1_d1", "name": "archive_backup_2025.zip", "size": 1288490188, "md5Checksum": "7a8b9c10d11e12f13a14b15c16d17e18", "mimeType": "application/zip", "createdTime": "2026-01-02T12:00:00Z", "parents": ["root"], "webViewLink": "#"},
        
        # Code file duplicates
        {"id": "code1", "name": "style.css", "size": 12288, "md5Checksum": "3c9d8e7a6b5c4d3e2f1a0b9c8d7e6f5a", "mimeType": "text/css", "createdTime": "2026-05-30T10:00:00Z", "parents": ["f4"], "webViewLink": "#"},
        {"id": "code1_d1", "name": "style.css", "size": 12288, "md5Checksum": "3c9d8e7a6b5c4d3e2f1a0b9c8d7e6f5a", "mimeType": "text/css", "createdTime": "2026-05-30T10:10:00Z", "parents": ["f5"], "webViewLink": "#"},
        
        # Extra non-duplicate files (for searching)
        {"id": "extra1", "name": "temp_config.json", "size": 1224, "mimeType": "application/json", "createdTime": "2026-05-29T15:00:00Z", "parents": ["f7"], "webViewLink": "#"},
        {"id": "extra2", "name": "test_script.py", "size": 4608, "mimeType": "text/x-python", "createdTime": "2026-05-28T09:30:00Z", "parents": ["f7"], "webViewLink": "#"},
        {"id": "extra3", "name": "contacts_backup.vcf", "size": 122880, "mimeType": "text/vcard", "createdTime": "2026-05-20T10:00:00Z", "parents": ["f5"], "webViewLink": "#"}
    ]
    
    scanned_files_cache = mock_files
    
    # Process scan depending on filters
    is_selective = bool(names_filter or types_filter)
    
    if is_selective:
        name_patterns = [p.strip() for p in names_filter.split(",")] if names_filter else []
        mime_types = [p.strip() for p in types_filter.split(",")] if types_filter else []
        
        filtered = gdrive_dedup.filter_files(mock_files, name_patterns, mime_types)
        formatted_files = []
        path_memo = {}
        for item in filtered:
            path = gdrive_dedup.resolve_file_path(item, folder_cache_global, path_memo)
            formatted_files.append({
                "id": item["id"],
                "name": item.get("name", "Unknown"),
                "path": path,
                "size": int(item.get("size", 0)),
                "mimeType": item.get("mimeType", "Unknown"),
                "createdTime": item.get("createdTime", "Unknown")
            })
        scan_state["results"] = {
            "files": formatted_files,
            "total_files": len(mock_files)
        }
    else:
        # Group duplicates
        duplicate_groups = gdrive_dedup.find_duplicates(mock_files)
        formatted_groups = []
        path_memo = {}
        
        for (name, size, md5), copies in sorted(duplicate_groups.items(), key=lambda x: x[0][0].lower()):
            copies_sorted = sorted(copies, key=lambda f: f.get("createdTime", ""))
            keeper = copies_sorted[0]
            
            group_copies = []
            for item in copies_sorted:
                path = gdrive_dedup.resolve_file_path(item, folder_cache_global, path_memo)
                group_copies.append({
                    "id": item["id"],
                    "name": item.get("name", "Unknown"),
                    "path": path,
                    "size": int(item.get("size", 0)),
                    "md5": item.get("md5Checksum"),
                    "createdTime": item.get("createdTime", "Unknown"),
                    "webViewLink": item.get("webViewLink", ""),
                    "isKeeper": item["id"] == keeper["id"]
                })
            
            formatted_groups.append({
                "name": name,
                "size": size,
                "md5": md5,
                "copies": group_copies
            })
            
        scan_state["results"] = {
            "duplicates": formatted_groups,
            "total_files": len(mock_files)
        }

    scan_state["status"] = "completed"

# -- Background Deletion Task (Real Mode) -------------------------------------
def bg_delete_real(file_ids: List[str], purge: bool):
    delete_state["status"] = "deleting"
    delete_state["error"] = None
    delete_state["progress"] = {"current": 0, "total": len(file_ids), "success": 0, "failed": 0, "actual_bytes": 0}

    # Find the files to delete in cache to get their sizes
    files_to_delete = []
    for fid in file_ids:
        found_file = next((f for f in scanned_files_cache if f["id"] == fid), None)
        size = int(found_file.get("size", 0)) if found_file else 0
        files_to_delete.append(({"id": fid, "name": found_file.get("name", "Unknown") if found_file else "Unknown"}, size))

    def progress_callback(curr, tot, succ, fail, act_bytes):
        delete_state["progress"] = {
            "current": curr,
            "total": tot,
            "success": succ,
            "failed": fail,
            "actual_bytes": act_bytes
        }

    try:
        service = gdrive_dedup.authenticate()
        if purge:
            gdrive_dedup.purge_files(service, files_to_delete, progress_callback=progress_callback)
        else:
            gdrive_dedup.trash_files(service, files_to_delete, progress_callback=progress_callback)
        
        delete_state["status"] = "completed"
    except Exception as e:
        delete_state["status"] = "error"
        delete_state["error"] = str(e)

# -- Background Deletion Task (Demo Mode) -------------------------------------
def bg_delete_demo(file_ids: List[str]):
    delete_state["status"] = "deleting"
    delete_state["error"] = None
    
    total = len(file_ids)
    success = 0
    failed = 0
    actual_bytes = 0

    delete_state["progress"] = {
        "current": 0,
        "total": total,
        "success": 0,
        "failed": 0,
        "actual_bytes": 0
    }

    for i, fid in enumerate(file_ids, 1):
        time.sleep(0.4) # Simulate network delete time
        
        found_file = next((f for f in scanned_files_cache if f["id"] == fid), None)
        size = int(found_file.get("size", 0)) if found_file else 0
        
        success += 1
        actual_bytes += size
        
        delete_state["progress"] = {
            "current": i,
            "total": total,
            "success": success,
            "failed": failed,
            "actual_bytes": actual_bytes
        }

    delete_state["status"] = "completed"

# -- OAuth Thread -------------------------------------------------------------
def trigger_google_auth():
    try:
        gdrive_dedup.authenticate()
    except Exception as e:
        print(f"Error authenticating: {e}")

# -- API Routes ---------------------------------------------------------------
@app.post("/api/login")
def api_login(req: LoginRequest):
    # Simple hardcoded user validation as requested
    if req.username == "admin" and req.password == "password":
        logged_in_users.add("admin-session")
        return {"token": "admin-session"}
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Incorrect username or password"
    )

@app.get("/api/auth/status")
def api_auth_status():
    creds_exist = is_credentials_present()
    token_active = False
    
    if creds_exist:
        try:
            # Try to build service silently. If it works, token is active.
            if is_token_present():
                gdrive_dedup.authenticate()
                token_active = True
        except Exception:
            token_active = False

    mode = "real" if creds_exist else "demo"
    return {
        "credentials_exist": creds_exist,
        "token_active": token_active,
        "mode": mode
    }

@app.post("/api/auth/google-login")
def api_google_login():
    if not is_credentials_present():
        raise HTTPException(
            status_code=400,
            detail="credentials.json not found in server root directory."
        )
    try:
        flow = InstalledAppFlow.from_client_secrets_file(
            gdrive_dedup.CREDS_FILE,
            scopes=gdrive_dedup.SCOPES,
            redirect_uri="http://localhost:8000/callback"
        )
        auth_url, state = flow.authorization_url(prompt='consent', access_type='offline')
        active_oauth_flows[state] = flow
        return {"auth_url": auth_url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate authorization URL: {e}")

@app.get("/callback", response_class=HTMLResponse)
def oauth_callback(code: str, state: str):
    flow = active_oauth_flows.pop(state, None)
    if not flow:
        return """
        <html>
            <body style="font-family: sans-serif; background-color: #0b0d18; color: #ef4444; text-align: center; padding-top: 80px;">
                <h2>Authentication Session Expired</h2>
                <p>Please return to the dashboard and try connecting again.</p>
            </body>
        </html>
        """
    try:
        flow.fetch_token(code=code)
        credentials = flow.credentials
        
        # Save token.json
        with open(gdrive_dedup.TOKEN_FILE, "w") as fh:
            fh.write(credentials.to_json())
            
        return """
        <html>
            <body style="font-family: sans-serif; background-color: #0b0d18; color: #14b8a6; text-align: center; padding-top: 80px;">
                <h2 style="color: #14b8a6;">Authentication Successful!</h2>
                <p style="color: #9ca3af;">You have successfully linked your Google account. You can close this tab and return to the dashboard.</p>
            </body>
        </html>
        """
    except Exception as e:
        return f"""
        <html>
            <body style="font-family: sans-serif; background-color: #0b0d18; color: #ef4444; text-align: center; padding-top: 80px;">
                <h2>Authentication Failed</h2>
                <p>{str(e)}</p>
            </body>
        </html>
        """

@app.post("/api/auth/logout")
def api_logout():
    if is_token_present():
        try:
            os.remove(gdrive_dedup.TOKEN_FILE)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to logout: {e}")
    return {"status": "logged_out"}



@app.post("/api/scan")
def api_start_scan(req: ScanRequest, background_tasks: BackgroundTasks):
    creds_exist = is_credentials_present()
    
    if creds_exist:
        # Check if token is ready before scanning in Real Mode
        if not is_token_present():
            raise HTTPException(status_code=400, detail="Google authentication required.")
        background_tasks.add_task(bg_scan_real, req.include_shared)
    else:
        # Fallback to Demo Mode
        background_tasks.add_task(bg_scan_demo, req.names, req.types)
        
    return {"status": "started"}

@app.get("/api/scan/status")
def api_scan_status():
    return scan_state

@app.post("/api/delete")
def api_start_delete(req: DeleteRequest, background_tasks: BackgroundTasks):
    if not req.file_ids:
        raise HTTPException(status_code=400, detail="No file IDs specified for deletion.")
        
    creds_exist = is_credentials_present()
    
    if creds_exist:
        if not is_token_present():
            raise HTTPException(status_code=400, detail="Google authentication required.")
        background_tasks.add_task(bg_delete_real, req.file_ids, req.purge)
    else:
        # Demo Mode simulation
        background_tasks.add_task(bg_delete_demo, req.file_ids)
        
    return {"status": "started"}

@app.get("/api/delete/status")
def api_delete_status():
    return delete_state

# -- Serve Static Assets -----------------------------------------------------
# Serve HTML dashboard
@app.get("/")
def read_root():
    static_index = os.path.join(os.path.dirname(__file__), "static", "index.html")
    if os.path.exists(static_index):
        return FileResponse(static_index)
    return JSONResponse(
        content={"error": "Frontend code not found. Create 'static/index.html' first."},
        status_code=404
    )

# Try mounting the static directory. We'll build the files next.
static_dir = os.path.join(os.path.dirname(__file__), "static")
if not os.path.exists(static_dir):
    os.makedirs(static_dir)

app.mount("/static", StaticFiles(directory=static_dir), name="static")

# -- Startup Browser Automation ----------------------------------------------
def open_browser():
    # Wait for the server to spin up
    time.sleep(1.5)
    webbrowser.open("http://127.0.0.1:8000")

if __name__ == "__main__":
    import uvicorn
    
    # Run browser opener in daemon thread
    browser_thread = threading.Thread(target=open_browser)
    browser_thread.daemon = True
    browser_thread.start()
    
    print("\n" + "=" * 70)
    print("  Google Drive Cleaner GUI server is starting...")
    print("  Open your browser and navigate to: http://127.0.0.1:8000")
    print("=" * 70 + "\n")
    
    uvicorn.run("app:app", host="127.0.0.1", port=8000, log_level="info")

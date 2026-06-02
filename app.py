#!/usr/bin/env python3
import os
import sys

# Wrap sys.stdout and sys.stderr to catch and ignore Errno 5 I/O errors when running in background/no TTY
class SafeStdout:
    def __init__(self, original):
        self.original = original
    def write(self, data):
        if self.original:
            try:
                self.original.write(data)
            except Exception:
                pass
    def flush(self):
        if self.original:
            try:
                self.original.flush()
            except Exception:
                pass
    def __getattr__(self, name):
        return getattr(self.original, name)

sys.stdout = SafeStdout(sys.stdout)
sys.stderr = SafeStdout(sys.stderr)

import time
import threading
import webbrowser
import json
from typing import List, Optional
from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, FileResponse, HTMLResponse
from pydantic import BaseModel
from google_auth_oauthlib.flow import InstalledAppFlow

# Import functions from existing script
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import gdrive_dedup

app = FastAPI(title="Google Drive Cleaner GUI")

class ScanRequest(BaseModel):
    names: Optional[str] = None
    types: Optional[str] = None
    min_size_mb: Optional[float] = None
    max_size_mb: Optional[float] = None
    include_shared: bool = False
    strict_name: bool = False

class DeleteRequest(BaseModel):
    file_ids: List[str]
    purge: bool = False

# In PyInstaller, bundled files are extracted to sys._MEIPASS
from dotenv import load_dotenv
if getattr(sys, 'frozen', False):
    env_path = os.path.join(sys._MEIPASS, '.env')
else:
    env_path = os.path.join(os.path.dirname(__file__), '.env')

load_dotenv(env_path)

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
active_oauth_flows = {}
scan_cancelled = False
delete_cancelled = False

# -- Authentication Checkers -------------------------------------------------
def is_credentials_present() -> bool:
    return os.path.exists(gdrive_dedup.CREDS_FILE)

def is_token_present() -> bool:
    return os.path.exists(gdrive_dedup.TOKEN_FILE)

# -- Background Scan Task (Real Mode) ----------------------------------------
def bg_scan_real(include_shared: bool, names_filter: Optional[str] = None, types_filter: Optional[str] = None, strict_name: bool = False, min_size_mb: Optional[float] = None, max_size_mb: Optional[float] = None):
    global scanned_files_cache, folder_cache_global, scan_cancelled
    scan_cancelled = False
    scan_state["status"] = "scanning"
    scan_state["progress"] = {"scanned_count": 0, "page_num": 0, "folders_cached": 0}
    scan_state["error"] = None
    scan_state["results"] = None

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
            progress_callback=progress_callback,
            cancel_check=lambda: scan_cancelled
        )
        
        scanned_files_cache = real_files
        folder_cache_global = folders
        
        is_selective = bool(names_filter or types_filter or min_size_mb is not None or max_size_mb is not None)
        
        if is_selective:
            name_patterns = [p.strip() for p in names_filter.split(",")] if names_filter else []
            mime_types    = [p.strip() for p in types_filter.split(",")] if types_filter else []
            filtered = gdrive_dedup.filter_files(
                real_files, 
                name_patterns, 
                mime_types, 
                min_size_mb=min_size_mb, 
                max_size_mb=max_size_mb
            )
            formatted_files = []
            path_memo = {}
            for item in filtered:
                path = gdrive_dedup.resolve_file_path(item, folders, path_memo)
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
                "total_files": len(real_files)
            }
        else:
            # Prepare duplicates report structure
            duplicate_groups = gdrive_dedup.find_duplicates(real_files, strict_name=strict_name)
            
            # Format the duplicates into a JSON-serializable list
            formatted_groups = []
            path_memo = {}
            
            for group_key, copies in sorted(duplicate_groups.items(), key=lambda x: x[1][0].get("name", "").lower()):
                size = group_key[0]
                md5 = group_key[1]
                copies_sorted = sorted(copies, key=lambda f: f.get("createdTime", ""))
                keeper = copies_sorted[0]
                group_name = keeper.get("name", "Unknown")
                
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
                    "name": group_name,
                    "size": size,
                    "md5": md5,
                    "copies": group_copies
                })
                
            scan_state["results"] = {
                "duplicates": formatted_groups,
                "total_files": len(real_files)
            }
            
        scan_state["status"] = "completed"
        
    except InterruptedError:
        scan_state["status"] = "cancelled"
        scan_state["error"] = "Scan was cancelled by user."
    except Exception as e:
        scan_state["status"] = "error"
        scan_state["error"] = str(e)



# -- Background Deletion Task (Real Mode) -------------------------------------
def bg_delete_real(file_ids: List[str], purge: bool):
    global delete_cancelled
    delete_cancelled = False
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
        import datetime
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        log_filename = f"deletion_history_{timestamp}.txt"
        log_path = os.path.abspath(log_filename)
        delete_state["log_path"] = log_path
        
        if purge:
            gdrive_dedup.purge_files(service, files_to_delete, progress_callback=progress_callback, cancel_check=lambda: delete_cancelled, log_path=log_path)
        else:
            gdrive_dedup.trash_files(service, files_to_delete, progress_callback=progress_callback, cancel_check=lambda: delete_cancelled, log_path=log_path)
        
        delete_state["status"] = "completed"
    except InterruptedError:
        delete_state["status"] = "cancelled"
        delete_state["error"] = "Deletion was cancelled by user."
    except Exception as e:
        delete_state["status"] = "error"
        delete_state["error"] = str(e)


# -- API Routes ---------------------------------------------------------------
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
        background_tasks.add_task(
            bg_scan_real, 
            req.include_shared, 
            req.names, 
            req.types, 
            req.strict_name,
            req.min_size_mb,
            req.max_size_mb
        )
    else:
        raise HTTPException(status_code=400, detail="Credentials not found.")
        
    return {"status": "started"}

@app.get("/api/scan/status")
def api_scan_status():
    return scan_state

@app.post("/api/scan/cancel")
def api_cancel_scan():
    global scan_cancelled
    if scan_state["status"] != "scanning":
        return {"status": "not_scanning"}
    scan_cancelled = True
    return {"status": "cancelling"}

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
        raise HTTPException(status_code=400, detail="Credentials not found.")
        
    return {"status": "started"}

@app.get("/api/delete/status")
def api_delete_status():
    return delete_state

@app.post("/api/delete/cancel")
def api_cancel_delete():
    global delete_cancelled
    if delete_state["status"] != "deleting":
        return {"status": "not_deleting"}
    delete_cancelled = True
    return {"status": "cancelling"}

# -- Serve Static Assets -----------------------------------------------------
def get_base_dir():
    return getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))

# Serve HTML dashboard
@app.get("/")
def read_root():
    static_index = os.path.join(get_base_dir(), "static", "index.html")
    if os.path.exists(static_index):
        return FileResponse(static_index)
    return JSONResponse(
        content={"error": f"Frontend code not found at {static_index}."},
        status_code=404
    )

# Try mounting the static directory. We'll build the files next.
static_dir = os.path.join(get_base_dir(), "static")
if not os.path.exists(static_dir):
    os.makedirs(static_dir, exist_ok=True)

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

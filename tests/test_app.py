import os
import sys
# Prevent module-level side effects in app.py (credentials.json write, etc.)
os.environ["GDRIVE_DUP_SKIP_INIT"] = "1"

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from fastapi.testclient import TestClient
from app import app
from unittest.mock import patch

client = TestClient(app)

@patch('app.is_credentials_present', return_value=False)
def test_auth_status_no_creds(_mock_creds):
    # If credentials.json is not found (which it shouldn't be in a clean test env)
    # The app should correctly report missing credentials
    response = client.get("/api/auth/status")
    assert response.status_code == 200
    data = response.json()
    assert data["credentials_exist"] is False

@patch('app.is_token_present', return_value=False)
def test_scan_unauthorized(_mock_token_present):
    # Hitting scan without a valid Google token should return 400 Bad Request
    response = client.post("/api/scan", json={"include_shared": False}, headers={"Origin": "http://127.0.0.1:8000"})
    assert response.status_code == 400
    assert response.json()["detail"] == "Google authentication required."


def test_scan_cancel_endpoint():
    # First, make sure scan_state is not "scanning"
    from app import scan_state
    scan_state["status"] = "idle"
    
    # Try cancelling when not scanning
    response = client.post("/api/scan/cancel", headers={"Origin": "http://127.0.0.1:8000"})
    assert response.status_code == 200
    assert response.json()["status"] == "not_scanning"
    
    # Try cancelling when scanning
    scan_state["status"] = "scanning"
    response = client.post("/api/scan/cancel", headers={"Origin": "http://127.0.0.1:8000"})
    assert response.status_code == 200
    assert response.json()["status"] == "cancelling"
    
    # Restore status to idle
    scan_state["status"] = "idle"

def test_delete_cancel_endpoint():
    # First, make sure delete_state is not "deleting"
    from app import delete_state
    delete_state["status"] = "idle"
    
    # Try cancelling when not deleting
    response = client.post("/api/delete/cancel", headers={"Origin": "http://127.0.0.1:8000"})
    assert response.status_code == 200
    assert response.json()["status"] == "not_deleting"
    
    # Try cancelling when deleting
    delete_state["status"] = "deleting"
    response = client.post("/api/delete/cancel", headers={"Origin": "http://127.0.0.1:8000"})
    assert response.status_code == 200
    assert response.json()["status"] == "cancelling"
    
    # Restore status to idle
    delete_state["status"] = "idle"

import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import pytest
from fastapi.testclient import TestClient
from app import app
from unittest.mock import patch

client = TestClient(app)

@patch('app.is_credentials_present', return_value=False)
def test_auth_status_no_creds(mock_creds):
    # If credentials.json is not found (which it shouldn't be in a clean test env)
    # The app should correctly report missing credentials
    response = client.get("/api/auth/status")
    assert response.status_code == 200
    data = response.json()
    assert data["credentials_exist"] is False

@patch('app.is_token_present', return_value=False)
def test_scan_unauthorized(mock_token_present):
    # Hitting scan without a valid Google token should return 400 Bad Request
    response = client.post("/api/scan", json={"include_shared": False})
    assert response.status_code == 400
    assert "Google authentication required" in response.json()["detail"] or "Credentials not found" in response.json()["detail"]


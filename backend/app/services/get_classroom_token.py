#!/usr/bin/env python3
"""
One-shot OAuth2 token generator for Google Classroom.
Run this LOCALLY (not in Docker) — it will open a browser for consent.

Usage:
    pip install google-auth-oauthlib
    python backend/app/services/get_classroom_token.py

Output:
    Saves token.json to backend/app/services/google_auth/token.json
    That file is volume-mounted into the backend container.
"""

import os
import sys
from pathlib import Path

SCOPES = [
    "https://www.googleapis.com/auth/classroom.courses.readonly",
    "https://www.googleapis.com/auth/classroom.coursework.students",
    "https://www.googleapis.com/auth/classroom.rosters.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]

HERE = Path(__file__).parent
CREDENTIALS_FILE = HERE / "google_auth" / "credentials.json"
TOKEN_FILE       = HERE / "google_auth" / "token.json"

def main():
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
        from google.auth.transport.requests import Request
        import google.oauth2.credentials
    except ImportError:
        print("ERROR: Install dependencies first:")
        print("   pip install google-auth-oauthlib google-auth-httplib2 google-api-python-client")
        sys.exit(1)

    if not CREDENTIALS_FILE.exists():
        print(f"ERROR: credentials.json not found at {CREDENTIALS_FILE}")
        sys.exit(1)

    creds = None
    if TOKEN_FILE.exists():
        import json
        try:
            data = json.loads(TOKEN_FILE.read_text())
            creds = google.oauth2.credentials.Credentials(
                token=data.get("token"),
                refresh_token=data.get("refresh_token"),
                token_uri=data.get("token_uri"),
                client_id=data.get("client_id"),
                client_secret=data.get("client_secret"),
                scopes=data.get("scopes"),
            )
        except Exception as e:
            print(f"Warning: could not load existing token ({e}), will re-auth.")
            creds = None

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            print("Refreshing expired token...")
            creds.refresh(Request())
        else:
            print("Opening browser for Google OAuth consent...")
            flow = InstalledAppFlow.from_client_secrets_file(
                str(CREDENTIALS_FILE),
                scopes=SCOPES,
            )
            creds = flow.run_local_server(port=0, open_browser=True)

        TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        TOKEN_FILE.write_text(creds.to_json())
        print(f"\n✅ Token saved to: {TOKEN_FILE}")

    print(f"\nAuthorized account: {getattr(creds, 'id_token', {})}")
    print("\nNow restart the backend:")
    print("   docker restart amgs-backend")
    print("\nThen hit:")
    print("   curl http://localhost:8080/api/v1/classroom/auth-status")
    print("   → should return: {\"authenticated\": true, \"valid\": true}")

    # Quick sanity: list courses
    try:
        from googleapiclient.discovery import build
        service = build("classroom", "v1", credentials=creds)
        results = service.courses().list(pageSize=10).execute()
        courses = results.get("courses", [])
        if courses:
            print("\n📚 Your Classroom courses:")
            for c in courses:
                print(f"   [{c['id']}] {c['name']}  state={c.get('courseState')}")
        else:
            print("\n⚠️  No courses found — you may need to create one in classroom.google.com first.")
    except Exception as e:
        print(f"\nWarning: could not list courses: {e}")


if __name__ == "__main__":
    main()

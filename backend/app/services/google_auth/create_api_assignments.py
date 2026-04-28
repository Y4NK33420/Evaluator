"""
Create a Classroom assignment via API so associatedWithDeveloper=True,
allowing AMGS to push draftGrade/assignedGrade back.

Run this once per test assignment you want to create.
Output: prints the courseWork ID to use in E2E tests.
"""

import json
import os
from pathlib import Path
from datetime import datetime, timezone, timedelta
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

ROOT_ENV_FILE = Path(__file__).resolve().parents[4] / ".env"


def load_root_env() -> None:
    if not ROOT_ENV_FILE.exists():
        return
    for raw_line in ROOT_ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_root_env()

CREDENTIALS_FILE = Path(os.getenv("GOOGLE_CREDENTIALS_FILE", "backend/app/services/google_auth/credentials.json"))
TOKEN_FILE = Path(os.getenv("GOOGLE_TOKEN_FILE", "backend/app/services/google_auth/token.json"))

SCOPES = [
    "https://www.googleapis.com/auth/classroom.courses.readonly",
    "https://www.googleapis.com/auth/classroom.coursework.students",
    "https://www.googleapis.com/auth/classroom.rosters.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]

COURSE_ID = os.getenv("CLASSROOM_COURSE_ID") or os.getenv("GOOGLE_CLASSROOM_DEFAULT_COURSE_ID")
if not COURSE_ID:
    raise RuntimeError("Set CLASSROOM_COURSE_ID or GOOGLE_CLASSROOM_DEFAULT_COURSE_ID in the root .env file")

def get_creds():
    d = json.loads(TOKEN_FILE.read_text())
    creds = Credentials(token=d['token'], refresh_token=d['refresh_token'],
        token_uri=d['token_uri'], client_id=d['client_id'],
        client_secret=d['client_secret'], scopes=d['scopes'])
    if creds.expired:
        creds.refresh(Request())
        TOKEN_FILE.write_text(creds.to_json())
    return creds


def create_coursework(svc, title: str, description: str, max_points: int = 100) -> dict:
    due = datetime.now(timezone.utc) + timedelta(days=7)
    body = {
        "title": title,
        "description": description,
        "workType": "ASSIGNMENT",
        "state": "PUBLISHED",
        "maxPoints": max_points,
        "dueDate": {"year": due.year, "month": due.month, "day": due.day},
        "dueTime": {"hours": 23, "minutes": 59},
    }
    return svc.courses().courseWork().create(courseId=COURSE_ID, body=body).execute()


if __name__ == "__main__":
    creds = get_creds()
    svc = build("classroom", "v1", credentials=creds)

    print("Creating API-owned assignments in DEPTest...")

    cw1 = create_coursework(svc,
        title="[AMGS] Subjective Test",
        description="Upload your handwritten answer sheet. Graded by AMGS OCR pipeline.",
        max_points=100,
    )
    print(f"\n[SUBJECTIVE] Created: {cw1['id']}")
    print(f"  title: {cw1['title']}")
    print(f"  associatedWithDeveloper: {cw1.get('associatedWithDeveloper')}")
    print(f"  state: {cw1['state']}")

    cw2 = create_coursework(svc,
        title="[AMGS] Code Test",
        description="Submit your Python/C/C++/Java solution file. Graded by AMGS code evaluator.",
        max_points=100,
    )
    print(f"\n[CODE] Created: {cw2['id']}")
    print(f"  title: {cw2['title']}")
    print(f"  associatedWithDeveloper: {cw2.get('associatedWithDeveloper')}")
    print(f"  state: {cw2['state']}")

    print(f"""
═══════════════════════════════════════════
Use these IDs to run the full E2E grade sync test:

  CLASSROOM_COURSE_ID     = {COURSE_ID}
  CLASSROOM_SUBJECTIVE_CW = {cw1['id']}
  CLASSROOM_CODE_CW       = {cw2['id']}

Have your student account submit work to both assignments,
then run test_classroom_e2e.py with these IDs.
═══════════════════════════════════════════
""")

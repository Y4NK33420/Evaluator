"""
Verify the `associatedWithDeveloper` flag on coursework and submissions.
If False → grading/returning via API is not permitted (403 ProjectPermissionDenied).
This is a hard Google Classroom restriction for manually-created assignments.
"""

import json
import os
from pathlib import Path
from google.oauth2.credentials import Credentials
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

token_file = Path(os.getenv("GOOGLE_TOKEN_FILE", "backend/app/services/google_auth/token.json"))
d = json.loads(token_file.read_text())
creds = Credentials(token=d['token'], refresh_token=d['refresh_token'],
    token_uri=d['token_uri'], client_id=d['client_id'],
    client_secret=d['client_secret'], scopes=d['scopes'])

svc = build('classroom', 'v1', credentials=creds)
COURSE = os.getenv("CLASSROOM_COURSE_ID") or os.getenv("GOOGLE_CLASSROOM_DEFAULT_COURSE_ID")
if not COURSE:
    raise RuntimeError("Set CLASSROOM_COURSE_ID or GOOGLE_CLASSROOM_DEFAULT_COURSE_ID in the root .env file")

coursework_to_check = []
code_cw = os.getenv("CLASSROOM_COURSEWORK_CODE_ID")
subjective_cw = os.getenv("CLASSROOM_COURSEWORK_SUBJECTIVE_ID")
if code_cw:
    coursework_to_check.append((code_cw, "Code"))
if subjective_cw:
    coursework_to_check.append((subjective_cw, "Subjective"))
if not coursework_to_check:
    raise RuntimeError(
        "Set CLASSROOM_COURSEWORK_CODE_ID and/or CLASSROOM_COURSEWORK_SUBJECTIVE_ID in the root .env file"
    )

for cw_id, title in coursework_to_check:
    cw = svc.courses().courseWork().get(courseId=COURSE, id=cw_id).execute()
    print(f"\n[{cw_id}] {title}")
    print(f"  associatedWithDeveloper: {cw.get('associatedWithDeveloper')}")
    print(f"  creationTime: {cw.get('creationTime')}")
    print(f"  creatorUserId: {cw.get('creatorUserId')}")

    subs = svc.courses().courseWork().studentSubmissions().list(
        courseId=COURSE, courseWorkId=cw_id).execute().get('studentSubmissions', [])
    for s in subs:
        print(f"  sub[{s['id']}]: associatedWithDeveloper={s.get('associatedWithDeveloper')} state={s['state']}")

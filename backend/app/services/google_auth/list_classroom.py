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
creds = Credentials(
    token=d['token'], refresh_token=d['refresh_token'],
    token_uri=d['token_uri'], client_id=d['client_id'],
    client_secret=d['client_secret'], scopes=d['scopes'],
)

svc = build('classroom', 'v1', credentials=creds)
COURSE = os.getenv("CLASSROOM_COURSE_ID") or os.getenv("GOOGLE_CLASSROOM_DEFAULT_COURSE_ID")
if not COURSE:
    raise RuntimeError("Set CLASSROOM_COURSE_ID or GOOGLE_CLASSROOM_DEFAULT_COURSE_ID in the root .env file")

cw_list = svc.courses().courseWork().list(courseId=COURSE).execute().get('courseWork', [])
print(f"COURSEWORK ({len(cw_list)} assignments):")
for w in cw_list:
    print(f"  [{w['id']}]  title={w['title']}  type={w.get('workType')}  maxPoints={w.get('maxPoints')}")

print()
for w in cw_list:
    subs = svc.courses().courseWork().studentSubmissions().list(
        courseId=COURSE, courseWorkId=w['id'],
    ).execute().get('studentSubmissions', [])
    print(f"SUBMISSIONS for [{w['id']}] {w['title']}:")
    for s in subs:
        print(f"  sub_id={s['id']}  userId={s['userId']}  state={s['state']}")
        atts = s.get('assignmentSubmission', {}).get('attachments', [])
        for a in atts:
            df = a.get('driveFile', {})
            lm = a.get('link', {})
            print(f"    driveFile: id={df.get('id')} title={df.get('title')} mimeType={df.get('mimeType')}" if df else f"    link: {lm}")
    if not subs:
        print("  (no submissions)")
    print()

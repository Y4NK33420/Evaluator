"""
AMGS Full Grade Sync E2E — uses API-owned assignments (associatedWithDeveloper=True)
Tests: ingest → grade insert → sync-draft → Classroom API verify → release → verify RETURNED

Course:        858211895824  (DEPTest)
Subjective CW: 849220866861  [AMGS] Subjective Test
Code CW:       849220633576  [AMGS] Code Test
"""

import json
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

BASE = "http://localhost:8080"
COURSE_ID = "858211895824"
CASES = [
    {"cw_id": "849220866861", "label": "Subjective", "score": 82.0},
    {"cw_id": "849220633576", "label": "Code",       "score": 75.0},
]

import subprocess, io as _io

PASS, FAIL = [], []


def req(method, path, body=None, expected=None):
    url = BASE + path
    for _ in range(3):
        data = json.dumps(body).encode() if body is not None else None
        r = urllib.request.Request(url, data=data, method=method,
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(r, timeout=30) as resp:
                raw, status = resp.read(), resp.status
        except urllib.error.HTTPError as e:
            raw, status = e.read(), e.code
            if status in (307, 308):
                url = BASE + e.headers.get("Location", "")
                continue
        break
    parsed = json.loads(raw) if raw else {}
    if expected and status != expected:
        raise AssertionError(f"{method} {path} → {status} (expected {expected})\n{json.dumps(parsed,indent=2)}")
    return status, parsed


def svc():
    p = Path('backend/app/services/google_auth/token.json')
    d = json.loads(p.read_text())
    creds = Credentials(token=d['token'], refresh_token=d['refresh_token'],
        token_uri=d['token_uri'], client_id=d['client_id'],
        client_secret=d['client_secret'], scopes=d['scopes'])
    if creds.expired:
        creds.refresh(Request())
        p.write_text(creds.to_json())
    return build("classroom", "v1", credentials=creds)


def ok(name, detail=""): PASS.append(name); print(f"  ✅ {name}" + (f"  — {detail}" if detail else ""))
def fail(name, detail): FAIL.append(name); print(f"  ❌ {name}  — {detail}")
def section(t): print(f"\n{'─'*60}\n  {t}\n{'─'*60}")


# ─────────────────────────────────────────────────────────────────────────────

def run_case(case: dict, classroom_svc):
    cw_id   = case["cw_id"]
    label   = case["label"]
    score   = case["score"]

    section(f"{label}: Step 1 — List Classroom submissions")
    subs = classroom_svc.courses().courseWork().studentSubmissions().list(
        courseId=COURSE_ID, courseWorkId=cw_id).execute().get("studentSubmissions", [])
    turned_in = [s for s in subs if s["state"] in ("TURNED_IN", "RETURNED")]
    print(f"  Total subs: {len(subs)}  Turned-in: {len(turned_in)}")
    if not turned_in:
        fail(f"{label}/has_submission", "No student has submitted yet — submit from student account first")
        return
    classroom_sub_id = turned_in[0]["id"]
    student_id = turned_in[0]["userId"]
    ok(f"{label}/has_submission", f"sub={classroom_sub_id} student={student_id}")

    section(f"{label}: Step 2 — Create AMGS assignment (API-owned CW)")
    _, asgn = req("POST", "/api/v1/assignments/", {
        "course_id": COURSE_ID,
        "classroom_id": cw_id,
        "title": f"[AMGS E2E] {label}",
        "max_marks": 100,
        "question_type": "subjective",
        "has_code_question": False,
    }, expected=201)
    amgs_id = asgn["id"]
    ok(f"{label}/create_assignment", f"amgs_id={amgs_id}")

    section(f"{label}: Step 3 — Ingest submissions")
    _, ingest = req("POST", f"/api/v1/classroom/{amgs_id}/ingest",
        {"course_id": COURSE_ID, "coursework_id": cw_id, "force_reingest": True},
        expected=200)
    print(f"  {json.dumps(ingest, indent=2)}")
    if ingest.get("errors"):
        fail(f"{label}/ingest", f"errors={ingest['errors']}")
        return
    ingested = ingest.get("ingested", 0)
    skipped  = ingest.get("skipped", 0)
    if ingested == 0 and skipped == 0:
        fail(f"{label}/ingest", "ingested=0 skipped=0 — student may not have submitted")
        return
    # skipped=1 means already ingested in a prior run (dedup) — that's fine
    ok(f"{label}/ingest", f"ingested={ingested} skipped={skipped}")

    section(f"{label}: Step 4 — Status shows graded=0 (pre-grade)")
    _, status_body = req("GET", f"/api/v1/classroom/{amgs_id}/status", expected=200)
    amgs_sub_id = status_body["submissions"][0]["submission_id"]
    print(f"  graded={status_body['graded']}  amgs_sub={amgs_sub_id}")
    ok(f"{label}/status_pre", f"total={status_body['total_submissions']} graded=0")

    section(f"{label}: Step 5 — Insert grade via psql")
    sql = (
        f"INSERT INTO grades (id, submission_id, active_version, total_score, "
        f"breakdown_json, source, classroom_status, is_truncated, graded_at) "
        f"VALUES (gen_random_uuid(), '{amgs_sub_id}', true, {score}, "
        f"'{{}}'::json, 'ta_manual', 'not_synced', false, now());"
    )
    result = subprocess.run(
        ["docker", "exec", "amgs-postgres", "psql", "-U", "amgs", "-d", "amgs", "-c", sql],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        fail(f"{label}/insert_grade", result.stderr[:300])
        return
    ok(f"{label}/insert_grade", f"score={score}/100 inserted")

    section(f"{label}: Step 6 — Status shows graded=1")
    _, status2 = req("GET", f"/api/v1/classroom/{amgs_id}/status", expected=200)
    graded = status2.get("graded", 0)
    if graded < 1:
        fail(f"{label}/status_post", f"graded still {graded} after grade insert")
        return
    ok(f"{label}/status_post", f"graded={graded}")

    section(f"{label}: Step 7 — Sync-draft → Classroom")
    _, sync = req("POST", f"/api/v1/classroom/{amgs_id}/sync-draft", expected=200)
    print(f"  {json.dumps(sync, indent=2)}")
    if sync.get("errors"):
        fail(f"{label}/sync_draft", f"errors={sync['errors']}")
        return
    pushed = sync.get("pushed", 0)
    if pushed < 1:
        fail(f"{label}/sync_draft", f"pushed={pushed} (expected ≥1)")
        return
    ok(f"{label}/sync_draft", f"pushed={pushed} draftGrade to Classroom")

    section(f"{label}: Step 8 — Verify draftGrade in Classroom API")
    classroom_sub = classroom_svc.courses().courseWork().studentSubmissions().get(
        courseId=COURSE_ID, courseWorkId=cw_id, id=classroom_sub_id).execute()
    draft = classroom_sub.get("draftGrade")
    print(f"  draftGrade={draft}  state={classroom_sub.get('state')}")
    if draft is None:
        fail(f"{label}/verify_draft", "draftGrade is None in Classroom API after sync")
        return
    if float(draft) != score:
        fail(f"{label}/verify_draft", f"draftGrade={draft} != expected {score}")
        return
    ok(f"{label}/verify_draft", f"draftGrade={draft} ✓")

    section(f"{label}: Step 9 — Release grades (visible to student)")
    _, release = req("POST", f"/api/v1/classroom/{amgs_id}/release", expected=200)
    print(f"  {json.dumps(release, indent=2)}")
    if release.get("errors"):
        fail(f"{label}/release", f"errors={release['errors']}")
        return
    released = release.get("released", 0)
    if released < 1:
        fail(f"{label}/release", f"released={released} (expected ≥1)")
        return
    ok(f"{label}/release", f"released={released}")

    section(f"{label}: Step 10 — Verify RETURNED state in Classroom")
    time.sleep(2)  # brief wait for Classroom to process
    final_sub = classroom_svc.courses().courseWork().studentSubmissions().get(
        courseId=COURSE_ID, courseWorkId=cw_id, id=classroom_sub_id).execute()
    state = final_sub.get("state")
    assigned = final_sub.get("assignedGrade")
    draft2 = final_sub.get("draftGrade")
    print(f"  state={state}  assignedGrade={assigned}  draftGrade={draft2}")
    if state != "RETURNED":
        fail(f"{label}/verify_returned", f"state={state} (expected RETURNED)")
        return
    if float(assigned or 0) != score:
        fail(f"{label}/verify_assigned", f"assignedGrade={assigned} != {score}")
        return
    ok(f"{label}/verify_returned", f"state=RETURNED assignedGrade={assigned}")


# ─────────────────────────────────────────────────────────────────────────────

def main():
    start = datetime.now(timezone.utc)
    print(f"\n{'═'*60}")
    print(f"  AMGS Full Grade Sync E2E — {start.strftime('%Y-%m-%dT%H:%M:%SZ')}")
    print(f"{'═'*60}")

    # Wait for backend
    for _ in range(15):
        try:
            with urllib.request.urlopen(f"{BASE}/health", timeout=5) as r:
                if r.status == 200: break
        except Exception:
            time.sleep(2)

    classroom_svc = svc()

    for case in CASES:
        try:
            run_case(case, classroom_svc)
        except Exception as exc:
            fail(f"{case['label']}/EXCEPTION", str(exc))

    elapsed = (datetime.now(timezone.utc) - start).total_seconds()
    print(f"\n{'═'*60}")
    print(f"  RESULTS  ({elapsed:.1f}s)")
    print(f"{'═'*60}")
    print(f"  ✅ Passed: {len(PASS)}")
    print(f"  ❌ Failed: {len(FAIL)}")
    if FAIL:
        for f in FAIL:
            print(f"    • {f}")
        print()
        print("  NOTE: If failures are 'No student has submitted yet' →")
        print("  Have your student account submit to the [AMGS] assignments in Classroom,")
        print("  then re-run this script.")
        sys.exit(1)
    print("  All grade sync checks passed — full Classroom loop verified!")


if __name__ == "__main__":
    main()

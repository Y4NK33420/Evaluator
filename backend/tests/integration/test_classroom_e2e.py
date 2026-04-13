#!/usr/bin/env python3
"""
AMGS Google Classroom Real-World E2E Test
==========================================
Tests the full flow against a real Google Classroom course:
  1. Auth status check
  2. List available courses (teacher view)
  3. Ingest submissions from a Classroom assignment into AMGS
  4. Verify submissions appear in AMGS
  5. Push draft grades back to Classroom
  6. Optionally release grades

Prerequisites:
  1. Run: python backend/app/services/get_classroom_token.py
  2. Create a course in Google Classroom (teacher account)
  3. Create an assignment in that course ("AMGS Test Assignment")
  4. (Optional) Have a student account submit work
  5. Set CLASSROOM_COURSE_ID and CLASSROOM_COURSEWORK_ID below, or pass as env vars

Usage:
    # Quick: just test auth + list courses
    python backend/tests/integration/test_classroom_e2e.py --list-courses

    # Full flow (requires course + coursework IDs):
    CLASSROOM_COURSE_ID=<id> CLASSROOM_COURSEWORK_ID=<cw_id> \\
        python backend/tests/integration/test_classroom_e2e.py
"""

import json
import os
import sys
import time
import urllib.request
import urllib.error
import urllib.parse
import argparse
from datetime import datetime, timezone

BASE = "http://localhost:8080"

# ── Override these or set as env vars ─────────────────────────────────────────
CLASSROOM_COURSE_ID     = os.getenv("CLASSROOM_COURSE_ID", "")
CLASSROOM_COURSEWORK_ID = os.getenv("CLASSROOM_COURSEWORK_ID", "")

PASS = []
FAIL = []


# ── HTTP helpers ──────────────────────────────────────────────────────────────

def _req(method, path, body=None, expected_status=None):
    url = BASE + path
    data = json.dumps(body).encode() if body is not None else None
    for _attempt in range(3):
        req = urllib.request.Request(
            url, data=data, method=method,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw, status = resp.read(), resp.status
        except urllib.error.HTTPError as e:
            raw, status = e.read(), e.code
            if status in (307, 308):
                location = e.headers.get("Location", "")
                url = (BASE + location) if location.startswith("/") else location
                continue
        if status in (307, 308):
            continue
        break
    parsed = json.loads(raw) if raw else {}
    if expected_status is not None and status != expected_status:
        raise AssertionError(
            f"{method} {path} → expected {expected_status}, got {status}\n"
            f"Body: {json.dumps(parsed, indent=2)}"
        )
    return status, parsed

def GET(path, expected_status=200): return _req("GET", path, expected_status=expected_status)
def POST(path, body=None, expected_status=200): return _req("POST", path, body=body, expected_status=expected_status)

def ok(name, detail=""):
    PASS.append(name); print(f"  ✅ {name}" + (f"  — {detail}" if detail else ""))
def fail(name, reason):
    FAIL.append(name); print(f"  ❌ {name}  — {reason}", file=sys.stderr)
def section(t): print(f"\n{'─'*60}\n  {t}\n{'─'*60}")


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_auth_status():
    section("T1: Auth Status")
    _, body = GET("/api/v1/classroom/auth-status")
    print(f"  Response: {json.dumps(body, indent=2)}")
    if not body.get("authenticated"):
        fail("T1/authenticated", f"Not authenticated: {body.get('reason')}")
        print("\n  ⚠️  Run: python backend/app/services/get_classroom_token.py")
        return False
    if not body.get("valid"):
        fail("T1/token_valid", f"Token not valid: {body}")
        return False
    ok("T1/authenticated", f"token_valid=True")
    return True


def test_list_courses():
    """Use the Classroom API directly via the sync service to list courses."""
    section("T2: List Classroom Courses (via auth-status extended)")
    # The auth-status endpoint returns basic status; list courses via Classroom API directly
    try:
        from googleapiclient.discovery import build
        from google.oauth2.credentials import Credentials
        import json as _json
        from pathlib import Path
        token_path = Path("backend/app/services/google_auth/token.json")
        if not token_path.exists():
            fail("T2/list_courses", f"token.json not found at {token_path}")
            return []
        creds_data = _json.loads(token_path.read_text())
        creds = Credentials(
            token=creds_data.get("token"),
            refresh_token=creds_data.get("refresh_token"),
            token_uri=creds_data.get("token_uri"),
            client_id=creds_data.get("client_id"),
            client_secret=creds_data.get("client_secret"),
            scopes=creds_data.get("scopes"),
        )
        svc = build("classroom", "v1", credentials=creds)
        courses = svc.courses().list(courseStates=["ACTIVE"]).execute().get("courses", [])
        if not courses:
            print("  No active courses found in Classroom.")
            print("  → Create a course at https://classroom.google.com")
            ok("T2/list_courses", "authenticated but 0 courses")
            return []
        print(f"\n  📚 Active courses ({len(courses)}):")
        for c in courses:
            print(f"    [{c['id']}] {c['name']}  enrollmentCode={c.get('enrollmentCode','?')}")
        ok("T2/list_courses", f"{len(courses)} courses found")
        return courses
    except Exception as e:
        fail("T2/list_courses", str(e))
        return []


def test_ingest(course_id: str, coursework_id: str, amgs_assignment_id: str):
    section(f"T3: Ingest submissions — course={course_id} cw={coursework_id}")
    status, body = POST(
        f"/api/v1/classroom/{amgs_assignment_id}/ingest",
        {"course_id": course_id, "coursework_id": coursework_id},
        expected_status=200,
    )
    print(f"  Response: {json.dumps(body, indent=2)}")
    ingested = body.get("ingested", 0)
    skipped  = body.get("skipped", 0)
    errors   = body.get("errors", [])
    if errors:
        fail("T3/ingest_errors", f"Errors during ingestion: {errors}")
    else:
        ok("T3/ingest", f"ingested={ingested} skipped={skipped}")
    return ingested


def test_classroom_status(amgs_assignment_id: str):
    section(f"T4: Classroom status — assignment={amgs_assignment_id}")
    _, body = GET(f"/api/v1/classroom/{amgs_assignment_id}/status")
    print(f"  Response: {json.dumps(body, indent=2)}")
    total = body.get("total_submissions", 0)
    graded = body.get("graded", 0)
    ok("T4/status", f"total={total} graded={graded} ungraded={body.get('ungraded',0)}")
    return body


def test_sync_draft(amgs_assignment_id: str):
    section(f"T5: Sync draft grades → Classroom")
    _, body = POST(f"/api/v1/classroom/{amgs_assignment_id}/sync-draft")
    print(f"  Response: {json.dumps(body, indent=2)}")
    pushed = body.get("pushed", 0)
    errors = body.get("errors", [])
    if errors:
        fail("T5/sync_draft_errors", f"Grade sync errors: {errors}")
    else:
        ok("T5/sync_draft", f"pushed={pushed} skipped={body.get('skipped',0)}")
    return pushed


def test_release(amgs_assignment_id: str):
    section(f"T6: Release grades (publish to students)")
    _, body = POST(f"/api/v1/classroom/{amgs_assignment_id}/release")
    print(f"  Response: {json.dumps(body, indent=2)}")
    released = body.get("released", 0)
    errors = body.get("errors", [])
    if errors:
        fail("T6/release_errors", f"Release errors: {errors}")
    else:
        ok("T6/release", f"released={released}")
    return released


# ── Setup helpers ─────────────────────────────────────────────────────────────

def create_test_assignment(course_id: str, coursework_id: str) -> str:
    """Create an AMGS assignment linked to the Classroom coursework."""
    import uuid
    _, asgn = POST("/api/v1/assignments/", {
        "course_id": f"classroom-{course_id}",
        "classroom_id": coursework_id,
        "title": f"Classroom E2E Test [{coursework_id[:8]}]",
        "description": "Auto-created by AMGS Classroom E2E test",
        "deadline": "2099-01-01T00:00:00Z",
        "max_marks": 10,
        "question_type": "subjective",
        "has_code_question": False,
    }, expected_status=201)
    print(f"  Created AMGS assignment: {asgn['id']}")
    return asgn["id"]


def wait_for_backend():
    print("⏳ Waiting for backend...")
    for _ in range(30):
        try:
            with urllib.request.urlopen(f"{BASE}/health", timeout=5) as r:
                if r.status == 200:
                    print(f"✅ Backend ready")
                    return
        except Exception:
            time.sleep(2)
    print("❌ Backend not reachable", file=sys.stderr)
    sys.exit(1)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="AMGS Classroom E2E Test")
    parser.add_argument("--list-courses", action="store_true",
                        help="Only check auth and list courses, then exit")
    parser.add_argument("--course-id", default=CLASSROOM_COURSE_ID)
    parser.add_argument("--coursework-id", default=CLASSROOM_COURSEWORK_ID)
    parser.add_argument("--release", action="store_true",
                        help="Also release grades at the end (makes them visible to students)")
    args = parser.parse_args()

    start = datetime.now(timezone.utc)
    print(f"\n{'═'*60}")
    print(f"  AMGS Classroom Real-World E2E")
    print(f"  {start.strftime('%Y-%m-%dT%H:%M:%SZ')}")
    print(f"{'═'*60}")

    wait_for_backend()

    # T1 — Auth
    authed = test_auth_status()
    if not authed:
        print("\n❌ Cannot proceed — not authenticated with Google.")
        sys.exit(1)

    # T2 — List courses
    courses = test_list_courses()

    if args.list_courses:
        print(f"\n{'═'*60}")
        print(f"  Listed courses. Use --course-id and --coursework-id to run full flow.")
        print(f"{'═'*60}")
        sys.exit(0)

    # Validate IDs
    course_id     = args.course_id
    coursework_id = args.coursework_id
    if not course_id or not coursework_id:
        print("\n⚠️  No course/coursework IDs provided. Options:")
        print("  1. Run with --list-courses first to find your course IDs")
        print("  2. Then: python test_classroom_e2e.py --course-id <id> --coursework-id <cw_id>")
        print("  3. Or set env vars: CLASSROOM_COURSE_ID and CLASSROOM_COURSEWORK_ID")
        if courses:
            print(f"\n  Found {len(courses)} courses above. Copy the ID from the list.")
        sys.exit(0)

    # Create AMGS assignment linked to this coursework
    section("Setup: Create AMGS assignment")
    amgs_id = create_test_assignment(course_id, coursework_id)

    # T3 — Ingest
    ingested = test_ingest(course_id, coursework_id, amgs_id)

    # T4 — Status
    test_classroom_status(amgs_id)

    # T5 — Sync draft (only if there are submissions with grades)
    test_sync_draft(amgs_id)

    # T6 — Release (optional)
    if args.release:
        test_release(amgs_id)

    elapsed = (datetime.now(timezone.utc) - start).total_seconds()
    print(f"\n{'═'*60}")
    print(f"  RESULTS  ({elapsed:.1f}s)")
    print(f"{'═'*60}")
    print(f"  ✅ Passed: {len(PASS)}")
    print(f"  ❌ Failed: {len(FAIL)}")
    if FAIL:
        for f in FAIL:
            print(f"    • {f}")
        sys.exit(1)
    else:
        print("  All Classroom checks passed.")


if __name__ == "__main__":
    main()

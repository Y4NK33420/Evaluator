"""Google Classroom integration — submission ingestion + grade sync.

Covers:
  - OAuth credential management (file-based token refresh)
  - Submission ingestion: pull student work from Classroom after deadline
  - Grade push: draftGrade and assignedGrade via Classroom API
  - Drive file download for attached PDFs/images

Design notes:
  - All Classroom API calls are synchronous; callers should run in a Celery task.
  - drive_service is built alongside classroom_service to fetch file bytes.
  - SHA-256 content-hash dedup is relied upon by the submission upload path —
    this service does not re-implement it.
"""

from __future__ import annotations

import hashlib
import io
import logging
import mimetypes
from pathlib import Path
from typing import Any

from app.config import get_settings

log = logging.getLogger(__name__)
settings = get_settings()

# ── OAuth / service construction ──────────────────────────────────────────────

_SCOPES = [
    "https://www.googleapis.com/auth/classroom.courses.readonly",
    "https://www.googleapis.com/auth/classroom.coursework.students",
    "https://www.googleapis.com/auth/classroom.rosters.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]

_FRIENDLY_SCOPE_NAMES = {
    "https://www.googleapis.com/auth/classroom.courses.readonly": "Read courses",
    "https://www.googleapis.com/auth/classroom.coursework.students": "Manage coursework + grades",
    "https://www.googleapis.com/auth/classroom.rosters.readonly": "Read rosters",
    "https://www.googleapis.com/auth/drive.readonly": "Read Drive attachments",
}


def _get_services() -> tuple[Any, Any]:
    """Return (classroom_service, drive_service), refreshing credentials as needed."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    creds = None
    token_path = Path(settings.google_token_file)
    creds_path = Path(settings.google_credentials_file)

    if token_path.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(token_path), _SCOPES)
        except Exception as exc:
            log.warning("Could not load token.json: %s — will re-authorize", exc)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            log.info("Refreshing expired Google credentials")
            creds.refresh(Request())
        else:
            if not creds_path.exists():
                raise FileNotFoundError(
                    f"credentials.json not found at {creds_path}. "
                    "Download it from GCP Console → APIs & Services → Credentials."
                )
            raise PermissionError(
                "Google token requires interactive re-auth. "
                "Use /api/v1/classroom/generate-token from UI first."
            )
        token_path.write_text(creds.to_json())
        log.info("Google credentials saved to %s", token_path)

    classroom_svc = build("classroom", "v1", credentials=creds, cache_discovery=False)
    drive_svc = build("drive", "v3", credentials=creds, cache_discovery=False)
    return classroom_svc, drive_svc


def regenerate_token(*, force_reauth: bool = False) -> dict:
    """Run OAuth flow explicitly and return fresh auth status."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    token_path = Path(settings.google_token_file)
    creds_path = Path(settings.google_credentials_file)
    if not creds_path.exists():
        raise FileNotFoundError(
            f"credentials.json not found at {creds_path}. "
            "Download it from GCP Console → APIs & Services → Credentials."
        )

    if force_reauth and token_path.exists():
        token_path.unlink()
        log.info("Removed existing token to force full OAuth re-consent")

    base_port = int(settings.google_oauth_callback_port)
    span = max(0, int(settings.google_oauth_callback_port_span))
    last_exc: Exception | None = None
    creds = None
    for port in range(base_port, base_port + span + 1):
        flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), _SCOPES)
        try:
            creds = flow.run_local_server(
                host=settings.google_oauth_callback_host,
                bind_addr=settings.google_oauth_callback_bind_addr,
                port=port,
                open_browser=False,
                authorization_prompt_message=(
                    "Open this URL in any browser to authorize Classroom access:\n{url}"
                ),
                prompt="consent",
                access_type="offline",
                include_granted_scopes="true",
            )
            break
        except OSError as exc:
            last_exc = exc
            log.warning("OAuth callback port %s unavailable: %s", port, exc)
            continue
    if creds is None:
        raise RuntimeError(
            f"No available OAuth callback port in range {base_port}-{base_port + span}"
        ) from last_exc
    token_path.write_text(creds.to_json())
    log.info("Google credentials saved to %s", token_path)
    return get_auth_status()


def get_auth_status() -> dict:
    """Return credential validity without triggering a browser flow."""
    token_path = Path(settings.google_token_file)
    creds_path = Path(settings.google_credentials_file)

    if not token_path.exists():
        return {
            "authenticated": False,
            "reason": "token_missing",
            "token_path": str(token_path),
            "credentials_file_exists": creds_path.exists(),
        }

    try:
        from google.oauth2.credentials import Credentials
        creds = Credentials.from_authorized_user_file(str(token_path), _SCOPES)
        granted_scopes = set(creds.scopes or [])
        required_scopes = set(_SCOPES)
        missing_scopes = sorted(required_scopes - granted_scopes)
        has_required_scopes = len(missing_scopes) == 0
        return {
            "authenticated": True,
            "valid": creds.valid,
            "expired": creds.expired,
            "has_refresh_token": bool(creds.refresh_token),
            "scopes": list(creds.scopes or []),
            "friendly_scopes": [
                _FRIENDLY_SCOPE_NAMES.get(scope, scope) for scope in list(creds.scopes or [])
            ],
            "required_scopes": list(_SCOPES),
            "missing_scopes": missing_scopes,
            "has_required_scopes": has_required_scopes,
            "ready": bool(creds.valid) and has_required_scopes,
        }
    except Exception as exc:
        return {"authenticated": False, "reason": str(exc)}


def get_coursework(course_id: str, coursework_id: str) -> dict:
    """Fetch a specific coursework record."""
    classroom_svc, _ = _get_services()
    return (
        classroom_svc.courses()
        .courseWork()
        .get(courseId=course_id, id=coursework_id)
        .execute()
    )


def list_coursework(course_id: str, page_size: int = 30) -> list[dict]:
    """List coursework entries for a course (newest first from Classroom API)."""
    classroom_svc, _ = _get_services()
    resp = (
        classroom_svc.courses()
        .courseWork()
        .list(courseId=course_id, pageSize=max(1, min(page_size, 100)))
        .execute()
    )
    return resp.get("courseWork", [])


def list_course_students(course_id: str, page_size: int = 100) -> list[dict]:
    """List enrolled students for a Classroom course."""
    classroom_svc, _ = _get_services()
    students: list[dict] = []
    page_token: str | None = None
    while True:
        resp = (
            classroom_svc.courses()
            .students()
            .list(
                courseId=course_id,
                pageSize=max(1, min(page_size, 100)),
                pageToken=page_token,
            )
            .execute()
        )
        students.extend(resp.get("students", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return students


def create_coursework_for_assignment(
    *,
    course_id: str,
    title: str,
    description: str | None,
    max_points: float,
    state: str = "PUBLISHED",
) -> dict:
    """Create Classroom coursework for an AMGS assignment."""
    classroom_svc, _ = _get_services()
    body = {
        "title": title,
        "description": description or "",
        "workType": "ASSIGNMENT",
        "state": state,
        "maxPoints": float(max_points),
    }
    return (
        classroom_svc.courses()
        .courseWork()
        .create(courseId=course_id, body=body)
        .execute()
    )


def update_coursework_for_assignment(
    *,
    course_id: str,
    coursework_id: str,
    title: str | None = None,
    description: str | None = None,
    max_points: float | None = None,
    state: str | None = None,
) -> dict:
    """Patch supported coursework fields for an existing assignment."""
    classroom_svc, _ = _get_services()
    body: dict[str, Any] = {}
    update_mask: list[str] = []
    if title is not None:
        body["title"] = title
        update_mask.append("title")
    if description is not None:
        body["description"] = description
        update_mask.append("description")
    if max_points is not None:
        body["maxPoints"] = float(max_points)
        update_mask.append("maxPoints")
    if state is not None:
        body["state"] = state
        update_mask.append("state")
    if not update_mask:
        raise ValueError("No coursework fields provided to update")

    return (
        classroom_svc.courses()
        .courseWork()
        .patch(
            courseId=course_id,
            id=coursework_id,
            updateMask=",".join(update_mask),
            body=body,
        )
        .execute()
    )


def validate_coursework_grade_sync_target(course_id: str, coursework_id: str) -> dict:
    """Ensure coursework is safe/eligible for grade push from this app."""
    cw = get_coursework(course_id, coursework_id)
    checks = {
        "coursework_exists": bool(cw),
        "work_type_assignment": cw.get("workType") == "ASSIGNMENT",
        "associated_with_developer": bool(cw.get("associatedWithDeveloper")),
    }
    missing = [k for k, ok in checks.items() if not ok]
    return {
        "coursework": cw,
        "checks": checks,
        "ready": not missing,
        "missing": missing,
    }


# ── Submission ingestion ───────────────────────────────────────────────────────

def _drive_file_bytes(drive_svc: Any, file_id: str) -> bytes:
    """Download a Drive file by ID and return its raw bytes."""
    from googleapiclient.http import MediaIoBaseDownload

    request = drive_svc.files().get_media(fileId=file_id)
    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return buf.getvalue()


def _guess_extension(mime_type: str | None, filename: str | None) -> str:
    if filename:
        suffix = Path(filename).suffix.lower()
        if suffix in {".pdf", ".jpg", ".jpeg", ".png", ".gif", ".webp"}:
            return suffix
    if mime_type:
        ext = mimetypes.guess_extension(mime_type)
        if ext:
            return ext
    return ".bin"


def ingest_course_submissions(
    course_id: str,
    coursework_id: str,
    db,
    *,
    assignment_id: str | None = None,
    force_reingest: bool = False,
) -> dict:
    """Pull all TURNED_IN student submissions from Classroom and store them in DB.

    Returns a summary dict with counts: found, skipped (already in DB), ingested, errors.
    """
    from app.models import Assignment, Submission

    classroom_svc, drive_svc = _get_services()

    # Resolve the AMGS assignment — prefer explicit ID, fall back to classroom_id lookup
    assignment = None
    if assignment_id:
        assignment = db.get(Assignment, assignment_id)
    if not assignment:
        assignment = (
            db.query(Assignment)
            .filter(Assignment.classroom_id == coursework_id)
            .first()
        )
    if not assignment:
        raise ValueError(
            f"No local assignment found with classroom_id={coursework_id}. "
            "Create the assignment in AMGS first."
        )

    log.info(
        "classroom_ingest: course=%s coursework=%s assignment=%s",
        course_id, coursework_id, assignment.id,
    )

    # Page through all student submissions
    all_submissions: list[dict] = []
    page_token: str | None = None
    while True:
        resp = (
            classroom_svc.courses()
            .courseWork()
            .studentSubmissions()
            .list(
                courseId=course_id,
                courseWorkId=coursework_id,
                states=["TURNED_IN", "RETURNED"],
                pageToken=page_token,
            )
            .execute()
        )
        all_submissions.extend(resp.get("studentSubmissions", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    log.info("classroom_ingest: found %d submissions in Classroom", len(all_submissions))

    summary = {"found": len(all_submissions), "skipped": 0, "ingested": 0, "errors": [], "submission_ids": []}

    for cs in all_submissions:
        student_id = cs.get("userId", "unknown")
        classroom_sub_id = cs.get("id", "")
        state = cs.get("state", "")

        if state not in {"TURNED_IN", "RETURNED"}:
            summary["skipped"] += 1
            continue

        # Check if already ingested (by student_id x assignment_id)
        existing = (
            db.query(Submission)
            .filter(
                Submission.assignment_id == assignment.id,
                Submission.student_id == student_id,
            )
            .first()
        )
        if existing and not force_reingest:
            log.debug(
                "classroom_ingest: student %s already has submission %s — skip",
                student_id, existing.id,
            )
            summary["skipped"] += 1
            continue

        # Resolve student profile for display name
        student_name = student_id
        try:
            profile = (
                classroom_svc.courses()
                .students()
                .get(courseId=course_id, userId=student_id)
                .execute()
            )
            student_name = profile.get("profile", {}).get("name", {}).get("fullName", student_id)
        except Exception:
            pass  # name is cosmetic — don't fail the ingest

        # Find the best attachment to download
        attachments = []
        for attachment in cs.get("assignmentSubmission", {}).get("attachments", []):
            drive_file = attachment.get("driveFile")
            if drive_file:
                attachments.append(drive_file)

        if not attachments:
            log.warning(
                "classroom_ingest: student %s submission %s has no drive attachments",
                student_id, classroom_sub_id,
            )
            summary["errors"].append({
                "student_id": student_id,
                "reason": "no_attachments",
            })
            continue

        # Download the first attachment (primary submission file)
        drive_file = attachments[0]
        file_id = drive_file.get("id") or drive_file.get("driveFile", {}).get("id")
        filename = drive_file.get("title") or drive_file.get("driveFile", {}).get("title")
        mime_type = drive_file.get("mimeType") or drive_file.get("driveFile", {}).get("mimeType")

        try:
            file_bytes = _drive_file_bytes(drive_svc, file_id)
        except Exception as exc:
            log.error(
                "classroom_ingest: failed to download drive file %s for student %s: %s",
                file_id, student_id, exc,
            )
            summary["errors"].append({"student_id": student_id, "reason": str(exc)})
            continue

        # Compute content hash for dedup
        content_hash = hashlib.sha256(file_bytes).hexdigest()
        ext = _guess_extension(mime_type, filename)

        # Check hash collision across submissions
        hash_collision = (
            db.query(Submission)
            .filter(
                Submission.assignment_id == assignment.id,
                Submission.image_hash == content_hash,
            )
            .first()
        )
        if hash_collision and not force_reingest:
            log.warning(
                "classroom_ingest: student %s file has same hash as student %s — skip duplicate",
                student_id, hash_collision.student_id,
            )
            summary["skipped"] += 1
            continue

        # Persist file
        import os
        from datetime import datetime, timezone
        uploads_dir = Path(settings.uploads_dir)
        uploads_dir.mkdir(parents=True, exist_ok=True)
        ts = int(datetime.now(timezone.utc).timestamp() * 1000)
        safe_name = f"{assignment.id}_{student_id}_{ts}{ext}"
        file_path = uploads_dir / safe_name
        file_path.write_bytes(file_bytes)

        if existing:
            # Update in place when force_reingest
            existing.file_path = str(file_path)
            existing.image_hash = content_hash
            existing.status = "ocr_done" if assignment.has_code_question else "pending"
            existing.ocr_result = None
            existing.error_message = None
            db.flush()
            sub_id = existing.id
        else:
            sub = Submission(
                assignment_id=assignment.id,
                student_id=student_id,
                student_name=student_name,
                file_path=str(file_path),
                image_hash=content_hash,
                status="ocr_done" if assignment.has_code_question else "pending",
            )
            db.add(sub)
            db.flush()
            sub_id = sub.id

        log.info(
            "classroom_ingest: ingested student=%s submission=%s file=%s",
            student_id, sub_id, safe_name,
        )
        summary["ingested"] += 1
        summary["submission_ids"].append(sub_id)

    db.commit()

    # Auto-dispatch processing for ingested written submissions.
    # (Coding submissions follow separate code-eval dispatch flow.)
    if not assignment.has_code_question:
        try:
            from app.workers.ocr_tasks import run_ocr_task
            for sid in summary["submission_ids"]:
                run_ocr_task.delay(sid)
        except Exception as exc:
            log.warning("classroom_ingest: failed to enqueue OCR tasks: %s", exc)

    log.info("classroom_ingest complete: %s", summary)
    return summary


# ── Grade push ────────────────────────────────────────────────────────────────

def _get_submission_meta(submission_id: str, db) -> tuple[str, str, str]:
    """Return (course_id, coursework_id, classroom_student_id) for a DB submission."""
    from app.models import Submission

    sub = db.get(Submission, submission_id)
    if not sub or not sub.assignment:
        raise ValueError(f"Submission {submission_id} or its assignment not found")

    course_id = sub.assignment.course_id
    # Strip 'classroom-' prefix if it was stored with it (defensive compat)
    if course_id and course_id.startswith("classroom-"):
        course_id = course_id[len("classroom-"):]
    coursework_id = sub.assignment.classroom_id
    student_id = sub.student_id

    if not coursework_id:
        raise ValueError(
            f"Assignment {sub.assignment_id} has no classroom_id set. "
            "Set classroom_id when creating the assignment."
        )
    return course_id, coursework_id, student_id


def push_draft_grade(submission_id: str, score: float, db) -> None:
    """PATCH studentSubmission draftGrade — does NOT release to student."""
    classroom_svc, _ = _get_services()
    course_id, cw_id, student_id = _get_submission_meta(submission_id, db)

    # We need the Classroom submission ID — list to find by userId
    resp = (
        classroom_svc.courses()
        .courseWork()
        .studentSubmissions()
        .list(courseId=course_id, courseWorkId=cw_id, userId=student_id)
        .execute()
    )
    subs = resp.get("studentSubmissions", [])
    if not subs:
        raise ValueError(
            f"No Classroom submission found for student {student_id} "
            f"in course {course_id} / coursework {cw_id}"
        )
    classroom_sub_id = subs[0]["id"]

    classroom_svc.courses().courseWork().studentSubmissions().patch(
        courseId=course_id,
        courseWorkId=cw_id,
        id=classroom_sub_id,
        updateMask="draftGrade",
        body={"draftGrade": float(score)},
    ).execute()

    log.info(
        "push_draft_grade: submission=%s student=%s score=%.2f → draftGrade",
        submission_id, student_id, score,
    )


def push_assigned_grade(submission_id: str, score: float, db) -> None:
    """PATCH assignedGrade and return the submission to students."""
    classroom_svc, _ = _get_services()
    course_id, cw_id, student_id = _get_submission_meta(submission_id, db)

    resp = (
        classroom_svc.courses()
        .courseWork()
        .studentSubmissions()
        .list(courseId=course_id, courseWorkId=cw_id, userId=student_id)
        .execute()
    )
    subs = resp.get("studentSubmissions", [])
    if not subs:
        raise ValueError(
            f"No Classroom submission found for student {student_id} "
            f"in course {course_id} / coursework {cw_id}"
        )
    classroom_sub_id = subs[0]["id"]

    classroom_svc.courses().courseWork().studentSubmissions().patch(
        courseId=course_id,
        courseWorkId=cw_id,
        id=classroom_sub_id,
        updateMask="assignedGrade",
        body={"assignedGrade": float(score)},
    ).execute()

    classroom_svc.courses().courseWork().studentSubmissions().return_(
        courseId=course_id,
        courseWorkId=cw_id,
        id=classroom_sub_id,
        body={},
    ).execute()

    log.info(
        "push_assigned_grade: submission=%s student=%s score=%.2f → assignedGrade+return",
        submission_id,
        student_id,
        score,
    )


def push_draft_grades_bulk(
    assignment_id: str,
    db,
) -> dict:
    """Push draftGrade for ALL completed submissions under an assignment.

    Returns {pushed: int, skipped: int, errors: list}.
    """
    from app.models import Grade, Submission

    subs = (
        db.query(Submission)
        .filter(Submission.assignment_id == assignment_id)
        .all()
    )

    result = {"pushed": 0, "skipped": 0, "errors": []}
    for sub in subs:
        grade = (
            db.query(Grade)
            .filter(Grade.submission_id == sub.id, Grade.active_version == True)
            .first()
        )
        if not grade:
            result["skipped"] += 1
            continue
        try:
            push_draft_grade(sub.id, grade.total_score, db)
            result["pushed"] += 1
        except Exception as exc:
            log.error("push_draft_grades_bulk: sub=%s error=%s", sub.id, exc)
            result["errors"].append({"submission_id": sub.id, "error": str(exc)})

    log.info("push_draft_grades_bulk assignment=%s result=%s", assignment_id, result)
    return result


def release_grades_bulk(assignment_id: str, db) -> dict:
    """Push assignedGrade + return() for ALL completed submissions.

    This makes grades visible to students in Google Classroom.
    Returns {released: int, skipped: int, errors: list}.
    """
    from app.models import Grade, Submission

    subs = (
        db.query(Submission)
        .filter(Submission.assignment_id == assignment_id)
        .all()
    )

    classroom_svc, _ = _get_services()
    result = {"released": 0, "skipped": 0, "errors": []}

    for sub in subs:
        grade = (
            db.query(Grade)
            .filter(Grade.submission_id == sub.id, Grade.active_version == True)
            .first()
        )
        if not grade:
            result["skipped"] += 1
            continue

        try:
            course_id, cw_id, student_id = _get_submission_meta(sub.id, db)
            resp = (
                classroom_svc.courses()
                .courseWork()
                .studentSubmissions()
                .list(courseId=course_id, courseWorkId=cw_id, userId=student_id)
                .execute()
            )
            subs_list = resp.get("studentSubmissions", [])
            if not subs_list:
                result["errors"].append({"submission_id": sub.id, "error": "classroom_sub_not_found"})
                continue
            classroom_sub_id = subs_list[0]["id"]

            # Set assignedGrade
            classroom_svc.courses().courseWork().studentSubmissions().patch(
                courseId=course_id,
                courseWorkId=cw_id,
                id=classroom_sub_id,
                updateMask="assignedGrade",
                body={"assignedGrade": float(grade.total_score)},
            ).execute()

            # Return (makes it visible to student)
            classroom_svc.courses().courseWork().studentSubmissions().return_(
                courseId=course_id,
                courseWorkId=cw_id,
                id=classroom_sub_id,
                body={},
            ).execute()

            log.info(
                "release_grades: sub=%s student=%s score=%.2f → assignedGrade+return",
                sub.id, student_id, grade.total_score,
            )
            result["released"] += 1

        except Exception as exc:
            log.error("release_grades_bulk: sub=%s error=%s", sub.id, exc)
            result["errors"].append({"submission_id": sub.id, "error": str(exc)})

    log.info("release_grades_bulk assignment=%s result=%s", assignment_id, result)
    return result

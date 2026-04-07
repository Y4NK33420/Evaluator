"""Google Classroom grade sync — draft and release."""

import logging
from pathlib import Path

from app.config import get_settings

log = logging.getLogger(__name__)
settings = get_settings()


def _get_classroom_service():
    """Build an authenticated Google Classroom API client."""
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build

    SCOPES = [
        "https://www.googleapis.com/auth/classroom.coursework.students",
        "https://www.googleapis.com/auth/drive.readonly",
    ]

    creds = None
    token_path = Path(settings.google_token_file)
    creds_path = Path(settings.google_credentials_file)

    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not creds_path.exists():
                raise FileNotFoundError(
                    f"credentials.json not found at {creds_path}. "
                    "Follow the GCP setup guide in the implementation plan."
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), SCOPES)
            creds = flow.run_local_server(port=0)
        token_path.write_text(creds.to_json())

    return build("classroom", "v1", credentials=creds)


def _get_submission_meta(submission_id: str, db) -> tuple[str, str, str]:
    """Return (course_id, coursework_id, classroom_submission_id) for a DB submission."""
    from app.models import Submission
    sub = db.get(Submission, submission_id)
    if not sub or not sub.assignment:
        raise ValueError(f"Submission {submission_id} or assignment not found")
    course_id        = sub.assignment.course_id
    coursework_id    = sub.assignment.classroom_id
    classroom_sub_id = sub.student_id        # When syncing from Classroom, store submission ID here
    if not coursework_id:
        raise ValueError("Assignment has no google_classroom_id set")
    return course_id, coursework_id, classroom_sub_id


def push_draft_grade(submission_id: str, score: float, db) -> None:
    """PATCH studentSubmission with draftGrade."""
    svc = _get_classroom_service()
    course_id, cw_id, sub_id = _get_submission_meta(submission_id, db)
    svc.courses().courseWork().studentSubmissions().patch(
        courseId=course_id,
        courseWorkId=cw_id,
        id=sub_id,
        updateMask="draftGrade",
        body={"draftGrade": score},
    ).execute()
    log.info("Draft grade %.1f pushed for submission %s", score, submission_id)


def push_assigned_grade(submission_id: str, score: float, db) -> None:
    """PATCH studentSubmission with assignedGrade and return it."""
    svc = _get_classroom_service()
    course_id, cw_id, sub_id = _get_submission_meta(submission_id, db)
    svc.courses().courseWork().studentSubmissions().patch(
        courseId=course_id,
        courseWorkId=cw_id,
        id=sub_id,
        updateMask="assignedGrade",
        body={"assignedGrade": score},
    ).execute()
    svc.courses().courseWork().studentSubmissions().return_(
        courseId=course_id,
        courseWorkId=cw_id,
        body={"ids": [sub_id]},
    ).execute()
    log.info("Assigned grade %.1f released for submission %s", score, submission_id)

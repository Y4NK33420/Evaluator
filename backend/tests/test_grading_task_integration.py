"""Integration tests for grading task lifecycle and hard rubric gate behavior."""

from unittest.mock import patch

from app.models import (
    Assignment,
    AuditLog,
    Grade,
    QuestionType,
    Rubric,
    RubricSource,
    Submission,
    SubmissionStatus,
)
from app.workers.grading_tasks import run_grading_task


def _mk_assignment(db_session, *, has_code_question: bool = False, question_type=QuestionType.subjective):
    assignment = Assignment(
        course_id="CSE102",
        title="Task Integration",
        max_marks=100.0,
        question_type=question_type,
        has_code_question=has_code_question,
    )
    db_session.add(assignment)
    db_session.commit()
    db_session.refresh(assignment)
    return assignment


def _mk_submission(db_session, assignment_id: str):
    submission = Submission(
        assignment_id=assignment_id,
        student_id="stu-1",
        student_name="Student One",
        file_path="/tmp/fake.jpg",
        image_hash="abc123",
        status=SubmissionStatus.ocr_done,
        ocr_result={
            "blocks": [
                {"index": 0, "question": "Q1", "content": "answer"},
            ],
            "engine": "gemini",
        },
        ocr_engine="gemini",
    )
    db_session.add(submission)
    db_session.commit()
    db_session.refresh(submission)
    return submission


def test_grading_task_blocks_when_no_approved_rubric(db_session):
    assignment = _mk_assignment(db_session)
    submission = _mk_submission(db_session, assignment.id)

    run_grading_task(submission.id)

    db_session.expire_all()
    refreshed = db_session.get(Submission, submission.id)
    assert refreshed.status == SubmissionStatus.failed
    assert "no approved rubric" in (refreshed.error_message or "").lower()

    logs = db_session.query(AuditLog).filter(AuditLog.submission_id == submission.id).all()
    assert any(log.action == "grading_blocked_unapproved_rubric" for log in logs)


def test_grading_task_persists_grade_when_rubric_exists(db_session):
    assignment = _mk_assignment(db_session, question_type=QuestionType.objective)
    submission = _mk_submission(db_session, assignment.id)

    rubric = Rubric(
        assignment_id=assignment.id,
        content_json={
            "questions": [{"id": "Q1", "max_marks": 100, "criteria": []}],
        },
        source=RubricSource.manual,
        approved=True,
    )
    db_session.add(rubric)
    db_session.commit()

    fake_result = {
        "total_score": 88.0,
        "is_truncated": False,
        "breakdown": {"Q1": {"marks_awarded": 88.0, "max_marks": 100.0, "feedback": "ok", "is_truncated": False}},
        "score_details": {
            "granularity": "question_level",
            "question_scores": [{"question_id": "Q1", "marks_awarded": 88.0, "max_marks": 100.0, "feedback": "ok"}],
        },
    }

    with patch("app.workers.grading_tasks.grade_submission", return_value=fake_result), patch(
        "app.workers.grading_tasks.validate_grade", return_value=[]
    ):
        run_grading_task(submission.id)

    db_session.expire_all()
    refreshed = db_session.get(Submission, submission.id)
    assert refreshed.status == SubmissionStatus.graded

    grade = (
        db_session.query(Grade)
        .filter(Grade.submission_id == submission.id, Grade.active_version == True)
        .first()
    )
    assert grade is not None
    assert grade.total_score == 88.0

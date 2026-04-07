"""HTTP-level integration tests for assignment -> rubric -> submission -> grading flow."""

from unittest.mock import patch

from app.models import Submission, SubmissionStatus
from app.workers.grading_tasks import run_grading_task


def _sample_mixed_ocr_result() -> dict:
    # Exact OCR expectation from test_subj.jpeg provided by user.
    return {
        "blocks": [
            {
                "index": 0,
                "question": "Q1",
                "content": "The answer for the given question lies in how the writeer wants the readers to understand the essence of time.",
                "bbox_2d": None,
                "confidence": 0.95,
                "flagged": False,
            },
            {
                "index": 1,
                "question": "Q2.a",
                "content": "4.6",
                "bbox_2d": None,
                "confidence": 0.95,
                "flagged": False,
            },
            {
                "index": 2,
                "question": "Q2.b",
                "content": "3.33",
                "bbox_2d": None,
                "confidence": 0.95,
                "flagged": False,
            },
            {
                "index": 3,
                "question": "Q2.c",
                "content": "8883300",
                "bbox_2d": None,
                "confidence": 0.95,
                "flagged": False,
            },
            {
                "index": 4,
                "question": "Q3",
                "content": "The flower blooms because of sudden sunshine as it lays flat on the grass.",
                "bbox_2d": None,
                "confidence": 0.95,
                "flagged": False,
            },
        ],
        "block_count": 5,
        "flagged_count": 0,
        "engine": "gemini",
    }


def test_http_full_workflow_assignment_to_grade(client, db_session, sample_subj_image_bytes):
    # 1) Create assignment (mixed follows subjective flow in backend)
    assignment_resp = client.post(
        "/api/v1/assignments/",
        json={
            "course_id": "ENG101",
            "title": "Mixed Test Sheet",
            "description": "Q1 subjective, Q2 objective(3 parts), Q3 subjective",
            "max_marks": 10,
            "question_type": "mixed",
            "has_code_question": False,
        },
    )
    assert assignment_resp.status_code == 201, assignment_resp.text
    assignment_id = assignment_resp.json()["id"]

    # 2) Upload approved manual rubric
    rubric_resp = client.post(
        f"/api/v1/rubrics/{assignment_id}",
        json={
            "content_json": {
                "questions": [
                    {"id": "Q1", "max_marks": 4, "criteria": [{"step": "Interpretation", "marks": 4}]},
                    {
                        "id": "Q2",
                        "max_marks": 3,
                        "criteria": [
                            {"step": "Part a", "marks": 1},
                            {"step": "Part b", "marks": 1},
                            {"step": "Part c", "marks": 1},
                        ],
                    },
                    {"id": "Q3", "max_marks": 3, "criteria": [{"step": "Inference", "marks": 3}]},
                ]
            },
            "source": "manual",
        },
    )
    assert rubric_resp.status_code == 201, rubric_resp.text
    assert rubric_resp.json()["approved"] is True

    # 3) Upload submission via HTTP (queue call patched to no-op)
    with patch("app.api.v1.submissions.run_ocr_task.delay", return_value=None):
        upload_resp = client.post(
            f"/api/v1/submissions/{assignment_id}/upload",
            params={"student_id": "stu-100", "student_name": "Student A"},
            files={"file": ("test_subj.jpeg", sample_subj_image_bytes, "image/jpeg")},
        )

    assert upload_resp.status_code == 202, upload_resp.text
    submission_id = upload_resp.json()["submission_id"]

    # 4) Seed OCR result as if OCR task completed.
    submission = db_session.get(Submission, submission_id)
    submission.ocr_result = _sample_mixed_ocr_result()
    submission.ocr_engine = "gemini"
    submission.status = SubmissionStatus.ocr_done
    db_session.commit()

    fake_grade_result = {
        "total_score": 8.0,
        "is_truncated": False,
        "breakdown": {
            "Q1": {"marks_awarded": 3.5, "max_marks": 4.0, "feedback": "Good interpretation", "is_truncated": False},
            "Q2": {"marks_awarded": 2.0, "max_marks": 3.0, "feedback": "Two parts correct", "is_truncated": False},
            "Q3": {"marks_awarded": 2.5, "max_marks": 3.0, "feedback": "Clear reasoning", "is_truncated": False},
        },
        "score_details": {
            "granularity": "rubric_step_level",
            "rubric_step_scores": [
                {"question_id": "Q1", "step_id": "Q1.S1", "step": "Interpretation", "marks_awarded": 3.5, "max_marks": 4.0, "feedback": "Good interpretation"},
                {"question_id": "Q2", "step_id": "Q2.S1", "step": "Part a", "marks_awarded": 1.0, "max_marks": 1.0, "feedback": "Correct"},
                {"question_id": "Q2", "step_id": "Q2.S2", "step": "Part b", "marks_awarded": 1.0, "max_marks": 1.0, "feedback": "Correct"},
                {"question_id": "Q2", "step_id": "Q2.S3", "step": "Part c", "marks_awarded": 0.0, "max_marks": 1.0, "feedback": "Incorrect"},
                {"question_id": "Q3", "step_id": "Q3.S1", "step": "Inference", "marks_awarded": 2.5, "max_marks": 3.0, "feedback": "Clear reasoning"},
            ],
        },
    }

    # 5) Trigger regrade via HTTP OCR-correction endpoint with synchronous grading execution.
    with patch("app.workers.grading_tasks.grade_submission", return_value=fake_grade_result), patch(
        "app.workers.grading_tasks.validate_grade", return_value=[]
    ), patch(
        "app.api.v1.submissions.run_grading_task.delay",
        side_effect=lambda sid: run_grading_task(sid),
    ):
        regrade_resp = client.patch(
            f"/api/v1/submissions/{submission_id}/ocr-correction",
            json={
                "block_index": 0,
                "new_content": "The answer lies in how the writer frames the essence of time.",
                "reason": "Minor OCR typo correction",
                "changed_by": "ta-1",
            },
        )

    assert regrade_resp.status_code == 200, regrade_resp.text
    assert regrade_resp.json()["status"] == "re_grading"

    # 6) Read grade via HTTP endpoint and verify shape.
    grade_resp = client.get(f"/api/v1/submissions/{submission_id}/grade")
    assert grade_resp.status_code == 200, grade_resp.text
    grade = grade_resp.json()
    assert grade["total_score"] == 8.0
    assert grade["breakdown_json"]["score_details"]["granularity"] == "rubric_step_level"

    # 7) Verify audit trail via HTTP includes OCR correction and grading action.
    audit_resp = client.get(f"/api/v1/submissions/{submission_id}/audit")
    assert audit_resp.status_code == 200, audit_resp.text
    actions = [row["action"] for row in audit_resp.json()]
    assert "ocr_correction" in actions
    assert "ai_grade" in actions


def test_http_coding_assignment_rejects_rubric_without_weights(client):
    # Create coding assignment
    assignment_resp = client.post(
        "/api/v1/assignments/",
        json={
            "course_id": "CSE201",
            "title": "Coding assignment",
            "max_marks": 100,
            "question_type": "subjective",
            "has_code_question": True,
        },
    )
    assert assignment_resp.status_code == 201, assignment_resp.text
    assignment_id = assignment_resp.json()["id"]

    # Missing scoring_policy.coding should be hard rejected.
    rubric_resp = client.post(
        f"/api/v1/rubrics/{assignment_id}",
        json={
            "content_json": {
                "questions": [
                    {"id": "Q1", "max_marks": 100, "criteria": [{"step": "Logic", "marks": 100}]}
                ]
            },
            "source": "manual",
        },
    )
    assert rubric_resp.status_code == 422, rubric_resp.text
    assert "scoring_policy.coding" in rubric_resp.text

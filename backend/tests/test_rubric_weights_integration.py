"""Integration tests for rubric upload/approval weight validation rules."""

import pytest
from fastapi import HTTPException

from app.api.v1.rubrics import approve_rubric, upload_rubric
from app.models import Assignment, QuestionType, Rubric
from app.schemas import RubricCreate


def _mk_assignment(db_session, *, has_code_question: bool) -> Assignment:
    assignment = Assignment(
        course_id="CSE101",
        title="Scoring Contract Test",
        max_marks=100.0,
        question_type=QuestionType.subjective,
        has_code_question=has_code_question,
    )
    db_session.add(assignment)
    db_session.commit()
    db_session.refresh(assignment)
    return assignment


def test_coding_assignment_rejects_missing_weightage(db_session):
    assignment = _mk_assignment(db_session, has_code_question=True)
    body = RubricCreate(
        content_json={
            "questions": [{"id": "Q1", "max_marks": 100, "criteria": []}],
        }
    )

    with pytest.raises(HTTPException) as exc:
        upload_rubric(assignment.id, body, db_session)

    assert exc.value.status_code == 422
    assert "scoring_policy.coding" in str(exc.value.detail)


def test_coding_assignment_accepts_explicit_weightage(db_session):
    assignment = _mk_assignment(db_session, has_code_question=True)
    body = RubricCreate(
        content_json={
            "questions": [{"id": "Q1", "max_marks": 100, "criteria": []}],
            "scoring_policy": {
                "coding": {
                    "rubric_weight": 0.25,
                    "testcase_weight": 0.75,
                }
            },
        }
    )

    rubric = upload_rubric(assignment.id, body, db_session)
    assert rubric.approved is True
    assert rubric.content_json["scoring_policy"]["coding"]["testcase_weight"] == 0.75


def test_non_coding_assignment_allows_missing_weightage(db_session):
    assignment = _mk_assignment(db_session, has_code_question=False)
    body = RubricCreate(
        content_json={
            "questions": [{"id": "Q1", "max_marks": 100, "criteria": []}],
        }
    )

    rubric = upload_rubric(assignment.id, body, db_session)
    assert rubric.approved is True


def test_rubric_approval_rejects_existing_invalid_coding_rubric(db_session):
    assignment = _mk_assignment(db_session, has_code_question=True)
    rubric = Rubric(
        assignment_id=assignment.id,
        content_json={
            "questions": [{"id": "Q1", "max_marks": 100, "criteria": []}],
            # invalid: no scoring_policy.coding
        },
        source="ai_generated",
        approved=False,
    )
    db_session.add(rubric)
    db_session.commit()
    db_session.refresh(rubric)

    with pytest.raises(HTTPException) as exc:
        approve_rubric(rubric.id, approved_by="ta-1", db=db_session)

    assert exc.value.status_code == 422

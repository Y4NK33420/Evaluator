"""Rubrics: manual upload + AI generation + approval gate."""

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Assignment, Rubric, RubricSource, AuditLog
from app.schemas import RubricCreate, RubricOut
from app.services.genai_client import ModelServicePermanentError, ModelServiceTransientError
from app.services.rubric_generator import generate_rubric

router = APIRouter(prefix="/rubrics", tags=["rubrics"])


def _parse_coding_weights(content_json: dict) -> tuple[float, float]:
    policy = content_json.get("scoring_policy") if isinstance(content_json, dict) else None
    coding = policy.get("coding") if isinstance(policy, dict) else None
    if not isinstance(coding, dict):
        raise HTTPException(
            status_code=422,
            detail=(
                "Coding assignments require scoring_policy.coding with "
                "rubric_weight and testcase_weight."
            ),
        )

    try:
        rubric_weight = float(coding.get("rubric_weight"))
        testcase_weight = float(coding.get("testcase_weight"))
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=422,
            detail="rubric_weight and testcase_weight must be numeric values.",
        )

    if rubric_weight < 0 or testcase_weight < 0:
        raise HTTPException(
            status_code=422,
            detail="rubric_weight and testcase_weight must be non-negative.",
        )

    total = rubric_weight + testcase_weight
    if total <= 0:
        raise HTTPException(
            status_code=422,
            detail="rubric_weight + testcase_weight must be greater than 0.",
        )

    return rubric_weight, testcase_weight


def _ensure_coding_weights_if_needed(assignment: Assignment, content_json: dict) -> None:
    if assignment.has_code_question:
        _parse_coding_weights(content_json)


@router.post("/{assignment_id}", response_model=RubricOut, status_code=201)
def upload_rubric(assignment_id: str, body: RubricCreate, db: Session = Depends(get_db)):
    """
    Upload a manual rubric (immediately approved).

    For coding assignments, instructors can define weightage in:
        content_json.scoring_policy.coding.rubric_weight
        content_json.scoring_policy.coding.testcase_weight
    """
    assignment = db.get(Assignment, assignment_id)
    if not assignment:
        raise HTTPException(404, "Assignment not found")

    _ensure_coding_weights_if_needed(assignment, body.content_json)

    r = Rubric(
        assignment_id = assignment_id,
        content_json  = body.content_json,
        source        = RubricSource.manual,
        approved      = True,
    )
    db.add(r)
    db.commit()
    db.refresh(r)
    return r


@router.post("/{assignment_id}/generate", response_model=RubricOut, status_code=201)
def ai_generate_rubric(
    assignment_id: str,
    master_answer: str = Body(..., embed=True),
    db: Session = Depends(get_db),
):
    """Generate a rubric from a master answer via Gemini. Requires instructor approval."""
    assignment = db.get(Assignment, assignment_id)
    if not assignment:
        raise HTTPException(404, "Assignment not found")

    try:
        rubric_json = generate_rubric(master_answer, assignment)
    except ModelServiceTransientError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ModelServicePermanentError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    _ensure_coding_weights_if_needed(assignment, rubric_json)

    r = Rubric(
        assignment_id = assignment_id,
        content_json  = rubric_json,
        source        = RubricSource.ai_generated,
        approved      = False,   # must be approved before grading starts
    )
    db.add(r)
    db.commit()
    db.refresh(r)
    return r


@router.post("/{rubric_id}/approve", response_model=RubricOut)
def approve_rubric(
    rubric_id:  str,
    approved_by: str = Body(..., embed=True),
    db: Session = Depends(get_db),
):
    """Instructor approves an AI-generated rubric. Only then can batch grading start."""
    r = db.get(Rubric, rubric_id)
    if not r:
        raise HTTPException(404, "Rubric not found")

    assignment = db.get(Assignment, r.assignment_id)
    if not assignment:
        raise HTTPException(404, "Assignment not found")

    _ensure_coding_weights_if_needed(assignment, r.content_json)

    r.approved    = True
    r.approved_by = approved_by
    db.commit()
    db.refresh(r)
    return r


@router.get("/{assignment_id}", response_model=list[RubricOut])
def list_rubrics(assignment_id: str, db: Session = Depends(get_db)):
    return (
        db.query(Rubric)
        .filter(Rubric.assignment_id == assignment_id)
        .order_by(Rubric.created_at.desc())
        .all()
    )

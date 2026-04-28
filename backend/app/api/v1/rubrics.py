"""Rubrics: manual upload + AI generation + approval gate."""

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Assignment, Rubric, RubricSource, AuditLog
from app.schemas import RubricCreate, RubricOut
from app.services.genai_client import ModelServicePermanentError, ModelServiceTransientError
from app.services.rubric_generator import generate_rubric, encode_natural_language_rubric

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
    assignment_text: str = Body(None, embed=True),
    master_answer: str = Body(None, embed=True),   # backward-compat alias
    db: Session = Depends(get_db),
):
    """Generate a rubric from assignment text / master answer via Gemini.

    Accepts either `assignment_text` (new preferred name) or `master_answer` (legacy).
    Always creates a NEW rubric version — does NOT overwrite existing ones.
    Requires instructor approval before grading can start.
    """
    text = assignment_text or master_answer
    if not text or not text.strip():
        raise HTTPException(422, "Provide assignment_text (or master_answer) to generate a rubric.")

    assignment = db.get(Assignment, assignment_id)
    if not assignment:
        raise HTTPException(404, "Assignment not found")

    try:
        rubric_json = generate_rubric(text, assignment)
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


@router.post("/{assignment_id}/encode-natural-language", response_model=RubricOut, status_code=201)
def encode_nl_rubric(
    assignment_id: str,
    natural_language_rubric: str = Body(..., embed=True),
    db: Session = Depends(get_db),
):
    """Encode a natural-language rubric description into structured rubric JSON.

    The instructor writes rubric criteria in plain English e.g.:
      '5 marks for correct output, 3 marks for code style, 2 marks for edge case handling'
    The AI converts this into the standard questions/criteria schema.
    Creates a NEW rubric version. Requires approval before grading.
    """
    if not natural_language_rubric.strip():
        raise HTTPException(422, "natural_language_rubric cannot be empty.")

    assignment = db.get(Assignment, assignment_id)
    if not assignment:
        raise HTTPException(404, "Assignment not found")

    try:
        rubric_json = encode_natural_language_rubric(natural_language_rubric, assignment)
    except ModelServiceTransientError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ModelServicePermanentError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    _ensure_coding_weights_if_needed(assignment, rubric_json)

    r = Rubric(
        assignment_id = assignment_id,
        content_json  = rubric_json,
        source        = RubricSource.ai_generated,
        approved      = False,
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


@router.patch("/{rubric_id}", response_model=RubricOut)
def update_rubric(
    rubric_id: str,
    content_json: dict = Body(..., embed=True),
    db: Session = Depends(get_db),
):
    """Update rubric content JSON (e.g. manual edits to questions/criteria).
    Resets approved=False so the instructor must re-approve after any edit.
    """
    r = db.get(Rubric, rubric_id)
    if not r:
        raise HTTPException(404, "Rubric not found")

    r.content_json = content_json
    r.approved = False  # require re-approval after any edit
    r.approved_by = None
    db.commit()
    db.refresh(r)
    return r


@router.delete("/{rubric_id}", status_code=204)
def delete_rubric(rubric_id: str, db: Session = Depends(get_db)):
    """Delete a rubric version."""
    r = db.get(Rubric, rubric_id)
    if not r:
        raise HTTPException(404, "Rubric not found")
    db.delete(r)
    db.commit()


@router.get("/{assignment_id}", response_model=list[RubricOut])
def list_rubrics(assignment_id: str, db: Session = Depends(get_db)):
    return (
        db.query(Rubric)
        .filter(Rubric.assignment_id == assignment_id)
        .order_by(Rubric.created_at.desc())
        .all()
    )

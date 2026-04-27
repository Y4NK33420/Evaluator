"""Auto-generate and encode rubrics from assignment text or natural-language descriptions."""

import logging

from app.config import get_settings
from app.services.genai_client import (
    build_structured_json_config,
    generate_structured_json_with_retry,
)

log = logging.getLogger(__name__)
settings = get_settings()

# ── Shared response schema ─────────────────────────────────────────────────────

_RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "questions": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "id": {"type": "STRING", "description": "Question identifier like Q1"},
                    "description": {"type": "STRING", "description": "Question description"},
                    "max_marks": {"type": "NUMBER", "description": "Maximum marks for the question"},
                    "criteria": {
                        "type": "ARRAY",
                        "items": {
                            "type": "OBJECT",
                            "properties": {
                                "step": {"type": "STRING", "description": "Criterion text"},
                                "marks": {"type": "NUMBER", "description": "Marks for this step"},
                                "partial_credit": {"type": "BOOLEAN", "description": "Whether partial credit is allowed"},
                            },
                            "required": ["step", "marks", "partial_credit"],
                            "propertyOrdering": ["step", "marks", "partial_credit"],
                        },
                        "description": "Step-wise marking criteria",
                    },
                },
                "required": ["id", "description", "max_marks", "criteria"],
                "propertyOrdering": ["id", "description", "max_marks", "criteria"],
            },
            "description": "All question rubrics",
        },
        "scoring_policy": {
            "type": "OBJECT",
            "properties": {
                "coding": {
                    "type": "OBJECT",
                    "properties": {
                        "rubric_weight": {"type": "NUMBER"},
                        "testcase_weight": {"type": "NUMBER"},
                    },
                    "required": ["rubric_weight", "testcase_weight"],
                    "propertyOrdering": ["rubric_weight", "testcase_weight"],
                }
            },
            "propertyOrdering": ["coding"],
        },
    },
    "required": ["questions"],
    "propertyOrdering": ["questions", "scoring_policy"],
}

# ── Generate from assignment text / master answer ──────────────────────────────

_GENERATE_SYSTEM = """\
You are an experienced university professor creating a step-wise marking rubric.
Given assignment details (which may include the full question paper, a model answer,
or a description of the assignment), infer how many questions exist, what they are,
and generate a detailed rubric for each.
Be specific. Multiple criteria per question are strongly encouraged for partial credit.
If the text contains explicit question numbers/sections, use them.
If not, infer sensible question boundaries from the structure of the text."""

_GENERATE_PROMPT = """\
Assignment: {title}
Max marks : {max_marks}
Question type: {question_type}
Has code question: {has_code_question}

Assignment text / question paper / model answer:
{assignment_text}

Build a step-wise rubric covering ALL questions in the text.
Allocate marks to each question so they sum to approximately {max_marks}.
For coding assignments, include scoring_policy.coding with rubric_weight and testcase_weight (must sum > 0).
Follow the provided structured response schema exactly."""


def generate_rubric(assignment_text: str, assignment) -> dict:
    """
    Call Gemini to generate a rubric from the assignment text / master answer.
    Returns rubric JSON (stored with approved=False until instructor approves).
    """
    prompt = _GENERATE_PROMPT.format(
        title             = assignment.title,
        max_marks         = assignment.max_marks,
        question_type     = assignment.question_type.value,
        has_code_question = assignment.has_code_question,
        assignment_text   = assignment_text,
    )

    model_name = settings.resolve_rubrics_generation_model()

    cfg = build_structured_json_config(
        response_schema=_RESPONSE_SCHEMA,
        system_instruction=_GENERATE_SYSTEM,
        temperature=0.2,
        top_p=0.95,
        max_output_tokens=8192,
    )
    rubric = generate_structured_json_with_retry(
        model_name=model_name,
        contents=prompt,
        config=cfg,
        operation="Rubric generation",
    )
    log.info("Generated rubric for assignment %s (%d questions)",
             assignment.id, len(rubric.get("questions", [])))
    return rubric


# ── Encode natural-language rubric description ────────────────────────────────

_NL_SYSTEM = """\
You are an expert academic grading assistant. The instructor has described their marking rubric
in plain English. Convert it into a precise, structured marking scheme following the JSON schema.
Preserve the intent and weightings described. If multiple questions are implied, create one entry
per question. If marks don't add up correctly, scale them to fit the total."""

_NL_PROMPT = """\
Assignment: {title}
Max marks : {max_marks}
Question type: {question_type}
Has code question: {has_code_question}

Instructor's rubric description (plain English):
{natural_language_rubric}

Convert the above into a structured JSON rubric.
Ensure all marks sum to approximately {max_marks}.
For coding assignments, include scoring_policy.coding with rubric_weight and testcase_weight.
Follow the provided structured response schema exactly."""


def encode_natural_language_rubric(natural_language_rubric: str, assignment) -> dict:
    """
    Call Gemini to convert a plain-English rubric description into structured JSON.
    Returns rubric JSON (approved=False until instructor approves).
    """
    prompt = _NL_PROMPT.format(
        title                  = assignment.title,
        max_marks              = assignment.max_marks,
        question_type          = assignment.question_type.value,
        has_code_question      = assignment.has_code_question,
        natural_language_rubric = natural_language_rubric,
    )

    model_name = settings.resolve_rubrics_generation_model()

    cfg = build_structured_json_config(
        response_schema=_RESPONSE_SCHEMA,
        system_instruction=_NL_SYSTEM,
        temperature=0.1,
        top_p=0.9,
        max_output_tokens=8192,
    )
    rubric = generate_structured_json_with_retry(
        model_name=model_name,
        contents=prompt,
        config=cfg,
        operation="Natural-language rubric encoding",
    )
    log.info("Encoded NL rubric for assignment %s (%d questions)",
             assignment.id, len(rubric.get("questions", [])))
    return rubric

"""Auto-generate a step-wise rubric from a master answer — google-genai SDK."""

import logging

from app.config import get_settings
from app.services.genai_client import (
    build_structured_json_config,
    generate_structured_json_with_retry,
)

log = logging.getLogger(__name__)
settings = get_settings()

_SYSTEM = """You are an experienced university professor creating a step-wise marking rubric.
Given a model answer and assignment details, generate a detailed rubric.
Be specific. Multiple criteria per question are encouraged for partial credit."""

_PROMPT = """\
Assignment: {title}
Max marks : {max_marks}
Question type: {question_type}
Has code question: {has_code_question}

Master answer / answer key:
{master_answer}

Build a step-wise rubric for all questions.
For coding assignments, include scoring_policy.coding with rubric_weight and testcase_weight.
Follow the provided structured response schema exactly."""

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


def generate_rubric(master_answer: str, assignment) -> dict:
    """
    Call Gemini to generate a rubric from the master answer.
    Returns rubric JSON (stored with approved=False until instructor approves).
    """
    prompt = _PROMPT.format(
        title         = assignment.title,
        max_marks     = assignment.max_marks,
        question_type = assignment.question_type.value,
        has_code_question = assignment.has_code_question,
        master_answer = master_answer,
    )

    model_name = settings.resolve_rubrics_generation_model()

    cfg = build_structured_json_config(
        response_schema=_RESPONSE_SCHEMA,
        system_instruction=_SYSTEM,
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

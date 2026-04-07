"""Integration-style OCR flow tests using the shared sample image bytes."""

from unittest.mock import patch

from app.models import QuestionType
from app.services import ocr_service


def _gemini_blocks_for_three_questions() -> dict:
    # Exact OCR expectation from test_subj.jpeg provided by user:
    # 1) subjective
    # 2) objective with 3 parts
    # 3) subjective
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
        "model": "gemini-3.1-flash-preview",
    }


def test_mixed_type_uses_subjective_flow_only(sample_subj_image_bytes):
    gemini_result = _gemini_blocks_for_three_questions()

    with patch.object(ocr_service, "_gemini_ocr", return_value=gemini_result) as gem_mock, patch.object(
        ocr_service, "_glm_ocr"
    ) as glm_mock:
        result, engine = ocr_service.run_ocr(sample_subj_image_bytes, QuestionType.mixed)

    assert engine == "gemini"
    assert result["block_count"] == 5
    assert result["blocks"][1]["question"] == "Q2.a"
    assert result["blocks"][1]["content"] == "4.6"
    assert result["blocks"][2]["content"] == "3.33"
    assert result["blocks"][3]["content"] == "8883300"
    gem_mock.assert_called_once()
    glm_mock.assert_not_called()


def test_objective_type_keeps_gemini_text_and_glm_regions_separate(sample_subj_image_bytes):
    gemini_result = _gemini_blocks_for_three_questions()
    glm_meta = {
        "blocks": [
            {"index": 0, "bbox_2d": [10, 10, 100, 50], "confidence": 0.92, "flagged": False, "content": "Q2 area 1"},
            {"index": 1, "bbox_2d": [10, 60, 100, 100], "confidence": 0.80, "flagged": True, "content": "Q2 area 2"},
            {"index": 2, "bbox_2d": [10, 110, 100, 150], "confidence": 0.78, "flagged": True, "content": "Q2 area 3"},
        ],
        "block_count": 3,
        "flagged_count": 2,
        "engine": "glm",
    }

    with patch.object(ocr_service, "_gemini_ocr", return_value=gemini_result) as gem_mock, patch.object(
        ocr_service, "_glm_ocr", return_value=glm_meta
    ) as glm_mock:
        result, engine = ocr_service.run_ocr(sample_subj_image_bytes, QuestionType.objective)

    assert engine == "gemini+glm_meta"
    # Downstream text source remains Gemini
    assert result["block_count"] == 5
    assert result["engine"] == "gemini"
    # Objective metadata retained separately for bbox/confidence UI
    assert result["objective_region_count"] == 3
    assert result["objective_flagged_count"] == 2
    assert len(result["objective_regions"]) == 3
    # For objective triage, flagged_count mirrors GLM flagged regions
    assert result["flagged_count"] == 2
    gem_mock.assert_called_once()
    glm_mock.assert_called_once()

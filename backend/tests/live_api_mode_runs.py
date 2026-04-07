import json
import os
import shutil
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient


def _load_root_env() -> dict[str, str]:
    env: dict[str, str] = {}
    for raw in Path("../.env").read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def _set_common_runtime_env(base_env: dict[str, str], mode: str) -> None:
    os.environ["GOOGLE_CLOUD_API_KEY"] = base_env.get("GOOGLE_CLOUD_API_KEY", "")
    os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "true"
    os.environ["GOOGLE_CLOUD_PROJECT"] = base_env.get("GOOGLE_CLOUD_PROJECT", "56451059812")
    os.environ["GOOGLE_CLOUD_LOCATION"] = base_env.get("GOOGLE_CLOUD_LOCATION", "us-central1")
    os.environ["DEFAULT_MODEL"] = base_env.get("DEFAULT_MODEL", "gemini-3.1-flash-lite-preview")
    os.environ["DATABASE_URL"] = f"sqlite:///d:/dev/DEP/backend/tests/live_api_{mode}.db"
    os.environ["UPLOADS_DIR"] = f"d:/dev/DEP/backend/tests/uploads_live_{mode}"
    os.environ["DEBUG"] = "true"


def _reset_mode_artifacts(mode: str) -> None:
    db_path = Path(f"tests/live_api_{mode}.db")
    if db_path.exists():
        db_path.unlink()

    uploads = Path(f"tests/uploads_live_{mode}")
    if uploads.exists():
        shutil.rmtree(uploads)


def _create_manual_rubric_content(mode: str) -> dict:
    if mode == "objective":
        return {
            "questions": [
                {
                    "id": "Q1",
                    "description": "Interpretive response",
                    "max_marks": 4.0,
                    "criteria": [
                        {"step": "Key interpretation identified", "marks": 4.0, "partial_credit": True}
                    ],
                },
                {
                    "id": "Q2",
                    "description": "Numeric parts a, b, c",
                    "max_marks": 3.0,
                    "criteria": [
                        {"step": "Q2.a", "marks": 1.0, "partial_credit": False},
                        {"step": "Q2.b", "marks": 1.0, "partial_credit": False},
                        {"step": "Q2.c", "marks": 1.0, "partial_credit": False},
                    ],
                },
                {
                    "id": "Q3",
                    "description": "Inference response",
                    "max_marks": 3.0,
                    "criteria": [
                        {"step": "Main inference", "marks": 3.0, "partial_credit": True}
                    ],
                },
            ]
        }

    # coding mode
    return {
        "questions": [
            {
                "id": "Q1",
                "description": "Coding-style reasoning and correctness",
                "max_marks": 10.0,
                "criteria": [
                    {"step": "Approach correctness", "marks": 4.0, "partial_credit": True},
                    {"step": "Edge case handling", "marks": 3.0, "partial_credit": True},
                    {"step": "Explanation clarity", "marks": 3.0, "partial_credit": True},
                ],
            }
        ],
        "scoring_policy": {
            "coding": {
                "rubric_weight": 0.4,
                "testcase_weight": 0.6,
            }
        },
    }


def _run_mode(mode: str) -> dict:
    if mode not in {"objective", "coding"}:
        raise ValueError("mode must be objective or coding")

    base_env = _load_root_env()
    _set_common_runtime_env(base_env, mode)
    _reset_mode_artifacts(mode)

    from app.main import app
    from app.workers.grading_tasks import run_grading_task
    from app.workers.ocr_tasks import run_ocr_task

    if mode == "objective":
        assignment_payload = {
            "course_id": "ENG101",
            "title": "Live Objective Mode",
            "description": "Objective-mode live run",
            "max_marks": 10,
            "question_type": "objective",
            "has_code_question": False,
        }
    else:
        assignment_payload = {
            "course_id": "CSE101",
            "title": "Live Coding Mode",
            "description": "Coding-mode live run",
            "max_marks": 10,
            "question_type": "subjective",
            "has_code_question": True,
        }

    result: dict = {"mode": mode}

    with TestClient(app) as client:
        with patch("app.api.v1.submissions.run_ocr_task.delay", side_effect=lambda sid: run_ocr_task(sid)), patch(
            "app.workers.grading_tasks.run_grading_task.delay", side_effect=lambda sid: run_grading_task(sid)
        ):
            a_resp = client.post("/api/v1/assignments/", json=assignment_payload)
            a_resp.raise_for_status()
            assignment = a_resp.json()
            assignment_id = assignment["id"]

            rubric_resp = client.post(
                f"/api/v1/rubrics/{assignment_id}",
                json={
                    "content_json": _create_manual_rubric_content(mode),
                    "source": "manual",
                },
            )
            rubric_resp.raise_for_status()
            rubric = rubric_resp.json()

            img_bytes = Path("../tests/test_subj.jpeg").read_bytes()
            upload_resp = client.post(
                f"/api/v1/submissions/{assignment_id}/upload",
                params={"student_id": f"stu-{mode}", "student_name": f"Student {mode}"},
                files={"file": ("test_subj.jpeg", img_bytes, "image/jpeg")},
            )
            upload_resp.raise_for_status()
            upload = upload_resp.json()
            submission_id = upload["submission_id"]

            sub_resp = client.get(f"/api/v1/submissions/detail/{submission_id}")
            sub_resp.raise_for_status()
            submission = sub_resp.json()

            grade_resp = client.get(f"/api/v1/submissions/{submission_id}/grade")
            grade = grade_resp.json() if grade_resp.status_code == 200 else None

            audit_resp = client.get(f"/api/v1/submissions/{submission_id}/audit")
            audit_resp.raise_for_status()
            audit = audit_resp.json()

            result.update(
                {
                    "assignment": assignment,
                    "rubric": rubric,
                    "upload": upload,
                    "submission": submission,
                    "grade": grade,
                    "grade_status_code": grade_resp.status_code,
                    "audit_actions": [a.get("action") for a in audit],
                }
            )

    out_path = Path(f"../tests/live_api_{mode}_output.json")
    out_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    result["out_file"] = str(out_path)
    return result


def main() -> None:
    for mode in ["objective", "coding"]:
        result = _run_mode(mode)
        submission = result.get("submission") or {}
        grade = result.get("grade") or {}
        ocr_result = submission.get("ocr_result") or {}
        breakdown_json = grade.get("breakdown_json") or {}
        print("MODE=" + mode)
        print("ASSIGNMENT_ID=" + str((result.get("assignment") or {}).get("id")))
        print("SUBMISSION_ID=" + str((result.get("upload") or {}).get("submission_id")))
        print("SUBMISSION_STATUS=" + str(submission.get("status")))
        print("OCR_ENGINE=" + str(ocr_result.get("engine")))
        print("OCR_BLOCK_COUNT=" + str(ocr_result.get("block_count")))
        print("GRADE_HTTP_STATUS=" + str(result.get("grade_status_code")))
        print("TOTAL_SCORE=" + str(grade.get("total_score")))
        print("SCORING_MODE=" + str(breakdown_json.get("scoring_mode")))
        print("CONSISTENCY_ISSUES=" + str(breakdown_json.get("consistency_issues", [])))
        print("OUT_FILE=" + str(result.get("out_file")))
        print("---")


if __name__ == "__main__":
    main()

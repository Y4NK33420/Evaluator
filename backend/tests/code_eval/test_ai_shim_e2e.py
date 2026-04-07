"""End-to-end tests for AI shim retry path through API + worker lifecycle."""

from unittest.mock import patch

from app.workers.code_eval_tasks import run_code_eval_job_task


def _create_assignment(client):
    resp = client.post(
        "/api/v1/assignments/",
        json={
            "course_id": "CSE-AI-SHIM",
            "title": "AI Shim E2E",
            "description": "code-eval ai shim lifecycle",
            "max_marks": 100,
            "question_type": "subjective",
            "has_code_question": True,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _create_ready_env(client, assignment_id: str, course_id: str):
    resp = client.post(
        "/api/v1/code-eval/environments/versions",
        json={
            "course_id": course_id,
            "assignment_id": assignment_id,
            "profile_key": "python-basic",
            "reuse_mode": "course_reuse_with_assignment_overrides",
            "spec_json": {"mode": "manifest", "runtime": "python-3.11"},
            "freeze_key": "codeeval/ai-shim-e2e/v1",
            "status": "ready",
            "version_number": 1,
            "is_active": True,
            "created_by": "test",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _create_submission(client, assignment_id: str):
    with patch("app.api.v1.submissions.run_ocr_task.delay", return_value=None):
        resp = client.post(
            f"/api/v1/submissions/{assignment_id}/upload",
            params={"student_id": "stu-ai-shim", "student_name": "AI Shim"},
            files={"file": ("submission.txt", b"print('x')\n", "text/plain")},
        )
    assert resp.status_code == 202, resp.text
    return resp.json()["submission_id"]


def _create_job_payload(assignment_id: str, submission_id: str, source: str, expected_stdout: str):
    return {
        "environment_version_id": None,
        "explicit_regrade": True,
        "request": {
            "assignment_id": assignment_id,
            "submission_id": submission_id,
            "language": "python",
            "entrypoint": "main.py",
            "source_files": {"main.py": source},
            "testcases": [
                {
                    "testcase_id": "tc1",
                    "weight": 1.0,
                    "input_mode": "stdin",
                    "stdin": "1",
                    "expected_stdout": expected_stdout,
                    "expected_stderr": "",
                    "expected_exit_code": 0,
                }
            ],
            "environment": {
                "mode": "manifest",
                "reuse_mode": "course_reuse_with_assignment_overrides",
                "runtime": "python-3.11",
                "clean_strategy": "ephemeral_clone",
            },
            "quality_evaluation": {
                "mandatory_per_assignment": True,
                "mode": "disabled",
                "rubric_source_mode": "instructor_provided",
                "weight_percent": 0.0,
                "dimensions": ["readability"],
            },
            "regrade_policy": "force_reprocess_all",
            "quota": {
                "timeout_seconds": 3.0,
                "memory_mb": 256,
                "max_output_kb": 256,
                "network_enabled": False,
            },
        },
    }


def test_ai_shim_e2e_heals_interface_mismatch(client, monkeypatch):
    assignment = _create_assignment(client)
    env = _create_ready_env(client, assignment["id"], assignment["course_id"])
    submission_id = _create_submission(client, assignment["id"])

    payload = _create_job_payload(
        assignment["id"],
        submission_id,
        source="print(input())\n",
        expected_stdout="2",
    )
    payload["environment_version_id"] = env["id"]

    monkeypatch.setattr("app.services.code_eval.shim_service.settings.code_eval_enable_ai_shim_generation", True)
    monkeypatch.setattr("app.workers.code_eval_tasks.settings.code_eval_enable_shim_retry", True)
    monkeypatch.setattr("app.services.code_eval.execution_service.settings.code_eval_execution_backend", "local")
    monkeypatch.setattr("app.services.code_eval.execution_service.settings.code_eval_enable_local_execution", True)

    def fake_model_call(**_kwargs):
        return {
            "fixable": True,
            "reason": "stdin/output adapter required",
            "comparison_mode": "strict",
            "updated_entrypoint": "shim_main.py",
            "updated_files": {
                "shim_main.py": "print('2')\n",
            },
            "confidence": 0.98,
        }

    monkeypatch.setattr("app.services.code_eval.shim_service.generate_structured_json_with_retry", fake_model_call)

    with patch(
        "app.workers.code_eval_tasks.run_code_eval_job_task.delay",
        side_effect=lambda job_id: run_code_eval_job_task.run(job_id),
    ):
        job_resp = client.post("/api/v1/code-eval/jobs", json=payload)

    assert job_resp.status_code == 201, job_resp.text
    job_id = job_resp.json()["id"]

    detail = client.get(f"/api/v1/code-eval/jobs/{job_id}")
    assert detail.status_code == 200, detail.text
    job = detail.json()

    assert job["status"] == "COMPLETED"
    assert job["attempt_count"] == 2

    final_result = job["final_result_json"]
    assert final_result["status"] == "COMPLETED"
    assert final_result["attempts"][0]["passed"] is False
    assert final_result["attempts"][1]["passed"] is True
    assert final_result["shim_decision"]["shim_strategy"] == "ai_generated_patch"
    assert final_result["shim_decision"]["model"]
    assert final_result["shim_decision"]["prompt_hash"]

    artifacts = final_result["attempt_artifacts"]
    assert len(artifacts) == 2
    assert artifacts[1]["shim_strategy"] == "ai_generated_patch"
    assert artifacts[1]["shim_model"]
    assert artifacts[1]["shim_prompt_hash"]


def test_ai_shim_e2e_logic_bug_not_healed(client, monkeypatch):
    assignment = _create_assignment(client)
    env = _create_ready_env(client, assignment["id"], assignment["course_id"])
    submission_id = _create_submission(client, assignment["id"])

    payload = _create_job_payload(
        assignment["id"],
        submission_id,
        source="print(input())\n",
        expected_stdout="999",
    )
    payload["environment_version_id"] = env["id"]

    monkeypatch.setattr("app.services.code_eval.shim_service.settings.code_eval_enable_ai_shim_generation", True)
    monkeypatch.setattr("app.workers.code_eval_tasks.settings.code_eval_enable_shim_retry", True)
    monkeypatch.setattr("app.services.code_eval.execution_service.settings.code_eval_execution_backend", "local")
    monkeypatch.setattr("app.services.code_eval.execution_service.settings.code_eval_enable_local_execution", True)

    def fake_model_call(**_kwargs):
        return {
            "fixable": False,
            "reason": "algorithmic logic mismatch",
            "comparison_mode": "strict",
            "updated_entrypoint": "main.py",
            "updated_files": {},
            "confidence": 0.99,
        }

    monkeypatch.setattr("app.services.code_eval.shim_service.generate_structured_json_with_retry", fake_model_call)

    with patch(
        "app.workers.code_eval_tasks.run_code_eval_job_task.delay",
        side_effect=lambda job_id: run_code_eval_job_task.run(job_id),
    ):
        job_resp = client.post("/api/v1/code-eval/jobs", json=payload)

    assert job_resp.status_code == 201, job_resp.text
    job_id = job_resp.json()["id"]

    detail = client.get(f"/api/v1/code-eval/jobs/{job_id}")
    assert detail.status_code == 200, detail.text
    job = detail.json()

    assert job["status"] == "FAILED"
    assert job["attempt_count"] == 1

    final_result = job["final_result_json"]
    assert final_result["status"] == "FAILED"
    assert final_result["shim_decision"]["eligible"] is False
    assert "ai_shim_not_fixable" in final_result["shim_decision"]["reason"]
    assert final_result["shim_decision"]["ai_decision"]["model"]
    assert final_result["shim_decision"]["ai_decision"]["prompt_hash"]

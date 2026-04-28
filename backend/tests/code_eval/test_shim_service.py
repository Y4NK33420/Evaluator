"""Unit tests for shim retry analysis and retry request building."""

from app.services.code_eval.contracts import CodeEvalJobRequest, InputMode, LanguageRuntime, TestCaseSpec
from app.services.code_eval import shim_service


def _request() -> CodeEvalJobRequest:
    return CodeEvalJobRequest(
        assignment_id="a1",
        submission_id="s1",
        language=LanguageRuntime.PYTHON,
        entrypoint="main.py",
        source_files={"main.py": "print(input())\n"},
        testcases=[
            TestCaseSpec(
                testcase_id="t1",
                input_mode=InputMode.STDIN,
                stdin="1",
                expected_stdout="2",
                expected_stderr="",
                expected_exit_code=0,
            )
        ],
    )


def test_deterministic_whitespace_retry_is_eligible():
    req = _request()
    artifacts = {
        "testcases": [
            {
                "testcase_id": "t1",
                "passed": False,
                "stdout": "2  ",
                "stderr": "",
                "failure_reason": "stdout_mismatch",
            }
        ]
    }

    decision = shim_service.analyze_for_retrying_shim(req, artifacts)

    assert decision["eligible"] is True
    assert decision["shim_strategy"] == "deterministic_whitespace_normalization"
    assert decision["comparison_mode"] == "whitespace_normalized"


def test_ai_generated_patch_path_can_be_selected(monkeypatch):
    req = _request()
    artifacts = {
        "testcases": [
            {
                "testcase_id": "t1",
                "passed": False,
                "stdout": "1",
                "stderr": "",
                "failure_reason": "stdout_mismatch",
            }
        ]
    }

    monkeypatch.setattr(shim_service.settings, "code_eval_enable_ai_shim_generation", True)

    def fake_model_call(**_kwargs):
        return {
            "fixable": True,
            "reason": "stdin/output adapter needed",
            "comparison_mode": "strict",
            "updated_entrypoint": "shim_main.py",
            "updated_files": {
                "shim_main.py": "import sys\nprint('2')\n",
            },
        }

    monkeypatch.setattr(shim_service, "generate_structured_json_with_retry", fake_model_call)

    decision = shim_service.analyze_for_retrying_shim(req, artifacts)

    assert decision["eligible"] is True
    assert decision["shim_strategy"] == "ai_generated_patch"
    assert decision["patched_entrypoint"] == "shim_main.py"
    assert "shim_main.py" in decision["patched_source_files"]
    assert decision.get("model")
    assert decision.get("prompt_hash")
    assert isinstance(decision.get("decision"), dict)
    assert decision["decision"].get("fixable") is True

    retry_req = shim_service.build_retry_request_from_shim_decision(req, decision)
    assert retry_req.entrypoint == "shim_main.py"
    assert "shim_main.py" in retry_req.source_files


def test_logic_bug_is_not_marked_fixable(monkeypatch):
    req = _request()
    artifacts = {
        "testcases": [
            {
                "testcase_id": "t1",
                "passed": False,
                "stdout": "123",
                "stderr": "",
                "failure_reason": "stdout_mismatch",
            }
        ]
    }

    monkeypatch.setattr(shim_service.settings, "code_eval_enable_ai_shim_generation", True)

    def fake_model_call(**_kwargs):
        return {
            "fixable": False,
            "reason": "appears to be algorithmic logic error",
            "comparison_mode": "strict",
            "updated_entrypoint": "main.py",
            "updated_files": {},
        }

    monkeypatch.setattr(shim_service, "generate_structured_json_with_retry", fake_model_call)

    decision = shim_service.analyze_for_retrying_shim(req, artifacts)

    assert decision["eligible"] is False
    assert "ai_shim_not_fixable" in decision["reason"]
    assert isinstance(decision.get("ai_decision"), dict)
    assert decision["ai_decision"].get("model")
    assert decision["ai_decision"].get("prompt_hash")

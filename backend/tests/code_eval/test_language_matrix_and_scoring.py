"""Language matrix behavior and deterministic local scoring tests."""

from pathlib import Path

from app.services.code_eval.contracts import CodeEvalJobRequest, InputMode, LanguageRuntime, TestCaseSpec
from app.services.code_eval import execution_service


def _request(language: LanguageRuntime, entrypoint: str, source: str, expected_stdout: str) -> CodeEvalJobRequest:
    return CodeEvalJobRequest(
        assignment_id="a1",
        submission_id="s1",
        language=language,
        entrypoint=entrypoint,
        source_files={entrypoint: source},
        testcases=[
            TestCaseSpec(
                testcase_id="t1",
                weight=1.0,
                input_mode=InputMode.STDIN,
                stdin="",
                expected_stdout=expected_stdout,
                expected_stderr="",
                expected_exit_code=0,
            )
        ],
    )


def test_python_pass_case_in_matrix(tmp_path):
    req = _request(LanguageRuntime.PYTHON, "main.py", "print('ok')\n", "ok")

    case_dir = tmp_path / "py_pass"
    case_dir.mkdir(parents=True, exist_ok=True)
    result = execution_service._run_single_testcase(req, case_dir, 0, "strict")

    assert result["passed"] is True
    assert result["awarded_score"] == 1.0


def test_c_compile_error_case_in_matrix(monkeypatch, tmp_path):
    req = _request(LanguageRuntime.C, "main.c", "int main(){ return 0; }\n", "")

    monkeypatch.setattr("app.services.code_eval.execution_service.shutil.which", lambda _name: "/usr/bin/fake")

    def fake_run_process(cmd, *, cwd, stdin_value, timeout_seconds):
        if cmd[0] == "gcc":
            return 1, "", "compile failed", False, None
        return 0, "", "", False, None

    monkeypatch.setattr(execution_service, "_run_process", fake_run_process)

    case_dir = tmp_path / "c_compile_error"
    case_dir.mkdir(parents=True, exist_ok=True)
    result = execution_service._run_single_testcase(req, case_dir, 0, "strict")

    assert result["passed"] is False
    assert result["awarded_score"] == 0.0
    assert "compile_error" in (result["failure_reason"] or "")


def test_java_timeout_case_in_matrix(monkeypatch, tmp_path):
    req = _request(LanguageRuntime.JAVA, "Main.java", "class Main { public static void main(String[] a){ for(;;){} } }\n", "")

    monkeypatch.setattr("app.services.code_eval.execution_service.shutil.which", lambda _name: "/usr/bin/fake")

    def fake_run_process(cmd, *, cwd, stdin_value, timeout_seconds):
        if cmd[0] == "javac":
            return 0, "", "", False, None
        return -1, "", "Execution timed out", True, "timeout"

    monkeypatch.setattr(execution_service, "_run_process", fake_run_process)

    case_dir = tmp_path / "java_timeout"
    case_dir.mkdir(parents=True, exist_ok=True)
    result = execution_service._run_single_testcase(req, case_dir, 0, "strict")

    assert result["passed"] is False
    assert "timeout" in (result["failure_reason"] or "")


def test_scoring_is_deterministic_for_same_case_results(monkeypatch):
    monkeypatch.setattr(execution_service.settings, "code_eval_enable_local_execution", True)

    req = CodeEvalJobRequest(
        assignment_id="a1",
        submission_id="s1",
        language=LanguageRuntime.PYTHON,
        entrypoint="main.py",
        source_files={"main.py": "print('x')\n"},
        testcases=[
            TestCaseSpec(
                testcase_id="t1",
                weight=2.0,
                input_mode=InputMode.STDIN,
                stdin="",
                expected_stdout="x",
                expected_stderr="",
                expected_exit_code=0,
            ),
            TestCaseSpec(
                testcase_id="t2",
                weight=1.0,
                input_mode=InputMode.STDIN,
                stdin="",
                expected_stdout="x",
                expected_stderr="",
                expected_exit_code=0,
            ),
        ],
    )

    def fake_single(_request, _case_dir: Path, case_index: int, _mode: str):
        if case_index == 0:
            return {
                "testcase_id": "t1",
                "passed": True,
                "weight": 2.0,
                "awarded_score": 2.0,
                "exit_code": 0,
                "stdout": "x",
                "stderr": "",
                "failure_reason": None,
                "output_truncated": False,
            }
        return {
            "testcase_id": "t2",
            "passed": False,
            "weight": 1.0,
            "awarded_score": 0.0,
            "exit_code": 1,
            "stdout": "bad",
            "stderr": "",
            "failure_reason": "stdout_mismatch",
            "output_truncated": False,
        }

    monkeypatch.setattr(execution_service, "_run_single_testcase", fake_single)

    attempt, artifacts = execution_service._execute_local_backend(
        req,
        stage="EXECUTING_RAW",
        comparison_mode="strict",
        shim_used=False,
        shim_source=None,
    )

    assert attempt.passed is False
    assert attempt.score == 2.0
    assert artifacts["max_score"] == 3.0
    assert artifacts["earned_score"] == 2.0

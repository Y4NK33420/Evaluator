"""Runtime behavior tests that are fully runnable on Windows local backend."""

from concurrent.futures import ThreadPoolExecutor

from app.services.code_eval.contracts import (
    CodeEvalJobRequest,
    ExecutionQuota,
    InputMode,
    LanguageRuntime,
    TestCaseSpec,
)
from app.services.code_eval.execution_service import execute_code_eval_job, settings


def _request(source: str, *, submission_id: str, stdin: str, expected_stdout: str, timeout_seconds: float) -> CodeEvalJobRequest:
    return CodeEvalJobRequest(
        assignment_id="a1",
        submission_id=submission_id,
        language=LanguageRuntime.PYTHON,
        entrypoint="main.py",
        source_files={"main.py": source},
        testcases=[
            TestCaseSpec(
                testcase_id="t1",
                weight=1.0,
                input_mode=InputMode.STDIN,
                stdin=stdin,
                expected_stdout=expected_stdout,
                expected_stderr="",
                expected_exit_code=0,
            )
        ],
        quota=ExecutionQuota(
            timeout_seconds=timeout_seconds,
            memory_mb=256,
            max_output_kb=256,
            network_enabled=False,
        ),
    )


def test_write_leak_absent_in_second_run(monkeypatch):
    monkeypatch.setattr(settings, "code_eval_execution_backend", "local")
    monkeypatch.setattr(settings, "code_eval_enable_local_execution", True)

    run1 = _request(
        "from pathlib import Path\nPath('leak_marker.txt').write_text('x', encoding='utf-8')\nprint('run1')\n",
        submission_id="s-run1",
        stdin="",
        expected_stdout="run1",
        timeout_seconds=2.0,
    )
    run2 = _request(
        "from pathlib import Path\nprint('present' if Path('leak_marker.txt').exists() else 'absent')\n",
        submission_id="s-run2",
        stdin="",
        expected_stdout="absent",
        timeout_seconds=2.0,
    )

    first_attempt, first_artifacts = execute_code_eval_job(run1, stage="EXECUTING_RAW")
    second_attempt, second_artifacts = execute_code_eval_job(run2, stage="EXECUTING_RAW")

    assert first_attempt.passed is True
    assert second_attempt.passed is True
    assert first_artifacts["testcases"][0]["stdout"].strip() == "run1"
    assert second_artifacts["testcases"][0]["stdout"].strip() == "absent"


def test_infinite_loop_times_out_and_is_killed(monkeypatch):
    monkeypatch.setattr(settings, "code_eval_execution_backend", "local")
    monkeypatch.setattr(settings, "code_eval_enable_local_execution", True)

    req = _request(
        "while True:\n    pass\n",
        submission_id="s-timeout",
        stdin="",
        expected_stdout="",
        timeout_seconds=0.2,
    )

    attempt, artifacts = execute_code_eval_job(req, stage="EXECUTING_RAW")

    assert attempt.passed is False
    assert artifacts["testcases"][0]["failure_reason"]
    assert "timeout" in artifacts["testcases"][0]["failure_reason"]


def test_parallel_ten_job_stress(monkeypatch):
    monkeypatch.setattr(settings, "code_eval_execution_backend", "local")
    monkeypatch.setattr(settings, "code_eval_enable_local_execution", True)

    source = "import sys\nnums=[int(x) for x in sys.stdin.read().split()]\nprint(sum(nums))\n"

    def _run(idx: int):
        req = _request(
            source,
            submission_id=f"s-{idx}",
            stdin="1 2 3",
            expected_stdout="6",
            timeout_seconds=2.0,
        )
        return execute_code_eval_job(req, stage="EXECUTING_RAW")

    with ThreadPoolExecutor(max_workers=10) as pool:
        results = list(pool.map(_run, range(10)))

    assert len(results) == 10
    for attempt, artifacts in results:
        assert attempt.passed is True
        assert attempt.score == 1.0
        assert artifacts["executor"] == "local_subprocess"
        assert artifacts["testcases"][0]["passed"] is True

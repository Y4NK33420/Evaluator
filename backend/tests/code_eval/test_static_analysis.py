"""Unit tests for code-eval static analysis guard."""

from app.services.code_eval.contracts import CodeEvalJobRequest, InputMode, LanguageRuntime, TestCaseSpec
from app.services.code_eval.static_analysis import run_static_analysis_gate


def _request(language: LanguageRuntime, source: str, entrypoint: str) -> CodeEvalJobRequest:
    return CodeEvalJobRequest(
        assignment_id="a1",
        submission_id="s1",
        language=language,
        entrypoint=entrypoint,
        source_files={entrypoint: source},
        testcases=[
            TestCaseSpec(
                testcase_id="t1",
                input_mode=InputMode.STDIN,
                stdin="",
                expected_stdout="",
                expected_stderr="",
                expected_exit_code=0,
            )
        ],
    )


def test_python_forbidden_call_blocks_submission():
    req = _request(
        LanguageRuntime.PYTHON,
        "import os\nos.system('echo hi')\nprint(1)\n",
        "main.py",
    )

    result = run_static_analysis_gate(req)

    assert result["blocked"] is True
    rules = {item["rule"] for item in result["violations"]}
    assert "python_forbidden_call" in rules


def test_cpp_forbidden_pattern_blocks_submission():
    req = _request(
        LanguageRuntime.CPP,
        "#include <cstdlib>\nint main(){ system(\"id\"); return 0; }\n",
        "main.cpp",
    )

    result = run_static_analysis_gate(req)

    assert result["blocked"] is True
    rules = {item["rule"] for item in result["violations"]}
    assert "system_call_forbidden" in rules


def test_clean_python_passes_static_analysis():
    req = _request(
        LanguageRuntime.PYTHON,
        "import sys\nprint(sum(int(x) for x in sys.stdin.read().split()))\n",
        "main.py",
    )

    result = run_static_analysis_gate(req)

    assert result["blocked"] is False
    assert result["violations"] == []

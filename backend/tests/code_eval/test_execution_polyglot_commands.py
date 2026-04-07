"""Unit tests for language command resolution in local execution backend."""

from pathlib import Path

from app.services.code_eval.contracts import CodeEvalJobRequest, InputMode, LanguageRuntime, TestCaseSpec
from app.services.code_eval.execution_service import _build_local_commands


def _request(language: LanguageRuntime, entrypoint: str) -> CodeEvalJobRequest:
    return CodeEvalJobRequest(
        assignment_id="a1",
        submission_id="s1",
        language=language,
        entrypoint=entrypoint,
        source_files={entrypoint: ""},
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


def test_build_local_commands_python():
    req = _request(LanguageRuntime.PYTHON, "main.py")
    compile_cmd, run_cmd = _build_local_commands(req, ["arg1"], Path("/tmp/case"))

    assert compile_cmd is None
    assert run_cmd[1] == "main.py"
    assert run_cmd[-1] == "arg1"


def test_build_local_commands_c_and_cpp(monkeypatch):
    monkeypatch.setattr("app.services.code_eval.execution_service.shutil.which", lambda name: f"/usr/bin/{name}")

    c_req = _request(LanguageRuntime.C, "main.c")
    c_compile, c_run = _build_local_commands(c_req, [], Path("/tmp/case"))
    assert c_compile[0] == "gcc"
    assert c_run[0].endswith(".codeeval_exec")

    cpp_req = _request(LanguageRuntime.CPP, "main.cpp")
    cpp_compile, cpp_run = _build_local_commands(cpp_req, ["x"], Path("/tmp/case"))
    assert cpp_compile[0] == "g++"
    assert cpp_run[-1] == "x"


def test_build_local_commands_java(monkeypatch):
    monkeypatch.setattr("app.services.code_eval.execution_service.shutil.which", lambda name: f"/usr/bin/{name}")

    req = _request(LanguageRuntime.JAVA, "Main.java")
    compile_cmd, run_cmd = _build_local_commands(req, ["v"], Path("/tmp/case"))

    assert compile_cmd == ["javac", "Main.java"]
    assert run_cmd[:4] == ["java", "-cp", ".", "Main"]
    assert run_cmd[-1] == "v"

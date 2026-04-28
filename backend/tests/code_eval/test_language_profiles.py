"""Unit tests for language profile presets and docker image selection."""

from app.services.code_eval.contracts import CodeEvalJobRequest, InputMode, LanguageRuntime, TestCaseSpec
from app.services.code_eval.execution_service import _resolve_docker_image, settings
from app.services.code_eval.language_profiles import get_language_profile


def _request(language: LanguageRuntime) -> CodeEvalJobRequest:
    entrypoint = {
        LanguageRuntime.PYTHON: "main.py",
        LanguageRuntime.C: "main.c",
        LanguageRuntime.CPP: "main.cpp",
        LanguageRuntime.JAVA: "Main.java",
    }[language]
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


def test_language_profiles_exist_for_all_supported_languages():
    assert get_language_profile("python")["docker_image"] == "python:3.11-slim"
    assert get_language_profile("c")["docker_image"] == "gcc:13"
    assert get_language_profile("cpp")["docker_image"] == "gcc:13"
    assert get_language_profile("java")["docker_image"] == "eclipse-temurin:21"


def test_resolve_docker_image_uses_language_default_for_compiled_languages(monkeypatch):
    req = _request(LanguageRuntime.CPP)

    monkeypatch.setattr(settings, "code_eval_docker_default_image", "python:3.11-slim")
    image = _resolve_docker_image(req)

    assert image == "gcc:13"


def test_resolve_docker_image_respects_explicit_env_image(monkeypatch):
    req = _request(LanguageRuntime.JAVA)
    req.environment.image_reference = "custom/java-image:latest"

    monkeypatch.setattr(settings, "code_eval_docker_default_image", "python:3.11-slim")
    image = _resolve_docker_image(req)

    assert image == "custom/java-image:latest"

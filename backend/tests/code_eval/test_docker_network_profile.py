"""Unit tests for docker execution network isolation profile."""

from app.services.code_eval.contracts import (
    CodeEvalJobRequest,
    ExecutionQuota,
    InputMode,
    LanguageRuntime,
    TestCaseSpec,
)
from app.services.code_eval.execution_service import _run_single_testcase_docker, settings


class _FakeContainer:
    def put_archive(self, _path, _archive):
        return None

    def start(self):
        return None

    def wait(self, timeout=None):
        return {"StatusCode": 0}

    def logs(self, stdout=True, stderr=False):
        if stdout:
            return b"ok\n"
        if stderr:
            return b""
        return b""

    def remove(self, force=False):
        return None


class _FakeContainers:
    def __init__(self):
        self.last_kwargs = None

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        return _FakeContainer()


class _FakeClient:
    def __init__(self):
        self.containers = _FakeContainers()


def _request(network_enabled: bool) -> CodeEvalJobRequest:
    return CodeEvalJobRequest(
        assignment_id="a1",
        submission_id="s1",
        language=LanguageRuntime.PYTHON,
        entrypoint="main.py",
        source_files={"main.py": "print('ok')\n"},
        testcases=[
            TestCaseSpec(
                testcase_id="t1",
                input_mode=InputMode.STDIN,
                stdin="",
                expected_stdout="ok",
                expected_stderr="",
                expected_exit_code=0,
            )
        ],
        quota=ExecutionQuota(
            timeout_seconds=2.0,
            memory_mb=128,
            max_output_kb=128,
            network_enabled=network_enabled,
        ),
    )


def test_docker_network_is_disabled_when_force_flag_is_true(monkeypatch):
    client = _FakeClient()
    req = _request(network_enabled=True)

    monkeypatch.setattr(settings, "code_eval_docker_force_no_network", True)

    result = _run_single_testcase_docker(req, 0, "python:3.11-slim", client, "strict")

    assert result["passed"] is True
    assert client.containers.last_kwargs is not None
    assert client.containers.last_kwargs["network_disabled"] is True


def test_docker_network_respects_request_when_force_flag_is_false(monkeypatch):
    client = _FakeClient()
    req = _request(network_enabled=True)

    monkeypatch.setattr(settings, "code_eval_docker_force_no_network", False)

    result = _run_single_testcase_docker(req, 0, "python:3.11-slim", client, "strict")

    assert result["passed"] is True
    assert client.containers.last_kwargs is not None
    assert client.containers.last_kwargs["network_disabled"] is False

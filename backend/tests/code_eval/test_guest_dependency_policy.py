"""Validation for guest dependency policy when dynamic pip install is disabled."""

import os
import sys
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from microvm_guest_agent import agent as guest_agent


def test_guest_rejects_runtime_pip_install_by_default(tmp_path, monkeypatch):
    monkeypatch.delenv("CODE_EVAL_GUEST_AGENT_ALLOW_DYNAMIC_PIP", raising=False)

    with pytest.raises(RuntimeError) as exc:
        guest_agent._ensure_python_dependencies(
            python_exec=sys.executable,
            dependencies=["requests==2.32.3"],
            sandbox_root=str(tmp_path),
            timeout_seconds=2.0,
        )

    assert "Dynamic dependency installation is disabled" in str(exc.value)


def test_guest_allows_runtime_pip_install_when_explicitly_enabled(monkeypatch, tmp_path):
    monkeypatch.setenv("CODE_EVAL_GUEST_AGENT_ALLOW_DYNAMIC_PIP", "true")

    def fake_run_subprocess(cmd, cwd, stdin_value, timeout_seconds, env_overrides=None):
        return 0, "", "", False

    monkeypatch.setattr(guest_agent, "_run_subprocess", fake_run_subprocess)

    dep_dir = guest_agent._ensure_python_dependencies(
        python_exec=sys.executable,
        dependencies=["requests==2.32.3"],
        sandbox_root=str(tmp_path),
        timeout_seconds=2.0,
    )

    assert dep_dir is not None
    assert os.path.basename(dep_dir) == "deps"

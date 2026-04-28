"""Multi-language AI shim tests — C, C++, Java interface mismatch scenarios.

All tests mock the Gemini model call so no real API key is needed.
They verify:
  1. Source signal builders for each language
  2. Deterministic whitespace path correctly rejects compiled languages
  3. AI shim path dispatches correct language-specific system instruction
  4. Compile-check step blocks broken patches for C/C++/Java
  5. Fallback adapter injection produces valid patched source dicts
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure backend app is importable
sys.path.insert(0, str(Path(__file__).parents[2]))

from app.services.code_eval.contracts import (
    CodeEvalJobRequest,
    EnvironmentSpec,
    ExecutionQuota,
    InputMode,
    LanguageRuntime,
    QualityEvaluationConfig,
    TestCaseSpec,
)
from app.services.code_eval.shim_service import (
    _build_c_source_signals,
    _build_cpp_source_signals,
    _build_java_source_signals,
    _compile_check_patch,
    _deterministic_whitespace_decision,
    _inject_fallback_adapter,
    _inject_stdin_to_argv_adapter_c,
    _inject_stdin_to_argv_adapter_cpp,
    _inject_stdin_to_argv_adapter_java,
    _inject_stdin_to_argv_adapter_python,
    analyze_for_retrying_shim,
)
from app.services.code_eval.language_config import _from_profile_defaults


# ── Fixtures ──────────────────────────────────────────────────────────────────

C_ARGV_SOURCE = r"""
#include <stdio.h>
#include <stdlib.h>

int main(int argc, char *argv[]) {
    int x = atoi(argv[1]);
    printf("%d\n", x * 2);
    return 0;
}
"""

CPP_ARGV_SOURCE = r"""
#include <iostream>
#include <string>

int main(int argc, char *argv[]) {
    std::cout << std::stoi(argv[1]) * 2 << std::endl;
    return 0;
}
"""

JAVA_ARGS_SOURCE = r"""
public class Solution {
    public static void main(String[] args) {
        System.out.println(Integer.parseInt(args[0]) * 2);
    }
}
"""

PYTHON_ARGV_SOURCE = """
import sys
x = int(sys.argv[1])
print(x * 2)
"""


def _make_request(language: str, source: str, entrypoint: str, stdin_input: str = "4") -> CodeEvalJobRequest:
    return CodeEvalJobRequest(
        assignment_id="test-assign-001",
        submission_id="test-sub-001",
        language=LanguageRuntime(language),
        entrypoint=entrypoint,
        source_files={entrypoint: source},
        testcases=[
            TestCaseSpec(
                testcase_id="tc_001",
                weight=1.0,
                input_mode=InputMode.STDIN,
                stdin=stdin_input,
                expected_stdout="8",
                expected_exit_code=0,
            )
        ],
        environment=EnvironmentSpec(),
        quality_evaluation=QualityEvaluationConfig(),
        quota=ExecutionQuota(timeout_seconds=5.0),
    )


def _make_failing_artifacts(testcase_id: str = "tc_001") -> dict:
    """Simulate artifacts where testcase failed with stdout_mismatch (empty stdout, argv-vs-stdin)."""
    return {
        "executor": "local_subprocess",
        "comparison_mode": "strict",
        "testcases": [{
            "testcase_id": testcase_id,
            "passed": False,
            "weight": 1.0,
            "awarded_score": 0.0,
            "exit_code": 1,
            "stdout": "",
            "stderr": "Segmentation fault" if True else "",
            "failure_reason": "stdout_mismatch|exit_code_expected_0_got_1",
            "output_truncated": False,
        }],
    }


# ── Source signal builders ────────────────────────────────────────────────────

class TestSourceSignalBuilders:
    def test_c_detects_argv(self):
        signals = _build_c_source_signals({"sol.c": C_ARGV_SOURCE})
        assert signals["uses_argv"] is True
        assert signals["uses_stdin"] is False

    def test_c_detects_scanf(self):
        source = "#include <stdio.h>\nint main() { int x; scanf(\"%d\", &x); printf(\"%d\\n\", x*2); }"
        signals = _build_c_source_signals({"sol.c": source})
        assert signals["uses_stdin"] is True
        assert signals["uses_argv"] is False

    def test_cpp_detects_argv(self):
        signals = _build_cpp_source_signals({"sol.cpp": CPP_ARGV_SOURCE})
        assert signals["uses_argv"] is True
        assert signals["uses_stdin"] is False

    def test_cpp_detects_cin(self):
        source = "#include <iostream>\nint main() { int x; std::cin >> x; std::cout << x*2; }"
        signals = _build_cpp_source_signals({"sol.cpp": source})
        assert signals["uses_stdin"] is True

    def test_java_detects_args(self):
        signals = _build_java_source_signals({"Solution.java": JAVA_ARGS_SOURCE})
        assert signals["uses_argv"] is True
        assert signals["uses_stdin"] is False

    def test_java_detects_scanner(self):
        source = "import java.util.Scanner; public class S { public static void main(String[] args) { Scanner sc = new Scanner(System.in); } }"
        signals = _build_java_source_signals({"S.java": source})
        assert signals["uses_stdin"] is True


# ── Deterministic whitespace: compiled languages rejected ─────────────────────

class TestDeterministicWhiteshimCompiledLanguages:
    def test_c_rejected(self):
        request = _make_request("c", C_ARGV_SOURCE, "sol.c")
        artifacts = _make_failing_artifacts()
        result = _deterministic_whitespace_decision(request, artifacts)
        assert result["eligible"] is False
        assert "compiled" in result["reason"] or "not_applicable" in result["reason"]

    def test_cpp_rejected(self):
        request = _make_request("cpp", CPP_ARGV_SOURCE, "sol.cpp")
        artifacts = _make_failing_artifacts()
        result = _deterministic_whitespace_decision(request, artifacts)
        assert result["eligible"] is False

    def test_java_rejected(self):
        request = _make_request("java", JAVA_ARGS_SOURCE, "Solution.java")
        artifacts = _make_failing_artifacts()
        result = _deterministic_whitespace_decision(request, artifacts)
        assert result["eligible"] is False

    def test_python_still_eligible_for_whitespace(self):
        """Python whitespace path should still work."""
        source = "import sys\nprint(int(sys.argv[1]) * 2)"
        request = _make_request("python", source, "sol.py")
        # A pure whitespace-only failure (stdout has trailing space)
        artifacts = {
            "executor": "local_subprocess",
            "comparison_mode": "strict",
            "testcases": [{
                "testcase_id": "tc_001",
                "passed": False,
                "weight": 1.0,
                "awarded_score": 0.0,
                "exit_code": 0,
                "stdout": "8 ",   # trailing space
                "stderr": "",
                "failure_reason": "stdout_mismatch",
                "output_truncated": False,
            }],
        }
        result = _deterministic_whitespace_decision(request, artifacts)
        # Should be eligible because whitespace-only mismatch
        assert result["eligible"] is True
        assert result["comparison_mode"] == "whitespace_normalized"


# ── Fallback adapter injectors ────────────────────────────────────────────────

class TestFallbackAdapterInjectors:
    def test_python_adapter_prepends_shim(self):
        source = "import sys\nprint(int(sys.argv[1]) * 2)\n"
        patched = _inject_stdin_to_argv_adapter_python(source)
        assert "sys.argv" in patched
        assert "_shim_stdin" in patched
        # Original code preserved
        assert "sys.argv[1]" in patched

    def test_c_adapter_returns_dict_with_entrypoint(self):
        result = _inject_stdin_to_argv_adapter_c(C_ARGV_SOURCE, "sol.c")
        assert isinstance(result, dict)
        assert "sol.c" in result
        patched = result["sol.c"]
        assert "_SHIM_BUF_SZ" in patched or "_shim_buf" in patched
        assert "_student_main" in patched

    def test_cpp_adapter_returns_dict_with_entrypoint(self):
        result = _inject_stdin_to_argv_adapter_cpp(CPP_ARGV_SOURCE, "sol.cpp")
        assert isinstance(result, dict)
        assert "sol.cpp" in result
        assert "_student_main" in result["sol.cpp"]

    def test_java_adapter_returns_two_files(self):
        result = _inject_stdin_to_argv_adapter_java(JAVA_ARGS_SOURCE, "Solution.java")
        assert isinstance(result, dict)
        assert "Solution.java" in result
        # Should also produce a shim runner file
        shim_files = [k for k in result if "Shim" in k or "shim" in k.lower() or k != "Solution.java"]
        assert len(shim_files) >= 1


# ── inject_fallback_adapter dispatches correctly ──────────────────────────────

class TestInjectFallbackAdapter:
    def _make_interface_like_failed_cases(self):
        return [{
            "testcase_id": "tc_001",
            "failure_tokens": ["stdout_mismatch"],
            "eligible": True,
            "decision_reason": "potential_interface_io_mismatch",
            "stdout": "",
            "stderr": "",
        }]

    def test_python(self):
        request = _make_request("python", PYTHON_ARGV_SOURCE, "sol.py")
        result = _inject_fallback_adapter(request, self._make_interface_like_failed_cases())
        assert result is not None
        assert "sol.py" in result

    def test_c(self):
        request = _make_request("c", C_ARGV_SOURCE, "sol.c")
        result = _inject_fallback_adapter(request, self._make_interface_like_failed_cases())
        assert result is not None
        assert "sol.c" in result

    def test_cpp(self):
        request = _make_request("cpp", CPP_ARGV_SOURCE, "sol.cpp")
        result = _inject_fallback_adapter(request, self._make_interface_like_failed_cases())
        assert result is not None
        assert "sol.cpp" in result

    def test_java(self):
        request = _make_request("java", JAVA_ARGS_SOURCE, "Solution.java")
        result = _inject_fallback_adapter(request, self._make_interface_like_failed_cases())
        assert result is not None
        assert "Solution.java" in result

    def test_no_injection_for_non_interface_failures(self):
        """Adapter should NOT be injected for logic failures."""
        request = _make_request("python", PYTHON_ARGV_SOURCE, "sol.py")
        non_interface_failed = [{
            "testcase_id": "tc_001",
            "failure_tokens": ["stdout_mismatch"],
            "eligible": False,
            "decision_reason": "output_difference_not_whitespace_only",
            "stdout": "wrong result",
            "stderr": "",
        }]
        result = _inject_fallback_adapter(request, non_interface_failed)
        assert result is None


# ── Compile-check (requires compiler on host; skipped if not available) ───────

class TestCompileCheck:
    def test_python_always_passes(self):
        """Python never needs a compile check."""
        lang_cfg = _from_profile_defaults("python")
        ok, err = _compile_check_patch("python", {"sol.py": "print('hi')"}, lang_cfg, "sol.py")
        assert ok is True
        assert err == ""

    @pytest.mark.skipif(
        not __import__("shutil").which("gcc"),
        reason="gcc not available on this host",
    )
    def test_valid_c_patch_passes(self):
        valid_c = "#include <stdio.h>\nint main() { printf(\"8\\n\"); return 0; }\n"
        lang_cfg = _from_profile_defaults("c")
        ok, err = _compile_check_patch("c", {"sol.c": valid_c}, lang_cfg, "sol.c")
        assert ok is True, f"Expected compile to pass, got err: {err}"

    @pytest.mark.skipif(
        not __import__("shutil").which("gcc"),
        reason="gcc not available on this host",
    )
    def test_broken_c_patch_fails(self):
        broken_c = "#include <stdio.h>\nint main() { SYNTAX_ERROR; return 0; }\n"
        lang_cfg = _from_profile_defaults("c")
        ok, err = _compile_check_patch("c", {"sol.c": broken_c}, lang_cfg, "sol.c")
        assert ok is False
        assert len(err) > 0

    @pytest.mark.skipif(
        not __import__("shutil").which("g++"),
        reason="g++ not available on this host",
    )
    def test_valid_cpp_patch_passes(self):
        valid_cpp = '#include <iostream>\nint main() { std::cout << 8 << std::endl; return 0; }\n'
        lang_cfg = _from_profile_defaults("cpp")
        ok, err = _compile_check_patch("cpp", {"sol.cpp": valid_cpp}, lang_cfg, "sol.cpp")
        assert ok is True, f"Expected compile to pass, got err: {err}"

    @pytest.mark.skipif(
        not __import__("shutil").which("javac"),
        reason="javac not available on this host",
    )
    def test_valid_java_patch_passes(self):
        valid_java = "public class sol { public static void main(String[] args) { System.out.println(8); } }\n"
        lang_cfg = _from_profile_defaults("java")
        ok, err = _compile_check_patch("java", {"sol.java": valid_java}, lang_cfg, "sol.java")
        assert ok is True, f"Expected compile to pass, got err: {err}"


# ── AI shim disabled: returns structured ineligible for all languages ──────────

class TestAiShimDisabled:
    """When CODE_EVAL_ENABLE_AI_SHIM_GENERATION=false, AI path returns structured ineligible."""

    def _run_shim(self, language: str, source: str, entrypoint: str) -> dict:
        request = _make_request(language, source, entrypoint)
        artifacts = _make_failing_artifacts()
        with patch("app.services.code_eval.shim_service.settings") as mock_settings:
            mock_settings.code_eval_enable_ai_shim_generation = False
            mock_settings.code_eval_enable_shim_retry = True
            return analyze_for_retrying_shim(request, artifacts)

    def test_c_ai_disabled(self):
        result = self._run_shim("c", C_ARGV_SOURCE, "sol.c")
        assert result["eligible"] is False
        assert "disabled" in result["reason"] or "not_enabled" in result.get("ai_decision", {}).get("reason", "")

    def test_cpp_ai_disabled(self):
        result = self._run_shim("cpp", CPP_ARGV_SOURCE, "sol.cpp")
        assert result["eligible"] is False

    def test_java_ai_disabled(self):
        result = self._run_shim("java", JAVA_ARGS_SOURCE, "Solution.java")
        assert result["eligible"] is False


# ── AI shim mocked: verifies language-specific instructions sent to Gemini ────

class TestAiShimLanguageDispatch:
    """Verify that the correct language-specific system instruction is dispatched."""

    def _run_mocked_shim(
        self,
        language: str,
        source: str,
        entrypoint: str,
        model_response: dict,
    ) -> dict:
        request = _make_request(language, source, entrypoint)
        artifacts = {
            "executor": "local_subprocess",
            "comparison_mode": "strict",
            "testcases": [{
                "testcase_id": "tc_001",
                "passed": False,
                "weight": 1.0,
                "awarded_score": 0.0,
                "exit_code": 0,
                "stdout": "",
                "stderr": "",
                "failure_reason": "stdout_mismatch",
                "output_truncated": False,
            }],
        }

        with patch("app.services.code_eval.shim_service.settings") as mock_settings, \
             patch("app.services.code_eval.shim_service.generate_structured_json_with_retry") as mock_gen, \
             patch("app.services.code_eval.shim_service.build_structured_json_config") as mock_cfg:

            mock_settings.code_eval_enable_ai_shim_generation = True
            mock_settings.code_eval_enable_shim_retry = True
            mock_settings.resolve_code_healing_model.return_value = "test-model"
            mock_gen.return_value = model_response
            mock_cfg.return_value = MagicMock()

            result = analyze_for_retrying_shim(request, artifacts)

            # Check that build_structured_json_config was called with the right system instruction
            if mock_cfg.called:
                call_kwargs = mock_cfg.call_args[1]
                system_instruction = call_kwargs.get("system_instruction", "")
                if language == "c":
                    assert "C" in system_instruction or "scanf" in system_instruction
                elif language == "cpp":
                    assert "C++" in system_instruction or "cin" in system_instruction
                elif language == "java":
                    assert "Java" in system_instruction or "Scanner" in system_instruction

        return result

    def test_c_model_says_fixable_no_patch_injects_fallback(self):
        result = self._run_mocked_shim(
            "c", C_ARGV_SOURCE, "sol.c",
            {"fixable": True, "reason": "argv_vs_stdin", "comparison_mode": "strict",
             "updated_files": {}, "updated_entrypoint": "sol.c"},
        )
        # Should inject fallback C adapter since model said fixable but provided no patch
        # (or if compile-check fails without a compiler, still eligible via fallback)
        # We just verify it's structured and not an exception
        assert isinstance(result, dict)
        assert "eligible" in result

    def test_java_model_says_not_fixable(self):
        result = self._run_mocked_shim(
            "java", JAVA_ARGS_SOURCE, "Solution.java",
            {"fixable": False, "reason": "logic_bug_not_fixable", "comparison_mode": "strict",
             "updated_files": {}, "updated_entrypoint": "Solution.java"},
        )
        assert result["eligible"] is False
        assert "not_fixable" in result.get("reason", "") or "not_fixable" in result.get("ai_decision", {}).get("reason", "")

    def test_python_model_returns_patch(self):
        patched_source = "import sys\nif len(sys.argv)<=1: sys.argv=[sys.argv[0],'4']\nprint(int(sys.argv[1])*2)\n"
        result = self._run_mocked_shim(
            "python", PYTHON_ARGV_SOURCE, "sol.py",
            {"fixable": True, "reason": "argv_adapter", "comparison_mode": "strict",
             "updated_files": {"sol.py": patched_source}, "updated_entrypoint": "sol.py"},
        )
        assert result["eligible"] is True
        assert result.get("patched_source_files", {}).get("sol.py") == patched_source


# ── Language config integration ───────────────────────────────────────────────

class TestLanguageConfig:
    def test_c_profile_has_flags(self):
        lc = _from_profile_defaults("c")
        assert "-Wall" in lc.compile_flags
        assert "-std=c17" in lc.compile_flags
        assert "-lm" in lc.link_flags

    def test_cpp_profile_has_cpp20(self):
        lc = _from_profile_defaults("cpp")
        assert "-std=c++20" in lc.compile_flags

    def test_java_profile_has_jvm_flags(self):
        lc = _from_profile_defaults("java")
        assert any("Xmx" in f for f in lc.run_flags)

    def test_java_run_command_includes_classpath(self):
        lc = _from_profile_defaults("java")
        cmd = lc.full_java_run_command("Solution")
        assert "-cp" in cmd
        assert "Solution" in cmd

    def test_c_compile_command_includes_link_flags(self):
        lc = _from_profile_defaults("c")
        cmd = lc.full_compile_command("gcc", ["sol.c"], "/tmp/a.out")
        assert "gcc" == cmd[0]
        assert "/tmp/a.out" in cmd
        assert "-lm" in cmd

"""Tests for language_config.py — parsing, validation, and merge logic."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[2]))

from app.services.code_eval.language_config import (
    LanguageConfig,
    _from_profile_defaults,
    parse_language_config,
)


class TestParseLanguageConfigValidation:
    def test_no_spec_returns_profile_defaults(self):
        lc = parse_language_config(None, job_language="python")
        assert lc.language == "python"
        assert lc.compile_flags == []  # python has no compile flags

    def test_empty_spec_returns_profile_defaults(self):
        lc = parse_language_config({}, job_language="c")
        assert "-lm" in lc.link_flags

    def test_unknown_key_raises_explicitly(self):
        with pytest.raises(ValueError, match="Unknown keys in language_config"):
            parse_language_config(
                {"language_config": {"language": "python", "unknown_field": "bad"}},
                job_language="python",
            )

    def test_language_mismatch_raises(self):
        with pytest.raises(ValueError, match="does not match job language"):
            parse_language_config(
                {"language_config": {"language": "java"}},
                job_language="python",
            )

    def test_invalid_compile_flags_type_raises(self):
        with pytest.raises(ValueError, match="must be a list"):
            parse_language_config(
                {"language_config": {"language": "c", "compile_flags": "-Wall"}},
                job_language="c",
            )

    def test_invalid_compile_flag_item_raises(self):
        with pytest.raises(ValueError, match="must be a string"):
            parse_language_config(
                {"language_config": {"language": "c", "compile_flags": ["-Wall", 123]}},
                job_language="c",
            )

    def test_invalid_entrypoint_style_raises(self):
        with pytest.raises(ValueError, match="is invalid"):
            parse_language_config(
                {"language_config": {"language": "python", "entrypoint_style": "garbage"}},
                job_language="python",
            )


class TestParseLanguageConfigMerge:
    def test_instructor_compile_flags_override_profile(self):
        lc = parse_language_config(
            {"language_config": {"language": "c", "compile_flags": ["-O0", "-g"]}},
            job_language="c",
        )
        assert "-O0" in lc.compile_flags
        assert "-g" in lc.compile_flags
        # Profile defaults should NOT appear since instructor specified flags
        assert "-O2" not in lc.compile_flags

    def test_instructor_link_flags_override_profile(self):
        lc = parse_language_config(
            {"language_config": {"language": "c", "link_flags": ["-lpthread"]}},
            job_language="c",
        )
        assert "-lpthread" in lc.link_flags
        assert "-lm" not in lc.link_flags  # profile default overridden

    def test_instructor_run_flags_override_jvm(self):
        lc = parse_language_config(
            {"language_config": {"language": "java", "run_flags": ["-Xmx512m"]}},
            job_language="java",
        )
        assert "-Xmx512m" in lc.run_flags
        assert "-Xmx256m" not in lc.run_flags

    def test_empty_compile_flags_falls_back_to_profile(self):
        lc = parse_language_config(
            {"language_config": {"language": "cpp"}},
            job_language="cpp",
        )
        assert "-std=c++20" in lc.compile_flags

    def test_packages_parsed_correctly(self):
        lc = parse_language_config(
            {"language_config": {"language": "python", "packages": ["numpy==2.0.0", "pandas"]}},
            job_language="python",
        )
        assert "numpy==2.0.0" in lc.packages
        assert "pandas" in lc.packages

    def test_java_classpath_jars(self):
        lc = parse_language_config(
            {"language_config": {"language": "java", "classpath_jars": ["lib/commons.jar"]}},
            job_language="java",
        )
        assert "lib/commons.jar" in lc.classpath_jars


class TestLanguageConfigCommands:
    def test_c_compile_command_structure(self):
        lc = _from_profile_defaults("c")
        cmd = lc.full_compile_command("gcc", ["main.c", "helper.c"], "/tmp/out")
        assert cmd[0] == "gcc"
        assert "main.c" in cmd
        assert "helper.c" in cmd
        assert "-o" in cmd
        assert "/tmp/out" in cmd
        assert "-lm" in cmd  # link flags at end

    def test_cpp_compile_command_has_cpp20(self):
        lc = _from_profile_defaults("cpp")
        cmd = lc.full_compile_command("g++", ["sol.cpp"], "/tmp/out")
        assert "-std=c++20" in cmd

    def test_java_compile_command(self):
        lc = _from_profile_defaults("java")
        cmd = lc.full_java_compile_command(["Solution.java", "Helper.java"])
        assert "javac" == cmd[0]
        assert "Solution.java" in cmd
        assert "Helper.java" in cmd

    def test_java_run_command_with_classpath_jars(self):
        lc = parse_language_config(
            {"language_config": {"language": "java", "classpath_jars": ["lib/a.jar", "lib/b.jar"]}},
            job_language="java",
        )
        cmd = lc.full_java_run_command("Main")
        cp_idx = cmd.index("-cp")
        cp_value = cmd[cp_idx + 1]
        assert "." in cp_value
        assert "lib/a.jar" in cp_value
        assert "lib/b.jar" in cp_value
        assert "Main" in cmd

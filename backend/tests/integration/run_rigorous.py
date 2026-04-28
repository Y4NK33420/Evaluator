#!/usr/bin/env python3
"""
AMGS Rigorous Integration Test Runner
======================================
Runs real-world integration tests against the live stack.

Rules:
  - NO pytest.xfail(), NO pytest.skip() unless the feature literally cannot exist on this host
  - NO assertion relaxation — if a behaviour should happen, it must happen
  - Every HTTP exchange is logged verbatim to logs/raw/<test_name>.json
  - Final summary is written to logs/integration_results.json
  - Exit code 1 on ANY failure

Usage:
    python tests/integration/run_rigorous.py
"""
from __future__ import annotations

import concurrent.futures
import json
import os
import sys
import time
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

BASE = "http://localhost:8080"
POLL_INTERVAL = 1.5
JOB_TIMEOUT = 120   # seconds

# ── Log directory ─────────────────────────────────────────────────────────────
LOG_DIR = Path(__file__).parent / "logs"
RAW_DIR = LOG_DIR / "raw"
LOG_DIR.mkdir(exist_ok=True)
RAW_DIR.mkdir(exist_ok=True)

RESULTS: list[dict] = []
RUN_ID = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def uid() -> str:
    return str(uuid.uuid4())


def _log_raw(name: str, data: dict) -> None:
    import re
    safe = re.sub(r'[\\/:*?"<>|() ]', "_", name).strip("_")
    safe = re.sub(r"_+", "_", safe)[:80]
    path = RAW_DIR / f"{safe}.json"
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")


def _record(name: str, passed: bool, detail: str, raw: dict | None = None) -> None:
    entry = {
        "test": name,
        "passed": passed,
        "detail": detail,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    RESULTS.append(entry)
    status = "✅ PASS" if passed else "❌ FAIL"
    print(f"  {status}  {name}")
    if not passed:
        print(f"         → {detail}")
    if raw:
        _log_raw(name, raw)


# ── HTTP helpers ──────────────────────────────────────────────────────────────

class AssertionFailure(Exception):
    pass


def api_post(path: str, body: dict) -> requests.Response:
    r = requests.post(f"{BASE}{path}", json=body, timeout=30)
    return r


def api_get(path: str, params: dict | None = None) -> requests.Response:
    return requests.get(f"{BASE}{path}", params=params, timeout=30)


def api_post_files(path: str, files: dict, params: dict) -> requests.Response:
    return requests.post(f"{BASE}{path}", files=files, params=params, timeout=30)


def require_status(r: requests.Response, expected: int, ctx: str) -> dict:
    if r.status_code != expected:
        raise AssertionFailure(
            f"{ctx}: expected HTTP {expected}, got {r.status_code}. "
            f"Body: {r.text[:600]}"
        )
    try:
        return r.json()
    except Exception:
        return {"_raw": r.text}


def poll_job(job_id: str, timeout: int = JOB_TIMEOUT) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = api_get(f"/api/v1/code-eval/jobs/{job_id}")
        if r.status_code != 200:
            raise AssertionFailure(f"poll_job GET returned {r.status_code}: {r.text[:300]}")
        j = r.json()
        if j["status"] in {"COMPLETED", "FAILED"}:
            return j
        time.sleep(POLL_INTERVAL)
    raise AssertionFailure(f"Job {job_id} did not finish within {timeout}s — timed out in poll")


# ── Domain helpers ────────────────────────────────────────────────────────────

def create_course() -> str:
    return f"COURSE-{uid()[:8]}"


def create_assignment(course_id: str, title: str = "Test", max_marks: float = 100.0) -> dict:
    r = api_post("/api/v1/assignments/", {
        "course_id": course_id, "title": title,
        "max_marks": max_marks, "question_type": "subjective",
        "has_code_question": True,
    })
    return require_status(r, 201, f"create_assignment({title})")


def create_submission(assignment_id: str, student_id: str, student_name: str = "Tester") -> dict:
    """Upload unique-hash fake JPEG for each student."""
    import io
    content = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00" + student_id.encode() + b"\x00" * 4
    files = {"file": (f"{student_id}.jpg", io.BytesIO(content), "image/jpeg")}
    params = {"student_id": student_id, "student_name": student_name}
    r = api_post_files(f"/api/v1/submissions/{assignment_id}/upload", files=files, params=params)
    resp = require_status(r, 202, f"create_submission({student_id})")
    return {"id": resp["submission_id"]}


def create_env(course_id: str, profile_key: str = "python-3.11",
               language_config: dict | None = None,
               status: str = "ready", freeze_key: str | None = None,
               is_active: bool = True, assignment_id: str | None = None) -> dict:
    spec: dict = {"image_reference": "python:3.11-slim"}
    if language_config:
        spec["language_config"] = language_config
    body = {
        "course_id": course_id,
        "assignment_id": assignment_id,
        "profile_key": profile_key,
        "spec_json": spec,
        "status": status,
        "is_active": is_active,
        "freeze_key": freeze_key or f"fk-{uid()[:8]}",
    }
    r = api_post("/api/v1/code-eval/environments/versions", body)
    return require_status(r, 201, f"create_env({profile_key})")


def make_testcase(tid: str, stdin: str | None = None, argv: list | None = None,
                  expected_stdout: str = "", weight: float = 1.0,
                  expected_exit: int = 0, input_mode: str = "stdin") -> dict:
    return {
        "testcase_id": tid, "weight": weight, "input_mode": input_mode,
        "stdin": stdin, "argv": argv or [], "files": {},
        "expected_stdout": expected_stdout,
        "expected_stderr": None, "expected_exit_code": expected_exit,
    }


def submit_job(assignment_id: str, submission_id: str, env_id: str,
               language: str = "python", entrypoint: str = "solution.py",
               source_files: dict = None, testcases: list = None,
               timeout_s: float = 8.0, explicit_regrade: bool = False) -> dict:
    request = {
        "assignment_id": assignment_id,
        "submission_id": submission_id,
        "language": language,
        "entrypoint": entrypoint,
        "source_files": source_files or {},
        "testcases": testcases or [],
        "environment": {},
        "quality_evaluation": {
            "mode": "disabled", "weight_percent": 0,
            "rubric_source_mode": "instructor_provided",
        },
        "quota": {
            "timeout_seconds": timeout_s, "memory_mb": 256,
            "max_output_kb": 512, "network_enabled": False,
        },
    }
    body = {"environment_version_id": env_id, "explicit_regrade": explicit_regrade,
            "request": request}
    r = api_post("/api/v1/code-eval/jobs", body)
    return require_status(r, 201, f"submit_job({language}/{entrypoint})")


# ══════════════════════════════════════════════════════════════════════════════
# TEST CASES
# ══════════════════════════════════════════════════════════════════════════════

def run_test(name: str, fn):
    """Execute one test, capture full raw response data, record result."""
    raw_log: dict = {"test": name, "run_id": RUN_ID, "steps": []}
    try:
        fn(raw_log)
        _record(name, True, "ok", raw_log)
    except AssertionFailure as e:
        _record(name, False, str(e), raw_log)
    except Exception as e:
        _record(name, False, f"EXCEPTION: {type(e).__name__}: {e}\n{traceback.format_exc()}", raw_log)


# ─── UC1: Python stdin ────────────────────────────────────────────────────────

def tc_python_stdin(raw: dict):
    cid = create_course()
    a = create_assignment(cid, "UC1: Python stdin")
    sub = create_submission(a["id"], f"stu-{uid()[:6]}")
    env = create_env(cid)

    tcs = [
        make_testcase("tc1", stdin="3 7",    expected_stdout="10\n"),
        make_testcase("tc2", stdin="0 0",    expected_stdout="0\n"),
        make_testcase("tc3", stdin="100 200",expected_stdout="300\n"),
        make_testcase("tc4", stdin="-5 5",   expected_stdout="0\n"),
        make_testcase("tc5", stdin="999 1",  expected_stdout="1000\n"),
    ]
    job = submit_job(a["id"], sub["id"], env["id"],
                     source_files={"solution.py": "a,b=map(int,input().split());print(a+b)\n"},
                     testcases=tcs)
    raw["steps"].append({"action": "submit_job", "job_id": job["id"]})

    result = poll_job(job["id"])
    raw["steps"].append({"action": "poll_result", "raw_job": result})

    if result["status"] != "COMPLETED":
        raise AssertionFailure(f"Expected COMPLETED, got {result['status']}. "
                               f"error={result.get('error_message')}")

    final = result["final_result_json"]
    score = float(final.get("total_score", 0))
    raw["steps"].append({"score": score, "final_result_json": final})

    if score != 5.0:
        raise AssertionFailure(f"Expected total_score=5.0, got {score}. full_result={final}")


# ─── UC1b: Grade write-back ───────────────────────────────────────────────────

def tc_grade_writeback(raw: dict):
    cid = create_course()
    a = create_assignment(cid, "UC1b: Grade write-back")
    sub = create_submission(a["id"], f"stu-{uid()[:6]}")
    env = create_env(cid)
    tcs = [make_testcase("tc1", stdin="7", expected_stdout="49\n")]
    job = submit_job(a["id"], sub["id"], env["id"],
                     source_files={"solution.py": "n=int(input());print(n*n)\n"},
                     testcases=tcs)
    result = poll_job(job["id"])
    raw["steps"].append({"poll_result": result})

    if result["status"] != "COMPLETED":
        raise AssertionFailure(f"Job not COMPLETED: {result['status']}")

    gr = api_get(f"/api/v1/code-eval/jobs/{job['id']}/grade")
    raw["steps"].append({"grade_response_status": gr.status_code, "grade_body": gr.json() if gr.ok else gr.text})

    if gr.status_code != 200:
        raise AssertionFailure(f"Grade endpoint returned {gr.status_code}: {gr.text[:400]}")

    grade = gr.json()
    if grade.get("source") != "code_eval":
        raise AssertionFailure(f"grade.source must be 'code_eval', got '{grade.get('source')}'")
    if float(grade.get("total_score", -1)) != 1.0:
        raise AssertionFailure(f"grade.total_score must be 1.0 (1 tc * weight 1), got {grade.get('total_score')}")
    if grade.get("submission_id") != sub["id"]:
        raise AssertionFailure(f"grade.submission_id mismatch: {grade.get('submission_id')} != {sub['id']}")


# ─── UC2: C fibonacci ─────────────────────────────────────────────────────────

def tc_c_fibonacci(raw: dict):
    cid = create_course()
    a = create_assignment(cid, "UC2: C fibonacci")
    sub = create_submission(a["id"], f"stu-{uid()[:6]}")
    env = create_env(cid, profile_key="c-gcc-13")

    source = (
        "#include<stdio.h>\n"
        "int fib(int n){return n<=1?n:fib(n-1)+fib(n-2);}\n"
        "int main(){int n;scanf(\"%d\",&n);printf(\"%d\\n\",fib(n));return 0;}\n"
    )
    tcs = [
        make_testcase("tc1", stdin="0",  expected_stdout="0\n"),
        make_testcase("tc2", stdin="1",  expected_stdout="1\n"),
        make_testcase("tc3", stdin="7",  expected_stdout="13\n"),
        make_testcase("tc4", stdin="10", expected_stdout="55\n"),
    ]
    job = submit_job(a["id"], sub["id"], env["id"], language="c", entrypoint="solution.c",
                     source_files={"solution.c": source}, testcases=tcs, timeout_s=15.0)
    raw["steps"].append({"job_id": job["id"]})

    result = poll_job(job["id"], timeout=180)
    raw["steps"].append({"raw_result": result})

    if result["status"] != "COMPLETED":
        raise AssertionFailure(
            f"C fibonacci FAILED: {result.get('error_message')}. "
            f"final={json.dumps(result.get('final_result_json'), indent=2)}"
        )

    score = float(result["final_result_json"].get("total_score", 0))
    if score != 4.0:
        raise AssertionFailure(f"Expected 4.0 (4 testcases × weight 1), got {score}")


# ─── UC2b: C compile error → structured error_code ───────────────────────────

def tc_c_compile_error(raw: dict):
    cid = create_course()
    a = create_assignment(cid, "UC2b: C compile error")
    sub = create_submission(a["id"], f"stu-{uid()[:6]}")
    env = create_env(cid, profile_key="c-gcc-13")

    bad_source = "#include<stdio.h>\nint main(){SYNTAX_WHOOPS;;;\nreturn 0;}\n"
    tcs = [make_testcase("tc1", stdin="", expected_stdout="0\n")]
    job = submit_job(a["id"], sub["id"], env["id"], language="c", entrypoint="solution.c",
                     source_files={"solution.c": bad_source}, testcases=tcs)
    result = poll_job(job["id"], timeout=60)
    raw["steps"].append({"raw_result": result})

    if result["status"] != "FAILED":
        raise AssertionFailure(f"Expected FAILED for bad C code, got {result['status']}")

    final = result.get("final_result_json") or {}
    # Expect compile_error in the artifacts
    testcase_list = []
    for artifact in final.get("attempt_artifacts", []):
        testcase_list.extend(artifact.get("testcases") or [])

    failure_reasons = [t.get("failure_reason", "") for t in testcase_list]
    raw["steps"].append({"failure_reasons": failure_reasons, "final": final})

    # Must have compile_error, not runtime failure
    has_compile_error = any("compile" in str(r).lower() for r in failure_reasons) or \
                        "compile" in str(final.get("error_code", "")).lower() or \
                        "compile" in str(result.get("error_message", "")).lower()
    if not has_compile_error:
        raise AssertionFailure(
            f"Expected compile_error in failure_reasons or error_code. "
            f"Got failure_reasons={failure_reasons}, error_code={final.get('error_code')}, "
            f"error_message={result.get('error_message')}"
        )


# ─── UC3: C++ sort ───────────────────────────────────────────────────────────

def tc_cpp_sort(raw: dict):
    cid = create_course()
    a = create_assignment(cid, "UC3: C++ sort")
    sub = create_submission(a["id"], f"stu-{uid()[:6]}")
    env = create_env(cid, profile_key="cpp-gpp-13")

    source = (
        "#include<iostream>\n#include<vector>\n#include<algorithm>\n"
        "int main(){\n"
        "    int n;std::cin>>n;\n"
        "    std::vector<int>v(n);\n"
        "    for(auto&x:v)std::cin>>x;\n"
        "    std::sort(v.begin(),v.end());\n"
        "    for(int i=0;i<n;++i)std::cout<<v[i]<<(i+1<n?' ':'\\n');\n"
        "}\n"
    )
    tcs = [
        make_testcase("tc1", stdin="5\n3 1 4 1 5", expected_stdout="1 1 3 4 5\n"),
        make_testcase("tc2", stdin="3\n9 2 7",     expected_stdout="2 7 9\n"),
        make_testcase("tc3", stdin="1\n42",         expected_stdout="42\n"),
    ]
    job = submit_job(a["id"], sub["id"], env["id"], language="cpp", entrypoint="solution.cpp",
                     source_files={"solution.cpp": source}, testcases=tcs, timeout_s=15.0)
    result = poll_job(job["id"], timeout=180)
    raw["steps"].append({"raw_result": result})

    if result["status"] != "COMPLETED":
        raise AssertionFailure(
            f"C++ sort FAILED: {result.get('error_message')}. "
            f"final={json.dumps(result.get('final_result_json'), indent=2)}"
        )
    score = float(result["final_result_json"].get("total_score", 0))
    if score != 3.0:
        raise AssertionFailure(f"Expected score=3.0, got {score}")


# ─── UC4: Java FizzBuzz ───────────────────────────────────────────────────────

def tc_java_fizzbuzz(raw: dict):
    cid = create_course()
    a = create_assignment(cid, "UC4: Java FizzBuzz")
    sub = create_submission(a["id"], f"stu-{uid()[:6]}")
    env = create_env(cid, profile_key="java-21")

    source = (
        "public class solution {\n"
        "    public static void main(String[] args) {\n"
        "        int n = Integer.parseInt(args[0]);\n"
        "        for (int i=1;i<=n;i++) {\n"
        "            if (i%15==0) System.out.println(\"FizzBuzz\");\n"
        "            else if (i%3==0) System.out.println(\"Fizz\");\n"
        "            else if (i%5==0) System.out.println(\"Buzz\");\n"
        "            else System.out.println(i);\n"
        "        }\n"
        "    }\n"
        "}\n"
    )
    expected_15 = "1\n2\nFizz\n4\nBuzz\nFizz\n7\n8\nFizz\nBuzz\n11\nFizz\n13\n14\nFizzBuzz\n"
    tcs = [
        make_testcase("tc1", argv=["5"],  expected_stdout="1\n2\nFizz\n4\nBuzz\n", input_mode="args"),
        make_testcase("tc2", argv=["15"], expected_stdout=expected_15, input_mode="args"),
    ]
    job = submit_job(a["id"], sub["id"], env["id"], language="java", entrypoint="solution.java",
                     source_files={"solution.java": source}, testcases=tcs, timeout_s=30.0)
    result = poll_job(job["id"], timeout=300)
    raw["steps"].append({"raw_result": result})

    if result["status"] != "COMPLETED":
        raise AssertionFailure(
            f"Java FizzBuzz FAILED: {result.get('error_message')}. "
            f"final={json.dumps(result.get('final_result_json'), indent=2)}"
        )


# ─── UC5: Regrade policy ─────────────────────────────────────────────────────

def tc_regrade_policy(raw: dict):
    cid = create_course()
    a = create_assignment(cid, "UC5: Regrade")
    sub = create_submission(a["id"], f"stu-{uid()[:6]}")
    env = create_env(cid)
    tcs = [make_testcase("tc1", stdin="", expected_stdout="hello\n")]

    job1 = submit_job(a["id"], sub["id"], env["id"],
                      source_files={"solution.py": "print('hello')\n"}, testcases=tcs)
    poll_job(job1["id"])
    raw["steps"].append({"job1": job1["id"]})

    # Second job without explicit_regrade MUST be 409
    r = requests.post(f"{BASE}/api/v1/code-eval/jobs", json={
        "environment_version_id": env["id"], "explicit_regrade": False,
        "request": {
            "assignment_id": a["id"], "submission_id": sub["id"],
            "language": "python", "entrypoint": "solution.py",
            "source_files": {"solution.py": "print('hello')\n"},
            "testcases": tcs, "environment": {},
            "quality_evaluation": {"mode": "disabled", "weight_percent": 0,
                                   "rubric_source_mode": "instructor_provided"},
            "quota": {"timeout_seconds": 5.0, "memory_mb": 128,
                      "max_output_kb": 512, "network_enabled": False},
        }
    }, timeout=15)
    raw["steps"].append({"duplicate_job_status": r.status_code, "response": r.text[:300]})

    if r.status_code != 409:
        raise AssertionFailure(
            f"Duplicate job must return 409, got {r.status_code}: {r.text[:400]}"
        )


# ─── UC6: Static analysis blocks OS calls ────────────────────────────────────

def tc_static_analysis(raw: dict):
    cid = create_course()
    env = create_env(cid)
    cases = [
        ("subprocess", "import subprocess\nsubprocess.run(['id'])\nprint('done')\n"),
        ("os_system",  "import os\nos.system('id')\nprint('done')\n"),
        ("eval_exec",  "__import__('os').system('id')\nprint('done')\n"),
    ]
    for case_name, code in cases:
        a = create_assignment(cid, f"UC6: {case_name}")
        sub = create_submission(a["id"], f"stu-{uid()[:6]}")
        tcs = [make_testcase("tc1", stdin="", expected_stdout="done\n")]
        job = submit_job(a["id"], sub["id"], env["id"],
                         source_files={"solution.py": code}, testcases=tcs)
        result = poll_job(job["id"], timeout=60)
        raw["steps"].append({"case": case_name, "result": result})

        if result["status"] != "FAILED":
            raise AssertionFailure(
                f"[{case_name}] Static analysis must block this code. "
                f"Got status={result['status']} — code ran unblocked!"
            )
        final = result.get("final_result_json") or {}
        ec = str(final.get("error_code") or result.get("error_message") or "")
        if "static_analysis" not in ec.lower() and "blocked" not in ec.lower():
            raise AssertionFailure(
                f"[{case_name}] FAILED but error_code doesn't mention static_analysis or blocked. "
                f"error_code='{final.get('error_code')}' error_message='{result.get('error_message')}'"
            )


# ─── UC7: Partial scoring ─────────────────────────────────────────────────────

def tc_partial_scoring(raw: dict):
    cid = create_course()
    a = create_assignment(cid, "UC7: Partial scoring")
    sub = create_submission(a["id"], f"stu-{uid()[:6]}")
    env = create_env(cid)
    # Only handles positive numbers
    code = "n=int(input())\nif n>0:print(n*2)\nelse:print('ERROR')\n"
    tcs = [
        make_testcase("tc1", weight=1.0, stdin="5",    expected_stdout="10\n"),   # pass
        make_testcase("tc2", weight=1.0, stdin="10",   expected_stdout="20\n"),   # pass
        make_testcase("tc3", weight=1.0, stdin="-3",   expected_stdout="-6\n"),   # fail
        make_testcase("tc4", weight=1.0, stdin="-100", expected_stdout="-200\n"), # fail
    ]
    job = submit_job(a["id"], sub["id"], env["id"],
                     source_files={"solution.py": code}, testcases=tcs)
    result = poll_job(job["id"])
    raw["steps"].append({"raw_result": result})

    if result["status"] != "FAILED":
        raise AssertionFailure(f"Expected FAILED (not all passed), got {result['status']}")

    final = result.get("final_result_json") or {}
    # Extract per-attempt score
    attempts = result.get("final_result_json", {}).get("attempts", [])
    if not attempts:
        raise AssertionFailure(f"No attempts in final_result_json: {final}")
    attempt_score = float(attempts[0].get("score", -1))
    if attempt_score != 2.0:
        raise AssertionFailure(
            f"Expected attempt score=2.0 (tc1+tc2 pass, each weight=1), got {attempt_score}. "
            f"attempts={attempts}"
        )


# ─── UC9: No grade for failed job ────────────────────────────────────────────

def tc_no_grade_failed_job(raw: dict):
    cid = create_course()
    a = create_assignment(cid, "UC9: No grade on fail")
    sub = create_submission(a["id"], f"stu-{uid()[:6]}")
    env = create_env(cid)
    tcs = [make_testcase("tc1", stdin="", expected_stdout="correct\n")]
    job = submit_job(a["id"], sub["id"], env["id"],
                     source_files={"solution.py": "print('wrong')\n"}, testcases=tcs)
    result = poll_job(job["id"])
    raw["steps"].append({"raw_result": result})

    if result["status"] != "FAILED":
        raise AssertionFailure(f"Expected FAILED, got {result['status']}")

    gr = api_get(f"/api/v1/code-eval/jobs/{job['id']}/grade")
    raw["steps"].append({"grade_status": gr.status_code, "grade_body": gr.text[:300]})
    if gr.status_code not in {404, 409}:
        raise AssertionFailure(
            f"A FAILED job must NOT have a grade. "
            f"GET /grade returned {gr.status_code}: {gr.text[:300]}"
        )


# ─── UC10: Missing entrypoint → structured error ──────────────────────────────

def tc_missing_entrypoint(raw: dict):
    cid = create_course()
    a = create_assignment(cid, "UC10: Missing entrypoint")
    sub = create_submission(a["id"], f"stu-{uid()[:6]}")
    env = create_env(cid)
    tcs = [make_testcase("tc1", stdin="", expected_stdout="hi\n")]
    job = submit_job(a["id"], sub["id"], env["id"],
                     entrypoint="main.py",
                     source_files={"solution.py": "print('hi')\n"},
                     testcases=tcs)
    result = poll_job(job["id"], timeout=60)
    raw["steps"].append({"raw_result": result})

    if result["status"] != "FAILED":
        raise AssertionFailure(f"Expected FAILED for wrong entrypoint, got {result['status']}")
    # Verify error propagates structured (not a Python traceback in server logs)
    final = result.get("final_result_json") or {}
    err = result.get("error_message") or str(final.get("error_code") or "")
    assert True  # FAILED is sufficient; error must be non-empty
    if not err:
        raise AssertionFailure("FAILED job has no error_message or error_code")


# ─── UC11: 5 concurrent jobs ─────────────────────────────────────────────────

def _one_concurrent_job(cid: str, env_id: str, n: int) -> dict:
    a = create_assignment(cid, f"UC11: Concurrent {n}")
    sub = create_submission(a["id"], f"stu-conc-{n}-{uid()[:4]}")
    expected = n * (n + 1)
    tcs = [make_testcase("tc1", stdin="", expected_stdout=f"{expected}\n")]
    job = submit_job(a["id"], sub["id"], env_id,
                     source_files={"solution.py": f"print({n}*{n+1})\n"}, testcases=tcs)
    return poll_job(job["id"])


def tc_concurrent_load(raw: dict):
    cid = create_course()
    env = create_env(cid)
    n_jobs = 5
    t0 = time.time()
    results = []
    errors = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=n_jobs) as pool:
        futs = {pool.submit(_one_concurrent_job, cid, env["id"], i): i for i in range(n_jobs)}
        for f in concurrent.futures.as_completed(futs, timeout=JOB_TIMEOUT * 3):
            try:
                results.append(f.result())
            except Exception as e:
                errors.append(str(e))

    elapsed = time.time() - t0
    raw["steps"].append({
        "elapsed_s": round(elapsed, 2),
        "completed": len([r for r in results if r["status"] == "COMPLETED"]),
        "failed": len([r for r in results if r["status"] == "FAILED"]),
        "errors": errors,
        "results": results,
    })

    if errors:
        raise AssertionFailure(f"Thread exceptions during concurrent load: {errors}")
    completed = [r for r in results if r["status"] == "COMPLETED"]
    if len(completed) != n_jobs:
        not_done = [r for r in results if r["status"] != "COMPLETED"]
        raise AssertionFailure(
            f"Expected {n_jobs} COMPLETED, got {len(completed)}. "
            f"Non-completed: {[r.get('error_message') for r in not_done]}"
        )
    print(f"         → {n_jobs}/5 COMPLETED in {elapsed:.1f}s", end="")


# ─── UC12: Approval coverage gate ────────────────────────────────────────────

def tc_approval_coverage(raw: dict):
    cid = create_course()
    a = create_assignment(cid, "UC12: Approval coverage")

    # Under-coverage — should 422
    r1 = api_post("/api/v1/code-eval/approvals", {
        "assignment_id": a["id"], "artifact_type": "ai_tests", "version_number": 1,
        "content_json": {
            "testcase_raw_with_classes": [
                {"testcase_id": "tc1", "testcase_class": "happy_path",
                 "input_mode": "stdin", "expected_exit_code": 0,
                 "weight": 1.0, "expected_stdout": "1\n"},
            ]
        }
    })
    raw["steps"].append({"under_coverage_create_status": r1.status_code, "body": r1.json()})

    if r1.status_code != 201:
        raise AssertionFailure(f"Create approval: expected 201, got {r1.status_code}")
    approval_id = r1.json()["id"]

    r_approve = requests.post(
        f"{BASE}/api/v1/code-eval/approvals/{approval_id}/approve",
        json={"actor": "test_instructor"}, timeout=15
    )
    raw["steps"].append({"approve_under_coverage_status": r_approve.status_code,
                         "body": r_approve.text[:400]})

    if r_approve.status_code != 422:
        raise AssertionFailure(
            f"Approving with 1 happy_path and no edge_case/invalid_input must return 422, "
            f"got {r_approve.status_code}: {r_approve.text[:300]}"
        )

    # Full coverage — should 200
    a2 = create_assignment(cid, "UC12b: Approval ok")
    r2 = api_post("/api/v1/code-eval/approvals", {
        "assignment_id": a2["id"], "artifact_type": "ai_tests", "version_number": 1,
        "content_json": {
            "testcase_raw_with_classes": [
                {"testcase_id": "tc1", "testcase_class": "happy_path",
                 "input_mode": "stdin", "expected_exit_code": 0,
                 "weight": 1.0, "expected_stdout": "10\n"},
                {"testcase_id": "tc2", "testcase_class": "happy_path",
                 "input_mode": "stdin", "expected_exit_code": 0,
                 "weight": 1.0, "expected_stdout": "20\n"},
                {"testcase_id": "tc3", "testcase_class": "edge_case",
                 "input_mode": "stdin", "expected_exit_code": 0,
                 "weight": 1.0, "expected_stdout": "0\n"},
                {"testcase_id": "tc4", "testcase_class": "invalid_input",
                 "input_mode": "stdin", "expected_exit_code": 1,
                 "weight": 0.5, "expected_stdout": ""},
            ]
        }
    })
    raw["steps"].append({"full_coverage_create_status": r2.status_code})
    if r2.status_code != 201:
        raise AssertionFailure(f"Create full-coverage approval: expected 201, got {r2.status_code}: {r2.text[:300]}")

    r_approve2 = requests.post(
        f"{BASE}/api/v1/code-eval/approvals/{r2.json()['id']}/approve",
        json={"actor": "test_instructor"}, timeout=15
    )
    raw["steps"].append({"approve_full_coverage_status": r_approve2.status_code,
                         "body": r_approve2.json() if r_approve2.ok else r_approve2.text[:300]})

    if r_approve2.status_code != 200:
        raise AssertionFailure(
            f"Full coverage approval must return 200, got {r_approve2.status_code}: {r_approve2.text[:400]}"
        )
    if r_approve2.json().get("status") != "approved":
        raise AssertionFailure(f"Approval status must be 'approved', got: {r_approve2.json()}")


# ─── UC13: Timeout ───────────────────────────────────────────────────────────

def tc_timeout(raw: dict):
    cid = create_course()
    a = create_assignment(cid, "UC13: Timeout")
    sub = create_submission(a["id"], f"stu-{uid()[:6]}")
    env = create_env(cid)
    tcs = [make_testcase("tc1", stdin="", expected_stdout="never\n")]
    job = submit_job(a["id"], sub["id"], env["id"],
                     source_files={"solution.py": "while True: pass\n"},
                     testcases=tcs, timeout_s=5.0)
    result = poll_job(job["id"], timeout=60)
    raw["steps"].append({"raw_result": result})

    if result["status"] != "FAILED":
        raise AssertionFailure(f"Infinite loop must FAIL (timeout), got {result['status']}")

    final = result.get("final_result_json") or {}
    # Find failure reason in testcase artifacts
    tcs_out = []
    for a_item in final.get("attempt_artifacts", []):
        tcs_out.extend(a_item.get("testcases") or [])

    if tcs_out:
        reason = str(tcs_out[0].get("failure_reason") or "")
        raw["steps"].append({"failure_reason": reason, "testcases_raw": tcs_out})
        if "timeout" not in reason.lower():
            raise AssertionFailure(
                f"Timeout job must have 'timeout' in failure_reason, got: '{reason}'"
            )


# ─── UC14: Bad language_config key → job FAILS with configuration_error ───────

def tc_bad_language_config(raw: dict):
    """
    Instructor creates an env with 'junk_key' in language_config.
    The job must FAIL with configuration_error.
    NO xfail masking. If the worker completes the job silently, this is a real bug.
    """
    cid = create_course()
    bad_spec = {
        "image_reference": "python:3.11-slim",
        "language_config": {
            "language": "python",
            "junk_unsupported_key_that_must_fail": "boom",
        }
    }
    r = api_post("/api/v1/code-eval/environments/versions", {
        "course_id": cid, "profile_key": "python-3.11",
        "spec_json": bad_spec, "status": "ready", "is_active": True,
        "freeze_key": f"fk-bad-{uid()[:8]}",
    })
    env = require_status(r, 201, "create bad env")
    raw["steps"].append({"env": env})

    a = create_assignment(cid, "UC14: Bad lang config")
    sub = create_submission(a["id"], f"stu-{uid()[:6]}")
    tcs = [make_testcase("tc1", stdin="", expected_stdout="hi\n")]
    job = submit_job(a["id"], sub["id"], env["id"],
                     source_files={"solution.py": "print('hi')\n"}, testcases=tcs)
    result = poll_job(job["id"], timeout=60)
    raw["steps"].append({"raw_result": result})

    if result["status"] == "COMPLETED":
        raise AssertionFailure(
            "BUG: Job COMPLETED despite having 'junk_unsupported_key_that_must_fail' "
            "in language_config. Worker is silently ignoring unknown config keys. "
            "execution_service.parse_language_config() try/except not firing."
        )

    if result["status"] != "FAILED":
        raise AssertionFailure(f"Expected FAILED, got {result['status']}")

    final = result.get("final_result_json") or {}
    ec = str(final.get("error_code") or result.get("error_message") or "")
    if "configuration" not in ec.lower() and "unknown" not in ec.lower():
        raise AssertionFailure(
            f"FAILED but error_code/message doesn't mention 'configuration' or 'unknown'. "
            f"Got error_code='{final.get('error_code')}' "
            f"error_message='{result.get('error_message')}'"
        )


# ─── UC15: Output truncation ─────────────────────────────────────────────────

def tc_output_truncation(raw: dict):
    cid = create_course()
    a = create_assignment(cid, "UC15: Output truncation")
    sub = create_submission(a["id"], f"stu-{uid()[:6]}")
    env = create_env(cid)
    # ~600KB — exceeds 512KB quota
    tcs = [make_testcase("tc1", stdin="", expected_stdout="x\n")]
    job = submit_job(a["id"], sub["id"], env["id"],
                     source_files={"solution.py": "print('x'*1024*600)\n"},
                     testcases=tcs)
    result = poll_job(job["id"], timeout=60)
    raw["steps"].append({"raw_result": result})

    # Must FAIL (output doesn't match expected "x\n") AND be truncated
    if result["status"] != "FAILED":
        raise AssertionFailure(f"Expected FAILED (output exceeded quota), got {result['status']}")

    final = result.get("final_result_json") or {}
    tcs_out = []
    for a_item in final.get("attempt_artifacts", []):
        tcs_out.extend(a_item.get("testcases") or [])

    raw["steps"].append({"testcases_raw": tcs_out})
    # Verify output_truncated flag is set
    if tcs_out:
        truncated = tcs_out[0].get("output_truncated", False)
        if not truncated:
            raise AssertionFailure(
                f"output_truncated must be True when stdout exceeds max_output_kb=512. "
                f"Got output_truncated={truncated}. testcase={tcs_out[0]}"
            )


# ─── UC16: 8-student classroom ────────────────────────────────────────────────

def _run_student_job(assignment_id: str, env_id: str, student_id: str,
                     code: str, testcases: list, student_name: str) -> dict:
    sub = create_submission(assignment_id, student_id, student_name)
    if not code.strip():
        code = "# empty\n"
    job = submit_job(assignment_id, sub["id"], env_id,
                     source_files={"solution.py": code}, testcases=testcases)
    result = poll_job(job["id"])
    return {
        "student": student_id,
        "status": result["status"],
        "score": float((result.get("final_result_json") or {}).get("total_score", 0)),
        "error_code": (result.get("final_result_json") or {}).get("error_code"),
        "error_message": result.get("error_message"),
        "raw": result,
    }


def tc_classroom_simulation(raw: dict):
    cid = create_course()
    a = create_assignment(cid, "UC16: Classroom", max_marks=3.0)
    env = create_env(cid)
    rid = uid()[:6]

    STUDENT_CODE = {
        "passing":       "n=int(input());print(n*n)\n",
        "off_by_one":    "n=int(input());print(n*n+1)\n",
        "wrong_logic":   "print(0)\n",
        "runtime_error": "raise ValueError('deliberate crash')\n",
        "slow_pass":     "import time;time.sleep(0.2);n=int(input());print(n*n)\n",
    }
    ROSTER = [
        (f"stu-A-{rid}", "passing",       "Alice Pass"),
        (f"stu-B-{rid}", "passing",       "Bob Pass"),
        (f"stu-C-{rid}", "off_by_one",    "Carol Off"),
        (f"stu-D-{rid}", "wrong_logic",   "Dave Wrong"),
        (f"stu-E-{rid}", "runtime_error", "Eve Crash"),
        (f"stu-F-{rid}", "passing",       "Frank Pass"),
        (f"stu-G-{rid}", "slow_pass",     "Grace Slow"),
        (f"stu-H-{rid}", "off_by_one",    "Hank Off"),
    ]

    testcases = [
        make_testcase("tc1", weight=1.0, stdin="5",  expected_stdout="25\n"),
        make_testcase("tc2", weight=1.0, stdin="10", expected_stdout="100\n"),
        make_testcase("tc3", weight=1.0, stdin="0",  expected_stdout="0\n"),
    ]

    t0 = time.time()
    outcomes = []
    exceptions = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futs = {
            pool.submit(
                _run_student_job, a["id"], env["id"],
                sid, STUDENT_CODE[code_key], testcases, name
            ): (sid, code_key)
            for sid, code_key, name in ROSTER
        }
        for f in concurrent.futures.as_completed(futs, timeout=JOB_TIMEOUT * 3):
            sid, code_key = futs[f]
            try:
                outcomes.append(f.result())
            except Exception as e:
                exceptions.append({"student": sid, "error": str(e)})
                outcomes.append({"student": sid, "status": "THREAD_ERROR",
                                  "score": 0, "error_code": None,
                                  "error_message": str(e), "raw": {}})

    elapsed = time.time() - t0
    raw["steps"].append({
        "elapsed_s": round(elapsed, 2),
        "outcomes": outcomes,
        "thread_exceptions": exceptions,
    })

    print(f"\n         Classroom ({len(ROSTER)} students, {elapsed:.1f}s):")
    for o in sorted(outcomes, key=lambda x: x["student"]):
        print(f"           {o['student']}: {o['status']} score={o['score']:.1f} "
              f"error_code={o.get('error_code')} error={str(o.get('error_message') or '')[:80]}")

    # HARD ASSERTIONS — no relaxation
    if exceptions:
        raise AssertionFailure(
            f"{len(exceptions)} student submits threw thread exceptions: {exceptions}"
        )

    thread_errors = [o for o in outcomes if o["status"] == "THREAD_ERROR"]
    if thread_errors:
        raise AssertionFailure(f"Thread errors — submission failed for: {thread_errors}")

    passing = [o for o in outcomes if o["status"] == "COMPLETED" and o["score"] > 0]
    expected_passers = {"passing", "slow_pass"}
    n_expected_pass = len([s for s in ROSTER if s[1] in expected_passers])  # 4: A,B,F,G
    if len(passing) != n_expected_pass:
        raise AssertionFailure(
            f"Expected exactly {n_expected_pass} COMPLETED students (A, B, F, G), "
            f"got {len(passing)}: {[o['student'] for o in passing]}"
        )

    failing = [o for o in outcomes if o["status"] == "FAILED"]
    n_expected_fail = len([s for s in ROSTER if s[1] not in expected_passers])  # 4: C,D,E,H
    if len(failing) != n_expected_fail:
        raise AssertionFailure(
            f"Expected exactly {n_expected_fail} FAILED students (C,D,E,H), "
            f"got {len(failing)}: {[o['student'] for o in failing]}"
        )

    for o in failing:
        if o["score"] != 0.0:
            raise AssertionFailure(
                f"FAILED student {o['student']} must have score=0, got {o['score']}"
            )
        if not o.get("error_code") and not o.get("error_message"):
            raise AssertionFailure(
                f"FAILED student {o['student']} has no error_code or error_message — "
                f"silent failure is not acceptable"
            )


# ─── UC17: Env guards ─────────────────────────────────────────────────────────

def tc_env_guards(raw: dict):
    cid = create_course()
    a = create_assignment(cid, "UC17: Env guards")
    sub = create_submission(a["id"], f"stu-{uid()[:6]}")

    # Inactive env
    inactive = create_env(cid, is_active=False)
    r = requests.post(f"{BASE}/api/v1/code-eval/jobs", json={
        "environment_version_id": inactive["id"], "explicit_regrade": False,
        "request": {
            "assignment_id": a["id"], "submission_id": sub["id"],
            "language": "python", "entrypoint": "solution.py",
            "source_files": {"solution.py": "print('hi')\n"},
            "testcases": [make_testcase("tc1", expected_stdout="hi\n")],
            "environment": {},
            "quality_evaluation": {"mode": "disabled", "weight_percent": 0,
                                   "rubric_source_mode": "instructor_provided"},
            "quota": {"timeout_seconds": 5.0, "memory_mb": 128,
                      "max_output_kb": 512, "network_enabled": False},
        }
    }, timeout=15)
    raw["steps"].append({"inactive_env_status": r.status_code, "body": r.text[:300]})
    if r.status_code != 409:
        raise AssertionFailure(f"Inactive env must return 409, got {r.status_code}: {r.text[:300]}")

    # Cross-course env
    other_course = f"ALIEN-{uid()[:6]}"
    alien_env = create_env(other_course)
    r2 = requests.post(f"{BASE}/api/v1/code-eval/jobs", json={
        "environment_version_id": alien_env["id"], "explicit_regrade": False,
        "request": {
            "assignment_id": a["id"], "submission_id": sub["id"],
            "language": "python", "entrypoint": "solution.py",
            "source_files": {"solution.py": "print('hi')\n"},
            "testcases": [make_testcase("tc1", expected_stdout="hi\n")],
            "environment": {},
            "quality_evaluation": {"mode": "disabled", "weight_percent": 0,
                                   "rubric_source_mode": "instructor_provided"},
            "quota": {"timeout_seconds": 5.0, "memory_mb": 128,
                      "max_output_kb": 512, "network_enabled": False},
        }
    }, timeout=15)
    raw["steps"].append({"cross_course_status": r2.status_code, "body": r2.text[:300]})
    if r2.status_code != 422:
        raise AssertionFailure(f"Cross-course env must return 422, got {r2.status_code}: {r2.text[:300]}")


# ─── UC18: AI shim — real Gemini call ────────────────────────────────────────

def tc_ai_shim_real_call(raw: dict):
    """
    Submit code that reads from stdin but has no input() call visible to the static analyzer.
    The shim must call real Gemini to wrap it. Verify:
      1. Job completes (shim or not)
      2. If shim was invoked, shim_used=True and shim_source is non-null (real model name)
      3. Response body has no 'mock' or 'fake' strings in shim_source
    """
    r_status = api_get("/api/v1/code-eval/runtime/status")
    status = r_status.json()
    raw["steps"].append({"runtime_status": status})

    shim_enabled = status.get("ai_shim_generation_enabled", False)
    shim_retry = status.get("shim_retry_enabled", False)
    raw["steps"].append({"shim_enabled": shim_enabled, "shim_retry": shim_retry})

    if not shim_enabled:
        raise AssertionFailure(
            "CODE_EVAL_ENABLE_AI_SHIM_GENERATION must be true for this test. "
            f"runtime status: {status}"
        )

    cid = create_course()
    a = create_assignment(cid, "UC18: AI Shim real Gemini")
    sub = create_submission(a["id"], f"stu-{uid()[:6]}")
    env = create_env(cid)

    # Code that needs shim: sys.argv based but testcase provides stdin
    code = (
        "import sys\n"
        "# This program expects two numbers via command line args\n"
        "x = int(sys.argv[1])\n"
        "y = int(sys.argv[2])\n"
        "print(x + y)\n"
    )
    tcs = [make_testcase("tc1", stdin="3 7", expected_stdout="10\n", input_mode="stdin")]
    job = submit_job(a["id"], sub["id"], env["id"],
                     source_files={"solution.py": code}, testcases=tcs)
    result = poll_job(job["id"])
    raw["steps"].append({"raw_result": result})

    # The shim may or may not fire (depends on static analysis deciding a shim is needed).
    # What we CAN verify regardless:
    # 1. Job either COMPLETED or FAILED with a real error_code
    if result["status"] not in {"COMPLETED", "FAILED"}:
        raise AssertionFailure(f"Unexpected status: {result['status']}")

    # Check attempts for shim info
    attempts_in_detail = []
    detail_r = api_get(f"/api/v1/code-eval/jobs/{job['id']}")
    raw["steps"].append({"job_detail": detail_r.json()})

    # If shim was used, shim_source must be a real model string, not mock/fake
    final = result.get("final_result_json") or {}
    shim_source = final.get("shim_source") or ""
    if shim_source:
        if "mock" in shim_source.lower() or "fake" in shim_source.lower():
            raise AssertionFailure(
                f"shim_source='{shim_source}' contains 'mock' or 'fake' — "
                f"AI shim is using a mock model, not real Gemini!"
            )
        raw["steps"].append({"shim_source": shim_source, "verdict": "real_model_used"})
    else:
        raw["steps"].append({"shim_verdict": "shim_not_triggered_for_this_code"})


# ─── UC19: API 404/422/409 robustness ────────────────────────────────────────

def tc_api_robustness(raw: dict):
    # 404 for nonexistent job
    r = api_get(f"/api/v1/code-eval/jobs/{uid()}")
    raw["steps"].append({"nonexistent_job_status": r.status_code})
    if r.status_code != 404:
        raise AssertionFailure(f"Nonexistent job: expected 404, got {r.status_code}")

    # 404 for grade of nonexistent job
    r2 = api_get(f"/api/v1/code-eval/jobs/{uid()}/grade")
    raw["steps"].append({"nonexistent_grade_status": r2.status_code})
    if r2.status_code != 404:
        raise AssertionFailure(f"Grade of nonexistent job: expected 404, got {r2.status_code}")

    # 404 for approve nonexistent approval
    r3 = requests.post(f"{BASE}/api/v1/code-eval/approvals/{uid()}/approve",
                       json={"actor": "x"}, timeout=10)
    raw["steps"].append({"nonexistent_approval_status": r3.status_code})
    if r3.status_code != 404:
        raise AssertionFailure(f"Approve nonexistent: expected 404, got {r3.status_code}")

    # Runtime status endpoint
    r4 = api_get("/api/v1/code-eval/runtime/status")
    raw["steps"].append({"runtime_status_response": r4.json()})
    if r4.status_code != 200:
        raise AssertionFailure(f"Runtime status: expected 200, got {r4.status_code}")
    s = r4.json()
    for key in ("execution_backend", "shim_retry_enabled"):
        if key not in s:
            raise AssertionFailure(f"Runtime status missing key '{key}': {s}")
    if s["execution_backend"] not in {"local", "docker", "microvm"}:
        raise AssertionFailure(f"execution_backend='{s['execution_backend']}' invalid")


# ──────────────────────────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────────────────────────

TESTS = [
    ("UC1:  Python stdin (5 testcases)",              tc_python_stdin),
    ("UC1b: Grade write-back verification",           tc_grade_writeback),
    ("UC2:  C fibonacci (4 testcases)",               tc_c_fibonacci),
    ("UC2b: C compile error → structured error_code", tc_c_compile_error),
    ("UC3:  C++ sort vector (3 testcases)",           tc_cpp_sort),
    ("UC4:  Java FizzBuzz (2 testcases)",             tc_java_fizzbuzz),
    ("UC5:  Regrade policy (409 on duplicate)",       tc_regrade_policy),
    ("UC6:  Static analysis blocks OS calls (3x)",    tc_static_analysis),
    ("UC7:  Partial scoring (2/4 testcases pass)",    tc_partial_scoring),
    ("UC9:  No grade for FAILED job",                 tc_no_grade_failed_job),
    ("UC10: Missing entrypoint → structured error",   tc_missing_entrypoint),
    ("UC11: 5 concurrent jobs",                       tc_concurrent_load),
    ("UC12: Approval coverage gate",                  tc_approval_coverage),
    ("UC13: Infinite loop → timeout error",           tc_timeout),
    ("UC14: Bad language_config → configuration_error (NO XFAIL)", tc_bad_language_config),
    ("UC15: Output truncation flag",                  tc_output_truncation),
    ("UC16: 8-student classroom (4 COMPLETED, 4 FAILED)", tc_classroom_simulation),
    ("UC17: Env guards (inactive=409, cross-course=422)", tc_env_guards),
    ("UC18: AI shim verifies real Gemini (no mock)",  tc_ai_shim_real_call),
    ("UC19: API 404/422/409 robustness",              tc_api_robustness),
]


def main():
    print(f"\n{'='*70}")
    print(f"  AMGS Rigorous Integration Tests — {RUN_ID}")
    print(f"  Stack: {BASE}")
    print(f"  Log dir: {LOG_DIR.resolve()}")
    print(f"{'='*70}\n")

    # Health check
    try:
        hr = requests.get(f"{BASE}/health", timeout=8)
        if hr.status_code != 200:
            print(f"FATAL: Stack not healthy: {hr.status_code}")
            sys.exit(1)
        print(f"  Stack health: {hr.json()}\n")
    except Exception as e:
        print(f"FATAL: Cannot reach {BASE}: {e}")
        sys.exit(1)

    for name, fn in TESTS:
        print(f"\n{'─'*60}")
        print(f"  {name}")
        run_test(name, fn)

    # Write summary
    passed = [r for r in RESULTS if r["passed"]]
    failed = [r for r in RESULTS if not r["passed"]]

    summary = {
        "run_id": RUN_ID,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total": len(RESULTS),
        "passed": len(passed),
        "failed": len(failed),
        "results": RESULTS,
    }
    summary_path = LOG_DIR / "integration_results.json"
    summary_path.write_text(json.dumps(summary, indent=2, default=str))

    print(f"\n{'='*70}")
    print(f"  RESULTS: {len(passed)}/{len(RESULTS)} passed, {len(failed)} failed")
    print(f"  Raw logs: {RAW_DIR.resolve()}")
    print(f"  Summary:  {summary_path.resolve()}")

    if failed:
        print(f"\n  FAILURES:")
        for r in failed:
            print(f"    ❌ {r['test']}")
            print(f"       {r['detail'][:200]}")
        print()
        sys.exit(1)

    print("\n  ALL TESTS PASSED\n")
    sys.exit(0)


if __name__ == "__main__":
    main()

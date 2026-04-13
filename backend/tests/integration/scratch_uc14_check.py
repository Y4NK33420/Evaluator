import requests, uuid, time, json, io

BASE = "http://localhost:8080"
uid = lambda: str(uuid.uuid4())

bad_spec = {
    "image_reference": "python:3.11-slim",
    "language_config": {
        "language": "python",
        "junk_key_must_fail": "boom",
    }
}
cid = f"C-{uid()[:6]}"
r = requests.post(f"{BASE}/api/v1/code-eval/environments/versions", json={
    "course_id": cid, "profile_key": "python-3.11",
    "spec_json": bad_spec, "status": "ready", "is_active": True,
    "freeze_key": f"fk-{uid()[:8]}",
})
env = r.json()
print("ENV:", r.status_code, env.get("id"))

a_r = requests.post(f"{BASE}/api/v1/assignments/", json={
    "course_id": cid, "title": "UC14 spot check",
    "max_marks": 10, "question_type": "subjective", "has_code_question": True,
})
a = a_r.json()
print("ASSIGNMENT:", a_r.status_code, a.get("id"))

content = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00stu-test-uc14\x00\x00"
files = {"file": ("s.jpg", io.BytesIO(content), "image/jpeg")}
sub_r = requests.post(
    f"{BASE}/api/v1/submissions/{a['id']}/upload",
    files=files, params={"student_id": "stu-uc14", "student_name": "T"}
)
sub = sub_r.json()
print("SUBMISSION:", sub_r.status_code, sub.get("submission_id"))

body = {
    "environment_version_id": env["id"],
    "explicit_regrade": False,
    "request": {
        "assignment_id": a["id"],
        "submission_id": sub["submission_id"],
        "language": "python",
        "entrypoint": "solution.py",
        "source_files": {"solution.py": "print('hi')\n"},
        "testcases": [{
            "testcase_id": "tc1", "weight": 1.0, "input_mode": "stdin",
            "stdin": "", "argv": [], "files": {},
            "expected_stdout": "hi\n", "expected_stderr": None, "expected_exit_code": 0,
        }],
        "environment": {},
        "quality_evaluation": {
            "mode": "disabled", "weight_percent": 0,
            "rubric_source_mode": "instructor_provided",
        },
        "quota": {
            "timeout_seconds": 5.0, "memory_mb": 128,
            "max_output_kb": 512, "network_enabled": False,
        },
    },
}
jr = requests.post(f"{BASE}/api/v1/code-eval/jobs", json=body)
job = jr.json()
print("JOB:", jr.status_code, job.get("id"))

for _ in range(40):
    r = requests.get(f"{BASE}/api/v1/code-eval/jobs/{job['id']}")
    j = r.json()
    if j["status"] in {"COMPLETED", "FAILED"}:
        print("RESULT STATUS:", j["status"])
        print("ERROR_MESSAGE:", j.get("error_message"))
        print("FINAL JSON:", json.dumps(j.get("final_result_json"), indent=2))
        break
    time.sleep(1.5)
else:
    print("TIMEOUT: job did not finish")

#!/usr/bin/env bash
set -euo pipefail

# Linux/KVM end-to-end runner for Firecracker code-eval runtime.
# 1) Ensures snapshot artifacts exist.
# 2) Brings up backend+worker with microvm override.
# 3) Verifies preflight ready.
# 4) Creates and runs a real code-eval job via API.

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
BASE_URL="${BASE_URL:-http://localhost:8080/api/v1}"
SNAPSHOT_VMSTATE="${SNAPSHOT_VMSTATE:-${ROOT_DIR}/microvm/snapshots/python311.vmstate}"
SNAPSHOT_MEM="${SNAPSHOT_MEM:-${ROOT_DIR}/microvm/snapshots/python311.mem}"

if [[ ! -f "${SNAPSHOT_VMSTATE}" || ! -f "${SNAPSHOT_MEM}" ]]; then
  echo "ERROR: snapshot artifacts are missing." >&2
  echo "Run: microvm/scripts/create_snapshot_with_guest_agent.sh" >&2
  exit 1
fi

pushd "${ROOT_DIR}" >/dev/null

docker compose -f docker-compose.yml -f docker-compose.microvm.yml up -d backend worker-code-eval

for _ in $(seq 1 60); do
  if curl -fsS "http://localhost:8080/health" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

PRE="$(curl -fsS "${BASE_URL}/code-eval/runtime/preflight")"
python3 - <<'PY' "${PRE}"
import json, sys
payload = json.loads(sys.argv[1])
fc = payload.get("firecracker") or {}
if not fc.get("ready"):
    print("ERROR: firecracker preflight is not ready:", file=sys.stderr)
    print(json.dumps(fc, indent=2), file=sys.stderr)
    raise SystemExit(1)
print("firecracker preflight ready=true")
PY

SUFFIX="$(date +%Y%m%d%H%M%S)"
ASSIGNMENT_PAYLOAD="$(cat <<JSON
{
  "course_id": "course-firecracker-live-${SUFFIX}",
  "title": "Firecracker Live ${SUFFIX}",
  "description": "firecracker e2e validation",
  "max_marks": 100,
  "question_type": "subjective",
  "has_code_question": true
}
JSON
)"

ASSIGNMENT_JSON="$(curl -fsS -X POST "${BASE_URL}/assignments/" -H 'Content-Type: application/json' -d "${ASSIGNMENT_PAYLOAD}")"
ASSIGNMENT_ID="$(python3 - <<'PY' "${ASSIGNMENT_JSON}"
import json, sys
print(json.loads(sys.argv[1])["id"])
PY
)"
COURSE_ID="$(python3 - <<'PY' "${ASSIGNMENT_JSON}"
import json, sys
print(json.loads(sys.argv[1])["course_id"])
PY
)"

ENV_PAYLOAD="$(cat <<JSON
{
  "course_id": "${COURSE_ID}",
  "assignment_id": "${ASSIGNMENT_ID}",
  "profile_key": "python-basic",
  "reuse_mode": "course_reuse_with_assignment_overrides",
  "spec_json": {
    "mode": "manifest",
    "runtime": "python-3.11",
    "manifest": {"python": "3.11.9"}
  },
  "freeze_key": "firecracker-live-${SUFFIX}",
  "status": "ready",
  "version_number": 1,
  "is_active": true,
  "created_by": "firecracker-e2e-script"
}
JSON
)"
ENV_JSON="$(curl -fsS -X POST "${BASE_URL}/code-eval/environments/versions" -H 'Content-Type: application/json' -d "${ENV_PAYLOAD}")"
ENV_ID="$(python3 - <<'PY' "${ENV_JSON}"
import json, sys
print(json.loads(sys.argv[1])["id"])
PY
)"

UPLOAD_FILE="${ROOT_DIR}/logs/firecracker_e2e_upload_${SUFFIX}.txt"
printf "print('upload')\n" > "${UPLOAD_FILE}"
UPLOAD_JSON="$(curl -fsS -X POST "${BASE_URL}/submissions/${ASSIGNMENT_ID}/upload?student_id=student-firecracker-${SUFFIX}&student_name=Firecracker%20E2E" -F "file=@${UPLOAD_FILE};type=text/plain")"
SUBMISSION_ID="$(python3 - <<'PY' "${UPLOAD_JSON}"
import json, sys
print(json.loads(sys.argv[1])["submission_id"])
PY
)"

JOB_PAYLOAD="$(cat <<JSON
{
  "environment_version_id": "${ENV_ID}",
  "explicit_regrade": true,
  "request": {
    "assignment_id": "${ASSIGNMENT_ID}",
    "submission_id": "${SUBMISSION_ID}",
    "language": "python",
    "entrypoint": "solution.py",
    "source_files": {
      "solution.py": "import sys\\nnums=[int(x) for x in sys.stdin.read().split() if x]\\nprint(sum(nums))"
    },
    "testcases": [
      {
        "testcase_id": "tc1",
        "weight": 1.0,
        "input_mode": "stdin",
        "stdin": "1 2 3",
        "expected_stdout": "6",
        "expected_stderr": "",
        "expected_exit_code": 0
      },
      {
        "testcase_id": "tc2",
        "weight": 1.0,
        "input_mode": "stdin",
        "stdin": "4 5",
        "expected_stdout": "9",
        "expected_stderr": "",
        "expected_exit_code": 0
      }
    ],
    "environment": {
      "mode": "manifest",
      "reuse_mode": "course_reuse_with_assignment_overrides",
      "runtime": "python-3.11",
      "clean_strategy": "ephemeral_clone"
    },
    "quality_evaluation": {
      "mandatory_per_assignment": true,
      "mode": "disabled",
      "rubric_source_mode": "instructor_provided",
      "weight_percent": 0.0,
      "dimensions": ["readability"]
    },
    "regrade_policy": "force_reprocess_all",
    "quota": {
      "timeout_seconds": 5.0,
      "memory_mb": 256,
      "max_output_kb": 256,
      "network_enabled": false
    }
  }
}
JSON
)"

JOB_JSON="$(curl -fsS -X POST "${BASE_URL}/code-eval/jobs" -H 'Content-Type: application/json' -d "${JOB_PAYLOAD}")"
JOB_ID="$(python3 - <<'PY' "${JOB_JSON}"
import json, sys
print(json.loads(sys.argv[1])["id"])
PY
)"

STATUS=""
DETAIL=""
for _ in $(seq 1 80); do
  DETAIL="$(curl -fsS "${BASE_URL}/code-eval/jobs/${JOB_ID}")"
  STATUS="$(python3 - <<'PY' "${DETAIL}"
import json, sys
print(json.loads(sys.argv[1])["status"])
PY
)"
  if [[ "${STATUS}" == "COMPLETED" || "${STATUS}" == "FAILED" ]]; then
    break
  fi
  sleep 2
done

echo "job_id=${JOB_ID} status=${STATUS}"
python3 - <<'PY' "${DETAIL}"
import json, sys
job = json.loads(sys.argv[1])
print(json.dumps({
    "status": job.get("status"),
    "error_message": job.get("error_message"),
    "final_result": job.get("final_result_json"),
    "attempt_artifacts": (job.get("attempts") or [{}])[0].get("artifacts_json"),
}, indent=2))
PY

popd >/dev/null

import json
import os
import shutil
from pathlib import Path
from unittest.mock import patch

# Load root .env
root_env = Path('../.env')
env = {}
for raw in root_env.read_text(encoding='utf-8').splitlines():
    line = raw.strip()
    if not line or line.startswith('#') or '=' not in line:
        continue
    k, v = line.split('=', 1)
    env[k.strip()] = v.strip().strip('"').strip("'")

# Runtime env for this live run
os.environ['GOOGLE_CLOUD_API_KEY'] = env.get('GOOGLE_CLOUD_API_KEY', '')
os.environ['GOOGLE_GENAI_USE_VERTEXAI'] = 'true'
os.environ['GOOGLE_CLOUD_PROJECT'] = env.get('GOOGLE_CLOUD_PROJECT', '56451059812')
os.environ['GOOGLE_CLOUD_LOCATION'] = env.get('GOOGLE_CLOUD_LOCATION', 'us-central1')
os.environ['DEFAULT_MODEL'] = env.get('DEFAULT_MODEL', 'gemini-3.1-flash-lite-preview')
os.environ['DATABASE_URL'] = 'sqlite:///d:/dev/DEP/backend/tests/live_api_e2e.db'
os.environ['UPLOADS_DIR'] = 'd:/dev/DEP/backend/tests/uploads_live'
os.environ['DEBUG'] = 'true'

# Reset live artifacts
Path('tests').mkdir(parents=True, exist_ok=True)
db_file = Path('tests/live_api_e2e.db')
if db_file.exists():
    db_file.unlink()
uploads = Path('tests/uploads_live')
if uploads.exists():
    shutil.rmtree(uploads)

from fastapi.testclient import TestClient
from app.main import app
from app.workers.ocr_tasks import run_ocr_task
from app.workers.grading_tasks import run_grading_task

master_answer = (
    'Q1: The writer conveys the essence of time through interpretation and perspective. '
    'Q2a: 4.6 Q2b: 3.33 Q2c: 8883300. '
    'Q3: The flower blooms due to sudden sunshine while lying flat on grass.'
)

result = {}

with TestClient(app) as client:
    with patch('app.api.v1.submissions.run_ocr_task.delay', side_effect=lambda sid: run_ocr_task(sid)), \
         patch('app.workers.grading_tasks.run_grading_task.delay', side_effect=lambda sid: run_grading_task(sid)):

        # 1) Assignment
        a_resp = client.post('/api/v1/assignments/', json={
            'course_id': 'ENG101',
            'title': 'Live E2E Structured Output Run',
            'description': 'Live run with Gemini OCR and grading',
            'max_marks': 10,
            'question_type': 'mixed',
            'has_code_question': False,
        })
        a_resp.raise_for_status()
        assignment = a_resp.json()
        assignment_id = assignment['id']

        # 2) AI rubric generation (real model)
        gen_resp = client.post(f'/api/v1/rubrics/{assignment_id}/generate', json={'master_answer': master_answer})
        gen_resp.raise_for_status()
        rubric = gen_resp.json()
        rubric_id = rubric['id']

        # 3) Approve rubric
        ap_resp = client.post(f'/api/v1/rubrics/{rubric_id}/approve', json={'approved_by': 'instructor-live'})
        ap_resp.raise_for_status()
        approved_rubric = ap_resp.json()

        # 4) Upload submission (real OCR + grading executed synchronously via patched delay)
        img_bytes = Path('../tests/test_subj.jpeg').read_bytes()
        up_resp = client.post(
            f'/api/v1/submissions/{assignment_id}/upload',
            params={'student_id': 'stu-live-1', 'student_name': 'Live Student'},
            files={'file': ('test_subj.jpeg', img_bytes, 'image/jpeg')},
        )
        up_resp.raise_for_status()
        upload = up_resp.json()
        submission_id = upload['submission_id']

        # 5) Fetch submission + grade + audit
        s_resp = client.get(f'/api/v1/submissions/detail/{submission_id}')
        s_resp.raise_for_status()
        submission = s_resp.json()

        g_resp = client.get(f'/api/v1/submissions/{submission_id}/grade')
        g_resp.raise_for_status()
        grade = g_resp.json()

        audit_resp = client.get(f'/api/v1/submissions/{submission_id}/audit')
        audit_resp.raise_for_status()
        audit = audit_resp.json()

        result = {
            'assignment': assignment,
            'generated_rubric': rubric,
            'approved_rubric': approved_rubric,
            'upload': upload,
            'submission': submission,
            'grade': grade,
            'audit_actions': [a.get('action') for a in audit],
        }

out_path = Path('../tests/live_api_e2e_output.json')
out_path.write_text(json.dumps(result, indent=2), encoding='utf-8')

print('SUCCESS')
print('ASSIGNMENT_ID=' + result['assignment']['id'])
print('RUBRIC_ID=' + result['generated_rubric']['id'])
print('SUBMISSION_ID=' + result['upload']['submission_id'])
print('SUBMISSION_STATUS=' + str(result['submission'].get('status')))
print('OCR_ENGINE=' + str((result['submission'].get('ocr_result') or {}).get('engine')))
print('OCR_BLOCK_COUNT=' + str((result['submission'].get('ocr_result') or {}).get('block_count')))
print('TOTAL_SCORE=' + str(result['grade'].get('total_score')))
print('CONSISTENCY_ISSUES=' + str(result['grade'].get('breakdown_json', {}).get('consistency_issues', [])))
print('OUT_FILE=../tests/live_api_e2e_output.json')

from pathlib import Path
import json
from app.services.ocr_service import run_ocr
from app.models import QuestionType

img = Path('../tests/test_subj.jpeg').read_bytes()
result, engine = run_ocr(img, QuestionType.subjective)
print('ENGINE=' + engine)
print('BLOCK_COUNT=' + str(result.get('block_count')))
print('MODEL=' + str(result.get('model')))
print('FIRST_BLOCK=' + json.dumps((result.get('blocks') or [{}])[0], ensure_ascii=False)[:500])

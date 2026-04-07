from pathlib import Path
import os
from google import genai
from google.genai import types

env = {}
for raw in Path('.env').read_text(encoding='utf-8').splitlines():
    line = raw.strip()
    if not line or line.startswith('#') or '=' not in line:
        continue
    k, v = line.split('=', 1)
    env[k.strip()] = v.strip().strip('"').strip("'")
api_key = env.get('GOOGLE_CLOUD_API_KEY','')
model = env.get('DEFAULT_MODEL','gemini-2.5-flash')

candidates = [
    ('sunny-effort-479911-h9','global'),
    ('sunny-effort-479911-h9','us-central1'),
    ('56451059812','global'),
    ('56451059812','us-central1'),
]

for project, location in candidates:
    try:
        client = genai.Client(vertexai=True, project=project, location=location, api_key=api_key, http_options=types.HttpOptions(api_version='v1'))
        r = client.models.generate_content(model=model, contents='Reply exactly: PONG')
        print(f'SUCCESS project={project} location={location} text={(r.text or "").strip()}')
        raise SystemExit(0)
    except Exception as e:
        print(f'FAIL project={project} location={location} err={e}')

raise SystemExit(1)

import os
from pathlib import Path
from google import genai
from google.genai import types

env = {}
for raw in Path('.env').read_text(encoding='utf-8').splitlines():
    line = raw.strip()
    if not line or line.startswith('#') or '=' not in line:
        continue
    k, v = line.split('=', 1)
    env[k.strip()] = v.strip().strip('"').strip("'")

api_key = env.get('GOOGLE_CLOUD_API_KEY', '')
os.environ['GOOGLE_CLOUD_PROJECT'] = '56451059812'
os.environ['GOOGLE_CLOUD_LOCATION'] = 'us-central1'
os.environ['GOOGLE_GENAI_USE_VERTEXAI'] = 'true'

print('Testing SDK mode: vertexai=True + api_key + env project/location')
try:
    client = genai.Client(vertexai=True, api_key=api_key, http_options=types.HttpOptions(api_version='v1'))
    resp = client.models.generate_content(
        model='gemini-2.5-flash',
        contents='Reply in JSON with ping=pong.',
        config=types.GenerateContentConfig(
            response_mime_type='application/json',
            response_schema={
                'type': 'OBJECT',
                'properties': {'ping': {'type': 'STRING'}},
                'required': ['ping']
            }
        )
    )
    print('SUCCESS_TEXT=' + (resp.text or '').strip())
except Exception as e:
    print('ERROR=' + str(e))

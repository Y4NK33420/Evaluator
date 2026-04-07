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

for key in ['GOOGLE_CLOUD_API_KEY', 'GOOGLE_GENAI_USE_VERTEXAI', 'GOOGLE_CLOUD_PROJECT', 'GOOGLE_CLOUD_LOCATION']:
    if env.get(key):
        os.environ[key] = env[key]

model = env.get('DEFAULT_MODEL', 'gemini-2.5-flash')
client = genai.Client(http_options=types.HttpOptions(api_version='v1'))
response = client.models.generate_content(
    model=model,
    contents='Return health check data as JSON. ping must be pong.',
    config=types.GenerateContentConfig(
        response_mime_type='application/json',
        response_schema={
            'type': 'OBJECT',
            'properties': {
                'ping': {'type': 'STRING', 'description': 'Must always be pong'},
                'model_ack': {'type': 'STRING', 'description': 'Short acknowledgement'},
            },
            'required': ['ping', 'model_ack'],
            'propertyOrdering': ['ping', 'model_ack'],
        },
    ),
)
print('MODEL=' + model)
print('RESPONSE_TEXT=' + (response.text or '').strip())

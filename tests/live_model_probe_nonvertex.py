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

# Force non-Vertex Gemini API mode with API key from .env
os.environ['GOOGLE_GENAI_USE_VERTEXAI'] = 'false'
os.environ.pop('GOOGLE_CLOUD_PROJECT', None)
os.environ.pop('GOOGLE_CLOUD_LOCATION', None)
os.environ['GOOGLE_API_KEY'] = env.get('GOOGLE_CLOUD_API_KEY', '')
os.environ['GOOGLE_CLOUD_API_KEY'] = env.get('GOOGLE_CLOUD_API_KEY', '')

client = genai.Client(http_options=types.HttpOptions(api_version='v1alpha'))
response = client.models.generate_content(
    model='gemini-2.5-flash',
    contents='Reply with plain text: PONG',
)
print('RESPONSE_TEXT=' + (response.text or '').strip())

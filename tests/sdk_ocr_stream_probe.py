import os
import base64
from pathlib import Path
from google import genai
from google.genai import types

# Load API key from .env
env = {}
for raw in Path('.env').read_text(encoding='utf-8').splitlines():
    line = raw.strip()
    if not line or line.startswith('#') or '=' not in line:
        continue
    k, v = line.split('=', 1)
    env[k.strip()] = v.strip().strip('"').strip("'")

os.environ['GOOGLE_CLOUD_API_KEY'] = env.get('GOOGLE_CLOUD_API_KEY', '')
os.environ['GOOGLE_GENAI_USE_VERTEXAI'] = 'true'
os.environ['GOOGLE_CLOUD_PROJECT'] = '56451059812'
os.environ['GOOGLE_CLOUD_LOCATION'] = 'us-central1'

img_b64 = base64.b64encode(Path('tests/test_subj.jpeg').read_bytes())

client = genai.Client(vertexai=True, api_key=os.environ.get('GOOGLE_CLOUD_API_KEY'))

msg1_image1 = types.Part.from_bytes(
    data=base64.b64decode(img_b64),
    mime_type='image/jpeg',
)

contents = [
    types.Content(
        role='user',
        parts=[
            msg1_image1,
            types.Part.from_text(text='OCR this image')
        ]
    ),
]

cfg = types.GenerateContentConfig(
    temperature=1,
    top_p=0.95,
    max_output_tokens=8192,
    safety_settings=[
        types.SafetySetting(category='HARM_CATEGORY_HATE_SPEECH', threshold='OFF'),
        types.SafetySetting(category='HARM_CATEGORY_DANGEROUS_CONTENT', threshold='OFF'),
        types.SafetySetting(category='HARM_CATEGORY_SEXUALLY_EXPLICIT', threshold='OFF'),
        types.SafetySetting(category='HARM_CATEGORY_HARASSMENT', threshold='OFF'),
    ],
    response_mime_type='application/json',
    response_schema={
        'type': 'OBJECT',
        'properties': {
            'response': {'type': 'STRING'}
        },
        'required': ['response']
    },
    thinking_config=types.ThinkingConfig(thinking_level='LOW'),
)

text = ''
for chunk in client.models.generate_content_stream(
    model='gemini-3.1-flash-lite-preview',
    contents=contents,
    config=cfg,
):
    text += chunk.text or ''

print(text)

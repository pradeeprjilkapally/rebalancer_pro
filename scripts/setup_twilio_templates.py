"""
One-time setup: creates the three WhatsApp quick-reply Content Templates
needed for the interactive auth flow, then patches .env with the SIDs.

Run once:  python3 scripts/setup_twilio_templates.py
"""
import os, re, sys, json, requests
from requests.auth import HTTPBasicAuth
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()
from twilio.rest import Client

SID   = os.getenv('TWILIO_ACCOUNT_SID', '')
TOKEN = os.getenv('TWILIO_AUTH_TOKEN', '')
AUTH  = HTTPBasicAuth(SID, TOKEN)
API   = 'https://content.twilio.com/v1/Content'
client = Client(SID, TOKEN)

TEMPLATES = [
    {
        'env_key':       'TWILIO_TMPL_AUTH_PING',
        'friendly_name': 'portfolio_auth_ping',
        'type':          'twilio/quick-reply',
        'body':          'Your {{1}} session has expired and the morning review was skipped.\n\nWhat would you like to do?',
        'actions': [
            {'id': 'btn_authenticate', 'title': 'Authenticate'},
            {'id': 'btn_skip',         'title': 'Skip Today'},
        ],
    },
    {
        'env_key':       'TWILIO_TMPL_POST_SKIP',
        'friendly_name': 'portfolio_post_skip',
        'type':          'twilio/quick-reply',
        'body':          "Got it — skipping today's {{1}} review.\n\nWould you like to send me any portfolio queries or instructions to work on?",
        'actions': [
            {'id': 'btn_add_input', 'title': 'Add Input'},
            {'id': 'btn_done',      'title': 'Done'},
        ],
    },
    {
        'env_key':       'TWILIO_TMPL_CONTINUE_DONE',
        'friendly_name': 'portfolio_continue_done',
        'type':          'twilio/quick-reply',
        'body':          'Got it. Anything else you\'d like to work on?',
        'actions': [
            {'id': 'btn_continue', 'title': 'Continue'},
            {'id': 'btn_done',     'title': 'Done'},
        ],
    },
]

env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env')

def patch_env(key: str, value: str):
    """Add or update a key=value line in .env."""
    try:
        content = open(env_path).read()
    except FileNotFoundError:
        content = ''
    pattern = rf'^{re.escape(key)}=.*$'
    new_line = f'{key}={value}'
    if re.search(pattern, content, re.MULTILINE):
        content = re.sub(pattern, new_line, content, flags=re.MULTILINE)
    else:
        content = content.rstrip('\n') + f'\n{new_line}\n'
    with open(env_path, 'w') as f:
        f.write(content)


created, skipped = [], []

# Check for existing templates to avoid duplicates
existing = {t.friendly_name: t.sid for t in client.content.v1.contents.list()}

for tmpl in TEMPLATES:
    name = tmpl['friendly_name']
    if name in existing:
        sid = existing[name]
        print(f'  [skip]   {name} already exists → {sid}')
        skipped.append((tmpl['env_key'], sid))
        patch_env(tmpl['env_key'], sid)
        continue

    payload = {
        'friendly_name': name,
        'language':      'en',
        'types': {
            tmpl['type']: {
                'body':    tmpl['body'],
                'actions': tmpl['actions'],
            }
        },
    }
    r = requests.post(API, auth=AUTH, json=payload)
    r.raise_for_status()
    sid = r.json()['sid']
    print(f'  [create] {name} → {sid}')
    created.append((tmpl['env_key'], sid))
    patch_env(tmpl['env_key'], sid)

print(f'\nDone. {len(created)} created, {len(skipped)} skipped.')
print('SIDs written to .env.')

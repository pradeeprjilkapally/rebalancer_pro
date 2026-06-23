"""
End-to-end interactive auth flow test.

Walks through every state in the WhatsApp conversation:
  1.  Auth ping sent (buttons: Authenticate / Skip Today)
  2.  User taps "Skip Today"  →  post_skip prompt (buttons: Add Input / Done)
  3.  User taps "Add Input"   →  agent asks for free text
  4.  User types a query      →  agent saves note, sends Continue / Done
  5.  User taps "Continue"    →  agent re-prompts
  6.  User types second query →  agent saves, sends Continue / Done
  7.  User taps "Done"        →  loop closed, state reset to idle

Real WhatsApp messages are sent at every outbound step.
Inbound button taps are simulated with valid Twilio signatures.
"""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
from dotenv import load_dotenv
load_dotenv()

from twilio.request_validator import RequestValidator
from agent import conversation as conv
from agent.auth import PENDING_FILE as PAYTM_P
from agent.brokers.zerodha import PENDING_FILE as ZERODHA_P
from agent.whatsapp import send_auth_ping

AUTH_TOKEN  = os.getenv('TWILIO_AUTH_TOKEN', '')
FROM_       = os.getenv('TWILIO_WHATSAPP_FROM', 'whatsapp:+14155238886')
TO_         = os.getenv('TWILIO_WHATSAPP_TO',   'whatsapp:+919885675853')
WEBHOOK     = 'http://localhost:5001/whatsapp'
# Twilio signs against the permanent relay URL, not the tunnel/local URL.
# Use that URL for signature computation so tests match production behaviour.
_RELAY_BASE = os.getenv('WORKERS_RELAY_URL', '').rstrip('/')
SIGN_URL    = f"{_RELAY_BASE}/whatsapp" if _RELAY_BASE else WEBHOOK

PASS = '\033[92m✓\033[0m'
FAIL = '\033[91m✗\033[0m'
results = []

PAUSE = 3   # seconds between steps so WhatsApp messages land visibly


def check(label, condition, detail=''):
    sym = PASS if condition else FAIL
    print(f'  {sym} {label}' + (f'  [{detail}]' if detail else ''))
    results.append((label, condition))


def whatsapp_post(body: str = '', button_payload: str = '') -> requests.Response:
    """POST to /whatsapp simulating a Twilio inbound message.

    Signature is computed against SIGN_URL (the relay URL) — matching what
    Twilio actually signs in production — while the POST itself goes to the
    local webhook directly.
    """
    params = {'Body': body, 'From': TO_, 'To': FROM_}
    if button_payload:
        params['ButtonPayload'] = button_payload
        if not body:
            params['Body'] = button_payload.replace('btn_', '').replace('_', ' ').title()
    sig = RequestValidator(AUTH_TOKEN).compute_signature(SIGN_URL, params)
    return requests.post(WEBHOOK, data=params, headers={'X-Twilio-Signature': sig}, timeout=10)


def reset():
    conv.reset()
    for p in [PAYTM_P, ZERODHA_P]:
        try: os.remove(p)
        except FileNotFoundError: pass


# ============================================================
print('\n' + '='*58)
print(' E2E Test: WhatsApp Interactive Auth Flow')
print('='*58)

# ----------------------------------------------------------------
# Step 0: Setup
# ----------------------------------------------------------------
print('\n[0] Setup — writing sentinels, resetting state...')
reset()
open(PAYTM_P,   'w').write('https://login.paytmmoney.com/merchant-login?apiKey=fa5e00dbc96748699b3d052194308d8c&state=e2e_test')
open(ZERODHA_P, 'w').write('https://kite.zerodha.com/connect/login?api_key=ql1p2d802yzdlzcq&v=3')
check('Paytm sentinel written',   os.path.isfile(PAYTM_P))
check('Zerodha sentinel written', os.path.isfile(ZERODHA_P))
check('State is idle',            conv.get()['mode'] == 'idle')

# ----------------------------------------------------------------
# Step 1: Send auth ping with buttons to WhatsApp
# ----------------------------------------------------------------
print('\n[1] Sending auth ping (Authenticate / Skip Today) to WhatsApp...')
ok = send_auth_ping(['Paytm Money', 'Zerodha'])
check('Auth ping sent', ok)
print(f'  >> Check WhatsApp — you should see buttons: [Authenticate] [Skip Today]')
time.sleep(PAUSE)

# ----------------------------------------------------------------
# Step 2: Simulate "Skip Today" button tap
# ----------------------------------------------------------------
print('\n[2] Simulating "Skip Today" button tap...')
r = whatsapp_post(button_payload='btn_skip')
check('HTTP 200',                   r.status_code == 200)
check('Sentinels cleared',          not os.path.isfile(PAYTM_P) and not os.path.isfile(ZERODHA_P))
check('State = post_skip',          conv.get()['mode'] == 'post_skip')
print(f'  >> WhatsApp: you should see buttons: [Add Input] [Done]')
time.sleep(PAUSE)

# ----------------------------------------------------------------
# Step 3: Simulate "Add Input" button tap
# ----------------------------------------------------------------
print('\n[3] Simulating "Add Input" button tap...')
r = whatsapp_post(button_payload='btn_add_input')
check('HTTP 200',                   r.status_code == 200)
check('State = awaiting_input',     conv.get()['mode'] == 'awaiting_input')
check('Agent asks for query',       'query' in r.text.lower() or 'type' in r.text.lower() or 'send' in r.text.lower())
print(f'  >> WhatsApp: "Go ahead — type your portfolio query or instruction"')
time.sleep(PAUSE)

# ----------------------------------------------------------------
# Step 4: User sends a free-text query
# ----------------------------------------------------------------
print('\n[4] User sends free-text: "Is my SIP allocation diversified enough?"...')
query1 = 'Is my SIP allocation diversified enough?'
r = whatsapp_post(body=query1)
check('HTTP 200',                   r.status_code == 200)
check('State still awaiting_input', conv.get()['mode'] == 'awaiting_input')
check('Agent confirms note saved',  'noted' in r.text.lower() or 'got it' in r.text.lower())

# Verify note was written to disk
notes_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'mydata', 'whatsapp_notes.txt')
note_saved = os.path.isfile(notes_path) and query1 in open(notes_path).read()
check('Note saved to mydata/whatsapp_notes.txt', note_saved)
print(f'  >> WhatsApp: "Got it — noted. Anything else?" with [Continue] [Done]')
time.sleep(PAUSE)

# ----------------------------------------------------------------
# Step 5: Simulate "Continue" — user has another query
# ----------------------------------------------------------------
print('\n[5] Simulating "Continue" button tap...')
r = whatsapp_post(button_payload='btn_continue')
check('HTTP 200',                   r.status_code == 200)
check('State still awaiting_input', conv.get()['mode'] == 'awaiting_input')
print(f'  >> WhatsApp: "Sure — send your next query or instruction"')
time.sleep(PAUSE)

# ----------------------------------------------------------------
# Step 6: User sends a second query
# ----------------------------------------------------------------
print('\n[6] User sends: "Should I increase my mid-cap exposure?"...')
query2 = 'Should I increase my mid-cap exposure?'
r = whatsapp_post(body=query2)
check('HTTP 200',                   r.status_code == 200)
note_saved2 = os.path.isfile(notes_path) and query2 in open(notes_path).read()
check('Second note saved',          note_saved2)
print(f'  >> WhatsApp: [Continue] [Done]')
time.sleep(PAUSE)

# ----------------------------------------------------------------
# Step 7: Simulate "Done" — close the loop
# ----------------------------------------------------------------
print('\n[7] Simulating "Done" button tap...')
r = whatsapp_post(button_payload='btn_done')
check('HTTP 200',                   r.status_code == 200)
check('State reset to idle',        conv.get()['mode'] == 'idle')
check('Closing message returned',   'closed' in r.text.lower() or 'tomorrow' in r.text.lower())
print(f'  >> WhatsApp: "Loop closed. No further reminders today."')
time.sleep(PAUSE)

# ----------------------------------------------------------------
# Step 8: Verify notes file content
# ----------------------------------------------------------------
print('\n[8] Notes file content:')
if os.path.isfile(notes_path):
    print(open(notes_path).read())
else:
    print('  (no notes file found)')

# ----------------------------------------------------------------
# Summary
# ----------------------------------------------------------------
print('='*58)
passed = sum(1 for _, ok in results if ok)
total  = len(results)
print(f'  {passed}/{total} checks passed')
if passed < total:
    print('  Failed:')
    for label, ok in results:
        if not ok:
            print(f'    ✗ {label}')
else:
    print('  All checks passed.')
print('='*58)
sys.exit(0 if passed == total else 1)

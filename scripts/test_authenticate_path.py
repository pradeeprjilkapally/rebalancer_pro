"""
Tests the Authenticate button path and fallback handling.
Complements test_e2e_auth_flow.py which covers the Skip Today path.
"""
import os, sys, requests
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()
from twilio.request_validator import RequestValidator
from agent import conversation as conv
from agent.auth import PENDING_FILE as PAYTM_P
from agent.brokers.zerodha import PENDING_FILE as ZERODHA_P

AUTH_TOKEN = os.getenv('TWILIO_AUTH_TOKEN', '')
FROM_      = os.getenv('TWILIO_WHATSAPP_FROM', '')
TO_        = os.getenv('TWILIO_WHATSAPP_TO', '')
WEBHOOK    = 'http://localhost:5001/whatsapp'
_RELAY     = os.getenv('WORKERS_RELAY_URL', '').rstrip('/')
SIGN_URL   = f"{_RELAY}/whatsapp" if _RELAY else WEBHOOK

PASS = '\033[92m✓\033[0m'
FAIL = '\033[91m✗\033[0m'
results = []

def check(label, ok):
    print(f'  {PASS if ok else FAIL} {label}')
    results.append((label, ok))

def post(body='', btn=''):
    params = {'Body': body or btn.replace('btn_', '').replace('_', ' ').title(), 'From': TO_, 'To': FROM_}
    if btn:
        params['ButtonPayload'] = btn
    sig = RequestValidator(AUTH_TOKEN).compute_signature(SIGN_URL, params)
    return requests.post(WEBHOOK, data=params, headers={'X-Twilio-Signature': sig}, timeout=10)


print('\n' + '='*58)
print(' Test: Authenticate path + edge cases')
print('='*58)

# ---- Authenticate path ----
print('\n[1] Authenticate with both brokers pending...')
conv.reset()
open(PAYTM_P, 'w').write('https://login.paytmmoney.com/merchant-login?test=1')
open(ZERODHA_P, 'w').write('https://kite.zerodha.com/connect/login?test=1')

r = post(btn='btn_authenticate')
check('HTTP 200', r.status_code == 200)
check('Mentions login link', 'login' in r.text.lower() or 'link' in r.text.lower())
check('State = auth_pending', conv.get()['mode'] == 'auth_pending')

# ---- Authenticate with no pending brokers ----
print('\n[2] Authenticate when sessions already active (no sentinels)...')
conv.reset()
for p in [PAYTM_P, ZERODHA_P]:
    try: os.remove(p)
    except FileNotFoundError: pass

r = post(btn='btn_authenticate')
check('HTTP 200', r.status_code == 200)
check('Says no pending auth', 'no pending' in r.text.lower() or 'active' in r.text.lower() or 'sessions' in r.text.lower())
check('State reset to idle', conv.get()['mode'] == 'idle')

# ---- Done with no active loop ----
print('\n[3] Done tap with no active loop...')
conv.reset()
r = post(btn='btn_done')
check('HTTP 200', r.status_code == 200)
check('State is idle', conv.get()['mode'] == 'idle')

# ---- Unrecognised text while idle ----
print('\n[4] Random text while idle...')
conv.reset()
r = post(body='what is the weather today?')
check('HTTP 200', r.status_code == 200)
check('Returns helpful fallback', "didn't catch" in r.text.lower() or 'add input' in r.text.lower())

# ---- Free text accepted while in awaiting_input ----
print('\n[5] Free text while awaiting_input...')
conv.set_mode('awaiting_input')
r = post(body='Should I rebalance my SIP now?')
check('HTTP 200', r.status_code == 200)
check('Note confirmed', 'noted' in r.text.lower() or 'got it' in r.text.lower())
check('State still awaiting_input', conv.get()['mode'] == 'awaiting_input')

conv.reset()

# ---- Summary ----
print('\n' + '='*58)
passed = sum(1 for _, ok in results if ok)
total = len(results)
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

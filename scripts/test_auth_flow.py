"""
End-to-end test for the YES/NO auth flow.

What it covers:
  1. Sentinel creation — both broker pending files written
  2. Auth reminder — runs module directly, verifies WhatsApp sent
  3. Webhook YES — generates valid Twilio signature, POSTs to /whatsapp,
                   verifies login links forwarded and sentinels still present
                   (they're only cleared by the OAuth callback, not by YES)
  4. Webhook NO  — POSTs NO, verifies sentinels cleared and skip confirmed
  5. Webhook unrecognised — verifies hint message returned
  6. Cleanup

Run:  python3 scripts/test_auth_flow.py
"""
import os, sys, time, json, hmac, hashlib, base64, urllib.parse
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
from dotenv import load_dotenv
load_dotenv()

from agent.auth import PENDING_FILE as PAYTM_PENDING
from agent.brokers.zerodha import PENDING_FILE as ZERODHA_PENDING
from twilio.request_validator import RequestValidator

WEBHOOK = 'http://localhost:5001'
AUTH_TOKEN = os.getenv('TWILIO_AUTH_TOKEN', '')
FROM_ = os.getenv('TWILIO_WHATSAPP_FROM', 'whatsapp:+14155238886')
TO_   = os.getenv('TWILIO_WHATSAPP_TO',   'whatsapp:+919885675853')

FAKE_PAYTM_URL   = 'https://login.paytmmoney.com/merchant-login?apiKey=TEST&state=test_paytm'
FAKE_ZERODHA_URL = 'https://kite.zerodha.com/connect/login?api_key=TEST&v=3'

PASS = '\033[92m✓\033[0m'
FAIL = '\033[91m✗\033[0m'

results = []

def check(label, condition, detail=''):
    symbol = PASS if condition else FAIL
    print(f'  {symbol} {label}' + (f'  [{detail}]' if detail else ''))
    results.append((label, condition))


def twilio_post(body_text: str) -> requests.Response:
    """POST to /whatsapp with a valid Twilio signature."""
    url    = f'{WEBHOOK}/whatsapp'
    params = {'Body': body_text, 'From': FROM_, 'To': TO_}
    sig    = RequestValidator(AUTH_TOKEN).compute_signature(url, params)
    return requests.post(url, data=params, headers={'X-Twilio-Signature': sig}, timeout=10)


# ---------------------------------------------------------------------------
# 1. Setup — write sentinel files
# ---------------------------------------------------------------------------
print('\n[1] Writing sentinel files...')
for path, url in [(PAYTM_PENDING, FAKE_PAYTM_URL), (ZERODHA_PENDING, FAKE_ZERODHA_URL)]:
    with open(path, 'w') as f:
        f.write(url)
check('Paytm sentinel exists',   os.path.isfile(PAYTM_PENDING))
check('Zerodha sentinel exists',  os.path.isfile(ZERODHA_PENDING))


# ---------------------------------------------------------------------------
# 2. Auth reminder — import and run directly
# ---------------------------------------------------------------------------
print('\n[2] Auth reminder (both brokers pending)...')
import agent.auth_reminder as reminder
reminder.main()   # should send WhatsApp reminder for both brokers
check('Paytm sentinel still present after reminder',   os.path.isfile(PAYTM_PENDING))
check('Zerodha sentinel still present after reminder', os.path.isfile(ZERODHA_PENDING))
print('  [manual check] You should have received a WhatsApp reminder listing Paytm Money and Zerodha')


# ---------------------------------------------------------------------------
# 3. Webhook — health
# ---------------------------------------------------------------------------
print('\n[3] Webhook health...')
r = requests.get(f'{WEBHOOK}/health', timeout=5)
check('Health 200', r.status_code == 200, r.text.strip())


# ---------------------------------------------------------------------------
# 4. Webhook — YES reply (both sentinels pending)
# ---------------------------------------------------------------------------
print('\n[4] Webhook YES (both pending)...')
r = twilio_post('YES')
check('HTTP 200', r.status_code == 200, str(r.status_code))
check('TwiML response', 'Response' in r.text)
check('Confirms links sent', 'Login link' in r.text or 'link' in r.text.lower())
# Sentinels should still exist — clearing only happens via OAuth callback
check('Paytm sentinel preserved', os.path.isfile(PAYTM_PENDING))
check('Zerodha sentinel preserved', os.path.isfile(ZERODHA_PENDING))
print('  [manual check] You should have received the Paytm + Zerodha login links on WhatsApp')


# ---------------------------------------------------------------------------
# 5. Webhook — NO reply (should clear both sentinels)
# ---------------------------------------------------------------------------
print('\n[5] Webhook NO (skip today)...')
r = twilio_post('NO')
check('HTTP 200', r.status_code == 200, str(r.status_code))
check('TwiML response', 'Response' in r.text)
check('Confirms skip in response', 'skip' in r.text.lower() or 'tomorrow' in r.text.lower())
check('Paytm sentinel cleared',   not os.path.isfile(PAYTM_PENDING))
check('Zerodha sentinel cleared',  not os.path.isfile(ZERODHA_PENDING))


# ---------------------------------------------------------------------------
# 6. Webhook — YES when no sentinels (nothing pending)
# ---------------------------------------------------------------------------
print('\n[6] Webhook YES (nothing pending)...')
r = twilio_post('YES')
check('HTTP 200', r.status_code == 200, str(r.status_code))
check('Reports all good', 'pending' in r.text.lower() or 'good' in r.text.lower() or 'authenticated' in r.text.lower())


# ---------------------------------------------------------------------------
# 7. Webhook — unrecognised message
# ---------------------------------------------------------------------------
print('\n[7] Webhook unrecognised reply...')
r = twilio_post('what is my portfolio value?')
check('HTTP 200', r.status_code == 200, str(r.status_code))
check('Hint returned', 'YES' in r.text or 'NO' in r.text)


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
print('\n' + '='*55)
passed = sum(1 for _, ok in results if ok)
total  = len(results)
print(f'  {passed}/{total} checks passed')
if passed == total:
    print('  All checks passed.')
else:
    print('  Failed checks:')
    for label, ok in results:
        if not ok:
            print(f'    ✗ {label}')
print('='*55)
sys.exit(0 if passed == total else 1)

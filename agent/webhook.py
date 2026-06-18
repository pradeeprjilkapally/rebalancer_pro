"""
Inbound webhook server — two routes:

  POST /whatsapp   — receives Twilio WhatsApp messages; fallback if user replies
                     with token manually (Twilio signature validated)

  GET  /callback   — Zerodha OAuth redirect landing page; captures request_token
                     automatically from the redirect URL after Zerodha login

  GET  /health     — liveness probe

Run standalone:   python -m agent.webhook
Kept alive by:    com.pradeep.zerodha-webhook launchd plist
Exposed via:      localhost.run tunnel (com.pradeep.zerodha-tunnel plist)

One-time setup:
  1. Register ~/.ssh/portfolio_tunnel.pub at https://admin.localhost.run/
     to get a permanent subdomain (e.g. abc123.lhr.life)
  2. Set TUNNEL_BASE_URL=https://abc123.lhr.life in .env
  3. In Zerodha developer app set redirect URL to https://abc123.lhr.life/callback
  4. In Twilio sandbox settings set "When a message comes in" to
     https://abc123.lhr.life/whatsapp
"""
import os
import re
import sys

from dotenv import load_dotenv
from flask import Flask, Response, redirect, render_template_string, request
from twilio.request_validator import RequestValidator
from twilio.twiml.messaging_response import MessagingResponse

load_dotenv()

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.crypto import encrypt_token

app = Flask(__name__)

_ENC_TOKEN_FILE = os.path.join(
    os.path.dirname(__file__), 'brokers', '.zerodha_request_token.enc'
)

# Zerodha request_tokens are 32-char alphanumeric strings
_TOKEN_RE = re.compile(r'\b([A-Za-z0-9]{32})\b')

_CALLBACK_SUCCESS_HTML = """
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>Zerodha Auth</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>body{font-family:sans-serif;text-align:center;padding:40px;background:#f5f5f5}
.box{background:#fff;border-radius:12px;padding:30px;max-width:400px;margin:auto;box-shadow:0 2px 8px rgba(0,0,0,.1)}
.ok{color:#2e7d32;font-size:48px}.msg{font-size:18px;margin-top:16px;color:#333}
.sub{font-size:14px;color:#666;margin-top:8px}</style></head>
<body><div class="box">
<div class="ok">&#10003;</div>
<div class="msg">Authentication successful!</div>
<div class="sub">Your Zerodha holdings will appear in the next daily review. You can close this tab.</div>
</div></body></html>
"""

_CALLBACK_ERROR_HTML = """
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>Zerodha Auth</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>body{font-family:sans-serif;text-align:center;padding:40px;background:#f5f5f5}
.box{background:#fff;border-radius:12px;padding:30px;max-width:400px;margin:auto;box-shadow:0 2px 8px rgba(0,0,0,.1)}
.err{color:#c62828;font-size:48px}.msg{font-size:18px;margin-top:16px;color:#333}
.sub{font-size:14px;color:#666;margin-top:8px}</style></head>
<body><div class="box">
<div class="err">&#10007;</div>
<div class="msg">{{ error }}</div>
<div class="sub">Please try logging in again from the WhatsApp link.</div>
</div></body></html>
"""


def _save_encrypted_token(raw_token: str):
    encrypted = encrypt_token(raw_token)
    os.makedirs(os.path.dirname(_ENC_TOKEN_FILE), exist_ok=True)
    with open(_ENC_TOKEN_FILE, 'wb') as fh:
        fh.write(encrypted)


def _validate_twilio(req) -> bool:
    auth_token = os.getenv('TWILIO_AUTH_TOKEN', '')
    signature  = req.headers.get('X-Twilio-Signature', '')
    validator  = RequestValidator(auth_token)
    return validator.validate(req.url, req.form, signature)


# ---------------------------------------------------------------------------
# Route 1: Zerodha OAuth callback (automatic — no manual token copying needed)
# ---------------------------------------------------------------------------

@app.route('/callback', methods=['GET'])
def zerodha_callback():
    status       = request.args.get('status', '')
    action       = request.args.get('action', '')
    raw_token    = request.args.get('request_token', '')

    if status != 'success' or action != 'login' or not raw_token:
        error = request.args.get('message', 'Login failed or was cancelled.')
        return render_template_string(_CALLBACK_ERROR_HTML, error=error), 400

    if not _TOKEN_RE.fullmatch(raw_token):
        return render_template_string(
            _CALLBACK_ERROR_HTML, error='Unexpected token format — please retry.'
        ), 400

    try:
        _save_encrypted_token(raw_token)
        del raw_token   # minimise in-memory exposure
        return render_template_string(_CALLBACK_SUCCESS_HTML), 200
    except Exception:
        return render_template_string(
            _CALLBACK_ERROR_HTML, error='Could not save token. Please retry.'
        ), 500


# ---------------------------------------------------------------------------
# Route 2: Twilio WhatsApp inbound (fallback — manual token reply)
# ---------------------------------------------------------------------------

@app.route('/whatsapp', methods=['POST'])
def whatsapp_inbound():
    if not _validate_twilio(request):
        return Response('Forbidden', status=403)

    body  = request.form.get('Body', '').strip()
    match = _TOKEN_RE.search(body)
    resp  = MessagingResponse()

    if not match:
        resp.message(
            "Received your message, but couldn't find a 32-character Zerodha token.\n"
            "Please reply with just the token from the redirect URL."
        )
        return str(resp), 200, {'Content-Type': 'text/xml'}

    raw_token = match.group(1)

    try:
        _save_encrypted_token(raw_token)
        del raw_token
        resp.message(
            "Zerodha token received and secured.\n"
            "Your holdings will appear in the next daily review."
        )
    except Exception:
        resp.message("Failed to save token — please try again.")

    return str(resp), 200, {'Content-Type': 'text/xml'}


# ---------------------------------------------------------------------------
# Route 3: Health probe
# ---------------------------------------------------------------------------

@app.route('/health', methods=['GET'])
def health():
    return {'status': 'ok'}, 200


if __name__ == '__main__':
    port = int(os.getenv('WEBHOOK_PORT', 5001))
    app.run(host='0.0.0.0', port=port, debug=False)

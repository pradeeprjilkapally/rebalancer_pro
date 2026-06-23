import json
import os

try:
    from twilio.rest import Client as TwilioClient
    TWILIO_AVAILABLE = True
except ImportError:
    TWILIO_AVAILABLE = False


# ---------------------------------------------------------------------------
# Core send helpers
# ---------------------------------------------------------------------------

def _creds() -> tuple[str, str, str, str] | None:
    sid   = os.getenv('TWILIO_ACCOUNT_SID', '').strip()
    token = os.getenv('TWILIO_AUTH_TOKEN', '').strip()
    from_  = os.getenv('TWILIO_WHATSAPP_FROM', '').strip()
    to_    = os.getenv('TWILIO_WHATSAPP_TO', '').strip()
    return (sid, token, from_, to_) if all([sid, token, from_, to_]) else None


def send_whatsapp(message: str) -> bool:
    """Send a plain-text WhatsApp message. Returns True on success."""
    if not TWILIO_AVAILABLE:
        _fallback_print(message)
        return False
    creds = _creds()
    if not creds:
        print("  [WhatsApp] Twilio credentials missing — printing to console.")
        _fallback_print(message)
        return False
    sid, token, from_, to_ = creds
    try:
        TwilioClient(sid, token).messages.create(body=message, from_=from_, to=to_)
        print(f"  [WhatsApp] Message sent to {to_}")
        return True
    except Exception as e:
        print(f"  [WhatsApp] Send failed: {e}")
        _fallback_print(message)
        return False


def send_interactive(content_sid: str, variables: dict | None = None) -> bool:
    """
    Send a WhatsApp message using a Twilio Content Template (quick-reply buttons).
    Falls back to plain text if Content SID is not set.
    """
    if not TWILIO_AVAILABLE:
        return False
    creds = _creds()
    if not creds:
        return False
    sid, token, from_, to_ = creds
    try:
        kwargs = dict(from_=from_, to=to_, content_sid=content_sid)
        if variables:
            kwargs['content_variables'] = json.dumps(variables)
        TwilioClient(sid, token).messages.create(**kwargs)
        print(f"  [WhatsApp] Interactive message sent to {to_}")
        return True
    except Exception as e:
        print(f"  [WhatsApp] Interactive send failed: {e}")
        return False


def _fallback_print(message: str):
    print("\n" + "="*60)
    print("PORTFOLIO AGENT (WhatsApp fallback — console output)")
    print("="*60)
    print(message)
    print("="*60 + "\n")


# ---------------------------------------------------------------------------
# Interactive auth flow messages
# ---------------------------------------------------------------------------

def send_auth_ping(brokers: list[str]) -> bool:
    """
    Auth-required notification with [Authenticate] [Skip Today] buttons.
    `brokers` = ['Paytm Money'] or ['Zerodha'] or ['Paytm Money', 'Zerodha']
    """
    broker_str = ' and '.join(brokers)
    tmpl_sid   = os.getenv('TWILIO_TMPL_AUTH_PING', '')
    if tmpl_sid:
        return send_interactive(tmpl_sid, {'1': broker_str})
    # Fallback: plain text
    return send_whatsapp(
        f"*{broker_str} — Login Required*\n\n"
        f"Your session has expired and the morning review was skipped.\n\n"
        f"Reply *Authenticate* to get the login link, or *Skip Today* to skip."
    )


def send_post_skip_prompt(brokers: list[str]) -> bool:
    """
    After user skips: offer [Add Input] [Done] buttons.
    """
    broker_str = ' and '.join(brokers)
    tmpl_sid   = os.getenv('TWILIO_TMPL_POST_SKIP', '')
    if tmpl_sid:
        return send_interactive(tmpl_sid, {'1': broker_str})
    return send_whatsapp(
        f"Understood. Skipping today's {broker_str} portfolio review.\n\n"
        f"Would you like to send me any portfolio queries or instructions to work on?\n\n"
        f"Reply *Add Input* to continue, or *Done* to close."
    )


def send_continue_or_done_prompt() -> bool:
    """After processing a user input: offer [Continue] [Done] buttons."""
    tmpl_sid = os.getenv('TWILIO_TMPL_CONTINUE_DONE', '')
    if tmpl_sid:
        return send_interactive(tmpl_sid)
    return send_whatsapp(
        "Got it. Anything else you'd like to work on?\n\n"
        "Reply *Continue* to add more, or *Done* to close."
    )


def send_auth_links(paytm_url: str | None, zerodha_url: str | None) -> bool:
    """Send login URLs after user tapped Authenticate — one message per broker."""
    ok = True
    if paytm_url:
        ok = send_whatsapp(
            f"*Paytm Money — Login Link*\n\n{paytm_url}\n\n"
            "Tap to log in. You'll be redirected automatically."
        ) and ok
    if zerodha_url:
        ok = send_whatsapp(
            f"*Zerodha — Login Link*\n\n{zerodha_url}\n\n"
            "Tap to log in. You'll be redirected automatically."
        ) and ok
    return ok


def send_auth_reminder(brokers: list[str]) -> bool:
    """9 AM nudge — reuses the auth_ping template."""
    return send_auth_ping(brokers)


# ---------------------------------------------------------------------------
# Daily portfolio review formatter (plain text — no buttons needed)
# ---------------------------------------------------------------------------

def format_daily_message(snapshot: dict, suggestions: list, fire: dict) -> str:
    holdings = snapshot['holdings']
    lines = [
        "*Paytm Money — Daily Portfolio Review*",
        f"Total: ₹{snapshot['total_portfolio']:,.0f}  |  Cash: ₹{snapshot['available_cash']:,.0f}",
        "", "*Holdings:*",
    ]
    for h in holdings:
        pnl_sign = "+" if h['unrealised_pnl'] >= 0 else ""
        lines.append(
            f"• {h['name']}: {h['quantity']:.0f} units @ ₹{h['ltp']:,.2f}"
            f"  ({pnl_sign}{h['unrealised_pnl']:,.0f})  [{h['allocation_pct']:.1f}%]"
        )
    lines += [
        "", "*FIRE Progress:*",
        f"Target: ₹{fire['target']:,.0f}",
        f"Current: ₹{fire['current']:,.0f}  ({fire['progress_pct']:.1f}% complete)",
        f"Gap: ₹{fire['gap']:,.0f}",
        f"Est. years to FIRE: {fire['years_to_fire']:.1f} yrs",
    ]
    if suggestions:
        lines += ["", "*Rebalancing Suggestions:*"]
        for s in suggestions[:3]:
            lines.append(f"• {s['action']} {s['quantity']} x {s['name']} (~₹{s['estimated_value']:,.0f})")
            lines.append(f"  _{s['reason']}_")
    else:
        lines += ["", "*No rebalancing needed today.*"]
    lines += ["", "_Reply to authorize any trade._"]
    return "\n".join(lines)

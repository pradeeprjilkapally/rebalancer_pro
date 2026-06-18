import os
from typing import Optional

try:
    from twilio.rest import Client as TwilioClient
    TWILIO_AVAILABLE = True
except ImportError:
    TWILIO_AVAILABLE = False


def send_whatsapp(message: str) -> bool:
    """Send a WhatsApp message via Twilio. Returns True on success."""
    if not TWILIO_AVAILABLE:
        print("  [WhatsApp] twilio package not installed. Run: pip install twilio")
        _fallback_print(message)
        return False

    sid   = os.getenv('TWILIO_ACCOUNT_SID', '').strip()
    token = os.getenv('TWILIO_AUTH_TOKEN', '').strip()
    from_ = os.getenv('TWILIO_WHATSAPP_FROM', '').strip()   # e.g. whatsapp:+14155238886
    to_   = os.getenv('TWILIO_WHATSAPP_TO', '').strip()     # e.g. whatsapp:+919XXXXXXXXX

    if not all([sid, token, from_, to_]):
        print("  [WhatsApp] Twilio credentials not set in .env — printing to console instead.")
        _fallback_print(message)
        return False

    try:
        client = TwilioClient(sid, token)
        client.messages.create(body=message, from_=from_, to=to_)
        print(f"  [WhatsApp] Message sent to {to_}")
        return True
    except Exception as e:
        print(f"  [WhatsApp] Send failed: {e}")
        _fallback_print(message)
        return False


def _fallback_print(message: str):
    print("\n" + "="*60)
    print("PORTFOLIO DAILY REVIEW (WhatsApp fallback — console output)")
    print("="*60)
    print(message)
    print("="*60 + "\n")


def send_zerodha_auth_required(login_url: str) -> bool:
    """Send a WhatsApp message asking the user to re-authenticate Zerodha."""
    message = (
        "*Zerodha Login Required*\n\n"
        "Your Zerodha session has expired (tokens reset daily around 6 AM).\n\n"
        "Tap the link below, log in with your Zerodha credentials, "
        "then copy the *request_token* from the redirect URL and reply here:\n\n"
        f"{login_url}\n\n"
        "_The next daily review will include your Zerodha holdings once authenticated._"
    )
    return send_whatsapp(message)


def format_daily_message(snapshot: dict, suggestions: list, fire: dict) -> str:
    """Format a concise WhatsApp-friendly daily review message."""
    holdings = snapshot['holdings']
    lines = []

    lines.append("*Paytm Money — Daily Portfolio Review*")
    lines.append(f"Total: ₹{snapshot['total_portfolio']:,.0f}  |  Cash: ₹{snapshot['available_cash']:,.0f}")
    lines.append("")

    lines.append("*Holdings:*")
    for h in holdings:
        pnl_sign = "+" if h['unrealised_pnl'] >= 0 else ""
        lines.append(
            f"• {h['name']}: {h['quantity']:.0f} units @ ₹{h['ltp']:,.2f}"
            f"  ({pnl_sign}{h['unrealised_pnl']:,.0f})  [{h['allocation_pct']:.1f}%]"
        )

    lines.append("")
    lines.append(f"*FIRE Progress:*")
    lines.append(f"Target: ₹{fire['target']:,.0f}")
    lines.append(f"Current: ₹{fire['current']:,.0f}  ({fire['progress_pct']:.1f}% complete)")
    lines.append(f"Gap: ₹{fire['gap']:,.0f}")
    lines.append(f"Est. years to FIRE: {fire['years_to_fire']:.1f} yrs")

    if suggestions:
        lines.append("")
        lines.append("*Rebalancing Suggestions:*")
        for s in suggestions[:3]:  # cap at 3 for WhatsApp readability
            lines.append(f"• {s['action']} {s['quantity']} x {s['name']} (~₹{s['estimated_value']:,.0f})")
            lines.append(f"  _{s['reason']}_")
    else:
        lines.append("")
        lines.append("*No rebalancing needed today.*")

    lines.append("")
    lines.append("_Reply to authorize any trade._")

    return "\n".join(lines)

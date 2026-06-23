"""
WhatsApp conversation state machine.

States
------
idle           No active loop.
auth_pending   Auth ping sent; waiting for Authenticate / Skip Today.
post_skip      User skipped; offered Add Input / Done.
awaiting_input User tapped Add Input; waiting for free-text query.

State is persisted to a JSON file so it survives webhook restarts.
"""
import json
import os
from datetime import datetime

_STATE_FILE  = os.path.join(os.path.dirname(__file__), '.whatsapp_state.json')
_NOTES_FILE  = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'mydata', 'whatsapp_notes.txt')


def get() -> dict:
    try:
        with open(_STATE_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {'mode': 'idle'}


def set_mode(mode: str, **extra):
    state = {'mode': mode, 'updated': datetime.now().isoformat(), **extra}
    with open(_STATE_FILE, 'w') as f:
        json.dump(state, f)


def reset():
    set_mode('idle')


def append_note(text: str):
    """Persist a user-sent query/instruction with a timestamp."""
    os.makedirs(os.path.dirname(_NOTES_FILE), exist_ok=True)
    with open(_NOTES_FILE, 'a') as f:
        f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] {text}\n")

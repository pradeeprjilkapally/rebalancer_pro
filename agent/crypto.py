"""
Token encryption helpers.
Fernet symmetric encryption, key derived from WEBHOOK_ENCRYPTION_KEY via PBKDF2.
"""
import base64
import os

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

_SALT = b'zerodha_token_salt_v1'
_ITERATIONS = 480_000


def _fernet() -> Fernet:
    key_material = os.getenv('WEBHOOK_ENCRYPTION_KEY', '').encode()
    if not key_material:
        raise EnvironmentError("WEBHOOK_ENCRYPTION_KEY not set in .env")
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=_SALT,
        iterations=_ITERATIONS,
    )
    key = base64.urlsafe_b64encode(kdf.derive(key_material))
    return Fernet(key)


def encrypt_token(token: str) -> bytes:
    return _fernet().encrypt(token.encode())


def decrypt_token(ciphertext: bytes) -> str:
    return _fernet().decrypt(ciphertext).decode()


# ---------------------------------------------------------------------------
# Generic helpers for encrypting structured data at rest (portfolio snapshots,
# token caches). Same Fernet key as token encryption.
# ---------------------------------------------------------------------------
import json as _json


def encrypt_json(obj) -> bytes:
    """Serialise obj to JSON and return Fernet ciphertext bytes."""
    return _fernet().encrypt(_json.dumps(obj, default=str).encode())


def decrypt_json(ciphertext: bytes):
    """Decrypt Fernet ciphertext bytes and parse JSON."""
    return _json.loads(_fernet().decrypt(ciphertext).decode())


def write_encrypted(path: str, obj) -> None:
    """Write obj as an encrypted blob to path (0600 perms)."""
    blob = encrypt_json(obj)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, blob)
    finally:
        os.close(fd)


def read_encrypted(path: str):
    """Read and decrypt an encrypted blob written by write_encrypted."""
    with open(path, 'rb') as f:
        return decrypt_json(f.read())

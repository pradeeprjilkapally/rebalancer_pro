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

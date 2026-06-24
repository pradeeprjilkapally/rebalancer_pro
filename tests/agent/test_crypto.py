"""Encryption-at-rest round-trips for agent.crypto."""
import os

import pytest

from agent import crypto


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setenv('WEBHOOK_ENCRYPTION_KEY', 'unit-test-key-do-not-use-in-prod')


def test_token_roundtrip():
    ct = crypto.encrypt_token('secret-access-token')
    assert ct != b'secret-access-token'           # actually encrypted
    assert crypto.decrypt_token(ct) == 'secret-access-token'


def test_json_roundtrip():
    obj = {'a': 1, 'b': [1, 2, 3], 'nested': {'x': 'y'}}
    assert crypto.decrypt_json(crypto.encrypt_json(obj)) == obj


def test_file_roundtrip_is_encrypted_and_0600(tmp_path):
    target = tmp_path / 'snapshot.json.enc'
    obj = {'holdings': [{'name': 'GOLDBEES', 'value': 53532}]}
    crypto.write_encrypted(str(target), obj)

    raw = target.read_bytes()
    assert b'GOLDBEES' not in raw                  # plaintext not on disk
    if os.name != 'nt':                            # POSIX file modes only; Windows has no 0o600
        assert (target.stat().st_mode & 0o777) == 0o600
    assert crypto.read_encrypted(str(target)) == obj


def test_wrong_key_cannot_decrypt(tmp_path, monkeypatch):
    target = tmp_path / 'd.enc'
    crypto.write_encrypted(str(target), {'x': 1})
    monkeypatch.setenv('WEBHOOK_ENCRYPTION_KEY', 'a-completely-different-key-value')
    with pytest.raises(Exception):
        crypto.read_encrypted(str(target))


def test_missing_key_raises(monkeypatch):
    monkeypatch.delenv('WEBHOOK_ENCRYPTION_KEY', raising=False)
    with pytest.raises(EnvironmentError):
        crypto.encrypt_token('x')

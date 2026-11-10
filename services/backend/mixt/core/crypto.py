"""Field-level encryption (AES-256-GCM) with a key ring for rotation.

Ciphertext layout: 12-byte nonce || AES-GCM ciphertext+tag. The ``aad`` (associated data)
binds a ciphertext to its record and field, so a value copied onto another row fails to decrypt.
In production the key ring is supplied from a secrets manager/KMS; keys never live in the repo.
"""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from mixt.core.config import get_config

_NONCE_BYTES = 12


class DecryptionError(Exception):
    pass


@dataclass(frozen=True)
class EncryptedValue:
    ciphertext: bytes
    key_id: str


def _key(key_id: str) -> bytes:
    keys = get_config().encryption_keys
    if key_id not in keys:
        raise DecryptionError(f"unknown encryption key id {key_id!r}")
    return base64.b64decode(keys[key_id])


def encrypt(plaintext: bytes, aad: bytes) -> EncryptedValue:
    key_id = get_config().active_encryption_key_id
    nonce = os.urandom(_NONCE_BYTES)
    ciphertext = AESGCM(_key(key_id)).encrypt(nonce, plaintext, aad)
    return EncryptedValue(ciphertext=nonce + ciphertext, key_id=key_id)


def decrypt(value: EncryptedValue, aad: bytes) -> bytes:
    nonce, body = value.ciphertext[:_NONCE_BYTES], value.ciphertext[_NONCE_BYTES:]
    try:
        return AESGCM(_key(value.key_id)).decrypt(nonce, body, aad)
    except InvalidTag as exc:
        raise DecryptionError("ciphertext failed authentication") from exc


def encrypt_text(plaintext: str, aad: str) -> EncryptedValue:
    return encrypt(plaintext.encode("utf-8"), aad.encode("utf-8"))


def decrypt_text(value: EncryptedValue, aad: str) -> str:
    return decrypt(value, aad.encode("utf-8")).decode("utf-8")

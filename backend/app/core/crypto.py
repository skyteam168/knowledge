"""Symmetric encryption of stored secrets (directory source credentials)."""

import base64
import hashlib
import json
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from app.core.exceptions import AppError


def _fernet(secret: str) -> Fernet:
    # Any configured string works: it is stretched into a 32-byte Fernet key.
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
    return Fernet(key)


def encrypt_json(secret: str, data: dict[str, Any]) -> str:
    raw = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode()
    return _fernet(secret).encrypt(raw).decode()


def decrypt_json(secret: str, token: str) -> dict[str, Any]:
    try:
        data = json.loads(_fernet(secret).decrypt(token.encode()))
    except InvalidToken as exc:
        raise AppError(
            "Stored credentials cannot be decrypted (DIRECTORY_SECRET_KEY changed?)",
            code="DIRECTORY_SECRET_INVALID",
        ) from exc
    if not isinstance(data, dict):
        raise AppError("Stored credentials are malformed", code="DIRECTORY_SECRET_INVALID")
    return data

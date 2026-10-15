import hashlib
import hmac
import secrets

KEY_PREFIX = "ekb_sk_"
DISPLAY_CHARS = 14


def generate_secret() -> str:
    return KEY_PREFIX + secrets.token_urlsafe(32)


def hash_secret(secret: str, pepper: str) -> str:
    return hmac.new(pepper.encode(), secret.encode(), hashlib.sha256).hexdigest()


def display_prefix(secret: str) -> str:
    return secret[:DISPLAY_CHARS]


def looks_like_key(value: str) -> bool:
    return value.startswith(KEY_PREFIX) and 20 <= len(value) <= 200

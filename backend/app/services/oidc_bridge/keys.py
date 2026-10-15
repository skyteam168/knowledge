import base64
import hashlib
import json
from functools import lru_cache
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from app.core.cache import KeyValueCache
from app.core.config import Settings
from app.core.exceptions import AppError

DEV_KEY_CACHE_KEY = "oidc:bridge:dev_signing_key"


class SigningKeyError(AppError):
    status_code = 500
    code = "OIDC_BRIDGE_KEY_INVALID"
    message = "OIDC bridge signing key is invalid"


class SigningKey:
    def __init__(self, private_key: rsa.RSAPrivateKey) -> None:
        self.private_key = private_key
        public_der = private_key.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
        )
        digest = hashlib.sha256(public_der).digest()[:12]
        self.kid = base64.urlsafe_b64encode(digest).decode().rstrip("=")

    def jwk(self) -> dict[str, Any]:
        jwk: dict[str, Any] = json.loads(RSAAlgorithm.to_jwk(self.private_key.public_key()))
        jwk.update({"kid": self.kid, "use": "sig", "alg": "RS256"})
        return jwk


def generate_pem() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()


@lru_cache(maxsize=4)
def _parse(pem: str) -> SigningKey:
    try:
        key = serialization.load_pem_private_key(pem.encode(), password=None)
    except (ValueError, TypeError) as exc:
        raise SigningKeyError(detail="OIDC_BRIDGE_SIGNING_KEY is not a PEM private key") from exc
    if not isinstance(key, rsa.RSAPrivateKey):
        raise SigningKeyError(detail="OIDC_BRIDGE_SIGNING_KEY must be an RSA key")
    return SigningKey(key)


async def load_signing_key(settings: Settings, cache: KeyValueCache) -> SigningKey:
    """Configured key, or (outside prod) one generated once and shared through Redis."""
    if settings.oidc_bridge_signing_key:
        # Env files often carry the PEM on one line with literal "\n".
        return _parse(settings.oidc_bridge_signing_key.replace("\\n", "\n").strip())
    if settings.app_env == "prod":
        raise SigningKeyError(detail="OIDC_BRIDGE_SIGNING_KEY is required in production")
    await cache.add(DEV_KEY_CACHE_KEY, generate_pem())
    pem = await cache.get(DEV_KEY_CACHE_KEY)
    if not pem:
        raise SigningKeyError(detail="development signing key unavailable")
    return _parse(pem)

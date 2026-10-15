from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app

PROD_SECRETS: dict[str, Any] = {
    "app_env": "prod",
    "directory_secret_key": "d" * 32,
    "oidc_bridge_client_secret": "b" * 32,
    "oidc_bridge_signing_key": "k" * 32,
    "open_api_key_pepper": "p" * 32,
    "metrics_token": "m" * 32,
}


def test_production_accepts_complete_secrets() -> None:
    assert Settings(**PROD_SECRETS).app_env == "prod"


@pytest.mark.parametrize(
    ("override", "missing"),
    [
        ({"directory_secret_key": "change-me-directory-secret"}, "DIRECTORY_SECRET_KEY"),
        (
            {"oidc_bridge_client_secret": "change-me-oidc-bridge-secret"},
            "OIDC_BRIDGE_CLIENT_SECRET",
        ),
        ({"oidc_bridge_signing_key": None}, "OIDC_BRIDGE_SIGNING_KEY"),
        ({"open_api_key_pepper": "change-me-open-api-pepper"}, "OPEN_API_KEY_PEPPER"),
        ({"metrics_token": None}, "METRICS_TOKEN"),
    ],
)
def test_production_rejects_dev_or_missing_secrets(override: dict[str, Any], missing: str) -> None:
    with pytest.raises(ValueError, match=missing):
        Settings(**{**PROD_SECRETS, **override})


def test_dev_defaults_are_allowed_outside_production() -> None:
    assert Settings(app_env="dev", metrics_token=None).app_env == "dev"


def test_api_docs_hidden_in_production() -> None:
    client = TestClient(create_app(Settings(**PROD_SECRETS)))
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404


def test_api_docs_available_in_dev() -> None:
    client = TestClient(create_app(Settings(app_env="dev")))
    assert client.get("/openapi.json").status_code == 200

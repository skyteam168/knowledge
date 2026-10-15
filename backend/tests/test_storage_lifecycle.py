from typing import Any

from minio.commonconfig import ENABLED, Filter
from minio.error import S3Error
from minio.lifecycleconfig import Expiration, LifecycleConfig, Rule

from app.core.config import Settings
from app.core.storage import STAGING_PREFIX, STAGING_RULE_ID, MinioStorage


class FakeMinio:
    def __init__(self, lifecycle: LifecycleConfig | None = None, fail: bool = False) -> None:
        self.lifecycle = lifecycle
        self.fail = fail
        self.set_calls = 0

    def bucket_exists(self, bucket: str) -> bool:
        return True

    def get_bucket_lifecycle(self, bucket: str) -> LifecycleConfig | None:
        if self.fail:
            raise S3Error("NotImplemented", "no lifecycle", "", "", "", None)  # type: ignore[arg-type]
        return self.lifecycle

    def set_bucket_lifecycle(self, bucket: str, config: LifecycleConfig) -> None:
        self.lifecycle = config
        self.set_calls += 1


def _storage(client: FakeMinio) -> MinioStorage:
    storage = MinioStorage(Settings())
    storage._client = client  # type: ignore[assignment]
    return storage


def _rules(client: FakeMinio) -> list[Any]:
    assert client.lifecycle is not None
    return list(client.lifecycle.rules)


async def test_adds_staging_expiry_once() -> None:
    client = FakeMinio()
    await _storage(client).ensure_bucket()
    await _storage(client).ensure_bucket()
    rules = _rules(client)
    assert client.set_calls == 1
    assert [(r.rule_id, r.rule_filter.prefix, r.expiration.days) for r in rules] == [
        (STAGING_RULE_ID, STAGING_PREFIX, 1)
    ]


async def test_keeps_existing_rules() -> None:
    other = Rule(
        ENABLED, rule_filter=Filter(prefix="tmp/"), rule_id="ops", expiration=Expiration(days=7)
    )
    client = FakeMinio(LifecycleConfig([other]))
    await _storage(client).ensure_bucket()
    assert [r.rule_id for r in _rules(client)] == ["ops", STAGING_RULE_ID]


async def test_lifecycle_failure_does_not_block_uploads() -> None:
    storage = _storage(FakeMinio(fail=True))
    await storage.ensure_bucket()
    assert storage._bucket_ready

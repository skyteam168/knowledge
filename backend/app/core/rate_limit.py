"""Fixed-window request limits per user and per organization (Redis counters).

Every authenticated request counts against the `api` bucket; question answering and uploads
additionally count against their own, tighter buckets. The limiter fails open: an unavailable
cache must not take the API down.
"""

import logging
import re
import time
from dataclasses import dataclass

from app.core.cache import KeyValueCache
from app.core.config import Settings
from app.core.exceptions import AppError
from app.core.metrics import RATE_LIMITED

logger = logging.getLogger(__name__)

_CHAT = re.compile(r"/chat/conversations/[^/]+/messages$")
_UPLOAD = re.compile(r"/knowledge-bases/[^/]+/documents(/upload-url)?$")


class RateLimitedError(AppError):
    status_code = 429
    code = "RATE_LIMITED"
    message = "Too many requests, please retry later"


@dataclass(frozen=True)
class Limit:
    bucket: str
    scope: str  # "user" | "org"
    limit: int


def buckets(method: str, path: str) -> tuple[str, ...]:
    if method == "POST" and _CHAT.search(path):
        return ("api", "chat")
    if method == "POST" and _UPLOAD.search(path):
        return ("api", "upload")
    return ("api",)


class RateLimiter:
    def __init__(self, cache: KeyValueCache, settings: Settings) -> None:
        self.cache = cache
        self.settings = settings
        self.window = max(1, settings.rate_limit_window_seconds)

    def limits(self, bucket: str) -> list[Limit]:
        s = self.settings
        table = {
            "api": [
                Limit("api", "user", s.rate_limit_user_requests),
                Limit("api", "org", s.rate_limit_org_requests),
            ],
            "chat": [
                Limit("chat", "user", s.rate_limit_chat_user_requests),
                Limit("chat", "org", s.rate_limit_chat_org_requests),
            ],
            "upload": [Limit("upload", "user", s.rate_limit_upload_user_requests)],
        }
        return [lim for lim in table.get(bucket, []) if lim.limit > 0]

    async def check(self, *, user_id: str, org_id: str, method: str, path: str) -> None:
        if not self.settings.rate_limit_enabled:
            return
        now = time.time()
        window = int(now // self.window)
        retry_after = max(1, int(self.window - now % self.window))
        for bucket in buckets(method, path):
            for lim in self.limits(bucket):
                subject = user_id if lim.scope == "user" else org_id
                key = f"rl:{lim.bucket}:{lim.scope}:{subject}:{window}"
                try:
                    count = await self.cache.incr(key, ttl_seconds=self.window + 1)
                except Exception:
                    logger.warning("rate_limit_unavailable", exc_info=True)
                    return
                if count > lim.limit:
                    RATE_LIMITED.labels(lim.scope, lim.bucket).inc()
                    raise RateLimitedError(
                        detail={
                            "bucket": lim.bucket,
                            "scope": lim.scope,
                            "limit": lim.limit,
                            "window_seconds": self.window,
                            "retry_after": retry_after,
                        },
                        headers={"Retry-After": str(retry_after)},
                    )

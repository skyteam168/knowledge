import logging

import dramatiq

from app.workers import broker as _broker  # noqa: F401  (configures the global broker first)

logger = logging.getLogger(__name__)


@dramatiq.actor(queue_name="default", max_retries=3)
def ping(message: str) -> str:
    """Example task used to verify the worker pipeline."""
    reply = f"pong: {message}"
    logger.info("ping_task", extra={"input": message, "reply": reply})
    return reply

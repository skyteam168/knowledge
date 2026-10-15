"""Outbox dispatcher: `python -m app.workers.outbox_dispatcher`.

Continuously claims due outbox events (FOR UPDATE SKIP LOCKED, so several replicas are safe)
and hands them to the `index` queue. Lost messages are recovered when their lease expires.
"""

import asyncio
import contextlib
import logging
import signal
from collections.abc import Callable

from app.core.config import Settings, get_settings
from app.core.logging import setup_logging
from app.services.indexing.outbox import OutboxProcessor
from app.services.indexing.runtime import IndexingRuntime

logger = logging.getLogger(__name__)


async def dispatch_once(processor: OutboxProcessor, send: Callable[[str], object]) -> int:
    ids = await processor.claim()
    for event_id in ids:
        send(event_id)
    return len(ids)


async def run(settings: Settings, stop: asyncio.Event) -> None:
    from app.workers.indexing import process_outbox_event

    runtime = IndexingRuntime.create(settings)
    try:
        await runtime.registry.bootstrap()
        logger.info("outbox_dispatcher_started")
        while not stop.is_set():
            try:
                sent = await dispatch_once(runtime.processor, process_outbox_event.send)
            except Exception:
                logger.exception("outbox_dispatch_failed")
                sent = 0
            if sent < settings.outbox_batch_size:
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(stop.wait(), settings.outbox_poll_interval_seconds)
    finally:
        await runtime.aclose()
        logger.info("outbox_dispatcher_stopped")


def main() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)
    stop = asyncio.Event()

    async def _main() -> None:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            # Not available on Windows event loops; Ctrl+C still raises KeyboardInterrupt.
            with contextlib.suppress(NotImplementedError):
                loop.add_signal_handler(sig, stop.set)
        await run(settings, stop)

    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(_main())


if __name__ == "__main__":
    main()

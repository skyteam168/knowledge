"""Periodic job scheduler: `python -m app.workers.scheduler`.

Enqueues the periodic jobs (gap clustering, expiry checks, analytics summaries) on fixed
intervals.
Run a single replica; the jobs themselves are idempotent, so an occasional overlap is harmless.
"""

import asyncio
import contextlib
import logging
import signal
import time
from collections.abc import Callable
from dataclasses import dataclass

from app.core.config import Settings, get_settings
from app.core.logging import setup_logging

logger = logging.getLogger(__name__)
TICK_SECONDS = 5.0


@dataclass
class Job:
    name: str
    interval: float
    send: Callable[[], object]
    due: float = 0.0


def run_due(jobs: list[Job], now: float) -> list[str]:
    fired = []
    for job in jobs:
        if now < job.due:
            continue
        try:
            job.send()
            fired.append(job.name)
        except Exception:
            logger.exception("scheduled_job_enqueue_failed", extra={"job": job.name})
        job.due = now + job.interval
    return fired


async def run(settings: Settings, stop: asyncio.Event) -> None:
    from app.workers.analytics import refresh_analytics
    from app.workers.curation import check_expirations, cluster_gaps
    from app.workers.directory import dispatch_directory_syncs
    from app.workers.maintenance import purge_expired_data

    jobs = [
        Job(
            "directory_sync",
            settings.directory_sync_check_interval_seconds,
            dispatch_directory_syncs.send,
        ),
        Job("cluster_gaps", settings.gap_cluster_interval_seconds, cluster_gaps.send),
        Job("check_expirations", settings.expiry_check_interval_seconds, check_expirations.send),
        Job(
            "refresh_analytics",
            settings.analytics_refresh_interval_seconds,
            refresh_analytics.send,
        ),
        Job(
            "purge_expired_data",
            settings.retention_check_interval_seconds,
            purge_expired_data.send,
        ),
    ]
    logger.info("scheduler_started", extra={"jobs": [j.name for j in jobs]})
    while not stop.is_set():
        for name in run_due(jobs, time.monotonic()):
            logger.info("scheduled_job_enqueued", extra={"job": name})
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), TICK_SECONDS)
    logger.info("scheduler_stopped")


def main() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)
    stop = asyncio.Event()

    async def _main() -> None:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            with contextlib.suppress(NotImplementedError):
                loop.add_signal_handler(sig, stop.set)
        await run(settings, stop)

    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(_main())


if __name__ == "__main__":
    main()

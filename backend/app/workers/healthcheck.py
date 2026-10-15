"""Container healthcheck for workers: the worker process is alive and Redis is reachable."""

import os
import sys
from pathlib import Path

from redis import Redis

from app.core.config import get_settings


def _process_running(marker: bytes) -> bool:
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit() or proc.name == str(os.getpid()):
            continue
        try:
            if marker in (proc / "cmdline").read_bytes():
                return True
        except OSError:
            continue
    return False


def main(argv: list[str] | None = None) -> int:
    """Usage: `python -m app.workers.healthcheck [process-marker]` (default: dramatiq)."""
    args = sys.argv[1:] if argv is None else argv
    marker = (args[0] if args else "dramatiq").encode()
    if not _process_running(marker):
        return 1
    try:
        Redis.from_url(get_settings().redis_url, socket_timeout=3).ping()
    except Exception:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

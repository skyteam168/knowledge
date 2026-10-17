"""Optional LibreOffice (soffice) conversion for legacy Office formats."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)


def resolve_soffice(soffice_path: str | None = None) -> str | None:
    if soffice_path and Path(soffice_path).exists():
        return soffice_path
    return shutil.which("soffice") or shutil.which("libreoffice")


def convert_with_soffice(
    data: bytes,
    *,
    source_suffix: str,
    to_format: str,
    soffice_path: str | None = None,
    timeout_seconds: float = 180,
) -> bytes | None:
    """Convert Office bytes via LibreOffice. Returns None when soffice is unavailable."""
    binary = resolve_soffice(soffice_path)
    if not binary:
        return None
    suffix = source_suffix if source_suffix.startswith(".") else f".{source_suffix}"
    with tempfile.TemporaryDirectory(prefix="ekb-soffice-") as tmp:
        tmp_path = Path(tmp)
        src = tmp_path / f"input{suffix}"
        src.write_bytes(data)
        try:
            completed = subprocess.run(
                [
                    binary,
                    # Private profile per call: concurrent soffice runs sharing one profile
                    # lock each other out, and the worker's HOME may not be writable.
                    f"-env:UserInstallation={(tmp_path / 'profile').as_uri()}",
                    "--headless",
                    "--nologo",
                    "--nofirststartwizard",
                    "--convert-to",
                    to_format,
                    "--outdir",
                    str(tmp_path),
                    str(src),
                ],
                check=False,
                capture_output=True,
                timeout=timeout_seconds,
                env={**os.environ, "HOME": str(tmp_path)},
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            logger.warning("soffice_convert_failed", extra={"error": str(exc), "to": to_format})
            return None
        out = tmp_path / f"input.{to_format}"
        if completed.returncode != 0 or not out.exists():
            logger.warning(
                "soffice_convert_failed",
                extra={
                    "code": completed.returncode,
                    "stderr": (completed.stderr or b"")[:300],
                    "to": to_format,
                },
            )
            return None
        return out.read_bytes()

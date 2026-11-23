import json
import os

from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_LOG_PATH = (
    Path(__file__).resolve().parents[2]
    / "logs"
    / "reviews.jsonl"
)


def append_event(
    event: dict[str, Any],
    log_path: Path = DEFAULT_LOG_PATH,
) -> None:
    """
    Append one JSON event to a local JSONL audit log.

    Log files are restricted to the current user on Unix.
    """

    log_path.parent.mkdir(
        parents=True,
        exist_ok=True,
        mode=0o700,
    )

    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND

    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW

    fd = os.open(
        log_path,
        flags,
        0o600,
    )

    try:
        os.fchmod(fd, 0o600)

        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **event,
        }

        line = (
            json.dumps(
                record,
                ensure_ascii=False,
            )
            + "\n"
        )

        with os.fdopen(fd, "a", encoding="utf-8") as file:
            fd = -1
            file.write(line)

    finally:
        if fd != -1:
            os.close(fd)

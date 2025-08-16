"""Small structured logging helpers for deterministic workflow events."""

from __future__ import annotations

import json
import logging
from typing import Any

LOGGER_NAME = "agentviz"


def emit_event(event: str, **fields: Any) -> None:
    """Emit one JSON log line without configuring global logging."""

    payload = {"event": event, **fields}
    logging.getLogger(LOGGER_NAME).info(
        json.dumps(payload, default=str, sort_keys=True)
    )

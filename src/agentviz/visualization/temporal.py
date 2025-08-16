"""Deterministic temporal parsing helpers for visualization."""

from __future__ import annotations

import re
from datetime import datetime

from agentviz.models import ScalarValue

_YEAR_MONTH_PATTERN = re.compile(r"^\d{4}-\d{2}$")


def parse_temporal_value(value: ScalarValue) -> datetime | None:
    if not isinstance(value, str):
        return None

    if _YEAR_MONTH_PATTERN.fullmatch(value):
        try:
            return datetime.fromisoformat(f"{value}-01")
        except ValueError:
            return None

    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def is_temporal_value(value: ScalarValue) -> bool:
    return parse_temporal_value(value) is not None

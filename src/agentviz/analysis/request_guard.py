"""Deterministic safety checks for natural-language analysis requests."""

from __future__ import annotations

import re

from agentviz.errors import RequestSafetyError
from agentviz.models import AnalysisRequest

_DISALLOWED_PATTERNS = (
    re.compile(r"\b(drop|delete|truncate|update|insert|alter|create)\b", re.I),
    re.compile(r"\battach\s+database\b", re.I),
    re.compile(r"\bpragma\b", re.I),
    re.compile(r"\bignore\s+(all\s+)?previous\s+instructions\b", re.I),
    re.compile(r"\bleak\b|\bexfiltrat", re.I),
)


def validate_request_safety(request: AnalysisRequest) -> None:
    """Reject obvious destructive or prompt-injection intent before agent calls."""

    question = request.question
    for pattern in _DISALLOWED_PATTERNS:
        if pattern.search(question):
            raise RequestSafetyError(
                "request contains disallowed database operation or "
                "instruction-overriding intent"
            )

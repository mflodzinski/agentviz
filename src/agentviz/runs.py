"""Run identifier helpers for reproducible AgentViz executions."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from secrets import token_hex

from agentviz.models import AnalysisAgentStatus, AnalysisRequest, ApplicationRunResult

RUN_ID_PATTERN = re.compile(r"^\d{8}_\d{6}_[0-9a-f]{8}$")


def generate_run_id(
    *,
    now: datetime | None = None,
    suffix: str | None = None,
) -> str:
    """Generate a sortable, human-readable run identifier."""

    timestamp = (now or datetime.now(UTC)).astimezone(UTC)
    random_suffix = suffix or token_hex(4)
    run_id = f"{timestamp:%Y%m%d_%H%M%S}_{random_suffix}"
    if not is_valid_run_id(run_id):
        raise ValueError("run id suffix must be 8 lowercase hexadecimal characters")
    return run_id


def is_valid_run_id(run_id: str) -> bool:
    return RUN_ID_PATTERN.fullmatch(run_id) is not None


def default_chart_output_path(run_id: str) -> Path:
    if not is_valid_run_id(run_id):
        raise ValueError("invalid run id")
    return Path("runs") / run_id / "chart.png"


def default_manifest_output_path(run_id: str) -> Path:
    if not is_valid_run_id(run_id):
        raise ValueError("invalid run id")
    return Path("runs") / run_id / "manifest.json"


def build_run_manifest(
    *,
    request: AnalysisRequest,
    result: ApplicationRunResult,
) -> dict[str, object]:
    """Build row-free reproducibility metadata for one application run."""

    artifact = result.analysis.artifact
    manifest: dict[str, object] = {
        "run_id": result.run_id,
        "user": request.user.username,
        "database": request.database,
        "request": request.question,
        "analysis_status": result.analysis.status,
        "analysis_message": result.analysis.message,
        "sql": artifact.sql if artifact is not None else None,
        "columns": artifact.columns if artifact is not None else [],
        "row_count": artifact.row_count if artifact is not None else 0,
        "truncated": artifact.truncated if artifact is not None else False,
        "chart_type": result.chart_spec.chart_type if result.chart_spec else None,
        "chart_path": (
            result.chart_path.as_posix() if result.chart_path is not None else None
        ),
        "visualization_warning": result.visualization_warning,
    }

    if result.analysis.status != AnalysisAgentStatus.COMPLETED:
        manifest["chart_type"] = None
        manifest["chart_path"] = None

    return manifest


def write_run_manifest(
    *,
    request: AnalysisRequest,
    result: ApplicationRunResult,
    output_path: Path,
) -> Path:
    manifest = build_run_manifest(request=request, result=result)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return output_path

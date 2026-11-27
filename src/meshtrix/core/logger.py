"""
Meshtrix Structured Run Logger — JSON audit trail and step-level reporting.

Authoritative Reference: ORIGINAL_REQUEST.md §R2 & PROJECT.md
"""

from __future__ import annotations

import hashlib
import json
import platform
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pydantic

from meshtrix.diagnostics.failure import FailureObject


def compute_spec_hash(spec_dict: dict[str, Any]) -> str:
    """Compute a deterministic SHA-256 hex digest of a JobSpec dictionary."""
    canonical = json.dumps(spec_dict, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def collect_tool_versions() -> dict[str, str]:
    """Collect runtime Python and core dependency versions for auditability."""
    return {
        "python": platform.python_version(),
        "pydantic": pydantic.__version__,
        "platform": sys.platform,
    }


class RunLogger:
    """Structured JSON audit logger for pipeline execution."""

    def __init__(
        self,
        log_dir: str | Path = ".meshtrix/logs",
        run_id: str = "run_default",
        job_id: str = "",
        spec_version: str = "1.0",
        spec_hash: str = "",
        resumed_from: str | None = None,
    ) -> None:
        self._log_dir = Path(log_dir)
        self.run_id = run_id
        self.job_id = job_id
        self.status = "running"
        self.started_at = datetime.now(UTC).isoformat()
        self.finished_at: str | None = None
        self.duration_seconds: float = 0.0
        self.spec_version = spec_version
        self.spec_hash = spec_hash
        self.tool_versions = collect_tool_versions()
        self.resumed_from = resumed_from
        self.steps: list[dict[str, Any]] = []

    def record_step(
        self,
        step_id: str,
        status: str,
        failures: list[FailureObject] | None = None,
        warnings: list[Any] | None = None,
        duration_seconds: float = 0.0,
    ) -> None:
        """Append a step execution record to the audit log."""
        self.steps.append(
            {
                "step_id": step_id,
                "status": status,
                "timestamp": datetime.now(UTC).isoformat(),
                "duration_seconds": duration_seconds,
                "failures": [f.model_dump(mode="json") for f in (failures or [])],
                "warnings": list(warnings or []),
            }
        )

    def finalize(self, status: str, duration_seconds: float) -> None:
        """Mark the run as complete with final status and duration."""
        self.status = status
        self.finished_at = datetime.now(UTC).isoformat()
        self.duration_seconds = duration_seconds

    def to_dict(self) -> dict[str, Any]:
        """Serialize the run log into a JSON-safe dictionary."""
        return {
            "run_id": self.run_id,
            "job_id": self.job_id,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_seconds": self.duration_seconds,
            "spec_version": self.spec_version,
            "spec_hash": self.spec_hash,
            "tool_versions": dict(self.tool_versions),
            "resumed_from": self.resumed_from,
            "steps": list(self.steps),
        }

    def save_log(self, filename: str | None = None) -> Path:
        """Persist the structured run log as a JSON file."""
        self._log_dir.mkdir(parents=True, exist_ok=True)
        fname = filename or f"{self.run_id}.json"
        path = self._log_dir / fname
        path.write_text(json.dumps(self.to_dict(), indent=2, default=str), encoding="utf-8")
        return path

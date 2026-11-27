"""
Meshtrix Core Checkpointing — JSON state persistence for resume support.

Authoritative Reference: ORIGINAL_REQUEST.md §R2 & PROJECT.md
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from meshtrix.core.step import RunContext
from meshtrix.spec.job_spec import JobSpec


class CheckpointManager:
    """Persist and load per-step checkpoint data to/from JSON files."""

    def __init__(self, base_dir: str | Path = ".meshtrix/checkpoints") -> None:
        self._base_dir = Path(base_dir)

    def _run_dir(self, run_id: str) -> Path:
        return self._base_dir / run_id

    def _checkpoint_path(self, run_id: str, step_id: str) -> Path:
        return self._run_dir(run_id) / f"{step_id}.json"

    def save_checkpoint(
        self,
        run_id: str,
        step_id: str,
        step_index: int,
        spec: JobSpec,
        context: RunContext,
        driver_state: dict[str, Any] | None = None,
        warnings: list[Any] | None = None,
        status: str = "passed",
    ) -> Path:
        """Write a checkpoint JSON file for a completed step."""
        run_dir = self._run_dir(run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] = {
            "run_id": run_id,
            "step_id": step_id,
            "step_index": step_index,
            "status": status,
            "timestamp": datetime.now(UTC).isoformat(),
            "spec": spec.to_dict(),
            "metadata": dict(context.metadata),
            "driver_state": driver_state or {},
            "warnings": warnings or [],
        }
        path = self._checkpoint_path(run_id, step_id)
        path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        return path

    def has_checkpoint(self, run_id: str, step_id: str) -> bool:
        """Return True if a checkpoint file exists for run_id and step_id."""
        return self._checkpoint_path(run_id, step_id).exists()

    def load_checkpoint(self, run_id: str, step_id: str) -> dict[str, Any]:
        """Load a checkpoint JSON dict; raises FileNotFoundError if missing."""
        path = self._checkpoint_path(run_id, step_id)
        if not path.exists():
            raise FileNotFoundError(
                f"Checkpoint not found for run_id='{run_id}', step_id='{step_id}' at {path}"
            )
        return dict(json.loads(path.read_text(encoding="utf-8")))

    def list_checkpoints(self, run_id: str) -> list[str]:
        """Return sorted list of step_ids that have checkpoint files for run_id."""
        run_dir = self._run_dir(run_id)
        if not run_dir.exists():
            return []
        return [p.stem for p in sorted(run_dir.glob("*.json"))]

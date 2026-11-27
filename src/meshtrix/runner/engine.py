"""
Meshtrix Pipeline Engine — sequential orchestrator with fail-fast, checkpointing, and resume.

Authoritative Reference: ORIGINAL_REQUEST.md §R2 & PROJECT.md
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from meshtrix.core.checkpoint import CheckpointManager
from meshtrix.core.logger import RunLogger, compute_spec_hash
from meshtrix.core.step import BaseStep, RunContext
from meshtrix.diagnostics.failure import FailureObject, StepCheckResult
from meshtrix.runner.registry import StepRegistry
from meshtrix.spec.job_spec import JobSpec


@dataclass
class StepResult:
    """Summary of a single step execution."""

    step_id: str
    status: str  # "passed" | "failed" | "skipped"
    pre_check: StepCheckResult | None = None
    post_check: StepCheckResult | None = None
    failures: list[FailureObject] = field(default_factory=list)


@dataclass
class PipelineResult:
    """Aggregate result of a full pipeline run."""

    run_id: str
    job_id: str
    status: str  # "passed" | "failed"
    success: bool
    completed_steps: list[str] = field(default_factory=list)
    skipped_steps: list[str] = field(default_factory=list)
    step_results: list[StepResult] = field(default_factory=list)
    failures: list[FailureObject] = field(default_factory=list)
    log_path: Path = field(default_factory=lambda: Path(".meshtrix/logs/run.json"))
    elapsed_seconds: float = 0.0

    def is_successful(self) -> bool:
        """Return True if the pipeline completed without failures."""
        return self.success


# Backward-compatible alias
RunResult = PipelineResult


class PipelineRunner:
    """Sequential pipeline orchestrator supporting checkpointing and resume."""

    def __init__(
        self,
        registry: StepRegistry | None = None,
        base_dir: str | Path = ".",
    ) -> None:
        self._registry = registry or StepRegistry()
        self._base_dir = Path(base_dir)

    def run(
        self,
        spec_or_ctx: JobSpec | RunContext,
        driver: Any | None = None,
        *,
        run_id: str | None = None,
        resume_from: str | None = None,
        checkpoint_dir: str | Path | None = None,
        log_dir: str | Path | None = None,
    ) -> PipelineResult:
        """Execute the pipeline sequentially with fail-fast and checkpointing."""
        if isinstance(spec_or_ctx, RunContext):
            ctx = spec_or_ctx
            spec = ctx.spec
        else:
            spec = spec_or_ctx
            ctx = RunContext(spec=spec, driver=driver)

        effective_run_id = run_id or (
            ctx.run_id if ctx.run_id != "run_default" else str(uuid.uuid4())[:8]
        )
        ctx.run_id = effective_run_id

        cp_root = (
            Path(checkpoint_dir)
            if checkpoint_dir is not None
            else self._base_dir / ".meshtrix" / "checkpoints"
        )
        log_root = Path(log_dir) if log_dir is not None else self._base_dir / ".meshtrix" / "logs"

        checkpoint_mgr = CheckpointManager(cp_root)
        run_logger = RunLogger(
            log_dir=log_root,
            run_id=effective_run_id,
            job_id=spec.job_id,
            spec_version=spec.spec_version,
            spec_hash=compute_spec_hash(spec.to_dict()),
            resumed_from=resume_from,
        )

        steps = self._registry.steps
        step_ids = [s.step_id for s in steps]

        # Validate resume_from and prior checkpoints before running
        resume_index = 0
        if resume_from is not None:
            if resume_from not in step_ids:
                raise ValueError(
                    f"Unknown resume_from step_id '{resume_from}'. Valid steps: {step_ids}"
                )
            resume_index = step_ids.index(resume_from)
            for prior_id in step_ids[:resume_index]:
                if not checkpoint_mgr.has_checkpoint(effective_run_id, prior_id):
                    raise FileNotFoundError(
                        f"Cannot resume from '{resume_from}': missing checkpoint for "
                        f"prior step '{prior_id}' in run '{effective_run_id}'."
                    )

        step_results: list[StepResult] = []
        completed_steps: list[str] = []
        skipped_steps: list[str] = []
        all_failures: list[FailureObject] = []
        overall_status = "passed"
        t_start = time.monotonic()

        for idx, step in enumerate(steps):
            step_id = step.step_id

            if idx < resume_index:
                sr = StepResult(step_id=step_id, status="skipped")
                step_results.append(sr)
                skipped_steps.append(step_id)
                run_logger.record_step(step_id=step_id, status="skipped")
                continue

            t_step = time.monotonic()
            sr = self._run_step(step, idx, ctx, checkpoint_mgr, effective_run_id)
            step_duration = time.monotonic() - t_step
            step_results.append(sr)

            warnings = sr.post_check.warnings if sr.post_check else []
            run_logger.record_step(
                step_id=step_id,
                status=sr.status,
                failures=sr.failures,
                warnings=warnings,
                duration_seconds=step_duration,
            )

            if sr.status == "failed":
                overall_status = "failed"
                all_failures.extend(sr.failures)
                break

            completed_steps.append(step_id)

        elapsed = time.monotonic() - t_start
        run_logger.finalize(status=overall_status, duration_seconds=elapsed)
        log_path = run_logger.save_log()

        return PipelineResult(
            run_id=effective_run_id,
            job_id=spec.job_id,
            status=overall_status,
            success=(overall_status == "passed"),
            completed_steps=completed_steps,
            skipped_steps=skipped_steps,
            step_results=step_results,
            failures=all_failures,
            log_path=log_path,
            elapsed_seconds=elapsed,
        )

    def _run_step(
        self,
        step: BaseStep,
        step_index: int,
        ctx: RunContext,
        checkpoint_mgr: CheckpointManager,
        run_id: str,
    ) -> StepResult:
        """Execute a single step through its 4-phase contract."""
        step_id = step.step_id
        sr = StepResult(step_id=step_id, status="passed")

        # Phase 1 — Pre-check
        pre = step.pre_check(ctx)
        sr.pre_check = pre
        if pre.has_blocking():
            sr.status = "failed"
            enriched = step.troubleshoot(ctx, pre)
            sr.failures.extend(enriched or pre.failures)
            return sr

        # Phase 2 — Execute
        step.execute(ctx)

        # Phase 3 — Post-check
        post = step.post_check(ctx)
        sr.post_check = post
        if post.has_blocking():
            sr.status = "failed"
            enriched = step.troubleshoot(ctx, post)
            sr.failures.extend(enriched or post.failures)
            return sr

        # Passed — persist checkpoint
        driver_state: dict[str, Any] = (
            ctx.driver.export_state() if hasattr(ctx.driver, "export_state") else {}
        )
        checkpoint_mgr.save_checkpoint(
            run_id=run_id,
            step_id=step_id,
            step_index=step_index,
            spec=ctx.spec,
            context=ctx,
            driver_state=driver_state,
            warnings=post.warnings,
            status="passed",
        )
        return sr

"""
Meshtrix Core Step Interface and RunContext Dependency Container.

Authoritative Reference: ORIGINAL_REQUEST.md §R2 & PROJECT.md
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from meshtrix.diagnostics.failure import FailureObject, StepCheckResult
from meshtrix.spec.job_spec import JobSpec


class RunContext(BaseModel):
    """Execution context bundling specification, driver port, and runtime artifacts."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    spec: JobSpec
    driver: Any
    run_id: str = "run_default"
    artifacts_dir: Path | str | None = None
    step_data: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class BaseStep(ABC):
    """Abstract 4-phase contract for pipeline steps."""

    @property
    @abstractmethod
    def step_id(self) -> str:
        """Unique step identifier (e.g. 'step_06_materials')."""

    @property
    @abstractmethod
    def description(self) -> str:
        """Engineering description of the step's purpose and scope."""

    @abstractmethod
    def pre_check(self, context: RunContext) -> StepCheckResult:
        """Phase 1: Validate inputs and model preconditions prior to mutation."""

    @abstractmethod
    def execute(self, context: RunContext) -> None:
        """Phase 2: Apply actions and mutations through the driver port."""

    @abstractmethod
    def post_check(self, context: RunContext) -> StepCheckResult:
        """Phase 3: Verify the physical driver state matches specification."""

    @abstractmethod
    def troubleshoot(
        self, context: RunContext, check_result: StepCheckResult
    ) -> list[FailureObject]:
        """Phase 4: Isolate root causes and produce actionable remediation objects."""

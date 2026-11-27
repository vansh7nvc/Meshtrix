"""
Meshtrix Step Registry — ordered pipeline definition.

The registry declares the canonical execution order for all pipeline steps.
Steps are instantiated lazily to avoid import cycles with the driver layer.

Authoritative Reference: ORIGINAL_REQUEST.md §R2 & PROJECT.md
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from meshtrix.core.step import BaseStep


def _build_pipeline() -> list[BaseStep]:
    """Instantiate all pipeline steps in execution order."""
    from meshtrix.steps.step_06_materials import Step06MaterialMapping
    from meshtrix.steps.step_08_meshing import Step08Meshing
    from meshtrix.steps.step_09_boundary_conditions import Step09BoundaryConditions
    from meshtrix.steps.step_10_loads import Step10Loads

    return [
        Step06MaterialMapping(),
        Step08Meshing(),
        Step09BoundaryConditions(),
        Step10Loads(),
    ]


class StepRegistry:
    """Ordered registry of pipeline steps supporting lookup by step_id."""

    def __init__(self) -> None:
        self._steps: list[BaseStep] = _build_pipeline()

    @property
    def steps(self) -> list[BaseStep]:
        """Return all registered steps in execution order."""
        return list(self._steps)

    def get_step(self, step_id: str) -> BaseStep | None:
        """Return the step with the given step_id, or None if not found."""
        for step in self._steps:
            if step.step_id == step_id:
                return step
        return None

    def step_ids(self) -> list[str]:
        """Return ordered list of step_id strings."""
        return [s.step_id for s in self._steps]

    def steps_from(self, step_id: str) -> list[BaseStep]:
        """Return steps starting from the given step_id (inclusive)."""
        idx = self.step_ids().index(step_id) if step_id in self.step_ids() else 0
        return self._steps[idx:]


# Singleton default pipeline for CLI and runner use
PIPELINE_STEPS: list[str] = [
    "step_06_materials",
    "step_08_meshing",
    "step_09_boundary_conditions",
    "step_10_loads",
]

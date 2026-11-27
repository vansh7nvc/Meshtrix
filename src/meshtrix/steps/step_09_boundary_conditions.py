"""
Meshtrix Step 09 — Boundary Condition Application.

Implements the 4-phase contract (pre_check → execute → post_check → troubleshoot)
for applying structural boundary conditions (supports) from JobSpec to the solver model.

Authoritative Reference: ORIGINAL_REQUEST.md §R2 & PROJECT.md
"""

from __future__ import annotations

import math

from meshtrix.core.step import BaseStep, RunContext
from meshtrix.diagnostics.failure import (
    ERR_BC_COORDINATE_SYSTEM_MISMATCH,
    ERR_BC_DOF_MISMATCH,
    ERR_BC_EMPTY_SELECTION,
    ERR_BC_INVALID_SPEC,
    ERR_BC_MISSING_SELECTION,
    ERR_BC_MISSING_SUPPORT,
    ERR_BC_SCOPING_MISMATCH,
    ERR_DRIVER_COMMUNICATION,
    FailureObject,
    Severity,
    StepCheckResult,
)
from meshtrix.drivers.base import SupportRecord
from meshtrix.spec.job_spec import AnalysisType, SupportSpec, SupportType

STEP_ID = "step_09_boundary_conditions"

_DEFAULT_DOFS: dict[str, list[str]] = {
    SupportType.FIXED.value: ["UX", "UY", "UZ", "RX", "RY", "RZ"],
    SupportType.PINNED.value: ["UX", "UY", "UZ"],
    SupportType.FRICTIONLESS.value: ["NORMAL"],
    SupportType.DISPLACEMENT.value: ["UX", "UY", "UZ"],
}


def _resolve_dofs(spec: SupportSpec) -> list[str]:
    """Resolve the DOF list for a support spec, applying defaults by support type."""
    if hasattr(spec, "resolved_dofs"):
        return list(spec.resolved_dofs())
    support_type = spec.type if isinstance(spec.type, str) else spec.type.value
    raw_dofs: list[str] = getattr(spec, "dofs", None) or getattr(spec, "dof", None) or []
    if raw_dofs:
        return [d.upper() for d in raw_dofs]
    return _DEFAULT_DOFS.get(support_type, ["UX", "UY", "UZ", "RX", "RY", "RZ"])


def _normalize_support_type(raw: str | SupportType) -> str:
    if isinstance(raw, SupportType):
        return raw.value
    return str(raw).strip().lower()


def _support_name(spec: SupportSpec, idx: int, selection: str) -> str:
    return getattr(spec, "name", None) or f"BC_{idx + 1}_{selection}"


class Step09BoundaryConditions(BaseStep):
    """Apply structural boundary conditions (supports) from JobSpec to the model."""

    @property
    def step_id(self) -> str:
        return STEP_ID

    @property
    def description(self) -> str:
        return "Apply structural boundary conditions (supports) from JobSpec to the solver model."

    # ------------------------------------------------------------------
    # Phase 1 — Pre-check
    # ------------------------------------------------------------------

    def pre_check(self, context: RunContext) -> StepCheckResult:
        """Validate driver connection, support specs, and named selections."""
        result = StepCheckResult(step_id=STEP_ID)

        if hasattr(context.driver, "is_connected") and not context.driver.is_connected():
            result.add_failure(
                FailureObject(
                    error_code=ERR_DRIVER_COMMUNICATION,
                    severity=Severity.BLOCKING,
                    step_id=STEP_ID,
                    component_or_entity="MechanicalDriver",
                    measured_value="Disconnected",
                    expected_value="Connected",
                    engineering_message="Mechanical driver is not connected.",
                    likely_causes=["Solver process crashed or failed to start"],
                    suggested_fixes=["Reconnect driver port to Mechanical instance"],
                    resume_step_id=STEP_ID,
                )
            )
            return result

        if not context.spec.supports:
            if context.spec.analysis_type == AnalysisType.MODAL:
                return result
            result.add_failure(
                FailureObject(
                    error_code=ERR_BC_INVALID_SPEC,
                    severity=Severity.BLOCKING,
                    step_id=STEP_ID,
                    component_or_entity="supports",
                    measured_value=0,
                    expected_value=">=1 support",
                    engineering_message=(
                        f"Analysis type '{context.spec.analysis_type}' requires at least one "
                        "boundary condition support to prevent rigid-body motion."
                    ),
                    likely_causes=["Missing supports in JobSpec for static analysis."],
                    suggested_fixes=["Add at least one support definition to JobSpec.supports."],
                    resume_step_id=STEP_ID,
                )
            )
            return result

        for idx, support_spec in enumerate(context.spec.supports):
            entity_label = f"support[{idx}] selection={support_spec.selection!r}"

            if not support_spec.selection or not support_spec.selection.strip():
                result.add_failure(
                    FailureObject(
                        error_code=ERR_BC_INVALID_SPEC,
                        severity=Severity.BLOCKING,
                        step_id=STEP_ID,
                        component_or_entity=entity_label,
                        engineering_message=(
                            "Support specification has an empty or missing selection name."
                        ),
                        likely_causes=["Spec authoring error — selection field is blank."],
                        suggested_fixes=["Provide a valid named selection string in JobSpec."],
                        resume_step_id=STEP_ID,
                    )
                )
                continue

            disp_vals = getattr(support_spec, "displacement_values", None)
            if disp_vals is not None:
                bad_vals = [
                    (k, v)
                    for k, v in disp_vals.items()
                    if not isinstance(v, (int, float))
                    or isinstance(v, bool)
                    or not math.isfinite(float(v))
                ]
                if bad_vals:
                    result.add_failure(
                        FailureObject(
                            error_code=ERR_BC_INVALID_SPEC,
                            severity=Severity.BLOCKING,
                            step_id=STEP_ID,
                            component_or_entity=entity_label,
                            measured_value=dict(bad_vals),
                            expected_value="finite numeric displacement values",
                            engineering_message=(
                                f"Support '{entity_label}' has non-finite displacement_values: "
                                f"{bad_vals}."
                            ),
                            likely_causes=["NaN or Inf passed into displacement_values."],
                            suggested_fixes=["Provide finite numeric displacement values."],
                            resume_step_id=STEP_ID,
                        )
                    )
                    continue

            selection = support_spec.selection.strip()

            if not context.driver.has_named_selection(selection):
                result.add_failure(
                    FailureObject(
                        error_code=ERR_BC_MISSING_SELECTION,
                        severity=Severity.BLOCKING,
                        step_id=STEP_ID,
                        component_or_entity=entity_label,
                        measured_value=None,
                        expected_value=selection,
                        engineering_message=(
                            f"Named selection '{selection}' required by support[{idx}] "
                            f"does not exist in the solver model."
                        ),
                        likely_causes=[
                            "Named selection not transferred from SpaceClaim.",
                            "Spelling mismatch between JobSpec and CAD model.",
                        ],
                        suggested_fixes=[
                            "Verify the named selection exists in SpaceClaim and was transferred.",
                            f"Check spelling: expected '{selection}'.",
                        ],
                        resume_step_id=STEP_ID,
                    )
                )
                continue

            entities = context.driver.get_named_selection_entities(selection)
            if not entities:
                result.add_failure(
                    FailureObject(
                        error_code=ERR_BC_EMPTY_SELECTION,
                        severity=Severity.BLOCKING,
                        step_id=STEP_ID,
                        component_or_entity=entity_label,
                        measured_value=0,
                        expected_value=">0 entities",
                        engineering_message=(
                            f"Named selection '{selection}' exists but contains no entities."
                        ),
                        likely_causes=[
                            "Selection was created but no geometry was assigned to it.",
                            "Geometry was suppressed or deleted after selection was defined.",
                        ],
                        suggested_fixes=[
                            f"Re-scope named selection '{selection}' to include at least one face/edge.",
                        ],
                        resume_step_id=STEP_ID,
                    )
                )

        return result

    # ------------------------------------------------------------------
    # Phase 2 — Execute
    # ------------------------------------------------------------------

    def execute(self, context: RunContext) -> None:
        """Apply all supports from JobSpec to the solver model via the driver."""
        if hasattr(context.driver, "is_connected") and not context.driver.is_connected():
            raise ConnectionError("Mechanical driver is not connected.")

        for idx, support_spec in enumerate(context.spec.supports):
            if not support_spec.selection or not support_spec.selection.strip():
                continue
            selection = support_spec.selection.strip()
            support_type = _normalize_support_type(support_spec.type)
            dofs = _resolve_dofs(support_spec)
            name = _support_name(support_spec, idx, selection)
            cs = getattr(support_spec, "coordinate_system", "Global") or "Global"
            disp_vals = getattr(support_spec, "displacement_values", None)

            context.driver.apply_support(
                selection=selection,
                support_type=support_type,
                dofs=dofs,
                coordinate_system=cs,
                name=name,
                displacement_values=disp_vals,
            )

    # ------------------------------------------------------------------
    # Phase 3 — Post-check
    # ------------------------------------------------------------------

    def post_check(self, context: RunContext) -> StepCheckResult:
        """Verify all applied supports match the spec selections, CS, and DOFs."""
        result = StepCheckResult(step_id=STEP_ID)

        if hasattr(context.driver, "is_connected") and not context.driver.is_connected():
            result.add_failure(
                FailureObject(
                    error_code=ERR_DRIVER_COMMUNICATION,
                    severity=Severity.BLOCKING,
                    step_id=STEP_ID,
                    component_or_entity="MechanicalDriver",
                    measured_value="Disconnected",
                    expected_value="Connected",
                    engineering_message="Mechanical driver is not connected.",
                    likely_causes=["Solver process disconnected during execution"],
                    suggested_fixes=["Reconnect driver port to Mechanical instance"],
                    resume_step_id=STEP_ID,
                )
            )
            return result

        if not context.spec.supports:
            return result

        applied = context.driver.get_supports()
        applied_by_name: dict[str, SupportRecord] = {s.name: s for s in applied}
        applied_by_selection: dict[str, list[SupportRecord]] = {}
        for s in applied:
            applied_by_selection.setdefault(s.selection, []).append(s)

        for idx, support_spec in enumerate(context.spec.supports):
            if not support_spec.selection or not support_spec.selection.strip():
                continue
            selection = support_spec.selection.strip()
            expected_name = _support_name(support_spec, idx, selection)
            expected_dofs = _resolve_dofs(support_spec)
            expected_cs = getattr(support_spec, "coordinate_system", "Global") or "Global"
            entity_label = f"support[{idx}] selection={selection!r}"

            record: SupportRecord | None = applied_by_name.get(expected_name)
            if record is None:
                sel_records = applied_by_selection.get(selection)
                if sel_records:
                    record = sel_records[0]

            if record is None:
                result.add_failure(
                    FailureObject(
                        error_code=ERR_BC_MISSING_SUPPORT,
                        severity=Severity.BLOCKING,
                        step_id=STEP_ID,
                        component_or_entity=entity_label,
                        measured_value=None,
                        expected_value=f"support on '{selection}'",
                        engineering_message=(
                            f"Support on selection '{selection}' was not found "
                            f"in the solver model after execute."
                        ),
                        likely_causes=[
                            "Driver apply_support call failed silently.",
                            "Support was not persisted to driver state.",
                        ],
                        suggested_fixes=[
                            "Re-run execute phase.",
                            "Inspect driver logs for apply_support errors.",
                        ],
                        resume_step_id=STEP_ID,
                    )
                )
                continue

            if record.selection != selection:
                result.add_failure(
                    FailureObject(
                        error_code=ERR_BC_SCOPING_MISMATCH,
                        severity=Severity.BLOCKING,
                        step_id=STEP_ID,
                        component_or_entity=entity_label,
                        measured_value=record.selection,
                        expected_value=selection,
                        engineering_message=(
                            f"Support '{record.name}' is scoped to '{record.selection}' "
                            f"but expected '{selection}'."
                        ),
                        likely_causes=["Named selection was renamed after support was applied."],
                        suggested_fixes=["Re-apply the support to the correct named selection."],
                        resume_step_id=STEP_ID,
                    )
                )

            if record.coordinate_system != expected_cs:
                result.add_failure(
                    FailureObject(
                        error_code=ERR_BC_COORDINATE_SYSTEM_MISMATCH,
                        severity=Severity.BLOCKING,
                        step_id=STEP_ID,
                        component_or_entity=entity_label,
                        measured_value=record.coordinate_system,
                        expected_value=expected_cs,
                        engineering_message=(
                            f"Support '{record.name}' uses coordinate system "
                            f"'{record.coordinate_system}' but expected '{expected_cs}'."
                        ),
                        likely_causes=["Coordinate system mismatch in solver model."],
                        suggested_fixes=["Re-apply support with the expected coordinate system."],
                        resume_step_id=STEP_ID,
                    )
                )

            applied_dofs_set = frozenset(d.upper() for d in record.dofs)
            expected_dofs_set = frozenset(d.upper() for d in expected_dofs)
            if applied_dofs_set != expected_dofs_set:
                result.add_failure(
                    FailureObject(
                        error_code=ERR_BC_DOF_MISMATCH,
                        severity=Severity.BLOCKING,
                        step_id=STEP_ID,
                        component_or_entity=entity_label,
                        measured_value=sorted(applied_dofs_set),
                        expected_value=sorted(expected_dofs_set),
                        engineering_message=(
                            f"Support '{record.name}' has DOFs {sorted(applied_dofs_set)} "
                            f"but expected {sorted(expected_dofs_set)}."
                        ),
                        likely_causes=[
                            "DOF list was modified after apply.",
                            "Fault injection altered DOF constraints.",
                        ],
                        suggested_fixes=[
                            "Re-apply support with correct DOF specification.",
                        ],
                        resume_step_id=STEP_ID,
                    )
                )

        return result

    # ------------------------------------------------------------------
    # Phase 4 — Troubleshoot
    # ------------------------------------------------------------------

    def troubleshoot(
        self, context: RunContext, check_result: StepCheckResult
    ) -> list[FailureObject]:
        """Annotate failures with additional root-cause context."""
        enriched: list[FailureObject] = []
        for f in check_result.failures:
            if f.error_code == ERR_BC_MISSING_SELECTION:
                f.likely_causes.append(
                    "Named selection transfer from SpaceClaim may have failed — "
                    "check the geometry import log."
                )
            elif f.error_code == ERR_BC_EMPTY_SELECTION:
                f.likely_causes.append(
                    "Geometry scoped to this selection may have been suppressed "
                    "in the CAD model — verify body visibility."
                )
            elif f.error_code == ERR_BC_DOF_MISMATCH:
                f.suggested_fixes.append(
                    "Clear existing supports and re-run Step 9 from the execute phase."
                )
            enriched.append(f)
        return enriched

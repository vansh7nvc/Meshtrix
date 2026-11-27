"""
Meshtrix Step 10 — Applied Load Application.

Implements the 4-phase contract (pre_check → execute → post_check → troubleshoot)
for applying forces, pressures, and accelerations from JobSpec to the solver model.

Authoritative Reference: ORIGINAL_REQUEST.md §R2 & PROJECT.md
"""

from __future__ import annotations

import math

from meshtrix.core.step import BaseStep, RunContext
from meshtrix.diagnostics.failure import (
    ERR_DRIVER_COMMUNICATION,
    ERR_LOAD_COORDINATE_SYSTEM_MISMATCH,
    ERR_LOAD_DIRECTION_MISMATCH,
    ERR_LOAD_EMPTY_SELECTION,
    ERR_LOAD_INVALID_SPEC,
    ERR_LOAD_MISSING_LOAD,
    ERR_LOAD_MISSING_SELECTION,
    ERR_LOAD_SIGN_MISMATCH,
    ERR_LOAD_TOTAL_MISMATCH,
    FailureObject,
    Severity,
    StepCheckResult,
)
from meshtrix.drivers.base import LoadRecord

STEP_ID = "step_10_loads"

_DIRECTION_TOLERANCE: float = 1e-4
_LOAD_TOLERANCE: float = 0.01


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Return the cosine similarity between two 3D vectors."""
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    mag_a = math.sqrt(sum(x**2 for x in a))
    mag_b = math.sqrt(sum(x**2 for x in b))
    if mag_a < 1e-12 or mag_b < 1e-12:
        return 1.0
    return dot / (mag_a * mag_b)


def _angular_deviation_rad(a: list[float], b: list[float]) -> float:
    """Return the angle in radians between two 3D vectors."""
    cos_val = max(-1.0, min(1.0, _cosine_similarity(a, b)))
    return math.acos(cos_val)


def _relative_error(measured: float, expected: float) -> float:
    """Compute relative error magnitude; uses absolute comparison when expected≈0."""
    if abs(expected) < 1e-12:
        return abs(measured - expected)
    return abs((measured - expected) / expected)


def _validate_numeric_load_fields(magnitude: object, direction: object) -> str | None:
    """Return an error reason string if magnitude or direction is invalid, else None."""
    if (
        not isinstance(magnitude, (int, float))
        or isinstance(magnitude, bool)
        or not math.isfinite(float(magnitude))
    ):
        return f"non-finite magnitude: {magnitude!r}"
    if not isinstance(direction, (list, tuple)) or len(direction) != 3:
        return f"direction must be a 3-element vector, got {direction!r}"
    for comp in direction:
        if (
            not isinstance(comp, (int, float))
            or isinstance(comp, bool)
            or not math.isfinite(float(comp))
        ):
            return f"non-finite direction component in {direction!r}"
    if float(magnitude) != 0.0 and math.hypot(*(float(c) for c in direction)) == 0.0:
        return "direction cannot be zero vector when magnitude is non-zero"
    return None


class Step10Loads(BaseStep):
    """Apply forces, pressures, and accelerations from JobSpec to the solver model."""

    @property
    def step_id(self) -> str:
        return STEP_ID

    @property
    def description(self) -> str:
        return "Apply forces, pressures, and accelerations from JobSpec to the solver model."

    # ------------------------------------------------------------------
    # Phase 1 — Pre-check
    # ------------------------------------------------------------------

    def pre_check(self, context: RunContext) -> StepCheckResult:
        """Validate driver connection, load specs, and named selections."""
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

        for lc in context.spec.load_cases:
            for load_kind, loads in [
                ("force", lc.forces),
                ("pressure", lc.pressures),
            ]:
                for idx, load_spec in enumerate(loads):
                    entity_label = (
                        f"load_case={lc.case_id!r} {load_kind}[{idx}] "
                        f"selection={getattr(load_spec, 'selection', None)!r}"
                    )

                    err_reason = _validate_numeric_load_fields(
                        getattr(load_spec, "magnitude", None),
                        getattr(load_spec, "direction", None),
                    )
                    if err_reason is not None:
                        result.add_failure(
                            FailureObject(
                                error_code=ERR_LOAD_INVALID_SPEC,
                                severity=Severity.BLOCKING,
                                step_id=STEP_ID,
                                component_or_entity=entity_label,
                                engineering_message=(
                                    f"Invalid {load_kind}[{idx}] in case '{lc.case_id}': "
                                    f"{err_reason}."
                                ),
                                likely_causes=["Non-finite or malformed load specification."],
                                suggested_fixes=[
                                    "Provide finite magnitude and valid 3D direction."
                                ],
                                resume_step_id=STEP_ID,
                            )
                        )
                        continue

                    selection = getattr(load_spec, "selection", None)
                    if not selection or not selection.strip():
                        result.add_failure(
                            FailureObject(
                                error_code=ERR_LOAD_INVALID_SPEC,
                                severity=Severity.BLOCKING,
                                step_id=STEP_ID,
                                component_or_entity=entity_label,
                                engineering_message=(
                                    f"Load spec for {load_kind}[{idx}] in case "
                                    f"'{lc.case_id}' has an empty selection."
                                ),
                                likely_causes=["Spec authoring error — selection field blank."],
                                suggested_fixes=[
                                    "Provide a valid named selection string in JobSpec."
                                ],
                                resume_step_id=STEP_ID,
                            )
                        )
                        continue

                    sel = selection.strip()

                    if not context.driver.has_named_selection(sel):
                        result.add_failure(
                            FailureObject(
                                error_code=ERR_LOAD_MISSING_SELECTION,
                                severity=Severity.BLOCKING,
                                step_id=STEP_ID,
                                component_or_entity=entity_label,
                                measured_value=None,
                                expected_value=sel,
                                engineering_message=(
                                    f"Named selection '{sel}' for {load_kind}[{idx}] "
                                    f"in case '{lc.case_id}' does not exist."
                                ),
                                likely_causes=[
                                    "Named selection not transferred from SpaceClaim.",
                                    "Spelling mismatch between JobSpec and CAD model.",
                                ],
                                suggested_fixes=[
                                    f"Create named selection '{sel}' in SpaceClaim.",
                                    "Check for typos in JobSpec.",
                                ],
                                resume_step_id=STEP_ID,
                            )
                        )
                        continue

                    entities = context.driver.get_named_selection_entities(sel)
                    if not entities:
                        result.add_failure(
                            FailureObject(
                                error_code=ERR_LOAD_EMPTY_SELECTION,
                                severity=Severity.BLOCKING,
                                step_id=STEP_ID,
                                component_or_entity=entity_label,
                                measured_value=0,
                                expected_value=">0 entities",
                                engineering_message=(
                                    f"Named selection '{sel}' exists but is empty "
                                    f"({load_kind}[{idx}] in case '{lc.case_id}')."
                                ),
                                likely_causes=[
                                    "Geometry was suppressed after selection was scoped.",
                                ],
                                suggested_fixes=[
                                    f"Re-scope '{sel}' to include at least one entity.",
                                ],
                                resume_step_id=STEP_ID,
                            )
                        )

            for idx, acc_spec in enumerate(lc.accelerations):
                entity_label = f"load_case={lc.case_id!r} acceleration[{idx}]"
                err_reason = _validate_numeric_load_fields(
                    getattr(acc_spec, "magnitude", None),
                    getattr(acc_spec, "direction", None),
                )
                if err_reason is not None:
                    result.add_failure(
                        FailureObject(
                            error_code=ERR_LOAD_INVALID_SPEC,
                            severity=Severity.BLOCKING,
                            step_id=STEP_ID,
                            component_or_entity=entity_label,
                            engineering_message=(
                                f"Invalid acceleration[{idx}] in case '{lc.case_id}': {err_reason}."
                            ),
                            likely_causes=["Non-finite or malformed acceleration specification."],
                            suggested_fixes=["Provide finite magnitude and valid 3D direction."],
                            resume_step_id=STEP_ID,
                        )
                    )
                    continue

                selection = getattr(acc_spec, "selection", None)
                if selection and selection.strip():
                    sel = selection.strip()
                    entity_label = f"load_case={lc.case_id!r} acceleration[{idx}] selection={sel!r}"
                    if not context.driver.has_named_selection(sel):
                        result.add_failure(
                            FailureObject(
                                error_code=ERR_LOAD_MISSING_SELECTION,
                                severity=Severity.BLOCKING,
                                step_id=STEP_ID,
                                component_or_entity=entity_label,
                                measured_value=None,
                                expected_value=sel,
                                engineering_message=(
                                    f"Named selection '{sel}' for acceleration[{idx}] "
                                    f"in case '{lc.case_id}' does not exist."
                                ),
                                likely_causes=["Named selection not in solver model."],
                                suggested_fixes=[f"Create named selection '{sel}'."],
                                resume_step_id=STEP_ID,
                            )
                        )

        return result

    # ------------------------------------------------------------------
    # Phase 2 — Execute
    # ------------------------------------------------------------------

    def execute(self, context: RunContext) -> None:
        """Apply all loads from every load case in JobSpec via the driver."""
        if hasattr(context.driver, "is_connected") and not context.driver.is_connected():
            raise ConnectionError("Mechanical driver is not connected.")

        for lc in context.spec.load_cases:
            for idx, force_spec in enumerate(lc.forces):
                selection = getattr(force_spec, "selection", None)
                if not selection or not selection.strip():
                    continue
                name = getattr(force_spec, "name", None) or f"Force_{lc.case_id}_{idx + 1}"
                context.driver.apply_force(
                    case_id=lc.case_id,
                    selection=selection.strip(),
                    magnitude=force_spec.magnitude,
                    direction=list(force_spec.direction),
                    coordinate_system=(
                        getattr(force_spec, "coordinate_system", "Global") or "Global"
                    ),
                    name=name,
                )

            for idx, pres_spec in enumerate(lc.pressures):
                selection = getattr(pres_spec, "selection", None)
                if not selection or not selection.strip():
                    continue
                name = getattr(pres_spec, "name", None) or f"Pressure_{lc.case_id}_{idx + 1}"
                context.driver.apply_pressure(
                    case_id=lc.case_id,
                    selection=selection.strip(),
                    magnitude=pres_spec.magnitude,
                    direction=list(pres_spec.direction),
                    coordinate_system=(
                        getattr(pres_spec, "coordinate_system", "Global") or "Global"
                    ),
                    name=name,
                )

            for idx, acc_spec in enumerate(lc.accelerations):
                selection = getattr(acc_spec, "selection", None)
                name = getattr(acc_spec, "name", None) or f"Accel_{lc.case_id}_{idx + 1}"
                context.driver.apply_acceleration(
                    case_id=lc.case_id,
                    magnitude=acc_spec.magnitude,
                    direction=list(acc_spec.direction),
                    selection=selection.strip() if selection and selection.strip() else None,
                    coordinate_system=(
                        getattr(acc_spec, "coordinate_system", "Global") or "Global"
                    ),
                    name=name,
                )

    # ------------------------------------------------------------------
    # Phase 3 — Post-check
    # ------------------------------------------------------------------

    def post_check(self, context: RunContext) -> StepCheckResult:
        """Verify applied loads match spec magnitudes, signs, directions, and CS."""
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

        tol = _LOAD_TOLERANCE
        dir_tol = _DIRECTION_TOLERANCE
        if context.spec.tolerances:
            if getattr(context.spec.tolerances, "load_tolerance", None) is not None:
                tol = context.spec.tolerances.load_tolerance
            if getattr(context.spec.tolerances, "direction_tolerance", None) is not None:
                dir_tol = context.spec.tolerances.direction_tolerance

        for lc in context.spec.load_cases:
            applied = context.driver.get_loads(case_id=lc.case_id)
            applied_by_name: dict[str, LoadRecord] = {ld.name: ld for ld in applied if ld.name}

            for idx, force_spec in enumerate(lc.forces):
                selection = getattr(force_spec, "selection", None)
                if not selection or not selection.strip():
                    continue
                name = getattr(force_spec, "name", None) or f"Force_{lc.case_id}_{idx + 1}"
                expected_cs = getattr(force_spec, "coordinate_system", "Global") or "Global"
                entity_label = f"load_case={lc.case_id!r} force[{idx}] name={name!r}"

                if name not in applied_by_name:
                    result.add_failure(
                        FailureObject(
                            error_code=ERR_LOAD_MISSING_LOAD,
                            severity=Severity.BLOCKING,
                            step_id=STEP_ID,
                            component_or_entity=entity_label,
                            engineering_message=(
                                f"Force '{name}' was not found in applied loads "
                                f"for case '{lc.case_id}'."
                            ),
                            likely_causes=["apply_force failed or was skipped."],
                            suggested_fixes=["Re-run execute phase."],
                            resume_step_id=STEP_ID,
                        )
                    )
                    continue

                rec = applied_by_name[name]
                self._check_magnitude(result, rec, force_spec.magnitude, tol, entity_label)
                self._check_direction(result, rec, force_spec.direction, dir_tol, entity_label)
                self._check_coordinate_system(result, rec, expected_cs, entity_label)

            for idx, pres_spec in enumerate(lc.pressures):
                selection = getattr(pres_spec, "selection", None)
                if not selection or not selection.strip():
                    continue
                name = getattr(pres_spec, "name", None) or f"Pressure_{lc.case_id}_{idx + 1}"
                expected_cs = getattr(pres_spec, "coordinate_system", "Global") or "Global"
                entity_label = f"load_case={lc.case_id!r} pressure[{idx}] name={name!r}"

                if name not in applied_by_name:
                    result.add_failure(
                        FailureObject(
                            error_code=ERR_LOAD_MISSING_LOAD,
                            severity=Severity.BLOCKING,
                            step_id=STEP_ID,
                            component_or_entity=entity_label,
                            engineering_message=(
                                f"Pressure '{name}' was not found in applied loads "
                                f"for case '{lc.case_id}'."
                            ),
                            likely_causes=["apply_pressure failed or was skipped."],
                            suggested_fixes=["Re-run execute phase."],
                            resume_step_id=STEP_ID,
                        )
                    )
                    continue

                rec = applied_by_name[name]
                self._check_magnitude(result, rec, pres_spec.magnitude, tol, entity_label)
                self._check_coordinate_system(result, rec, expected_cs, entity_label)

            for idx, acc_spec in enumerate(lc.accelerations):
                name = getattr(acc_spec, "name", None) or f"Accel_{lc.case_id}_{idx + 1}"
                expected_cs = getattr(acc_spec, "coordinate_system", "Global") or "Global"
                entity_label = f"load_case={lc.case_id!r} acceleration[{idx}] name={name!r}"

                if name not in applied_by_name:
                    result.add_failure(
                        FailureObject(
                            error_code=ERR_LOAD_MISSING_LOAD,
                            severity=Severity.BLOCKING,
                            step_id=STEP_ID,
                            component_or_entity=entity_label,
                            engineering_message=(
                                f"Acceleration '{name}' was not found in applied loads "
                                f"for case '{lc.case_id}'."
                            ),
                            likely_causes=["apply_acceleration failed or was skipped."],
                            suggested_fixes=["Re-run execute phase."],
                            resume_step_id=STEP_ID,
                        )
                    )
                    continue

                rec = applied_by_name[name]
                self._check_magnitude(result, rec, acc_spec.magnitude, tol, entity_label)
                self._check_direction(result, rec, acc_spec.direction, dir_tol, entity_label)
                self._check_coordinate_system(result, rec, expected_cs, entity_label)

        return result

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _check_magnitude(
        self,
        result: StepCheckResult,
        applied_load: LoadRecord,
        expected_magnitude: float,
        tol: float,
        entity_label: str,
    ) -> None:
        applied_mag = applied_load.magnitude

        if (
            expected_magnitude != 0.0
            and applied_mag != 0.0
            and (expected_magnitude > 0) != (applied_mag > 0)
        ):
            result.add_failure(
                FailureObject(
                    error_code=ERR_LOAD_SIGN_MISMATCH,
                    severity=Severity.BLOCKING,
                    step_id=STEP_ID,
                    component_or_entity=entity_label,
                    measured_value=applied_mag,
                    expected_value=expected_magnitude,
                    engineering_message=(
                        f"{entity_label}: load sign mismatch — "
                        f"applied {applied_mag:+.4g}, expected {expected_magnitude:+.4g}."
                    ),
                    likely_causes=["Sign error in JobSpec or fault injection."],
                    suggested_fixes=[
                        "Verify the sign convention of the load in JobSpec.",
                        "Re-apply the load with the correct sign.",
                    ],
                    resume_step_id=STEP_ID,
                )
            )

        rel_err = _relative_error(applied_mag, expected_magnitude)
        if rel_err > tol:
            result.add_failure(
                FailureObject(
                    error_code=ERR_LOAD_TOTAL_MISMATCH,
                    severity=Severity.BLOCKING,
                    step_id=STEP_ID,
                    component_or_entity=entity_label,
                    measured_value=applied_mag,
                    expected_value=expected_magnitude,
                    engineering_message=(
                        f"{entity_label}: load magnitude mismatch — "
                        f"applied {applied_mag:.4g}, expected {expected_magnitude:.4g} "
                        f"(rel err {rel_err:.2%} > tol {tol:.2%})."
                    ),
                    likely_causes=[
                        "Magnitude was altered after apply.",
                        "Fault injection changed the magnitude.",
                    ],
                    suggested_fixes=[
                        "Re-apply load with the correct magnitude.",
                    ],
                    resume_step_id=STEP_ID,
                )
            )

    def _check_direction(
        self,
        result: StepCheckResult,
        applied_load: LoadRecord,
        expected_direction: list[float],
        dir_tol: float,
        entity_label: str,
    ) -> None:
        applied_dir = applied_load.direction
        angle = _angular_deviation_rad(applied_dir, expected_direction)
        if angle > dir_tol:
            result.add_failure(
                FailureObject(
                    error_code=ERR_LOAD_DIRECTION_MISMATCH,
                    severity=Severity.BLOCKING,
                    step_id=STEP_ID,
                    component_or_entity=entity_label,
                    measured_value=applied_dir,
                    expected_value=expected_direction,
                    engineering_message=(
                        f"{entity_label}: load direction mismatch — "
                        f"angular deviation {angle:.6g} rad > tol {dir_tol:.6g}."
                    ),
                    likely_causes=[
                        "Direction vector was altered after apply.",
                        "Coordinate system mismatch.",
                    ],
                    suggested_fixes=[
                        "Re-apply load with the correct direction vector.",
                        "Verify coordinate system is consistent.",
                    ],
                    resume_step_id=STEP_ID,
                )
            )

    def _check_coordinate_system(
        self,
        result: StepCheckResult,
        applied_load: LoadRecord,
        expected_cs: str,
        entity_label: str,
    ) -> None:
        if applied_load.coordinate_system != expected_cs:
            result.add_failure(
                FailureObject(
                    error_code=ERR_LOAD_COORDINATE_SYSTEM_MISMATCH,
                    severity=Severity.BLOCKING,
                    step_id=STEP_ID,
                    component_or_entity=entity_label,
                    measured_value=applied_load.coordinate_system,
                    expected_value=expected_cs,
                    engineering_message=(
                        f"{entity_label}: coordinate system mismatch — "
                        f"applied '{applied_load.coordinate_system}', expected '{expected_cs}'."
                    ),
                    likely_causes=["Coordinate system mismatch in solver model."],
                    suggested_fixes=["Re-apply load using the expected coordinate system."],
                    resume_step_id=STEP_ID,
                )
            )

    # ------------------------------------------------------------------
    # Phase 4 — Troubleshoot
    # ------------------------------------------------------------------

    def troubleshoot(
        self, context: RunContext, check_result: StepCheckResult
    ) -> list[FailureObject]:
        """Annotate failures with additional root-cause context."""
        enriched: list[FailureObject] = []
        for f in check_result.failures:
            if f.error_code == ERR_LOAD_MISSING_SELECTION:
                f.likely_causes.append(
                    "Named selection may not have been created in SpaceClaim — "
                    "check geometry import log."
                )
            elif f.error_code == ERR_LOAD_TOTAL_MISMATCH:
                f.suggested_fixes.append(
                    "Clear existing loads in this case and re-run Step 10 from execute."
                )
            elif f.error_code == ERR_LOAD_DIRECTION_MISMATCH:
                f.suggested_fixes.append(
                    "Confirm direction is specified in the Global coordinate system "
                    "or update coordinate_system field in JobSpec."
                )
            enriched.append(f)
        return enriched

"""
Meshtrix Phase 2 Tier 2: Boundary, Edge & Corner Cases E2E Test Suite.

Authoritative Reference: ORIGINAL_REQUEST.md & PROJECT.md § Interface Contracts
Features Tested (26 tests):
- Area 2A: Step09BoundaryConditions & SupportSpec boundaries (7 tests)
- Area 2B: Step10Loads, LoadSpec/AccelerationSpec, & tolerance boundaries (7 tests)
- Area 2C: PipelineRunner, CheckpointManager, & backward compatibility boundaries (6 tests)
- Area 2D: meshtrix.cli negative paths and error exit codes (6 tests)
"""

import inspect
import json
import math
from collections.abc import Callable
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError
from typer.testing import CliRunner

from meshtrix.core.step import RunContext
from meshtrix.diagnostics.failure import ERR_DRIVER_COMMUNICATION, Severity
from meshtrix.drivers.mock import MockMechanicalDriver
from meshtrix.spec.job_spec import (
    AnalysisType,
    CheckTolerances,
    JobSpec,
    LoadSpec,
    SupportSpec,
)
from tests.conftest import assert_check_failed, assert_check_passed

# ---------------------------------------------------------------------------
# Self-Contained Phase 2 Boundary Helpers & Fixtures
# ---------------------------------------------------------------------------


def _base_boundary_spec_dict() -> dict[str, Any]:
    """Return a clean, self-contained Phase 2 JobSpec dictionary for boundary tests."""
    return {
        "job_id": "JOB-P2-TIER2-001",
        "units": "Metric_mm",
        "analysis_type": "STRUCTURAL_STATIC",
        "materials": {
            "catalog": {
                "Structural_Steel": {
                    "name": "Structural_Steel",
                    "density": 7.85e-9,
                    "elastic_modulus": 200000.0,
                    "poissons_ratio": 0.30,
                    "yield_strength": 250.0,
                },
                "Aluminum_6061_T6": {
                    "name": "Aluminum_6061_T6",
                    "density": 2.70e-9,
                    "elastic_modulus": 68900.0,
                    "poissons_ratio": 0.33,
                    "yield_strength": 276.0,
                },
            },
            "mappings": {
                "Bracket_Solid_Base": {
                    "body_name": "Bracket_Solid_Base",
                    "material_name": "Structural_Steel",
                    "thickness": None,
                },
                "Web_Plate_Upper": {
                    "body_name": "Web_Plate_Upper",
                    "material_name": "Aluminum_6061_T6",
                    "thickness": 2.5,
                },
            },
        },
        "mesh": {
            "global_size": 5.0,
            "element_order": "quadratic",
            "min_quality": 0.25,
            "quality_metric": "skewness",
        },
        "tolerances": {
            "thickness_tolerance": 0.01,
            "mass_tolerance": 0.05,
            "load_tolerance": 0.01,
            "direction_tolerance": 1e-4,
        },
        "load_cases": [
            {
                "case_id": "LC1_Tension",
                "forces": [
                    {
                        "selection": "NS_LUG_HOLE",
                        "magnitude": 10000.0,
                        "direction": [0.0, 1.0, 0.0],
                        "load_type": "force",
                        "coordinate_system": "Global",
                        "name": "NS_LUG_HOLE",
                    }
                ],
                "pressures": [],
                "accelerations": [],
            }
        ],
        "supports": [
            {
                "selection": "NS_BASE_FACES",
                "type": "fixed",
                "coordinate_system": "Global",
                "name": "NS_BASE_FACES",
            }
        ],
    }


def _build_driver_with_selections(
    named_selections: dict[str, list[str]] | None = None,
) -> MockMechanicalDriver:
    """Build a MockMechanicalDriver seeded with standard bodies and named selections."""
    driver = MockMechanicalDriver()
    driver.add_body(name="Bracket_Solid_Base", body_type="solid", thickness=None)
    driver.add_body(name="Web_Plate_Upper", body_type="surface", thickness=None)
    if named_selections:
        for ns_name, entities in named_selections.items():
            driver.create_named_selection(ns_name, entities)
    return driver


def _invoke_load_fault(
    fn: Callable[..., Any],
    case_id: str,
    selection: str,
    *extra: Any,
) -> None:
    """Invoke a MockMechanicalDriver load fault injector respecting its public signature."""
    params = list(inspect.signature(fn).parameters.keys())
    if params and params[0] == "case_id":
        if len(params) >= 2 and params[1] in ("selection", "name", "load_name", "identifier"):
            fn(case_id, selection, *extra)
        else:
            fn(case_id, *extra)
    else:
        fn(selection, *extra)


@pytest.fixture
def tier2_spec_dict() -> dict[str, Any]:
    """Fresh Phase 2 JobSpec dict per test."""
    return deepcopy(_base_boundary_spec_dict())


@pytest.fixture
def tier2_spec(tier2_spec_dict: dict[str, Any]) -> JobSpec:
    """Validated Phase 2 JobSpec model."""
    return JobSpec.model_validate(tier2_spec_dict)


# ===========================================================================
# Area 2A: Step09BoundaryConditions & SupportSpec Boundaries (7)
# ===========================================================================


class TestPhase2Tier2Step09Boundaries:
    """Tier 2 negative & boundary tests for Step 9 and SupportSpec."""

    def test_step09_missing_named_selection_fails_pre_check(self, tier2_spec: JobSpec) -> None:
        """T2-A1: Missing named selection fails Step09 pre_check with ERR_BC_MISSING_SELECTION."""
        from meshtrix.steps.step_09_boundary_conditions import Step09BoundaryConditions

        from meshtrix.diagnostics.failure import ERR_BC_MISSING_SELECTION

        step = Step09BoundaryConditions()

        # Case 1: Named selection never registered in driver
        driver_unreg = _build_driver_with_selections({})
        ctx_unreg = RunContext(spec=tier2_spec, driver=driver_unreg)
        res_unreg = step.pre_check(ctx_unreg)
        assert_check_failed(res_unreg, ERR_BC_MISSING_SELECTION)
        assert all(f.severity == Severity.BLOCKING for f in res_unreg.failures)
        diagnosed = step.troubleshoot(ctx_unreg, res_unreg)
        assert any(f.error_code == ERR_BC_MISSING_SELECTION for f in diagnosed)

        # Case 2: Named selection registered then fault-injected as missing
        driver_inj = _build_driver_with_selections({"NS_BASE_FACES": ["Face_1"]})
        driver_inj.inject_missing_named_selection("NS_BASE_FACES")
        ctx_inj = RunContext(spec=tier2_spec, driver=driver_inj)
        res_inj = step.pre_check(ctx_inj)
        assert_check_failed(res_inj, ERR_BC_MISSING_SELECTION)

    def test_step09_empty_named_selection_fails_pre_check(self, tier2_spec: JobSpec) -> None:
        """T2-A2: Empty named selection fails Step09 pre_check with ERR_BC_EMPTY_SELECTION."""
        from meshtrix.steps.step_09_boundary_conditions import Step09BoundaryConditions

        from meshtrix.diagnostics.failure import ERR_BC_EMPTY_SELECTION

        step = Step09BoundaryConditions()

        # Case 1: Named selection exists with zero entities
        driver_empty = _build_driver_with_selections({"NS_BASE_FACES": []})
        ctx_empty = RunContext(spec=tier2_spec, driver=driver_empty)
        res_empty = step.pre_check(ctx_empty)
        assert_check_failed(res_empty, ERR_BC_EMPTY_SELECTION)
        assert any(f.severity == Severity.BLOCKING for f in res_empty.failures)

        # Case 2: Non-empty named selection corrupted via inject_empty_named_selection
        driver_inj = _build_driver_with_selections({"NS_BASE_FACES": ["Face_1", "Face_2"]})
        driver_inj.inject_empty_named_selection("NS_BASE_FACES")
        ctx_inj = RunContext(spec=tier2_spec, driver=driver_inj)
        res_inj = step.pre_check(ctx_inj)
        assert_check_failed(res_inj, ERR_BC_EMPTY_SELECTION)

    def test_step09_support_scoping_mismatch_fails_post_check(self, tier2_spec: JobSpec) -> None:
        """T2-A3: Injected support scoping mismatch fails post_check with ERR_BC_SCOPING_MISMATCH."""
        from meshtrix.steps.step_09_boundary_conditions import Step09BoundaryConditions

        from meshtrix.diagnostics.failure import ERR_BC_SCOPING_MISMATCH

        driver = _build_driver_with_selections(
            {"NS_BASE_FACES": ["Face_1"], "NS_WRONG_FACE": ["Face_99"]}
        )
        context = RunContext(spec=tier2_spec, driver=driver)
        step = Step09BoundaryConditions()

        assert_check_passed(step.pre_check(context))
        step.execute(context)
        driver.inject_support_scoping_error("NS_BASE_FACES", "NS_WRONG_FACE")

        post = step.post_check(context)
        assert_check_failed(post, ERR_BC_SCOPING_MISMATCH)
        assert any(f.severity == Severity.BLOCKING for f in post.failures)
        failures = step.troubleshoot(context, post)
        assert any(
            f.error_code == ERR_BC_SCOPING_MISMATCH and "NS_BASE_FACES" in f.component_or_entity
            for f in failures
        )

    def test_step09_support_dof_mismatch_fails_post_check(self, tier2_spec: JobSpec) -> None:
        """T2-A4: Injected DOF mismatch on fixed support fails with ERR_BC_DOF_MISMATCH."""
        from meshtrix.steps.step_09_boundary_conditions import Step09BoundaryConditions

        from meshtrix.diagnostics.failure import ERR_BC_DOF_MISMATCH

        driver = _build_driver_with_selections({"NS_BASE_FACES": ["Face_1"]})
        context = RunContext(spec=tier2_spec, driver=driver)
        step = Step09BoundaryConditions()

        assert_check_passed(step.pre_check(context))
        step.execute(context)
        driver.inject_support_dof_error("NS_BASE_FACES", ["UX", "UY"])

        post = step.post_check(context)
        assert_check_failed(post, ERR_BC_DOF_MISMATCH)
        assert any(f.severity == Severity.BLOCKING for f in post.failures)

    def test_step09_support_coordinate_system_and_missing_support_faults(
        self, tier2_spec: JobSpec
    ) -> None:
        """T2-A5: CS mismatch and missing support faults produce exact ERR_BC_* codes."""
        from meshtrix.steps.step_09_boundary_conditions import Step09BoundaryConditions

        from meshtrix.diagnostics.failure import (
            ERR_BC_COORDINATE_SYSTEM_MISMATCH,
            ERR_BC_MISSING_SUPPORT,
        )

        step = Step09BoundaryConditions()

        # Case 1: Coordinate system mismatch
        driver_cs = _build_driver_with_selections({"NS_BASE_FACES": ["Face_1"]})
        ctx_cs = RunContext(spec=tier2_spec, driver=driver_cs)
        assert_check_passed(step.pre_check(ctx_cs))
        step.execute(ctx_cs)
        driver_cs.inject_support_coordinate_system_error("NS_BASE_FACES", "Cylindrical_Wrong")
        post_cs = step.post_check(ctx_cs)
        assert_check_failed(post_cs, ERR_BC_COORDINATE_SYSTEM_MISMATCH)
        assert any(f.severity == Severity.BLOCKING for f in post_cs.failures)

        # Case 2: Missing support in solver model
        driver_miss = _build_driver_with_selections({"NS_BASE_FACES": ["Face_1"]})
        ctx_miss = RunContext(spec=tier2_spec, driver=driver_miss)
        assert_check_passed(step.pre_check(ctx_miss))
        step.execute(ctx_miss)
        driver_miss.inject_missing_support("NS_BASE_FACES")
        post_miss = step.post_check(ctx_miss)
        assert_check_failed(post_miss, ERR_BC_MISSING_SUPPORT)
        assert any(f.severity == Severity.BLOCKING for f in post_miss.failures)

    def test_step09_modal_free_free_vs_structural_static_empty_supports(
        self, tier2_spec_dict: dict[str, Any]
    ) -> None:
        """T2-A6: MODAL free-free (supports=[]) passes, whereas STRUCTURAL_STATIC rejects it."""
        from meshtrix.steps.step_09_boundary_conditions import Step09BoundaryConditions

        from meshtrix.diagnostics.failure import ERR_BC_INVALID_SPEC

        step = Step09BoundaryConditions()

        # MODAL free-free analysis
        modal_dict = deepcopy(tier2_spec_dict)
        modal_dict["analysis_type"] = AnalysisType.MODAL.value
        modal_dict["supports"] = []
        modal_dict["load_cases"] = []
        modal_spec = JobSpec.model_validate(modal_dict)
        modal_driver = _build_driver_with_selections({})
        modal_ctx = RunContext(spec=modal_spec, driver=modal_driver)
        assert_check_passed(step.pre_check(modal_ctx))
        step.execute(modal_ctx)
        assert_check_passed(step.post_check(modal_ctx))

        # STRUCTURAL_STATIC with empty supports must fail pre_check
        static_dict = deepcopy(tier2_spec_dict)
        static_dict["analysis_type"] = AnalysisType.STRUCTURAL_STATIC.value
        static_dict["supports"] = []
        static_spec = JobSpec.model_validate(static_dict)
        static_driver = _build_driver_with_selections({})
        static_ctx = RunContext(spec=static_spec, driver=static_driver)
        static_res = step.pre_check(static_ctx)
        assert_check_failed(static_res, ERR_BC_INVALID_SPEC)
        assert any(f.severity == Severity.BLOCKING for f in static_res.failures)

    def test_step09_nan_inf_displacement_and_disconnected_driver(self, tier2_spec: JobSpec) -> None:
        """T2-A7: NaN/Inf displacement_values and disconnected driver are rejected cleanly."""
        from meshtrix.steps.step_09_boundary_conditions import Step09BoundaryConditions

        from meshtrix.diagnostics.failure import ERR_BC_INVALID_SPEC

        for bad_val in (float("nan"), float("inf"), float("-inf")):
            with pytest.raises(ValidationError):
                SupportSpec(
                    selection="NS_BASE_FACES",
                    type="displacement",
                    dofs=["UX"],
                    displacement_values={"UX": bad_val},
                )

        # Bypass Pydantic validation via model_construct to verify Step09 pre_check defense
        step = Step09BoundaryConditions()
        bad_spec = tier2_spec.model_copy(
            update={
                "supports": [
                    SupportSpec.model_construct(
                        selection="NS_BASE_FACES",
                        type="displacement",
                        dofs=["UX"],
                        displacement_values={"UX": float("nan")},
                        coordinate_system="Global",
                        name="Bad_Disp",
                    )
                ]
            }
        )
        driver = _build_driver_with_selections({"NS_BASE_FACES": ["Face_1"]})
        bad_res = step.pre_check(RunContext(spec=bad_spec, driver=driver))
        assert_check_failed(bad_res, ERR_BC_INVALID_SPEC)

        # Disconnected driver behavior across pre_check, execute, post_check
        driver.disconnect()
        disconn_ctx = RunContext(spec=tier2_spec, driver=driver)
        assert_check_failed(step.pre_check(disconn_ctx), ERR_DRIVER_COMMUNICATION)
        with pytest.raises(ConnectionError):
            step.execute(disconn_ctx)
        assert_check_failed(step.post_check(disconn_ctx), ERR_DRIVER_COMMUNICATION)


# ===========================================================================
# Area 2B: Step10Loads, LoadSpec/AccelerationSpec & Tolerance Boundaries (7)
# ===========================================================================


class TestPhase2Tier2Step10Boundaries:
    """Tier 2 negative & boundary tests for Step 10, LoadSpec, and AccelerationSpec."""

    def test_step10_missing_and_empty_load_named_selections(
        self, tier2_spec_dict: dict[str, Any]
    ) -> None:
        """T2-B1: Missing or empty named selections fail Step10 pre_check with ERR_LOAD_*."""
        from meshtrix.steps.step_10_loads import Step10Loads

        from meshtrix.diagnostics.failure import (
            ERR_LOAD_EMPTY_SELECTION,
            ERR_LOAD_MISSING_SELECTION,
        )

        step = Step10Loads()
        spec = JobSpec.model_validate(tier2_spec_dict)

        # Case 1: Missing NS (never created)
        driver_miss = _build_driver_with_selections({})
        res_miss = step.pre_check(RunContext(spec=spec, driver=driver_miss))
        assert_check_failed(res_miss, ERR_LOAD_MISSING_SELECTION)
        assert any(f.severity == Severity.BLOCKING for f in res_miss.failures)

        # Case 2: Empty NS
        driver_empty = _build_driver_with_selections({"NS_LUG_HOLE": []})
        res_empty = step.pre_check(RunContext(spec=spec, driver=driver_empty))
        assert_check_failed(res_empty, ERR_LOAD_EMPTY_SELECTION)
        assert any(f.severity == Severity.BLOCKING for f in res_empty.failures)

    def test_step10_zero_direction_vector_and_wrong_arity_rejected(
        self, tier2_spec: JobSpec
    ) -> None:
        """T2-B2: Zero direction vector and wrong vector arity are rejected at schema & pre_check."""
        from meshtrix.steps.step_10_loads import Step10Loads

        from meshtrix.diagnostics.failure import ERR_LOAD_INVALID_SPEC
        from meshtrix.spec.job_spec import AccelerationSpec

        for bad_dir in ([0.0, 0.0, 0.0], [1.0, 0.0], [1.0, 0.0, 0.0, 0.0]):
            with pytest.raises(ValidationError):
                LoadSpec(selection="NS_LUG_HOLE", magnitude=1000.0, direction=bad_dir)
            with pytest.raises(ValidationError):
                AccelerationSpec(magnitude=9810.0, direction=bad_dir)

        step = Step10Loads()
        driver = _build_driver_with_selections({"NS_LUG_HOLE": ["Face_1"]})

        # Bypass schema via model_construct
        bad_force = LoadSpec.model_construct(
            selection="NS_LUG_HOLE",
            magnitude=1000.0,
            direction=[0.0, 0.0, 0.0],
            load_type="force",
            coordinate_system="Global",
            name="Zero_Dir_Force",
        )
        bad_lc = tier2_spec.load_cases[0].model_copy(update={"forces": [bad_force]})
        bad_spec = tier2_spec.model_copy(update={"load_cases": [bad_lc]})
        res = step.pre_check(RunContext(spec=bad_spec, driver=driver))
        assert_check_failed(res, ERR_LOAD_INVALID_SPEC)

    def test_step10_nan_and_inf_in_load_magnitude_or_direction(self, tier2_spec: JobSpec) -> None:
        """T2-B3: NaN/Inf in load magnitude or direction rejected cleanly without exceptions."""
        from meshtrix.steps.step_10_loads import Step10Loads

        from meshtrix.diagnostics.failure import ERR_LOAD_INVALID_SPEC
        from meshtrix.spec.job_spec import AccelerationSpec

        for bad_float in (float("nan"), float("inf"), float("-inf")):
            with pytest.raises(ValidationError):
                LoadSpec(
                    selection="NS_LUG_HOLE",
                    magnitude=bad_float,
                    direction=[0.0, 1.0, 0.0],
                )
            with pytest.raises(ValidationError):
                LoadSpec(
                    selection="NS_LUG_HOLE",
                    magnitude=1000.0,
                    direction=[bad_float, 1.0, 0.0],
                )
            with pytest.raises(ValidationError):
                AccelerationSpec(magnitude=bad_float, direction=[0.0, 0.0, -1.0])
            with pytest.raises(ValidationError):
                AccelerationSpec(magnitude=9810.0, direction=[0.0, bad_float, -1.0])

        step = Step10Loads()
        driver = _build_driver_with_selections({"NS_LUG_HOLE": ["Face_1"]})
        nan_accel = AccelerationSpec.model_construct(
            magnitude=float("nan"),
            direction=[0.0, 0.0, -1.0],
            selection=None,
            coordinate_system="Global",
            name="NaN_Accel",
            load_type="acceleration",
        )
        bad_lc = tier2_spec.load_cases[0].model_copy(
            update={"forces": [], "accelerations": [nan_accel]}
        )
        bad_spec = tier2_spec.model_copy(update={"load_cases": [bad_lc]})
        res = step.pre_check(RunContext(spec=bad_spec, driver=driver))
        assert_check_failed(res, ERR_LOAD_INVALID_SPEC)

    def test_step10_zero_negative_and_canceling_loads(
        self, tier2_spec_dict: dict[str, Any]
    ) -> None:
        """T2-B4: Canceling load pairs, negative suction pressure, and zero loads avoid ZeroDivisionError."""
        from meshtrix.steps.step_10_loads import Step10Loads

        from meshtrix.diagnostics.failure import ERR_LOAD_INVALID_SPEC

        step = Step10Loads()

        # (i) Canceling equal-and-opposite pair + (ii) negative suction pressure
        cancel_dict = deepcopy(tier2_spec_dict)
        cancel_dict["load_cases"] = [
            {
                "case_id": "LC_Balanced",
                "forces": [
                    {
                        "selection": "NS_LUG_A",
                        "magnitude": 5000.0,
                        "direction": [1.0, 0.0, 0.0],
                        "name": "F_Plus_X",
                    },
                    {
                        "selection": "NS_LUG_B",
                        "magnitude": 5000.0,
                        "direction": [-1.0, 0.0, 0.0],
                        "name": "F_Minus_X",
                    },
                ],
                "pressures": [
                    {
                        "selection": "NS_SKIN",
                        "magnitude": -250.0,
                        "direction": [0.0, 0.0, 1.0],
                        "load_type": "pressure",
                        "name": "Suction_Pressure",
                    }
                ],
                "accelerations": [],
            }
        ]
        cancel_spec = JobSpec.model_validate(cancel_dict)
        driver = _build_driver_with_selections(
            {"NS_LUG_A": ["Face_A"], "NS_LUG_B": ["Face_B"], "NS_SKIN": ["Face_S"]}
        )
        ctx = RunContext(spec=cancel_spec, driver=driver)
        assert_check_passed(step.pre_check(ctx))
        step.execute(ctx)
        assert_check_passed(step.post_check(ctx))

        # (iii) Zero-magnitude load must never trigger ZeroDivisionError
        zero_dict = deepcopy(tier2_spec_dict)
        zero_dict["load_cases"] = [
            {
                "case_id": "LC_Zero",
                "forces": [
                    {
                        "selection": "NS_LUG_A",
                        "magnitude": 0.0,
                        "direction": [0.0, 0.0, 1.0],
                        "name": "Zero_Force",
                    }
                ],
                "pressures": [],
                "accelerations": [],
            }
        ]
        try:
            zero_spec = JobSpec.model_validate(zero_dict)
        except ValidationError:
            return
        zero_driver = _build_driver_with_selections({"NS_LUG_A": ["Face_A"]})
        zero_ctx = RunContext(spec=zero_spec, driver=zero_driver)
        pre = step.pre_check(zero_ctx)
        if pre.is_successful:
            step.execute(zero_ctx)
            post = step.post_check(zero_ctx)
            assert_check_passed(post)
        else:
            assert_check_failed(pre, ERR_LOAD_INVALID_SPEC)

    def test_step10_sign_inversion_and_direction_mismatch_faults(self, tier2_spec: JobSpec) -> None:
        """T2-B5: Sign inversion triggers ERR_LOAD_SIGN_MISMATCH; tilted direction triggers ERR_LOAD_DIRECTION_MISMATCH."""
        from meshtrix.steps.step_10_loads import Step10Loads

        from meshtrix.diagnostics.failure import (
            ERR_LOAD_DIRECTION_MISMATCH,
            ERR_LOAD_SIGN_MISMATCH,
        )

        step = Step10Loads()

        # Case 1: Sign inversion fault
        driver_sign = _build_driver_with_selections({"NS_LUG_HOLE": ["Face_1"]})
        ctx_sign = RunContext(spec=tier2_spec, driver=driver_sign)
        assert_check_passed(step.pre_check(ctx_sign))
        step.execute(ctx_sign)
        _invoke_load_fault(driver_sign.inject_load_sign_error, "LC1_Tension", "NS_LUG_HOLE")
        post_sign = step.post_check(ctx_sign)
        assert_check_failed(post_sign, ERR_LOAD_SIGN_MISMATCH)
        assert any(f.severity == Severity.BLOCKING for f in post_sign.failures)

        # Case 2: Direction mismatch fault (orthogonal [1, 0, 0] vs [0, 1, 0])
        driver_dir = _build_driver_with_selections({"NS_LUG_HOLE": ["Face_1"]})
        ctx_dir = RunContext(spec=tier2_spec, driver=driver_dir)
        assert_check_passed(step.pre_check(ctx_dir))
        step.execute(ctx_dir)
        _invoke_load_fault(
            driver_dir.inject_load_direction_error,
            "LC1_Tension",
            "NS_LUG_HOLE",
            [1.0, 0.0, 0.0],
        )
        post_dir = step.post_check(ctx_dir)
        assert_check_failed(post_dir, ERR_LOAD_DIRECTION_MISMATCH)
        assert any(f.severity == Severity.BLOCKING for f in post_dir.failures)

    def test_step10_load_and_direction_tolerance_boundaries(self, tier2_spec: JobSpec) -> None:
        """T2-B6: Magnitude and direction deviations pass within CheckTolerances and fail beyond."""
        from meshtrix.steps.step_10_loads import Step10Loads

        from meshtrix.diagnostics.failure import (
            ERR_LOAD_DIRECTION_MISMATCH,
            ERR_LOAD_TOTAL_MISMATCH,
        )

        step = Step10Loads()

        # Magnitude within 1% tolerance (+0.5% -> 10050.0)
        d_mag_ok = _build_driver_with_selections({"NS_LUG_HOLE": ["Face_1"]})
        ctx_mag_ok = RunContext(spec=tier2_spec, driver=d_mag_ok)
        assert_check_passed(step.pre_check(ctx_mag_ok))
        step.execute(ctx_mag_ok)
        _invoke_load_fault(
            d_mag_ok.inject_load_magnitude_error, "LC1_Tension", "NS_LUG_HOLE", 10050.0
        )
        assert_check_passed(step.post_check(ctx_mag_ok))

        # Magnitude outside 1% tolerance (+1.5% -> 10150.0)
        d_mag_bad = _build_driver_with_selections({"NS_LUG_HOLE": ["Face_1"]})
        ctx_mag_bad = RunContext(spec=tier2_spec, driver=d_mag_bad)
        assert_check_passed(step.pre_check(ctx_mag_bad))
        step.execute(ctx_mag_bad)
        _invoke_load_fault(
            d_mag_bad.inject_load_magnitude_error, "LC1_Tension", "NS_LUG_HOLE", 10150.0
        )
        assert_check_failed(step.post_check(ctx_mag_bad), ERR_LOAD_TOTAL_MISMATCH)

        # Direction within 1e-4 tolerance
        norm_ok = math.hypot(5e-5, 1.0)
        dir_ok = [5e-5 / norm_ok, 1.0 / norm_ok, 0.0]
        d_dir_ok = _build_driver_with_selections({"NS_LUG_HOLE": ["Face_1"]})
        ctx_dir_ok = RunContext(spec=tier2_spec, driver=d_dir_ok)
        assert_check_passed(step.pre_check(ctx_dir_ok))
        step.execute(ctx_dir_ok)
        _invoke_load_fault(
            d_dir_ok.inject_load_direction_error, "LC1_Tension", "NS_LUG_HOLE", dir_ok
        )
        assert_check_passed(step.post_check(ctx_dir_ok))

        # Direction outside 1e-4 tolerance
        norm_bad = math.hypot(0.01, 1.0)
        dir_bad = [0.01 / norm_bad, 1.0 / norm_bad, 0.0]
        d_dir_bad = _build_driver_with_selections({"NS_LUG_HOLE": ["Face_1"]})
        ctx_dir_bad = RunContext(spec=tier2_spec, driver=d_dir_bad)
        assert_check_passed(step.pre_check(ctx_dir_bad))
        step.execute(ctx_dir_bad)
        _invoke_load_fault(
            d_dir_bad.inject_load_direction_error, "LC1_Tension", "NS_LUG_HOLE", dir_bad
        )
        assert_check_failed(step.post_check(ctx_dir_bad), ERR_LOAD_DIRECTION_MISMATCH)

    def test_step10_cs_mismatch_missing_load_and_disconnected_driver(
        self, tier2_spec: JobSpec
    ) -> None:
        """T2-B7: Load CS mismatch, missing load, and disconnected driver yield exact errors."""
        from meshtrix.steps.step_10_loads import Step10Loads

        from meshtrix.diagnostics.failure import (
            ERR_LOAD_COORDINATE_SYSTEM_MISMATCH,
            ERR_LOAD_MISSING_LOAD,
        )

        step = Step10Loads()

        # CS mismatch
        d_cs = _build_driver_with_selections({"NS_LUG_HOLE": ["Face_1"]})
        ctx_cs = RunContext(spec=tier2_spec, driver=d_cs)
        assert_check_passed(step.pre_check(ctx_cs))
        step.execute(ctx_cs)
        _invoke_load_fault(
            d_cs.inject_load_coordinate_system_error,
            "LC1_Tension",
            "NS_LUG_HOLE",
            "Cylindrical_Wrong",
        )
        assert_check_failed(step.post_check(ctx_cs), ERR_LOAD_COORDINATE_SYSTEM_MISMATCH)

        # Missing load
        d_miss = _build_driver_with_selections({"NS_LUG_HOLE": ["Face_1"]})
        ctx_miss = RunContext(spec=tier2_spec, driver=d_miss)
        assert_check_passed(step.pre_check(ctx_miss))
        step.execute(ctx_miss)
        _invoke_load_fault(d_miss.inject_missing_load, "LC1_Tension", "NS_LUG_HOLE")
        assert_check_failed(step.post_check(ctx_miss), ERR_LOAD_MISSING_LOAD)

        # Disconnected driver
        d_disc = _build_driver_with_selections({"NS_LUG_HOLE": ["Face_1"]})
        d_disc.disconnect()
        ctx_disc = RunContext(spec=tier2_spec, driver=d_disc)
        assert_check_failed(step.pre_check(ctx_disc), ERR_DRIVER_COMMUNICATION)
        with pytest.raises(ConnectionError):
            step.execute(ctx_disc)
        assert_check_failed(step.post_check(ctx_disc), ERR_DRIVER_COMMUNICATION)


# ===========================================================================
# Area 2C: PipelineRunner, CheckpointManager, & Backward Compat Boundaries (6)
# ===========================================================================


class TestPhase2Tier2RunnerBoundaries:
    """Tier 2 boundary and failure tests for runner, checkpoints, and schema compat."""

    def test_runner_invalid_resume_from_step_id_rejected(
        self, tmp_path: Path, tier2_spec: JobSpec
    ) -> None:
        """T2-C1: Unknown resume_from step_id raises or returns failed PipelineResult."""
        from meshtrix.runner import PipelineRunner

        driver = _build_driver_with_selections(
            {"NS_BASE_FACES": ["Face_1"], "NS_LUG_HOLE": ["Face_2"]}
        )
        try:
            result = PipelineRunner().run(
                tier2_spec,
                driver,
                run_id="r_bad_step",
                resume_from="step_99_nonexistent",
                checkpoint_dir=tmp_path / "cp",
                log_dir=tmp_path / "logs",
            )
        except (ValueError, KeyError):
            return

        assert result.success is False
        assert result.status == "failed"

    def test_runner_resume_from_with_missing_prior_checkpoint_fails(
        self, tmp_path: Path, tier2_spec: JobSpec
    ) -> None:
        """T2-C2: Resuming without required prior checkpoint raises or returns failed result."""
        from meshtrix.runner import PipelineRunner

        driver = _build_driver_with_selections(
            {"NS_BASE_FACES": ["Face_1"], "NS_LUG_HOLE": ["Face_2"]}
        )
        try:
            result = PipelineRunner().run(
                tier2_spec,
                driver,
                run_id="r_missing_cp",
                resume_from="step_09_boundary_conditions",
                checkpoint_dir=tmp_path / "empty_cp",
                log_dir=tmp_path / "logs",
            )
        except (FileNotFoundError, ValueError, RuntimeError):
            return

        assert result.success is False
        assert result.status == "failed"

    def test_checkpoint_manager_load_nonexistent_raises_file_not_found(
        self, tmp_path: Path
    ) -> None:
        """T2-C3: CheckpointManager.load_checkpoint raises FileNotFoundError when missing."""
        from meshtrix.core.checkpoint import CheckpointManager

        cm = CheckpointManager(tmp_path / "cp")
        assert cm.has_checkpoint("missing_run", "step_06_materials") is False
        assert cm.list_checkpoints("missing_run") == []
        with pytest.raises(FileNotFoundError):
            cm.load_checkpoint("missing_run", "step_06_materials")

    def test_runner_disconnected_driver_fails_cleanly_and_writes_log(
        self, tmp_path: Path, tier2_spec: JobSpec
    ) -> None:
        """T2-C4: Disconnected driver fails cleanly in PipelineRunner and writes failed log."""
        from meshtrix.runner import PipelineRunner

        driver = _build_driver_with_selections(
            {"NS_BASE_FACES": ["Face_1"], "NS_LUG_HOLE": ["Face_2"]}
        )
        driver.disconnect()

        result = PipelineRunner().run(
            tier2_spec,
            driver,
            run_id="r_disconnected",
            checkpoint_dir=tmp_path / "cp",
            log_dir=tmp_path / "logs",
        )
        assert result.success is False
        assert result.status == "failed"
        assert any(f.error_code == ERR_DRIVER_COMMUNICATION for f in result.failures)
        assert result.log_path.exists()
        log_data = json.loads(result.log_path.read_text(encoding="utf-8"))
        assert log_data["status"] == "failed"

    def test_runner_step06_failure_aborts_before_step08_09_10(
        self, tmp_path: Path, tier2_spec: JobSpec
    ) -> None:
        """T2-C5: Step 6 pre_check failure aborts pipeline with zero downstream checkpoints."""
        from meshtrix.core.checkpoint import CheckpointManager
        from meshtrix.runner import PipelineRunner

        cp_dir = tmp_path / "cp"
        driver = _build_driver_with_selections(
            {"NS_BASE_FACES": ["Face_1"], "NS_LUG_HOLE": ["Face_2"]}
        )
        driver.inject_unmapped_body("Surprise_Unmapped_Rib", body_type="solid")

        result = PipelineRunner().run(
            tier2_spec,
            driver,
            run_id="r_step06_fail",
            checkpoint_dir=cp_dir,
            log_dir=tmp_path / "logs",
        )
        assert result.success is False
        assert result.status == "failed"
        assert result.completed_steps == []

        cm = CheckpointManager(cp_dir)
        for downstream in (
            "step_08_meshing",
            "step_09_boundary_conditions",
            "step_10_loads",
        ):
            assert cm.has_checkpoint("r_step06_fail", downstream) is False

    def test_backward_compatibility_phase1_job_spec_without_new_fields(self) -> None:
        """T2-C6: Phase 1 JobSpec dict omitting Phase 2 fields validates with defaults."""
        phase1_dict: dict[str, Any] = {
            "job_id": "JOB-P1-COMPAT-001",
            "units": "Metric_mm",
            "analysis_type": "STRUCTURAL_STATIC",
            "materials": {
                "catalog": {
                    "Structural_Steel": {
                        "name": "Structural_Steel",
                        "density": 7.85e-9,
                        "elastic_modulus": 200000.0,
                        "poissons_ratio": 0.30,
                        "yield_strength": 250.0,
                    }
                },
                "mappings": {
                    "Bracket_Solid_Base": {
                        "body_name": "Bracket_Solid_Base",
                        "material_name": "Structural_Steel",
                        "thickness": None,
                    }
                },
            },
            "mesh": {
                "global_size": 5.0,
                "element_order": "quadratic",
                "min_quality": 0.25,
                "quality_metric": "skewness",
            },
            "tolerances": {
                "thickness_tolerance": 0.01,
                "mass_tolerance": 0.05,
            },
            "load_cases": [
                {
                    "case_id": "LC1_Tension",
                    "forces": [
                        {
                            "selection": "NS_LUG_HOLE",
                            "magnitude": 10000.0,
                            "direction": [0.0, 1.0, 0.0],
                        }
                    ],
                }
            ],
            "supports": [{"selection": "NS_BASE_FACES", "type": "fixed"}],
        }

        spec = JobSpec.model_validate(phase1_dict)
        assert spec.spec_version == "1.0"
        assert spec.tolerances is not None
        assert spec.tolerances.load_tolerance == pytest.approx(0.01)
        assert spec.tolerances.direction_tolerance == pytest.approx(1e-4)
        assert spec.load_cases[0].accelerations == []
        assert spec.load_cases[0].forces[0].coordinate_system == "Global"
        assert spec.supports[0].coordinate_system == "Global"
        assert set(spec.supports[0].resolved_dofs()) == {"UX", "UY", "UZ", "RX", "RY", "RZ"}

        with pytest.raises(ValidationError):
            CheckTolerances(load_tolerance=0.0)
        with pytest.raises(ValidationError):
            CheckTolerances(direction_tolerance=-1e-4)


# ===========================================================================
# Area 2D: meshtrix.cli Negative Paths & Boundary Tests (6)
# ===========================================================================


class TestPhase2Tier2CLIBoundaries:
    """Tier 2 negative-path tests for meshtrix CLI commands."""

    def test_cli_validate_malformed_yaml_exits_nonzero(self, tmp_path: Path) -> None:
        """T2-D1: `meshtrix validate` exits non-zero on syntax-invalid YAML."""
        from meshtrix.cli.main import app

        bad_yaml = tmp_path / "malformed.yaml"
        bad_yaml.write_text("job_id: [unclosed\n  bad: : :\n", encoding="utf-8")

        result = CliRunner().invoke(app, ["validate", str(bad_yaml)])
        assert result.exit_code != 0
        assert len(result.output.strip()) > 0

    def test_cli_validate_invalid_job_spec_schema_exits_nonzero(
        self, tmp_path: Path, tier2_spec_dict: dict[str, Any]
    ) -> None:
        """T2-D2: `meshtrix validate` exits non-zero on invalid JobSpec schema values."""
        from meshtrix.cli.main import app

        bad_dict = deepcopy(tier2_spec_dict)
        bad_dict["units"] = "FURLONGS_PER_FORTNIGHT"
        bad_dict["load_cases"][0]["forces"][0]["direction"] = [0.0, 0.0, 0.0]

        bad_spec_path = tmp_path / "invalid_schema.yaml"
        bad_spec_path.write_text(yaml.safe_dump(bad_dict, sort_keys=False), encoding="utf-8")

        result = CliRunner().invoke(app, ["validate", str(bad_spec_path)])
        assert result.exit_code != 0
        assert len(result.output.strip()) > 0

    def test_cli_validate_nonexistent_file_exits_nonzero(self, tmp_path: Path) -> None:
        """T2-D3: `meshtrix validate` exits non-zero when spec file does not exist."""
        from meshtrix.cli.main import app

        missing = tmp_path / "nonexistent_spec.yaml"
        result = CliRunner().invoke(app, ["validate", str(missing)])
        assert result.exit_code != 0

    def test_cli_run_invalid_resume_from_exits_nonzero(
        self, tmp_path: Path, tier2_spec_dict: dict[str, Any]
    ) -> None:
        """T2-D4: `meshtrix run --mock --resume-from step_99_bad` exits non-zero."""
        from meshtrix.cli.main import app

        spec_path = tmp_path / "valid.yaml"
        spec_path.write_text(yaml.safe_dump(tier2_spec_dict, sort_keys=False), encoding="utf-8")

        result = CliRunner().invoke(
            app,
            [
                "run",
                str(spec_path),
                "--mock",
                "--run-id",
                "r_bad_step",
                "--resume-from",
                "step_99_bad",
                "--checkpoint-dir",
                str(tmp_path / "cp"),
                "--log-dir",
                str(tmp_path / "logs"),
            ],
        )
        assert result.exit_code != 0

    def test_cli_run_resume_from_missing_prior_checkpoint_exits_nonzero(
        self, tmp_path: Path, tier2_spec_dict: dict[str, Any]
    ) -> None:
        """T2-D5: `meshtrix run --mock --resume-from step_10_loads` without checkpoints exits non-zero."""
        from meshtrix.cli.main import app

        spec_path = tmp_path / "valid.yaml"
        spec_path.write_text(yaml.safe_dump(tier2_spec_dict, sort_keys=False), encoding="utf-8")

        result = CliRunner().invoke(
            app,
            [
                "run",
                str(spec_path),
                "--mock",
                "--run-id",
                "r_nocp",
                "--resume-from",
                "step_10_loads",
                "--checkpoint-dir",
                str(tmp_path / "empty_cp"),
                "--log-dir",
                str(tmp_path / "logs"),
            ],
        )
        assert result.exit_code != 0

    def test_cli_inspect_run_unknown_run_id_exits_nonzero(self, tmp_path: Path) -> None:
        """T2-D6: `meshtrix inspect-run` exits non-zero when run_id is unknown."""
        from meshtrix.cli.main import app

        result = CliRunner().invoke(
            app,
            [
                "inspect-run",
                "unknown_run_999",
                "--checkpoint-dir",
                str(tmp_path / "empty_cp"),
                "--log-dir",
                str(tmp_path / "empty_logs"),
            ],
        )
        assert result.exit_code != 0

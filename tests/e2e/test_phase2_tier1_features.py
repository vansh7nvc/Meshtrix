"""
Meshtrix Phase 2 Tier 1: Core Feature Coverage E2E Test Suite.

Authoritative Reference: ORIGINAL_REQUEST.md & PROJECT.md § Interface Contracts
Features Tested (24 tests, 6 per area):
- Area 1A: Step09BoundaryConditions, SupportSpec.resolved_dofs(), & Driver BC/NS APIs
- Area 1B: Step10Loads, LoadSpec/AccelerationSpec/LoadCase/CheckTolerances, & Driver Load APIs
- Area 1C: PipelineRunner, CheckpointManager, & RunLogger (--resume-from & fail-fast)
- Area 1D: meshtrix.cli (validate, run --mock, run --resume-from, inspect-run)
"""

import json
import tomllib
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
import typer
import yaml
from typer.testing import CliRunner

from meshtrix.core.step import BaseStep, RunContext
from meshtrix.diagnostics.failure import StepCheckResult
from meshtrix.drivers.mock import MockMechanicalDriver
from meshtrix.spec.job_spec import (
    AnalysisType,
    CheckTolerances,
    JobSpec,
    LoadCase,
    LoadSpec,
    LoadType,
    SupportSpec,
    SupportType,
)
from tests.conftest import assert_check_passed

# ---------------------------------------------------------------------------
# Self-Contained Phase 2 Helpers & Fixtures (No Phase 2 Top-Level Imports)
# ---------------------------------------------------------------------------


def _base_phase2_spec_dict() -> dict[str, Any]:
    """Return a clean, self-contained Phase 2 JobSpec dictionary."""
    return {
        "job_id": "JOB-P2-TIER1-001",
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
                "Bracket_Base": {
                    "body_name": "Bracket_Base",
                    "material_name": "Structural_Steel",
                    "thickness": None,
                },
                "Gusset_Plate": {
                    "body_name": "Gusset_Plate",
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
                "case_id": "LC1_Limit",
                "step_number": 1,
                "description": "Primary structural limit load case",
                "forces": [
                    {
                        "selection": "NS_LUG_HOLE",
                        "magnitude": 10000.0,
                        "direction": [0.0, 1.0, 0.0],
                        "load_type": "force",
                        "coordinate_system": "Global",
                        "name": "Lug_Tension",
                    }
                ],
                "pressures": [
                    {
                        "selection": "NS_SKIN_FACE",
                        "magnitude": 1.5,
                        "direction": [0.0, 0.0, -1.0],
                        "load_type": "pressure",
                        "coordinate_system": "Global",
                        "name": "Skin_Pressure",
                    }
                ],
                "accelerations": [
                    {
                        "magnitude": 9810.0,
                        "direction": [0.0, 0.0, -1.0],
                        "selection": None,
                        "coordinate_system": "Global",
                        "name": "Gravity_1G",
                    }
                ],
            }
        ],
        "supports": [
            {
                "selection": "NS_BASE_FACES",
                "type": "fixed",
                "coordinate_system": "Global",
                "name": "Base_Fixed",
            }
        ],
    }


def _build_seeded_driver(
    named_selections: dict[str, list[str]] | None = None,
) -> MockMechanicalDriver:
    """Create a MockMechanicalDriver with Phase 1 bodies and requested named selections."""
    driver = MockMechanicalDriver()
    driver.add_body(name="Bracket_Base", body_type="solid", thickness=None)
    driver.add_body(name="Gusset_Plate", body_type="surface", thickness=None)
    if named_selections:
        for ns_name, entities in named_selections.items():
            driver.create_named_selection(ns_name, entities)
    return driver


def _run_step_lifecycle(step: BaseStep, context: RunContext) -> StepCheckResult:
    """Execute pre_check -> execute -> post_check and assert nominal success."""
    pre_res = step.pre_check(context)
    assert_check_passed(pre_res)
    step.execute(context)
    post_res = step.post_check(context)
    assert_check_passed(post_res)
    assert step.troubleshoot(context, post_res) == []
    return post_res


@pytest.fixture
def tier1_spec_dict() -> dict[str, Any]:
    """Fresh Phase 2 JobSpec dictionary per test."""
    return deepcopy(_base_phase2_spec_dict())


@pytest.fixture
def tier1_spec(tier1_spec_dict: dict[str, Any]) -> JobSpec:
    """Validated Phase 2 JobSpec instance."""
    return JobSpec.model_validate(tier1_spec_dict)


# ===========================================================================
# Area 1A: Step09BoundaryConditions, SupportSpec, & Driver BC/NS APIs (6)
# ===========================================================================


class TestPhase2Tier1BoundaryConditions:
    """Tier 1 feature coverage for Step 9, SupportSpec, and Driver BC APIs."""

    def test_support_spec_resolved_dofs_for_all_support_types(self) -> None:
        """T1-A1: SupportSpec.resolved_dofs() returns canonical uppercase DOFs."""
        canonical = {"UX", "UY", "UZ", "RX", "RY", "RZ", "NORMAL"}

        fixed = SupportSpec(selection="NS_A", type=SupportType.FIXED)
        pinned = SupportSpec(selection="NS_B", type="pinned")
        frictionless = SupportSpec(selection="NS_C", type=SupportType.FRICTIONLESS)
        disp_explicit = SupportSpec(
            selection="NS_D",
            type="displacement",
            dofs=["ux", "rz"],
            displacement_values={"ux": 0.0, "rz": 0.0},
        )
        disp_from_values = SupportSpec(
            selection="NS_E",
            type=SupportType.DISPLACEMENT,
            displacement_values={"uy": 0.0},
        )

        assert set(fixed.resolved_dofs()) == {"UX", "UY", "UZ", "RX", "RY", "RZ"}
        assert set(pinned.resolved_dofs()) == {"UX", "UY", "UZ"}
        assert frictionless.resolved_dofs() == ["NORMAL"]
        assert set(disp_explicit.resolved_dofs()) == {"UX", "RZ"}
        assert disp_from_values.resolved_dofs() == ["UY"]

        for spec in (fixed, pinned, frictionless, disp_explicit, disp_from_values):
            dofs = spec.resolved_dofs()
            assert len(dofs) > 0
            assert all(dof == dof.upper() and dof in canonical for dof in dofs)

    def test_driver_named_selection_and_support_apis(self) -> None:
        """T1-A2: MockMechanicalDriver named-selection queries and support APIs work."""
        from meshtrix.drivers.base import SupportRecord

        driver = MockMechanicalDriver()
        driver.create_named_selection("NS_BASE", ["Face_1", "Face_2"])

        assert driver.has_named_selection("NS_BASE") is True
        assert driver.has_named_selection("NS_NONE") is False
        assert driver.get_named_selection_entities("NS_BASE") == ["Face_1", "Face_2"]

        record = driver.apply_support(
            selection="NS_BASE",
            support_type="fixed",
            dofs=["UX", "UY", "UZ", "RX", "RY", "RZ"],
            coordinate_system="Global",
            name="Base_Fixed",
        )
        assert isinstance(record, SupportRecord)
        assert record.selection == "NS_BASE"
        assert record.support_type == "fixed"
        assert set(record.dofs) == {"UX", "UY", "UZ", "RX", "RY", "RZ"}
        assert record.coordinate_system == "Global"
        assert record.name == "Base_Fixed"

        supports = driver.get_supports()
        assert len(supports) == 1
        assert supports[0].selection == "NS_BASE"
        assert supports[0].support_type == "fixed"

    def test_step09_attributes_and_base_step_contract(self) -> None:
        """T1-A3: Step09BoundaryConditions implements BaseStep with exact step_id."""
        from meshtrix.steps.step_09_boundary_conditions import Step09BoundaryConditions

        step = Step09BoundaryConditions()
        assert isinstance(step, BaseStep)
        assert step.step_id == "step_09_boundary_conditions"
        assert isinstance(step.description, str)
        assert len(step.description.strip()) > 0

    def test_step09_nominal_4_phase_lifecycle_mixed_supports(
        self, tier1_spec_dict: dict[str, Any]
    ) -> None:
        """T1-A4: Step09 applies fixed, pinned, frictionless, and displacement supports."""
        from meshtrix.steps.step_09_boundary_conditions import Step09BoundaryConditions

        tier1_spec_dict["supports"] = [
            {"selection": "NS_BASE", "type": "fixed", "name": "Sup_Fixed"},
            {"selection": "NS_PIN", "type": "pinned", "name": "Sup_Pinned"},
            {"selection": "NS_SYM", "type": "frictionless", "name": "Sup_Sym"},
            {
                "selection": "NS_DISP",
                "type": "displacement",
                "dofs": ["UX", "UZ"],
                "displacement_values": {"UX": 0.0, "UZ": 0.25},
                "name": "Sup_Disp",
            },
        ]
        spec = JobSpec.model_validate(tier1_spec_dict)
        driver = _build_seeded_driver(
            {
                "NS_BASE": ["Face_1", "Face_2"],
                "NS_PIN": ["Face_3"],
                "NS_SYM": ["Face_4"],
                "NS_DISP": ["Face_5"],
            }
        )
        context = RunContext(spec=spec, driver=driver)
        step = Step09BoundaryConditions()

        _run_step_lifecycle(step, context)

        applied = driver.get_supports()
        assert len(applied) == 4
        by_selection = {rec.selection: rec for rec in applied}
        assert set(by_selection["NS_BASE"].dofs) == {"UX", "UY", "UZ", "RX", "RY", "RZ"}
        assert set(by_selection["NS_PIN"].dofs) == {"UX", "UY", "UZ"}
        assert by_selection["NS_SYM"].dofs == ["NORMAL"]
        assert set(by_selection["NS_DISP"].dofs) == {"UX", "UZ"}
        assert by_selection["NS_DISP"].displacement_values == {"UX": 0.0, "UZ": 0.25}

    def test_step09_custom_coordinate_system_and_named_support(
        self, tier1_spec_dict: dict[str, Any]
    ) -> None:
        """T1-A5: Step09 preserves custom coordinate_system and explicit support name."""
        from meshtrix.steps.step_09_boundary_conditions import Step09BoundaryConditions

        tier1_spec_dict["supports"] = [
            {
                "selection": "NS_LUG_PIN",
                "type": "pinned",
                "coordinate_system": "Cylindrical_CS_01",
                "name": "Lug_Pin_Support",
            }
        ]
        spec = JobSpec.model_validate(tier1_spec_dict)
        driver = _build_seeded_driver({"NS_LUG_PIN": ["Cyl_Face_1"]})
        context = RunContext(spec=spec, driver=driver)

        _run_step_lifecycle(Step09BoundaryConditions(), context)

        supports = driver.get_supports()
        assert len(supports) == 1
        assert supports[0].coordinate_system == "Cylindrical_CS_01"
        assert supports[0].name == "Lug_Pin_Support"

    def test_step09_modal_constrained_supports_nominal(
        self, tier1_spec_dict: dict[str, Any]
    ) -> None:
        """T1-A6: Step09 passes 4-phase lifecycle for constrained MODAL analysis."""
        from meshtrix.steps.step_09_boundary_conditions import Step09BoundaryConditions

        tier1_spec_dict["analysis_type"] = AnalysisType.MODAL.value
        tier1_spec_dict["load_cases"] = []
        tier1_spec_dict["supports"] = [
            {"selection": "NS_ROOT", "type": "fixed", "name": "Modal_Root"}
        ]
        spec = JobSpec.model_validate(tier1_spec_dict)
        driver = _build_seeded_driver({"NS_ROOT": ["Face_Root_1"]})
        context = RunContext(spec=spec, driver=driver)

        _run_step_lifecycle(Step09BoundaryConditions(), context)

        supports = driver.get_supports()
        assert len(supports) == 1
        assert supports[0].selection == "NS_ROOT"


# ===========================================================================
# Area 1B: Step10Loads, Load/Acceleration Specs, & Driver Load APIs (6)
# ===========================================================================


class TestPhase2Tier1Loads:
    """Tier 1 feature coverage for Step 10, load schemas, and driver load APIs."""

    def test_load_and_acceleration_spec_and_tolerances_schema(
        self, tier1_spec_dict: dict[str, Any]
    ) -> None:
        """T1-B1: LoadSpec, AccelerationSpec, LoadCase, CheckTolerances, and spec_version validate."""
        from meshtrix.spec.job_spec import AccelerationSpec

        force = LoadSpec(
            selection="NS_LUG",
            magnitude=12500.0,
            direction=[1.0, 0.0, 0.0],
            load_type=LoadType.FORCE,
            coordinate_system="Global",
            name="Axial_Force",
        )
        pressure = LoadSpec(
            selection="NS_SKIN",
            magnitude=2.0,
            direction=[0.0, 0.0, -1.0],
            load_type=LoadType.PRESSURE,
            name="Internal_Pressure",
        )
        accel_global = AccelerationSpec(magnitude=9810.0, direction=[0.0, 0.0, -1.0])
        accel_scoped = AccelerationSpec(
            magnitude=24525.0,
            direction=[0.0, 1.0, 0.0],
            selection="NS_SUBASSEMBLY",
            coordinate_system="Local_CS",
            name="Lateral_2_5G",
        )
        load_case = LoadCase(
            case_id="LC_Combined",
            forces=[force],
            pressures=[pressure],
            accelerations=[accel_global, accel_scoped],
            step_number=1,
            description="Limit maneuver",
        )
        tolerances = CheckTolerances(load_tolerance=0.02, direction_tolerance=1e-3)

        tier1_spec_dict["load_cases"] = [load_case.model_dump()]
        tier1_spec_dict["tolerances"] = tolerances.model_dump()
        spec = JobSpec.model_validate(tier1_spec_dict)

        assert spec.spec_version == "1.0"
        assert len(spec.load_cases) == 1
        assert len(spec.load_cases[0].accelerations) == 2
        assert spec.load_cases[0].accelerations[0].selection is None
        assert spec.load_cases[0].accelerations[1].selection == "NS_SUBASSEMBLY"
        assert spec.load_cases[0].step_number == 1
        assert spec.load_cases[0].description == "Limit maneuver"
        assert spec.tolerances is not None
        assert spec.tolerances.load_tolerance == pytest.approx(0.02)
        assert spec.tolerances.direction_tolerance == pytest.approx(1e-3)

    def test_driver_load_apis_force_pressure_acceleration(self) -> None:
        """T1-B2: MockMechanicalDriver apply_force/pressure/acceleration and get_loads work."""
        from meshtrix.drivers.base import LoadRecord

        driver = MockMechanicalDriver()
        driver.create_named_selection("NS_LUG", ["Face_1"])
        driver.create_named_selection("NS_WALL", ["Face_2"])

        f_rec = driver.apply_force(
            case_id="LC1",
            selection="NS_LUG",
            magnitude=5000.0,
            direction=[0.0, 1.0, 0.0],
            coordinate_system="Global",
            name="Lug_Force",
        )
        p_rec = driver.apply_pressure(
            case_id="LC1",
            selection="NS_WALL",
            magnitude=2.5,
            direction=[0.0, 0.0, -1.0],
            coordinate_system="Global",
            name="Wall_Press",
        )
        a_rec = driver.apply_acceleration(
            case_id="LC2",
            magnitude=9810.0,
            direction=[0.0, 0.0, -1.0],
            selection=None,
            coordinate_system="Global",
            name="Gravity",
        )

        for rec in (f_rec, p_rec, a_rec):
            assert isinstance(rec, LoadRecord)

        assert f_rec.case_id == "LC1"
        assert f_rec.selection == "NS_LUG"
        assert f_rec.magnitude == pytest.approx(5000.0)
        assert p_rec.magnitude == pytest.approx(2.5)
        assert a_rec.case_id == "LC2"
        assert a_rec.selection is None
        assert a_rec.magnitude == pytest.approx(9810.0)

        assert len(driver.get_loads()) == 3
        assert len(driver.get_loads(case_id="LC1")) == 2
        assert len(driver.get_loads(case_id="LC2")) == 1

    def test_step10_attributes_and_base_step_contract(self) -> None:
        """T1-B3: Step10Loads implements BaseStep with exact step_id."""
        from meshtrix.steps.step_10_loads import Step10Loads

        step = Step10Loads()
        assert isinstance(step, BaseStep)
        assert step.step_id == "step_10_loads"
        assert isinstance(step.description, str)
        assert len(step.description.strip()) > 0

    def test_step10_nominal_force_pressure_acceleration_lifecycle(
        self, tier1_spec: JobSpec
    ) -> None:
        """T1-B4: Step10 executes 4-phase lifecycle for force, pressure, and acceleration."""
        from meshtrix.steps.step_10_loads import Step10Loads

        driver = _build_seeded_driver(
            {
                "NS_LUG_HOLE": ["Face_1"],
                "NS_SKIN_FACE": ["Face_2"],
                "NS_BASE_FACES": ["Face_3"],
            }
        )
        context = RunContext(spec=tier1_spec, driver=driver)
        step = Step10Loads()

        _run_step_lifecycle(step, context)

        loads = driver.get_loads("LC1_Limit")
        assert len(loads) == 3
        load_types = {str(rec.load_type).lower() for rec in loads}
        assert "force" in load_types
        assert "pressure" in load_types
        assert "acceleration" in load_types

    def test_step10_multiple_load_cases_isolation_and_totals(
        self, tier1_spec_dict: dict[str, Any]
    ) -> None:
        """T1-B5: Step10 isolates multiple load cases and verifies per-case totals."""
        from meshtrix.steps.step_10_loads import Step10Loads

        tier1_spec_dict["load_cases"] = [
            {
                "case_id": "LC1_Maneuver",
                "step_number": 1,
                "forces": [
                    {
                        "selection": "NS_LUG_A",
                        "magnitude": 4000.0,
                        "direction": [1.0, 0.0, 0.0],
                        "name": "Maneuver_Fx",
                    },
                    {
                        "selection": "NS_LUG_B",
                        "magnitude": 6000.0,
                        "direction": [0.0, 1.0, 0.0],
                        "name": "Maneuver_Fy",
                    },
                ],
                "pressures": [],
                "accelerations": [
                    {
                        "magnitude": 24525.0,
                        "direction": [0.0, 0.0, -1.0],
                        "name": "Maneuver_2_5G",
                    }
                ],
            },
            {
                "case_id": "LC2_Landing",
                "step_number": 2,
                "forces": [
                    {
                        "selection": "NS_GEAR",
                        "magnitude": 18000.0,
                        "direction": [0.0, 0.0, 1.0],
                        "name": "Landing_Fz",
                    }
                ],
                "pressures": [
                    {
                        "selection": "NS_SKIN_FACE",
                        "magnitude": 0.85,
                        "direction": [0.0, 0.0, -1.0],
                        "load_type": "pressure",
                        "name": "Landing_Press",
                    }
                ],
                "accelerations": [],
            },
        ]
        spec = JobSpec.model_validate(tier1_spec_dict)
        driver = _build_seeded_driver(
            {
                "NS_LUG_A": ["Face_A"],
                "NS_LUG_B": ["Face_B"],
                "NS_GEAR": ["Face_G"],
                "NS_SKIN_FACE": ["Face_S"],
            }
        )
        context = RunContext(spec=spec, driver=driver)

        _run_step_lifecycle(Step10Loads(), context)

        lc1_loads = driver.get_loads("LC1_Maneuver")
        lc2_loads = driver.get_loads("LC2_Landing")
        assert len(lc1_loads) == 3
        assert len(lc2_loads) == 2
        assert len(driver.get_loads()) == 5
        assert sum(r.magnitude for r in lc1_loads if str(r.load_type).lower() == "force") == (
            pytest.approx(10000.0)
        )
        assert sum(r.magnitude for r in lc2_loads if str(r.load_type).lower() == "force") == (
            pytest.approx(18000.0)
        )

    def test_step10_custom_coordinate_system_load_verification(
        self, tier1_spec_dict: dict[str, Any]
    ) -> None:
        """T1-B6: Step10 preserves and verifies custom coordinate systems on loads."""
        from meshtrix.steps.step_10_loads import Step10Loads

        tier1_spec_dict["load_cases"] = [
            {
                "case_id": "LC_Local",
                "forces": [
                    {
                        "selection": "NS_LUG_HOLE",
                        "magnitude": 7500.0,
                        "direction": [0.0, 1.0, 0.0],
                        "coordinate_system": "Wing_Local_CS",
                        "name": "Local_Force",
                    }
                ],
                "pressures": [],
                "accelerations": [
                    {
                        "magnitude": 9810.0,
                        "direction": [0.0, 0.0, -1.0],
                        "coordinate_system": "Wing_Local_CS",
                        "name": "Local_Accel",
                    }
                ],
            }
        ]
        spec = JobSpec.model_validate(tier1_spec_dict)
        driver = _build_seeded_driver({"NS_LUG_HOLE": ["Face_1"]})
        context = RunContext(spec=spec, driver=driver)

        _run_step_lifecycle(Step10Loads(), context)

        loads = driver.get_loads("LC_Local")
        assert len(loads) == 2
        assert all(rec.coordinate_system == "Wing_Local_CS" for rec in loads)


# ===========================================================================
# Area 1C: PipelineRunner, CheckpointManager, & RunLogger (6)
# ===========================================================================


class TestPhase2Tier1RunnerCheckpointing:
    """Tier 1 feature coverage for CheckpointManager, RunLogger, and PipelineRunner."""

    def test_checkpoint_manager_save_load_has_list(
        self, tmp_path: Path, tier1_spec: JobSpec
    ) -> None:
        """T1-C1: CheckpointManager saves, queries, lists, and loads JSON checkpoints."""
        from meshtrix.core.checkpoint import CheckpointManager

        cm = CheckpointManager(tmp_path / ".meshtrix")
        driver = _build_seeded_driver(
            {
                "NS_BASE_FACES": ["Face_1"],
                "NS_LUG_HOLE": ["Face_2"],
                "NS_SKIN_FACE": ["Face_3"],
            }
        )
        context = RunContext(spec=tier1_spec, driver=driver, run_id="run_cm_01")

        p0 = cm.save_checkpoint(
            run_id="run_cm_01",
            step_id="step_06_materials",
            step_index=0,
            spec=tier1_spec,
            context=context,
            driver_state={"bodies": ["Bracket_Base", "Gusset_Plate"]},
            warnings=[],
        )
        p1 = cm.save_checkpoint(
            run_id="run_cm_01",
            step_id="step_08_meshing",
            step_index=1,
            spec=tier1_spec,
            context=context,
            driver_state={"mesh_generated": True},
            warnings=["Minor aspect ratio note"],
        )

        assert p0.exists()
        assert p1.exists()
        assert cm.has_checkpoint("run_cm_01", "step_06_materials") is True
        assert cm.has_checkpoint("run_cm_01", "step_08_meshing") is True
        assert cm.has_checkpoint("run_cm_01", "step_09_boundary_conditions") is False
        assert set(cm.list_checkpoints("run_cm_01")) == {
            "step_06_materials",
            "step_08_meshing",
        }

        loaded = cm.load_checkpoint("run_cm_01", "step_06_materials")
        assert loaded["step_id"] == "step_06_materials"
        assert loaded["step_index"] == 0
        assert "spec" in loaded
        assert loaded["driver_state"] == {"bodies": ["Bracket_Base", "Gusset_Plate"]}

    def test_run_logger_records_audit_metadata_and_saves_json(
        self, tmp_path: Path, tier1_spec: JobSpec
    ) -> None:
        """T1-C2: RunLogger & PipelineRunner emit structured JSON audit metadata."""
        from meshtrix.core.logger import RunLogger
        from meshtrix.runner import PipelineRunner

        logger_dir = tmp_path / "direct_logs"
        run_logger = RunLogger(logger_dir)
        initial_dict = run_logger.to_dict()
        assert isinstance(initial_dict, dict)
        saved_direct = run_logger.save_log()
        assert saved_direct.exists()
        assert isinstance(json.loads(saved_direct.read_text(encoding="utf-8")), dict)

        driver = _build_seeded_driver(
            {
                "NS_BASE_FACES": ["Face_1"],
                "NS_LUG_HOLE": ["Face_2"],
                "NS_SKIN_FACE": ["Face_3"],
            }
        )
        cp_dir = tmp_path / "checkpoints"
        log_dir = tmp_path / "run_logs"
        result = PipelineRunner().run(
            tier1_spec,
            driver,
            run_id="run_audit_01",
            checkpoint_dir=cp_dir,
            log_dir=log_dir,
        )

        assert result.success is True
        assert result.log_path.exists()
        log_payload = json.loads(result.log_path.read_text(encoding="utf-8"))

        required_keys = {
            "run_id",
            "job_id",
            "status",
            "started_at",
            "finished_at",
            "duration_seconds",
            "spec_version",
            "spec_hash",
            "tool_versions",
            "resumed_from",
            "steps",
        }
        assert required_keys.issubset(log_payload.keys())
        assert log_payload["run_id"] == "run_audit_01"
        assert log_payload["job_id"] == tier1_spec.job_id
        assert log_payload["status"] == "passed"
        assert log_payload["spec_version"] == tier1_spec.spec_version
        assert isinstance(log_payload["spec_hash"], str) and len(log_payload["spec_hash"]) > 0
        assert isinstance(log_payload["tool_versions"], dict)
        assert log_payload["duration_seconds"] >= 0.0
        assert log_payload["resumed_from"] is None
        assert len(log_payload["steps"]) == 4

    def test_pipeline_runner_executes_phase2_steps_in_order(
        self, tmp_path: Path, tier1_spec: JobSpec
    ) -> None:
        """T1-C3: PipelineRunner runs Phase 2 Steps 6 -> 8 -> 9 -> 10 sequentially."""
        from meshtrix.runner import PipelineResult, PipelineRunner

        driver = _build_seeded_driver(
            {
                "NS_BASE_FACES": ["Face_1"],
                "NS_LUG_HOLE": ["Face_2"],
                "NS_SKIN_FACE": ["Face_3"],
            }
        )
        result = PipelineRunner().run(
            tier1_spec,
            driver,
            run_id="run_seq_01",
            checkpoint_dir=tmp_path / "cp",
            log_dir=tmp_path / "logs",
        )

        assert isinstance(result, PipelineResult)
        assert result.success is True
        assert result.status == "passed"
        assert result.completed_steps == [
            "step_06_materials",
            "step_08_meshing",
            "step_09_boundary_conditions",
            "step_10_loads",
        ]
        assert result.skipped_steps == []
        assert result.failures == []

    def test_pipeline_runner_creates_per_step_checkpoints_and_run_log(
        self, tmp_path: Path, tier1_spec: JobSpec
    ) -> None:
        """T1-C4: PipelineRunner persists all 4 JSON checkpoints and structured run log."""
        from meshtrix.core.checkpoint import CheckpointManager
        from meshtrix.runner import PipelineRunner

        cp_dir = tmp_path / "cp"
        log_dir = tmp_path / "logs"
        driver = _build_seeded_driver(
            {
                "NS_BASE_FACES": ["Face_1"],
                "NS_LUG_HOLE": ["Face_2"],
                "NS_SKIN_FACE": ["Face_3"],
            }
        )
        result = PipelineRunner().run(
            tier1_spec,
            driver,
            run_id="run_persist_01",
            checkpoint_dir=cp_dir,
            log_dir=log_dir,
        )

        cm = CheckpointManager(cp_dir)
        expected_steps = [
            "step_06_materials",
            "step_08_meshing",
            "step_09_boundary_conditions",
            "step_10_loads",
        ]
        for step_id in expected_steps:
            assert cm.has_checkpoint("run_persist_01", step_id) is True

        assert result.log_path.exists()
        log_data = json.loads(result.log_path.read_text(encoding="utf-8"))
        assert log_data["status"] == "passed"
        assert len(log_data["steps"]) == 4

    def test_pipeline_runner_resume_from_skips_prior_steps(
        self, tmp_path: Path, tier1_spec: JobSpec
    ) -> None:
        """T1-C5: PipelineRunner --resume-from skips prior checkpointed steps."""
        from meshtrix.runner import PipelineRunner

        cp_dir = tmp_path / "cp"
        log_dir = tmp_path / "logs"
        initial_driver = _build_seeded_driver(
            {
                "NS_BASE_FACES": ["Face_1"],
                "NS_LUG_HOLE": ["Face_2"],
                "NS_SKIN_FACE": ["Face_3"],
            }
        )
        runner = PipelineRunner()
        first_run = runner.run(
            tier1_spec,
            initial_driver,
            run_id="run_r1",
            checkpoint_dir=cp_dir,
            log_dir=log_dir,
        )
        assert first_run.success is True

        fresh_driver = _build_seeded_driver(
            {
                "NS_BASE_FACES": ["Face_1"],
                "NS_LUG_HOLE": ["Face_2"],
                "NS_SKIN_FACE": ["Face_3"],
            }
        )
        resumed = runner.run(
            tier1_spec,
            fresh_driver,
            run_id="run_r1",
            resume_from="step_09_boundary_conditions",
            checkpoint_dir=cp_dir,
            log_dir=log_dir,
        )

        assert resumed.success is True
        assert resumed.status == "passed"
        assert resumed.skipped_steps == ["step_06_materials", "step_08_meshing"]
        assert resumed.completed_steps == [
            "step_09_boundary_conditions",
            "step_10_loads",
        ]
        log_data = json.loads(resumed.log_path.read_text(encoding="utf-8"))
        assert log_data["resumed_from"] == "step_09_boundary_conditions"

    def test_pipeline_runner_fail_fast_stops_before_downstream_steps(
        self, tmp_path: Path, tier1_spec: JobSpec
    ) -> None:
        """T1-C6: PipelineRunner stops immediately on Step 9 failure without running Step 10."""
        from meshtrix.diagnostics.failure import ERR_BC_EMPTY_SELECTION
        from meshtrix.runner import PipelineRunner

        driver = _build_seeded_driver(
            {
                "NS_BASE_FACES": [],  # Empty NS triggers Step 9 pre_check failure
                "NS_LUG_HOLE": ["Face_2"],
                "NS_SKIN_FACE": ["Face_3"],
            }
        )
        result = PipelineRunner().run(
            tier1_spec,
            driver,
            run_id="run_failfast_01",
            checkpoint_dir=tmp_path / "cp",
            log_dir=tmp_path / "logs",
        )

        assert result.success is False
        assert result.status == "failed"
        assert result.completed_steps == ["step_06_materials", "step_08_meshing"]
        assert "step_10_loads" not in result.completed_steps
        recorded_step_ids = [rec.step_id for rec in result.step_results]
        assert "step_10_loads" not in recorded_step_ids
        assert any(f.error_code == ERR_BC_EMPTY_SELECTION for f in result.failures)


# ===========================================================================
# Area 1D: meshtrix.cli (validate, run --mock, run --resume-from, inspect-run) (6)
# ===========================================================================


class TestPhase2Tier1CLI:
    """Tier 1 feature coverage for meshtrix Typer CLI commands."""

    def test_cli_validate_valid_yaml_spec_exits_zero(
        self, tmp_path: Path, tier1_spec_dict: dict[str, Any]
    ) -> None:
        """T1-D1: `meshtrix validate` exits 0 on valid YAML JobSpec."""
        from meshtrix.cli.main import app

        spec_path = tmp_path / "spec.yaml"
        spec_path.write_text(yaml.safe_dump(tier1_spec_dict, sort_keys=False), encoding="utf-8")

        result = CliRunner().invoke(app, ["validate", str(spec_path)])
        assert result.exit_code == 0, result.output
        assert tier1_spec_dict["job_id"] in result.output or "valid" in result.output.lower()

    def test_cli_validate_valid_json_spec_exits_zero(
        self, tmp_path: Path, tier1_spec_dict: dict[str, Any]
    ) -> None:
        """T1-D2: `meshtrix validate` exits 0 on valid JSON JobSpec."""
        from meshtrix.cli.main import app

        spec_path = tmp_path / "spec.json"
        spec_path.write_text(json.dumps(tier1_spec_dict, indent=2), encoding="utf-8")

        result = CliRunner().invoke(app, ["validate", str(spec_path)])
        assert result.exit_code == 0, result.output
        assert tier1_spec_dict["job_id"] in result.output or "valid" in result.output.lower()

    def test_cli_run_mock_end_to_end_exits_zero_and_persists_artifacts(
        self, tmp_path: Path, tier1_spec_dict: dict[str, Any]
    ) -> None:
        """T1-D3: `meshtrix run --mock` runs end-to-end and writes checkpoints & log."""
        from meshtrix.cli.main import app
        from meshtrix.core.checkpoint import CheckpointManager

        spec_path = tmp_path / "spec.yaml"
        spec_path.write_text(yaml.safe_dump(tier1_spec_dict, sort_keys=False), encoding="utf-8")
        cp_dir = tmp_path / "cp"
        log_dir = tmp_path / "logs"

        result = CliRunner().invoke(
            app,
            [
                "run",
                str(spec_path),
                "--mock",
                "--run-id",
                "cli_run_01",
                "--checkpoint-dir",
                str(cp_dir),
                "--log-dir",
                str(log_dir),
            ],
        )
        assert result.exit_code == 0, result.output

        cm = CheckpointManager(cp_dir)
        assert set(cm.list_checkpoints("cli_run_01")) == {
            "step_06_materials",
            "step_08_meshing",
            "step_09_boundary_conditions",
            "step_10_loads",
        }
        log_files = list(log_dir.rglob("*.json"))
        assert len(log_files) >= 1

    def test_cli_run_resume_from_step09_exits_zero(
        self, tmp_path: Path, tier1_spec_dict: dict[str, Any]
    ) -> None:
        """T1-D4: `meshtrix run --mock --resume-from step_09_boundary_conditions` exits 0."""
        from meshtrix.cli.main import app

        spec_path = tmp_path / "spec.yaml"
        spec_path.write_text(yaml.safe_dump(tier1_spec_dict, sort_keys=False), encoding="utf-8")
        cp_dir = tmp_path / "cp"
        log_dir = tmp_path / "logs"
        runner = CliRunner()

        first = runner.invoke(
            app,
            [
                "run",
                str(spec_path),
                "--mock",
                "--run-id",
                "cli_res_01",
                "--checkpoint-dir",
                str(cp_dir),
                "--log-dir",
                str(log_dir),
            ],
        )
        assert first.exit_code == 0, first.output

        resumed = runner.invoke(
            app,
            [
                "run",
                str(spec_path),
                "--mock",
                "--run-id",
                "cli_res_01",
                "--resume-from",
                "step_09_boundary_conditions",
                "--checkpoint-dir",
                str(cp_dir),
                "--log-dir",
                str(log_dir),
            ],
        )
        assert resumed.exit_code == 0, resumed.output
        log_files = list(log_dir.rglob("*.json"))
        assert len(log_files) >= 1
        parsed_logs = [json.loads(p.read_text(encoding="utf-8")) for p in log_files]
        assert any(
            data.get("resumed_from") == "step_09_boundary_conditions" for data in parsed_logs
        ) or ("step_09_boundary_conditions" in resumed.output)

    def test_cli_inspect_run_displays_summary_exits_zero(
        self, tmp_path: Path, tier1_spec_dict: dict[str, Any]
    ) -> None:
        """T1-D5: `meshtrix inspect-run` displays run summary and exits 0."""
        from meshtrix.cli.main import app

        spec_path = tmp_path / "spec.yaml"
        spec_path.write_text(yaml.safe_dump(tier1_spec_dict, sort_keys=False), encoding="utf-8")
        cp_dir = tmp_path / "cp"
        log_dir = tmp_path / "logs"
        runner = CliRunner()

        run_res = runner.invoke(
            app,
            [
                "run",
                str(spec_path),
                "--mock",
                "--run-id",
                "cli_insp_01",
                "--checkpoint-dir",
                str(cp_dir),
                "--log-dir",
                str(log_dir),
            ],
        )
        assert run_res.exit_code == 0, run_res.output

        insp = runner.invoke(
            app,
            [
                "inspect-run",
                "cli_insp_01",
                "--checkpoint-dir",
                str(cp_dir),
                "--log-dir",
                str(log_dir),
            ],
        )
        assert insp.exit_code == 0, insp.output
        assert "cli_insp_01" in insp.output
        assert tier1_spec_dict["job_id"] in insp.output
        assert "passed" in insp.output.lower()

    def test_pyproject_registers_meshtrix_console_script(self) -> None:
        """T1-D6: pyproject.toml registers `meshtrix` pointing to `meshtrix.cli.main:app`."""
        from meshtrix.cli.main import app

        pyproject_path = Path(__file__).resolve().parents[2] / "pyproject.toml"
        data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
        scripts = data.get("project", {}).get("scripts", {})
        assert scripts.get("meshtrix") == "meshtrix.cli.main:app"
        assert isinstance(app, typer.Typer)

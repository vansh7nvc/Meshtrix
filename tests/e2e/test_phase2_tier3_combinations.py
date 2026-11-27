"""
Phase 2 E2E Tests — Tier 3: Cross-Feature Pairwise Combinations (T3-1 through T3-10).

Authoritative Reference: ORIGINAL_REQUEST.md & PROJECT.md § Interface Contracts
Methodology: Opaque-box pairwise cross-feature integration testing across
Steps 6, 8, 9, 10, MockMechanicalDriver, CheckpointManager, RunLogger,
PipelineRunner, and meshtrix.cli.
"""

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner

from meshtrix.core.step import RunContext
from meshtrix.diagnostics.failure import Severity
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
from tests.conftest import assert_check_failed, assert_check_passed

# ---------------------------------------------------------------------------
# Self-Contained Helpers & Opaque-Box Fault-Injecting Driver Adapter
# ---------------------------------------------------------------------------


def _build_lug_bracket_spec_dict(
    *,
    job_id: str = "JOB-P2-T3-BRACKET",
    load_tolerance: float = 0.01,
    direction_tolerance: float = 1e-4,
) -> dict[str, Any]:
    """Return a valid Phase 2 multi-body spec dictionary for Tier 3 combination tests."""
    return {
        "job_id": job_id,
        "spec_version": "1.0",
        "units": "Metric_mm",
        "analysis_type": "STRUCTURAL_STATIC",
        "materials": {
            "catalog": {
                "Structural_Steel_4340": {
                    "name": "Structural_Steel_4340",
                    "density": 7.85e-9,
                    "elastic_modulus": 205000.0,
                    "poissons_ratio": 0.29,
                    "yield_strength": 470.0,
                },
                "Aluminum_7075_T6": {
                    "name": "Aluminum_7075_T6",
                    "density": 2.81e-9,
                    "elastic_modulus": 71700.0,
                    "poissons_ratio": 0.33,
                    "yield_strength": 503.0,
                },
            },
            "mappings": {
                "Clevis_Body_Solid": {
                    "body_name": "Clevis_Body_Solid",
                    "material_name": "Structural_Steel_4340",
                    "thickness": None,
                },
                "Gusset_Plate_Shell": {
                    "body_name": "Gusset_Plate_Shell",
                    "material_name": "Aluminum_7075_T6",
                    "thickness": 3.0,
                },
            },
        },
        "mesh": {
            "global_size": 4.0,
            "element_order": "quadratic",
            "min_quality": 0.25,
            "quality_metric": "skewness",
            "local_refinements": [
                {
                    "name": "Lug_Pin_Refinement",
                    "selection": "NS_LUG_HOLE",
                    "element_size": 1.5,
                }
            ],
        },
        "tolerances": {
            "thickness_tolerance": 0.01,
            "mass_tolerance": 0.05,
            "load_tolerance": load_tolerance,
            "direction_tolerance": direction_tolerance,
        },
        "load_cases": [
            {
                "case_id": "LC1_Limit_Tension",
                "step_number": 1,
                "description": "Primary axial tension plus gravity",
                "forces": [
                    {
                        "name": "Lug_Axial_Force",
                        "selection": "NS_LUG_HOLE",
                        "magnitude": 15000.0,
                        "direction": [1.0, 0.0, 0.0],
                        "coordinate_system": "Global",
                    }
                ],
                "pressures": [
                    {
                        "name": "Bearing_Pressure",
                        "selection": "NS_BEARING_PAD",
                        "magnitude": 2.5,
                        "direction": [0.0, 0.0, -1.0],
                        "load_type": "pressure",
                        "coordinate_system": "Global",
                    }
                ],
                "accelerations": [
                    {
                        "name": "Gravity_2_5G",
                        "magnitude": 24525.0,
                        "direction": [0.0, 0.0, -1.0],
                        "selection": None,
                        "coordinate_system": "Global",
                    }
                ],
            }
        ],
        "supports": [
            {
                "name": "Base_Bolt_Pattern",
                "selection": "NS_BASE_BOLTS",
                "type": "fixed",
                "coordinate_system": "Global",
            },
            {
                "name": "Pin_Guide_Constraint",
                "selection": "NS_PIN_GUIDE",
                "type": "pinned",
                "coordinate_system": "Global",
            },
        ],
    }


def _create_seeded_driver(spec: JobSpec) -> MockMechanicalDriver:
    """Create a MockMechanicalDriver seeded from a JobSpec using public port APIs."""
    driver = MockMechanicalDriver()
    driver.seed_from_spec(spec)
    return driver


def _find_run_log_json(log_dir: Path, run_id: str) -> dict[str, Any]:
    """Locate and parse the persisted JSON run log matching run_id under log_dir."""
    for candidate in sorted(log_dir.rglob("*.json")):
        payload = json.loads(candidate.read_text(encoding="utf-8"))
        if isinstance(payload, dict) and payload.get("run_id") == run_id:
            return payload
    raise AssertionError(f"No JSON run log found for run_id='{run_id}' in {log_dir}")


class _PortFaultDriver(MockMechanicalDriver):
    """Opaque-box MockMechanicalDriver subclass simulating solver post-check corruptions."""

    def __init__(self) -> None:
        super().__init__()
        self.support_dof_override: dict[str, list[str]] = {}
        self.support_cs_override: dict[str, str] = {}
        self.load_sign_flip_cases: set[str] = set()
        self.load_magnitude_scale_cases: dict[str, float] = {}
        self.load_direction_override: dict[tuple[str, str | None], list[float]] = {}

    def get_supports(self) -> list[Any]:
        from meshtrix.drivers.base import SupportRecord

        records = super().get_supports()
        corrupted: list[SupportRecord] = []
        for rec in records:
            dofs = self.support_dof_override.get(rec.selection, list(rec.dofs))
            cs = self.support_cs_override.get(rec.selection, rec.coordinate_system)
            corrupted.append(
                SupportRecord(
                    name=rec.name,
                    selection=rec.selection,
                    support_type=rec.support_type,
                    dofs=dofs,
                    coordinate_system=cs,
                    displacement_values=rec.displacement_values,
                )
            )
        return corrupted

    def get_loads(self, case_id: str | None = None) -> list[Any]:
        from meshtrix.drivers.base import LoadRecord

        records = super().get_loads(case_id=case_id)
        corrupted: list[LoadRecord] = []
        for rec in records:
            mag = float(rec.magnitude)
            direction = list(rec.direction)
            if rec.case_id in self.load_sign_flip_cases:
                mag = -mag
            if rec.case_id in self.load_magnitude_scale_cases:
                mag *= self.load_magnitude_scale_cases[rec.case_id]
            key = (rec.case_id, rec.selection)
            if key in self.load_direction_override:
                direction = list(self.load_direction_override[key])
            corrupted.append(
                LoadRecord(
                    case_id=rec.case_id,
                    load_type=rec.load_type,
                    selection=rec.selection,
                    magnitude=mag,
                    direction=direction,
                    coordinate_system=rec.coordinate_system,
                    name=rec.name,
                )
            )
        return corrupted

    def clear_faults(self) -> None:
        super().clear_faults()
        self.support_dof_override.clear()
        self.support_cs_override.clear()
        self.load_sign_flip_cases.clear()
        self.load_magnitude_scale_cases.clear()
        self.load_direction_override.clear()


# ---------------------------------------------------------------------------
# Tier 3 Tests: T3-1 through T3-10
# ---------------------------------------------------------------------------


def test_full_pipeline_6_8_9_10_fault_injection_clear_and_resume(tmp_path: Path) -> None:
    """T3-1: Full 6->8->9->10 pipeline fails on Step 9 fault, clears, and resumes at Step 9."""
    from meshtrix.core.checkpoint import CheckpointManager
    from meshtrix.runner import PipelineRunner

    from meshtrix.diagnostics.failure import ERR_BC_EMPTY_SELECTION

    spec = JobSpec.from_dict(_build_lug_bracket_spec_dict())
    driver = _create_seeded_driver(spec)
    cp_dir = tmp_path / "checkpoints"
    log_dir = tmp_path / "logs"
    run_id = "t3_1_fault_clear_resume"

    driver.inject_empty_named_selection("NS_BASE_BOLTS")
    assert driver.get_named_selection_entities("NS_BASE_BOLTS") == []

    runner = PipelineRunner()
    res_fail = runner.run(
        spec,
        driver,
        run_id=run_id,
        checkpoint_dir=cp_dir,
        log_dir=log_dir,
    )

    assert res_fail.success is False
    assert res_fail.status == "failed"
    assert res_fail.completed_steps == ["step_06_materials", "step_08_meshing"]
    assert "step_10_loads" not in res_fail.completed_steps
    assert any(f.error_code == ERR_BC_EMPTY_SELECTION for f in res_fail.failures)

    ckpt_mgr = CheckpointManager(cp_dir)
    assert ckpt_mgr.has_checkpoint(run_id, "step_06_materials") is True
    assert ckpt_mgr.has_checkpoint(run_id, "step_08_meshing") is True

    driver.clear_faults()
    assert len(driver.get_named_selection_entities("NS_BASE_BOLTS")) > 0

    res_pass = runner.run(
        spec,
        driver,
        run_id=run_id,
        resume_from="step_09_boundary_conditions",
        checkpoint_dir=cp_dir,
        log_dir=log_dir,
    )

    assert res_pass.success is True
    assert res_pass.status == "passed"
    assert res_pass.skipped_steps == ["step_06_materials", "step_08_meshing"]
    assert res_pass.completed_steps == ["step_09_boundary_conditions", "step_10_loads"]
    assert len(driver.get_supports()) == 2
    assert len(driver.get_loads("LC1_Limit_Tension")) == 3


def test_cli_validate_run_resume_inspect_workflow(tmp_path: Path) -> None:
    """T3-2: CLI validate -> run --mock -> run --resume-from step_10_loads -> inspect-run."""
    from meshtrix.cli.main import app

    spec_dict = _build_lug_bracket_spec_dict(job_id="JOB-T3-CLI-WORKFLOW")
    spec_path = tmp_path / "spec.yaml"
    spec_path.write_text(yaml.safe_dump(spec_dict, sort_keys=False), encoding="utf-8")

    cp_dir = tmp_path / "cp"
    log_dir = tmp_path / "logs"
    run_id = "t3_2_cli_run"
    cli = CliRunner()

    val_res = cli.invoke(app, ["validate", str(spec_path)])
    assert val_res.exit_code == 0, val_res.output

    run1_res = cli.invoke(
        app,
        [
            "run",
            str(spec_path),
            "--mock",
            "--run-id",
            run_id,
            "--checkpoint-dir",
            str(cp_dir),
            "--log-dir",
            str(log_dir),
        ],
    )
    assert run1_res.exit_code == 0, run1_res.output

    run2_res = cli.invoke(
        app,
        [
            "run",
            str(spec_path),
            "--mock",
            "--run-id",
            run_id,
            "--resume-from",
            "step_10_loads",
            "--checkpoint-dir",
            str(cp_dir),
            "--log-dir",
            str(log_dir),
        ],
    )
    assert run2_res.exit_code == 0, run2_res.output

    insp_res = cli.invoke(
        app,
        [
            "inspect-run",
            run_id,
            "--checkpoint-dir",
            str(cp_dir),
            "--log-dir",
            str(log_dir),
        ],
    )
    assert insp_res.exit_code == 0, insp_res.output
    assert run_id in insp_res.output
    assert "JOB-T3-CLI-WORKFLOW" in insp_res.output
    assert "passed" in insp_res.output.lower()

    log_payload = _find_run_log_json(log_dir, run_id)
    assert log_payload["status"] == "passed"
    assert log_payload["resumed_from"] == "step_10_loads"


def test_multi_support_and_multi_load_case_combinations(tmp_path: Path) -> None:
    """T3-3: Combine fixed, pinned, frictionless, displacement supports across 3 load cases."""
    from meshtrix.runner import PipelineRunner

    spec_dict = _build_lug_bracket_spec_dict(job_id="JOB-T3-MULTI-BC-LC")
    spec_dict["supports"] = [
        {"name": "Base_Fixed", "selection": "NS_BASE_BOLTS", "type": "fixed"},
        {"name": "Clevis_Pinned", "selection": "NS_PIN_GUIDE", "type": "pinned"},
        {"name": "Sym_Frictionless", "selection": "NS_SYM_PLANE", "type": "frictionless"},
        {
            "name": "Slot_Displacement",
            "selection": "NS_SLOT_FACE",
            "type": "displacement",
            "dofs": ["UX", "RZ"],
            "displacement_values": {"UX": 0.0, "RZ": 0.0},
            "coordinate_system": "Slot_Local_CS",
        },
    ]
    spec_dict["load_cases"] = [
        {
            "case_id": "LC1_Axial",
            "step_number": 1,
            "forces": [
                {"selection": "NS_LUG_HOLE", "magnitude": 12000.0, "direction": [1.0, 0.0, 0.0]}
            ],
        },
        {
            "case_id": "LC2_Shear_Pressure",
            "step_number": 2,
            "forces": [
                {"selection": "NS_LUG_HOLE", "magnitude": 8500.0, "direction": [0.0, 1.0, 0.0]}
            ],
            "pressures": [
                {
                    "selection": "NS_BEARING_PAD",
                    "magnitude": 4.0,
                    "direction": [0.0, 0.0, -1.0],
                    "load_type": "pressure",
                }
            ],
        },
        {
            "case_id": "LC3_Inertial_9G",
            "step_number": 3,
            "accelerations": [
                {"magnitude": 88290.0, "direction": [0.0, 0.0, -1.0], "selection": None}
            ],
        },
    ]
    spec = JobSpec.from_dict(spec_dict)
    driver = _create_seeded_driver(spec)

    result = PipelineRunner().run(
        spec,
        driver,
        run_id="t3_3_multi_bc_lc",
        checkpoint_dir=tmp_path / "cp",
        log_dir=tmp_path / "logs",
    )

    assert result.success is True
    assert result.completed_steps == [
        "step_06_materials",
        "step_08_meshing",
        "step_09_boundary_conditions",
        "step_10_loads",
    ]

    supports = {s.selection: s for s in driver.get_supports()}
    assert len(supports) == 4
    assert set(supports["NS_BASE_BOLTS"].dofs) == {"UX", "UY", "UZ", "RX", "RY", "RZ"}
    assert set(supports["NS_PIN_GUIDE"].dofs) == {"UX", "UY", "UZ"}
    assert set(supports["NS_SYM_PLANE"].dofs) == {"NORMAL"}
    assert set(supports["NS_SLOT_FACE"].dofs) == {"UX", "RZ"}
    assert supports["NS_SLOT_FACE"].coordinate_system == "Slot_Local_CS"

    lc1 = driver.get_loads("LC1_Axial")
    lc2 = driver.get_loads("LC2_Shear_Pressure")
    lc3 = driver.get_loads("LC3_Inertial_9G")
    assert len(lc1) == 1
    assert lc1[0].magnitude == pytest.approx(12000.0)
    assert len(lc2) == 2
    assert {r.load_type for r in lc2} == {"force", "pressure"}
    assert len(lc3) == 1
    assert lc3[0].load_type == "acceleration"
    assert lc3[0].magnitude == pytest.approx(88290.0)


def test_mixed_forces_pressures_accelerations_custom_tolerances(tmp_path: Path) -> None:
    """T3-4: Tight custom CheckTolerances catches 5e-4 error that default 0.01 would permit."""
    from meshtrix.runner import PipelineRunner

    from meshtrix.diagnostics.failure import ERR_LOAD_TOTAL_MISMATCH

    # Nominal pass under tight custom tolerances
    tight_dict = _build_lug_bracket_spec_dict(
        job_id="JOB-T3-TIGHT-TOL",
        load_tolerance=1e-4,
        direction_tolerance=1e-6,
    )
    tight_dict["load_cases"][0]["forces"][0]["coordinate_system"] = "Lug_Local_CS"
    tight_spec = JobSpec.from_dict(tight_dict)

    clean_driver = _create_seeded_driver(tight_spec)
    res_clean = PipelineRunner().run(
        tight_spec,
        clean_driver,
        run_id="t3_4_clean",
        checkpoint_dir=tmp_path / "cp_clean",
        log_dir=tmp_path / "logs_clean",
    )
    assert res_clean.success is True

    # 5e-4 relative magnitude error passes default load_tolerance=0.01
    default_dict = deepcopy(tight_dict)
    default_dict["tolerances"]["load_tolerance"] = 0.01
    default_spec = JobSpec.from_dict(default_dict)

    default_driver = _PortFaultDriver()
    default_driver.seed_from_spec(default_spec)
    default_driver.load_magnitude_scale_cases["LC1_Limit_Tension"] = 1.0005
    res_default = PipelineRunner().run(
        default_spec,
        default_driver,
        run_id="t3_4_default_tol",
        checkpoint_dir=tmp_path / "cp_default",
        log_dir=tmp_path / "logs_default",
    )
    assert res_default.success is True

    # Same 5e-4 relative magnitude error fails under custom load_tolerance=1e-4
    tight_driver = _PortFaultDriver()
    tight_driver.seed_from_spec(tight_spec)
    tight_driver.load_magnitude_scale_cases["LC1_Limit_Tension"] = 1.0005
    res_tight = PipelineRunner().run(
        tight_spec,
        tight_driver,
        run_id="t3_4_tight_tol",
        checkpoint_dir=tmp_path / "cp_tight",
        log_dir=tmp_path / "logs_tight",
    )
    assert res_tight.success is False
    assert any(f.error_code == ERR_LOAD_TOTAL_MISMATCH for f in res_tight.failures)


def test_step09_and_step10_concurrent_diagnostic_aggregation() -> None:
    """T3-5: Step 9 and Step 10 aggregate multiple concurrent faults and preserve them in troubleshoot."""
    from meshtrix.steps.step_09_boundary_conditions import Step09BoundaryConditions
    from meshtrix.steps.step_10_loads import Step10Loads

    from meshtrix.diagnostics.failure import (
        ERR_BC_COORDINATE_SYSTEM_MISMATCH,
        ERR_BC_DOF_MISMATCH,
        ERR_BC_EMPTY_SELECTION,
        ERR_BC_MISSING_SELECTION,
        ERR_LOAD_DIRECTION_MISMATCH,
        ERR_LOAD_SIGN_MISMATCH,
        ERR_LOAD_TOTAL_MISMATCH,
    )

    # Part A: Step 9 pre_check aggregates missing + empty named selections
    spec_dict = _build_lug_bracket_spec_dict(job_id="JOB-T3-CONCURRENT-DIAG")
    spec_pre = JobSpec.from_dict(spec_dict)
    driver_pre = MockMechanicalDriver()
    driver_pre.create_named_selection("NS_BASE_BOLTS", [])  # empty
    # NS_PIN_GUIDE is intentionally omitted (missing)

    step09 = Step09BoundaryConditions()
    ctx_pre = RunContext(spec=spec_pre, driver=driver_pre)
    pre_res = step09.pre_check(ctx_pre)
    assert_check_failed(pre_res)
    pre_codes = {f.error_code for f in pre_res.failures}
    assert ERR_BC_EMPTY_SELECTION in pre_codes
    assert ERR_BC_MISSING_SELECTION in pre_codes
    troubleshoot_pre = step09.troubleshoot(ctx_pre, pre_res)
    assert {f.error_code for f in troubleshoot_pre} == pre_codes

    # Part B: Step 9 post_check aggregates DOF mismatch + coordinate system mismatch
    driver_bc = _PortFaultDriver()
    driver_bc.seed_from_spec(spec_pre)
    ctx_bc = RunContext(spec=spec_pre, driver=driver_bc)
    assert_check_passed(step09.pre_check(ctx_bc))
    step09.execute(ctx_bc)
    driver_bc.support_dof_override["NS_BASE_BOLTS"] = ["UX", "UY"]
    driver_bc.support_cs_override["NS_PIN_GUIDE"] = "Wrong_Cylindrical_CS"

    post_bc_res = step09.post_check(ctx_bc)
    assert_check_failed(post_bc_res)
    bc_post_codes = {f.error_code for f in post_bc_res.failures}
    assert ERR_BC_DOF_MISMATCH in bc_post_codes
    assert ERR_BC_COORDINATE_SYSTEM_MISMATCH in bc_post_codes
    assert {f.error_code for f in step09.troubleshoot(ctx_bc, post_bc_res)} == bc_post_codes

    # Part C: Step 10 post_check aggregates sign, direction, and total mismatch
    multi_lc_dict = deepcopy(spec_dict)
    multi_lc_dict["load_cases"] = [
        {
            "case_id": "LC_Sign_Fault",
            "forces": [
                {"selection": "NS_LUG_HOLE", "magnitude": 10000.0, "direction": [1.0, 0.0, 0.0]}
            ],
        },
        {
            "case_id": "LC_Dir_Fault",
            "forces": [
                {"selection": "NS_PIN_GUIDE", "magnitude": 5000.0, "direction": [0.0, 1.0, 0.0]}
            ],
        },
        {
            "case_id": "LC_Mag_Fault",
            "pressures": [
                {
                    "selection": "NS_BEARING_PAD",
                    "magnitude": 4.0,
                    "direction": [0.0, 0.0, -1.0],
                    "load_type": "pressure",
                }
            ],
        },
    ]
    spec_load = JobSpec.from_dict(multi_lc_dict)
    driver_load = _PortFaultDriver()
    driver_load.seed_from_spec(spec_load)
    ctx_load = RunContext(spec=spec_load, driver=driver_load)

    step10 = Step10Loads()
    assert_check_passed(step10.pre_check(ctx_load))
    step10.execute(ctx_load)
    driver_load.load_sign_flip_cases.add("LC_Sign_Fault")
    driver_load.load_direction_override[("LC_Dir_Fault", "NS_PIN_GUIDE")] = [0.0, 0.0, 1.0]
    driver_load.load_magnitude_scale_cases["LC_Mag_Fault"] = 2.0

    post_load_res = step10.post_check(ctx_load)
    assert_check_failed(post_load_res)
    load_codes = {f.error_code for f in post_load_res.failures}
    assert ERR_LOAD_SIGN_MISMATCH in load_codes
    assert ERR_LOAD_DIRECTION_MISMATCH in load_codes
    assert ERR_LOAD_TOTAL_MISMATCH in load_codes
    troubleshoot_loads = step10.troubleshoot(ctx_load, post_load_res)
    assert {f.error_code for f in troubleshoot_loads} == load_codes
    assert all(f.severity == Severity.BLOCKING for f in troubleshoot_loads)


def test_driver_export_import_state_roundtrip_across_pipeline_resume(tmp_path: Path) -> None:
    """T3-6: Export driver state after Steps 6 & 8, import into fresh driver, resume Steps 9 & 10."""
    from meshtrix.runner import PipelineRunner

    spec = JobSpec.from_dict(_build_lug_bracket_spec_dict(job_id="JOB-T3-STATE-ROUNDTRIP"))
    driver1 = _create_seeded_driver(spec)
    # Remove one BC named selection so Steps 6 & 8 pass and checkpoint, while Step 9 halts cleanly
    driver1.inject_missing_named_selection("NS_BASE_BOLTS")

    cp_dir = tmp_path / "cp"
    log_dir = tmp_path / "logs"
    run_id = "t3_6_roundtrip"

    runner = PipelineRunner()
    res1 = runner.run(spec, driver1, run_id=run_id, checkpoint_dir=cp_dir, log_dir=log_dir)
    assert res1.success is False
    assert res1.completed_steps == ["step_06_materials", "step_08_meshing"]

    # Round-trip driver state through JSON serialization into a brand-new driver instance
    exported_json = json.dumps(driver1.export_state())
    restored_state = json.loads(exported_json)

    driver2 = MockMechanicalDriver()
    driver2.import_state(restored_state)
    # Supply the missing named selection on the new driver instance
    driver2.create_named_selection("NS_BASE_BOLTS", ["Base_Face_1", "Base_Face_2"])

    assert driver2.get_assigned_material("Clevis_Body_Solid") == "Structural_Steel_4340"
    assert driver2.get_shell_thickness("Gusset_Plate_Shell") == pytest.approx(3.0)
    assert driver2.is_mesh_generated() is True
    assert driver2.get_element_count() > 0

    res2 = runner.run(
        spec,
        driver2,
        run_id=run_id,
        resume_from="step_09_boundary_conditions",
        checkpoint_dir=cp_dir,
        log_dir=log_dir,
    )
    assert res2.success is True
    assert res2.skipped_steps == ["step_06_materials", "step_08_meshing"]
    assert res2.completed_steps == ["step_09_boundary_conditions", "step_10_loads"]


def test_step10_fault_after_step09_checkpoint_resumes_at_step10_only(tmp_path: Path) -> None:
    """T3-7: Steps 6, 8, 9 checkpoint cleanly; Step 10 sign fault clears and resumes Step 10 only."""
    from meshtrix.core.checkpoint import CheckpointManager
    from meshtrix.runner import PipelineRunner

    from meshtrix.diagnostics.failure import ERR_LOAD_SIGN_MISMATCH

    spec = JobSpec.from_dict(_build_lug_bracket_spec_dict(job_id="JOB-T3-RESUME-STEP10"))
    driver = _PortFaultDriver()
    driver.seed_from_spec(spec)
    driver.load_sign_flip_cases.add("LC1_Limit_Tension")

    cp_dir = tmp_path / "cp"
    log_dir = tmp_path / "logs"
    run_id = "t3_7_step10_resume"

    runner = PipelineRunner()
    res1 = runner.run(spec, driver, run_id=run_id, checkpoint_dir=cp_dir, log_dir=log_dir)

    assert res1.success is False
    assert res1.status == "failed"
    assert res1.completed_steps == [
        "step_06_materials",
        "step_08_meshing",
        "step_09_boundary_conditions",
    ]
    assert any(f.error_code == ERR_LOAD_SIGN_MISMATCH for f in res1.failures)

    ckpt_mgr = CheckpointManager(cp_dir)
    for sid in ("step_06_materials", "step_08_meshing", "step_09_boundary_conditions"):
        assert ckpt_mgr.has_checkpoint(run_id, sid) is True

    driver.clear_faults()
    res2 = runner.run(
        spec,
        driver,
        run_id=run_id,
        resume_from="step_10_loads",
        checkpoint_dir=cp_dir,
        log_dir=log_dir,
    )

    assert res2.success is True
    assert res2.status == "passed"
    assert res2.skipped_steps == [
        "step_06_materials",
        "step_08_meshing",
        "step_09_boundary_conditions",
    ]
    assert res2.completed_steps == ["step_10_loads"]


def test_modal_free_free_full_4_step_pipeline_and_audit_log(tmp_path: Path) -> None:
    """T3-8: MODAL free-free (supports=[], load_cases=[]) completes all 4 steps and audit log."""
    from meshtrix.core.checkpoint import CheckpointManager
    from meshtrix.runner import PipelineRunner

    modal_dict = _build_lug_bracket_spec_dict(job_id="JOB-T3-MODAL-FREE-FREE")
    modal_dict["analysis_type"] = AnalysisType.MODAL.value
    modal_dict["supports"] = []
    modal_dict["load_cases"] = []
    spec = JobSpec.from_dict(modal_dict)
    driver = _create_seeded_driver(spec)

    cp_dir = tmp_path / "cp"
    log_dir = tmp_path / "logs"
    run_id = "t3_8_modal_free"

    result = PipelineRunner().run(
        spec,
        driver,
        run_id=run_id,
        checkpoint_dir=cp_dir,
        log_dir=log_dir,
    )

    assert result.success is True
    assert result.status == "passed"
    assert result.completed_steps == [
        "step_06_materials",
        "step_08_meshing",
        "step_09_boundary_conditions",
        "step_10_loads",
    ]
    assert driver.get_supports() == []
    assert driver.get_loads() == []

    ckpts = CheckpointManager(cp_dir).list_checkpoints(run_id)
    assert set(ckpts) == {
        "step_06_materials",
        "step_08_meshing",
        "step_09_boundary_conditions",
        "step_10_loads",
    }

    log_data = json.loads(result.log_path.read_text(encoding="utf-8"))
    assert log_data["status"] == "passed"
    assert log_data["spec_version"] == "1.0"
    assert isinstance(log_data["spec_hash"], str) and len(log_data["spec_hash"]) > 0
    assert isinstance(log_data["tool_versions"], dict) and len(log_data["tool_versions"]) > 0
    assert len(log_data["steps"]) == 4


def test_cli_mock_state_fault_detection_fix_and_resume(tmp_path: Path) -> None:
    """T3-9: CLI --mock-state detects empty NS_LUG_HOLE, remedies JSON, and resumes cleanly."""
    from meshtrix.cli.main import app

    spec_dict = _build_lug_bracket_spec_dict(job_id="JOB-T3-MOCK-STATE")
    spec = JobSpec.from_dict(spec_dict)
    spec_path = tmp_path / "spec.yaml"
    spec_path.write_text(yaml.safe_dump(spec_dict, sort_keys=False), encoding="utf-8")

    # Build faulty mock state with empty NS_LUG_HOLE
    bad_driver = _create_seeded_driver(spec)
    bad_driver.create_named_selection("NS_LUG_HOLE", [])
    bad_state_path = tmp_path / "bad_state.json"
    bad_state_path.write_text(json.dumps(bad_driver.export_state()), encoding="utf-8")

    # Build remediated mock state preserving prior state and restoring NS_LUG_HOLE entities
    fixed_driver = MockMechanicalDriver()
    fixed_driver.import_state(json.loads(bad_state_path.read_text(encoding="utf-8")))
    fixed_driver.create_named_selection("NS_LUG_HOLE", ["Lug_Bore_Face_1", "Lug_Bore_Face_2"])
    fixed_state_path = tmp_path / "fixed_state.json"
    fixed_state_path.write_text(json.dumps(fixed_driver.export_state()), encoding="utf-8")

    cp_dir = tmp_path / "cp"
    log_dir = tmp_path / "logs"
    run_id = "t3_9_mock_state"
    cli = CliRunner()

    res_fail = cli.invoke(
        app,
        [
            "run",
            str(spec_path),
            "--mock",
            "--mock-state",
            str(bad_state_path),
            "--run-id",
            run_id,
            "--checkpoint-dir",
            str(cp_dir),
            "--log-dir",
            str(log_dir),
        ],
    )
    assert res_fail.exit_code != 0
    assert "NS_LUG_HOLE" in res_fail.output

    res_recover = cli.invoke(
        app,
        [
            "run",
            str(spec_path),
            "--mock",
            "--mock-state",
            str(fixed_state_path),
            "--run-id",
            run_id,
            "--resume-from",
            "step_09_boundary_conditions",
            "--checkpoint-dir",
            str(cp_dir),
            "--log-dir",
            str(log_dir),
        ],
    )
    assert res_recover.exit_code == 0, res_recover.output

    res_inspect = cli.invoke(
        app,
        [
            "inspect-run",
            run_id,
            "--checkpoint-dir",
            str(cp_dir),
            "--log-dir",
            str(log_dir),
        ],
    )
    assert res_inspect.exit_code == 0, res_inspect.output
    assert "passed" in res_inspect.output.lower()


def test_aerospace_phase1_spec_upgraded_to_phase2_pipeline(
    aerospace_assembly_spec_dict: dict[str, Any],
    tmp_path: Path,
) -> None:
    """T3-10: Phase 1 aerospace_assembly_spec_dict runs end-to-end through Phase 2 PipelineRunner."""
    from meshtrix.runner import PipelineRunner

    # Ensure backward compatibility without mutating the shared fixture dict
    raw_dict = deepcopy(aerospace_assembly_spec_dict)
    spec = JobSpec.from_dict(raw_dict)
    assert spec.spec_version == "1.0"
    assert isinstance(spec.tolerances, CheckTolerances)
    assert isinstance(spec.supports[0], SupportSpec)
    assert spec.supports[0].type == SupportType.FIXED
    assert isinstance(spec.load_cases[0], LoadCase)
    assert isinstance(spec.load_cases[0].forces[0], LoadSpec)
    assert spec.load_cases[0].forces[0].load_type == LoadType.FORCE

    driver = _create_seeded_driver(spec)
    result = PipelineRunner().run(
        spec,
        driver,
        run_id="t3_10_phase1_compat",
        checkpoint_dir=tmp_path / "cp",
        log_dir=tmp_path / "logs",
    )

    assert result.success is True
    assert result.status == "passed"
    assert result.completed_steps == [
        "step_06_materials",
        "step_08_meshing",
        "step_09_boundary_conditions",
        "step_10_loads",
    ]
    supports = driver.get_supports()
    assert len(supports) == 1
    assert supports[0].selection == "NS_FUSELAGE_FRAME_MOUNT"
    loads = driver.get_loads("LC_Limit_Maneuver_2_5G")
    assert len(loads) == 1
    assert loads[0].magnitude == pytest.approx(25000.0)
    assert loads[0].direction == pytest.approx([0.0, 0.0, 1.0])

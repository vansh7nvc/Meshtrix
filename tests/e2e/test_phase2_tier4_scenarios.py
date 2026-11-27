"""
Phase 2 E2E Tests — Tier 4: Real-World Engineering Application Scenarios (T4-1 through T4-6).

Authoritative Reference: ORIGINAL_REQUEST.md & PROJECT.md § Interface Contracts
Methodology: Opaque-box end-to-end engineering workflows covering aerospace lugs,
pressure vessels, wing spars (static vs modal), multi-load-case fault recovery,
and CLI audit / mock-state remediation pipelines.
"""

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner

from meshtrix.drivers.mock import MockMechanicalDriver
from meshtrix.spec.job_spec import AnalysisType, JobSpec

# ---------------------------------------------------------------------------
# Self-Contained Scenario Helpers & Opaque-Box Fault Driver
# ---------------------------------------------------------------------------


def _find_run_log_json(log_dir: Path, run_id: str) -> dict[str, Any]:
    """Locate and parse the persisted JSON run log matching run_id under log_dir."""
    for candidate in sorted(log_dir.rglob("*.json")):
        payload = json.loads(candidate.read_text(encoding="utf-8"))
        if isinstance(payload, dict) and payload.get("run_id") == run_id:
            return payload
    raise AssertionError(f"No JSON run log found for run_id='{run_id}' in {log_dir}")


class _LoadFaultDriver(MockMechanicalDriver):
    """Opaque-box MockMechanicalDriver subclass simulating Step 10 load faults."""

    def __init__(self) -> None:
        super().__init__()
        self.sign_flip_cases: set[str] = set()
        self.magnitude_scale_cases: dict[str, float] = {}

    def get_loads(self, case_id: str | None = None) -> list[Any]:
        from meshtrix.drivers.base import LoadRecord

        records = super().get_loads(case_id=case_id)
        corrupted: list[LoadRecord] = []
        for rec in records:
            mag = float(rec.magnitude)
            if rec.case_id in self.sign_flip_cases:
                mag = -mag
            if rec.case_id in self.magnitude_scale_cases:
                mag *= self.magnitude_scale_cases[rec.case_id]
            corrupted.append(
                LoadRecord(
                    case_id=rec.case_id,
                    load_type=rec.load_type,
                    selection=rec.selection,
                    magnitude=mag,
                    direction=list(rec.direction),
                    coordinate_system=rec.coordinate_system,
                    name=rec.name,
                )
            )
        return corrupted

    def clear_faults(self) -> None:
        super().clear_faults()
        self.sign_flip_cases.clear()
        self.magnitude_scale_cases.clear()


def _aerospace_bracket_multi_lc_dict() -> dict[str, Any]:
    """Build a realistic 3-load-case aerospace bracket specification dictionary."""
    return {
        "job_id": "JOB-T4-AERO-BRACKET-3LC",
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
                "Bracket_Clevis_Solid": {
                    "body_name": "Bracket_Clevis_Solid",
                    "material_name": "Structural_Steel_4340",
                    "thickness": None,
                },
                "Bracket_Gusset_Left": {
                    "body_name": "Bracket_Gusset_Left",
                    "material_name": "Aluminum_7075_T6",
                    "thickness": 2.5,
                },
                "Bracket_Gusset_Right": {
                    "body_name": "Bracket_Gusset_Right",
                    "material_name": "Aluminum_7075_T6",
                    "thickness": 2.5,
                },
            },
        },
        "mesh": {
            "global_size": 3.5,
            "element_order": "quadratic",
            "min_quality": 0.25,
            "quality_metric": "skewness",
            "local_refinements": [
                {
                    "name": "Clevis_Pin_Refinement",
                    "selection": "NS_PIN_BORE",
                    "element_size": 1.25,
                }
            ],
        },
        "tolerances": {
            "thickness_tolerance": 0.01,
            "mass_tolerance": 0.05,
            "load_tolerance": 0.01,
            "direction_tolerance": 1e-4,
        },
        "supports": [
            {
                "name": "Base_Mount_Fixed",
                "selection": "NS_BASE_MOUNT",
                "type": "fixed",
                "coordinate_system": "Global",
            },
            {
                "name": "Guide_Slot_Disp",
                "selection": "NS_GUIDE_SLOT",
                "type": "displacement",
                "dofs": ["UY", "UZ"],
                "displacement_values": {"UY": 0.0, "UZ": 0.0},
                "coordinate_system": "Global",
            },
        ],
        "load_cases": [
            {
                "case_id": "LC1_Limit_2_5G",
                "step_number": 1,
                "description": "Limit axial tension + 2.5G downward acceleration",
                "forces": [
                    {
                        "name": "Limit_Axial",
                        "selection": "NS_PIN_BORE",
                        "magnitude": 18000.0,
                        "direction": [1.0, 0.0, 0.0],
                    }
                ],
                "accelerations": [
                    {
                        "name": "Accel_2_5G",
                        "magnitude": 24525.0,
                        "direction": [0.0, 0.0, -1.0],
                        "selection": None,
                    }
                ],
            },
            {
                "case_id": "LC2_Lateral_Gust",
                "step_number": 2,
                "description": "Lateral gust shear loading",
                "forces": [
                    {
                        "name": "Gust_Shear",
                        "selection": "NS_PIN_BORE",
                        "magnitude": 9500.0,
                        "direction": [0.0, 1.0, 0.0],
                    }
                ],
            },
            {
                "case_id": "LC3_Crash_9G",
                "step_number": 3,
                "description": "Emergency 9G forward crash inertial load",
                "forces": [
                    {
                        "name": "Crash_Bearing",
                        "selection": "NS_PIN_BORE",
                        "magnitude": 42000.0,
                        "direction": [0.8, 0.0, -0.6],
                    }
                ],
                "accelerations": [
                    {
                        "name": "Accel_9G",
                        "magnitude": 88290.0,
                        "direction": [1.0, 0.0, 0.0],
                        "selection": None,
                    }
                ],
            },
        ],
    }


# ---------------------------------------------------------------------------
# Tier 4 Scenarios: T4-1 through T4-6
# ---------------------------------------------------------------------------


def test_scenario_aerospace_lug_bracket_tension_and_gravity(tmp_path: Path) -> None:
    """T4-1: Aerospace lug bracket under axial/lateral tension + 2.5G gravity across 4 steps."""
    from meshtrix.runner import PipelineRunner

    spec_dict: dict[str, Any] = {
        "job_id": "JOB-T4-LUG-BRACKET-01",
        "spec_version": "1.0",
        "units": "Metric_mm",
        "analysis_type": "STRUCTURAL_STATIC",
        "materials": {
            "catalog": {
                "Steel_4340": {
                    "name": "Steel_4340",
                    "density": 7.85e-9,
                    "elastic_modulus": 205000.0,
                    "poissons_ratio": 0.29,
                    "yield_strength": 470.0,
                },
                "Al_7075_T6": {
                    "name": "Al_7075_T6",
                    "density": 2.81e-9,
                    "elastic_modulus": 71700.0,
                    "poissons_ratio": 0.33,
                    "yield_strength": 503.0,
                },
            },
            "mappings": {
                "Lug_Clevis_Solid": {
                    "body_name": "Lug_Clevis_Solid",
                    "material_name": "Steel_4340",
                    "thickness": None,
                },
                "Lug_Gusset_Shell": {
                    "body_name": "Lug_Gusset_Shell",
                    "material_name": "Al_7075_T6",
                    "thickness": 3.2,
                },
            },
        },
        "mesh": {
            "global_size": 4.0,
            "element_order": "quadratic",
            "min_quality": 0.25,
            "quality_metric": "skewness",
        },
        "supports": [
            {"name": "Base_Bolts", "selection": "NS_BASE_BOLTS", "type": "fixed"},
            {"name": "Pin_Bore", "selection": "NS_PIN_BORE", "type": "pinned"},
        ],
        "load_cases": [
            {
                "case_id": "LC_Tension_2_5G",
                "step_number": 1,
                "forces": [
                    {
                        "name": "Axial_Tension",
                        "selection": "NS_PIN_BORE",
                        "magnitude": 22000.0,
                        "direction": [1.0, 0.0, 0.0],
                    },
                    {
                        "name": "Lateral_Shear",
                        "selection": "NS_PIN_BORE",
                        "magnitude": 4500.0,
                        "direction": [0.0, 1.0, 0.0],
                    },
                ],
                "accelerations": [
                    {
                        "name": "Gravity_2_5G",
                        "magnitude": 24525.0,
                        "direction": [0.0, 0.0, -1.0],
                        "selection": None,
                    }
                ],
            }
        ],
    }

    spec = JobSpec.from_dict(spec_dict)
    driver = MockMechanicalDriver()
    driver.seed_from_spec(spec)

    result = PipelineRunner().run(
        spec,
        driver,
        run_id="t4_1_lug_bracket",
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
    assert driver.get_assigned_material("Lug_Clevis_Solid") == "Steel_4340"
    assert driver.get_assigned_material("Lug_Gusset_Shell") == "Al_7075_T6"
    assert driver.get_shell_thickness("Lug_Gusset_Shell") == pytest.approx(3.2)
    assert driver.is_mesh_generated() is True
    assert driver.get_element_count() > 0

    supports = {s.selection: s for s in driver.get_supports()}
    assert set(supports["NS_BASE_BOLTS"].dofs) == {"UX", "UY", "UZ", "RX", "RY", "RZ"}
    assert set(supports["NS_PIN_BORE"].dofs) == {"UX", "UY", "UZ"}

    loads = driver.get_loads("LC_Tension_2_5G")
    assert len(loads) == 3
    forces = [r for r in loads if r.load_type == "force"]
    accels = [r for r in loads if r.load_type == "acceleration"]
    assert len(forces) == 2
    assert sum(r.magnitude for r in forces) == pytest.approx(26500.0)
    assert len(accels) == 1
    assert accels[0].magnitude == pytest.approx(24525.0)
    assert accels[0].direction == pytest.approx([0.0, 0.0, -1.0])


def test_scenario_cylindrical_pressure_vessel_pinned_and_frictionless(tmp_path: Path) -> None:
    """T4-2: Ti-6Al-4V pressure vessel with weld refinement, pinned/frictionless BCs, pressure."""
    from meshtrix.runner import PipelineRunner

    spec_dict: dict[str, Any] = {
        "job_id": "JOB-T4-PRESSURE-VESSEL-02",
        "spec_version": "1.0",
        "units": "Metric_mm",
        "analysis_type": "STRUCTURAL_STATIC",
        "materials": {
            "catalog": {
                "Titanium_Ti6Al4V": {
                    "name": "Titanium_Ti6Al4V",
                    "density": 4.43e-9,
                    "elastic_modulus": 113800.0,
                    "poissons_ratio": 0.342,
                    "yield_strength": 880.0,
                },
                "Stainless_316L": {
                    "name": "Stainless_316L",
                    "density": 8.00e-9,
                    "elastic_modulus": 193000.0,
                    "poissons_ratio": 0.30,
                    "yield_strength": 290.0,
                },
            },
            "mappings": {
                "Vessel_Cylindrical_Shell": {
                    "body_name": "Vessel_Cylindrical_Shell",
                    "material_name": "Titanium_Ti6Al4V",
                    "thickness": 4.5,
                },
                "Nozzle_Flange_Solid": {
                    "body_name": "Nozzle_Flange_Solid",
                    "material_name": "Stainless_316L",
                    "thickness": None,
                },
            },
        },
        "mesh": {
            "global_size": 5.0,
            "element_order": "quadratic",
            "min_quality": 0.25,
            "quality_metric": "skewness",
            "local_refinements": [
                {
                    "name": "Nozzle_Weld_Refinement",
                    "selection": "NS_NOZZLE_WELD",
                    "element_size": 1.5,
                }
            ],
        },
        "supports": [
            {"name": "Saddle_Supports", "selection": "NS_SADDLE_SUPPORTS", "type": "pinned"},
            {
                "name": "Axial_Symmetry",
                "selection": "NS_SYM_AXIAL",
                "type": "frictionless",
            },
        ],
        "load_cases": [
            {
                "case_id": "LC1_Operating_Pressure",
                "step_number": 1,
                "pressures": [
                    {
                        "name": "Internal_Pressure_2_4MPa",
                        "selection": "NS_VESSEL_INNER_WALL",
                        "magnitude": 2.4,
                        "direction": [0.0, 0.0, 1.0],
                        "load_type": "pressure",
                    }
                ],
            }
        ],
    }

    spec = JobSpec.from_dict(spec_dict)
    driver = MockMechanicalDriver()
    driver.seed_from_spec(spec)

    result = PipelineRunner().run(
        spec,
        driver,
        run_id="t4_2_pressure_vessel",
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
    refinements = driver.get_local_refinements()
    assert any(r["selection"] == "NS_NOZZLE_WELD" for r in refinements)

    supports = {s.selection: s for s in driver.get_supports()}
    assert set(supports["NS_SADDLE_SUPPORTS"].dofs) == {"UX", "UY", "UZ"}
    assert set(supports["NS_SYM_AXIAL"].dofs) == {"NORMAL"}

    loads = driver.get_loads("LC1_Operating_Pressure")
    assert len(loads) == 1
    assert loads[0].load_type == "pressure"
    assert loads[0].selection == "NS_VESSEL_INNER_WALL"
    assert loads[0].magnitude == pytest.approx(2.4)


def test_scenario_cantilevered_wing_spar_static_vs_free_free_modal(tmp_path: Path) -> None:
    """T4-3: Cantilevered wing spar passes static + free-free modal; empty static BCs fail."""
    from meshtrix.runner import PipelineRunner

    from meshtrix.diagnostics.failure import ERR_BC_INVALID_SPEC

    base_spec_dict: dict[str, Any] = {
        "job_id": "JOB-T4-WING-SPAR-STATIC",
        "spec_version": "1.0",
        "units": "Metric_mm",
        "analysis_type": "STRUCTURAL_STATIC",
        "materials": {
            "catalog": {
                "Al_2024_T3": {
                    "name": "Al_2024_T3",
                    "density": 2.78e-9,
                    "elastic_modulus": 73100.0,
                    "poissons_ratio": 0.33,
                    "yield_strength": 345.0,
                }
            },
            "mappings": {
                "Wing_Spar_Web": {
                    "body_name": "Wing_Spar_Web",
                    "material_name": "Al_2024_T3",
                    "thickness": 2.8,
                },
                "Wing_Spar_Cap": {
                    "body_name": "Wing_Spar_Cap",
                    "material_name": "Al_2024_T3",
                    "thickness": None,
                },
            },
        },
        "mesh": {
            "global_size": 5.0,
            "element_order": "quadratic",
            "min_quality": 0.25,
            "quality_metric": "skewness",
        },
        "supports": [{"name": "Root_Clamp", "selection": "NS_SPAR_ROOT", "type": "fixed"}],
        "load_cases": [
            {
                "case_id": "LC_Aerodynamic_Lift",
                "forces": [
                    {
                        "name": "Tip_Shear",
                        "selection": "NS_SPAR_TIP",
                        "magnitude": 14000.0,
                        "direction": [0.0, 0.0, 1.0],
                    }
                ],
                "pressures": [
                    {
                        "name": "Skin_Aero_Pressure",
                        "selection": "NS_WING_SKIN",
                        "magnitude": 0.045,
                        "direction": [0.0, 0.0, 1.0],
                        "load_type": "pressure",
                    }
                ],
            }
        ],
    }

    runner = PipelineRunner()

    # (A) Static clamped spar
    static_spec = JobSpec.from_dict(base_spec_dict)
    static_driver = MockMechanicalDriver()
    static_driver.seed_from_spec(static_spec)
    res_static = runner.run(
        static_spec,
        static_driver,
        run_id="t4_3_static",
        checkpoint_dir=tmp_path / "cp_static",
        log_dir=tmp_path / "logs_static",
    )
    assert res_static.success is True
    assert len(static_driver.get_supports()) == 1
    assert len(static_driver.get_loads("LC_Aerodynamic_Lift")) == 2

    # (B) Free-free modal on identical spar geometry
    modal_dict = deepcopy(base_spec_dict)
    modal_dict["job_id"] = "JOB-T4-WING-SPAR-MODAL"
    modal_dict["analysis_type"] = AnalysisType.MODAL.value
    modal_dict["supports"] = []
    modal_dict["load_cases"] = []
    modal_spec = JobSpec.from_dict(modal_dict)
    modal_driver = MockMechanicalDriver()
    modal_driver.seed_from_spec(modal_spec)
    res_modal = runner.run(
        modal_spec,
        modal_driver,
        run_id="t4_3_modal",
        checkpoint_dir=tmp_path / "cp_modal",
        log_dir=tmp_path / "logs_modal",
    )
    assert res_modal.success is True
    assert res_modal.completed_steps == [
        "step_06_materials",
        "step_08_meshing",
        "step_09_boundary_conditions",
        "step_10_loads",
    ]

    # (C) Removing supports while keeping STRUCTURAL_STATIC must fail Step 9 pre_check
    unconstrained_dict = deepcopy(base_spec_dict)
    unconstrained_dict["supports"] = []
    unconstrained_spec = JobSpec.from_dict(unconstrained_dict)
    unconstrained_driver = MockMechanicalDriver()
    unconstrained_driver.seed_from_spec(unconstrained_spec)
    res_unconstrained = runner.run(
        unconstrained_spec,
        unconstrained_driver,
        run_id="t4_3_unconstrained",
        checkpoint_dir=tmp_path / "cp_unconstrained",
        log_dir=tmp_path / "logs_unconstrained",
    )
    assert res_unconstrained.success is False
    assert "step_10_loads" not in res_unconstrained.completed_steps
    assert any(f.error_code == ERR_BC_INVALID_SPEC for f in res_unconstrained.failures)


def test_scenario_multi_load_case_bracket_fault_injection_and_resume_recovery(
    tmp_path: Path,
) -> None:
    """T4-4: 3-LC bracket fails at Step 10 (sign + magnitude), clears, resumes at Step 10."""
    from meshtrix.core.checkpoint import CheckpointManager
    from meshtrix.runner import PipelineRunner

    from meshtrix.diagnostics.failure import ERR_LOAD_SIGN_MISMATCH, ERR_LOAD_TOTAL_MISMATCH

    spec = JobSpec.from_dict(_aerospace_bracket_multi_lc_dict())
    driver = _LoadFaultDriver()
    driver.seed_from_spec(spec)
    driver.sign_flip_cases.add("LC2_Lateral_Gust")
    driver.magnitude_scale_cases["LC2_Lateral_Gust"] = 1.5

    cp_dir = tmp_path / "cp"
    log_dir = tmp_path / "logs"
    run_id = "t4_4_multi_lc_recovery"
    runner = PipelineRunner()

    res_fail = runner.run(spec, driver, run_id=run_id, checkpoint_dir=cp_dir, log_dir=log_dir)
    assert res_fail.success is False
    assert res_fail.status == "failed"
    assert res_fail.completed_steps == [
        "step_06_materials",
        "step_08_meshing",
        "step_09_boundary_conditions",
    ]
    fail_codes = {f.error_code for f in res_fail.failures}
    assert ERR_LOAD_SIGN_MISMATCH in fail_codes
    assert ERR_LOAD_TOTAL_MISMATCH in fail_codes

    ckpt_mgr = CheckpointManager(cp_dir)
    assert ckpt_mgr.has_checkpoint(run_id, "step_09_boundary_conditions") is True
    assert ckpt_mgr.has_checkpoint(run_id, "step_10_loads") is False

    driver.clear_faults()
    res_pass = runner.run(
        spec,
        driver,
        run_id=run_id,
        resume_from="step_10_loads",
        checkpoint_dir=cp_dir,
        log_dir=log_dir,
    )

    assert res_pass.success is True
    assert res_pass.status == "passed"
    assert res_pass.skipped_steps == [
        "step_06_materials",
        "step_08_meshing",
        "step_09_boundary_conditions",
    ]
    assert res_pass.completed_steps == ["step_10_loads"]
    assert len(driver.get_loads("LC1_Limit_2_5G")) == 2
    assert len(driver.get_loads("LC2_Lateral_Gust")) == 1
    assert len(driver.get_loads("LC3_Crash_9G")) == 2

    log_data = json.loads(res_pass.log_path.read_text(encoding="utf-8"))
    assert log_data["status"] == "passed"
    assert log_data["resumed_from"] == "step_10_loads"


def test_scenario_cli_validate_run_inspect_audit_workflow(tmp_path: Path) -> None:
    """T4-5: Realistic CLI validate -> run --mock -> inspect-run audit trail verification."""
    from meshtrix.cli.main import app

    spec_dict = _aerospace_bracket_multi_lc_dict()
    spec_path = tmp_path / "aero_bracket.yaml"
    spec_path.write_text(yaml.safe_dump(spec_dict, sort_keys=False), encoding="utf-8")

    cp_dir = tmp_path / "cp"
    log_dir = tmp_path / "logs"
    run_id = "t4_5_cli_audit"
    cli = CliRunner()

    val_res = cli.invoke(app, ["validate", str(spec_path)])
    assert val_res.exit_code == 0, val_res.output

    run_res = cli.invoke(
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
    assert run_res.exit_code == 0, run_res.output

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
    assert spec_dict["job_id"] in insp_res.output
    assert "passed" in insp_res.output.lower()

    log_data = _find_run_log_json(log_dir, run_id)
    assert log_data["run_id"] == run_id
    assert log_data["job_id"] == spec_dict["job_id"]
    assert log_data["status"] == "passed"
    assert log_data["spec_version"] == "1.0"
    assert isinstance(log_data["spec_hash"], str) and len(log_data["spec_hash"]) >= 16
    assert isinstance(log_data["tool_versions"], dict) and len(log_data["tool_versions"]) > 0
    assert log_data["duration_seconds"] >= 0.0
    assert len(log_data["steps"]) == 4


def test_scenario_cli_faulty_mock_state_troubleshoot_and_resume(tmp_path: Path) -> None:
    """T4-6: SpaceClaim export defect in --mock-state fails Step 9, remedies, and resumes."""
    from meshtrix.cli.main import app
    from meshtrix.core.checkpoint import CheckpointManager

    from meshtrix.diagnostics.failure import ERR_BC_EMPTY_SELECTION

    spec_dict = _aerospace_bracket_multi_lc_dict()
    spec_dict["supports"][0]["selection"] = "NS_FRAME_MOUNT"
    spec = JobSpec.from_dict(spec_dict)
    spec_path = tmp_path / "frame_mount.yaml"
    spec_path.write_text(yaml.safe_dump(spec_dict, sort_keys=False), encoding="utf-8")

    # Simulate SpaceClaim export defect: empty NS_FRAME_MOUNT
    bad_driver = MockMechanicalDriver()
    bad_driver.seed_from_spec(spec)
    bad_driver.create_named_selection("NS_FRAME_MOUNT", [])
    bad_state_path = tmp_path / "spaceclaim_bad_state.json"
    bad_state_path.write_text(json.dumps(bad_driver.export_state()), encoding="utf-8")

    # Analyst repairs SpaceClaim named selection and exports remediated state
    repaired_driver = MockMechanicalDriver()
    repaired_driver.import_state(json.loads(bad_state_path.read_text(encoding="utf-8")))
    repaired_driver.create_named_selection("NS_FRAME_MOUNT", ["Frame_Mount_1", "Frame_Mount_2"])
    repaired_state_path = tmp_path / "spaceclaim_repaired_state.json"
    repaired_state_path.write_text(json.dumps(repaired_driver.export_state()), encoding="utf-8")

    cp_dir = tmp_path / "cp"
    log_dir = tmp_path / "logs"
    run_id = "t4_6_spaceclaim_recovery"
    cli = CliRunner()

    run1 = cli.invoke(
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
    assert run1.exit_code != 0
    assert ERR_BC_EMPTY_SELECTION in run1.output or "NS_FRAME_MOUNT" in run1.output

    ckpt_mgr = CheckpointManager(cp_dir)
    assert ckpt_mgr.has_checkpoint(run_id, "step_06_materials") is True
    assert ckpt_mgr.has_checkpoint(run_id, "step_08_meshing") is True
    assert ckpt_mgr.has_checkpoint(run_id, "step_09_boundary_conditions") is False

    run2 = cli.invoke(
        app,
        [
            "run",
            str(spec_path),
            "--mock",
            "--mock-state",
            str(repaired_state_path),
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
    assert run2.exit_code == 0, run2.output

    inspect_res = cli.invoke(
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
    assert inspect_res.exit_code == 0, inspect_res.output
    assert run_id in inspect_res.output
    assert "passed" in inspect_res.output.lower()

    log_data = _find_run_log_json(log_dir, run_id)
    assert log_data["status"] == "passed"
    assert log_data["resumed_from"] == "step_09_boundary_conditions"

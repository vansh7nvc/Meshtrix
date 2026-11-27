"""
Phase 2 E2E pipeline test — Steps 06→08→09→10 end-to-end with checkpoint resume.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from meshtrix.core.step import RunContext
from meshtrix.drivers.mock import MockMechanicalDriver
from meshtrix.runner.engine import PipelineRunner
from meshtrix.spec.job_spec import JobSpec
from meshtrix.steps.step_06_materials import Step06MaterialMapping
from meshtrix.steps.step_08_meshing import Step08Meshing
from meshtrix.steps.step_09_boundary_conditions import Step09BoundaryConditions
from meshtrix.steps.step_10_loads import Step10Loads

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


def _phase2_spec() -> JobSpec:
    """Full Phase 2 JobSpec: materials, mesh, BCs, loads, and accelerations."""
    return JobSpec.model_validate(
        {
            "job_id": "E2E-PHASE2-001",
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
            },
            "supports": [
                {"selection": "NS_BASE_FACES", "type": "fixed"},
                {"selection": "NS_SYM_PLANE", "type": "frictionless"},
            ],
            "load_cases": [
                {
                    "case_id": "LC1_Tension",
                    "forces": [
                        {
                            "selection": "NS_LUG_HOLE",
                            "magnitude": 10000.0,
                            "direction": [0.0, 1.0, 0.0],
                            "name": "LugTension",
                        }
                    ],
                    "accelerations": [
                        {"magnitude": 9810.0, "direction": [0.0, 0.0, -1.0], "name": "Gravity"}
                    ],
                },
                {
                    "case_id": "LC2_Pressure",
                    "pressures": [
                        {
                            "selection": "NS_SKIN_OUTER",
                            "magnitude": 0.1,
                            "direction": [0, 0, 1],
                            "name": "CabinPressure",
                        }
                    ],
                },
            ],
        }
    )


def _phase2_driver(spec: JobSpec) -> MockMechanicalDriver:
    driver = MockMechanicalDriver()
    driver.seed_from_spec(spec)
    return driver


# ---------------------------------------------------------------------------
# Class TestPhase2E2EPipeline
# ---------------------------------------------------------------------------


class TestPhase2E2EPipeline:
    def test_full_pipeline_runs_to_completion(self) -> None:
        spec = _phase2_spec()
        driver = _phase2_driver(spec)
        ctx = RunContext(spec=spec, driver=driver)

        with tempfile.TemporaryDirectory() as tmpdir:
            runner = PipelineRunner(base_dir=tmpdir)
            result = runner.run(ctx)

        assert result.is_successful(), (
            f"Pipeline failed: {[(sr.step_id, sr.status, sr.failures) for sr in result.step_results]}"
        )
        assert result.status == "passed"

        # All 4 steps must have run and passed
        status_map = {sr.step_id: sr.status for sr in result.step_results}
        assert status_map["step_06_materials"] == "passed"
        assert status_map["step_08_meshing"] == "passed"
        assert status_map["step_09_boundary_conditions"] == "passed"
        assert status_map["step_10_loads"] == "passed"

    def test_driver_state_after_pipeline(self) -> None:
        """Verify driver state reflects all pipeline operations."""
        spec = _phase2_spec()
        driver = _phase2_driver(spec)
        ctx = RunContext(spec=spec, driver=driver)

        with tempfile.TemporaryDirectory() as tmpdir:
            PipelineRunner(base_dir=tmpdir).run(ctx)

        # Materials
        assert driver.get_assigned_material("Bracket_Solid_Base") == "Structural_Steel"
        assert driver.get_assigned_material("Web_Plate_Upper") == "Aluminum_6061_T6"
        assert driver.get_shell_thickness("Web_Plate_Upper") == 2.5

        # Mesh
        assert driver.is_mesh_generated()

        # BCs
        supports = driver.get_supports()
        selections = {s.selection for s in supports}
        assert "NS_BASE_FACES" in selections
        assert "NS_SYM_PLANE" in selections

        # Loads
        lc1_loads = driver.get_loads(case_id="LC1_Tension")
        assert len(lc1_loads) == 2  # force + acceleration
        lc2_loads = driver.get_loads(case_id="LC2_Pressure")
        assert len(lc2_loads) == 1  # pressure

    def test_pipeline_checkpoints_written(self) -> None:
        from meshtrix.runner.checkpoint import CheckpointManager

        spec = _phase2_spec()
        driver = _phase2_driver(spec)
        ctx = RunContext(spec=spec, driver=driver)

        with tempfile.TemporaryDirectory() as tmpdir:
            cp_dir = Path(tmpdir) / ".meshtrix" / "checkpoints"
            runner = PipelineRunner(base_dir=tmpdir)
            result = runner.run(ctx)
            run_id = result.run_id
            mgr = CheckpointManager(cp_dir)
            cps = mgr.list_checkpoints(run_id)

        assert "step_06_materials" in cps
        assert "step_08_meshing" in cps
        assert "step_09_boundary_conditions" in cps
        assert "step_10_loads" in cps

    def test_pipeline_resume_from_step09(self) -> None:
        """Resume from step_09; steps 06 and 08 are skipped."""
        spec = _phase2_spec()
        driver = _phase2_driver(spec)

        with tempfile.TemporaryDirectory() as tmpdir:
            runner = PipelineRunner(base_dir=tmpdir)
            first = runner.run(spec, driver, run_id="e2e_resume_01")
            assert first.is_successful()

            fresh_driver = _phase2_driver(spec)
            result = runner.run(
                spec,
                fresh_driver,
                run_id="e2e_resume_01",
                resume_from="step_09_boundary_conditions",
            )

        status_map = {sr.step_id: sr.status for sr in result.step_results}
        assert status_map.get("step_06_materials") == "skipped"
        assert status_map.get("step_08_meshing") == "skipped"
        assert status_map.get("step_09_boundary_conditions") == "passed"
        assert status_map.get("step_10_loads") == "passed"

    def test_pipeline_fail_fast_on_missing_bc_selection(self) -> None:
        """Step 09 pre_check fails when NS_BASE_FACES is not in the driver."""
        spec = _phase2_spec()
        driver = MockMechanicalDriver()
        # Only add bodies from spec but NOT the named selections
        driver.add_body("Bracket_Solid_Base", body_type="solid")
        driver.add_body("Web_Plate_Upper", body_type="surface")
        # Add NS_LUG_HOLE and NS_SKIN_OUTER so step_10 pre-check can be reached
        # but deliberately omit NS_BASE_FACES, NS_SYM_PLANE
        driver.create_named_selection("NS_LUG_HOLE", ["Face_A"])
        driver.create_named_selection("NS_SKIN_OUTER", ["Face_B"])
        ctx = RunContext(spec=spec, driver=driver)

        with tempfile.TemporaryDirectory() as tmpdir:
            runner = PipelineRunner(base_dir=tmpdir)
            result = runner.run(ctx)

        assert result.status == "failed"
        step09 = next(
            (sr for sr in result.step_results if sr.step_id == "step_09_boundary_conditions"),
            None,
        )
        assert step09 is not None
        assert step09.status == "failed"
        assert any(f.error_code == "ERR_BC_MISSING_SELECTION" for f in step09.failures)


# ---------------------------------------------------------------------------
# Class TestPhase2StepByStepManual
# ---------------------------------------------------------------------------


class TestPhase2StepByStepManual:
    """Run each step individually against a shared driver to verify independence."""

    def test_manual_step_sequence(self) -> None:
        spec = _phase2_spec()
        driver = _phase2_driver(spec)
        ctx = RunContext(spec=spec, driver=driver)

        # Step 06
        s06 = Step06MaterialMapping()
        assert s06.pre_check(ctx).passed is True
        s06.execute(ctx)
        assert s06.post_check(ctx).passed is True

        # Step 08
        s08 = Step08Meshing()
        assert s08.pre_check(ctx).passed is True
        s08.execute(ctx)
        assert s08.post_check(ctx).passed is True

        # Step 09
        s09 = Step09BoundaryConditions()
        assert s09.pre_check(ctx).passed is True
        s09.execute(ctx)
        assert s09.post_check(ctx).passed is True

        # Step 10
        s10 = Step10Loads()
        assert s10.pre_check(ctx).passed is True
        s10.execute(ctx)
        assert s10.post_check(ctx).passed is True

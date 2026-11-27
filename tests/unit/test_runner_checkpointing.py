"""
Unit tests for PipelineRunner — checkpointing, resume, and fail-fast.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from meshtrix.core.checkpoint import CheckpointManager
from meshtrix.core.logger import RunLogger
from meshtrix.core.step import RunContext
from meshtrix.drivers.mock import MockMechanicalDriver
from meshtrix.runner.engine import PipelineRunner
from meshtrix.runner.registry import StepRegistry
from meshtrix.spec.job_spec import JobSpec


def _minimal_spec() -> JobSpec:
    return JobSpec.model_validate(
        {
            "job_id": "RUNNER-TEST-001",
            "units": "Metric_mm",
            "analysis_type": "STRUCTURAL_STATIC",
            "materials": {
                "catalog": {
                    "Steel": {
                        "name": "Steel",
                        "density": 7.85e-9,
                        "elastic_modulus": 200000.0,
                        "poissons_ratio": 0.3,
                        "yield_strength": 250.0,
                    }
                },
                "mappings": {
                    "Body_A": {
                        "body_name": "Body_A",
                        "material_name": "Steel",
                        "thickness": None,
                    }
                },
            },
            "mesh": {
                "global_size": 5.0,
                "element_order": "quadratic",
            },
            "supports": [{"selection": "NS_BASE", "type": "fixed"}],
            "load_cases": [
                {
                    "case_id": "LC1",
                    "forces": [
                        {"selection": "NS_LUG", "magnitude": 1000.0, "direction": [0, 1, 0]}
                    ],
                }
            ],
        }
    )


def _seeded_driver(spec: JobSpec) -> MockMechanicalDriver:
    driver = MockMechanicalDriver()
    driver.seed_from_spec(spec)
    return driver


class TestPipelineRunnerBasic:
    def test_full_pipeline_passes(self) -> None:
        spec = _minimal_spec()
        driver = _seeded_driver(spec)
        ctx = RunContext(spec=spec, driver=driver)
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = PipelineRunner(base_dir=tmpdir)
            result = runner.run(ctx)
        assert result.is_successful()
        assert result.status == "passed"
        assert all(sr.status == "passed" for sr in result.step_results)

    def test_all_steps_executed(self) -> None:
        spec = _minimal_spec()
        driver = _seeded_driver(spec)
        ctx = RunContext(spec=spec, driver=driver)
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = PipelineRunner(base_dir=tmpdir)
            result = runner.run(ctx)
        step_ids = [sr.step_id for sr in result.step_results]
        assert "step_06_materials" in step_ids
        assert "step_08_meshing" in step_ids
        assert "step_09_boundary_conditions" in step_ids
        assert "step_10_loads" in step_ids

    def test_fail_fast_on_blocking_failure(self) -> None:
        spec = _minimal_spec()
        driver = MockMechanicalDriver()
        driver.add_body("Body_A", body_type="solid")
        driver.create_named_selection("NS_BASE", ["Face_1"])
        driver.create_named_selection("NS_LUG", ["Edge_1"])
        driver.inject_mesh_generation_failure()

        ctx = RunContext(spec=spec, driver=driver)
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = PipelineRunner(base_dir=tmpdir)
            result = runner.run(ctx)
        assert result.status == "failed"
        step_ids = [sr.step_id for sr in result.step_results]
        assert "step_08_meshing" in step_ids
        assert "step_09_boundary_conditions" not in step_ids


class TestCheckpointManager:
    def test_save_and_load_checkpoint(self) -> None:
        spec = _minimal_spec()
        driver = _seeded_driver(spec)
        ctx = RunContext(spec=spec, driver=driver)
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = CheckpointManager(base_dir=tmpdir)
            path = mgr.save_checkpoint(
                run_id="run_abc",
                step_id="step_06_materials",
                step_index=0,
                spec=spec,
                context=ctx,
                driver_state={"bodies": 1},
            )
            assert path.exists()
            data = mgr.load_checkpoint("run_abc", "step_06_materials")
            assert data["status"] == "passed"
            assert data["driver_state"]["bodies"] == 1

    def test_has_checkpoint(self) -> None:
        spec = _minimal_spec()
        driver = _seeded_driver(spec)
        ctx = RunContext(spec=spec, driver=driver)
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = CheckpointManager(base_dir=tmpdir)
            assert mgr.has_checkpoint("run_xyz", "step_06_materials") is False
            mgr.save_checkpoint("run_xyz", "step_06_materials", 0, spec, ctx)
            assert mgr.has_checkpoint("run_xyz", "step_06_materials") is True

    def test_list_checkpoints(self) -> None:
        spec = _minimal_spec()
        driver = _seeded_driver(spec)
        ctx = RunContext(spec=spec, driver=driver)
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = CheckpointManager(base_dir=tmpdir)
            mgr.save_checkpoint("run_list", "step_06_materials", 0, spec, ctx)
            mgr.save_checkpoint("run_list", "step_08_meshing", 1, spec, ctx)
            ids = mgr.list_checkpoints("run_list")
            assert "step_06_materials" in ids
            assert "step_08_meshing" in ids

    def test_load_missing_checkpoint_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = CheckpointManager(base_dir=tmpdir)
            with pytest.raises(FileNotFoundError):
                mgr.load_checkpoint("run_empty", "nonexistent_step")


class TestRunLogger:
    def test_logger_records_and_saves(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = RunLogger(log_dir=Path(tmpdir), run_id="run_1", job_id="JOB-001")
            logger.record_step("step_06_materials", "passed", duration_seconds=0.1)
            logger.finalize("passed", duration_seconds=0.42)
            path = logger.save_log()
            assert path.exists()
            data = logger.to_dict()
            assert data["run_id"] == "run_1"
            assert data["status"] == "passed"
            assert len(data["steps"]) == 1


class TestStepRegistry:
    def test_registry_has_all_steps(self) -> None:
        registry = StepRegistry()
        ids = registry.step_ids()
        assert "step_06_materials" in ids
        assert "step_08_meshing" in ids
        assert "step_09_boundary_conditions" in ids
        assert "step_10_loads" in ids

    def test_registry_step_lookup(self) -> None:
        registry = StepRegistry()
        step = registry.get_step("step_09_boundary_conditions")
        assert step is not None
        assert step.step_id == "step_09_boundary_conditions"

    def test_registry_steps_from(self) -> None:
        registry = StepRegistry()
        tail = registry.steps_from("step_09_boundary_conditions")
        ids = [s.step_id for s in tail]
        assert ids[0] == "step_09_boundary_conditions"
        assert "step_10_loads" in ids

    def test_registry_unknown_step_returns_none(self) -> None:
        registry = StepRegistry()
        assert registry.get_step("step_99_nonexistent") is None


class TestPipelineRunnerResume:
    def test_resume_from_skips_earlier_steps(self) -> None:
        spec = _minimal_spec()
        driver = _seeded_driver(spec)
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = PipelineRunner(base_dir=tmpdir)
            first = runner.run(spec, driver, run_id="unit_resume_01")
            assert first.is_successful()

            fresh_driver = _seeded_driver(spec)
            result = runner.run(
                spec,
                fresh_driver,
                run_id="unit_resume_01",
                resume_from="step_09_boundary_conditions",
            )
        assert result.step_results[0].status == "skipped"  # step_06
        assert result.step_results[1].status == "skipped"  # step_08
        assert any(
            sr.step_id == "step_09_boundary_conditions" and sr.status == "passed"
            for sr in result.step_results
        )

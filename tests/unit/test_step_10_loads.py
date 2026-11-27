"""
Unit tests for Step10Loads — 4-phase contract.
"""

from __future__ import annotations

from typing import Any

from meshtrix.core.step import RunContext
from meshtrix.diagnostics.failure import (
    ERR_LOAD_DIRECTION_MISMATCH,
    ERR_LOAD_EMPTY_SELECTION,
    ERR_LOAD_INVALID_SPEC,
    ERR_LOAD_MISSING_LOAD,
    ERR_LOAD_MISSING_SELECTION,
    ERR_LOAD_SIGN_MISMATCH,
    ERR_LOAD_TOTAL_MISMATCH,
)
from meshtrix.drivers.mock import MockMechanicalDriver
from meshtrix.spec.job_spec import JobSpec
from meshtrix.steps.step_10_loads import Step10Loads

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_spec(load_cases: list[dict[str, Any]], supports: list[dict] | None = None) -> JobSpec:
    base: dict[str, Any] = {
        "job_id": "TEST-LOADS-001",
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
                "Body_A": {"body_name": "Body_A", "material_name": "Steel", "thickness": None}
            },
        },
        "load_cases": load_cases,
        "supports": supports or [],
    }
    return JobSpec.model_validate(base)


def _make_driver(*named_selections: str) -> MockMechanicalDriver:
    driver = MockMechanicalDriver()
    driver.add_body("Body_A", body_type="solid")
    for ns in named_selections:
        driver.create_named_selection(ns, [f"{ns}_entity_1"])
    return driver


# ---------------------------------------------------------------------------
# Class TestStep10PreCheck
# ---------------------------------------------------------------------------


class TestStep10PreCheck:
    def test_no_load_cases_passes(self) -> None:
        spec = _make_spec([])
        driver = _make_driver()
        ctx = RunContext(spec=spec, driver=driver)
        result = Step10Loads().pre_check(ctx)
        assert result.passed is True

    def test_valid_force_selection_passes(self) -> None:
        spec = _make_spec(
            [
                {
                    "case_id": "LC1",
                    "forces": [
                        {"selection": "NS_LUG", "magnitude": 1000.0, "direction": [0, 1, 0]}
                    ],
                }
            ]
        )
        driver = _make_driver("NS_LUG")
        ctx = RunContext(spec=spec, driver=driver)
        result = Step10Loads().pre_check(ctx)
        assert result.passed is True

    def test_missing_force_selection_blocks(self) -> None:
        spec = _make_spec(
            [
                {
                    "case_id": "LC1",
                    "forces": [
                        {"selection": "NS_GHOST", "magnitude": 1000.0, "direction": [0, 1, 0]}
                    ],
                }
            ]
        )
        driver = _make_driver()
        ctx = RunContext(spec=spec, driver=driver)
        result = Step10Loads().pre_check(ctx)
        assert result.passed is False
        assert any(f.error_code == ERR_LOAD_MISSING_SELECTION for f in result.failures)

    def test_empty_force_selection_blocks(self) -> None:
        spec = _make_spec(
            [
                {
                    "case_id": "LC1",
                    "forces": [
                        {"selection": "NS_EMPTY", "magnitude": 500.0, "direction": [1, 0, 0]}
                    ],
                }
            ]
        )
        driver = MockMechanicalDriver()
        driver.add_body("Body_A", body_type="solid")
        driver.create_named_selection("NS_EMPTY", ["Face_X"])
        driver.inject_empty_named_selection("NS_EMPTY")
        ctx = RunContext(spec=spec, driver=driver)
        result = Step10Loads().pre_check(ctx)
        assert result.passed is False
        assert any(f.error_code == ERR_LOAD_EMPTY_SELECTION for f in result.failures)

    def test_blank_selection_gives_invalid_spec(self) -> None:
        spec = _make_spec(
            [
                {
                    "case_id": "LC1",
                    "forces": [{"selection": "  ", "magnitude": 100.0, "direction": [0, 0, 1]}],
                }
            ]
        )
        driver = _make_driver()
        ctx = RunContext(spec=spec, driver=driver)
        result = Step10Loads().pre_check(ctx)
        assert result.passed is False
        assert any(f.error_code == ERR_LOAD_INVALID_SPEC for f in result.failures)

    def test_acceleration_with_optional_selection_passes(self) -> None:
        spec = _make_spec(
            [
                {
                    "case_id": "LC2",
                    "accelerations": [{"magnitude": 9810.0, "direction": [0, 0, -1]}],
                }
            ]
        )
        driver = _make_driver()
        ctx = RunContext(spec=spec, driver=driver)
        result = Step10Loads().pre_check(ctx)
        assert result.passed is True

    def test_acceleration_with_missing_selection_blocks(self) -> None:
        spec = _make_spec(
            [
                {
                    "case_id": "LC2",
                    "accelerations": [
                        {"magnitude": 9810.0, "direction": [0, 0, -1], "selection": "NS_MISSING"}
                    ],
                }
            ]
        )
        driver = _make_driver()
        ctx = RunContext(spec=spec, driver=driver)
        result = Step10Loads().pre_check(ctx)
        assert result.passed is False
        assert any(f.error_code == ERR_LOAD_MISSING_SELECTION for f in result.failures)


# ---------------------------------------------------------------------------
# Class TestStep10Execute
# ---------------------------------------------------------------------------


class TestStep10Execute:
    def test_force_applied(self) -> None:
        spec = _make_spec(
            [
                {
                    "case_id": "LC1",
                    "forces": [
                        {
                            "selection": "NS_LUG",
                            "magnitude": 10000.0,
                            "direction": [0.0, 1.0, 0.0],
                            "name": "LugForce",
                        }
                    ],
                }
            ]
        )
        driver = _make_driver("NS_LUG")
        ctx = RunContext(spec=spec, driver=driver)
        Step10Loads().execute(ctx)
        loads = driver.get_loads(case_id="LC1")
        assert len(loads) == 1
        assert loads[0].load_type == "force"
        assert loads[0].magnitude == 10000.0

    def test_pressure_applied(self) -> None:
        spec = _make_spec(
            [
                {
                    "case_id": "LC1",
                    "pressures": [
                        {"selection": "NS_SKIN", "magnitude": 0.25, "direction": [0, 0, 1]}
                    ],
                }
            ]
        )
        driver = _make_driver("NS_SKIN")
        ctx = RunContext(spec=spec, driver=driver)
        Step10Loads().execute(ctx)
        loads = driver.get_loads(case_id="LC1")
        assert len(loads) == 1
        assert loads[0].load_type == "pressure"

    def test_acceleration_applied_no_selection(self) -> None:
        spec = _make_spec(
            [
                {
                    "case_id": "LC2",
                    "accelerations": [
                        {"magnitude": 9810.0, "direction": [0.0, 0.0, -1.0], "name": "Gravity"}
                    ],
                }
            ]
        )
        driver = _make_driver()
        ctx = RunContext(spec=spec, driver=driver)
        Step10Loads().execute(ctx)
        loads = driver.get_loads(case_id="LC2")
        assert len(loads) == 1
        assert loads[0].selection is None

    def test_multiple_load_cases_applied(self) -> None:
        spec = _make_spec(
            [
                {
                    "case_id": "LC1",
                    "forces": [{"selection": "NS_A", "magnitude": 1000.0, "direction": [1, 0, 0]}],
                },
                {
                    "case_id": "LC2",
                    "forces": [{"selection": "NS_B", "magnitude": 2000.0, "direction": [0, 1, 0]}],
                },
            ]
        )
        driver = _make_driver("NS_A", "NS_B")
        ctx = RunContext(spec=spec, driver=driver)
        Step10Loads().execute(ctx)
        assert len(driver.get_loads(case_id="LC1")) == 1
        assert len(driver.get_loads(case_id="LC2")) == 1


# ---------------------------------------------------------------------------
# Class TestStep10PostCheck
# ---------------------------------------------------------------------------


class TestStep10PostCheck:
    def _run_full(
        self, spec: JobSpec, driver: MockMechanicalDriver
    ) -> tuple[Step10Loads, RunContext]:
        step = Step10Loads()
        ctx = RunContext(spec=spec, driver=driver)
        step.execute(ctx)
        return step, ctx

    def test_post_check_passes_after_clean_execute(self) -> None:
        spec = _make_spec(
            [
                {
                    "case_id": "LC1",
                    "forces": [
                        {
                            "selection": "NS_LUG",
                            "magnitude": 10000.0,
                            "direction": [0, 1, 0],
                            "name": "F1",
                        }
                    ],
                }
            ]
        )
        driver = _make_driver("NS_LUG")
        step, ctx = self._run_full(spec, driver)
        result = step.post_check(ctx)
        assert result.passed is True

    def test_missing_load_after_inject(self) -> None:
        spec = _make_spec(
            [
                {
                    "case_id": "LC1",
                    "forces": [
                        {
                            "selection": "NS_LUG",
                            "magnitude": 10000.0,
                            "direction": [0, 1, 0],
                            "name": "F1",
                        }
                    ],
                }
            ]
        )
        driver = _make_driver("NS_LUG")
        step, ctx = self._run_full(spec, driver)
        driver.inject_missing_load("F1", case_id="LC1")
        result = step.post_check(ctx)
        assert result.passed is False
        assert any(f.error_code == ERR_LOAD_MISSING_LOAD for f in result.failures)

    def test_magnitude_mismatch_detected(self) -> None:
        spec = _make_spec(
            [
                {
                    "case_id": "LC1",
                    "forces": [
                        {
                            "selection": "NS_LUG",
                            "magnitude": 10000.0,
                            "direction": [0, 1, 0],
                            "name": "F1",
                        }
                    ],
                }
            ]
        )
        driver = _make_driver("NS_LUG")
        step, ctx = self._run_full(spec, driver)
        driver.inject_load_magnitude_error("F1", 1.0, case_id="LC1")  # near-zero magnitude
        result = step.post_check(ctx)
        assert result.passed is False
        assert any(f.error_code == ERR_LOAD_TOTAL_MISMATCH for f in result.failures)

    def test_sign_mismatch_detected(self) -> None:
        spec = _make_spec(
            [
                {
                    "case_id": "LC1",
                    "forces": [
                        {
                            "selection": "NS_LUG",
                            "magnitude": 10000.0,
                            "direction": [0, 1, 0],
                            "name": "F1",
                        }
                    ],
                }
            ]
        )
        driver = _make_driver("NS_LUG")
        step, ctx = self._run_full(spec, driver)
        driver.inject_load_sign_error("F1", case_id="LC1")  # flips sign
        result = step.post_check(ctx)
        assert result.passed is False
        assert any(f.error_code == ERR_LOAD_SIGN_MISMATCH for f in result.failures)

    def test_direction_mismatch_detected(self) -> None:
        spec = _make_spec(
            [
                {
                    "case_id": "LC1",
                    "forces": [
                        {
                            "selection": "NS_LUG",
                            "magnitude": 5000.0,
                            "direction": [0, 1, 0],
                            "name": "F1",
                        }
                    ],
                }
            ]
        )
        driver = _make_driver("NS_LUG")
        step, ctx = self._run_full(spec, driver)
        # Inject a direction 90° off
        driver.inject_load_direction_error("F1", [1.0, 0.0, 0.0], case_id="LC1")
        result = step.post_check(ctx)
        assert result.passed is False
        assert any(f.error_code == ERR_LOAD_DIRECTION_MISMATCH for f in result.failures)

    def test_acceleration_post_check_passes(self) -> None:
        spec = _make_spec(
            [
                {
                    "case_id": "LC2",
                    "accelerations": [
                        {"magnitude": 9810.0, "direction": [0, 0, -1], "name": "Grav"}
                    ],
                }
            ]
        )
        driver = _make_driver()
        step, ctx = self._run_full(spec, driver)
        result = step.post_check(ctx)
        assert result.passed is True


# ---------------------------------------------------------------------------
# Class TestStep10FullPipeline
# ---------------------------------------------------------------------------


class TestStep10FullPipeline:
    def test_full_4phase_forces_pressures_accelerations(self) -> None:
        spec = _make_spec(
            [
                {
                    "case_id": "LC1",
                    "forces": [
                        {
                            "selection": "NS_LUG",
                            "magnitude": 10000.0,
                            "direction": [0, 1, 0],
                            "name": "LugForce",
                        }
                    ],
                    "pressures": [
                        {
                            "selection": "NS_SKIN",
                            "magnitude": 0.25,
                            "direction": [0, 0, 1],
                            "name": "CabinPressure",
                        }
                    ],
                    "accelerations": [
                        {"magnitude": 9810.0, "direction": [0, 0, -1], "name": "Gravity"}
                    ],
                }
            ]
        )
        driver = _make_driver("NS_LUG", "NS_SKIN")
        step = Step10Loads()
        ctx = RunContext(spec=spec, driver=driver)

        pre = step.pre_check(ctx)
        assert pre.passed is True

        step.execute(ctx)

        post = step.post_check(ctx)
        assert post.passed is True

        all_loads = driver.get_loads(case_id="LC1")
        assert len(all_loads) == 3

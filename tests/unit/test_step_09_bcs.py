"""
Unit tests for Step09BoundaryConditions — 4-phase contract.
"""

from __future__ import annotations

from typing import Any

from meshtrix.core.step import RunContext
from meshtrix.diagnostics.failure import (
    ERR_BC_DOF_MISMATCH,
    ERR_BC_EMPTY_SELECTION,
    ERR_BC_INVALID_SPEC,
    ERR_BC_MISSING_SELECTION,
    ERR_BC_MISSING_SUPPORT,
    ERR_BC_SCOPING_MISMATCH,
)
from meshtrix.drivers.mock import MockMechanicalDriver
from meshtrix.spec.job_spec import JobSpec
from meshtrix.steps.step_09_boundary_conditions import Step09BoundaryConditions

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_spec(supports: list[dict[str, Any]], **extra: Any) -> JobSpec:
    """Build a minimal JobSpec with the given supports list."""
    base: dict[str, Any] = {
        "job_id": "TEST-BC-001",
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
        "supports": supports,
        **extra,
    }
    return JobSpec.model_validate(base)


def _make_driver(*named_selections: str) -> MockMechanicalDriver:
    driver = MockMechanicalDriver()
    driver.add_body("Body_A", body_type="solid")
    for ns in named_selections:
        driver.create_named_selection(ns, [f"{ns}_Face_1", f"{ns}_Face_2"])
    return driver


# ---------------------------------------------------------------------------
# Class TestStep09PreCheck
# ---------------------------------------------------------------------------


class TestStep09PreCheck:
    def test_no_supports_passes_for_modal_and_blocks_for_static(self) -> None:
        modal_spec = _make_spec([], analysis_type="MODAL")
        driver = _make_driver()
        ctx_modal = RunContext(spec=modal_spec, driver=driver)
        assert Step09BoundaryConditions().pre_check(ctx_modal).passed is True

        static_spec = _make_spec([])
        ctx_static = RunContext(spec=static_spec, driver=driver)
        res_static = Step09BoundaryConditions().pre_check(ctx_static)
        assert res_static.passed is False
        assert any(f.error_code == ERR_BC_INVALID_SPEC for f in res_static.failures)

    def test_valid_selections_pass(self) -> None:
        spec = _make_spec([{"selection": "NS_BASE", "type": "fixed"}])
        driver = _make_driver("NS_BASE")
        ctx = RunContext(spec=spec, driver=driver)
        result = Step09BoundaryConditions().pre_check(ctx)
        assert result.passed is True

    def test_missing_named_selection_blocks(self) -> None:
        spec = _make_spec([{"selection": "NS_GHOST", "type": "fixed"}])
        driver = _make_driver()  # NS_GHOST not created
        ctx = RunContext(spec=spec, driver=driver)
        result = Step09BoundaryConditions().pre_check(ctx)
        assert result.passed is False
        assert any(f.error_code == ERR_BC_MISSING_SELECTION for f in result.failures)

    def test_empty_named_selection_blocks(self) -> None:
        spec = _make_spec([{"selection": "NS_EMPTY", "type": "pinned"}])
        driver = MockMechanicalDriver()
        driver.add_body("Body_A", body_type="solid")
        # Create selection, then inject empty fault
        driver.create_named_selection("NS_EMPTY", ["Face_1"])
        driver.inject_empty_named_selection("NS_EMPTY")
        ctx = RunContext(spec=spec, driver=driver)
        result = Step09BoundaryConditions().pre_check(ctx)
        assert result.passed is False
        assert any(f.error_code == ERR_BC_EMPTY_SELECTION for f in result.failures)

    def test_blank_selection_string_gives_invalid_spec(self) -> None:
        spec = _make_spec([{"selection": "   ", "type": "fixed"}])
        driver = _make_driver()
        ctx = RunContext(spec=spec, driver=driver)
        result = Step09BoundaryConditions().pre_check(ctx)
        assert result.passed is False
        assert any(f.error_code == ERR_BC_INVALID_SPEC for f in result.failures)

    def test_multiple_supports_one_missing(self) -> None:
        spec = _make_spec(
            [
                {"selection": "NS_BASE", "type": "fixed"},
                {"selection": "NS_MISSING", "type": "pinned"},
            ]
        )
        driver = _make_driver("NS_BASE")
        ctx = RunContext(spec=spec, driver=driver)
        result = Step09BoundaryConditions().pre_check(ctx)
        assert result.passed is False
        assert len(result.failures) == 1
        assert result.failures[0].error_code == ERR_BC_MISSING_SELECTION


# ---------------------------------------------------------------------------
# Class TestStep09Execute
# ---------------------------------------------------------------------------


class TestStep09Execute:
    def test_fixed_support_applied(self) -> None:
        spec = _make_spec([{"selection": "NS_BASE", "type": "fixed"}])
        driver = _make_driver("NS_BASE")
        ctx = RunContext(spec=spec, driver=driver)
        Step09BoundaryConditions().execute(ctx)
        supports = driver.get_supports()
        assert len(supports) == 1
        assert supports[0].selection == "NS_BASE"
        assert "UX" in supports[0].dofs
        assert "RZ" in supports[0].dofs

    def test_pinned_support_dofs(self) -> None:
        spec = _make_spec([{"selection": "NS_PIN", "type": "pinned"}])
        driver = _make_driver("NS_PIN")
        ctx = RunContext(spec=spec, driver=driver)
        Step09BoundaryConditions().execute(ctx)
        supports = driver.get_supports()
        assert frozenset(supports[0].dofs) == frozenset(["UX", "UY", "UZ"])

    def test_frictionless_support_dofs(self) -> None:
        spec = _make_spec([{"selection": "NS_SYM", "type": "frictionless"}])
        driver = _make_driver("NS_SYM")
        ctx = RunContext(spec=spec, driver=driver)
        Step09BoundaryConditions().execute(ctx)
        supports = driver.get_supports()
        assert supports[0].dofs == ["NORMAL"]

    def test_multiple_supports_all_applied(self) -> None:
        spec = _make_spec(
            [
                {"selection": "NS_A", "type": "fixed"},
                {"selection": "NS_B", "type": "pinned"},
            ]
        )
        driver = _make_driver("NS_A", "NS_B")
        ctx = RunContext(spec=spec, driver=driver)
        Step09BoundaryConditions().execute(ctx)
        assert len(driver.get_supports()) == 2

    def test_no_supports_execute_is_noop(self) -> None:
        spec = _make_spec([])
        driver = _make_driver()
        ctx = RunContext(spec=spec, driver=driver)
        Step09BoundaryConditions().execute(ctx)
        assert driver.get_supports() == []


# ---------------------------------------------------------------------------
# Class TestStep09PostCheck
# ---------------------------------------------------------------------------


class TestStep09PostCheck:
    def _run_full(
        self, spec: JobSpec, driver: MockMechanicalDriver
    ) -> tuple[Step09BoundaryConditions, RunContext]:
        step = Step09BoundaryConditions()
        ctx = RunContext(spec=spec, driver=driver)
        step.execute(ctx)
        return step, ctx

    def test_post_check_passes_after_clean_execute(self) -> None:
        spec = _make_spec([{"selection": "NS_BASE", "type": "fixed"}])
        driver = _make_driver("NS_BASE")
        step, ctx = self._run_full(spec, driver)
        result = step.post_check(ctx)
        assert result.passed is True

    def test_missing_support_after_fault_injection(self) -> None:
        spec = _make_spec([{"selection": "NS_BASE", "type": "fixed"}])
        driver = _make_driver("NS_BASE")
        step, ctx = self._run_full(spec, driver)
        # Inject fault: remove the support
        supports = driver.get_supports()
        driver.inject_missing_support(supports[0].name)
        result = step.post_check(ctx)
        assert result.passed is False
        assert any(f.error_code == ERR_BC_MISSING_SUPPORT for f in result.failures)

    def test_scoping_mismatch_detected(self) -> None:
        spec = _make_spec([{"selection": "NS_BASE", "type": "fixed"}])
        driver = _make_driver("NS_BASE")
        step, ctx = self._run_full(spec, driver)
        # Inject scoping fault
        supports = driver.get_supports()
        driver.inject_support_scoping_error(supports[0].name, "NS_WRONG")
        result = step.post_check(ctx)
        assert result.passed is False
        assert any(f.error_code == ERR_BC_SCOPING_MISMATCH for f in result.failures)

    def test_dof_mismatch_detected(self) -> None:
        spec = _make_spec([{"selection": "NS_PIN", "type": "pinned"}])
        driver = _make_driver("NS_PIN")
        step, ctx = self._run_full(spec, driver)
        # Inject DOF fault — only 1 DOF instead of 3
        supports = driver.get_supports()
        driver.inject_support_dof_error(supports[0].name, ["UX"])
        result = step.post_check(ctx)
        assert result.passed is False
        assert any(f.error_code == ERR_BC_DOF_MISMATCH for f in result.failures)

    def test_no_supports_post_check_passes(self) -> None:
        spec = _make_spec([])
        driver = _make_driver()
        step = Step09BoundaryConditions()
        ctx = RunContext(spec=spec, driver=driver)
        result = step.post_check(ctx)
        assert result.passed is True


# ---------------------------------------------------------------------------
# Class TestStep09Troubleshoot
# ---------------------------------------------------------------------------


class TestStep09Troubleshoot:
    def test_troubleshoot_enriches_missing_selection(self) -> None:
        from meshtrix.diagnostics.failure import FailureObject, Severity

        f = FailureObject(
            error_code=ERR_BC_MISSING_SELECTION,
            severity=Severity.BLOCKING,
            step_id="step_09_boundary_conditions",
            component_or_entity="support[0]",
            engineering_message="missing",
            likely_causes=["original cause"],
            suggested_fixes=[],
        )
        spec = _make_spec([])
        driver = _make_driver()
        ctx = RunContext(spec=spec, driver=driver)
        from meshtrix.diagnostics.failure import StepCheckResult

        check_result = StepCheckResult(step_id="step_09_boundary_conditions", failures=[f])
        enriched = Step09BoundaryConditions().troubleshoot(ctx, check_result)
        assert len(enriched[0].likely_causes) == 2  # original + appended

    def test_troubleshoot_enriches_dof_mismatch(self) -> None:
        from meshtrix.diagnostics.failure import FailureObject, Severity, StepCheckResult

        f = FailureObject(
            error_code=ERR_BC_DOF_MISMATCH,
            severity=Severity.BLOCKING,
            step_id="step_09_boundary_conditions",
            component_or_entity="support[0]",
            engineering_message="dof mismatch",
            likely_causes=[],
            suggested_fixes=["re-apply"],
        )
        spec = _make_spec([])
        driver = _make_driver()
        ctx = RunContext(spec=spec, driver=driver)
        check_result = StepCheckResult(step_id="step_09_boundary_conditions", failures=[f])
        enriched = Step09BoundaryConditions().troubleshoot(ctx, check_result)
        assert len(enriched[0].suggested_fixes) == 2

    def test_troubleshoot_identity_for_unrecognized_code(self) -> None:
        from meshtrix.diagnostics.failure import FailureObject, Severity, StepCheckResult

        f = FailureObject(
            error_code="ERR_UNRECOGNIZED",
            severity=Severity.WARNING,
            step_id="step_09_boundary_conditions",
            component_or_entity="x",
            engineering_message="x",
        )
        spec = _make_spec([])
        driver = _make_driver()
        ctx = RunContext(spec=spec, driver=driver)
        check_result = StepCheckResult(step_id="step_09_boundary_conditions", failures=[f])
        enriched = Step09BoundaryConditions().troubleshoot(ctx, check_result)
        assert len(enriched) == 1


# ---------------------------------------------------------------------------
# Class TestStep09FullPipeline
# ---------------------------------------------------------------------------


class TestStep09FullPipeline:
    def test_full_4phase_contract_passes(self) -> None:
        spec = _make_spec(
            [
                {"selection": "NS_BASE", "type": "fixed"},
                {"selection": "NS_SYM", "type": "frictionless"},
            ]
        )
        driver = _make_driver("NS_BASE", "NS_SYM")
        step = Step09BoundaryConditions()
        ctx = RunContext(spec=spec, driver=driver)

        pre = step.pre_check(ctx)
        assert pre.passed is True

        step.execute(ctx)

        post = step.post_check(ctx)
        assert post.passed is True

        assert len(driver.get_supports()) == 2

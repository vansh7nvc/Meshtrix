"""
Meshtrix Tier 3: Cross-Feature Combinations & Integration Workflows.

Authoritative Reference: ORIGINAL_REQUEST.md §R2, §R3 & Acceptance Criteria
Focus:
- Full Step 6 lifecycle integration (pre_check -> execute -> post_check)
- Interaction between JobSpec, MockMechanicalDriver, and StepCheckResult
- Fault injection and structured troubleshooting generation
- Concurrent multi-failure diagnostic aggregation
- Resilient recovery flows
"""

from copy import deepcopy
from typing import Any

import pytest

from meshtrix.core.step import RunContext
from meshtrix.diagnostics.failure import Severity
from meshtrix.drivers.mock import MockMechanicalDriver
from meshtrix.spec.job_spec import JobSpec
from meshtrix.steps.step_06_materials import Step06MaterialMapping
from tests.conftest import assert_check_failed, assert_check_passed

# ===========================================================================
# 1. Full Lifecycle Step 6 Execution Flow
# ===========================================================================


class TestStep06LifecycleIntegration:
    """Verifies end-to-end multi-body execution through the 4-phase contract."""

    def test_full_lifecycle_clean_model(self, sample_run_context: RunContext) -> None:
        """Sequential lifecycle pre_check -> execute -> post_check must succeed cleanly."""
        step = Step06MaterialMapping()

        # Phase 1: Pre-Check
        pre_res = step.pre_check(sample_run_context)
        assert_check_passed(pre_res)

        # Phase 2: Execute
        step.execute(sample_run_context)

        # Direct driver verification
        driver = sample_run_context.driver
        assert driver.get_assigned_material("Bracket_Solid_Base") == "Structural_Steel"
        assert driver.get_assigned_material("Web_Plate_Upper") == "Aluminum_6061_T6"
        assert driver.get_assigned_material("Flange_Skin_Outer") == "Titanium_Ti6Al4V"

        # Surface bodies have thicknesses assigned
        assert driver.get_shell_thickness("Web_Plate_Upper") == pytest.approx(2.5)
        assert driver.get_shell_thickness("Flange_Skin_Outer") == pytest.approx(1.25)
        # Solid body does not have shell thickness
        assert driver.get_shell_thickness("Bracket_Solid_Base") is None

        # Phase 3: Post-Check
        post_res = step.post_check(sample_run_context)
        assert_check_passed(post_res)


# ===========================================================================
# 2. Post-Check Fault Injection & Troubleshooting
# ===========================================================================


class TestPostCheckFaultInjectionAndDiagnostics:
    """Verifies that driver anomalies are detected by post-check and accurately diagnosed."""

    def test_injected_material_mismatch_detected(self, sample_run_context: RunContext) -> None:
        """Injected wrong material on a body must fail post-check and produce FailureObject."""
        step = Step06MaterialMapping()
        step.pre_check(sample_run_context)
        step.execute(sample_run_context)

        # Inject material mismatch on Web_Plate_Upper
        driver = sample_run_context.driver
        driver.inject_material_error("Web_Plate_Upper", "Structural_Steel")

        post_res = step.post_check(sample_run_context)
        assert_check_failed(post_res)

        failures = step.troubleshoot(sample_run_context, post_res)
        mat_failures = [
            f
            for f in failures
            if "material" in f.engineering_message.lower() or "MATERIAL" in f.error_code
        ]
        assert len(mat_failures) > 0
        failure = mat_failures[0]
        assert failure.component_or_entity == "Web_Plate_Upper"
        assert failure.measured_value == "Structural_Steel"
        assert failure.expected_value == "Aluminum_6061_T6"
        assert failure.severity == Severity.BLOCKING
        assert len(failure.likely_causes) > 0
        assert len(failure.suggested_fixes) > 0

    def test_injected_thickness_error_detected(self, sample_run_context: RunContext) -> None:
        """Injected shell thickness corruption must fail post-check and produce exact diagnostics."""
        step = Step06MaterialMapping()
        step.pre_check(sample_run_context)
        step.execute(sample_run_context)

        # Inject thickness corruption on Flange_Skin_Outer (spec is 1.25mm, inject 5.0mm)
        driver = sample_run_context.driver
        driver.inject_thickness_error("Flange_Skin_Outer", 5.0)

        post_res = step.post_check(sample_run_context)
        assert_check_failed(post_res, expected_code="ERR_MAT_THICKNESS_MISMATCH")

        failures = step.troubleshoot(sample_run_context, post_res)
        thk_failures = [f for f in failures if f.error_code == "ERR_MAT_THICKNESS_MISMATCH"]
        assert len(thk_failures) > 0
        failure = thk_failures[0]
        assert failure.component_or_entity == "Flange_Skin_Outer"
        assert failure.measured_value == pytest.approx(5.0)
        assert failure.expected_value == pytest.approx(1.25)


# ===========================================================================
# 3. Concurrent Multi-Failure Aggregation
# ===========================================================================


class TestMultiFailureDiagnosticAggregation:
    """Verifies that multiple concurrent discrepancies across bodies are captured simultaneously."""

    def test_concurrent_pre_check_failures(
        self, valid_job_spec_dict: dict[str, Any], mock_driver: MockMechanicalDriver
    ) -> None:
        """Pre-check captures both unmapped bodies and surface bodies missing thickness."""
        spec_dict = deepcopy(valid_job_spec_dict)
        # Web_Plate_Upper has no thickness
        spec_dict["materials"]["mappings"]["Web_Plate_Upper"]["thickness"] = None
        spec = JobSpec.model_validate(spec_dict)

        # Add two unmapped bodies to driver
        mock_driver.add_body("Unmapped_Stiffener_A", body_type="surface")
        mock_driver.add_body("Unmapped_Stiffener_B", body_type="solid")

        step = Step06MaterialMapping()
        context = RunContext(spec=spec, driver=mock_driver)

        res = step.pre_check(context)
        assert_check_failed(res)

        # Must aggregate multiple failures
        failures = step.troubleshoot(context, res)
        failed_entities = {f.component_or_entity for f in failures}

        assert "Unmapped_Stiffener_A" in failed_entities
        assert "Unmapped_Stiffener_B" in failed_entities
        assert "Web_Plate_Upper" in failed_entities

    def test_concurrent_post_check_failures(self, sample_run_context: RunContext) -> None:
        """Post-check captures multiple distinct body discrepancies in a single inspection pass."""
        step = Step06MaterialMapping()
        step.pre_check(sample_run_context)
        step.execute(sample_run_context)

        # Inject material error on one body and thickness error on another
        driver = sample_run_context.driver
        driver.inject_material_error("Bracket_Solid_Base", "Titanium_Ti6Al4V")
        driver.inject_thickness_error("Web_Plate_Upper", 0.5)

        post_res = step.post_check(sample_run_context)
        assert_check_failed(post_res)

        failures = step.troubleshoot(sample_run_context, post_res)
        failed_entities = {f.component_or_entity for f in failures}
        assert "Bracket_Solid_Base" in failed_entities
        assert "Web_Plate_Upper" in failed_entities

"""
Unit and Integration Tests for Step 8 Meshing Automation and Quality Verification.

Authoritative Reference: ORIGINAL_REQUEST.md §R1, §R2, §R3 & PROJECT.md
"""

from typing import Any

import pytest

from meshtrix.core.step import RunContext
from meshtrix.diagnostics.failure import (
    ERR_DRIVER_COMMUNICATION,
    ERR_MAT_INVALID_THICKNESS,
    ERR_MAT_UNASSIGNED_BODY,
    ERR_MESH_ASPECT_RATIO_EXCEEDED,
    ERR_MESH_ELEMENT_COUNT,
    ERR_MESH_GENERATION_FAILED,
    ERR_MESH_MISSING_SELECTION,
    ERR_MESH_NO_BODIES,
    ERR_MESH_SKEWNESS_EXCEEDED,
    ERR_MESH_SPEC_MISSING,
    ERR_MESH_WARPAGE_EXCEEDED,
    Severity,
)
from meshtrix.drivers.base import MeshStatistics
from meshtrix.drivers.mock import MockMechanicalDriver
from meshtrix.spec.job_spec import JobSpec
from meshtrix.steps.step_06_materials import Step06MaterialMapping
from meshtrix.steps.step_08_meshing import Step08Meshing, Step08MeshingAutomation
from tests.conftest import assert_check_failed, assert_check_passed

# ===========================================================================
# 1. Mock Driver Meshing API Tests
# ===========================================================================


class TestMockDriverMeshingCoverage:
    """Verifies that MockMechanicalDriver provides full meshing and quality query capabilities."""

    def test_global_sizing_and_element_order(self) -> None:
        """Driver records global mesh size and element order."""
        driver = MockMechanicalDriver()
        driver.set_global_mesh_size(3.5)
        driver.set_element_order("linear")
        assert driver._global_mesh_size == pytest.approx(3.5)
        assert driver._element_order == "linear"

    def test_local_refinement_registration(self) -> None:
        """Driver registers local refinements on named selections."""
        driver = MockMechanicalDriver()
        driver.add_local_refinement("HoleRefinement", "NS_BOLT_HOLES", 1.0)
        refinements = driver.get_local_refinements()
        assert len(refinements) == 1
        assert refinements[0]["name"] == "HoleRefinement"
        assert refinements[0]["selection"] == "NS_BOLT_HOLES"
        assert refinements[0]["element_size"] == pytest.approx(1.0)

    def test_mesh_generation_nominal_quadratic(self) -> None:
        """Mesh generation creates elements and nodes according to bodies and quadratic order."""
        driver = MockMechanicalDriver()
        driver.add_body("Body1", body_type="solid")
        driver.add_body("Body2", body_type="surface", thickness=2.0)
        assert driver.is_mesh_generated() is False

        stats = driver.generate_mesh(global_size=5.0, element_order="quadratic")
        assert driver.is_mesh_generated() is True
        assert isinstance(stats, MeshStatistics)
        assert stats.element_count > 0
        assert stats.node_count == stats.element_count * 8
        assert stats.max_skewness == pytest.approx(0.28)
        assert stats.max_aspect_ratio == pytest.approx(1.85)
        assert stats.max_warpage == pytest.approx(3.5)
        assert stats.min_quality > 0.5

    def test_mesh_generation_linear_order(self) -> None:
        """Linear element order generates 4 nodes per element."""
        driver = MockMechanicalDriver()
        driver.add_body("Body1", body_type="solid")
        stats = driver.generate_mesh(global_size=4.0, element_order="linear")
        assert stats.node_count == stats.element_count * 4

    def test_mesh_generation_with_local_refinement_increases_element_count(self) -> None:
        """Adding local refinement increases total generated element count."""
        driver1 = MockMechanicalDriver()
        driver1.add_body("Body1", body_type="solid")
        stats1 = driver1.generate_mesh(global_size=5.0)

        driver2 = MockMechanicalDriver()
        driver2.add_body("Body1", body_type="solid")
        driver2.add_local_refinement("LocalRef", "NS_EDGE", 1.0)
        stats2 = driver2.generate_mesh(global_size=5.0)

        assert stats2.element_count > stats1.element_count

    def test_quality_query_methods(self) -> None:
        """Quality query methods return correct scalar metrics."""
        driver = MockMechanicalDriver()
        driver.add_body("Body1", body_type="solid")
        driver.generate_mesh(global_size=5.0)

        assert driver.get_element_count() == driver.get_mesh_statistics().element_count
        assert driver.get_max_skewness() == pytest.approx(0.28)
        assert driver.get_max_aspect_ratio() == pytest.approx(1.85)
        assert driver.get_max_warpage() == pytest.approx(3.5)

    def test_failing_elements_query(self) -> None:
        """Driver returns failing element IDs when metrics exceed threshold."""
        driver = MockMechanicalDriver()
        driver.add_body("Body1", body_type="solid")
        driver.generate_mesh(global_size=5.0)

        # In nominal state (skewness 0.28), threshold 0.85 returns empty list
        assert driver.get_failing_elements("skewness", threshold=0.85) == []

        # Inject high skewness with explicit element IDs
        driver.inject_mesh_skewness(0.92, [1042, 1043])
        assert driver.get_failing_elements("skewness", threshold=0.85) == [1042, 1043]

    def test_fault_injection_and_clear_faults(self) -> None:
        """Fault injection modifies metrics and clear_faults restores nominal values."""
        driver = MockMechanicalDriver()
        driver.add_body("Body1", body_type="solid")
        driver.generate_mesh(global_size=5.0)

        # Inject faults
        driver.inject_mesh_skewness(0.95)
        driver.inject_mesh_aspect_ratio(15.0)
        driver.inject_mesh_warpage(60.0)
        driver.inject_mesh_element_count(50000)

        assert driver.get_max_skewness() == pytest.approx(0.95)
        assert driver.get_max_aspect_ratio() == pytest.approx(15.0)
        assert driver.get_max_warpage() == pytest.approx(60.0)
        assert driver.get_element_count() == 50000

        # Clear faults
        driver.clear_faults()
        assert driver.get_max_skewness() == pytest.approx(0.28)
        assert driver.get_max_aspect_ratio() == pytest.approx(1.85)
        assert driver.get_max_warpage() == pytest.approx(3.5)
        assert driver.get_element_count() < 50000

    def test_inject_mesh_generation_failure(self) -> None:
        """Injecting mesh generation failure causes is_mesh_generated to be False."""
        driver = MockMechanicalDriver()
        driver.add_body("Body1", body_type="solid")
        driver.inject_mesh_generation_failure(True)
        stats = driver.generate_mesh(global_size=5.0)
        assert driver.is_mesh_generated() is False
        assert stats.element_count == 0


# ===========================================================================
# 2. Step 8 Meshing Automation Lifecycle Tests
# ===========================================================================


class TestStep08MeshingLifecycleCoverage:
    """Verifies nominal 4-phase execution of Step 8."""

    @pytest.fixture
    def meshing_ready_context(
        self, valid_job_spec: JobSpec, mock_driver: MockMechanicalDriver
    ) -> RunContext:
        """RunContext where Step 6 has already been executed (bodies have materials & thicknesses)."""
        step6 = Step06MaterialMapping()
        context = RunContext(spec=valid_job_spec, driver=mock_driver)
        step6.pre_check(context)
        step6.execute(context)
        return context

    def test_step_attributes_and_alias(self) -> None:
        """Step 8 defines required step_id, description, and aliases."""
        step = Step08Meshing()
        assert step.step_id == "step_08_meshing"
        assert len(step.description) > 0
        assert Step08MeshingAutomation is Step08Meshing

    def test_pre_check_nominal(self, meshing_ready_context: RunContext) -> None:
        """Pre-check passes cleanly on a properly prepared model."""
        step = Step08Meshing()
        res = step.pre_check(meshing_ready_context)
        assert_check_passed(res)

    def test_execute_nominal(self, meshing_ready_context: RunContext) -> None:
        """Execute applies mesh sizing and generates mesh in driver."""
        step = Step08Meshing()
        step.execute(meshing_ready_context)

        driver: MockMechanicalDriver = meshing_ready_context.driver
        assert driver.is_mesh_generated() is True
        assert driver.get_element_count() > 0
        assert "mesh_statistics" in meshing_ready_context.step_data

    def test_post_check_nominal(self, meshing_ready_context: RunContext) -> None:
        """Post-check validates that all mesh quality metrics are within spec thresholds."""
        step = Step08Meshing()
        step.execute(meshing_ready_context)
        res = step.post_check(meshing_ready_context)
        assert_check_passed(res)

    def test_troubleshoot_empty_on_success(self, meshing_ready_context: RunContext) -> None:
        """Troubleshoot produces zero failure objects when post_check passes."""
        step = Step08Meshing()
        step.execute(meshing_ready_context)
        res = step.post_check(meshing_ready_context)
        failures = step.troubleshoot(meshing_ready_context, res)
        assert len(failures) == 0


# ===========================================================================
# 3. Pre-Check Failure Scenarios
# ===========================================================================


class TestStep08PreCheckFailures:
    """Verifies that Step 8 pre-check strictly guards all prerequisites."""

    def test_pre_check_driver_disconnected(self, valid_job_spec: JobSpec) -> None:
        """Pre-check flags ERR_DRIVER_COMMUNICATION when driver is disconnected."""
        driver = MockMechanicalDriver()
        driver.disconnect()
        context = RunContext(spec=valid_job_spec, driver=driver)
        step = Step08Meshing()
        res = step.pre_check(context)
        assert_check_failed(res, expected_code=ERR_DRIVER_COMMUNICATION)
        assert res.failures[0].severity == Severity.BLOCKING

    def test_pre_check_missing_mesh_spec(
        self, valid_job_spec: JobSpec, mock_driver: MockMechanicalDriver
    ) -> None:
        """Pre-check flags ERR_MESH_SPEC_MISSING if spec.mesh is None."""
        spec_dict = valid_job_spec.to_dict()
        spec_dict["mesh"] = None
        spec = JobSpec.model_validate(spec_dict)
        context = RunContext(spec=spec, driver=mock_driver)
        step = Step08Meshing()
        res = step.pre_check(context)
        assert_check_failed(res, expected_code=ERR_MESH_SPEC_MISSING)

    def test_pre_check_empty_model_no_bodies(self, valid_job_spec: JobSpec) -> None:
        """Pre-check flags ERR_MESH_NO_BODIES if CAD model has zero bodies."""
        driver = MockMechanicalDriver()  # No bodies added
        context = RunContext(spec=valid_job_spec, driver=driver)
        step = Step08Meshing()
        res = step.pre_check(context)
        assert_check_failed(res, expected_code=ERR_MESH_NO_BODIES)

    def test_pre_check_body_without_material_assignment(
        self, valid_job_spec: JobSpec, mock_driver: MockMechanicalDriver
    ) -> None:
        """Pre-check flags ERR_MAT_UNASSIGNED_BODY if a body has no material assigned."""
        # mock_driver has bodies but Step 6 has not run (no material assigned)
        context = RunContext(spec=valid_job_spec, driver=mock_driver)
        step = Step08Meshing()
        res = step.pre_check(context)
        assert_check_failed(res, expected_code=ERR_MAT_UNASSIGNED_BODY)
        assert any("Bracket_Solid_Base" in f.component_or_entity for f in res.failures)

    def test_pre_check_surface_body_missing_thickness(
        self, valid_job_spec: JobSpec, mock_driver: MockMechanicalDriver
    ) -> None:
        """Pre-check flags ERR_MAT_INVALID_THICKNESS if a surface body has None thickness."""
        # Assign materials to all bodies, but leave thickness None on surface body
        for body in mock_driver.get_bodies():
            mock_driver.assign_material(body.name, "Structural_Steel")
        mock_driver.set_shell_thickness("Web_Plate_Upper", 0.0)  # Invalid non-positive

        context = RunContext(spec=valid_job_spec, driver=mock_driver)
        step = Step08Meshing()
        res = step.pre_check(context)
        assert_check_failed(res, expected_code=ERR_MAT_INVALID_THICKNESS)

    def test_pre_check_local_refinement_missing_named_selection(
        self, valid_job_spec: JobSpec, mock_driver: MockMechanicalDriver
    ) -> None:
        """Pre-check flags ERR_MESH_MISSING_SELECTION if local refinement targets non-existent selection."""
        # Prepare bodies
        for body in mock_driver.get_bodies():
            mock_driver.assign_material(body.name, "Structural_Steel")
            if body.body_type == "surface":
                mock_driver.set_shell_thickness(body.name, 2.0)

        # Create one selection in driver
        mock_driver.create_named_selection("NS_EXISTING", ["face_1"])

        # Spec references non-existent selection
        spec_dict = valid_job_spec.to_dict()
        spec_dict["mesh"]["local_refinements"] = [
            {"name": "RefineHoles", "selection": "NS_NONEXISTENT_HOLES", "element_size": 1.0}
        ]
        spec = JobSpec.model_validate(spec_dict)

        context = RunContext(spec=spec, driver=mock_driver)
        step = Step08Meshing()
        res = step.pre_check(context)
        assert_check_failed(res, expected_code=ERR_MESH_MISSING_SELECTION)

    def test_pre_check_local_refinement_valid_named_selection(
        self, valid_job_spec: JobSpec, mock_driver: MockMechanicalDriver
    ) -> None:
        """Pre-check passes when local refinement targets an existing named selection."""
        for body in mock_driver.get_bodies():
            mock_driver.assign_material(body.name, "Structural_Steel")
            if body.body_type == "surface":
                mock_driver.set_shell_thickness(body.name, 2.0)

        mock_driver.create_named_selection("NS_HOLES", ["face_1", "face_2"])

        spec_dict = valid_job_spec.to_dict()
        spec_dict["mesh"]["local_refinements"] = [
            {"name": "RefineHoles", "selection": "NS_HOLES", "element_size": 1.5}
        ]
        spec = JobSpec.model_validate(spec_dict)

        context = RunContext(spec=spec, driver=mock_driver)
        step = Step08Meshing()
        res = step.pre_check(context)
        assert_check_passed(res)


# ===========================================================================
# 4. Execute Phase Failure Scenarios
# ===========================================================================


class TestStep08ExecuteFailures:
    """Verifies that execute enforces connection and spec integrity."""

    def test_execute_driver_disconnected_raises(
        self, valid_job_spec: JobSpec, mock_driver: MockMechanicalDriver
    ) -> None:
        """Execute aborts with ConnectionError when driver is disconnected."""
        mock_driver.disconnect()
        context = RunContext(spec=valid_job_spec, driver=mock_driver)
        step = Step08Meshing()
        with pytest.raises(ConnectionError, match="not connected"):
            step.execute(context)

    def test_execute_missing_mesh_settings_raises(
        self, valid_job_spec: JobSpec, mock_driver: MockMechanicalDriver
    ) -> None:
        """Execute aborts with ValueError when mesh spec is None."""
        spec_dict = valid_job_spec.to_dict()
        spec_dict["mesh"] = None
        spec = JobSpec.model_validate(spec_dict)
        context = RunContext(spec=spec, driver=mock_driver)
        step = Step08Meshing()
        with pytest.raises(ValueError, match="mesh settings are missing"):
            step.execute(context)


# ===========================================================================
# 5. Post-Check and Fault Injection Scenarios
# ===========================================================================


class TestStep08PostCheckAndFaultInjection:
    """Verifies that post-check detects corrupted mesh quality metrics and produces actionable diagnostics."""

    @pytest.fixture
    def meshed_context(
        self, valid_job_spec: JobSpec, mock_driver: MockMechanicalDriver
    ) -> RunContext:
        """RunContext with Step 6 and Step 8 executed cleanly."""
        step6 = Step06MaterialMapping()
        step8 = Step08Meshing()
        context = RunContext(spec=valid_job_spec, driver=mock_driver)
        step6.pre_check(context)
        step6.execute(context)
        step8.pre_check(context)
        step8.execute(context)
        return context

    def test_post_check_driver_disconnected(self, meshed_context: RunContext) -> None:
        """Post-check flags ERR_DRIVER_COMMUNICATION if connection drops after execution."""
        step = Step08Meshing()
        meshed_context.driver.disconnect()
        res = step.post_check(meshed_context)
        assert_check_failed(res, expected_code=ERR_DRIVER_COMMUNICATION)
        meshed_context.driver.connect()

    def test_post_check_mesh_generation_failure(self, meshed_context: RunContext) -> None:
        """Post-check flags ERR_MESH_GENERATION_FAILED when mesh was not generated."""
        step = Step08Meshing()
        meshed_context.driver._mesh_generated = False
        res = step.post_check(meshed_context)
        assert_check_failed(res, expected_code=ERR_MESH_GENERATION_FAILED)

    def test_post_check_element_count_below_minimum(self, meshed_context: RunContext) -> None:
        """Post-check flags ERR_MESH_ELEMENT_COUNT when element count is 0."""
        step = Step08Meshing()
        meshed_context.driver.inject_mesh_element_count(0)
        res = step.post_check(meshed_context)
        assert_check_failed(res, expected_code=ERR_MESH_ELEMENT_COUNT)

    def test_post_check_skewness_exceeded(self, meshed_context: RunContext) -> None:
        """Post-check flags ERR_MESH_SKEWNESS_EXCEEDED when skewness exceeds threshold."""
        step = Step08Meshing()
        # Inject high skewness (0.92) with specific element IDs
        meshed_context.driver.inject_mesh_skewness(0.92, [1042, 1043])

        res = step.post_check(meshed_context)
        assert_check_failed(res, expected_code=ERR_MESH_SKEWNESS_EXCEEDED)

        failure = res.failures[0]
        assert failure.measured_value == pytest.approx(0.92)
        assert "1042" in failure.component_or_entity
        assert "1043" in failure.component_or_entity
        assert any("local mesh refinement" in fix.lower() for fix in failure.suggested_fixes)
        assert failure.resume_step_id == "step_08_meshing"

        # Troubleshooter produces the same failure
        failures = step.troubleshoot(meshed_context, res)
        assert len(failures) == 1
        assert failures[0].error_code == ERR_MESH_SKEWNESS_EXCEEDED

    def test_post_check_aspect_ratio_exceeded(self, meshed_context: RunContext) -> None:
        """Post-check flags ERR_MESH_ASPECT_RATIO_EXCEEDED when aspect ratio exceeds limit."""
        step = Step08Meshing()
        meshed_context.driver.inject_mesh_aspect_ratio(15.5, [2001, 2002])

        res = step.post_check(meshed_context)
        assert_check_failed(res, expected_code=ERR_MESH_ASPECT_RATIO_EXCEEDED)

        failure = res.failures[0]
        assert failure.measured_value == pytest.approx(15.5)
        assert "2001" in failure.component_or_entity
        assert failure.resume_step_id == "step_08_meshing"

    def test_post_check_warpage_exceeded(self, meshed_context: RunContext) -> None:
        """Post-check flags ERR_MESH_WARPAGE_EXCEEDED when warpage exceeds limit."""
        step = Step08Meshing()
        meshed_context.driver.inject_mesh_warpage(52.0, [3005])

        res = step.post_check(meshed_context)
        assert_check_failed(res, expected_code=ERR_MESH_WARPAGE_EXCEEDED)

        failure = res.failures[0]
        assert failure.measured_value == pytest.approx(52.0)
        assert "3005" in failure.component_or_entity
        assert failure.resume_step_id == "step_08_meshing"

    def test_post_check_concurrent_quality_failures(self, meshed_context: RunContext) -> None:
        """Post-check records multiple concurrent failures when several metrics fail."""
        step = Step08Meshing()
        meshed_context.driver.inject_mesh_skewness(0.91, [1001])
        meshed_context.driver.inject_mesh_aspect_ratio(14.0, [2001])
        meshed_context.driver.inject_mesh_warpage(48.0, [3001])

        res = step.post_check(meshed_context)
        assert_check_failed(res)
        assert len(res.failures) == 3
        codes = [f.error_code for f in res.failures]
        assert ERR_MESH_SKEWNESS_EXCEEDED in codes
        assert ERR_MESH_ASPECT_RATIO_EXCEEDED in codes
        assert ERR_MESH_WARPAGE_EXCEEDED in codes

    def test_fault_recovery_lifecycle(self, meshed_context: RunContext) -> None:
        """Fault is injected, detected by post-check, cleared, and post-check passes."""
        step = Step08Meshing()
        meshed_context.driver.inject_mesh_skewness(0.93)
        res_fail = step.post_check(meshed_context)
        assert_check_failed(res_fail)

        # Clear fault
        meshed_context.driver.clear_faults()
        res_pass = step.post_check(meshed_context)
        assert_check_passed(res_pass)


# ===========================================================================
# 6. Quality Threshold Boundaries and Custom Overrides
# ===========================================================================


class TestStep08ThresholdBoundaries:
    """Verifies threshold boundary values and custom spec overrides."""

    @pytest.fixture
    def meshed_context(
        self, valid_job_spec: JobSpec, mock_driver: MockMechanicalDriver
    ) -> RunContext:
        step6 = Step06MaterialMapping()
        step8 = Step08Meshing()
        context = RunContext(spec=valid_job_spec, driver=mock_driver)
        step6.pre_check(context)
        step6.execute(context)
        step8.pre_check(context)
        step8.execute(context)
        return context

    def test_exact_skewness_boundary_passes(self, meshed_context: RunContext) -> None:
        """Skewness exactly equal to threshold passes."""
        step = Step08Meshing()
        # Default threshold in valid_job_spec (min_quality 0.25 -> 1 - 0.25 = 0.75)
        meshed_context.driver.inject_mesh_skewness(0.7500)
        res = step.post_check(meshed_context)
        assert_check_passed(res)

    def test_slightly_exceeded_skewness_boundary_fails(self, meshed_context: RunContext) -> None:
        """Skewness slightly exceeding threshold fails."""
        step = Step08Meshing()
        meshed_context.driver.inject_mesh_skewness(0.7501)
        res = step.post_check(meshed_context)
        assert_check_failed(res, expected_code=ERR_MESH_SKEWNESS_EXCEEDED)

    def test_custom_quality_limits_override(
        self, valid_job_spec: JobSpec, mock_driver: MockMechanicalDriver
    ) -> None:
        """Explicit quality_limits in JobSpec take precedence."""
        spec_dict = valid_job_spec.to_dict()
        spec_dict["mesh"]["quality_limits"] = {
            "max_skewness": 0.88,
            "max_aspect_ratio": 8.0,
            "max_warpage": 30.0,
        }
        spec = JobSpec.model_validate(spec_dict)

        step6 = Step06MaterialMapping()
        step8 = Step08Meshing()
        context = RunContext(spec=spec, driver=mock_driver)
        step6.pre_check(context)
        step6.execute(context)
        step8.execute(context)

        # Skewness 0.86 is < 0.88 -> passes
        mock_driver.inject_mesh_skewness(0.86)
        res = step8.post_check(context)
        assert_check_passed(res)

        # Aspect ratio 8.5 > 8.0 -> fails
        mock_driver.inject_mesh_aspect_ratio(8.5)
        res = step8.post_check(context)
        assert_check_failed(res, expected_code=ERR_MESH_ASPECT_RATIO_EXCEEDED)


# ===========================================================================
# 7. Step 6 + Step 8 End-to-End Sequential Integration
# ===========================================================================


class TestStep06And08EndToEndIntegration:
    """Verifies end-to-end integration across materials and meshing steps."""

    def test_sequential_materials_and_meshing_workflow(
        self,
        aerospace_assembly_spec_dict: dict[str, Any],
        populated_aerospace_driver: MockMechanicalDriver,
    ) -> None:
        """Step 6 followed by Step 8 executes cleanly on realistic aerospace assembly."""
        spec = JobSpec.model_validate(aerospace_assembly_spec_dict)
        context = RunContext(spec=spec, driver=populated_aerospace_driver)

        step6 = Step06MaterialMapping()
        step8 = Step08Meshing()

        # Step 6 execution
        res6_pre = step6.pre_check(context)
        assert_check_passed(res6_pre)
        step6.execute(context)
        res6_post = step6.post_check(context)
        assert_check_passed(res6_post)

        # Step 8 execution
        res8_pre = step8.pre_check(context)
        assert_check_passed(res8_pre)
        step8.execute(context)
        res8_post = step8.post_check(context)
        assert_check_passed(res8_post)

        # Confirm model state
        driver = context.driver
        assert driver.is_mesh_generated() is True
        assert driver.get_element_count() > 0
        assert driver.get_max_skewness() <= 0.75
        assert driver.get_max_aspect_ratio() <= 10.0
        assert driver.get_max_warpage() <= 45.0


# ===========================================================================
# 8. Adversarial Edge Cases and Hardened Scenarios
# ===========================================================================


class TestStep08AdversarialEdgeCases:
    """Rigorous adversarial edge cases: empty selections, shell aliases, idempotency, warnings."""

    def test_pre_check_local_refinement_zero_named_selections_in_model_fails(
        self, valid_job_spec: JobSpec, mock_driver: MockMechanicalDriver
    ) -> None:
        """Pre-check strictly flags ERR_MESH_MISSING_SELECTION when model has ZERO named selections."""
        for body in mock_driver.get_bodies():
            mock_driver.assign_material(body.name, "Structural_Steel")
            if body.body_type == "surface":
                mock_driver.set_shell_thickness(body.name, 2.0)

        # Driver has NO named selections created (empty list)
        assert len(mock_driver.get_named_selections()) == 0

        spec_dict = valid_job_spec.to_dict()
        spec_dict["mesh"]["local_refinements"] = [
            {"name": "RefineHoles", "selection": "NS_NONEXISTENT", "element_size": 1.0}
        ]
        spec = JobSpec.model_validate(spec_dict)

        context = RunContext(spec=spec, driver=mock_driver)
        step = Step08Meshing()
        res = step.pre_check(context)
        assert_check_failed(res, expected_code=ERR_MESH_MISSING_SELECTION)
        assert res.failures[0].component_or_entity == "RefineHoles"
        assert "none found" in str(res.failures[0].expected_value).lower()

    def test_pre_check_shell_body_type_missing_thickness_fails(
        self, valid_job_spec: JobSpec, mock_driver: MockMechanicalDriver
    ) -> None:
        """Pre-check checks thickness for body_type='shell' (interchangeable with 'surface')."""
        mock_driver.add_body("Fuselage_Shell", body_type="shell", thickness=None)
        mock_driver.assign_material("Fuselage_Shell", "Structural_Steel")

        for body in mock_driver.get_bodies():
            mock_driver.assign_material(body.name, "Structural_Steel")
            if body.body_type in ("surface", "shell") and body.name != "Fuselage_Shell":
                mock_driver.set_shell_thickness(body.name, 2.0)

        context = RunContext(spec=valid_job_spec, driver=mock_driver)
        step = Step08Meshing()
        res = step.pre_check(context)
        assert_check_failed(res, expected_code=ERR_MAT_INVALID_THICKNESS)
        assert any(f.component_or_entity == "Fuselage_Shell" for f in res.failures)

    def test_add_local_refinement_idempotent_update(self) -> None:
        """Driver add_local_refinement updates existing entry by name instead of duplicating."""
        driver = MockMechanicalDriver()
        driver.add_body("Body1", body_type="solid")
        driver.add_local_refinement("RefineWeld", "NS_WELD", 2.0)
        assert len(driver.get_local_refinements()) == 1
        assert driver.get_local_refinements()[0]["element_size"] == pytest.approx(2.0)

        # Update refinement with smaller element size
        driver.add_local_refinement("RefineWeld", "NS_WELD", 1.0)
        assert len(driver.get_local_refinements()) == 1
        assert driver.get_local_refinements()[0]["element_size"] == pytest.approx(1.0)

    def test_mesh_generation_uppercase_quadratic_order(self) -> None:
        """Driver handles uppercase or variant element_order ('QUADRATIC') as quadratic."""
        driver = MockMechanicalDriver()
        driver.add_body("Body1", body_type="solid")
        stats = driver.generate_mesh(global_size=5.0, element_order="QUADRATIC")
        assert stats.node_count == stats.element_count * 8

    def test_post_check_element_count_exceeds_maximum_warning(
        self, valid_job_spec: JobSpec, mock_driver: MockMechanicalDriver
    ) -> None:
        """Post-check flags ERR_MESH_ELEMENT_COUNT as WARNING (non-blocking) when count exceeds max_elements."""
        spec_dict = valid_job_spec.to_dict()
        spec_dict["mesh"]["quality_limits"] = {
            "min_elements": 100,
            "max_elements": 500,
        }
        spec = JobSpec.model_validate(spec_dict)

        step6 = Step06MaterialMapping()
        step8 = Step08Meshing()
        context = RunContext(spec=spec, driver=mock_driver)
        step6.pre_check(context)
        step6.execute(context)
        step8.execute(context)

        # Inject high element count (800 > max 500)
        mock_driver.inject_mesh_element_count(800)
        res = step8.post_check(context)

        # Result is non-blocking warning: passed is True, is_successful is True
        assert res.passed is True
        assert res.is_successful is True
        assert len(res.failures) == 1
        assert res.failures[0].error_code == ERR_MESH_ELEMENT_COUNT
        assert res.failures[0].severity == Severity.WARNING

    def test_pre_check_none_driver_handled_cleanly(self, valid_job_spec: JobSpec) -> None:
        """Pre-check handles None driver cleanly without AttributeError."""
        context = RunContext(spec=valid_job_spec, driver=None)
        step = Step08Meshing()
        res = step.pre_check(context)
        assert_check_failed(res, expected_code=ERR_DRIVER_COMMUNICATION)

    def test_get_failing_elements_case_insensitive(self) -> None:
        """Quality metric query handles case variations and hyphens."""
        driver = MockMechanicalDriver()
        driver.add_body("Body1", body_type="solid")
        driver.generate_mesh(global_size=5.0)
        driver.inject_mesh_skewness(0.92, [1001, 1002])

        assert driver.get_failing_elements("SKEWNESS", 0.85) == [1001, 1002]
        assert driver.get_failing_elements("skewness", 0.85) == [1001, 1002]


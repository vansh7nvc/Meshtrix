"""
Meshtrix Tier 2: Boundary, Edge & Corner Cases Test Suite.

Authoritative Reference: ORIGINAL_REQUEST.md §R2, §R3 & Acceptance Criteria
Focus:
- Negative & zero shell thickness handling
- Invalid units and unsupported analysis types
- Unmapped bodies present in CAD model
- Missing material catalog references
- Surface bodies with missing thickness vs solid bodies
- Tolerance threshold boundaries (exact, within-tolerance, out-of-tolerance)
- Adversarial body naming (spaces, slashes, unicode)
- Empty assembly and catalog edge conditions
"""

from copy import deepcopy
from typing import Any

import pytest
from pydantic import ValidationError

from meshtrix.core.step import RunContext
from meshtrix.diagnostics.failure import Severity
from meshtrix.drivers.mock import MockMechanicalDriver
from meshtrix.spec.job_spec import (
    BodyMaterialMapping,
    JobSpec,
)
from meshtrix.steps.step_06_materials import Step06MaterialMapping
from tests.conftest import assert_check_failed, assert_check_passed

# ===========================================================================
# 1. Negative & Zero Thickness Boundary Tests
# ===========================================================================


class TestThicknessBoundaries:
    """Verifies strict boundary handling of shell thicknesses."""

    @pytest.mark.parametrize("invalid_thickness", [0.0, -0.001, -1.5, -100.0])
    def test_schema_rejects_non_positive_thickness(self, invalid_thickness: float) -> None:
        """Pydantic schema must reject thickness <= 0.0 with ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            BodyMaterialMapping(
                body_name="Skin_Panel",
                material_name="Aluminum_6061_T6",
                thickness=invalid_thickness,
            )
        assert "thickness" in str(exc_info.value).lower()

    def test_pre_check_catches_unsupported_zero_or_negative_thickness(
        self, valid_job_spec_dict: dict[str, Any]
    ) -> None:
        """If a bypass occurs or dynamic dict is used, pre-check must flag non-positive thickness."""
        spec_dict = deepcopy(valid_job_spec_dict)
        # Manually alter thickness bypassing initial validation if dict passed directly
        driver = MockMechanicalDriver()
        driver.add_body("Web_Plate_Upper", body_type="surface")

        # Create spec with valid minimal model
        spec = JobSpec.model_validate(spec_dict)
        step = Step06MaterialMapping()
        context = RunContext(spec=spec, driver=driver)

        # Inject an invalid thickness directly into mapping
        spec.materials.mappings["Web_Plate_Upper"].thickness = -2.0

        res = step.pre_check(context)
        assert_check_failed(res)
        assert any(
            "thickness" in f.engineering_message.lower() or "ERR_MAT" in f.error_code
            for f in res.failures
        )


# ===========================================================================
# 2. Invalid Units & Unsupported Analysis Types
# ===========================================================================


class TestUnitsAndAnalysisBoundaries:
    """Verifies system defense against invalid units and unsupported analysis disciplines."""

    @pytest.mark.parametrize(
        "bad_units", ["INVALID_UNITS", "furlongs_per_fortnight", "Kelvin_Imperial", ""]
    )
    def test_reject_invalid_units(
        self, valid_job_spec_dict: dict[str, Any], bad_units: str
    ) -> None:
        """JobSpec must reject unrecognized unit systems at the schema level."""
        spec_dict = deepcopy(valid_job_spec_dict)
        spec_dict["units"] = bad_units
        with pytest.raises(ValidationError):
            JobSpec.model_validate(spec_dict)

    @pytest.mark.parametrize(
        "bad_analysis", ["CFD_TURBULENCE", "QUANTUM_MECHANICS", "ELECTROMAGNETIC", "1234", ""]
    )
    def test_reject_unsupported_analysis_types(
        self, valid_job_spec_dict: dict[str, Any], bad_analysis: str
    ) -> None:
        """JobSpec must reject non-structural / unsupported analysis types."""
        spec_dict = deepcopy(valid_job_spec_dict)
        spec_dict["analysis_type"] = bad_analysis
        with pytest.raises(ValidationError):
            JobSpec.model_validate(spec_dict)


# ===========================================================================
# 3. Unmapped CAD Bodies in Model
# ===========================================================================


class TestUnmappedBodiesBoundaries:
    """Verifies pre-check and troubleshooting when CAD contains unmapped parts."""

    def test_pre_check_flags_unmapped_cad_body(
        self, valid_job_spec: JobSpec, mock_driver: MockMechanicalDriver
    ) -> None:
        """When the CAD model introduces an unexpected body, pre-check must fail with ERR_MAT_UNMAPPED_BODY."""
        # Add an unmapped body to the driver
        mock_driver.add_body(name="Mystery_Gusset_99", body_type="surface", thickness=None)

        step = Step06MaterialMapping()
        context = RunContext(spec=valid_job_spec, driver=mock_driver)

        res = step.pre_check(context)
        assert_check_failed(res, expected_code="ERR_MAT_UNMAPPED_BODY")

        # Troubleshooter must point to the specific unmapped component
        failures = step.troubleshoot(context, res)
        unmapped_failures = [f for f in failures if f.error_code == "ERR_MAT_UNMAPPED_BODY"]
        assert len(unmapped_failures) > 0
        assert unmapped_failures[0].component_or_entity == "Mystery_Gusset_99"
        assert unmapped_failures[0].severity == Severity.BLOCKING
        assert unmapped_failures[0].resume_step_id == "step_06_materials"


# ===========================================================================
# 4. Missing Material Catalog Entries
# ===========================================================================


class TestMissingCatalogEntriesBoundaries:
    """Verifies relational checks between body mappings and the materials catalog."""

    def test_schema_or_pre_check_catches_unregistered_material(
        self, valid_job_spec_dict: dict[str, Any]
    ) -> None:
        """Mapping referencing a material not defined in catalog must be caught."""
        spec_dict = deepcopy(valid_job_spec_dict)
        # Assign undefined material to one mapping
        spec_dict["materials"]["mappings"]["Flange_Skin_Outer"]["material_name"] = "Unobtainium_X"

        # The schema relational validator or pre_check must detect this
        try:
            spec = JobSpec.model_validate(spec_dict)
            # If schema allows forward-references, pre-check must catch it
            driver = MockMechanicalDriver()
            driver.add_body("Flange_Skin_Outer", body_type="surface")
            step = Step06MaterialMapping()
            res = step.pre_check(RunContext(spec=spec, driver=driver))
            assert_check_failed(res, expected_code="ERR_MAT_MISSING_CATALOG")
        except ValidationError as e:
            # Schema relational validation caught it at construction
            assert "Unobtainium_X" in str(e) or "catalog" in str(e).lower()


# ===========================================================================
# 5. Surface Body Missing Thickness
# ===========================================================================


class TestSurfaceBodyMissingThicknessBoundaries:
    """Verifies that surface/shell bodies MUST have thickness specified."""

    def test_surface_body_without_thickness_fails_pre_check(
        self, valid_job_spec_dict: dict[str, Any]
    ) -> None:
        """A surface body mapped with thickness=None must fail pre-check with blocking severity."""
        spec_dict = deepcopy(valid_job_spec_dict)
        # Web_Plate_Upper is a surface body in CAD, set thickness to None
        spec_dict["materials"]["mappings"]["Web_Plate_Upper"]["thickness"] = None
        spec = JobSpec.model_validate(spec_dict)

        driver = MockMechanicalDriver()
        driver.add_body("Web_Plate_Upper", body_type="surface")

        step = Step06MaterialMapping()
        res = step.pre_check(RunContext(spec=spec, driver=driver))

        assert_check_failed(res)
        # Verify failure specifically flags missing thickness for surface body
        thickness_failures = [
            f
            for f in res.failures
            if "thickness" in f.engineering_message.lower() or "THICKNESS" in f.error_code
        ]
        assert len(thickness_failures) > 0
        assert thickness_failures[0].component_or_entity == "Web_Plate_Upper"


# ===========================================================================
# 6. Physical Tolerance Threshold Boundaries
# ===========================================================================


class TestToleranceThresholdBoundaries:
    """Verifies post-check thickness tolerance evaluations (exact, within, out-of-tolerance)."""

    def test_exact_thickness_match_passes(self, sample_run_context: RunContext) -> None:
        """Exact match between driver state and spec passes post-check."""
        step = Step06MaterialMapping()
        step.pre_check(sample_run_context)
        step.execute(sample_run_context)
        res = step.post_check(sample_run_context)
        assert_check_passed(res)

    def test_within_tolerance_thickness_passes(self, sample_run_context: RunContext) -> None:
        """A minor variation within the configured tolerance threshold passes post-check."""
        step = Step06MaterialMapping()
        step.pre_check(sample_run_context)
        step.execute(sample_run_context)

        # Injected variation: Web_Plate_Upper spec is 2.5mm, tolerance is 0.01 (10um)
        # Inject driver variation of 0.005mm (5um)
        driver = sample_run_context.driver
        driver.set_shell_thickness("Web_Plate_Upper", 2.505)

        res = step.post_check(sample_run_context)
        assert_check_passed(res)

    def test_out_of_tolerance_thickness_fails_post_check(
        self, sample_run_context: RunContext
    ) -> None:
        """A variation exceeding tolerance threshold must fail post-check with ERR_MAT_THICKNESS_MISMATCH."""
        step = Step06MaterialMapping()
        step.pre_check(sample_run_context)
        step.execute(sample_run_context)

        # Web_Plate_Upper spec is 2.5mm, inject 2.8mm (+0.3mm > 0.01mm tolerance)
        driver = sample_run_context.driver
        driver.set_shell_thickness("Web_Plate_Upper", 2.8)

        res = step.post_check(sample_run_context)
        assert_check_failed(res, expected_code="ERR_MAT_THICKNESS_MISMATCH")

        failures = step.troubleshoot(sample_run_context, res)
        thk_failures = [f for f in failures if f.error_code == "ERR_MAT_THICKNESS_MISMATCH"]
        assert len(thk_failures) > 0
        assert thk_failures[0].component_or_entity == "Web_Plate_Upper"
        assert thk_failures[0].measured_value == pytest.approx(2.8)
        assert thk_failures[0].expected_value == pytest.approx(2.5)


# ===========================================================================
# 7. Adversarial Strings & Extreme Geometry Boundaries
# ===========================================================================


class TestAdversarialInputsAndExtremeValues:
    """Adversarial testing with spaces, slashes, unicode, and extreme thicknesses."""

    @pytest.mark.parametrize(
        "exotic_name",
        [
            "Lower Rib / Subassembly #1",
            "Rib.Outer-Left_Flange",
            "Front_Bulkhead_隔框_01",
            "Part with multiple spaces and (parentheses)",
        ],
    )
    def test_exotic_body_names_supported(
        self, valid_job_spec_dict: dict[str, Any], exotic_name: str
    ) -> None:
        """CAD body names containing spaces, slashes, parentheses, and unicode are handled cleanly."""
        spec_dict = deepcopy(valid_job_spec_dict)
        spec_dict["materials"]["mappings"] = {
            exotic_name: {
                "body_name": exotic_name,
                "material_name": "Structural_Steel",
                "thickness": 3.0,
            }
        }
        spec = JobSpec.model_validate(spec_dict)

        driver = MockMechanicalDriver()
        driver.add_body(name=exotic_name, body_type="surface")

        step = Step06MaterialMapping()
        context = RunContext(spec=spec, driver=driver)

        # Pre-check, execute, post-check should all pass cleanly without string escaping bugs
        assert_check_passed(step.pre_check(context))
        step.execute(context)
        assert_check_passed(step.post_check(context))
        assert driver.get_assigned_material(exotic_name) == "Structural_Steel"
        assert driver.get_shell_thickness(exotic_name) == pytest.approx(3.0)

    @pytest.mark.parametrize("extreme_thickness", [0.0001, 100.0, 500.0])
    def test_extreme_thickness_values(
        self, valid_job_spec_dict: dict[str, Any], extreme_thickness: float
    ) -> None:
        """Micro-thin foils (0.1um) and thick armor plates (500mm) pass if positive."""
        mapping = BodyMaterialMapping(
            body_name="Armor_Skin",
            material_name="Structural_Steel",
            thickness=extreme_thickness,
        )
        assert mapping.thickness == pytest.approx(extreme_thickness)


# ===========================================================================
# 8. Empty Assembly and Empty Catalog Edge Conditions
# ===========================================================================


class TestEmptyAssemblyAndCatalogBoundaries:
    """Verifies graceful handling of empty assembly and empty catalog edge conditions."""

    def test_empty_model_and_catalog_graceful_pass(self) -> None:
        """When CAD model has 0 bodies and JobSpec catalog/mappings are empty, lifecycle passes."""
        spec_dict = {
            "job_id": "JOB-EMPTY-001",
            "units": "Metric_mm",
            "analysis_type": "STRUCTURAL_STATIC",
            "materials": {"catalog": {}, "mappings": {}},
        }
        spec = JobSpec.model_validate(spec_dict)
        driver = MockMechanicalDriver()
        context = RunContext(spec=spec, driver=driver)
        step = Step06MaterialMapping()

        pre_res = step.pre_check(context)
        assert_check_passed(pre_res)

        step.execute(context)

        post_res = step.post_check(context)
        assert_check_passed(post_res)

    def test_cad_bodies_with_empty_catalog_and_mappings_fails_pre_check(self) -> None:
        """When CAD model contains bodies but JobSpec has empty mappings, pre-check flags ERR_MAT_UNMAPPED_BODY."""
        spec_dict = {
            "job_id": "JOB-EMPTY-CATALOG-002",
            "units": "Metric_mm",
            "analysis_type": "STRUCTURAL_STATIC",
            "materials": {"catalog": {}, "mappings": {}},
        }
        spec = JobSpec.model_validate(spec_dict)
        driver = MockMechanicalDriver()
        driver.add_body("Unmapped_Spar", body_type="solid")
        context = RunContext(spec=spec, driver=driver)
        step = Step06MaterialMapping()

        res = step.pre_check(context)
        assert_check_failed(res, expected_code="ERR_MAT_UNMAPPED_BODY")
        assert res.failures[0].component_or_entity == "Unmapped_Spar"

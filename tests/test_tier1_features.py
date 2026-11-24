"""
Meshtrix Tier 1: Feature Coverage Test Suite.

Authoritative Reference: ORIGINAL_REQUEST.md & PROJECT.md
Features Tested:
- JobSpec Pydantic v2 validation (units, analysis type, materials, mesh, loads, supports, mass target, tolerances)
- Structured engineering FailureObject schema & Severity tiers
- StepCheckResult container aggregation
- BaseStep 4-phase contract (pre_check, execute, post_check, troubleshoot)
- MockMechanicalDriver zero-license inspection, mutation, and fault injection
- Step 6 Material Mapping nominal 4-phase execution
"""

from pathlib import Path
from typing import Any

import pytest

from meshtrix.core.step import BaseStep, RunContext
from meshtrix.diagnostics.failure import (
    ERR_DRIVER_COMMUNICATION,
    ERR_MAT_THICKNESS_MISMATCH,
    ERR_MAT_UNASSIGNED_BODY,
    FailureObject,
    Severity,
    StepCheckResult,
)
from meshtrix.drivers.base import BodyProperties, MechanicalDriver
from meshtrix.drivers.mock import MockMechanicalDriver
from meshtrix.spec.job_spec import (
    AnalysisType,
    BodyMaterialMapping,
    CheckTolerances,
    JobSpec,
    MassTarget,
    MaterialCatalogEntry,
    MeshSettings,
    UnitsSystem,
)
from meshtrix.steps.step_06_materials import Step06MaterialMapping
from tests.conftest import assert_check_failed, assert_check_passed

# ===========================================================================
# 1. JobSpec and Sub-Model Schema Feature Coverage
# ===========================================================================


class TestJobSpecSchemaCoverage:
    """Verifies that all JobSpec schemas validate correctly against specification requirements."""

    def test_units_system_enum_members(self) -> None:
        """UnitsSystem enum must define standard engineering units (Metric_mm, SI, etc.)."""
        # Ensure enum values are valid string-compatible identifiers
        assert hasattr(UnitsSystem, "METRIC_MM") or hasattr(UnitsSystem, "Metric_mm")
        # Validate parsing from string
        unit = UnitsSystem("Metric_mm")
        assert unit is not None

    def test_analysis_type_enum_members(self) -> None:
        """AnalysisType enum must define valid FEA disciplines."""
        assert hasattr(AnalysisType, "STRUCTURAL_STATIC")
        analysis = AnalysisType("STRUCTURAL_STATIC")
        assert analysis is not None

    def test_material_catalog_entry_instantiation(self) -> None:
        """MaterialCatalogEntry must capture physical engineering constants."""
        mat = MaterialCatalogEntry(
            name="Alloy_Steel_4130",
            density=7.85e-9,
            elastic_modulus=205000.0,
            poissons_ratio=0.29,
            yield_strength=435.0,
        )
        assert mat.name == "Alloy_Steel_4130"
        assert mat.density == pytest.approx(7.85e-9)
        assert mat.elastic_modulus == pytest.approx(205000.0)
        assert mat.poissons_ratio == pytest.approx(0.29)
        assert mat.yield_strength == pytest.approx(435.0)

    def test_body_material_mapping_instantiation(self) -> None:
        """BodyMaterialMapping must accept solid (None thickness) and shell (positive thickness)."""
        solid_mapping = BodyMaterialMapping(
            body_name="Solid_Casting",
            material_name="Structural_Steel",
            thickness=None,
        )
        assert solid_mapping.body_name == "Solid_Casting"
        assert solid_mapping.thickness is None

        shell_mapping = BodyMaterialMapping(
            body_name="Shell_Fairing",
            material_name="Aluminum_6061_T6",
            thickness=1.8,
        )
        assert shell_mapping.body_name == "Shell_Fairing"
        assert shell_mapping.thickness == pytest.approx(1.8)

    def test_mesh_settings_instantiation(self) -> None:
        """MeshSettings must validate mesh sizing, element order, and quality limits."""
        mesh = MeshSettings(
            global_size=4.0,
            element_order="quadratic",
            min_quality=0.3,
            quality_metric="skewness",
        )
        assert mesh.global_size == pytest.approx(4.0)
        assert mesh.element_order == "quadratic"
        assert mesh.min_quality == pytest.approx(0.3)

    def test_tolerances_and_mass_target(self) -> None:
        """CheckTolerances and MassTarget must capture engineering target parameters."""
        tol = CheckTolerances(thickness_tolerance=0.005, mass_tolerance=0.02)
        assert tol.thickness_tolerance == pytest.approx(0.005)

        mass = MassTarget(total_mass=128.4, cg_x=12.0, cg_y=0.0, cg_z=-5.5)
        assert mass.total_mass == pytest.approx(128.4)
        assert mass.cg_x == pytest.approx(12.0)

    def test_full_valid_job_spec(self, valid_job_spec: JobSpec) -> None:
        """JobSpec root model loads and exposes all subcomponents correctly."""
        assert valid_job_spec.job_id == "JOB-AERO-2026-001"
        assert "Structural_Steel" in valid_job_spec.materials.catalog
        assert "Web_Plate_Upper" in valid_job_spec.materials.mappings
        assert valid_job_spec.mesh is not None
        assert valid_job_spec.tolerances is not None

    def test_job_spec_serialization_methods(self, valid_job_spec: JobSpec, tmp_path: Path) -> None:
        """JobSpec must serialize to/from dict and to/from YAML strings and files."""
        # Dict serialization
        spec_dict = valid_job_spec.to_dict()
        assert isinstance(spec_dict, dict)
        reconstructed = JobSpec.from_dict(spec_dict)
        assert reconstructed.job_id == valid_job_spec.job_id

        # YAML string serialization
        yaml_str = valid_job_spec.to_yaml()
        assert isinstance(yaml_str, str)
        from_str = JobSpec.from_yaml(yaml_str)
        assert from_str.job_id == valid_job_spec.job_id

        # YAML file serialization
        yaml_file = tmp_path / "spec.yaml"
        valid_job_spec.to_yaml(yaml_file)
        assert yaml_file.exists()
        from_file = JobSpec.from_yaml(yaml_file)
        assert from_file.job_id == valid_job_spec.job_id

    def test_units_system_and_analysis_type_case_insensitivity(self) -> None:
        """UnitsSystem and AnalysisType resolve case-insensitively and handle variations."""
        assert UnitsSystem("metric_mm") == UnitsSystem.Metric_mm
        assert UnitsSystem("METRIC_MM") == UnitsSystem.Metric_mm
        assert UnitsSystem("si") == UnitsSystem.SI
        assert UnitsSystem("mks") == UnitsSystem.MKS
        assert UnitsSystem("mpa") == UnitsSystem.MPA
        assert UnitsSystem("us_in_lbf_psi") == UnitsSystem.US_IN_LBF_PSI

        assert AnalysisType("structural_static") == AnalysisType.STRUCTURAL_STATIC
        assert AnalysisType("static_structural") == AnalysisType.STATIC_STRUCTURAL
        assert AnalysisType("modal") == AnalysisType.MODAL
        assert AnalysisType("random_vibration") == AnalysisType.RANDOM_VIBRATION

    def test_materials_spec_list_mappings_normalization(
        self, valid_job_spec_dict: dict[str, Any]
    ) -> None:
        """MaterialsSpec normalizes mappings when provided as a list of dicts."""
        from copy import deepcopy

        spec_dict = deepcopy(valid_job_spec_dict)
        spec_dict["materials"]["mappings"] = [
            {"body_name": "Bracket_Solid_Base", "material_name": "Structural_Steel"},
            {
                "body_name": "Web_Plate_Upper",
                "material_name": "Aluminum_6061_T6",
                "thickness": 2.5,
            },
            {
                "body_name": "Flange_Skin_Outer",
                "material_name": "Titanium_Ti6Al4V",
                "thickness": 1.25,
            },
        ]
        spec = JobSpec.model_validate(spec_dict)
        assert "Bracket_Solid_Base" in spec.materials.mappings
        assert spec.materials.mappings["Web_Plate_Upper"].thickness == pytest.approx(2.5)


# ===========================================================================
# 2. Diagnostics: FailureObject & StepCheckResult Feature Coverage
# ===========================================================================


class TestDiagnosticsFeatureCoverage:
    """Verifies FailureObject schema, Severity tiers, and StepCheckResult aggregation."""

    def test_severity_tier_values(self) -> None:
        """Severity enum must support blocking, warning, and auto-recoverable tiers."""
        assert Severity.BLOCKING.value == "blocking"
        assert Severity.WARNING.value == "warning"
        assert Severity.AUTO_RECOVERABLE.value == "auto_recoverable"

    def test_failure_object_schema_integrity(self) -> None:
        """FailureObject captures full engineering context, causes, fixes, and resume step."""
        failure = FailureObject(
            error_code="ERR_MAT_THICKNESS_MISMATCH",
            severity=Severity.BLOCKING,
            step_id="step_06_materials",
            component_or_entity="Wing_Upper_Skin",
            measured_value=1.5,
            expected_value=2.0,
            engineering_message="Shell thickness mismatch on surface body Wing_Upper_Skin.",
            likely_causes=["CAD export mid-surface thickness attribute missing", "Spec typo"],
            suggested_fixes=["Update CAD mid-surface thickness", "Correct thickness in JobSpec"],
            resume_step_id="step_06_materials",
        )
        assert failure.error_code == "ERR_MAT_THICKNESS_MISMATCH"
        assert failure.severity == Severity.BLOCKING
        assert failure.step_id == "step_06_materials"
        assert failure.component_or_entity == "Wing_Upper_Skin"
        assert failure.measured_value == 1.5
        assert failure.expected_value == 2.0
        assert len(failure.likely_causes) == 2
        assert len(failure.suggested_fixes) == 2
        assert failure.resume_step_id == "step_06_materials"

    def test_step_check_result_clean_pass(self) -> None:
        """StepCheckResult indicating clean execution has no failures."""
        result = StepCheckResult(passed=True, failures=[], warnings=[])
        assert result.passed is True
        assert len(result.failures) == 0
        assert len(result.warnings) == 0

    def test_step_check_result_with_blocking_failures(self) -> None:
        """StepCheckResult correctly aggregates blocking failures and flags failed status."""
        failure = FailureObject(
            error_code="ERR_MAT_UNMAPPED_BODY",
            severity=Severity.BLOCKING,
            step_id="step_06_materials",
            component_or_entity="Rib_04",
            measured_value=None,
            expected_value="Aluminum_7075",
            engineering_message="Body Rib_04 has no material mapping.",
            likely_causes=["Unlisted body in JobSpec"],
            suggested_fixes=["Add body mapping in spec.materials.mappings"],
            resume_step_id="step_06_materials",
        )
        result = StepCheckResult(passed=False, failures=[failure], warnings=[])
        assert result.passed is False
        assert len(result.failures) == 1
        assert result.failures[0].component_or_entity == "Rib_04"

    def test_step_check_result_warnings(self) -> None:
        """StepCheckResult correctly records non-blocking warnings while remaining passing."""
        result = StepCheckResult(passed=True)
        result.add_warning("Notice: local mesh refinement suggested.")
        assert result.passed is True
        assert result.is_successful is True
        assert len(result.warnings) == 1
        assert "mesh refinement" in result.warnings[0]


# ===========================================================================
# 3. BaseStep 4-Phase Contract & Core Lifecycle Feature Coverage
# ===========================================================================


class TestBaseStepInterfaceCoverage:
    """Verifies that BaseStep enforces the 4-phase contract."""

    def test_base_step_cannot_be_instantiated_directly(self) -> None:
        """BaseStep is an abstract base class and cannot be instantiated without implementations."""
        with pytest.raises(TypeError):
            BaseStep()  # type: ignore[abstract]

    def test_concrete_step_satisfies_contract(self, sample_run_context: RunContext) -> None:
        """A minimal concrete step implementing all 4 abstract methods satisfies the contract."""

        class DummyStep(BaseStep):
            @property
            def step_id(self) -> str:
                return "step_00_dummy"

            @property
            def description(self) -> str:
                return "Dummy verification step"

            def pre_check(self, context: RunContext) -> StepCheckResult:
                return StepCheckResult(passed=True, failures=[], warnings=[])

            def execute(self, context: RunContext) -> None:
                pass

            def post_check(self, context: RunContext) -> StepCheckResult:
                return StepCheckResult(passed=True, failures=[], warnings=[])

            def troubleshoot(
                self, context: RunContext, failure: StepCheckResult
            ) -> list[FailureObject]:
                return failure.failures

        step = DummyStep()
        assert step.step_id == "step_00_dummy"
        assert "Dummy" in step.description

        pre_res = step.pre_check(sample_run_context)
        assert pre_res.passed is True

        step.execute(sample_run_context)

        post_res = step.post_check(sample_run_context)
        assert post_res.passed is True


# ===========================================================================
# 4. MockMechanicalDriver Feature Coverage
# ===========================================================================


class TestMockMechanicalDriverCoverage:
    """Verifies MockMechanicalDriver behavior adhering to MechanicalDriver protocol."""

    def test_mock_driver_is_mechanical_driver(self) -> None:
        """MockMechanicalDriver must implement the MechanicalDriver port interface."""
        driver = MockMechanicalDriver()
        assert isinstance(driver, MechanicalDriver)

    def test_body_registration_and_query(self) -> None:
        """Mock driver allows registering bodies and querying their state."""
        driver = MockMechanicalDriver()
        driver.add_body(name="Spar_Solid", body_type="solid")
        driver.add_body(name="Skin_Surface", body_type="surface", thickness=2.0)

        bodies = driver.get_bodies()
        assert len(bodies) == 2
        body_names = [b["name"] if isinstance(b, dict) else b.name for b in bodies]
        assert "Spar_Solid" in body_names
        assert "Skin_Surface" in body_names

    def test_material_registration_and_assignment(self) -> None:
        """Mock driver registers materials and assigns them to bodies."""
        driver = MockMechanicalDriver()
        driver.add_body(name="Bulkhead", body_type="solid")

        driver.register_material("Steel_4130", {"elastic_modulus": 205000.0, "density": 7.85e-9})
        driver.assign_material("Bulkhead", "Steel_4130")

        assigned = driver.get_assigned_material("Bulkhead")
        assert assigned == "Steel_4130"

    def test_shell_thickness_assignment(self) -> None:
        """Mock driver sets and retrieves shell thicknesses."""
        driver = MockMechanicalDriver()
        driver.add_body(name="Skin_Panel", body_type="surface")
        driver.set_shell_thickness("Skin_Panel", 3.175)

        thk = driver.get_shell_thickness("Skin_Panel")
        assert thk == pytest.approx(3.175)

    def test_fault_injection_api(self) -> None:
        """Mock driver allows injecting corruptions to simulate downstream anomalies."""
        driver = MockMechanicalDriver()
        driver.add_body(name="Lug", body_type="solid")
        driver.assign_material("Lug", "Titanium_Ti6Al4V")

        driver.inject_material_error("Lug", "Corrupted_Plastic")
        assert driver.get_assigned_material("Lug") == "Corrupted_Plastic"

        driver.clear_faults()

    def test_driver_connection_lifecycle(self) -> None:
        """Mock driver supports connect and disconnect lifecycle."""
        driver = MockMechanicalDriver()
        assert driver.is_connected() is True
        driver.disconnect()
        assert driver.is_connected() is False
        driver.connect()
        assert driver.is_connected() is True

    def test_driver_body_properties_inspection(self) -> None:
        """Mock driver correctly queries body existence and individual properties."""
        driver = MockMechanicalDriver()
        driver.add_body(name="Spar", body_type="solid")
        assert driver.get_body_names() == ["Spar"]
        assert driver.has_body("Spar") is True
        assert driver.has_body("Nonexistent") is False

        props = driver.get_body_properties("Spar")
        assert props is not None
        assert props.name == "Spar"
        assert props.body_type == "solid"

        assert driver.get_body_properties("Nonexistent") is None

    def test_body_properties_dict_protocol(self) -> None:
        """BodyProperties provides dict-like access for backward compatibility."""
        props = BodyProperties(name="Rib", body_type="surface", thickness=1.5)
        assert props["name"] == "Rib"
        assert "thickness" in props
        assert "unknown" not in props
        assert props.get("thickness") == pytest.approx(1.5)
        assert props.get("missing_key", 42) == 42
        props["material_name"] = "Aluminum_2024"
        assert props.material_name == "Aluminum_2024"

    def test_driver_material_and_thickness_aliases(self) -> None:
        """Mock driver aliases for create_material and get_assigned_thickness function correctly."""
        driver = MockMechanicalDriver()
        driver.add_body("Panel", body_type="surface", thickness=2.0)
        driver.create_material("Al6061", {"density": 2.7e-9})
        assert "Al6061" in driver.list_materials()
        assert driver.get_assigned_thickness("Panel") == pytest.approx(2.0)

    def test_driver_named_selections(self) -> None:
        """Mock driver creates and lists named selections."""
        driver = MockMechanicalDriver()
        driver.create_named_selection("NS_HOLES", ["face_1", "face_2"])
        assert "NS_HOLES" in driver.get_named_selections()

    def test_driver_inject_body_variants(self) -> None:
        """Mock driver inject_body and inject_unmapped_body helpers register bodies."""
        driver = MockMechanicalDriver()
        driver.inject_body("Injected_Part", body_type="solid")
        assert driver.has_body("Injected_Part") is True
        driver.inject_unmapped_body("Unmapped_Extra", body_type="surface")
        assert driver.has_body("Unmapped_Extra") is True

        driver.assign_material("Injected_Part", "Steel")
        driver.inject_material_mismatch("Injected_Part", "Corrupted_Mat")
        assert driver.get_assigned_material("Injected_Part") == "Corrupted_Mat"

        driver.set_shell_thickness("Unmapped_Extra", 1.0)
        driver.inject_thickness_mismatch("Unmapped_Extra", 9.9)
        assert driver.get_shell_thickness("Unmapped_Extra") == pytest.approx(9.9)


# ===========================================================================
# 5. Step 6 Material Mapping Nominal Execution Coverage
# ===========================================================================


class TestStep06MaterialMappingFeatureCoverage:
    """Verifies nominal 4-phase execution of Step 6 on valid model and spec."""

    def test_step_attributes(self) -> None:
        """Step 6 must define step_id and descriptive metadata."""
        step = Step06MaterialMapping()
        assert step.step_id == "step_06_materials"
        assert len(step.description) > 0

    def test_pre_check_nominal(self, sample_run_context: RunContext) -> None:
        """Pre-check on a fully matched CAD model and valid spec passes cleanly."""
        step = Step06MaterialMapping()
        res = step.pre_check(sample_run_context)
        assert_check_passed(res)

    def test_execute_nominal(self, sample_run_context: RunContext) -> None:
        """Execute applies all materials and shell thicknesses without raising exceptions."""
        step = Step06MaterialMapping()
        # Run pre-check first
        pre_res = step.pre_check(sample_run_context)
        assert_check_passed(pre_res)

        # Run execute
        step.execute(sample_run_context)

        # Verify driver state directly
        driver = sample_run_context.driver
        assert driver.get_assigned_material("Bracket_Solid_Base") == "Structural_Steel"
        assert driver.get_assigned_material("Web_Plate_Upper") == "Aluminum_6061_T6"
        assert driver.get_shell_thickness("Web_Plate_Upper") == pytest.approx(2.5)
        assert driver.get_shell_thickness("Flange_Skin_Outer") == pytest.approx(1.25)

    def test_post_check_nominal(self, sample_run_context: RunContext) -> None:
        """Post-check validates that all assigned driver states match the input spec."""
        step = Step06MaterialMapping()
        step.pre_check(sample_run_context)
        step.execute(sample_run_context)

        post_res = step.post_check(sample_run_context)
        assert_check_passed(post_res)

    def test_pre_check_driver_disconnected(self, sample_run_context: RunContext) -> None:
        """Pre-check flags ERR_DRIVER_COMMUNICATION when driver connection is inactive."""
        step = Step06MaterialMapping()
        sample_run_context.driver.disconnect()
        res = step.pre_check(sample_run_context)
        assert_check_failed(res, expected_code=ERR_DRIVER_COMMUNICATION)
        assert res.failures[0].severity == Severity.BLOCKING
        sample_run_context.driver.connect()

    def test_post_check_unassigned_material(self, sample_run_context: RunContext) -> None:
        """Post-check flags ERR_MAT_UNASSIGNED_BODY if a body has no material assigned."""
        step = Step06MaterialMapping()
        step.pre_check(sample_run_context)
        step.execute(sample_run_context)

        # Clear material assignment for one body
        sample_run_context.driver._assigned_materials.pop("Bracket_Solid_Base", None)
        sample_run_context.driver._bodies["Bracket_Solid_Base"].material_name = None

        res = step.post_check(sample_run_context)
        assert_check_failed(res, expected_code=ERR_MAT_UNASSIGNED_BODY)

    def test_post_check_missing_shell_thickness(self, sample_run_context: RunContext) -> None:
        """Post-check flags ERR_MAT_THICKNESS_MISMATCH if a surface body has None thickness."""
        step = Step06MaterialMapping()
        step.pre_check(sample_run_context)
        step.execute(sample_run_context)

        # Clear thickness for Web_Plate_Upper
        sample_run_context.driver._shell_thicknesses["Web_Plate_Upper"] = None
        sample_run_context.driver._bodies["Web_Plate_Upper"].thickness = None

        res = step.post_check(sample_run_context)
        assert_check_failed(res, expected_code=ERR_MAT_THICKNESS_MISMATCH)

    def test_post_check_ignores_unmapped_cad_body(self, sample_run_context: RunContext) -> None:
        """Post-check safely ignores CAD bodies that have no JobSpec mapping."""
        step = Step06MaterialMapping()
        step.pre_check(sample_run_context)
        step.execute(sample_run_context)

        # Inject an extra body directly into driver (post-execution)
        sample_run_context.driver.add_body("Surprise_Datum_Body", body_type="solid")

        res = step.post_check(sample_run_context)
        assert_check_passed(res)

    def test_troubleshoot_produces_failure_objects(self, sample_run_context: RunContext) -> None:
        """Troubleshoot phase returns FailureObjects from check result."""
        step = Step06MaterialMapping()
        step.pre_check(sample_run_context)
        step.execute(sample_run_context)
        sample_run_context.driver.inject_material_error("Web_Plate_Upper", "Corrupted_Mat")
        res = step.post_check(sample_run_context)
        assert_check_failed(res)
        failures = step.troubleshoot(sample_run_context, res)
        assert len(failures) == len(res.failures)
        assert failures[0].component_or_entity == "Web_Plate_Upper"

    def test_pre_check_catches_non_positive_thickness_on_solid_body(
        self, sample_run_context: RunContext
    ) -> None:
        """Pre-check flags ERR_MAT_INVALID_THICKNESS if a solid body mapping has invalid thickness."""
        step = Step06MaterialMapping()
        sample_run_context.spec.materials.mappings["Bracket_Solid_Base"].thickness = -1.0
        res = step.pre_check(sample_run_context)
        assert_check_failed(res)
        assert any(f.error_code == "ERR_MAT_INVALID_THICKNESS" for f in res.failures)
        sample_run_context.spec.materials.mappings["Bracket_Solid_Base"].thickness = None

    def test_pre_check_catches_uncataloged_material_bypassing_schema(
        self, sample_run_context: RunContext
    ) -> None:
        """Pre-check flags ERR_MAT_MISSING_CATALOG if material name is missing from catalog."""
        step = Step06MaterialMapping()
        orig = sample_run_context.spec.materials.mappings["Bracket_Solid_Base"].material_name
        sample_run_context.spec.materials.mappings[
            "Bracket_Solid_Base"
        ].material_name = "Nonexistent_Mat"
        res = step.pre_check(sample_run_context)
        assert_check_failed(res)
        assert any(
            f.component_or_entity == "Bracket_Solid_Base" and "CATALOG" in f.error_code
            for f in res.failures
        )
        sample_run_context.spec.materials.mappings["Bracket_Solid_Base"].material_name = orig

"""
Meshtrix E2E Testing Infrastructure: Global Pytest Fixtures & Configuration.

Authoritative Reference: ORIGINAL_REQUEST.md & PROJECT.md
Architecture: Hexagonal (Ports & Adapters), Opaque-Box, Requirement-Driven.
"""

from typing import Any

import pytest

from meshtrix.core.step import RunContext
from meshtrix.diagnostics.failure import StepCheckResult
from meshtrix.drivers.mock import MockMechanicalDriver
from meshtrix.spec.job_spec import (
    JobSpec,
)


@pytest.fixture
def sample_materials_catalog_dict() -> dict[str, dict[str, Any]]:
    """Standard aerospace and structural materials catalog data."""
    return {
        "Structural_Steel": {
            "name": "Structural_Steel",
            "density": 7.85e-9,  # tonne / mm^3
            "elastic_modulus": 200000.0,  # MPa
            "poissons_ratio": 0.30,
            "yield_strength": 250.0,  # MPa
        },
        "Aluminum_6061_T6": {
            "name": "Aluminum_6061_T6",
            "density": 2.70e-9,  # tonne / mm^3
            "elastic_modulus": 68900.0,  # MPa
            "poissons_ratio": 0.33,
            "yield_strength": 276.0,  # MPa
        },
        "Titanium_Ti6Al4V": {
            "name": "Titanium_Ti6Al4V",
            "density": 4.43e-9,  # tonne / mm^3
            "elastic_modulus": 113800.0,  # MPa
            "poissons_ratio": 0.342,
            "yield_strength": 880.0,  # MPa
        },
    }


@pytest.fixture
def sample_body_mappings_dict() -> dict[str, dict[str, Any]]:
    """Sample body-to-material assignments mixing solid and surface/shell bodies."""
    return {
        "Bracket_Solid_Base": {
            "body_name": "Bracket_Solid_Base",
            "material_name": "Structural_Steel",
            "thickness": None,  # Solid body: no thickness
        },
        "Web_Plate_Upper": {
            "body_name": "Web_Plate_Upper",
            "material_name": "Aluminum_6061_T6",
            "thickness": 2.5,  # Surface body: 2.5 mm
        },
        "Flange_Skin_Outer": {
            "body_name": "Flange_Skin_Outer",
            "material_name": "Titanium_Ti6Al4V",
            "thickness": 1.25,  # Surface body: 1.25 mm
        },
    }


@pytest.fixture
def valid_job_spec_dict(
    sample_materials_catalog_dict: dict[str, dict[str, Any]],
    sample_body_mappings_dict: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """A complete valid JobSpec raw dictionary representation conforming to R2."""
    return {
        "job_id": "JOB-AERO-2026-001",
        "units": "Metric_mm",
        "analysis_type": "STRUCTURAL_STATIC",
        "materials": {
            "catalog": sample_materials_catalog_dict,
            "mappings": sample_body_mappings_dict,
        },
        "mesh": {
            "global_size": 5.0,
            "element_order": "quadratic",
            "min_quality": 0.25,
            "quality_metric": "skewness",
        },
        "tolerances": {
            "thickness_tolerance": 0.01,  # 1% or 0.01mm tolerance threshold
            "mass_tolerance": 0.05,
        },
        "mass_target": {
            "total_mass": 42.5,  # kg or tonnes depending on units
            "cg_x": 150.0,
            "cg_y": 75.0,
            "cg_z": 30.0,
        },
        "load_cases": [
            {
                "case_id": "LC1_Tension",
                "forces": [
                    {"selection": "NS_LUG_HOLE", "magnitude": 10000.0, "direction": [0.0, 1.0, 0.0]}
                ],
            }
        ],
        "supports": [
            {
                "selection": "NS_BASE_FACES",
                "type": "fixed",
            }
        ],
    }


@pytest.fixture
def valid_job_spec(valid_job_spec_dict: dict[str, Any]) -> JobSpec:
    """Instantiated and validated Pydantic JobSpec model."""
    return JobSpec.model_validate(valid_job_spec_dict)


@pytest.fixture
def sample_cad_bodies() -> list[dict[str, Any]]:
    """Authoritative representation of CAD model bodies before material assignment."""
    return [
        {"name": "Bracket_Solid_Base", "body_type": "solid", "initial_thickness": None},
        {"name": "Web_Plate_Upper", "body_type": "surface", "initial_thickness": None},
        {"name": "Flange_Skin_Outer", "body_type": "surface", "initial_thickness": None},
    ]


@pytest.fixture
def mock_driver(sample_cad_bodies: list[dict[str, Any]]) -> MockMechanicalDriver:
    """Pre-populated MockMechanicalDriver instance adhering to driver port interface."""
    driver = MockMechanicalDriver()
    for body in sample_cad_bodies:
        driver.add_body(
            name=body["name"],
            body_type=body["body_type"],
            thickness=body["initial_thickness"],
        )
    return driver


@pytest.fixture
def sample_run_context(valid_job_spec: JobSpec, mock_driver: MockMechanicalDriver) -> RunContext:
    """RunContext dependency container populated with spec, driver, and metadata."""
    return RunContext(spec=valid_job_spec, driver=mock_driver, metadata={"env": "test_harness"})


@pytest.fixture
def aerospace_assembly_spec_dict() -> dict[str, Any]:
    """Realistic aerospace subassembly with multi-material and mixed shell/solid bodies."""
    return {
        "job_id": "JOB-AERO-WING-BOX-004",
        "units": "Metric_mm",
        "analysis_type": "STRUCTURAL_STATIC",
        "materials": {
            "catalog": {
                "Aluminum_2024_T3": {
                    "name": "Aluminum_2024_T3",
                    "density": 2.78e-9,  # tonne / mm^3
                    "elastic_modulus": 73100.0,  # MPa
                    "poissons_ratio": 0.33,
                    "yield_strength": 345.0,  # MPa
                },
                "Aluminum_7075_T6": {
                    "name": "Aluminum_7075_T6",
                    "density": 2.81e-9,
                    "elastic_modulus": 71700.0,
                    "poissons_ratio": 0.33,
                    "yield_strength": 503.0,
                },
                "Titanium_Ti6Al4V": {
                    "name": "Titanium_Ti6Al4V",
                    "density": 4.43e-9,
                    "elastic_modulus": 113800.0,
                    "poissons_ratio": 0.342,
                    "yield_strength": 880.0,
                },
                "Structural_Steel_4340": {
                    "name": "Structural_Steel_4340",
                    "density": 7.85e-9,
                    "elastic_modulus": 205000.0,
                    "poissons_ratio": 0.29,
                    "yield_strength": 470.0,
                },
                "Stainless_Steel_316": {
                    "name": "Stainless_Steel_316",
                    "density": 8.00e-9,
                    "elastic_modulus": 193000.0,
                    "poissons_ratio": 0.30,
                    "yield_strength": 290.0,
                },
            },
            "mappings": {
                "Fuselage_Skin_Panel_01": {
                    "body_name": "Fuselage_Skin_Panel_01",
                    "material_name": "Aluminum_2024_T3",
                    "thickness": 1.6,  # 1.6 mm sheet
                },
                "Fuselage_Skin_Panel_02": {
                    "body_name": "Fuselage_Skin_Panel_02",
                    "material_name": "Aluminum_2024_T3",
                    "thickness": 2.0,  # 2.0 mm sheet
                },
                "Frame_Rib_01": {
                    "body_name": "Frame_Rib_01",
                    "material_name": "Titanium_Ti6Al4V",
                    "thickness": 3.2,  # 3.2 mm milled rib
                },
                "Mount_Bracket_Solid": {
                    "body_name": "Mount_Bracket_Solid",
                    "material_name": "Structural_Steel_4340",
                    "thickness": None,  # Solid machined lug
                },
                "Support_Gusset": {
                    "body_name": "Support_Gusset",
                    "material_name": "Aluminum_7075_T6",
                    "thickness": 2.5,  # 2.5 mm reinforcement
                },
                "Retainer_Bolt_Cluster": {
                    "body_name": "Retainer_Bolt_Cluster",
                    "material_name": "Stainless_Steel_316",
                    "thickness": None,  # Solid hardware representation
                },
            },
        },
        "mesh": {
            "global_size": 4.0,
            "element_order": "quadratic",
            "min_quality": 0.25,
            "quality_metric": "skewness",
        },
        "tolerances": {
            "thickness_tolerance": 0.001,  # 1 um tight tolerance
            "mass_tolerance": 0.01,
        },
        "mass_target": {
            "total_mass": 28.65,
            "cg_x": 350.0,
            "cg_y": 120.0,
            "cg_z": 45.0,
        },
        "load_cases": [
            {
                "case_id": "LC_Limit_Maneuver_2_5G",
                "forces": [
                    {
                        "selection": "NS_LUG_PRIMARY",
                        "magnitude": 25000.0,
                        "direction": [0.0, 0.0, 1.0],
                    }
                ],
            }
        ],
        "supports": [
            {
                "selection": "NS_FUSELAGE_FRAME_MOUNT",
                "type": "fixed",
            }
        ],
    }


@pytest.fixture
def populated_aerospace_driver() -> MockMechanicalDriver:
    """Pre-loaded MockMechanicalDriver representing imported SpaceClaim geometry."""
    driver = MockMechanicalDriver()
    driver.add_body(name="Fuselage_Skin_Panel_01", body_type="surface")
    driver.add_body(name="Fuselage_Skin_Panel_02", body_type="surface")
    driver.add_body(name="Frame_Rib_01", body_type="surface")
    driver.add_body(name="Mount_Bracket_Solid", body_type="solid")
    driver.add_body(name="Support_Gusset", body_type="surface")
    driver.add_body(name="Retainer_Bolt_Cluster", body_type="solid")
    return driver


# ---------------------------------------------------------------------------
# Test Verification Helpers
# ---------------------------------------------------------------------------


def assert_check_passed(result: StepCheckResult) -> None:
    """Assert that a StepCheckResult indicates clean pass with zero blocking failures."""
    passed = getattr(result, "passed", getattr(result, "is_successful", True))
    assert passed is True, f"Expected step check to pass, but failed with: {result.failures}"
    assert len(result.failures) == 0, f"Expected zero failures, found: {result.failures}"


def assert_check_failed(result: StepCheckResult, expected_code: str | None = None) -> None:
    """Assert that a StepCheckResult indicates failure with optional error_code check."""
    passed = getattr(result, "passed", getattr(result, "is_successful", False))
    assert passed is False, "Expected step check to fail, but it passed."
    assert len(result.failures) > 0, "Expected at least one FailureObject in result.failures."

    if expected_code:
        matching = [f for f in result.failures if f.error_code == expected_code]
        assert len(matching) > 0, (
            f"Expected error code '{expected_code}' among failures, "
            f"got: {[f.error_code for f in result.failures]}"
        )

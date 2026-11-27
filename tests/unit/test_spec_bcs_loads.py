"""
Unit tests for M1 JobSpec BC/Load extensions and Diagnostic error codes.
"""

from typing import Any

import pytest
from pydantic import ValidationError

from meshtrix import diagnostics
from meshtrix.diagnostics import failure
from meshtrix.spec import (
    AccelerationSpec,
    CheckTolerances,
    JobSpec,
    LoadCase,
    LoadSpec,
    LoadType,
    SupportSpec,
    SupportType,
)


class TestSupportSpecExtensions:
    """Tests for SupportSpec backward compatibility, DOF resolution, and validation."""

    def test_backward_compatible_minimal_support(self, valid_job_spec: JobSpec) -> None:
        sup = SupportSpec.model_validate({"selection": "NS_BASE", "type": "fixed"})
        assert sup.selection == "NS_BASE"
        assert sup.type == SupportType.FIXED
        assert sup.dofs is None
        assert sup.displacement_values is None
        assert sup.coordinate_system == "Global"
        assert sup.name is None
        assert len(valid_job_spec.supports) == 1
        assert valid_job_spec.supports[0].resolved_dofs() == ["UX", "UY", "UZ", "RX", "RY", "RZ"]

    def test_resolved_dofs_defaults_by_support_type(self) -> None:
        assert SupportSpec(selection="NS1", type="fixed").resolved_dofs() == [
            "UX",
            "UY",
            "UZ",
            "RX",
            "RY",
            "RZ",
        ]
        assert SupportSpec(selection="NS1", type="pinned").resolved_dofs() == ["UX", "UY", "UZ"]
        assert SupportSpec(selection="NS1", type="frictionless").resolved_dofs() == ["NORMAL"]
        assert SupportSpec(selection="NS1", type="displacement").resolved_dofs() == [
            "UX",
            "UY",
            "UZ",
        ]
        disp_with_vals = SupportSpec(
            selection="NS1",
            type="displacement",
            displacement_values={"ux": 0.0, "rz": 0.05},
        )
        assert disp_with_vals.resolved_dofs() == ["UX", "RZ"]

    def test_case_insensitive_support_type_normalization(self) -> None:
        assert SupportSpec(selection="NS1", type="FIXED").type == SupportType.FIXED
        assert SupportSpec(selection="NS1", type="Pinned").type == SupportType.PINNED
        assert SupportSpec(selection="NS1", type="Frictionless").type == SupportType.FRICTIONLESS
        assert SupportSpec(selection="NS1", type="DISPLACEMENT").type == SupportType.DISPLACEMENT

    def test_unknown_support_type_kept_for_step_precheck(self) -> None:
        sup = SupportSpec(selection="", type="custom_support")
        assert sup.selection == ""
        assert sup.type == "custom_support"
        assert sup.resolved_dofs() == []

    def test_explicit_dofs_normalization_and_deduplication(self) -> None:
        sup = SupportSpec(selection="NS1", type="displacement", dofs=[" ux ", "UX", "uy", "rz"])
        assert sup.dofs == ["UX", "UY", "RZ"]
        assert sup.resolved_dofs() == ["UX", "UY", "RZ"]

    @pytest.mark.parametrize("bad_dofs", [[], ["TX"], ["U1"], ["ROT_X"], [""]])
    def test_invalid_dofs_rejected(self, bad_dofs: list[str]) -> None:
        with pytest.raises(ValidationError):
            SupportSpec(selection="NS1", dofs=bad_dofs)

    def test_displacement_values_validation_and_consistency(self) -> None:
        sup = SupportSpec(
            selection="NS1",
            type="displacement",
            dofs=["UX", "UY"],
            displacement_values={" ux ": 1.5, "UY": 0.0},
            coordinate_system="Cylindrical_CS",
            name="Pin_Displacement",
        )
        assert sup.displacement_values == {"UX": 1.5, "UY": 0.0}
        assert sup.coordinate_system == "Cylindrical_CS"
        assert sup.name == "Pin_Displacement"

        with pytest.raises(ValidationError):
            SupportSpec(selection="NS1", displacement_values={"TX": 1.0})

        with pytest.raises(ValidationError):
            SupportSpec(selection="NS1", displacement_values={"ux": 0.0, "UX": 1.0})

        with pytest.raises(ValidationError):
            SupportSpec(selection="NS1", displacement_values={"UX": float("nan")})

        with pytest.raises(ValidationError):
            SupportSpec(selection="NS1", displacement_values={"UX": float("inf")})

        with pytest.raises(ValidationError):
            SupportSpec.model_validate({"selection": "NS1", "displacement_values": {"UX": True}})

        with pytest.raises(ValidationError):
            SupportSpec(
                selection="NS1",
                type="displacement",
                dofs=["UX"],
                displacement_values={"UX": 0.0, "UY": 1.0},
            )


class TestLoadSpecAndAccelerationSpec:
    """Tests for LoadSpec and AccelerationSpec validation rules."""

    def test_load_spec_defaults_and_negative_values_allowed(self) -> None:
        load = LoadSpec(selection="NS_LUG", magnitude=-1500.0, direction=[-1.0, 0.0, 0.0])
        assert load.magnitude == -1500.0
        assert load.direction == [-1.0, 0.0, 0.0]
        assert load.load_type == LoadType.FORCE
        assert load.coordinate_system == "Global"
        assert load.name is None

        zero_load = LoadSpec(
            selection="NS_LUG",
            magnitude=0.0,
            direction=[0.0, 0.0, 0.0],
            load_type="PRESSURE",
            coordinate_system="Local_CS",
            name="ZeroPressure",
        )
        assert zero_load.load_type == LoadType.PRESSURE
        assert zero_load.coordinate_system == "Local_CS"
        assert zero_load.name == "ZeroPressure"

    @pytest.mark.parametrize("bad_mag", [float("nan"), float("inf"), float("-inf"), True, False])
    def test_load_spec_rejects_non_finite_and_bool_magnitude(self, bad_mag: Any) -> None:
        with pytest.raises(ValidationError):
            LoadSpec.model_validate({"selection": "NS_LUG", "magnitude": bad_mag})

    @pytest.mark.parametrize(
        "bad_dir",
        [
            [],
            [1.0, 0.0],
            [1.0, 0.0, 0.0, 0.0],
            [0.0, 0.0, 0.0],
            [float("nan"), 0.0, 1.0],
            [float("inf"), 0.0, 0.0],
            [True, 0.0, 0.0],
        ],
    )
    def test_load_spec_rejects_invalid_direction(self, bad_dir: list[Any]) -> None:
        with pytest.raises(ValidationError):
            LoadSpec.model_validate(
                {"selection": "NS_LUG", "magnitude": 100.0, "direction": bad_dir}
            )

    def test_acceleration_spec_defaults_and_validation(self) -> None:
        acc = AccelerationSpec(magnitude=9810.0)
        assert acc.magnitude == 9810.0
        assert acc.direction == [0.0, 0.0, -1.0]
        assert acc.selection is None
        assert acc.coordinate_system == "Global"
        assert acc.name is None
        assert acc.load_type == LoadType.ACCELERATION

        scoped_acc = AccelerationSpec(
            magnitude=-24525.0,
            direction=[0.0, -1.0, 0.0],
            selection="NS_WING_MASS",
            coordinate_system="Aircraft_Body_CS",
            name="Maneuver_2_5G",
        )
        assert scoped_acc.selection == "NS_WING_MASS"
        assert scoped_acc.magnitude == -24525.0

        with pytest.raises(ValidationError):
            AccelerationSpec.model_validate({"magnitude": True})

        with pytest.raises(ValidationError):
            AccelerationSpec(magnitude=9810.0, direction=[0.0, 0.0, 0.0])

        with pytest.raises(ValidationError):
            AccelerationSpec(magnitude=9810.0, direction=[1.0, 0.0])


class TestLoadCaseCheckTolerancesAndJobSpecVersion:
    """Tests for LoadCase, CheckTolerances, and JobSpec version fields."""

    def test_load_case_extensions_and_validation(self) -> None:
        lc = LoadCase(
            case_id="LC_ACCEL",
            accelerations=[AccelerationSpec(magnitude=9810.0)],
            step_number=2,
            description="2.5G pull-up maneuver",
        )
        assert len(lc.accelerations) == 1
        assert lc.step_number == 2
        assert lc.description == "2.5G pull-up maneuver"

        with pytest.raises(ValidationError):
            LoadCase(case_id="LC_BAD", step_number=0)

        with pytest.raises(ValidationError):
            LoadCase.model_validate({"case_id": "LC_BAD", "step_number": True})

    def test_check_tolerances_defaults_and_validation(self) -> None:
        tol = CheckTolerances()
        assert tol.load_tolerance == 0.01
        assert tol.direction_tolerance == 1e-4

        for bad_val in [0.0, -0.01, float("nan"), float("inf"), True, False]:
            with pytest.raises(ValidationError):
                CheckTolerances.model_validate({"load_tolerance": bad_val})
            with pytest.raises(ValidationError):
                CheckTolerances.model_validate({"direction_tolerance": bad_val})

    def test_job_spec_version_round_trip(self, valid_job_spec_dict: dict[str, Any]) -> None:
        spec_default = JobSpec.from_dict(valid_job_spec_dict)
        assert spec_default.spec_version == "1.0"

        custom_dict = dict(valid_job_spec_dict)
        custom_dict["spec_version"] = "2.0"
        spec_custom = JobSpec.from_dict(custom_dict)
        assert spec_custom.spec_version == "2.0"

        round_tripped_dict = JobSpec.from_dict(spec_custom.to_dict())
        assert round_tripped_dict.spec_version == "2.0"

        round_tripped_yaml = JobSpec.from_yaml(spec_custom.to_yaml())
        assert round_tripped_yaml.spec_version == "2.0"


class TestDiagnosticBcAndLoadCodes:
    """Tests for ERR_BC_* and ERR_LOAD_* diagnostic error code exports."""

    EXPECTED_CODES = (
        "ERR_BC_MISSING_SELECTION",
        "ERR_BC_EMPTY_SELECTION",
        "ERR_BC_MISSING_SUPPORT",
        "ERR_BC_SCOPING_MISMATCH",
        "ERR_BC_DOF_MISMATCH",
        "ERR_BC_COORDINATE_SYSTEM_MISMATCH",
        "ERR_BC_INVALID_SPEC",
        "ERR_LOAD_MISSING_SELECTION",
        "ERR_LOAD_EMPTY_SELECTION",
        "ERR_LOAD_MISSING_LOAD",
        "ERR_LOAD_TOTAL_MISMATCH",
        "ERR_LOAD_DIRECTION_MISMATCH",
        "ERR_LOAD_SIGN_MISMATCH",
        "ERR_LOAD_COORDINATE_SYSTEM_MISMATCH",
        "ERR_LOAD_INVALID_SPEC",
    )

    @pytest.mark.parametrize("code_name", EXPECTED_CODES)
    def test_diagnostic_code_exported_and_consistent(self, code_name: str) -> None:
        assert getattr(failure, code_name) == code_name
        assert getattr(diagnostics, code_name) == code_name
        assert code_name in diagnostics.__all__

"""
Unit tests for M1 Driver BC/Load Port, MockMechanicalDriver, Fault Injection, and State.
"""

import json
from dataclasses import asdict
from typing import Any

from meshtrix import drivers
from meshtrix.core.step import RunContext
from meshtrix.drivers import (
    LoadRecord,
    MechanicalDriver,
    MockMechanicalDriver,
    SupportRecord,
)
from meshtrix.spec.job_spec import JobSpec
from meshtrix.steps.step_06_materials import Step06MaterialMapping
from meshtrix.steps.step_08_meshing import Step08Meshing


class TestDriverRecordsAndPort:
    """Verify SupportRecord, LoadRecord, and MechanicalDriver port exports."""

    def test_mock_driver_conforms_to_port_and_exports(self) -> None:
        driver = MockMechanicalDriver()
        assert isinstance(driver, MechanicalDriver)
        assert "LoadRecord" in drivers.__all__
        assert "SupportRecord" in drivers.__all__

    def test_records_serialization_and_positional_construction(self) -> None:
        sup = SupportRecord(
            "BaseSupport",
            "NS_BASE_FACES",
            "displacement",
            ["UX", "UY"],
            "Local_CS",
            {"UX": 0.0, "UY": 1.5},
        )
        sup_dict = sup.to_dict()
        assert sup_dict == asdict(sup)
        assert json.loads(json.dumps(sup_dict)) == sup_dict

        load = LoadRecord(
            "LC1",
            "force",
            "NS_LUG",
            10000.0,
            [0.0, 1.0, 0.0],
            "Global",
            "LugTension",
        )
        load_dict = load.to_dict()
        assert load_dict == asdict(load)
        assert json.loads(json.dumps(load_dict)) == load_dict


class TestMockDriverNamedSelections:
    """Verify named selection creation, entity queries, fault injection, and restoration."""

    def test_named_selection_queries_and_defensive_copies(self) -> None:
        driver = MockMechanicalDriver()
        driver.create_named_selection("NS_BASE", ["Face_1", "Face_2"])

        assert driver.has_named_selection("NS_BASE") is True
        assert driver.has_named_selection("NS_UNKNOWN") is False
        assert "NS_BASE" in driver.get_named_selections()

        entities = driver.get_named_selection_entities("NS_BASE")
        assert entities == ["Face_1", "Face_2"]
        entities.append("Mutated")
        assert driver.get_named_selection_entities("NS_BASE") == ["Face_1", "Face_2"]
        assert driver.get_named_selection_entities("NS_UNKNOWN") == []

    def test_named_selection_faults_and_clear_faults(self) -> None:
        driver = MockMechanicalDriver()
        driver.create_named_selection("NS_BASE", ["Face_1", "Face_2"])
        driver.create_named_selection("NS_LOAD", ["Edge_1"])

        driver.inject_empty_named_selection("NS_BASE")
        assert driver.has_named_selection("NS_BASE") is True
        assert driver.get_named_selection_entities("NS_BASE") == []

        driver.inject_missing_named_selection("NS_LOAD")
        assert driver.has_named_selection("NS_LOAD") is False
        assert driver.get_named_selection_entities("NS_LOAD") == []

        driver.inject_empty_named_selection("NS_PHANTOM")
        assert driver.has_named_selection("NS_PHANTOM") is True

        driver.clear_faults()
        assert driver.has_named_selection("NS_BASE") is True
        assert driver.get_named_selection_entities("NS_BASE") == ["Face_1", "Face_2"]
        assert driver.has_named_selection("NS_LOAD") is True
        assert driver.get_named_selection_entities("NS_LOAD") == ["Edge_1"]
        assert driver.has_named_selection("NS_PHANTOM") is False


class TestMockDriverSupportsAndFaults:
    """Verify support application, DOF defaults, faults, and clear_faults restoration."""

    def test_apply_support_defaults_and_idempotency(self) -> None:
        driver = MockMechanicalDriver()

        fixed = driver.apply_support("NS_BASE", support_type="fixed")
        assert fixed.dofs == ["UX", "UY", "UZ", "RX", "RY", "RZ"]
        assert fixed.name == "Support_1_NS_BASE"

        pinned = driver.apply_support("NS_PIN", support_type="pinned")
        assert pinned.dofs == ["UX", "UY", "UZ"]

        frictionless = driver.apply_support("NS_SYM", support_type="frictionless")
        assert frictionless.dofs == ["NORMAL"]

        disp = driver.apply_support(
            "NS_DISP",
            support_type="displacement",
            displacement_values={"ux": 0.0, "rz": 0.1},
            coordinate_system="Cylindrical_CS",
            name="NamedDisp",
        )
        assert disp.dofs == ["UX", "RZ"]
        assert disp.displacement_values == {"UX": 0.0, "RZ": 0.1}
        assert disp.coordinate_system == "Cylindrical_CS"

        # Explicit name updates in place
        updated = driver.apply_support(
            "NS_DISP",
            support_type="displacement",
            dofs=["ux", "uy", "ux"],
            name="NamedDisp",
        )
        assert updated.dofs == ["UX", "UY"]
        assert len(driver.get_supports()) == 4

        # Defensive copy from get_supports
        supports = driver.get_supports()
        supports[0].dofs.clear()
        assert driver.get_supports()[0].dofs == ["UX", "UY", "UZ", "RX", "RY", "RZ"]

    def test_support_fault_injections_and_clear_faults(self) -> None:
        driver = MockMechanicalDriver()
        driver.apply_support("NS_BASE", support_type="fixed", name="BaseFixed")
        driver.apply_support("NS_PIN", support_type="pinned", name="PinSupport")

        driver.inject_support_scoping_error("BaseFixed", "NS_WRONG")
        driver.inject_support_dof_error("NS_PIN", ["ux"])
        driver.inject_support_coordinate_system_error("BaseFixed", "Local_99")

        live = {s.name: s for s in driver.get_supports()}
        assert live["BaseFixed"].selection == "NS_WRONG"
        assert live["BaseFixed"].coordinate_system == "Local_99"
        assert live["PinSupport"].dofs == ["UX"]

        driver.inject_missing_support("PinSupport")
        assert [s.name for s in driver.get_supports()] == ["BaseFixed"]

        driver.clear_faults()
        restored = {s.name: s for s in driver.get_supports()}
        assert restored["BaseFixed"].selection == "NS_BASE"
        assert restored["BaseFixed"].coordinate_system == "Global"
        assert restored["PinSupport"].dofs == ["UX", "UY", "UZ"]


class TestMockDriverLoadsAndFaults:
    """Verify force, pressure, acceleration APIs, fault injections, and clear_faults."""

    def test_apply_loads_and_filtering(self) -> None:
        driver = MockMechanicalDriver()

        f1 = driver.apply_force("LC1", "NS_LUG", 10000.0, [0.0, 1.0, 0.0], name="LugForce")
        p1 = driver.apply_pressure("LC1", "NS_SKIN", 0.25, name="CabinPressure")
        a1 = driver.apply_acceleration("LC2", 9810.0, [0.0, 0.0, -1.0], name="Gravity")
        a2 = driver.apply_acceleration("LC2", 0.0, [1.0, 0.0, 0.0], selection="NS_WING")

        assert f1.load_type == "force"
        assert p1.load_type == "pressure"
        assert p1.direction == [0.0, 0.0, 1.0]
        assert a1.load_type == "acceleration"
        assert a1.selection is None
        assert a2.selection == "NS_WING"

        assert len(driver.get_loads()) == 4
        assert len(driver.get_loads(case_id="LC1")) == 2
        assert len(driver.get_loads(case_id="LC2")) == 2
        assert driver.get_loads(case_id="NONEXISTENT") == []

    def test_load_fault_injections_and_clear_faults(self) -> None:
        driver = MockMechanicalDriver()
        driver.apply_force("LC1", "NS_LUG", 10000.0, [0.0, 1.0, 0.0], name="LugForce")
        driver.apply_pressure("LC1", "NS_SKIN", 2.5, name="SkinPressure")
        driver.apply_acceleration("LC2", 0.0, [0.0, 0.0, -1.0], name="ZeroAccel")

        driver.inject_load_magnitude_error("LugForce", 5000.0, case_id="LC1")
        driver.inject_load_direction_error("LugForce", [1.0, 0.0, 0.0], case_id="LC1")
        driver.inject_load_coordinate_system_error("LugForce", "Wrong_CS", case_id="LC1")
        driver.inject_load_sign_error("SkinPressure", case_id="LC1")
        driver.inject_load_sign_error("ZeroAccel", case_id="LC2")

        lc1 = {ld.name: ld for ld in driver.get_loads(case_id="LC1")}
        assert lc1["LugForce"].magnitude == 5000.0
        assert lc1["LugForce"].direction == [1.0, 0.0, 0.0]
        assert lc1["LugForce"].coordinate_system == "Wrong_CS"
        assert lc1["SkinPressure"].magnitude == -2.5

        lc2 = {ld.name: ld for ld in driver.get_loads(case_id="LC2")}
        assert lc2["ZeroAccel"].direction == [-0.0, -0.0, 1.0]

        driver.inject_missing_load("SkinPressure", case_id="LC1")
        assert len(driver.get_loads(case_id="LC1")) == 1

        driver.clear_faults()
        restored_lc1 = {ld.name: ld for ld in driver.get_loads(case_id="LC1")}
        assert restored_lc1["LugForce"].magnitude == 10000.0
        assert restored_lc1["LugForce"].direction == [0.0, 1.0, 0.0]
        assert restored_lc1["LugForce"].coordinate_system == "Global"
        assert restored_lc1["SkinPressure"].magnitude == 2.5
        restored_lc2 = {ld.name: ld for ld in driver.get_loads(case_id="LC2")}
        assert restored_lc2["ZeroAccel"].direction == [0.0, 0.0, -1.0]


class TestMockDriverStateAndSeeding:
    """Verify export_state, import_state, and seed_from_spec behavior."""

    def test_export_and_import_state_json_safe_round_trip(
        self, valid_job_spec: JobSpec, mock_driver: MockMechanicalDriver
    ) -> None:
        mock_driver.create_named_selection("NS_BASE_FACES", ["Face_1"])
        mock_driver.create_named_selection("NS_LUG_HOLE", ["Face_2"])

        ctx = RunContext(spec=valid_job_spec, driver=mock_driver)
        step6 = Step06MaterialMapping()
        assert step6.pre_check(ctx).is_successful is True
        step6.execute(ctx)
        assert step6.post_check(ctx).is_successful is True

        step8 = Step08Meshing()
        assert step8.pre_check(ctx).is_successful is True
        step8.execute(ctx)
        assert step8.post_check(ctx).is_successful is True

        mock_driver.apply_support("NS_BASE_FACES", support_type="fixed", name="BaseFix")
        mock_driver.apply_force("LC1_Tension", "NS_LUG_HOLE", 10000.0, [0.0, 1.0, 0.0], name="F1")

        exported = mock_driver.export_state()
        serialized = json.dumps(exported)
        rehydrated_dict: dict[str, Any] = json.loads(serialized)

        fresh = MockMechanicalDriver()
        fresh.import_state(rehydrated_dict)

        assert fresh.get_body_names() == mock_driver.get_body_names()
        assert fresh.get_assigned_material("Bracket_Solid_Base") == "Structural_Steel"
        assert fresh.get_shell_thickness("Web_Plate_Upper") == 2.5
        assert fresh.is_mesh_generated() is True
        assert fresh.get_element_count() == mock_driver.get_element_count()
        assert fresh.get_named_selection_entities("NS_BASE_FACES") == ["Face_1"]
        assert [s.name for s in fresh.get_supports()] == ["BaseFix"]
        assert [ld.name for ld in fresh.get_loads()] == ["F1"]

        # Verify nominal snapshots survive round trip and clear_faults restores them
        fresh.inject_missing_support("BaseFix")
        fresh.inject_load_sign_error("F1")
        fresh.clear_faults()
        assert [s.name for s in fresh.get_supports()] == ["BaseFix"]
        assert fresh.get_loads()[0].magnitude == 10000.0

    def test_import_partial_mock_state_supports_body_list(self) -> None:
        partial_state: dict[str, Any] = {
            "bodies": [
                {"name": "Panel_A", "body_type": "surface"},
                {"name": "Block_B", "body_type": "solid"},
            ],
            "named_selections": {"NS_EDGE": ["E1", "E2"]},
        }
        driver = MockMechanicalDriver()
        driver.import_state(partial_state)

        assert driver.get_body_names() == ["Panel_A", "Block_B"]
        assert driver.has_named_selection("NS_EDGE") is True
        driver.inject_empty_named_selection("NS_EDGE")
        driver.clear_faults()
        assert driver.get_named_selection_entities("NS_EDGE") == ["E1", "E2"]

    def test_seed_from_spec_idempotent_and_executes_steps(
        self, valid_job_spec: JobSpec, aerospace_assembly_spec_dict: dict[str, Any]
    ) -> None:
        driver = MockMechanicalDriver()
        driver.create_named_selection("NS_BASE_FACES", ["Custom_Base_Face"])

        driver.seed_from_spec(valid_job_spec)
        driver.seed_from_spec(valid_job_spec)  # idempotent second call

        assert set(driver.get_body_names()) == {
            "Bracket_Solid_Base",
            "Web_Plate_Upper",
            "Flange_Skin_Outer",
        }
        body_types = {b.name: b.body_type for b in driver.get_bodies()}
        assert body_types["Bracket_Solid_Base"] == "solid"
        assert body_types["Web_Plate_Upper"] == "surface"
        assert body_types["Flange_Skin_Outer"] == "surface"

        # Pre-existing NS preserved; missing NS seeded non-empty
        assert driver.get_named_selection_entities("NS_BASE_FACES") == ["Custom_Base_Face"]
        assert driver.has_named_selection("NS_LUG_HOLE") is True
        assert len(driver.get_named_selection_entities("NS_LUG_HOLE")) > 0

        # Materials, supports, and loads remain unapplied for pipeline steps
        assert driver.get_assigned_material("Bracket_Solid_Base") is None
        assert driver.get_supports() == []
        assert driver.get_loads() == []

        # Steps 6 & 8 pass cleanly on seeded driver
        ctx = RunContext(spec=valid_job_spec, driver=driver)
        step6 = Step06MaterialMapping()
        assert step6.pre_check(ctx).is_successful is True
        step6.execute(ctx)
        assert step6.post_check(ctx).is_successful is True

        step8 = Step08Meshing()
        assert step8.pre_check(ctx).is_successful is True
        step8.execute(ctx)
        assert step8.post_check(ctx).is_successful is True

        # Also verify aerospace spec with accelerations
        aero_dict = dict(aerospace_assembly_spec_dict)
        aero_dict["load_cases"][0]["accelerations"] = [
            {"magnitude": 24525.0, "direction": [0.0, 0.0, -1.0], "selection": "NS_AERO_MASS"}
        ]
        aero_spec = JobSpec.from_dict(aero_dict)
        aero_driver = MockMechanicalDriver()
        aero_driver.seed_from_spec(aero_spec)
        assert aero_driver.has_named_selection("NS_AERO_MASS") is True
        assert aero_driver.has_named_selection("NS_LUG_PRIMARY") is True
        assert aero_driver.has_named_selection("NS_FUSELAGE_FRAME_MOUNT") is True

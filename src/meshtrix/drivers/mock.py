"""
Meshtrix In-Memory Mock Driver for Zero-License Offline Execution.

Authoritative Reference: ORIGINAL_REQUEST.md §R2 & PROJECT.md
"""

from typing import Any

from meshtrix.drivers.base import BodyProperties, MechanicalDriver


class MockMechanicalDriver(MechanicalDriver):
    """Zero-license offline simulation engine implementing MechanicalDriver port."""

    def __init__(self) -> None:
        self._connected: bool = True
        self._bodies: dict[str, BodyProperties] = {}
        self._materials: dict[str, Any] = {}
        self._assigned_materials: dict[str, str] = {}
        self._shell_thicknesses: dict[str, float | None] = {}
        self._nominal_assigned_materials: dict[str, str] = {}
        self._nominal_shell_thicknesses: dict[str, float | None] = {}
        self._named_selections: dict[str, list[str]] = {}

    def connect(self) -> None:
        """Establish solver connection."""
        self._connected = True

    def disconnect(self) -> None:
        """Terminate solver connection."""
        self._connected = False

    def is_connected(self) -> bool:
        """Query connection state."""
        return self._connected

    def add_body(self, name: str, body_type: str = "solid", thickness: float | None = None) -> None:
        """Add a CAD body representation to the in-memory model."""
        body = BodyProperties(name=name, body_type=body_type, thickness=thickness)
        self._bodies[name] = body
        self._shell_thicknesses[name] = thickness
        self._nominal_shell_thicknesses[name] = thickness

    def get_bodies(self) -> list[BodyProperties]:
        """Retrieve all CAD bodies reflecting their current assignment state."""
        result: list[BodyProperties] = []
        for name, body in self._bodies.items():
            assigned_mat = self._assigned_materials.get(name, body.material_name)
            assigned_thk = self._shell_thicknesses.get(name, body.thickness)
            result.append(
                BodyProperties(
                    name=body.name,
                    body_type=body.body_type,
                    material_name=assigned_mat,
                    thickness=assigned_thk,
                    offset_type=body.offset_type,
                )
            )
        return result

    def get_body_names(self) -> list[str]:
        """Retrieve list of body names."""
        return list(self._bodies.keys())

    def get_body_properties(self, body_name: str) -> BodyProperties | None:
        """Retrieve properties for a specific body."""
        body = self._bodies.get(body_name)
        if body is None:
            return None
        assigned_mat = self._assigned_materials.get(body_name, body.material_name)
        assigned_thk = self._shell_thicknesses.get(body_name, body.thickness)
        return BodyProperties(
            name=body.name,
            body_type=body.body_type,
            material_name=assigned_mat,
            thickness=assigned_thk,
            offset_type=body.offset_type,
        )

    def has_body(self, body_name: str) -> bool:
        """Check whether a body exists in the model."""
        return body_name in self._bodies

    def register_material(self, name: str, properties: Any) -> None:
        """Register a material definition in the material catalog."""
        self._materials[name] = properties

    def create_material(self, name: str, properties: Any) -> None:
        """Alias for register_material."""
        self.register_material(name, properties)

    def list_materials(self) -> list[str]:
        """List names of all registered materials."""
        return list(self._materials.keys())

    def assign_material(self, body_name: str, material_name: str) -> None:
        """Assign a registered material to a body."""
        self._assigned_materials[body_name] = material_name
        self._nominal_assigned_materials[body_name] = material_name
        if body_name in self._bodies:
            self._bodies[body_name].material_name = material_name

    def get_assigned_material(self, body_name: str) -> str | None:
        """Retrieve the material currently assigned to a body."""
        if body_name in self._assigned_materials:
            return self._assigned_materials[body_name]
        body = self._bodies.get(body_name)
        return body.material_name if body else None

    def set_shell_thickness(self, body_name: str, thickness: float) -> None:
        """Set shell thickness for a surface body."""
        self._shell_thicknesses[body_name] = thickness
        self._nominal_shell_thicknesses[body_name] = thickness
        if body_name in self._bodies:
            self._bodies[body_name].thickness = thickness

    def get_shell_thickness(self, body_name: str) -> float | None:
        """Retrieve shell thickness for a surface body."""
        return self._shell_thicknesses.get(body_name)

    def get_assigned_thickness(self, body_name: str) -> float | None:
        """Alias for get_shell_thickness."""
        return self.get_shell_thickness(body_name)

    def create_named_selection(self, name: str, entities: list[str]) -> None:
        """Create a named selection."""
        self._named_selections[name] = entities

    def get_named_selections(self) -> list[str]:
        """List all named selection identifiers."""
        return list(self._named_selections.keys())

    # -----------------------------------------------------------------------
    # Fault Injection API for Resiliency and Recovery Verification
    # -----------------------------------------------------------------------

    def inject_material_error(self, body_name: str, material_name: str) -> None:
        """Inject an erroneous or corrupted material assignment."""
        self._assigned_materials[body_name] = material_name
        if body_name in self._bodies:
            self._bodies[body_name].material_name = material_name

    def inject_material_mismatch(self, body_name: str, material_name: str) -> None:
        """Alias for inject_material_error."""
        self.inject_material_error(body_name, material_name)

    def inject_thickness_error(self, body_name: str, thickness: float) -> None:
        """Inject an out-of-tolerance shell thickness."""
        self._shell_thicknesses[body_name] = thickness
        if body_name in self._bodies:
            self._bodies[body_name].thickness = thickness

    def inject_thickness_mismatch(self, body_name: str, thickness: float) -> None:
        """Alias for inject_thickness_error."""
        self.inject_thickness_error(body_name, thickness)

    def inject_body(
        self, name: str, body_type: str = "solid", thickness: float | None = None
    ) -> None:
        """Inject a body into the model."""
        self.add_body(name=name, body_type=body_type, thickness=thickness)

    def inject_unmapped_body(self, name: str, body_type: str = "solid") -> None:
        """Inject a body not present in specification mappings."""
        self.add_body(name=name, body_type=body_type)

    def clear_faults(self) -> None:
        """Restore nominal state and clear injected errors."""
        self._assigned_materials = dict(self._nominal_assigned_materials)
        self._shell_thicknesses = dict(self._nominal_shell_thicknesses)
        for name, body in self._bodies.items():
            body.material_name = self._assigned_materials.get(name)
            body.thickness = self._shell_thicknesses.get(name)

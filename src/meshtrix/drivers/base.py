"""
Meshtrix Driver Port Interface and Geometry / Mesh Entities.

Authoritative Reference: ORIGINAL_REQUEST.md §R2 & PROJECT.md
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class BodyProperties:
    """Attributes and properties of a CAD body."""

    name: str
    body_type: str = "solid"
    material_name: str | None = None
    thickness: float | None = None
    offset_type: str = "middle"

    def __getitem__(self, item: str) -> Any:
        return getattr(self, item)

    def __setitem__(self, item: str, value: Any) -> None:
        setattr(self, item, value)

    def __contains__(self, item: str) -> bool:
        return hasattr(self, item)

    def get(self, item: str, default: Any = None) -> Any:
        return getattr(self, item, default)


@dataclass
class MeshStatistics:
    """Metrics and statistics from mesh generation."""

    node_count: int = 0
    element_count: int = 0
    min_quality: float = 1.0
    max_skewness: float = 0.0
    max_aspect_ratio: float = 1.0
    max_warpage: float = 0.0
    failing_elements: dict[str, list[int]] | None = None


@dataclass
class SupportRecord:
    """Recorded boundary condition support applied in the solver model."""

    name: str
    selection: str
    support_type: str = "fixed"
    dofs: list[str] = field(default_factory=list)
    coordinate_system: str = "Global"
    displacement_values: dict[str, float] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize support record into JSON-safe primitives."""
        return {
            "name": self.name,
            "selection": self.selection,
            "support_type": self.support_type,
            "dofs": list(self.dofs),
            "coordinate_system": self.coordinate_system,
            "displacement_values": (
                dict(self.displacement_values) if self.displacement_values is not None else None
            ),
        }


@dataclass
class LoadRecord:
    """Recorded load (force, pressure, or acceleration) applied in the solver model."""

    case_id: str
    load_type: str
    selection: str | None
    magnitude: float
    direction: list[float] = field(default_factory=lambda: [0.0, 0.0, 1.0])
    coordinate_system: str = "Global"
    name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize load record into JSON-safe primitives."""
        return {
            "case_id": self.case_id,
            "load_type": self.load_type,
            "selection": self.selection,
            "magnitude": float(self.magnitude),
            "direction": [float(v) for v in self.direction],
            "coordinate_system": self.coordinate_system,
            "name": self.name,
        }


class MechanicalDriver(ABC):
    """Abstract port defining solver interaction and model manipulation contracts."""

    @abstractmethod
    def connect(self) -> None:
        """Establish connection to solver instance."""

    @abstractmethod
    def disconnect(self) -> None:
        """Disconnect from solver instance."""

    @abstractmethod
    def is_connected(self) -> bool:
        """Return True if connection is active."""

    @abstractmethod
    def get_bodies(self) -> list[BodyProperties]:
        """Retrieve all CAD bodies in the model."""

    @abstractmethod
    def get_body_names(self) -> list[str]:
        """Retrieve names of all CAD bodies in the model."""

    @abstractmethod
    def get_body_properties(self, body_name: str) -> BodyProperties | None:
        """Retrieve properties for a specific body by name."""

    @abstractmethod
    def has_body(self, body_name: str) -> bool:
        """Check whether a body exists in the model."""

    @abstractmethod
    def register_material(self, name: str, properties: Any) -> None:
        """Register a material definition in the preprocessor."""

    @abstractmethod
    def list_materials(self) -> list[str]:
        """List all materials currently registered in the preprocessor."""

    @abstractmethod
    def assign_material(self, body_name: str, material_name: str) -> None:
        """Assign a material to a target CAD body."""

    @abstractmethod
    def get_assigned_material(self, body_name: str) -> str | None:
        """Retrieve the material currently assigned to a target body."""

    @abstractmethod
    def set_shell_thickness(self, body_name: str, thickness: float) -> None:
        """Set the shell thickness for a surface body."""

    @abstractmethod
    def get_shell_thickness(self, body_name: str) -> float | None:
        """Retrieve the assigned shell thickness for a surface body."""

    @abstractmethod
    def add_body(self, name: str, body_type: str = "solid", thickness: float | None = None) -> None:
        """Add a body representation to the model."""

    @abstractmethod
    def set_global_mesh_size(self, size: float) -> None:
        """Set the global element size for meshing."""

    @abstractmethod
    def set_element_order(self, order: str) -> None:
        """Set the mesh element formulation order (e.g. 'linear', 'quadratic')."""

    @abstractmethod
    def add_local_refinement(self, name: str, selection: str, element_size: float) -> None:
        """Define a local mesh refinement on a named selection."""

    @abstractmethod
    def generate_mesh(
        self,
        global_size: float | None = None,
        element_order: str | None = None,
        local_refinements: list[Any] | None = None,
    ) -> MeshStatistics:
        """Generate the mesh with global and local settings."""

    @abstractmethod
    def get_mesh_statistics(self) -> MeshStatistics:
        """Retrieve aggregated mesh generation statistics and quality metrics."""

    @abstractmethod
    def get_element_count(self) -> int:
        """Retrieve the total count of generated mesh elements."""

    @abstractmethod
    def get_max_skewness(self) -> float:
        """Retrieve the maximum element skewness in the mesh."""

    @abstractmethod
    def get_max_aspect_ratio(self) -> float:
        """Retrieve the maximum element aspect ratio in the mesh."""

    @abstractmethod
    def get_max_warpage(self) -> float:
        """Retrieve the maximum element warpage (degrees) in the mesh."""

    @abstractmethod
    def get_failing_elements(self, metric: str, threshold: float) -> list[int]:
        """Retrieve IDs of elements violating a quality metric threshold."""

    @abstractmethod
    def is_mesh_generated(self) -> bool:
        """Return True if a valid mesh has been successfully generated."""

    @abstractmethod
    def create_named_selection(self, name: str, entities: list[str]) -> None:
        """Create a named selection."""

    @abstractmethod
    def get_named_selections(self) -> list[str]:
        """List all named selection identifiers."""

    @abstractmethod
    def has_named_selection(self, name: str) -> bool:
        """Return True if a named selection with the given name exists."""

    @abstractmethod
    def get_named_selection_entities(self, name: str) -> list[str]:
        """Retrieve entity identifiers belonging to a named selection."""

    @abstractmethod
    def apply_support(
        self,
        selection: str,
        support_type: str = "fixed",
        dofs: list[str] | None = None,
        coordinate_system: str = "Global",
        name: str | None = None,
        displacement_values: dict[str, float] | None = None,
    ) -> SupportRecord:
        """Apply a boundary condition support to a named selection."""

    @abstractmethod
    def get_supports(self) -> list[SupportRecord]:
        """Retrieve all boundary condition supports currently applied."""

    @abstractmethod
    def apply_force(
        self,
        case_id: str,
        selection: str,
        magnitude: float,
        direction: list[float],
        coordinate_system: str = "Global",
        name: str | None = None,
    ) -> LoadRecord:
        """Apply a force load to a named selection within a load case."""

    @abstractmethod
    def apply_pressure(
        self,
        case_id: str,
        selection: str,
        magnitude: float,
        direction: list[float] | None = None,
        coordinate_system: str = "Global",
        name: str | None = None,
    ) -> LoadRecord:
        """Apply a pressure load to a named selection within a load case."""

    @abstractmethod
    def apply_acceleration(
        self,
        case_id: str,
        magnitude: float,
        direction: list[float],
        selection: str | None = None,
        coordinate_system: str = "Global",
        name: str | None = None,
    ) -> LoadRecord:
        """Apply an inertial acceleration load within a load case."""

    @abstractmethod
    def get_loads(self, case_id: str | None = None) -> list[LoadRecord]:
        """Retrieve applied loads, optionally filtered by load case identifier."""

    @abstractmethod
    def clear_faults(self) -> None:
        """Reset or clear all simulated faults and restore nominal states."""

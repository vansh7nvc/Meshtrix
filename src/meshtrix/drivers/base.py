"""
Meshtrix Driver Port Interface and Geometry / Mesh Entities.

Authoritative Reference: ORIGINAL_REQUEST.md §R2 & PROJECT.md
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
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
    def clear_faults(self) -> None:
        """Reset or clear all simulated faults and restore nominal states."""

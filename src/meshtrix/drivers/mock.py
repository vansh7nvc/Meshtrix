"""
Meshtrix In-Memory Mock Driver for Zero-License Offline Execution.

Authoritative Reference: ORIGINAL_REQUEST.md §R2 & PROJECT.md
"""

from typing import Any

from meshtrix.drivers.base import BodyProperties, MechanicalDriver, MeshStatistics


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

        # Mesh generation and quality inspection state
        self._mesh_generated: bool = False
        self._global_mesh_size: float | None = None
        self._element_order: str = "quadratic"
        self._local_refinements: list[dict[str, Any]] = []
        self._mesh_stats: MeshStatistics = MeshStatistics()
        self._nominal_mesh_stats: MeshStatistics = MeshStatistics()
        self._failing_elements: dict[str, list[int]] = {}

        # Injected mesh faults
        self._inject_mesh_generation_failure_flag: bool = False
        self._injected_element_count: int | None = None
        self._injected_max_skewness: float | None = None
        self._injected_max_aspect_ratio: float | None = None
        self._injected_max_warpage: float | None = None

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
    # Meshing Execution and Quality Query API
    # -----------------------------------------------------------------------

    def set_global_mesh_size(self, size: float) -> None:
        """Set the global element size for meshing."""
        self._global_mesh_size = size

    def set_element_order(self, order: str) -> None:
        """Set the mesh element formulation order (e.g. 'linear', 'quadratic')."""
        self._element_order = order

    def add_local_refinement(self, name: str, selection: str, element_size: float) -> None:
        """Define a local mesh refinement on a named selection."""
        self._local_refinements.append(
            {"name": name, "selection": selection, "element_size": element_size}
        )

    def get_local_refinements(self) -> list[dict[str, Any]]:
        """Retrieve applied local mesh refinements."""
        return list(self._local_refinements)

    def generate_mesh(
        self,
        global_size: float | None = None,
        element_order: str | None = None,
        local_refinements: list[Any] | None = None,
    ) -> MeshStatistics:
        """Generate the mesh with global and local settings."""
        if global_size is not None:
            self._global_mesh_size = global_size
        if element_order is not None:
            self._element_order = element_order
        if local_refinements is not None:
            for ref in local_refinements:
                if hasattr(ref, "name"):
                    self.add_local_refinement(ref.name, ref.selection, ref.element_size)
                elif isinstance(ref, dict):
                    self.add_local_refinement(ref["name"], ref["selection"], ref["element_size"])

        if self._inject_mesh_generation_failure_flag:
            self._mesh_generated = False
            self._mesh_stats = MeshStatistics(
                node_count=0,
                element_count=0,
                min_quality=0.0,
                max_skewness=1.0,
                max_aspect_ratio=999.0,
                max_warpage=90.0,
                failing_elements=dict(self._failing_elements),
            )
            return self._mesh_stats

        body_count = max(1, len(self._bodies))
        size = self._global_mesh_size or 5.0
        base_elem_count = int(max(100, 1000 * body_count / size))
        refinement_elem_count = len(self._local_refinements) * 250
        total_elements = (
            self._injected_element_count
            if self._injected_element_count is not None
            else (base_elem_count + refinement_elem_count)
        )
        mult = 8 if self._element_order == "quadratic" else 4
        total_nodes = total_elements * mult

        skew = self._injected_max_skewness if self._injected_max_skewness is not None else 0.28
        aspect = self._injected_max_aspect_ratio if self._injected_max_aspect_ratio is not None else 1.85
        warpage = self._injected_max_warpage if self._injected_max_warpage is not None else 3.5
        min_qual = max(0.0, 1.0 - skew)

        self._mesh_stats = MeshStatistics(
            node_count=total_nodes,
            element_count=total_elements,
            min_quality=min_qual,
            max_skewness=skew,
            max_aspect_ratio=aspect,
            max_warpage=warpage,
            failing_elements=dict(self._failing_elements),
        )
        self._nominal_mesh_stats = MeshStatistics(
            node_count=base_elem_count * mult,
            element_count=base_elem_count,
            min_quality=0.72,
            max_skewness=0.28,
            max_aspect_ratio=1.85,
            max_warpage=3.5,
        )
        self._mesh_generated = True
        return self._mesh_stats

    def is_mesh_generated(self) -> bool:
        """Return True if a valid mesh has been successfully generated."""
        return self._mesh_generated

    def get_mesh_statistics(self) -> MeshStatistics:
        """Retrieve aggregated mesh generation statistics and quality metrics."""
        return self._mesh_stats

    def get_element_count(self) -> int:
        """Retrieve the total count of generated mesh elements."""
        if self._injected_element_count is not None:
            return self._injected_element_count
        return self._mesh_stats.element_count

    def get_max_skewness(self) -> float:
        """Retrieve the maximum element skewness in the mesh."""
        if self._injected_max_skewness is not None:
            return self._injected_max_skewness
        return self._mesh_stats.max_skewness

    def get_max_aspect_ratio(self) -> float:
        """Retrieve the maximum element aspect ratio in the mesh."""
        if self._injected_max_aspect_ratio is not None:
            return self._injected_max_aspect_ratio
        return self._mesh_stats.max_aspect_ratio

    def get_max_warpage(self) -> float:
        """Retrieve the maximum element warpage (degrees) in the mesh."""
        if self._injected_max_warpage is not None:
            return self._injected_max_warpage
        return self._mesh_stats.max_warpage

    def get_failing_elements(self, metric: str, threshold: float) -> list[int]:
        """Retrieve IDs of elements violating a quality metric threshold."""
        elements = self._failing_elements.get(metric)
        if elements:
            return list(elements)

        cur_val = 0.0
        if metric == "skewness":
            cur_val = self.get_max_skewness()
        elif metric in ("aspect_ratio", "aspect"):
            cur_val = self.get_max_aspect_ratio()
        elif metric == "warpage":
            cur_val = self.get_max_warpage()

        if cur_val > threshold:
            return [1001, 1002, 1003]
        return []

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

    def inject_mesh_skewness(
        self, skewness: float, failing_elements: list[int] | None = None
    ) -> None:
        """Inject an out-of-tolerance mesh skewness value."""
        self._injected_max_skewness = skewness
        self._mesh_stats.max_skewness = skewness
        if failing_elements is not None:
            self._failing_elements["skewness"] = list(failing_elements)
        elif skewness > 0.8:
            self._failing_elements["skewness"] = [1042, 1043, 1044]

    def inject_mesh_aspect_ratio(
        self, aspect_ratio: float, failing_elements: list[int] | None = None
    ) -> None:
        """Inject an out-of-tolerance mesh aspect ratio value."""
        self._injected_max_aspect_ratio = aspect_ratio
        self._mesh_stats.max_aspect_ratio = aspect_ratio
        if failing_elements is not None:
            self._failing_elements["aspect_ratio"] = list(failing_elements)
        elif aspect_ratio > 10.0:
            self._failing_elements["aspect_ratio"] = [2041, 2042]

    def inject_mesh_warpage(
        self, warpage: float, failing_elements: list[int] | None = None
    ) -> None:
        """Inject an out-of-tolerance mesh warpage value."""
        self._injected_max_warpage = warpage
        self._mesh_stats.max_warpage = warpage
        if failing_elements is not None:
            self._failing_elements["warpage"] = list(failing_elements)
        elif warpage > 45.0:
            self._failing_elements["warpage"] = [3011, 3012]

    def inject_mesh_element_count(self, count: int) -> None:
        """Inject an abnormal mesh element count."""
        self._injected_element_count = count
        self._mesh_stats.element_count = count

    def inject_mesh_generation_failure(self, fail: bool = True) -> None:
        """Inject simulated mesh generation failure."""
        self._inject_mesh_generation_failure_flag = fail
        if fail:
            self._mesh_generated = False

    def clear_faults(self) -> None:
        """Restore nominal state and clear injected errors."""
        self._assigned_materials = dict(self._nominal_assigned_materials)
        self._shell_thicknesses = dict(self._nominal_shell_thicknesses)
        for name, body in self._bodies.items():
            body.material_name = self._assigned_materials.get(name)
            body.thickness = self._shell_thicknesses.get(name)

        # Clear mesh fault injections
        self._injected_element_count = None
        self._injected_max_skewness = None
        self._injected_max_aspect_ratio = None
        self._injected_max_warpage = None
        self._inject_mesh_generation_failure_flag = False
        self._failing_elements.clear()

        if self._mesh_generated:
            self._mesh_stats = MeshStatistics(
                node_count=self._nominal_mesh_stats.node_count,
                element_count=self._nominal_mesh_stats.element_count,
                min_quality=self._nominal_mesh_stats.min_quality,
                max_skewness=self._nominal_mesh_stats.max_skewness,
                max_aspect_ratio=self._nominal_mesh_stats.max_aspect_ratio,
                max_warpage=self._nominal_mesh_stats.max_warpage,
                failing_elements={},
            )

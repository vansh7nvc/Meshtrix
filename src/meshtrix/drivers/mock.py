"""
Meshtrix In-Memory Mock Driver for Zero-License Offline Execution.

Authoritative Reference: ORIGINAL_REQUEST.md §R2 & PROJECT.md
"""

import copy
import math
from typing import TYPE_CHECKING, Any

from meshtrix.drivers.base import (
    BodyProperties,
    LoadRecord,
    MechanicalDriver,
    MeshStatistics,
    SupportRecord,
)

if TYPE_CHECKING:
    from meshtrix.spec.job_spec import JobSpec


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
        self._nominal_named_selections: dict[str, list[str]] = {}
        self._supports: list[SupportRecord] = []
        self._nominal_supports: list[SupportRecord] = []
        self._loads: list[LoadRecord] = []
        self._nominal_loads: list[LoadRecord] = []
        self._support_counter: int = 0
        self._load_counter: int = 0

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
        copied = [str(e) for e in entities]
        self._named_selections[name] = copied
        self._nominal_named_selections[name] = list(copied)

    def get_named_selections(self) -> list[str]:
        """List all named selection identifiers."""
        return list(self._named_selections.keys())

    def has_named_selection(self, name: str) -> bool:
        """Return True if a named selection with the given name exists."""
        return name in self._named_selections

    def get_named_selection_entities(self, name: str) -> list[str]:
        """Retrieve entity identifiers belonging to a named selection."""
        return list(self._named_selections.get(name, []))

    # -----------------------------------------------------------------------
    # Boundary Conditions and Applied Loads API
    # -----------------------------------------------------------------------

    @staticmethod
    def _normalize_enum_str(value: Any, default: str = "") -> str:
        if value is None:
            return default
        if hasattr(value, "value"):
            return str(value.value).strip()
        return str(value).strip()

    @staticmethod
    def _resolve_default_dofs(
        support_type: str,
        displacement_values: dict[str, float] | None,
    ) -> list[str]:
        norm = support_type.strip().lower()
        if norm == "fixed":
            return ["UX", "UY", "UZ", "RX", "RY", "RZ"]
        if norm == "pinned":
            return ["UX", "UY", "UZ"]
        if norm == "frictionless":
            return ["NORMAL"]
        if norm == "displacement":
            if displacement_values:
                return [str(k).strip().upper() for k in displacement_values]
            return ["UX", "UY", "UZ"]
        return []

    @staticmethod
    def _clone_support(record: SupportRecord) -> SupportRecord:
        return SupportRecord(
            name=record.name,
            selection=record.selection,
            support_type=record.support_type,
            dofs=list(record.dofs),
            coordinate_system=record.coordinate_system,
            displacement_values=(
                dict(record.displacement_values) if record.displacement_values is not None else None
            ),
        )

    @staticmethod
    def _clone_load(record: LoadRecord) -> LoadRecord:
        return LoadRecord(
            case_id=record.case_id,
            load_type=record.load_type,
            selection=record.selection,
            magnitude=float(record.magnitude),
            direction=[float(v) for v in record.direction],
            coordinate_system=record.coordinate_system,
            name=record.name,
        )

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
        s_type = self._normalize_enum_str(support_type, "fixed").lower()
        disp_vals = (
            {str(k).strip().upper(): float(v) for k, v in displacement_values.items()}
            if displacement_values is not None
            else None
        )
        resolved_dofs = (
            list(dict.fromkeys(str(d).strip().upper() for d in dofs))
            if dofs is not None
            else self._resolve_default_dofs(s_type, disp_vals)
        )

        has_explicit_name = name is not None and bool(str(name).strip())
        if has_explicit_name:
            resolved_name = str(name).strip()
        else:
            self._support_counter += 1
            resolved_name = f"Support_{self._support_counter}_{selection}"

        record = SupportRecord(
            name=resolved_name,
            selection=selection,
            support_type=s_type,
            dofs=resolved_dofs,
            coordinate_system=coordinate_system,
            displacement_values=disp_vals,
        )

        updated = False
        if has_explicit_name:
            for idx, existing in enumerate(self._supports):
                if existing.name == resolved_name:
                    self._supports[idx] = record
                    updated = True
                    break
        if not updated:
            self._supports.append(record)

        self._nominal_supports = [self._clone_support(s) for s in self._supports]
        return self._clone_support(record)

    def get_supports(self) -> list[SupportRecord]:
        """Retrieve all boundary condition supports currently applied."""
        return [self._clone_support(s) for s in self._supports]

    def _apply_load_record(
        self,
        *,
        case_id: str,
        load_type: str,
        selection: str | None,
        magnitude: float,
        direction: list[float] | None,
        coordinate_system: str,
        name: str | None,
    ) -> LoadRecord:
        dir_vec = [float(v) for v in direction] if direction is not None else [0.0, 0.0, 1.0]
        clean_name = str(name).strip() if name is not None and str(name).strip() else None
        self._load_counter += 1

        record = LoadRecord(
            case_id=case_id,
            load_type=load_type,
            selection=selection,
            magnitude=float(magnitude),
            direction=dir_vec,
            coordinate_system=coordinate_system,
            name=clean_name,
        )

        updated = False
        if clean_name is not None:
            for idx, existing in enumerate(self._loads):
                if (
                    existing.case_id == case_id
                    and existing.name == clean_name
                    and existing.load_type == load_type
                ):
                    self._loads[idx] = record
                    updated = True
                    break
        if not updated:
            self._loads.append(record)

        self._nominal_loads = [self._clone_load(ld) for ld in self._loads]
        return self._clone_load(record)

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
        return self._apply_load_record(
            case_id=case_id,
            load_type="force",
            selection=selection,
            magnitude=magnitude,
            direction=direction,
            coordinate_system=coordinate_system,
            name=name,
        )

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
        return self._apply_load_record(
            case_id=case_id,
            load_type="pressure",
            selection=selection,
            magnitude=magnitude,
            direction=direction,
            coordinate_system=coordinate_system,
            name=name,
        )

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
        return self._apply_load_record(
            case_id=case_id,
            load_type="acceleration",
            selection=selection,
            magnitude=magnitude,
            direction=direction,
            coordinate_system=coordinate_system,
            name=name,
        )

    def get_loads(self, case_id: str | None = None) -> list[LoadRecord]:
        """Retrieve applied loads, optionally filtered by load case identifier."""
        if case_id is None:
            return [self._clone_load(ld) for ld in self._loads]
        return [self._clone_load(ld) for ld in self._loads if ld.case_id == case_id]

    # -----------------------------------------------------------------------
    # Meshing Execution and Quality Query API
    # -----------------------------------------------------------------------

    def set_global_mesh_size(self, size: float) -> None:
        """Set the global element size for meshing."""
        self._global_mesh_size = size

    def set_element_order(self, order: str) -> None:
        """Set the mesh element formulation order (e.g. 'linear', 'quadratic')."""
        self._element_order = str(order).lower()

    def add_local_refinement(self, name: str, selection: str, element_size: float) -> None:
        """Define a local mesh refinement on a named selection."""
        norm_name = str(name).strip() if name is not None and str(name).strip() else "refinement"
        for ref in self._local_refinements:
            if ref["name"] == norm_name:
                ref["selection"] = selection
                ref["element_size"] = element_size
                return
        self._local_refinements.append(
            {"name": norm_name, "selection": selection, "element_size": element_size}
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
            self._element_order = str(element_order).lower()
        if local_refinements is not None:
            for ref in local_refinements:
                if isinstance(ref, dict):
                    raw_n = ref.get("name")
                    raw_s = ref.get("selection")
                    r_name = (
                        str(raw_n).strip()
                        if raw_n is not None and str(raw_n).strip()
                        else (
                            f"refinement_{str(raw_s).strip()}"
                            if raw_s is not None and str(raw_s).strip()
                            else "refinement"
                        )
                    )
                    r_sel = str(raw_s).strip() if raw_s is not None else ""
                    r_size_raw = ref.get("element_size", 0.0)
                    r_size = (
                        float(r_size_raw)
                        if isinstance(r_size_raw, (int, float))
                        and not isinstance(r_size_raw, bool)
                        and not math.isnan(r_size_raw)
                        and not math.isinf(r_size_raw)
                        else 0.0
                    )
                    self.add_local_refinement(r_name, r_sel, r_size)
                elif hasattr(ref, "name") or hasattr(ref, "selection"):
                    raw_n = getattr(ref, "name", None)
                    raw_s = getattr(ref, "selection", None)
                    r_name = (
                        str(raw_n).strip()
                        if raw_n is not None and str(raw_n).strip()
                        else (
                            f"refinement_{str(raw_s).strip()}"
                            if raw_s is not None and str(raw_s).strip()
                            else "refinement"
                        )
                    )
                    r_sel = str(raw_s).strip() if raw_s is not None else ""
                    r_size_raw = getattr(ref, "element_size", 0.0)
                    r_size = (
                        float(r_size_raw)
                        if isinstance(r_size_raw, (int, float))
                        and not isinstance(r_size_raw, bool)
                        and not math.isnan(r_size_raw)
                        and not math.isinf(r_size_raw)
                        else 0.0
                    )
                    self.add_local_refinement(r_name, r_sel, r_size)

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
        raw_size = self._global_mesh_size
        if (
            raw_size is not None
            and isinstance(raw_size, (int, float))
            and not isinstance(raw_size, bool)
            and not math.isnan(raw_size)
            and not math.isinf(raw_size)
            and raw_size > 0.0
        ):
            size = max(0.001, float(raw_size))
        else:
            size = 5.0

        base_elem_count = int(max(100, 1000 * body_count / size))
        refinement_elem_count = len(self._local_refinements) * 250
        if (
            self._injected_element_count is not None
            and isinstance(self._injected_element_count, (int, float))
            and not isinstance(self._injected_element_count, bool)
            and not math.isnan(self._injected_element_count)
            and not math.isinf(self._injected_element_count)
        ):
            total_elements = int(self._injected_element_count)
        elif self._injected_element_count is not None:
            total_elements = 0
        else:
            total_elements = base_elem_count + refinement_elem_count

        mult = 8 if self._element_order in ("quadratic", "2", "second") else 4
        total_nodes = max(0, total_elements * mult)

        skew = self._injected_max_skewness if self._injected_max_skewness is not None else 0.28
        aspect = (
            self._injected_max_aspect_ratio if self._injected_max_aspect_ratio is not None else 1.85
        )
        warpage = self._injected_max_warpage if self._injected_max_warpage is not None else 3.5
        if (
            isinstance(skew, (int, float))
            and not isinstance(skew, bool)
            and not math.isnan(skew)
            and not math.isinf(skew)
        ):
            min_qual = max(0.0, 1.0 - float(skew))
        else:
            min_qual = 0.0

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
        norm_metric = "" if metric is None else str(metric).lower().replace("-", "_").strip()
        cur_val: float | None = None
        if norm_metric == "skewness":
            cur_val = self.get_max_skewness()
        elif norm_metric in ("aspect_ratio", "aspect"):
            cur_val = self.get_max_aspect_ratio()
        elif norm_metric == "warpage":
            cur_val = self.get_max_warpage()

        if (
            threshold is not None
            and isinstance(threshold, (int, float))
            and not isinstance(threshold, bool)
            and not math.isnan(threshold)
            and not math.isinf(threshold)
            and cur_val is not None
            and isinstance(cur_val, (int, float))
            and not isinstance(cur_val, bool)
            and not math.isnan(cur_val)
            and not math.isinf(cur_val)
            and cur_val <= threshold
        ):
            return []

        elements = self._failing_elements.get(norm_metric)
        if elements is None and isinstance(metric, str):
            elements = self._failing_elements.get(metric)
        if elements is not None:
            return list(elements)

        return [1001, 1002, 1003]

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
        elif skewness is not None and (
            not isinstance(skewness, (int, float))
            or isinstance(skewness, bool)
            or math.isnan(skewness)
            or math.isinf(skewness)
            or skewness < 0.0
            or skewness > 0.8
        ):
            self._failing_elements["skewness"] = [1042, 1043, 1044]

    def inject_mesh_aspect_ratio(
        self, aspect_ratio: float, failing_elements: list[int] | None = None
    ) -> None:
        """Inject an out-of-tolerance mesh aspect ratio value."""
        self._injected_max_aspect_ratio = aspect_ratio
        self._mesh_stats.max_aspect_ratio = aspect_ratio
        if failing_elements is not None:
            self._failing_elements["aspect_ratio"] = list(failing_elements)
        elif aspect_ratio is not None and (
            not isinstance(aspect_ratio, (int, float))
            or isinstance(aspect_ratio, bool)
            or math.isnan(aspect_ratio)
            or math.isinf(aspect_ratio)
            or aspect_ratio < 1.0
            or aspect_ratio > 10.0
        ):
            self._failing_elements["aspect_ratio"] = [2041, 2042]

    def inject_mesh_warpage(
        self, warpage: float, failing_elements: list[int] | None = None
    ) -> None:
        """Inject an out-of-tolerance mesh warpage value."""
        self._injected_max_warpage = warpage
        self._mesh_stats.max_warpage = warpage
        if failing_elements is not None:
            self._failing_elements["warpage"] = list(failing_elements)
        elif warpage is not None and (
            not isinstance(warpage, (int, float))
            or isinstance(warpage, bool)
            or math.isnan(warpage)
            or math.isinf(warpage)
            or warpage < 0.0
            or warpage > 45.0
        ):
            self._failing_elements["warpage"] = [3011, 3012]

    def inject_mesh_element_count(self, count: Any) -> None:
        """Inject an abnormal mesh element count."""
        self._injected_element_count = count
        if (
            isinstance(count, (int, float))
            and not isinstance(count, bool)
            and not math.isnan(count)
            and not math.isinf(count)
        ):
            self._mesh_stats.element_count = int(count)
        else:
            self._mesh_stats.element_count = 0

    def inject_mesh_generation_failure(self, fail: bool = True) -> None:
        """Inject simulated mesh generation failure."""
        self._inject_mesh_generation_failure_flag = fail
        if fail:
            self._mesh_generated = False

    def inject_empty_named_selection(self, name: str) -> None:
        """Inject an empty named selection in live model state."""
        self._named_selections[name] = []

    def inject_missing_named_selection(self, name: str) -> None:
        """Remove a named selection from live model state."""
        self._named_selections.pop(name, None)

    @staticmethod
    def _matches_support(record: SupportRecord, target: str) -> bool:
        return record.name == target or record.selection == target

    def inject_support_scoping_error(self, target: str, wrong_selection: str) -> None:
        """Inject a scoping mismatch on matching live supports."""
        for rec in self._supports:
            if self._matches_support(rec, target):
                rec.selection = wrong_selection

    def inject_support_dof_error(self, target: str, wrong_dofs: list[str]) -> None:
        """Inject a DOF mismatch on matching live supports."""
        norm_dofs = [str(d).strip().upper() for d in wrong_dofs]
        for rec in self._supports:
            if self._matches_support(rec, target):
                rec.dofs = list(norm_dofs)

    def inject_support_coordinate_system_error(self, target: str, wrong_cs: str) -> None:
        """Inject a coordinate system mismatch on matching live supports."""
        for rec in self._supports:
            if self._matches_support(rec, target):
                rec.coordinate_system = wrong_cs

    def inject_missing_support(self, target: str) -> None:
        """Remove matching supports from live model state."""
        self._supports = [r for r in self._supports if not self._matches_support(r, target)]

    @staticmethod
    def _matches_load(record: LoadRecord, target: str, case_id: str | None) -> bool:
        if case_id is not None and record.case_id != case_id:
            return False
        return target in (record.name, record.selection, record.case_id, record.load_type)

    def inject_load_magnitude_error(
        self, target: str, wrong_magnitude: float, case_id: str | None = None
    ) -> None:
        """Inject an erroneous load magnitude on matching live loads."""
        for rec in self._loads:
            if self._matches_load(rec, target, case_id):
                rec.magnitude = float(wrong_magnitude)

    def inject_load_sign_error(self, target: str, case_id: str | None = None) -> None:
        """Invert the sign of matching live loads."""
        for rec in self._loads:
            if self._matches_load(rec, target, case_id):
                if rec.magnitude != 0.0:
                    rec.magnitude = -rec.magnitude
                else:
                    rec.direction = [-v for v in rec.direction]

    def inject_load_direction_error(
        self, target: str, wrong_direction: list[float], case_id: str | None = None
    ) -> None:
        """Inject an erroneous direction vector on matching live loads."""
        dir_vec = [float(v) for v in wrong_direction]
        for rec in self._loads:
            if self._matches_load(rec, target, case_id):
                rec.direction = list(dir_vec)

    def inject_load_coordinate_system_error(
        self, target: str, wrong_cs: str, case_id: str | None = None
    ) -> None:
        """Inject a coordinate system mismatch on matching live loads."""
        for rec in self._loads:
            if self._matches_load(rec, target, case_id):
                rec.coordinate_system = wrong_cs

    def inject_missing_load(self, target: str, case_id: str | None = None) -> None:
        """Remove matching loads from live model state."""
        self._loads = [r for r in self._loads if not self._matches_load(r, target, case_id)]

    def clear_faults(self) -> None:
        """Restore nominal state and clear injected errors."""
        self._assigned_materials = dict(self._nominal_assigned_materials)
        self._shell_thicknesses = dict(self._nominal_shell_thicknesses)
        for name, body in self._bodies.items():
            body.material_name = self._assigned_materials.get(name)
            body.thickness = self._shell_thicknesses.get(name)

        self._named_selections = {k: list(v) for k, v in self._nominal_named_selections.items()}
        self._supports = [self._clone_support(s) for s in self._nominal_supports]
        self._loads = [self._clone_load(ld) for ld in self._nominal_loads]

        # Clear mesh fault injections
        self._injected_element_count = None
        self._injected_max_skewness = None
        self._injected_max_aspect_ratio = None
        self._injected_max_warpage = None
        self._inject_mesh_generation_failure_flag = False
        self._failing_elements.clear()

        if self._nominal_mesh_stats.element_count > 0:
            self._mesh_generated = True
            self._mesh_stats = MeshStatistics(
                node_count=self._nominal_mesh_stats.node_count,
                element_count=self._nominal_mesh_stats.element_count,
                min_quality=self._nominal_mesh_stats.min_quality,
                max_skewness=self._nominal_mesh_stats.max_skewness,
                max_aspect_ratio=self._nominal_mesh_stats.max_aspect_ratio,
                max_warpage=self._nominal_mesh_stats.max_warpage,
                failing_elements={},
            )
        elif self._mesh_generated:
            self._mesh_stats = MeshStatistics(
                node_count=self._nominal_mesh_stats.node_count,
                element_count=self._nominal_mesh_stats.element_count,
                min_quality=self._nominal_mesh_stats.min_quality,
                max_skewness=self._nominal_mesh_stats.max_skewness,
                max_aspect_ratio=self._nominal_mesh_stats.max_aspect_ratio,
                max_warpage=self._nominal_mesh_stats.max_warpage,
                failing_elements={},
            )

    # -----------------------------------------------------------------------
    # State Serialization and Spec Seeding
    # -----------------------------------------------------------------------

    @staticmethod
    def _mesh_stats_to_dict(stats: MeshStatistics) -> dict[str, Any]:
        return {
            "node_count": int(stats.node_count),
            "element_count": int(stats.element_count),
            "min_quality": float(stats.min_quality),
            "max_skewness": float(stats.max_skewness),
            "max_aspect_ratio": float(stats.max_aspect_ratio),
            "max_warpage": float(stats.max_warpage),
            "failing_elements": (
                {str(k): [int(e) for e in v] for k, v in stats.failing_elements.items()}
                if stats.failing_elements is not None
                else None
            ),
        }

    @staticmethod
    def _mesh_stats_from_dict(data: dict[str, Any]) -> MeshStatistics:
        raw_fe = data.get("failing_elements")
        failing_elements = (
            {str(k): [int(e) for e in v] for k, v in raw_fe.items()}
            if isinstance(raw_fe, dict)
            else None
        )
        return MeshStatistics(
            node_count=int(data.get("node_count", 0)),
            element_count=int(data.get("element_count", 0)),
            min_quality=float(data.get("min_quality", 1.0)),
            max_skewness=float(data.get("max_skewness", 0.0)),
            max_aspect_ratio=float(data.get("max_aspect_ratio", 1.0)),
            max_warpage=float(data.get("max_warpage", 0.0)),
            failing_elements=failing_elements,
        )

    @staticmethod
    def _support_from_dict(data: dict[str, Any]) -> SupportRecord:
        raw_disp = data.get("displacement_values")
        disp_vals = (
            {str(k).strip().upper(): float(v) for k, v in raw_disp.items()}
            if isinstance(raw_disp, dict)
            else None
        )
        return SupportRecord(
            name=str(data.get("name", "")),
            selection=str(data.get("selection", "")),
            support_type=str(data.get("support_type", "fixed")),
            dofs=[str(d).strip().upper() for d in data.get("dofs", [])],
            coordinate_system=str(data.get("coordinate_system", "Global")),
            displacement_values=disp_vals,
        )

    @staticmethod
    def _load_from_dict(data: dict[str, Any]) -> LoadRecord:
        raw_sel = data.get("selection")
        raw_name = data.get("name")
        return LoadRecord(
            case_id=str(data.get("case_id", "")),
            load_type=str(data.get("load_type", "force")),
            selection=str(raw_sel) if raw_sel is not None else None,
            magnitude=float(data.get("magnitude", 0.0)),
            direction=[float(v) for v in data.get("direction", [0.0, 0.0, 1.0])],
            coordinate_system=str(data.get("coordinate_system", "Global")),
            name=str(raw_name) if raw_name is not None else None,
        )

    @staticmethod
    def _serialize_material(props: Any) -> Any:
        if hasattr(props, "model_dump"):
            return props.model_dump(mode="json")
        return copy.deepcopy(props)

    def export_state(self) -> dict[str, Any]:
        """Export complete mock driver state as a JSON-serializable dictionary."""
        return {
            "connected": self._connected,
            "bodies": {
                name: {
                    "name": body.name,
                    "body_type": body.body_type,
                    "material_name": body.material_name,
                    "thickness": body.thickness,
                    "offset_type": body.offset_type,
                }
                for name, body in self._bodies.items()
            },
            "materials": {k: self._serialize_material(v) for k, v in self._materials.items()},
            "assigned_materials": dict(self._assigned_materials),
            "nominal_assigned_materials": dict(self._nominal_assigned_materials),
            "shell_thicknesses": dict(self._shell_thicknesses),
            "nominal_shell_thicknesses": dict(self._nominal_shell_thicknesses),
            "named_selections": {k: list(v) for k, v in self._named_selections.items()},
            "nominal_named_selections": {
                k: list(v) for k, v in self._nominal_named_selections.items()
            },
            "mesh_generated": self._mesh_generated,
            "global_mesh_size": self._global_mesh_size,
            "element_order": self._element_order,
            "local_refinements": copy.deepcopy(self._local_refinements),
            "mesh_stats": self._mesh_stats_to_dict(self._mesh_stats),
            "nominal_mesh_stats": self._mesh_stats_to_dict(self._nominal_mesh_stats),
            "failing_elements": {k: list(v) for k, v in self._failing_elements.items()},
            "inject_mesh_generation_failure_flag": self._inject_mesh_generation_failure_flag,
            "injected_element_count": self._injected_element_count,
            "injected_max_skewness": self._injected_max_skewness,
            "injected_max_aspect_ratio": self._injected_max_aspect_ratio,
            "injected_max_warpage": self._injected_max_warpage,
            "supports": [s.to_dict() for s in self._supports],
            "nominal_supports": [s.to_dict() for s in self._nominal_supports],
            "loads": [ld.to_dict() for ld in self._loads],
            "nominal_loads": [ld.to_dict() for ld in self._nominal_loads],
            "support_counter": self._support_counter,
            "load_counter": self._load_counter,
        }

    def import_state(self, state: dict[str, Any]) -> None:
        """Restore mock driver state from an exported or partial JSON dictionary."""
        self._connected = bool(state.get("connected", True))

        bodies: dict[str, BodyProperties] = {}
        raw_bodies = state.get("bodies", {})
        if isinstance(raw_bodies, dict):
            for key, b_data in raw_bodies.items():
                if isinstance(b_data, dict):
                    b_name = str(b_data.get("name", key))
                    bodies[b_name] = BodyProperties(
                        name=b_name,
                        body_type=str(b_data.get("body_type", "solid")),
                        material_name=(
                            str(b_data["material_name"])
                            if b_data.get("material_name") is not None
                            else None
                        ),
                        thickness=(
                            float(b_data["thickness"])
                            if b_data.get("thickness") is not None
                            else None
                        ),
                        offset_type=str(b_data.get("offset_type", "middle")),
                    )
        elif isinstance(raw_bodies, list):
            for b_data in raw_bodies:
                if isinstance(b_data, dict) and "name" in b_data:
                    b_name = str(b_data["name"])
                    bodies[b_name] = BodyProperties(
                        name=b_name,
                        body_type=str(b_data.get("body_type", "solid")),
                        material_name=(
                            str(b_data["material_name"])
                            if b_data.get("material_name") is not None
                            else None
                        ),
                        thickness=(
                            float(b_data["thickness"])
                            if b_data.get("thickness") is not None
                            else None
                        ),
                        offset_type=str(b_data.get("offset_type", "middle")),
                    )
        self._bodies = bodies

        raw_materials = state.get("materials", {})
        self._materials = copy.deepcopy(raw_materials) if isinstance(raw_materials, dict) else {}

        if "assigned_materials" in state:
            self._assigned_materials = {
                str(k): str(v) for k, v in state["assigned_materials"].items()
            }
        else:
            self._assigned_materials = {
                name: b.material_name
                for name, b in self._bodies.items()
                if b.material_name is not None
            }

        if "nominal_assigned_materials" in state:
            self._nominal_assigned_materials = {
                str(k): str(v) for k, v in state["nominal_assigned_materials"].items()
            }
        else:
            self._nominal_assigned_materials = dict(self._assigned_materials)

        if "shell_thicknesses" in state:
            self._shell_thicknesses = {
                str(k): (float(v) if v is not None else None)
                for k, v in state["shell_thicknesses"].items()
            }
        else:
            self._shell_thicknesses = {name: b.thickness for name, b in self._bodies.items()}

        if "nominal_shell_thicknesses" in state:
            self._nominal_shell_thicknesses = {
                str(k): (float(v) if v is not None else None)
                for k, v in state["nominal_shell_thicknesses"].items()
            }
        else:
            self._nominal_shell_thicknesses = dict(self._shell_thicknesses)

        raw_ns = state.get("named_selections", {})
        self._named_selections = (
            {str(k): [str(e) for e in v] for k, v in raw_ns.items()}
            if isinstance(raw_ns, dict)
            else {}
        )
        if "nominal_named_selections" in state:
            raw_nom_ns = state["nominal_named_selections"]
            self._nominal_named_selections = (
                {str(k): [str(e) for e in v] for k, v in raw_nom_ns.items()}
                if isinstance(raw_nom_ns, dict)
                else {}
            )
        else:
            self._nominal_named_selections = {k: list(v) for k, v in self._named_selections.items()}

        self._mesh_generated = bool(state.get("mesh_generated", False))
        raw_gms = state.get("global_mesh_size")
        self._global_mesh_size = float(raw_gms) if raw_gms is not None else None
        self._element_order = str(state.get("element_order", "quadratic"))
        raw_refs = state.get("local_refinements", [])
        self._local_refinements = copy.deepcopy(raw_refs) if isinstance(raw_refs, list) else []

        raw_stats = state.get("mesh_stats")
        self._mesh_stats = (
            self._mesh_stats_from_dict(raw_stats)
            if isinstance(raw_stats, dict)
            else MeshStatistics()
        )
        raw_nom_stats = state.get("nominal_mesh_stats")
        self._nominal_mesh_stats = (
            self._mesh_stats_from_dict(raw_nom_stats)
            if isinstance(raw_nom_stats, dict)
            else self._mesh_stats_from_dict(self._mesh_stats_to_dict(self._mesh_stats))
        )

        raw_fe = state.get("failing_elements", {})
        self._failing_elements = (
            {str(k): [int(e) for e in v] for k, v in raw_fe.items()}
            if isinstance(raw_fe, dict)
            else {}
        )
        self._inject_mesh_generation_failure_flag = bool(
            state.get("inject_mesh_generation_failure_flag", False)
        )
        self._injected_element_count = state.get("injected_element_count")
        self._injected_max_skewness = state.get("injected_max_skewness")
        self._injected_max_aspect_ratio = state.get("injected_max_aspect_ratio")
        self._injected_max_warpage = state.get("injected_max_warpage")

        raw_supports = state.get("supports", [])
        self._supports = (
            [self._support_from_dict(s) for s in raw_supports if isinstance(s, dict)]
            if isinstance(raw_supports, list)
            else []
        )
        if "nominal_supports" in state:
            raw_nom_supports = state["nominal_supports"]
            self._nominal_supports = (
                [self._support_from_dict(s) for s in raw_nom_supports if isinstance(s, dict)]
                if isinstance(raw_nom_supports, list)
                else []
            )
        else:
            self._nominal_supports = [self._clone_support(s) for s in self._supports]

        raw_loads = state.get("loads", [])
        self._loads = (
            [self._load_from_dict(ld) for ld in raw_loads if isinstance(ld, dict)]
            if isinstance(raw_loads, list)
            else []
        )
        if "nominal_loads" in state:
            raw_nom_loads = state["nominal_loads"]
            self._nominal_loads = (
                [self._load_from_dict(ld) for ld in raw_nom_loads if isinstance(ld, dict)]
                if isinstance(raw_nom_loads, list)
                else []
            )
        else:
            self._nominal_loads = [self._clone_load(ld) for ld in self._loads]

        self._support_counter = int(state.get("support_counter", len(self._supports)))
        self._load_counter = int(state.get("load_counter", len(self._loads)))

    def seed_from_spec(self, spec: "JobSpec") -> None:
        """Idempotently populate CAD bodies and named selections referenced by a JobSpec."""
        for body_name, mapping in spec.materials.mappings.items():
            if not self.has_body(body_name):
                if mapping.body_type is not None:
                    bt = self._normalize_enum_str(mapping.body_type, "solid").lower()
                elif mapping.thickness is not None:
                    bt = "surface"
                else:
                    bt = "solid"
                self.add_body(name=body_name, body_type=bt, thickness=None)

        selections: list[str] = []
        if spec.mesh is not None:
            for ref in spec.mesh.local_refinements:
                selections.append(ref.selection)
        for sup in spec.supports:
            selections.append(sup.selection)
        for lc in spec.load_cases:
            for force in lc.forces:
                selections.append(force.selection)
            for pressure in lc.pressures:
                selections.append(pressure.selection)
            for accel in lc.accelerations:
                if accel.selection is not None:
                    selections.append(accel.selection)

        for sel_name in dict.fromkeys(selections):
            if sel_name and sel_name.strip() and not self.has_named_selection(sel_name):
                self.create_named_selection(sel_name, [f"{sel_name}_entity_1"])

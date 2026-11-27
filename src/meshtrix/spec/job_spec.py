"""
Meshtrix JobSpec and Sub-Model Pydantic v2 Schemas.

Authoritative Reference: ORIGINAL_REQUEST.md §R2 & PROJECT.md
"""

import math
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator


class UnitsSystem(StrEnum):
    """FEA unit systems supported by Meshtrix."""

    METRIC_MM = "Metric_mm"
    Metric_mm = "Metric_mm"
    METRIC_MM_N_MPA = "metric_mm_n_mpa"
    SI = "SI"
    SI_M_N_PA = "si_m_n_pa"
    MKS = "MKS"
    MPA = "MPA"
    US_IN_LBF_PSI = "us_in_lbf_psi"

    @classmethod
    def _missing_(cls, value: object) -> Any:
        if isinstance(value, str):
            val_clean = value.strip()
            if not val_clean:
                return None
            val_norm = val_clean.lower().replace("-", "_").replace(" ", "_")
            for member in cls:
                if (
                    member.value.lower() == val_norm
                    or member.name.lower() == val_norm
                    or member.value == val_clean
                ):
                    return member
        return None


class AnalysisType(StrEnum):
    """FEA analysis disciplines supported by Meshtrix."""

    STRUCTURAL_STATIC = "STRUCTURAL_STATIC"
    STATIC_STRUCTURAL = "static_structural"
    MODAL = "MODAL"
    RANDOM_VIBRATION = "random_vibration"

    @classmethod
    def _missing_(cls, value: object) -> Any:
        if isinstance(value, str):
            val_clean = value.strip()
            if not val_clean:
                return None
            val_norm = val_clean.lower().replace("-", "_").replace(" ", "_")
            for member in cls:
                if (
                    member.value.lower() == val_norm
                    or member.name.lower() == val_norm
                    or member.value == val_clean
                ):
                    return member
        return None


class BodyType(StrEnum):
    """Physical representation of CAD body."""

    SOLID = "solid"
    SURFACE = "surface"


class OffsetType(StrEnum):
    """Shell offset definition relative to mid-surface."""

    MIDDLE = "middle"
    TOP = "top"
    BOTTOM = "bottom"


class ElementOrder(StrEnum):
    """FEA mesh element formulation order."""

    LINEAR = "linear"
    QUADRATIC = "quadratic"


class SupportType(StrEnum):
    """Boundary constraint support types."""

    FIXED = "fixed"
    DISPLACEMENT = "displacement"
    FRICTIONLESS = "frictionless"
    PINNED = "pinned"


class LoadType(StrEnum):
    """Applied load types."""

    FORCE = "force"
    PRESSURE = "pressure"
    ACCELERATION = "acceleration"
    MOMENT = "moment"


VALID_SUPPORT_DOFS: tuple[str, ...] = ("UX", "UY", "UZ", "RX", "RY", "RZ", "NORMAL")
_VALID_SUPPORT_DOF_SET: frozenset[str] = frozenset(VALID_SUPPORT_DOFS)

_DEFAULT_DOFS_BY_SUPPORT_TYPE: dict[str, tuple[str, ...]] = {
    SupportType.FIXED.value: ("UX", "UY", "UZ", "RX", "RY", "RZ"),
    SupportType.PINNED.value: ("UX", "UY", "UZ"),
    SupportType.FRICTIONLESS.value: ("NORMAL",),
    SupportType.DISPLACEMENT.value: ("UX", "UY", "UZ"),
}


def _reject_bool(v: Any, field_name: str) -> Any:
    if isinstance(v, bool):
        raise ValueError(f"{field_name} must be numeric, not a boolean")
    return v


def _validate_finite_float(v: float, field_name: str) -> float:
    if not math.isfinite(v):
        raise ValueError(f"{field_name} must be a finite number")
    return v


def _reject_bool_in_sequence(v: Any, field_name: str) -> Any:
    if isinstance(v, (list, tuple)) and any(isinstance(item, bool) for item in v):
        raise ValueError(f"{field_name} entries must be numeric, not booleans")
    return v


def _validate_direction_3d(v: list[float]) -> list[float]:
    if len(v) != 3:
        raise ValueError("direction must be a 3-element vector [x, y, z]")
    for component in v:
        if not math.isfinite(component):
            raise ValueError("direction components must be finite numbers")
    return v


class MaterialCatalogEntry(BaseModel):
    """Physical engineering constants for a material definition."""

    name: str
    density: float = Field(gt=0.0, description="Density (> 0.0)")
    elastic_modulus: float = Field(gt=0.0, description="Young's Modulus (> 0.0)")
    poissons_ratio: float = Field(gt=0.0, lt=0.5, description="Poisson's ratio (0.0 < nu < 0.5)")
    yield_strength: float = Field(gt=0.0, description="Yield strength (> 0.0)")
    ultimate_strength: float | None = Field(
        default=None, gt=0.0, description="Ultimate tensile strength"
    )
    thermal_expansion: float | None = Field(
        default=None, description="Coefficient of thermal expansion"
    )


class BodyMaterialMapping(BaseModel):
    """Assignment mapping of a CAD body to a catalog material and shell attributes."""

    body_name: str
    material_name: str
    body_type: BodyType | str | None = None
    thickness: float | None = None
    offset_type: OffsetType | str = "middle"

    @field_validator("thickness")
    @classmethod
    def validate_thickness(cls, v: float | None) -> float | None:
        if v is not None and v <= 0.0:
            raise ValueError("thickness must be positive (> 0.0)")
        return v


class MaterialsSpec(BaseModel):
    """Collection of material definitions and CAD body assignments."""

    catalog: dict[str, MaterialCatalogEntry] = Field(default_factory=dict)
    mappings: dict[str, BodyMaterialMapping] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def normalize_mappings_and_catalog(cls, data: Any) -> Any:
        if isinstance(data, dict):
            mappings = data.get("mappings")
            if isinstance(mappings, list):
                norm_map: dict[str, Any] = {}
                for item in mappings:
                    if isinstance(item, dict) and "body_name" in item:
                        norm_map[item["body_name"]] = item
                    elif hasattr(item, "body_name"):
                        norm_map[item.body_name] = item
                data["mappings"] = norm_map
        return data

    @model_validator(mode="after")
    def validate_materials_in_catalog(self) -> "MaterialsSpec":
        for body_name, mapping in self.mappings.items():
            if mapping.material_name not in self.catalog:
                raise ValueError(
                    f"Material '{mapping.material_name}' for body '{body_name}' is not defined in the materials catalog."
                )
        return self


class LocalMeshRefinement(BaseModel):
    """Local mesh refinement specification on named selections."""

    name: str
    selection: str
    element_size: float = Field(gt=0.0)


class MeshQualityLimits(BaseModel):
    """Acceptance thresholds for element quality metrics."""

    min_quality: float = Field(default=0.2, ge=0.0, le=1.0)
    metric: str = "skewness"
    max_skewness: float | None = Field(default=None, ge=0.0, le=1.0)
    max_aspect_ratio: float | None = Field(default=None, gt=0.0)
    max_warpage: float | None = Field(default=None, ge=0.0)
    min_elements: int | None = Field(default=None, ge=1)
    max_elements: int | None = Field(default=None, ge=1)


class MeshSettings(BaseModel):
    """Global and local meshing controls."""

    global_size: float = Field(gt=0.0)
    element_order: ElementOrder | str = "quadratic"
    min_quality: float = Field(default=0.2, ge=0.0, le=1.0)
    quality_metric: str = "skewness"
    max_skewness: float | None = Field(default=None, ge=0.0, le=1.0)
    max_aspect_ratio: float | None = Field(default=None, gt=0.0)
    max_warpage: float | None = Field(default=None, ge=0.0)
    local_refinements: list[LocalMeshRefinement] = Field(default_factory=list)
    quality_limits: MeshQualityLimits | None = None


class CheckTolerances(BaseModel):
    """Numerical tolerances for physical pre/post verification checks."""

    thickness_tolerance: float = Field(default=0.01, gt=0.0)
    mass_tolerance: float = Field(default=0.05, gt=0.0)
    mesh_skewness_limit: float | None = Field(default=None, ge=0.0, le=1.0)
    mesh_aspect_ratio_limit: float | None = Field(default=None, gt=0.0)
    mesh_warpage_limit: float | None = Field(default=None, ge=0.0)
    load_tolerance: float = Field(default=0.01, gt=0.0)
    direction_tolerance: float = Field(default=1e-4, gt=0.0)

    @field_validator("load_tolerance", "direction_tolerance", mode="before")
    @classmethod
    def _reject_bool_tolerances(cls, v: Any) -> Any:
        return _reject_bool(v, "tolerance")

    @field_validator("load_tolerance", "direction_tolerance")
    @classmethod
    def _validate_finite_tolerances(cls, v: float) -> float:
        return _validate_finite_float(v, "tolerance")


class MassTarget(BaseModel):
    """Mass budget targets and expected center of gravity coordinates."""

    total_mass: float = Field(gt=0.0)
    cg_x: float = 0.0
    cg_y: float = 0.0
    cg_z: float = 0.0


class SupportSpec(BaseModel):
    """Support boundary condition constraint."""

    selection: str
    type: SupportType | str = "fixed"
    dofs: list[str] | None = None
    displacement_values: dict[str, float] | None = None
    coordinate_system: str = "Global"
    name: str | None = None

    @field_validator("type")
    @classmethod
    def _normalize_type(cls, v: SupportType | str) -> SupportType | str:
        if isinstance(v, SupportType):
            return v
        norm = v.strip().lower()
        try:
            return SupportType(norm)
        except ValueError:
            return v.strip()

    @field_validator("dofs")
    @classmethod
    def _validate_dofs(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return None
        if len(v) == 0:
            raise ValueError("dofs cannot be empty when specified")
        normalized: list[str] = []
        for d in v:
            d_norm = d.strip().upper()
            if d_norm not in _VALID_SUPPORT_DOF_SET:
                raise ValueError(f"Invalid DOF '{d}'. Valid DOFs: {list(VALID_SUPPORT_DOFS)}")
            normalized.append(d_norm)
        return list(dict.fromkeys(normalized))

    @field_validator("displacement_values", mode="before")
    @classmethod
    def _check_displacement_values_raw(cls, v: Any) -> Any:
        if isinstance(v, dict) and any(isinstance(val, bool) for val in v.values()):
            raise ValueError("displacement_values must be numeric, not booleans")
        return v

    @field_validator("displacement_values")
    @classmethod
    def _validate_displacement_values(cls, v: dict[str, float] | None) -> dict[str, float] | None:
        if v is None:
            return None
        normalized: dict[str, float] = {}
        for k, val in v.items():
            k_norm = k.strip().upper()
            if k_norm not in _VALID_SUPPORT_DOF_SET:
                raise ValueError(
                    f"Invalid DOF '{k}' in displacement_values. "
                    f"Valid DOFs: {list(VALID_SUPPORT_DOFS)}"
                )
            if k_norm in normalized:
                raise ValueError(f"Duplicate DOF key '{k_norm}' in displacement_values")
            if not math.isfinite(val):
                raise ValueError(f"displacement_values['{k}'] must be a finite number")
            normalized[k_norm] = val
        return normalized

    @model_validator(mode="after")
    def _validate_displacement_consistency(self) -> "SupportSpec":
        if self.dofs is not None and self.displacement_values is not None:
            extra = set(self.displacement_values.keys()) - set(self.dofs)
            if extra:
                raise ValueError(
                    f"displacement_values keys {sorted(extra)} are not present in dofs {self.dofs}"
                )
        return self

    def resolved_dofs(self) -> list[str]:
        """Return canonical uppercase DOF list resolved from explicit DOFs or support type."""
        if self.dofs is not None:
            return list(self.dofs)
        norm_type = (
            self.type.value
            if isinstance(self.type, SupportType)
            else str(self.type).strip().lower()
        )
        if norm_type == SupportType.DISPLACEMENT.value and self.displacement_values:
            return list(self.displacement_values.keys())
        defaults = _DEFAULT_DOFS_BY_SUPPORT_TYPE.get(norm_type)
        return list(defaults) if defaults is not None else []


class LoadSpec(BaseModel):
    """Applied load specification."""

    selection: str
    magnitude: float
    direction: list[float] = Field(default_factory=lambda: [0.0, 0.0, 1.0])
    load_type: LoadType | str = "force"
    coordinate_system: str = "Global"
    name: str | None = None

    @field_validator("magnitude", mode="before")
    @classmethod
    def _reject_bool_magnitude(cls, v: Any) -> Any:
        return _reject_bool(v, "magnitude")

    @field_validator("magnitude")
    @classmethod
    def _validate_magnitude(cls, v: float) -> float:
        return _validate_finite_float(v, "magnitude")

    @field_validator("direction", mode="before")
    @classmethod
    def _reject_bool_direction(cls, v: Any) -> Any:
        return _reject_bool_in_sequence(v, "direction")

    @field_validator("direction")
    @classmethod
    def _validate_direction(cls, v: list[float]) -> list[float]:
        return _validate_direction_3d(v)

    @field_validator("load_type")
    @classmethod
    def _normalize_load_type(cls, v: LoadType | str) -> LoadType | str:
        if isinstance(v, LoadType):
            return v
        norm = v.strip().lower()
        try:
            return LoadType(norm)
        except ValueError:
            return v.strip()

    @model_validator(mode="after")
    def _validate_non_zero_direction(self) -> "LoadSpec":
        if self.magnitude != 0.0 and math.hypot(*self.direction) == 0.0:
            raise ValueError("direction cannot be the zero vector when magnitude is non-zero")
        return self


class AccelerationSpec(BaseModel):
    """Applied inertial acceleration load specification."""

    magnitude: float
    direction: list[float] = Field(default_factory=lambda: [0.0, 0.0, -1.0])
    selection: str | None = None
    coordinate_system: str = "Global"
    name: str | None = None
    load_type: LoadType | str = LoadType.ACCELERATION

    @field_validator("magnitude", mode="before")
    @classmethod
    def _reject_bool_magnitude(cls, v: Any) -> Any:
        return _reject_bool(v, "magnitude")

    @field_validator("magnitude")
    @classmethod
    def _validate_magnitude(cls, v: float) -> float:
        return _validate_finite_float(v, "magnitude")

    @field_validator("direction", mode="before")
    @classmethod
    def _reject_bool_direction(cls, v: Any) -> Any:
        return _reject_bool_in_sequence(v, "direction")

    @field_validator("direction")
    @classmethod
    def _validate_direction(cls, v: list[float]) -> list[float]:
        return _validate_direction_3d(v)

    @field_validator("load_type")
    @classmethod
    def _normalize_load_type(cls, v: LoadType | str) -> LoadType | str:
        if isinstance(v, LoadType):
            return v
        norm = v.strip().lower()
        try:
            return LoadType(norm)
        except ValueError:
            return v.strip()

    @model_validator(mode="after")
    def _validate_non_zero_direction(self) -> "AccelerationSpec":
        if self.magnitude != 0.0 and math.hypot(*self.direction) == 0.0:
            raise ValueError("direction cannot be the zero vector when magnitude is non-zero")
        return self


class LoadCase(BaseModel):
    """Analysis load case bundling forces, pressures, accelerations, and constraints."""

    case_id: str
    forces: list[LoadSpec] = Field(default_factory=list)
    pressures: list[LoadSpec] = Field(default_factory=list)
    accelerations: list[AccelerationSpec] = Field(default_factory=list)
    step_number: int | None = Field(default=None, ge=1)
    description: str | None = None

    @field_validator("step_number", mode="before")
    @classmethod
    def _reject_bool_step_number(cls, v: Any) -> Any:
        return _reject_bool(v, "step_number")


class JobSpec(BaseModel):
    """Unified root specification for autonomous FEA execution."""

    job_id: str
    units: UnitsSystem
    analysis_type: AnalysisType
    materials: MaterialsSpec
    mesh: MeshSettings | None = None
    tolerances: CheckTolerances | None = None
    mass_target: MassTarget | None = None
    load_cases: list[LoadCase] = Field(default_factory=list)
    supports: list[SupportSpec] = Field(default_factory=list)
    spec_version: str = "1.0"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "JobSpec":
        """Instantiate JobSpec from a dictionary."""
        return cls.model_validate(data)

    def to_dict(self) -> dict[str, Any]:
        """Convert JobSpec to dictionary."""
        return self.model_dump(mode="json")

    @classmethod
    def from_yaml(cls, path_or_yaml: str | Path) -> "JobSpec":
        """Load JobSpec from YAML string or file path."""
        if isinstance(path_or_yaml, Path):
            if not path_or_yaml.exists() or not path_or_yaml.is_file():
                raise FileNotFoundError(f"JobSpec file not found: {path_or_yaml}")
            content = path_or_yaml.read_text(encoding="utf-8")
        else:
            try:
                path = Path(path_or_yaml)
                if path.exists() and path.is_file():
                    content = path.read_text(encoding="utf-8")
                else:
                    content = str(path_or_yaml)
            except (OSError, ValueError):
                content = str(path_or_yaml)
        data = yaml.safe_load(content)
        return cls.model_validate(data)

    def to_yaml(self, path: str | Path | None = None) -> str:
        """Export JobSpec to YAML string or file path."""
        yaml_str = yaml.dump(self.model_dump(mode="json"), sort_keys=False)
        if path is not None:
            out_path = Path(path)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(yaml_str, encoding="utf-8")
        return yaml_str

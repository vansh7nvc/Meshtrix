"""
Meshtrix JobSpec and Sub-Model Pydantic v2 Schemas.

Authoritative Reference: ORIGINAL_REQUEST.md §R2 & PROJECT.md
"""

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


class MeshSettings(BaseModel):
    """Global and local meshing controls."""

    global_size: float = Field(gt=0.0)
    element_order: ElementOrder | str = "quadratic"
    min_quality: float = Field(default=0.2, ge=0.0, le=1.0)
    quality_metric: str = "skewness"
    local_refinements: list[LocalMeshRefinement] = Field(default_factory=list)
    quality_limits: MeshQualityLimits | None = None


class CheckTolerances(BaseModel):
    """Numerical tolerances for physical pre/post verification checks."""

    thickness_tolerance: float = Field(default=0.01, gt=0.0)
    mass_tolerance: float = Field(default=0.05, gt=0.0)


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


class LoadSpec(BaseModel):
    """Applied load specification."""

    selection: str
    magnitude: float
    direction: list[float] = Field(default_factory=lambda: [0.0, 0.0, 1.0])
    load_type: LoadType | str = "force"


class LoadCase(BaseModel):
    """Analysis load case bundling forces, pressures, and constraints."""

    case_id: str
    forces: list[LoadSpec] = Field(default_factory=list)
    pressures: list[LoadSpec] = Field(default_factory=list)


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

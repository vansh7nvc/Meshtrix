"""
Meshtrix Step 8: Meshing Automation and Quality Verification.

Authoritative Reference: ORIGINAL_REQUEST.md §R1 & PROJECT.md
"""

import math
from typing import Any, cast

from meshtrix.core.step import BaseStep, RunContext
from meshtrix.diagnostics.failure import (
    ERR_DRIVER_COMMUNICATION,
    ERR_MAT_INVALID_THICKNESS,
    ERR_MAT_UNASSIGNED_BODY,
    ERR_MESH_ASPECT_RATIO_EXCEEDED,
    ERR_MESH_ELEMENT_COUNT,
    ERR_MESH_GENERATION_FAILED,
    ERR_MESH_MISSING_SELECTION,
    ERR_MESH_NO_BODIES,
    ERR_MESH_SKEWNESS_EXCEEDED,
    ERR_MESH_SPEC_MISSING,
    ERR_MESH_WARPAGE_EXCEEDED,
    FailureObject,
    Severity,
    StepCheckResult,
)
from meshtrix.drivers.base import BodyProperties


def _resolve_numeric_threshold(
    val: Any, min_val: float, max_val: float | None = None
) -> float | None:
    """Validate and return float threshold if finite, numeric, non-boolean, and within bounds."""
    if (
        val is not None
        and isinstance(val, (int, float))
        and not isinstance(val, bool)
        and not math.isnan(val)
        and not math.isinf(val)
        and val >= min_val
        and (max_val is None or val <= max_val)
    ):
        return float(val)
    return None


class Step08Meshing(BaseStep):
    """Step 8: Global and local mesh generation, quality inspection, and diagnostic troubleshooting."""

    @property
    def step_id(self) -> str:
        """Step identifier."""
        return "step_08_meshing"

    @property
    def description(self) -> str:
        """Step description."""
        return "Step 8: Meshing Automation & Quality Inspection"

    def pre_check(self, context: RunContext) -> StepCheckResult:
        """
        Phase 1: Validate prerequisites before executing meshing.

        Verifies:
        1. Driver connection is live.
        2. Mesh specification is provided in JobSpec.
        3. Model bodies exist in the CAD/preprocessor model.
        4. Every body has a valid material assigned (from Step 6).
        5. Every surface/shell body has a valid positive thickness assigned.
        6. Local refinement named selections exist in the preprocessor model (if specified).
        """
        result = StepCheckResult(step_id=self.step_id)

        # 1. Driver connection verification
        if context.driver is None or (hasattr(context.driver, "is_connected") and not context.driver.is_connected()):
            result.add_failure(
                FailureObject(
                    error_code=ERR_DRIVER_COMMUNICATION,
                    severity=Severity.BLOCKING,
                    step_id=self.step_id,
                    component_or_entity="MechanicalDriver",
                    measured_value="Disconnected",
                    expected_value="Connected",
                    engineering_message="Mechanical driver is not connected during pre-check.",
                    likely_causes=[
                        "Solver process crashed or failed to start",
                        "Network timeout or gRPC communication drop",
                    ],
                    suggested_fixes=["Reconnect driver port to Mechanical instance"],
                    resume_step_id=self.step_id,
                )
            )
            return result

        # 2. Verify mesh specification exists in JobSpec
        if context.spec.mesh is None:
            result.add_failure(
                FailureObject(
                    error_code=ERR_MESH_SPEC_MISSING,
                    severity=Severity.BLOCKING,
                    step_id=self.step_id,
                    component_or_entity="JobSpec.mesh",
                    measured_value=None,
                    expected_value="Defined MeshSettings",
                    engineering_message="JobSpec does not define required mesh settings.",
                    likely_causes=[
                        "JobSpec missing 'mesh' configuration block",
                        "Incomplete specification passed to runner",
                    ],
                    suggested_fixes=[
                        "Add 'mesh' section with global_size and element_order to JobSpec"
                    ],
                    resume_step_id=self.step_id,
                )
            )
            return result

        # 2b. Verify global mesh size is valid positive finite number
        g_size = context.spec.mesh.global_size
        if _resolve_numeric_threshold(g_size, min_val=1e-6) is None:
            result.add_failure(
                FailureObject(
                    error_code=ERR_MESH_SPEC_MISSING,
                    severity=Severity.BLOCKING,
                    step_id=self.step_id,
                    component_or_entity="JobSpec.mesh.global_size",
                    measured_value=g_size,
                    expected_value="> 0.0 mm",
                    engineering_message=(
                        f"Global mesh size must be a positive finite number, but found {g_size}."
                    ),
                    likely_causes=[
                        "Non-positive, NaN, infinite, or non-numeric global element size in JobSpec",
                    ],
                    suggested_fixes=[
                        "Specify a positive finite global_size (e.g. 5.0 mm) in JobSpec mesh settings"
                    ],
                    resume_step_id=self.step_id,
                )
            )
            return result

        # 3. Verify bodies exist in model
        model_bodies = cast(list[BodyProperties], context.driver.get_bodies())
        if not model_bodies:
            result.add_failure(
                FailureObject(
                    error_code=ERR_MESH_NO_BODIES,
                    severity=Severity.BLOCKING,
                    step_id=self.step_id,
                    component_or_entity="MechanicalModel",
                    measured_value=0,
                    expected_value=">= 1 CAD body",
                    engineering_message="CAD model contains no bodies to mesh.",
                    likely_causes=[
                        "Geometry import failed or geometry was not transferred",
                        "All CAD bodies suppressed or deleted",
                    ],
                    suggested_fixes=[
                        "Verify CAD geometry transfer in Step 4",
                        "Ensure at least one unsuppressed body exists in Mechanical model",
                    ],
                    resume_step_id=self.step_id,
                )
            )
            return result

        # 4 & 5. Verify material and thickness assignments on every body
        for body in model_bodies:
            b_name = getattr(body, "name", None) or (body.get("name") if isinstance(body, dict) else str(body))
            b_type = getattr(body, "body_type", None) or (body.get("body_type") if isinstance(body, dict) else "solid")
            assigned_mat = context.driver.get_assigned_material(b_name)
            if not assigned_mat or isinstance(assigned_mat, bool) or not str(assigned_mat).strip():
                result.add_failure(
                    FailureObject(
                        error_code=ERR_MAT_UNASSIGNED_BODY,
                        severity=Severity.BLOCKING,
                        step_id=self.step_id,
                        component_or_entity=b_name,
                        measured_value=assigned_mat,
                        expected_value="Valid assigned material",
                        engineering_message=(
                            f"Body '{b_name}' has no material assigned prior to meshing. "
                            f"Material assignment must precede mesh generation."
                        ),
                        likely_causes=[
                            "Step 6 Material Mapping was skipped or failed",
                            "Body was newly added without running Step 6",
                        ],
                        suggested_fixes=[
                            f"Execute Step 6 Material Mapping for body '{b_name}'",
                            f"Assign a valid material to body '{b_name}' in JobSpec",
                        ],
                        resume_step_id="step_06_materials",
                    )
                )

            if str(b_type).strip().lower() in ("surface", "shell"):
                assigned_thk = context.driver.get_shell_thickness(b_name)
                is_thk_valid = (
                    assigned_thk is not None
                    and isinstance(assigned_thk, (int, float))
                    and not isinstance(assigned_thk, bool)
                    and not math.isnan(assigned_thk)
                    and not math.isinf(assigned_thk)
                    and assigned_thk > 0.0
                )
                if not is_thk_valid:
                    result.add_failure(
                        FailureObject(
                            error_code=ERR_MAT_INVALID_THICKNESS,
                            severity=Severity.BLOCKING,
                            step_id=self.step_id,
                            component_or_entity=b_name,
                            measured_value=assigned_thk,
                            expected_value="> 0.0 mm",
                            engineering_message=(
                                f"Surface body '{b_name}' requires positive finite shell thickness before meshing, "
                                f"but found {assigned_thk}."
                            ),
                            likely_causes=[
                                "Step 6 failed to assign shell thickness to surface body",
                                "Zero, negative, or infinite thickness assigned in JobSpec",
                            ],
                            suggested_fixes=[
                                f"Assign positive shell thickness to surface body '{b_name}' in JobSpec",
                                "Re-run Step 6 Material Mapping",
                            ],
                            resume_step_id="step_06_materials",
                        )
                    )

        # 6. Verify local refinement named selections and element sizes
        if context.spec.mesh.local_refinements:
            existing_selections = (
                set(context.driver.get_named_selections() or [])
                if hasattr(context.driver, "get_named_selections")
                else set()
            )
            for ref in context.spec.mesh.local_refinements:
                ref_name = getattr(ref, "name", None) or (ref.get("name") if isinstance(ref, dict) else str(ref))
                ref_selection = getattr(ref, "selection", None) or (ref.get("selection") if isinstance(ref, dict) else "")
                ref_size = getattr(ref, "element_size", None) or (ref.get("element_size") if isinstance(ref, dict) else None)

                if ref_selection not in existing_selections:
                    expected_str = (
                        f"One of {sorted(existing_selections)}"
                        if existing_selections
                        else "Existing named selection in model (none found)"
                    )
                    result.add_failure(
                        FailureObject(
                            error_code=ERR_MESH_MISSING_SELECTION,
                            severity=Severity.BLOCKING,
                            step_id=self.step_id,
                            component_or_entity=ref_name,
                            measured_value=ref_selection,
                            expected_value=expected_str,
                            engineering_message=(
                                f"Local mesh refinement '{ref_name}' references non-existent "
                                f"named selection '{ref_selection}'."
                            ),
                            likely_causes=[
                                f"Named selection '{ref_selection}' not created in Step 3",
                                f"Typo in named selection identifier '{ref_selection}'",
                            ],
                            suggested_fixes=[
                                f"Create named selection '{ref_selection}' in Mechanical model",
                                f"Update refinement '{ref_name}' in JobSpec to reference an existing selection",
                            ],
                            resume_step_id="step_03_named_selections",
                        )
                    )

                if _resolve_numeric_threshold(ref_size, min_val=1e-6) is None:
                    result.add_failure(
                        FailureObject(
                            error_code=ERR_MESH_SPEC_MISSING,
                            severity=Severity.BLOCKING,
                            step_id=self.step_id,
                            component_or_entity=ref_name,
                            measured_value=ref_size,
                            expected_value="> 0.0 mm",
                            engineering_message=(
                                f"Local mesh refinement '{ref_name}' requires positive finite element size, "
                                f"but found {ref_size}."
                            ),
                            likely_causes=[
                                "Non-positive, NaN, infinite, or non-numeric element size in local refinement",
                            ],
                            suggested_fixes=[
                                f"Set element_size for refinement '{ref_name}' to a positive finite value",
                            ],
                            resume_step_id=self.step_id,
                        )
                    )

        return result

    def execute(self, context: RunContext) -> None:
        """
        Phase 2: Apply mesh controls and trigger mesh generation.

        1. Verifies driver connection.
        2. Applies global mesh size.
        3. Applies element formulation order.
        4. Applies all local mesh refinements from JobSpec.
        5. Triggers solver mesh generation.
        """
        if context.driver is None or (hasattr(context.driver, "is_connected") and not context.driver.is_connected()):
            raise ConnectionError("Mechanical driver is not connected.")

        if context.spec.mesh is None:
            raise ValueError("JobSpec mesh settings are missing.")

        mesh_spec = context.spec.mesh

        # 1. Apply global mesh sizing
        context.driver.set_global_mesh_size(mesh_spec.global_size)

        # 2. Apply element order
        context.driver.set_element_order(str(mesh_spec.element_order))

        # 3. Apply local mesh refinements
        for ref in mesh_spec.local_refinements:
            ref_name = getattr(ref, "name", None) or (ref.get("name") if isinstance(ref, dict) else str(ref))
            ref_selection = getattr(ref, "selection", None) or (ref.get("selection") if isinstance(ref, dict) else "")
            ref_size = getattr(ref, "element_size", None) or (ref.get("element_size") if isinstance(ref, dict) else 0.0)
            context.driver.add_local_refinement(
                name=ref_name,
                selection=ref_selection,
                element_size=float(ref_size),
            )

        # 4. Trigger mesh generation via driver
        stats = context.driver.generate_mesh(
            global_size=mesh_spec.global_size,
            element_order=str(mesh_spec.element_order),
            local_refinements=mesh_spec.local_refinements,
        )

        if context.step_data is not None:
            context.step_data["mesh_statistics"] = stats

    def post_check(self, context: RunContext) -> StepCheckResult:
        """
        Phase 3: Inspect driver mesh quality metrics against specification thresholds.

        Verifies:
        1. Driver connection is live.
        2. Mesh has been successfully generated.
        3. Element count is positive and satisfies bounds.
        4. Maximum skewness satisfies quality threshold.
        5. Maximum aspect ratio satisfies quality threshold.
        6. Maximum warpage satisfies quality threshold.
        """
        result = StepCheckResult(step_id=self.step_id)

        # 1. Driver connection verification
        if context.driver is None or (hasattr(context.driver, "is_connected") and not context.driver.is_connected()):
            result.add_failure(
                FailureObject(
                    error_code=ERR_DRIVER_COMMUNICATION,
                    severity=Severity.BLOCKING,
                    step_id=self.step_id,
                    component_or_entity="MechanicalDriver",
                    measured_value="Disconnected",
                    expected_value="Connected",
                    engineering_message="Mechanical driver is not connected during post-check.",
                    likely_causes=[
                        "Solver process crashed or terminated during meshing",
                        "Network timeout or gRPC communication drop",
                    ],
                    suggested_fixes=["Reconnect driver port to Mechanical instance"],
                    resume_step_id=self.step_id,
                )
            )
            return result

        # 2. Check mesh generation status
        if hasattr(context.driver, "is_mesh_generated") and not context.driver.is_mesh_generated():
            result.add_failure(
                FailureObject(
                    error_code=ERR_MESH_GENERATION_FAILED,
                    severity=Severity.BLOCKING,
                    step_id=self.step_id,
                    component_or_entity="MechanicalMesh",
                    measured_value="Not Generated",
                    expected_value="Generated",
                    engineering_message="Mesh generation failed or produced zero elements.",
                    likely_causes=[
                        "Geometry features too small for specified mesh sizing",
                        "Conflicting local mesh refinements or unmeshable topology",
                        "Solver meshing kernel error or memory exhaustion",
                    ],
                    suggested_fixes=[
                        "Adjust global mesh size to capture geometry features",
                        "Inspect CAD geometry for sliver faces or knife edges",
                        "Review solver meshing diagnostics log",
                    ],
                    resume_step_id=self.step_id,
                )
            )
            return result

        mesh_spec = context.spec.mesh
        quality_limits = mesh_spec.quality_limits if mesh_spec else None

        # 3. Element count validation
        elem_count = context.driver.get_element_count()
        raw_min_elem = quality_limits.min_elements if quality_limits else None
        min_elem_resolved = _resolve_numeric_threshold(raw_min_elem, min_val=1.0)
        min_elements = int(min_elem_resolved) if min_elem_resolved is not None else 1

        raw_max_elem = quality_limits.max_elements if quality_limits else None
        max_elem_resolved = _resolve_numeric_threshold(raw_max_elem, min_val=1.0)
        max_elements = int(max_elem_resolved) if max_elem_resolved is not None else None

        is_elem_count_valid = (
            elem_count is not None
            and isinstance(elem_count, (int, float))
            and not isinstance(elem_count, bool)
            and not math.isnan(elem_count)
            and not math.isinf(elem_count)
            and elem_count >= 1
        )

        if not is_elem_count_valid or elem_count < min_elements:
            result.add_failure(
                FailureObject(
                    error_code=ERR_MESH_ELEMENT_COUNT,
                    severity=Severity.BLOCKING,
                    step_id=self.step_id,
                    component_or_entity="MechanicalMesh",
                    measured_value=elem_count,
                    expected_value=f">= {min_elements}",
                    engineering_message=(
                        f"Mesh element count {elem_count} is below required minimum of {min_elements}."
                        if is_elem_count_valid
                        else f"Mesh element count is invalid ({elem_count}), expected >= {min_elements}."
                    ),
                    likely_causes=[
                        "Mesh generation failed silently or produced incomplete mesh",
                        "Global element size too large for geometry volume",
                    ],
                    suggested_fixes=[
                        "Reduce global mesh size in JobSpec",
                        "Ensure all geometry bodies are unsuppressed and meshable",
                    ],
                    resume_step_id=self.step_id,
                )
            )
        elif max_elements is not None and elem_count > max_elements:
            result.add_failure(
                FailureObject(
                    error_code=ERR_MESH_ELEMENT_COUNT,
                    severity=Severity.WARNING,
                    step_id=self.step_id,
                    component_or_entity="MechanicalMesh",
                    measured_value=elem_count,
                    expected_value=f"<= {max_elements}",
                    engineering_message=(
                        f"Mesh element count {elem_count} exceeds recommended maximum of {max_elements}."
                    ),
                    likely_causes=[
                        "Element size too fine, causing solver solve time inflation",
                        "Overly aggressive local refinement settings",
                    ],
                    suggested_fixes=[
                        "Increase global element size",
                        "Relax local mesh refinement sizes",
                    ],
                    resume_step_id=self.step_id,
                )
            )

        # 4. Resolve quality metric thresholds
        # Skewness threshold resolution:
        # Priority: quality_limits.max_skewness -> mesh.max_skewness -> tolerances.mesh_skewness_limit ->
        #           quality_limits.min_quality (if explicitly defined for skewness) ->
        #           mesh.min_quality (if skewness metric) ->
        #           quality_limits.min_quality (default for skewness) ->
        #           default 0.85
        ql_max_skew = _resolve_numeric_threshold(quality_limits.max_skewness, 0.0, 1.0) if quality_limits else None
        mesh_max_skew = _resolve_numeric_threshold(mesh_spec.max_skewness, 0.0, 1.0) if mesh_spec else None
        tol_max_skew = (
            _resolve_numeric_threshold(context.spec.tolerances.mesh_skewness_limit, 0.0, 1.0)
            if context.spec.tolerances
            else None
        )

        ql_raw_min_q = _resolve_numeric_threshold(quality_limits.min_quality, 0.0, 1.0) if quality_limits else None
        mesh_raw_min_q = _resolve_numeric_threshold(mesh_spec.min_quality, 0.0, 1.0) if mesh_spec else None

        ql_explicit_min_qual = (
            quality_limits is not None
            and ql_raw_min_q is not None
            and (not hasattr(quality_limits, "model_fields_set") or "min_quality" in quality_limits.model_fields_set)
            and (
                str(quality_limits.metric).strip().lower() == "skewness"
                or (quality_limits.metric is None and mesh_spec and str(mesh_spec.quality_metric).strip().lower() == "skewness")
            )
        )
        mesh_has_min_qual = (
            mesh_spec is not None
            and mesh_raw_min_q is not None
            and str(mesh_spec.quality_metric).strip().lower() == "skewness"
        )

        if ql_max_skew is not None:
            skew_thresh = ql_max_skew
        elif mesh_max_skew is not None:
            skew_thresh = mesh_max_skew
        elif tol_max_skew is not None:
            skew_thresh = tol_max_skew
        elif ql_explicit_min_qual and ql_raw_min_q is not None:
            skew_thresh = 1.0 - ql_raw_min_q
        elif mesh_has_min_qual and mesh_raw_min_q is not None:
            skew_thresh = 1.0 - mesh_raw_min_q
        elif (
            quality_limits
            and ql_raw_min_q is not None
            and (
                str(quality_limits.metric).strip().lower() == "skewness"
                or (quality_limits.metric is None and mesh_spec and str(mesh_spec.quality_metric).strip().lower() == "skewness")
            )
        ):
            skew_thresh = 1.0 - ql_raw_min_q
        else:
            skew_thresh = 0.85

        # Aspect ratio threshold resolution:
        # Priority: quality_limits.max_aspect_ratio -> mesh.max_aspect_ratio -> tolerances.mesh_aspect_ratio_limit -> default 10.0
        ql_max_aspect = _resolve_numeric_threshold(quality_limits.max_aspect_ratio, 1.0) if quality_limits else None
        mesh_max_aspect = _resolve_numeric_threshold(mesh_spec.max_aspect_ratio, 1.0) if mesh_spec else None
        tol_max_aspect = (
            _resolve_numeric_threshold(context.spec.tolerances.mesh_aspect_ratio_limit, 1.0)
            if context.spec.tolerances
            else None
        )

        if ql_max_aspect is not None:
            aspect_thresh = ql_max_aspect
        elif mesh_max_aspect is not None:
            aspect_thresh = mesh_max_aspect
        elif tol_max_aspect is not None:
            aspect_thresh = tol_max_aspect
        else:
            aspect_thresh = 10.0

        # Warpage threshold resolution:
        # Priority: quality_limits.max_warpage -> mesh.max_warpage -> tolerances.mesh_warpage_limit -> default 45.0 degrees
        ql_max_warp = _resolve_numeric_threshold(quality_limits.max_warpage, 0.0) if quality_limits else None
        mesh_max_warp = _resolve_numeric_threshold(mesh_spec.max_warpage, 0.0) if mesh_spec else None
        tol_max_warp = (
            _resolve_numeric_threshold(context.spec.tolerances.mesh_warpage_limit, 0.0)
            if context.spec.tolerances
            else None
        )

        if ql_max_warp is not None:
            warp_thresh = ql_max_warp
        elif mesh_max_warp is not None:
            warp_thresh = mesh_max_warp
        elif tol_max_warp is not None:
            warp_thresh = tol_max_warp
        else:
            warp_thresh = 45.0

        # 5. Inspect skewness
        max_skew = context.driver.get_max_skewness()
        is_skew_valid = (
            max_skew is not None
            and isinstance(max_skew, (int, float))
            and not isinstance(max_skew, bool)
            and not math.isnan(max_skew)
            and not math.isinf(max_skew)
            and max_skew >= 0.0
        )
        if not is_skew_valid or max_skew > skew_thresh:
            raw_failing: list[int] = []
            if hasattr(context.driver, "get_failing_elements"):
                try:
                    failing_res = context.driver.get_failing_elements("skewness", skew_thresh)
                    if failing_res is not None:
                        raw_failing = list(failing_res)
                except Exception:
                    raw_failing = []
            elem_desc = f"Elements {raw_failing}" if raw_failing else "Global Mesh"
            measured_repr = f"{max_skew:.4f}" if is_skew_valid else str(max_skew)
            msg = (
                f"Maximum element skewness {measured_repr} exceeds allowable threshold "
                f"{skew_thresh:.4f} on {elem_desc}."
                if is_skew_valid
                else f"Maximum element skewness is invalid ({measured_repr}) on {elem_desc}, expected <= {skew_thresh:.4f}."
            )
            result.add_failure(
                FailureObject(
                    error_code=ERR_MESH_SKEWNESS_EXCEEDED,
                    severity=Severity.BLOCKING,
                    step_id=self.step_id,
                    component_or_entity=elem_desc,
                    measured_value=max_skew,
                    expected_value=f"<= {skew_thresh:.4f}",
                    engineering_message=msg,
                    likely_causes=[
                        "Distorted elements near high curvature fillets or acute corners",
                        "Coarse mesh transition between disparate shell thicknesses",
                        "Poor surface midsurface trimming or sliver surfaces in CAD",
                    ],
                    suggested_fixes=[
                        f"Apply local mesh refinement with smaller element size on named selection around {elem_desc}",
                        "Reduce global mesh size in JobSpec",
                        "Enable quad-dominant or triangle transition meshing in curvature zones",
                    ],
                    resume_step_id=self.step_id,
                )
            )

        # 6. Inspect aspect ratio
        max_aspect = context.driver.get_max_aspect_ratio()
        is_aspect_valid = (
            max_aspect is not None
            and isinstance(max_aspect, (int, float))
            and not isinstance(max_aspect, bool)
            and not math.isnan(max_aspect)
            and not math.isinf(max_aspect)
            and max_aspect >= 1.0
        )
        if not is_aspect_valid or max_aspect > aspect_thresh:
            raw_failing = []
            if hasattr(context.driver, "get_failing_elements"):
                try:
                    failing_res = context.driver.get_failing_elements("aspect_ratio", aspect_thresh)
                    if failing_res is not None:
                        raw_failing = list(failing_res)
                except Exception:
                    raw_failing = []
            elem_desc = f"Elements {raw_failing}" if raw_failing else "Global Mesh"
            measured_repr = f"{max_aspect:.2f}" if is_aspect_valid else str(max_aspect)
            msg = (
                f"Maximum element aspect ratio {measured_repr} exceeds allowable threshold "
                f"{aspect_thresh:.2f} on {elem_desc}."
                if is_aspect_valid
                else f"Maximum element aspect ratio is invalid ({measured_repr}) on {elem_desc}, expected <= {aspect_thresh:.2f}."
            )
            result.add_failure(
                FailureObject(
                    error_code=ERR_MESH_ASPECT_RATIO_EXCEEDED,
                    severity=Severity.BLOCKING,
                    step_id=self.step_id,
                    component_or_entity=elem_desc,
                    measured_value=max_aspect,
                    expected_value=f"<= {aspect_thresh:.2f}",
                    engineering_message=msg,
                    likely_causes=[
                        "Elongated elements along narrow strips or thin features",
                        "Coarse mesh along high-aspect CAD faces",
                        "Anisotropic sizing without curvature adaptation",
                    ],
                    suggested_fixes=[
                        f"Apply local mesh refinement on named selection around {elem_desc}",
                        "Reduce global mesh size in JobSpec",
                        "Split long narrow faces in CAD model",
                    ],
                    resume_step_id=self.step_id,
                )
            )

        # 7. Inspect warpage
        max_warp = context.driver.get_max_warpage()
        is_warp_valid = (
            max_warp is not None
            and isinstance(max_warp, (int, float))
            and not isinstance(max_warp, bool)
            and not math.isnan(max_warp)
            and not math.isinf(max_warp)
            and max_warp >= 0.0
        )
        if not is_warp_valid or max_warp > warp_thresh:
            raw_failing = []
            if hasattr(context.driver, "get_failing_elements"):
                try:
                    failing_res = context.driver.get_failing_elements("warpage", warp_thresh)
                    if failing_res is not None:
                        raw_failing = list(failing_res)
                except Exception:
                    raw_failing = []
            elem_desc = f"Elements {raw_failing}" if raw_failing else "Global Mesh"
            measured_repr = f"{max_warp:.1f}" if is_warp_valid else str(max_warp)
            msg = (
                f"Maximum element warpage {measured_repr} deg exceeds allowable threshold "
                f"{warp_thresh:.1f} deg on {elem_desc}."
                if is_warp_valid
                else f"Maximum element warpage is invalid ({measured_repr}) on {elem_desc}, expected <= {warp_thresh:.1f} deg."
            )
            result.add_failure(
                FailureObject(
                    error_code=ERR_MESH_WARPAGE_EXCEEDED,
                    severity=Severity.BLOCKING,
                    step_id=self.step_id,
                    component_or_entity=elem_desc,
                    measured_value=max_warp,
                    expected_value=f"<= {warp_thresh:.1f} deg",
                    engineering_message=msg,
                    likely_causes=[
                        "Quad shell elements mapped across non-planar or doubly-curved surfaces",
                        "Coarse mesh on twisted geometry",
                        "Mid-surface extraction deviation",
                    ],
                    suggested_fixes=[
                        f"Refine mesh size on curved regions near {elem_desc} to improve planarity",
                        "Switch element shape to triangles or split warped quads",
                        "Add local mesh refinement on non-planar named selections",
                    ],
                    resume_step_id=self.step_id,
                )
            )

        return result

    def troubleshoot(
        self, context: RunContext, check_result: StepCheckResult
    ) -> list[FailureObject]:
        """Phase 4: Return structured FailureObjects identifying failing element sets and recommended local refinement actions."""
        if check_result is None or not hasattr(check_result, "failures") or check_result.failures is None:
            return []
        return [f for f in check_result.failures if isinstance(f, FailureObject)]


# Alias Step08MeshingAutomation for architectural flexibility
Step08MeshingAutomation = Step08Meshing

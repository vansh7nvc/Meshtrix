"""
Meshtrix Step 6: Material Mapping and Shell Thickness Automation.

Authoritative Reference: ORIGINAL_REQUEST.md §R3 & PROJECT.md
"""

from typing import cast

from meshtrix.core.step import BaseStep, RunContext
from meshtrix.diagnostics.failure import (
    ERR_DRIVER_COMMUNICATION,
    ERR_MAT_ASSIGNMENT_MISMATCH,
    ERR_MAT_INVALID_THICKNESS,
    ERR_MAT_MISSING_CATALOG,
    ERR_MAT_THICKNESS_MISMATCH,
    ERR_MAT_UNASSIGNED_BODY,
    ERR_MAT_UNMAPPED_BODY,
    FailureObject,
    Severity,
    StepCheckResult,
)
from meshtrix.drivers.base import BodyProperties


class Step06MaterialMapping(BaseStep):
    """Step 6: Material registration, assignment, and shell thickness validation."""

    @property
    def step_id(self) -> str:
        """Step identifier."""
        return "step_06_materials"

    @property
    def description(self) -> str:
        """Step description."""
        return "Step 6: Material Mapping & Properties"

    def pre_check(self, context: RunContext) -> StepCheckResult:
        """
        Phase 1: Validate prerequisites before applying mutations.

        Verifies:
        1. Driver connection is live.
        2. Every CAD body in the model has a matching material mapping in JobSpec.
        3. Every assigned material exists in the materials catalog.
        4. Every surface/shell body in the model has a positive thickness (> 0.0).
        """
        result = StepCheckResult(step_id=self.step_id)

        # 1. Driver connection verification
        if hasattr(context.driver, "is_connected") and not context.driver.is_connected():
            result.add_failure(
                FailureObject(
                    error_code=ERR_DRIVER_COMMUNICATION,
                    severity=Severity.BLOCKING,
                    step_id=self.step_id,
                    component_or_entity="MechanicalDriver",
                    measured_value="Disconnected",
                    expected_value="Connected",
                    engineering_message="Mechanical driver is not connected.",
                    likely_causes=["Solver process crashed or failed to start", "Network timeout"],
                    suggested_fixes=["Reconnect driver port to Mechanical instance"],
                    resume_step_id=self.step_id,
                )
            )
            return result

        model_bodies = cast(list[BodyProperties], context.driver.get_bodies())
        spec_mappings = context.spec.materials.mappings
        spec_catalog = context.spec.materials.catalog

        # 2. Check all CAD bodies in model have a mapping in JobSpec
        for body in model_bodies:
            if body.name not in spec_mappings:
                result.add_failure(
                    FailureObject(
                        error_code=ERR_MAT_UNMAPPED_BODY,
                        severity=Severity.BLOCKING,
                        step_id=self.step_id,
                        component_or_entity=body.name,
                        measured_value=None,
                        expected_value="Mapped in JobSpec",
                        engineering_message=(
                            f"Body '{body.name}' present in CAD model has no material mapping in JobSpec."
                        ),
                        likely_causes=[
                            "CAD model revision introduced a new or renamed body",
                            "Unlisted body in JobSpec materials.mappings",
                        ],
                        suggested_fixes=[
                            f"Add body mapping for '{body.name}' in JobSpec materials.mappings",
                            "Remove or suppress unexpected body in CAD model",
                        ],
                        resume_step_id=self.step_id,
                    )
                )

        # 3. Check surface bodies have positive thickness specified
        for body in model_bodies:
            if body.name in spec_mappings:
                mapping = spec_mappings[body.name]
                if body.body_type == "surface" and (
                    mapping.thickness is None or mapping.thickness <= 0.0
                ):
                    result.add_failure(
                        FailureObject(
                            error_code=ERR_MAT_INVALID_THICKNESS,
                            severity=Severity.BLOCKING,
                            step_id=self.step_id,
                            component_or_entity=body.name,
                            measured_value=mapping.thickness,
                            expected_value="> 0.0 mm",
                            engineering_message=(
                                f"Surface body '{body.name}' requires positive shell thickness, "
                                f"but thickness is {mapping.thickness}."
                            ),
                            likely_causes=[
                                "CAD export mid-surface thickness attribute missing",
                                "JobSpec mapping has null or non-positive thickness",
                            ],
                            suggested_fixes=[
                                f"Specify a positive thickness for surface body '{body.name}' in JobSpec",
                            ],
                            resume_step_id=self.step_id,
                        )
                    )

        # Also check for any mapping with non-positive thickness regardless of body type
        for body_name, mapping in spec_mappings.items():
            if (
                mapping.thickness is not None
                and mapping.thickness <= 0.0
                and not any(
                    f.component_or_entity == body_name and f.error_code == ERR_MAT_INVALID_THICKNESS
                    for f in result.failures
                )
            ):
                result.add_failure(
                    FailureObject(
                        error_code=ERR_MAT_INVALID_THICKNESS,
                        severity=Severity.BLOCKING,
                        step_id=self.step_id,
                        component_or_entity=body_name,
                        measured_value=mapping.thickness,
                        expected_value="> 0.0 mm",
                        engineering_message=(
                            f"Body '{body_name}' has invalid non-positive thickness {mapping.thickness}."
                        ),
                        likely_causes=["Non-positive thickness specified in JobSpec"],
                        suggested_fixes=[f"Set thickness for '{body_name}' to > 0.0"],
                        resume_step_id=self.step_id,
                    )
                )

        # 4. Check all assigned materials exist in the catalog
        for body_name, mapping in spec_mappings.items():
            if mapping.material_name not in spec_catalog:
                result.add_failure(
                    FailureObject(
                        error_code=ERR_MAT_MISSING_CATALOG,
                        severity=Severity.BLOCKING,
                        step_id=self.step_id,
                        component_or_entity=body_name,
                        measured_value=mapping.material_name,
                        expected_value="Valid catalog material",
                        engineering_message=(
                            f"Material '{mapping.material_name}' assigned to body '{body_name}' "
                            f"is not defined in the materials catalog."
                        ),
                        likely_causes=[
                            f"Typo in material name '{mapping.material_name}'",
                            "Material definition missing from materials.catalog",
                        ],
                        suggested_fixes=[
                            f"Add material '{mapping.material_name}' to JobSpec materials.catalog",
                            f"Update body '{body_name}' to reference an existing catalog material",
                        ],
                        resume_step_id=self.step_id,
                    )
                )

        return result

    def execute(self, context: RunContext) -> None:
        """
        Phase 2: Apply material and shell thickness mutations.

        1. Registers all material cards from the catalog into the driver.
        2. Assigns specified materials to CAD bodies.
        3. Assigns shell thicknesses to surface bodies.
        """
        # Register all catalog materials
        for mat_name, mat_entry in context.spec.materials.catalog.items():
            context.driver.register_material(mat_name, mat_entry)

        model_bodies = {b.name: b for b in context.driver.get_bodies()}

        # Apply assignments to bodies
        for body_name, mapping in context.spec.materials.mappings.items():
            if body_name in model_bodies:
                context.driver.assign_material(body_name, mapping.material_name)
                body = model_bodies[body_name]
                if body.body_type == "surface" and mapping.thickness is not None:
                    context.driver.set_shell_thickness(body_name, mapping.thickness)

    def post_check(self, context: RunContext) -> StepCheckResult:
        """
        Phase 3: Inspect driver state and verify against input specification.

        Verifies:
        1. Every CAD body has a material assigned.
        2. Assigned material strictly matches the specification.
        3. Assigned shell thickness on surface bodies matches specification within tolerance.
        """
        result = StepCheckResult(step_id=self.step_id)
        model_bodies = cast(list[BodyProperties], context.driver.get_bodies())
        spec_mappings = context.spec.materials.mappings
        tol = context.spec.tolerances.thickness_tolerance if context.spec.tolerances else 0.01

        for body in model_bodies:
            mapping = spec_mappings.get(body.name)
            if mapping is None:
                continue

            # Verify material assignment
            assigned_mat = context.driver.get_assigned_material(body.name)
            if not assigned_mat:
                result.add_failure(
                    FailureObject(
                        error_code=ERR_MAT_UNASSIGNED_BODY,
                        severity=Severity.BLOCKING,
                        step_id=self.step_id,
                        component_or_entity=body.name,
                        measured_value=None,
                        expected_value=mapping.material_name,
                        engineering_message=f"Body '{body.name}' has no material assigned in Mechanical model.",
                        likely_causes=[
                            "Driver failed to apply material assignment",
                            "Body was skipped during execution",
                        ],
                        suggested_fixes=[f"Re-run material assignment for body '{body.name}'"],
                        resume_step_id=self.step_id,
                    )
                )
            elif assigned_mat != mapping.material_name:
                result.add_failure(
                    FailureObject(
                        error_code=ERR_MAT_ASSIGNMENT_MISMATCH,
                        severity=Severity.BLOCKING,
                        step_id=self.step_id,
                        component_or_entity=body.name,
                        measured_value=assigned_mat,
                        expected_value=mapping.material_name,
                        engineering_message=(
                            f"Material assignment mismatch on body '{body.name}': "
                            f"driver has '{assigned_mat}', expected '{mapping.material_name}'."
                        ),
                        likely_causes=[
                            "Mechanical driver applied incorrect material",
                            "Fault injection or external script overwrote material",
                        ],
                        suggested_fixes=[f"Assign '{mapping.material_name}' to body '{body.name}'"],
                        resume_step_id=self.step_id,
                    )
                )

            # Verify shell thickness for surface bodies
            if body.body_type == "surface" and mapping.thickness is not None:
                assigned_thk = context.driver.get_shell_thickness(body.name)
                expected_thk = mapping.thickness
                if assigned_thk is None or abs(assigned_thk - expected_thk) > tol:
                    result.add_failure(
                        FailureObject(
                            error_code=ERR_MAT_THICKNESS_MISMATCH,
                            severity=Severity.BLOCKING,
                            step_id=self.step_id,
                            component_or_entity=body.name,
                            measured_value=assigned_thk,
                            expected_value=expected_thk,
                            engineering_message=(
                                f"Shell thickness mismatch on surface body '{body.name}': "
                                f"driver has {assigned_thk}, expected {expected_thk} within tolerance {tol}."
                            ),
                            likely_causes=[
                                "CAD export mid-surface thickness attribute missing",
                                "Fault injection or driver thickness corruption",
                                "Tolerance threshold exceeded",
                            ],
                            suggested_fixes=[
                                f"Update thickness for '{body.name}' in JobSpec or driver to {expected_thk}",
                                f"Adjust thickness tolerance threshold ({tol}) in JobSpec",
                            ],
                            resume_step_id=self.step_id,
                        )
                    )

        return result

    def troubleshoot(
        self, context: RunContext, check_result: StepCheckResult
    ) -> list[FailureObject]:
        """Phase 4: Return isolated failures with actionable remediation metadata."""
        return list(check_result.failures)


# Alias Step06Materials for architectural flexibility
Step06Materials = Step06MaterialMapping

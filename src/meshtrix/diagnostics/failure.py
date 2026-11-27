"""
Meshtrix Diagnostics, Severity Tiers, FailureObject, and StepCheckResult.

Authoritative Reference: ORIGINAL_REQUEST.md §R2 & PROJECT.md
"""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class Severity(StrEnum):
    """Failure severity tiers governing workflow execution."""

    BLOCKING = "blocking"
    WARNING = "warning"
    AUTO_RECOVERABLE = "auto_recoverable"


# Standard FEA Automation Harness Error Codes
ERR_MAT_UNMAPPED_BODY = "ERR_MAT_UNMAPPED_BODY"
ERR_MAT_MISSING_CATALOG = "ERR_MAT_MISSING_CATALOG"
ERR_MAT_NOT_FOUND_IN_CATALOG = "ERR_MAT_MISSING_CATALOG"
ERR_MAT_INVALID_THICKNESS = "ERR_MAT_INVALID_THICKNESS"
ERR_MAT_THICKNESS_MISMATCH = "ERR_MAT_THICKNESS_MISMATCH"
ERR_MAT_ASSIGNMENT_MISMATCH = "ERR_MAT_ASSIGNMENT_MISMATCH"
ERR_MAT_UNASSIGNED_BODY = "ERR_MAT_UNASSIGNED_BODY"
ERR_DRIVER_COMMUNICATION = "ERR_DRIVER_COMMUNICATION"
ERR_PRECHECK_FAILED = "ERR_PRECHECK_FAILED"
ERR_POSTCHECK_FAILED = "ERR_POSTCHECK_FAILED"

# Mesh Automation Error Codes (Step 8)
ERR_MESH_SPEC_MISSING = "ERR_MESH_SPEC_MISSING"
ERR_MESH_NO_BODIES = "ERR_MESH_NO_BODIES"
ERR_MESH_GENERATION_FAILED = "ERR_MESH_GENERATION_FAILED"
ERR_MESH_ELEMENT_COUNT = "ERR_MESH_ELEMENT_COUNT"
ERR_MESH_SKEWNESS_EXCEEDED = "ERR_MESH_SKEWNESS_EXCEEDED"
ERR_MESH_ASPECT_RATIO_EXCEEDED = "ERR_MESH_ASPECT_RATIO_EXCEEDED"
ERR_MESH_WARPAGE_EXCEEDED = "ERR_MESH_WARPAGE_EXCEEDED"
ERR_MESH_MISSING_SELECTION = "ERR_MESH_MISSING_SELECTION"

# Boundary Condition Error Codes (Step 9)
ERR_BC_MISSING_SELECTION = "ERR_BC_MISSING_SELECTION"
ERR_BC_EMPTY_SELECTION = "ERR_BC_EMPTY_SELECTION"
ERR_BC_MISSING_SUPPORT = "ERR_BC_MISSING_SUPPORT"
ERR_BC_SCOPING_MISMATCH = "ERR_BC_SCOPING_MISMATCH"
ERR_BC_DOF_MISMATCH = "ERR_BC_DOF_MISMATCH"
ERR_BC_COORDINATE_SYSTEM_MISMATCH = "ERR_BC_COORDINATE_SYSTEM_MISMATCH"
ERR_BC_INVALID_SPEC = "ERR_BC_INVALID_SPEC"

# Applied Load Error Codes (Step 10)
ERR_LOAD_MISSING_SELECTION = "ERR_LOAD_MISSING_SELECTION"
ERR_LOAD_EMPTY_SELECTION = "ERR_LOAD_EMPTY_SELECTION"
ERR_LOAD_MISSING_LOAD = "ERR_LOAD_MISSING_LOAD"
ERR_LOAD_TOTAL_MISMATCH = "ERR_LOAD_TOTAL_MISMATCH"
ERR_LOAD_DIRECTION_MISMATCH = "ERR_LOAD_DIRECTION_MISMATCH"
ERR_LOAD_SIGN_MISMATCH = "ERR_LOAD_SIGN_MISMATCH"
ERR_LOAD_COORDINATE_SYSTEM_MISMATCH = "ERR_LOAD_COORDINATE_SYSTEM_MISMATCH"
ERR_LOAD_INVALID_SPEC = "ERR_LOAD_INVALID_SPEC"


class FailureObject(BaseModel):
    """Structured diagnostic failure object with root cause analysis and remediation guidance."""

    error_code: str
    severity: Severity
    step_id: str
    component_or_entity: str
    measured_value: Any = None
    expected_value: Any = None
    engineering_message: str
    likely_causes: list[str] = Field(default_factory=list)
    suggested_fixes: list[str] = Field(default_factory=list)
    resume_step_id: str | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class StepCheckResult(BaseModel):
    """Container aggregating check status, failures, and non-fatal warnings."""

    passed: bool = True
    failures: list[FailureObject] = Field(default_factory=list)
    warnings: list[Any] = Field(default_factory=list)
    step_id: str = ""

    @property
    def is_successful(self) -> bool:
        """True if the check passed and has no blocking failures."""
        return self.passed and not self.has_blocking()

    def add_failure(self, failure: FailureObject) -> None:
        """Register a failure object and update passed status if blocking."""
        self.failures.append(failure)
        if failure.severity == Severity.BLOCKING:
            self.passed = False

    def add_warning(self, warning: Any) -> None:
        """Register a non-fatal warning."""
        self.warnings.append(warning)

    def has_blocking(self) -> bool:
        """Check whether any recorded failure has BLOCKING severity."""
        return any(f.severity == Severity.BLOCKING for f in self.failures)

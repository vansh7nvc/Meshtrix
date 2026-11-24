# Meshtrix FEA Automation Harness: Test Infrastructure & Verification Architecture

## 1. Executive Summary & Purpose

This document establishes the test infrastructure, test architecture, oracle definitions, and quality verification matrix for the **Meshtrix FEA Automation Harness (Phase 1 & Step 6 Material Mapping)**.

The testing philosophy adheres strictly to the core principle established in `ORIGINAL_REQUEST.md`:
> **"The LLM plans and explains. Deterministic, tested code touches the model."**

All test suites are **opaque-box**, **requirement-driven**, and **isolated**, verifying system behavior against physical engineering specifications and interface contracts rather than implementation internals.

---

## 2. Testing Architecture: The 4-Tier Pyramid

The test infrastructure is stratified into 4 distinct verification tiers:

```
                  ▲
                 / \
                /   \     Tier 4: Real-World Application Scenarios
               / Tier\    (Multi-body aerospace/automotive CAD assemblies,
              /   4   \    end-to-end spec execution, troubleshooting recovery)
             /---------\
            /  Tier 3   \  Tier 3: Cross-Feature Integration Combinations
           /             \ (Full Step 6 lifecycle, mock driver mutations, fault injection)
          /---------------\
         /     Tier 2      \ Tier 2: Boundary, Edge & Corner Cases
        /                   \ (Negative thickness, invalid units, missing catalog, unmapped bodies)
       /---------------------\
      /        Tier 1         \ Tier 1: Core Feature Coverage
     /                         \ (JobSpec validation, FailureObject schema, BaseStep ABC, Driver Port)
    ▼---------------------------▼
```

### Tier 1: Core Feature Coverage (Unit & Interface Verification)
- **JobSpec Validation**: Schema parsing, valid units (`Metric_mm`, `MPA`, `MKS`, `SI`), analysis types (`STRUCTURAL_STATIC`, `MODAL`), materials catalog, mesh sizing, load cases, supports, mass target, check tolerances.
- **FailureObject Schema**: Severity levels (`BLOCKING`, `WARNING`, `AUTO_RECOVERABLE`), error code taxonomy, engineering explanation, root cause analysis, actionable suggestions, resume step tracking.
- **StepCheckResult Container**: Aggregation of blocking failures vs non-fatal warnings, boolean status flags, failure retrieval.
- **BaseStep 4-Phase Contract**: Abstract interface validation (`pre_check`, `execute`, `post_check`, `troubleshoot`).
- **MockMechanicalDriver Port Implementation**: In-memory zero-license driver, body queries, material registration, shell thickness assignment, fault injection API.
- **Step 6 Material Mapping Baseline**: Happy-path 4-phase execution on a clean solid/shell CAD model.

### Tier 2: Boundary, Edge & Corner Cases (Adversarial Robustness)
- **Zero & Negative Thickness**: Rejection of `thickness <= 0.0` for shell/surface bodies at both schema and pre-check levels.
- **Invalid Units & Disallowed Analysis Types**: Schema-level rejection of unrecognized unit systems and unapproved analysis modes.
- **Unmapped Bodies**: Pre-check detection when CAD model bodies lack material mapping in JobSpec.
- **Missing Material Catalog Entries**: Pre-check and schema detection when body mappings reference undefined materials.
- **Solid vs Surface Body Distinctions**: Verifying that surface bodies require thickness while solid bodies do not.
- **Tolerance Thresholds**: Validation of exact matches, within-tolerance deviations, and out-of-tolerance deviations (`thickness_tolerance`).
- **Adversarial & Special Strings**: Handling CAD body names with spaces, special characters (`/`, `_`, `#`), and unicode.
- **Empty Model & Empty Catalog Boundaries**: Graceful diagnostic handling when no bodies exist or catalog is empty.

### Tier 3: Cross-Feature Combinations (Integration Workflows)
- **Complete Step 6 Lifecycle Execution**: Sequential execution `pre_check -> execute -> post_check` against `MockMechanicalDriver`.
- **Pre-Check Failure Short-Circuiting**: Ensuring that execution is aborted when pre-checks encounter blocking failures.
- **Post-Check Discrepancy Detection**: Catching driver-level assignment discrepancies or simulation errors.
- **Fault Injection & Automated Troubleshooting**: Injected thickness corruptions and material mismatches trigger `troubleshoot()` producing exact, structured `FailureObject` instances.
- **Mixed Solid & Shell Assemblies**: Concurrent assignment of shell thicknesses to 2D surfaces and material-only properties to 3D solid components.

### Tier 4: Real-World Application Scenarios (System-Level End-to-End)
- **Realistic Aerospace/Automotive CAD Assembly**: Realistic 6-body assembly containing:
  - `Fuselage_Skin_Panel_01` (Surface body: Aluminum 2024-T3, 1.6 mm)
  - `Fuselage_Skin_Panel_02` (Surface body: Aluminum 2024-T3, 2.0 mm)
  - `Frame_Rib_01` (Surface body: Titanium Ti-6Al-4V, 3.2 mm)
  - `Mount_Bracket_Solid` (Solid body: Structural Steel 4340, no thickness)
  - `Support_Gusset` (Surface body: Aluminum 7075-T6, 2.5 mm)
  - `Retainer_Bolt_Cluster` (Solid body: Stainless Steel 316, no thickness)
- **Full End-to-End Automation Flow**: Loading raw spec -> populating CAD model -> Step 6 pre-check -> execution -> post-check verification.
- **Troubleshooting & Auto-Remediation Loop**:
  - Injected scenario: CAD model revision introduces an unmapped rib `Frame_Rib_02` and a typo in material specification (`Alum_2024` instead of `Aluminum_2024_T3`).
  - Step 6 pre-check flags failure -> troubleshooter isolates exact root cause -> remediation updates spec -> re-execution succeeds cleanly.

---

## 3. Test Oracle Definitions

Test oracles define the authoritative expected output for every test case:

| Component | Test Oracle Source | Expected Behavior / Output |
|---|---|---|
| **JobSpec Validation** | `ORIGINAL_REQUEST.md` R2, Pydantic v2 Core | Valid spec returns instance with validated types; invalid spec raises `pydantic.ValidationError` with field-level details. |
| **FailureObject** | Architecture Plan §2.B, `ORIGINAL_REQUEST.md` R2 | Contains `error_code`, `severity` in (`blocking`, `warning`, `auto_recoverable`), `component_or_entity`, `engineering_message`, `likely_causes`, `suggested_fixes`, `resume_step_id`. |
| **StepCheckResult** | `PROJECT.md` Interface Contracts | Boolean status (`passed` / `is_successful`), lists of `failures` and `warnings`. |
| **BaseStep Interface** | `fea_automation_harness_architecture_plan.md` §2.A | Requires implementation of `step_id`, `description`, `pre_check`, `execute`, `post_check`, `troubleshoot`. |
| **MockMechanicalDriver** | Architecture Plan §2.C, R2 | In-memory tracking of bodies, materials, shell thicknesses; provides inspection methods and fault injection. |
| **Step 6 Pre-Check** | `ORIGINAL_REQUEST.md` R3, Phase 2 Build Plan | Fails with `Severity.BLOCKING` if any body in model is missing from mappings or catalog; fails if shell body lacks positive thickness. |
| **Step 6 Execution** | `ORIGINAL_REQUEST.md` R3 | Registers all catalog materials into driver, assigns material to every body, assigns thickness to surface bodies. |
| **Step 6 Post-Check** | `ORIGINAL_REQUEST.md` R3 | Queries driver physical state; asserts assigned material matches spec and thickness matches within tolerance. |
| **Step 6 Troubleshooter** | `ORIGINAL_REQUEST.md` R3 | Produces `FailureObject` with `ERR_MAT_UNMAPPED_BODY`, `ERR_MAT_MISSING_CATALOG`, or `ERR_MAT_THICKNESS_MISMATCH`. |

---

## 4. Test Directory Layout

The tests are organized into isolated, self-contained modules under `tests/`:

```
tests/
├── conftest.py                     # Shared fixtures, factories, CAD assembly generators
├── test_tier1_features.py          # Tier 1: Unit & Interface Feature Coverage
├── test_tier2_boundaries.py        # Tier 2: Boundary, Edge & Corner Cases
├── test_tier3_combinations.py      # Tier 3: Cross-Feature Integration Combinations
├── test_tier4_scenarios.py         # Tier 4: Real-World Application End-to-End Scenarios
├── unit/                           # Layout compliance mappings
│   ├── test_spec_validation.py
│   ├── test_failure_object.py
│   ├── test_mock_driver.py
│   └── test_step_06_materials.py
└── e2e/
    └── test_end_to_end.py
```

---

## 5. Execution Instructions

### Running the Entire Test Suite
```bash
uv run pytest tests/ -v
```

### Running Specific Tiers
```bash
# Tier 1: Core Feature Coverage
uv run pytest tests/test_tier1_features.py -v

# Tier 2: Boundary & Corner Cases
uv run pytest tests/test_tier2_boundaries.py -v

# Tier 3: Cross-Feature Combinations
uv run pytest tests/test_tier3_combinations.py -v

# Tier 4: Real-World Application Scenarios
uv run pytest tests/test_tier4_scenarios.py -v
```

### Running with Coverage & Type Checking
```bash
uv run pytest tests/ --cov=meshtrix --cov-report=term-missing
uv run ruff check tests/
uv run mypy tests/
```

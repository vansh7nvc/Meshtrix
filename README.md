# Meshtrix

**Autonomous Finite Element Analysis (FEA) Automation Harness** for the SpaceClaim → ANSYS Mechanical shell-model workflow.

> **Core Ground Rule:** *"The LLM plans and explains. Deterministic, tested code touches the model."*

Meshtrix takes a schema-validated **JobSpec** (YAML or JSON), executes a fixed, deterministic preprocessing pipeline against a solver port (`MechanicalDriver`), verifies the physical model state after every step, and emits structured engineering diagnostics (`FailureObject`) with checkpoint-based resume support.

---

## Architecture

Meshtrix follows a **Hexagonal (Ports & Adapters)** architecture:

- **Single Source of Truth (`meshtrix.spec`)**: Pydantic v2 `JobSpec` schemas for units, analysis type, material catalogs and body mappings, mesh settings/quality limits, boundary conditions (`fixed`, `pinned`, `frictionless`, `displacement`), load cases (forces, pressures, inertial accelerations), and verification tolerances.
- **4-Phase Step Contract (`meshtrix.core.step.BaseStep`)**:
  1. `pre_check(context) -> StepCheckResult` — validate inputs, driver connectivity, and preconditions prior to mutation.
  2. `execute(context) -> None` — apply mutations strictly through the `MechanicalDriver` port.
  3. `post_check(context) -> StepCheckResult` — read back the actual model state and compare against `JobSpec`.
  4. `troubleshoot(context, check_result) -> list[FailureObject]` — enrich failures with root causes, remediation steps, and `resume_step_id`.
- **Structured Diagnostics (`meshtrix.diagnostics`)**: Typed `FailureObject` records with `BLOCKING`, `WARNING`, and `AUTO_RECOVERABLE` severity tiers.
- **Driver Port (`meshtrix.drivers`)**:
  - `MockMechanicalDriver`: Full in-memory, zero-license simulation engine with state export/import and fault injection for offline development and CI.
  - `PyMechanicalDriver` *(planned)*: Live ANSYS Mechanical adapter via `ansys-mechanical-core`.
- **Orchestration & Auditability (`meshtrix.runner`, `meshtrix.core`)**:
  - `PipelineRunner`: Sequential fail-fast orchestrator (`step_06_materials` → `step_08_meshing` → `step_09_boundary_conditions` → `step_10_loads`).
  - `CheckpointManager`: Per-step JSON checkpoints enabling `--resume-from <step_id>`.
  - `RunLogger`: Structured JSON audit trail recording `spec_version`, `spec_hash`, `tool_versions`, per-step timings, and outcomes.

---

## Implementation Status

| Phase | Scope | Status |
| --- | --- | --- |
| **Phase 1** | Foundations (`JobSpec`, `FailureObject`, `BaseStep`, `MockMechanicalDriver`, Step 6 Materials) | Complete |
| **Phase 2** | Prepared-Model Setup (Step 8 Meshing, Step 9 Boundary Conditions, Step 10 Loads, `PipelineRunner`, Checkpointing, `RunLogger`, `meshtrix` CLI) | Complete |
| **Phase 3** | Solve, Verification Gates, Post-Processing & Engineering Report | Planned |
| **Phase 4** | Model Build Steps (Steps 3, 4, 5, 7: Named Selections, Transfer, Connections, Point Mass) | Planned |
| **Phase 5** | LLM Layer (Google Agent ADK) & Analyst Approval UI | Planned |
| **Phase 6** | Geometry Prep & Health Report (Steps 1 & 2) | Planned |
| **Phase 7** | Enterprise Hardening & Benchmark Regression Suite | Planned |

See [`FEA Automation Harness Incremental Build Plan.md`](FEA%20Automation%20Harness%20Incremental%20Build%20Plan.md) for the full roadmap.

---

## Quickstart

### Prerequisites
- **Python 3.11** (required for PyAnsys / `ansys-mechanical-core` compatibility)
- [`uv`](https://github.com/astral-sh/uv) package manager

### Installation

```bash
git clone https://github.com/vansh7nvc/Meshtrix.git
cd Meshtrix

uv venv --python 3.11
uv sync --all-extras --dev
```

### CLI Usage

```bash
# 1. Validate a JobSpec (YAML or JSON)
uv run meshtrix validate path/to/job_spec.yaml

# 2. Run the pipeline offline using MockMechanicalDriver
uv run meshtrix run path/to/job_spec.yaml --mock --run-id demo_001

# 3. Run with an explicit mock CAD/model state JSON
uv run meshtrix run path/to/job_spec.yaml --mock --mock-state path/to/state.json --run-id demo_002

# 4. Resume a previous run from a specific step
uv run meshtrix run path/to/job_spec.yaml --mock --run-id demo_001 --resume-from step_09_boundary_conditions

# 5. Inspect checkpoints and audit log for a run
uv run meshtrix inspect-run demo_001
```

---

## Project Layout

```text
Meshtrix/
├── .github/workflows/ci.yml      # Multi-platform CI (ubuntu-latest + windows-latest, Python 3.11)
├── pyproject.toml                # Package metadata, Ruff, Mypy (strict), Pytest config
├── src/meshtrix/
│   ├── cli/                      # Typer + Rich CLI (validate, run, inspect-run)
│   ├── core/                     # BaseStep, RunContext, CheckpointManager, RunLogger
│   ├── diagnostics/              # FailureObject, Severity, StepCheckResult, error codes
│   ├── drivers/                  # MechanicalDriver ABC & MockMechanicalDriver
│   ├── runner/                   # PipelineRunner, PipelineResult, StepRegistry
│   ├── spec/                     # Pydantic v2 JobSpec schemas (YAML & JSON)
│   └── steps/                    # Step 06 (Materials), 08 (Meshing), 09 (BCs), 10 (Loads)
└── tests/
    ├── unit/                     # Unit tests for spec, diagnostics, driver, steps, runner, CLI
    └── e2e/                      # Tier 1–4 end-to-end pipeline and fault-recovery suites
```

---

## Development & Verification

All pull requests must pass formatting, linting, strict type checking, and the full test suite on both Ubuntu and Windows:

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy src
uv run pytest
```

Please read [`CONTRIBUTING.md`](CONTRIBUTING.md) for the branching model, PR checklist, and coding standards.

# Contributing to Meshtrix

Thank you for your interest in contributing to **Meshtrix**, an enterprise-grade autonomous Finite Element Analysis (FEA) automation harness. Meshtrix is built with strict architectural standards to ensure robust, deterministic, and verifiable engineering workflows.

---

## Table of Contents
1. [Core Architectural Principles](#core-architectural-principles)
2. [Branching Model](#branching-model)
3. [Issue Linking and Pull Request Process](#issue-linking-and-pull-request-process)
4. [Development Environment Setup](#development-environment-setup)
5. [Code Quality Standards](#code-quality-standards)
6. [Testing Expectations](#testing-expectations)
7. [Submitting Your Changes](#submitting-your-changes)

---

## 1. Core Architectural Principles

All contributions to Meshtrix must strictly comply with our architectural pillars:

- **Hexagonal Architecture (Ports and Adapters)**:
  Domain logic, specification parsing, and diagnostics are decoupled from simulation drivers.
- **4-Phase Step Contract**:
  Every workflow step implements the standard lifecycle:
  1. `pre_check(context) -> StepCheckResult`
  2. `execute(context) -> None`
  3. `post_check(context) -> StepCheckResult`
  4. `troubleshoot(context, check_result) -> list[FailureObject]`
- **Structured Failure Diagnostics**:
  Failures must not raise uncaught generic exceptions during routine validation. Steps must report domain findings as structured `FailureObject` instances with explicit severity tiers (`BLOCKING`, `WARNING`, `AUTO_RECOVERABLE`), entity identifiers, and concrete remediation advice.
- **Offline Mock-First Verification**:
  All features and step logic must be 100% testable without live ANSYS license availability via `MockMechanicalDriver`. Live driver adapters (`ansys-mechanical-core`) are isolated behind the `MechanicalDriver` port.

---

## 2. Branching Model

Meshtrix follows a disciplined Git branching workflow:

- **`main`**:
  - The protected, production-ready branch.
  - Direct commits and forced pushes are strictly forbidden.
  - All changes must arrive via reviewed pull requests passing all CI checks.
- **Feature Branches**:
  - Branch naming: `feature/<feature-name>` or `feature/<issue-number>-<short-description>`.
  - Used for implementing new steps, spec models, or capability additions.
- **Bugfix Branches**:
  - Branch naming: `fix/<issue-number>-<short-description>`.
  - Used for resolving identified defects or unexpected behaviors.
- **Refactoring & Infrastructure Branches**:
  - Branch naming: `refactor/<short-description>` or `chore/<short-description>`.

---

## 3. Issue Linking and Pull Request Process

1. **Find or Open an Issue**:
   - Every pull request must be linked to an approved GitHub issue (bug report or feature request).
   - Use the designated issue templates in `.github/ISSUE_TEMPLATE/`.
2. **Follow the Pull Request Template**:
   - Fill in all sections of `.github/pull_request_template.md`.
   - Explicitly link the issue (e.g., `Fixes #42` or `Closes #15`).
   - Complete the Architectural Ground Rules and Testing checklists.
3. **Review & Merge Protocol**:
   - At least one code review approval from a maintainer is required.
   - All multi-platform CI checks (Ubuntu and Windows on Python 3.11) must pass.
   - Merges are performed via **Squash and Merge** to maintain a clean linear history on `main`.

---

## 4. Development Environment Setup

Meshtrix uses [`uv`](https://github.com/astral-sh/uv) for fast, reproducible dependency management and virtual environment orchestration. Python **3.11** is the required standard runtime.

### Prerequisites
- Python 3.11 installed on your system.
- `uv` installed (`pip install uv` or via official installer).

### Virtual Environment Initialization
Clone the repository and initialize the virtual environment:

```bash
# Clone the repository
git clone https://github.com/meshtrix/meshtrix.git
cd meshtrix

# Create virtual environment targeting Python 3.11
uv venv --python 3.11

# Activate the virtual environment
# Windows (PowerShell):
.venv\Scripts\Activate.ps1
# Windows (cmd.exe):
.venv\Scripts\activate.bat
# Linux / macOS (bash/zsh):
source .venv/bin/activate

# Synchronize all core, dev, and optional dependencies
uv sync --all-extras --dev
```

---

## 5. Code Quality Standards

We enforce strict formatting, linting, and typing standards across all codebase directories.

### Linting & Formatting with Ruff
[Ruff](https://github.com/astral-sh/ruff) is configured in `pyproject.toml` with target version Python 3.11 and a 100-character line length limit.

- **Check code for lint errors**:
  ```bash
  uv run ruff check .
  ```
- **Automatically apply safe lint fixes**:
  ```bash
  uv run ruff check --fix .
  ```
- **Check code formatting**:
  ```bash
  uv run ruff format --check .
  ```
- **Automatically apply formatting**:
  ```bash
  uv run ruff format .
  ```

### Static Type Checking with Mypy
[Mypy](https://mypy-lang.org/) runs in strict mode (`strict = true`) to prevent type-related runtime defects:

- **Run strict static type analysis**:
  ```bash
  uv run mypy src tests
  ```
- No untyped definitions (`def foo(x):`) are permitted in `src/`. All function signatures and return types must be fully annotated.

---

## 6. Testing Expectations

All contributions must include thorough, behavior-driven test coverage under `tests/`.

### Running Tests
Execute the full test suite with Pytest:

```bash
# Run all tests
uv run pytest

# Run tests with coverage reporting
uv run pytest --cov=meshtrix tests/
```

### Testing Guidelines
- **Unit Tests**: Co-locate unit tests under `tests/unit/` testing isolated spec models, diagnostic schemas, and driver adapters.
- **Lifecycle Testing**: For any step implementation, test:
  - Valid scenario where `pre_check`, `execute`, and `post_check` succeed without warnings.
  - Invalid pre-check scenario (e.g., missing material catalog entry, unmapped body) producing appropriate `FailureObject` instances.
  - Post-check deviation catching deliberate physical mismatches.
  - Troubleshooter remediation guidance.
- **Determinism**: Tests must never depend on external network connections, live ANSYS installations, or non-deterministic random seeds. Always use `MockMechanicalDriver`.

---

## 7. Submitting Your Changes

Before submitting your PR, perform this final pre-flight verification:

```bash
# 1. Format check
uv run ruff format --check .

# 2. Lint check
uv run ruff check .

# 3. Type check
uv run mypy src tests

# 4. Pytest test suite
uv run pytest
```

When all four checks pass with zero errors and your branch is rebased on latest `main`, push your branch and open a Pull Request. Thank you for helping build Meshtrix!

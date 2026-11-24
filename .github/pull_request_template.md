## Summary of Changes
Provide a clear and concise summary of the architectural changes, new step implementations, or bug fixes introduced in this pull request.

## Linked Issue
Closes #[issue-number] / Fixes #[issue-number]

## Type of Change
- [ ] Bug fix (non-breaking change fixing an issue)
- [ ] New feature (non-breaking change introducing new functionality or step implementation)
- [ ] Breaking change (fix or feature modifying public interfaces or JobSpec schemas)
- [ ] Architectural / Refactoring (non-functional code improvement)
- [ ] CI/CD & Repository Infrastructure
- [ ] Documentation update

## Architectural Ground Rules Checklist
Every contribution to Meshtrix must adhere to the core architectural principles:
- [ ] **Deterministic Core**: Core execution and validation logic are decoupled from environment/proprietary licenses.
- [ ] **4-Phase Step Contract**: Any step modifications implement `pre_check`, `execute`, `post_check`, and `troubleshoot`.
- [ ] **Structured Failure**: Failures and warnings are reported as structured `FailureObject` instances with clear remediation paths, not unhandled exceptions.
- [ ] **Mock Driver Offline Compatibility**: All changes are verifiable offline without a live ANSYS license using `MockMechanicalDriver`.
- [ ] **Minimal Change Principle**: Modifications are focused strictly on the intended scope without unrelated refactoring.

## Testing & Quality Checklist
- [ ] Unit tests added or updated for all new behavior and edge cases.
- [ ] Pre-check, post-check, and troubleshooting paths tested for both success and intentional failure scenarios.
- [ ] All tests pass locally:
  ```bash
  uv run pytest
  ```
- [ ] Ruff linting passes with zero warnings:
  ```bash
  uv run ruff check .
  ```
- [ ] Ruff formatting passes:
  ```bash
  uv run ruff format --check .
  ```
- [ ] Strict Mypy type-checking passes:
  ```bash
  uv run mypy src tests
  ```

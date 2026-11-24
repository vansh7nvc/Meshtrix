---
name: Bug Report
about: Create a report to help us improve Meshtrix
title: "[BUG] "
labels: ["bug"]
assignees: ""
---

## Description
A clear and concise description of the bug encountered during execution.

## Affected Workflow Step / Component
Select or specify the affected step or subsystem:
- [ ] Spec Loading & Validation (`meshtrix.spec`)
- [ ] Failure Diagnostics & Error Engine (`meshtrix.diagnostics`)
- [ ] Step Framework / Lifecycle (`meshtrix.core.step`)
- [ ] Driver Port / Mock Simulation (`meshtrix.drivers`)
- [ ] Step 1: Geometry & CAD Preparation
- [ ] Step 2: Boundary Group Definitions
- [ ] Step 3: Global Mesh Generation
- [ ] Step 4: Local Mesh Refinement
- [ ] Step 5: Mesh Quality Verification
- [ ] Step 6: Material Mapping & Properties
- [ ] Step 7: Boundary Conditions & Contacts
- [ ] Step 8: Load Cases & Solutions
- [ ] Step 9: Post-Processing & Probing
- [ ] Step 10: Validation Reporting
- [ ] CLI / Runner

## Steps to Reproduce
1. Job Spec input file: `path/to/spec.yaml`
2. Command or API invocation:
   ```bash
   uv run meshtrix run --spec spec.yaml --driver mock
   ```
3. Execution phase where failure occurred (Pre-check / Execute / Post-check / Troubleshoot).

## Expected Behavior
A concise description of what should have occurred (e.g. successful material property assignment or clean non-blocking warning).

## Actual Behavior
A concise description of what actually occurred (e.g. unexpected exception, incorrect body mapping, or failed post-check).

## Diagnostic Logs / FailureObject Output
Paste any structured diagnostic log, `FailureObject` JSON payload, or stack trace below:
```json
{
  "code": "STEP_CHECK_FAILED",
  "severity": "BLOCKING",
  "entity": "Body_1",
  "message": "...",
  "remediation": "..."
}
```

## Environment
- **Operating System**: (e.g., Windows 11, Ubuntu 22.04 LTS)
- **Python Version**: 3.11.x (`python --version`)
- **Meshtrix Version**: (`uv run python -c "import meshtrix; print(meshtrix.__version__)"`)
- **Driver**: [ ] MockMechanicalDriver  [ ] Live PyMechanical (`ansys-mechanical-core`)
- **ANSYS Version** (if live): (e.g., ANSYS 2024 R1, N/A for Mock)

## Additional Context
Add any other context, model geometry files, or screenshots about the problem here.

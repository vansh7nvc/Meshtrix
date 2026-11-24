# FEA Automation Harness: Incremental Build Plan

Prototype plan for automating the SpaceClaim to ANSYS Mechanical shell-model workflow, built in phases so every phase ends with something an analyst can run and check.

## 1. Goal and ground rules

**Goal:** a harness that takes a validated job spec and produces a configured, verified Mechanical model plus a report, with the analyst approving at defined gates.

**Ground rules**

- The LLM plans and explains. Deterministic, tested code touches the model.
- Workflow order is fixed in code, not chosen by the model.
- Every step has pre-checks, post-checks and a troubleshooter, and checks measure the actual model, not the AI's description of it.
- Every failure is a structured object in engineering language (what failed, where, measured vs expected, likely causes, fixes, resume point).
- Every phase ends with a demo on a real past model, compared against the analyst's manual setup.
- Build the deterministic core first. The LLM layer is added late because it is the thinnest part.

## 2. Phase overview

| Phase | Focus | Workflow steps covered | Exit demo |
| --- | --- | --- | --- |
| 0 | Feasibility and environment | none (proof of access) | Python launches Mechanical, applies one setting, reads it back |
| 1 | Foundations: spec, failure object, mock layer, logging | none (infrastructure) | Spec validates, checks run against a mock model, failure report renders |
| 2 | Setup automation on a prepared model | 6, 8, 9, 10 | Materials, mesh, BCs, loads set up from spec on a real model |
| 3 | Solve, verification, post-processing, report | beyond the 10 steps | End-to-end run on a prepared model with a report |
| 4 | Model build steps | 3, 4, 5, 7 | Named selections, transfer, connections and mass balance from spec |
| 5 | LLM layer and approval UI | all (interface) | Analyst submits a request and approves a setup summary |
| 6 | Geometry prep, detect and report first | 1, 2 | Geometry health report on a raw assembly |
| 7 | Hardening for enterprise use | all | Audit trail, regression suite, deployment option |

## 3. Phase 0: Feasibility and environment

**Purpose:** remove the biggest unknowns before writing real code.

**Tasks**

- Record ANSYS version, license type and availability on the development machine.
- Confirm Mechanical can be launched and controlled from Python (PyMechanical) and results read back.
- Confirm which SpaceClaim operations (midsurface, share topology, named selections) are scriptable in this version. Record a GUI session to a script and replay it on 2 or 3 assemblies.
- Collect 3 to 5 completed past models plus the analyst's final setups as ground truth.
- Interview 2 or 3 analysts beyond the first one, to separate one person's habits from a standard.
- Ask the analyst which tasks they repeat most and dread most.
- Confirm whether geometry may leave the company network (decides cloud vs private LLM).

**Exit criteria:** a script launches Mechanical, sets one property and reads it back. A written feasibility note lists what is scriptable and what is not.

## 4. Phase 1: Foundations

**Purpose:** build the skeleton every later phase plugs into.

**Deliverables**

- **Job spec schema** (Pydantic, YAML/JSON): units, analysis type, materials, mesh settings, load cases, supports, mass target, check tolerances.
- **Failure object schema** with severity levels: blocking, warning, auto-recoverable.
- **Step interface:** every step implements pre-check, execute, post-check, troubleshooter.
- **Mock Mechanical layer** so logic and checks can be developed and tested without a license.
- **Run logger and checkpoints:** every run records spec version, tool versions and results, and can resume from a completed step.
- **Project layout, test setup (pytest) and code conventions.**

**Exit criteria:** a spec loads and validates, a deliberately bad spec is rejected with a readable message, and a mock run produces a pass/fail report.

## 5. Phase 2: Setup automation on a prepared model

Works on a Mechanical model that already has geometry, named selections and connections. Automates the most deterministic steps.

### Step 6: Materials

- Material library as data, mapped by part name or ID.
- **Pre-check:** every body has a mapping.
- **Post-check:** every body has a material, and shell thickness matches the CAD or spec.
- **Troubleshooter:** unmapped parts, thickness mismatch, missing library entry.

### Step 8: Meshing

- Mesh template from the spec (global size, local refinement at holes and welds).
- **Post-checks:** skewness, warpage, aspect ratio, element count, connectivity across shared edges.
- **Troubleshooter:** list the failing elements and their location, suggest local refinement.

### Step 9: Boundary conditions

- Created from the load case table and named selections.
- **Pre-check:** every named selection exists and is non-empty.
- **Post-check:** each support's scoping and degrees of freedom match the spec.

### Step 10: Loads

- Forces, pressures, accelerations and load steps created from the same table.
- **Post-check:** applied totals match the spec, and coordinate systems and signs are correct.

**Exit criteria:** on 2 or 3 real models, the harness reproduces the analyst's manual setup and the checks catch a deliberately injected error (empty selection, wrong thickness, wrong sign).

## 6. Phase 3: Solve, verification, post-processing and report

These tasks are outside the 10 steps but are a large share of the repetitive hours and are low risk.

- **Solve and monitor:** submit the run, track convergence, flag failures.
- **Verification gates:**
  - Free-free modal run confirms exactly 6 rigid-body modes.
  - Sum of reaction forces matches the applied load.
  - Contact status check.
  - Convergence log check.
- **Post-processing:** max stress and displacement per load case, standard plots, margin of safety against allowables.
- **Report generator:** templated report with the model summary, checks passed or failed, results and plots.
- **Batch runs:** same model across multiple load cases.

**Note on weld regions:** stress at shell weld junctions is a singularity. Report structural or hot-spot stress rather than peak values, and agree the method with the analyst.

**Exit criteria:** one command takes a spec and a prepared model to a finished report, and the numbers match the analyst's manual results within an agreed tolerance.

## 7. Phase 4: Model build steps

### Step 3: Named selections

- Rule-based creation (weld faces and edges, bolt-hole edges by diameter), strict naming convention.
- **Post-check:** the count found equals the expected count.

### Step 4: Transfer to Mechanical

- Scripted transfer.
- **Post-check:** body count, thickness and named selections all arrived intact against the CAD.

### Step 5: Connections

- Contact regions created from the bolt-edge named selections using a company standard.
- Make contact type a config option (frictional, bonded, beam/MPC). The original workflow uses frictional contact on a shell model, which needs an analyst decision because of the shell offset geometry and convergence cost.
- **Post-checks:** no unconnected bolts, contact offset checked, initial penetration or gap reported.

### Step 7: Point mass and mass balancing

- Compute total mass and CG against the target, create point masses, iterate within tolerance.
- Point masses deformable by default.
- **Needs from the analyst:** a written rule for where missing mass goes (by region, by weight fraction or a fixed rule).
- **Post-check:** mass and CG within the tolerance in the spec.

**Exit criteria:** from a transferred model, steps 3 to 10 run end to end with all gates passing on 2 or 3 real models.

## 8. Phase 5: LLM layer and approval UI

Added only once the deterministic pipeline works.

- **Request to spec:** the LLM turns a request, load case table or email into a schema-validated spec. It never writes directly into the model.
- **Readable approval screen:** model summary table (parts, materials, thicknesses, contacts, loads), shown back in engineering terms for confirmation.
- **Provenance on every value:** from spec row, from material library, or ASSUMED (needs confirmation). Values without a source are blocked.
- **Failure explanation:** plain-language explanation of failure objects. Confirmed causes (from checks) are labelled separately from suggested causes (LLM-ranked).
- **Report drafting** from verified results only.
- **Determinism:** temperature 0, versioned prompts and model, full logging.
- **Degraded mode:** if the LLM is unavailable, the deterministic core and playbooks still run.
- **Feedback button on each step** feeding the failure log.
- **Provider-agnostic interface** so a private or on-premises model can be swapped in.

**Exit criteria:** an analyst with no AI background submits a request, reviews the setup summary and completes a run without needing any AI terminology.

## 9. Phase 6: Geometry prep (steps 1 and 2)

The hardest and least predictable part, so it comes after the rest is proven.

- **Step 1:** import, unit check, part naming, geometry health report.
- **Step 2:** scripted midsurface extraction and share topology with spec-driven tolerances.
- **Detect and report first:** gaps at T-joints, free edges, wrong normals, thickness not captured, share topology wrongly applied across bolted interfaces.
- **Stop and hand over** to the analyst on unresolved problems. Add automatic repair (surface extension, gap closure) only for failure types that have proven safe and have a tolerance limit.

**Exit criteria:** on a raw assembly, the harness produces a geometry health report that agrees with the analyst's own assessment.

## 10. Phase 7: Hardening for enterprise use

- **Audit trail:** who approved what, which model version and spec produced each setup.
- **Regression suite:** benchmark models with known answers that must pass before any tool or ANSYS version change ships.
- **Access control, secrets handling, license-aware job scheduling.**
- **Deployment:** on-premises or private option for confidential geometry.
- **Analyst training:** a one-page guide in FEA terms covering what the tool automates, what it never decides, and what each flag means.
- **Metrics:** baseline time per task versus time with the harness, hours saved per model, failure rate by step.

## 11. Cross-cutting rules for every step

| Part | Rule |
| --- | --- |
| Pre-checks | Validate inputs before executing |
| Execution | Wrap every tool call to catch exceptions, license timeouts and hangs |
| Post-checks | Read the real model state and compare against the spec |
| Troubleshooter | Failure code to diagnosis to fix, with the resume step |
| Auto-recovery | Allowed only for pre-approved fixes, with a retry limit, logged and shown to the analyst |
| Checkpoint | Save state after every step so fixes do not require full reruns |

## 12. Risks and open questions

**Risks**

- Scriptability of midsurface and share topology in the available SpaceClaim version.
- License availability for development and testing.
- A workflow encoding one analyst's habits instead of a company standard.
- Frictional contact on shell models causing convergence failures.
- Analyst over-reliance if every run passes, so keep mandatory sign-off gates.
- Confidentiality limits on sending geometry to external LLM providers.

**Open questions to settle in Phase 0**

1. Which ANSYS version and license setup?
2. Which analysis types (static, modal, random vibration) are in scope for the first release?
3. Is frictional contact on the midsurface model intentional, or should the standard be bonded or beam connections?
4. What is the analyst's rule for point mass placement?
5. Can geometry leave the company network?
6. Which 3 to 5 past models will serve as ground truth?

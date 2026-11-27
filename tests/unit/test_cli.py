"""
Unit tests for Meshtrix CLI — validate and run commands.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from typer.testing import CliRunner

from meshtrix.cli.main import app

runner = CliRunner()

# ---------------------------------------------------------------------------
# Fixtures: YAML files
# ---------------------------------------------------------------------------

VALID_SPEC_YAML = """\
job_id: CLI-TEST-001
units: Metric_mm
analysis_type: STRUCTURAL_STATIC
spec_version: "1.0"
materials:
  catalog:
    Steel:
      name: Steel
      density: 7.85e-9
      elastic_modulus: 200000.0
      poissons_ratio: 0.3
      yield_strength: 250.0
  mappings:
    Body_A:
      body_name: Body_A
      material_name: Steel
      thickness: null
mesh:
  global_size: 5.0
  element_order: quadratic
supports:
  - selection: NS_BASE
    type: fixed
load_cases:
  - case_id: LC1
    forces:
      - selection: NS_LUG
        magnitude: 1000.0
        direction: [0.0, 1.0, 0.0]
        name: LugForce
"""

INVALID_SPEC_YAML = """\
job_id: 12345
units: INVALID_UNIT
analysis_type: ???
materials: {}
"""


# ---------------------------------------------------------------------------
# Class TestCLIValidate
# ---------------------------------------------------------------------------


class TestCLIValidate:
    def test_validate_valid_spec(self) -> None:
        with tempfile.NamedTemporaryFile(
            suffix=".yaml", mode="w", delete=False, encoding="utf-8"
        ) as f:
            f.write(VALID_SPEC_YAML)
            spec_path = f.name
        result = runner.invoke(app, ["validate", spec_path])
        assert result.exit_code == 0
        assert "CLI-TEST-001" in result.output

    def test_validate_missing_file(self) -> None:
        result = runner.invoke(app, ["validate", "nonexistent_spec.yaml"])
        assert result.exit_code != 0

    def test_validate_invalid_yaml(self) -> None:
        with tempfile.NamedTemporaryFile(
            suffix=".yaml", mode="w", delete=False, encoding="utf-8"
        ) as f:
            f.write(INVALID_SPEC_YAML)
            spec_path = f.name
        result = runner.invoke(app, ["validate", spec_path])
        # Should fail validation
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# Class TestCLIRun
# ---------------------------------------------------------------------------


class TestCLIRun:
    def test_run_mock_mode_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            spec_path = Path(tmpdir) / "spec.yaml"
            spec_path.write_text(VALID_SPEC_YAML, encoding="utf-8")
            result = runner.invoke(app, ["run", str(spec_path), "--mock"])
        assert result.exit_code == 0
        assert "passed" in result.output.lower()

    def test_run_missing_file(self) -> None:
        result = runner.invoke(app, ["run", "no_file.yaml", "--mock"])
        assert result.exit_code != 0

    def test_run_no_mock_flag_exits_with_error(self) -> None:
        with tempfile.NamedTemporaryFile(
            suffix=".yaml", mode="w", delete=False, encoding="utf-8"
        ) as f:
            f.write(VALID_SPEC_YAML)
            spec_path = f.name
        result = runner.invoke(app, ["run", spec_path])
        # Without --mock there is no live driver — should fail
        assert result.exit_code != 0

    def test_run_mock_resume_from(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            spec_path = Path(tmpdir) / "spec.yaml"
            spec_path.write_text(VALID_SPEC_YAML, encoding="utf-8")
            cp_dir = Path(tmpdir) / "cp"
            log_dir = Path(tmpdir) / "logs"
            first = runner.invoke(
                app,
                [
                    "run",
                    str(spec_path),
                    "--mock",
                    "--run-id",
                    "cli_unit_res",
                    "--checkpoint-dir",
                    str(cp_dir),
                    "--log-dir",
                    str(log_dir),
                ],
            )
            assert first.exit_code == 0
            result = runner.invoke(
                app,
                [
                    "run",
                    str(spec_path),
                    "--mock",
                    "--run-id",
                    "cli_unit_res",
                    "--resume-from",
                    "step_09_boundary_conditions",
                    "--checkpoint-dir",
                    str(cp_dir),
                    "--log-dir",
                    str(log_dir),
                ],
            )
        assert result.exit_code == 0

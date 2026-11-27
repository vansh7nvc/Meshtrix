"""
Meshtrix CLI — validate, run, and inspect FEA automation pipelines.

Authoritative Reference: ORIGINAL_REQUEST.md §R2 & PROJECT.md
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from meshtrix.core.checkpoint import CheckpointManager
from meshtrix.runner.engine import PipelineRunner
from meshtrix.spec.job_spec import JobSpec

app = typer.Typer(
    name="meshtrix",
    help="Meshtrix FEA Automation Harness CLI",
    add_completion=False,
)
console = Console()
err_console = Console(stderr=True)


def _load_spec(spec_path: Path) -> JobSpec:
    """Load and validate a JobSpec from YAML or JSON."""
    if spec_path.suffix.lower() == ".json":
        data = json.loads(spec_path.read_text(encoding="utf-8"))
        return JobSpec.from_dict(data)
    return JobSpec.from_yaml(spec_path)


@app.command("validate")
def cmd_validate(
    spec_path: Path = typer.Argument(..., help="Path to the JobSpec YAML/JSON file."),  # noqa: B008
) -> None:
    """Validate a JobSpec YAML or JSON file and print a summary table."""
    if not spec_path.exists():
        err_console.print(f"[bold red]Error:[/] File not found: {spec_path}")
        raise typer.Exit(code=1)

    try:
        spec = _load_spec(spec_path)
    except Exception as exc:
        err_console.print(f"[bold red]Validation failed:[/] {exc}")
        raise typer.Exit(code=1) from exc

    table = Table(title=f"JobSpec Validation — {spec_path.name}", show_header=True)
    table.add_column("Field", style="cyan", no_wrap=True)
    table.add_column("Value", style="green")

    table.add_row("job_id", spec.job_id)
    table.add_row("spec_version", spec.spec_version)
    table.add_row("units", str(spec.units))
    table.add_row("analysis_type", str(spec.analysis_type))
    table.add_row("bodies", str(len(spec.materials.mappings)))
    table.add_row("materials in catalog", str(len(spec.materials.catalog)))
    table.add_row("supports", str(len(spec.supports)))
    table.add_row(
        "load_cases",
        str(len(spec.load_cases))
        + (
            f" ({sum(len(lc.forces) for lc in spec.load_cases)} forces, "
            f"{sum(len(lc.pressures) for lc in spec.load_cases)} pressures, "
            f"{sum(len(lc.accelerations) for lc in spec.load_cases)} accelerations)"
        ),
    )

    console.print(table)
    console.print("[bold green]JobSpec is valid.[/]")


@app.command("run")
def cmd_run(
    spec_path: Path = typer.Argument(..., help="Path to the JobSpec YAML/JSON file."),  # noqa: B008
    mock: bool = typer.Option(
        False, "--mock", help="Use MockMechanicalDriver (offline, no license needed)."
    ),
    mock_state: Path | None = typer.Option(  # noqa: B008
        None, "--mock-state", help="Optional JSON file to import into MockMechanicalDriver."
    ),
    run_id: str | None = typer.Option(None, "--run-id", help="Explicit run identifier."),
    resume_from: str | None = typer.Option(
        None, "--resume-from", help="Step ID to resume execution from."
    ),
    checkpoint_dir: Path | None = typer.Option(  # noqa: B008
        None, "--checkpoint-dir", help="Directory for step checkpoint files."
    ),
    log_dir: Path | None = typer.Option(  # noqa: B008
        None, "--log-dir", help="Directory for structured run logs."
    ),
) -> None:
    """Execute the Meshtrix pipeline for a JobSpec."""
    if not spec_path.exists():
        err_console.print(f"[bold red]Error:[/] File not found: {spec_path}")
        raise typer.Exit(code=1)

    try:
        spec = _load_spec(spec_path)
    except Exception as exc:
        err_console.print(f"[bold red]Spec load failed:[/] {exc}")
        raise typer.Exit(code=1) from exc

    console.print(f"[bold cyan]Meshtrix[/] — job_id=[cyan]{spec.job_id}[/]")

    if not mock:
        err_console.print(
            "[bold red]Error:[/] Live driver not available. Use --mock for offline runs."
        )
        raise typer.Exit(code=1)

    from meshtrix.drivers.mock import MockMechanicalDriver

    driver = MockMechanicalDriver()
    if mock_state is not None:
        if not mock_state.exists():
            err_console.print(f"[bold red]Error:[/] Mock state file not found: {mock_state}")
            raise typer.Exit(code=1)
        state_data: dict[str, Any] = json.loads(mock_state.read_text(encoding="utf-8"))
        driver.import_state(state_data)
    else:
        driver.seed_from_spec(spec)

    runner = PipelineRunner(base_dir=spec_path.parent)
    try:
        result = runner.run(
            spec,
            driver,
            run_id=run_id,
            resume_from=resume_from,
            checkpoint_dir=checkpoint_dir,
            log_dir=log_dir,
        )
    except Exception as exc:
        err_console.print(f"[bold red]Run aborted:[/] {exc}")
        raise typer.Exit(code=1) from exc

    table = Table(title="Pipeline Run Summary", show_header=True)
    table.add_column("Step", style="cyan")
    table.add_column("Status")
    for sr in result.step_results:
        table.add_row(sr.step_id, sr.status)
    console.print(table)

    console.print(f"Run {result.run_id} — status={result.status} ({result.elapsed_seconds:.2f}s)")

    if not result.is_successful():
        for failure in result.failures:
            err_console.print(f"[red]{failure.error_code}[/]: {failure.engineering_message}")
        raise typer.Exit(code=1)


@app.command("inspect-run")
def cmd_inspect_run(
    run_id: str = typer.Argument(..., help="Run identifier to inspect."),
    checkpoint_dir: Path = typer.Option(  # noqa: B008
        Path(".meshtrix/checkpoints"), "--checkpoint-dir", help="Checkpoint directory."
    ),
    log_dir: Path = typer.Option(  # noqa: B008
        Path(".meshtrix/logs"), "--log-dir", help="Run log directory."
    ),
) -> None:
    """Inspect checkpoints and audit log for a previous pipeline run."""
    log_path = log_dir / f"{run_id}.json"
    cm = CheckpointManager(checkpoint_dir)
    checkpoints = cm.list_checkpoints(run_id)

    if not log_path.exists() and not checkpoints:
        err_console.print(f"[bold red]Error:[/] No run artifacts found for run_id='{run_id}'.")
        raise typer.Exit(code=1)

    log_data: dict[str, Any] = {}
    if log_path.exists():
        log_data = json.loads(log_path.read_text(encoding="utf-8"))

    table = Table(title=f"Run Inspection — {run_id}", show_header=True)
    table.add_column("Field", style="cyan")
    table.add_column("Value", style="green")
    table.add_row("run_id", run_id)
    table.add_row("job_id", str(log_data.get("job_id", "unknown")))
    table.add_row("status", str(log_data.get("status", "unknown")))
    table.add_row("resumed_from", str(log_data.get("resumed_from")))
    table.add_row("checkpoints", ", ".join(checkpoints) if checkpoints else "none")
    console.print(table)


def main() -> None:  # pragma: no cover
    """Entrypoint for the ``meshtrix`` CLI command."""
    app()


if __name__ == "__main__":  # pragma: no cover
    main()

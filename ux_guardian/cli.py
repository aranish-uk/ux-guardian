import asyncio
from pathlib import Path
from typing import Annotated

import typer
from dotenv import load_dotenv

from ux_guardian.config import load_config, load_journeys, validate_url
from ux_guardian.demo import app as demo_app
from ux_guardian.run import replay_pipeline, write_report

app = typer.Typer(help="UX Guardian. M0: offline fixture replay; live agents arrive in M1.")
live = typer.Typer(help="Explicitly confirmed paid-run entry point.")
app.add_typer(live, name="live")
app.add_typer(demo_app, name="demo")


@app.callback()
def setup() -> None:
    load_dotenv(Path(".env"), override=False)


@app.command("run")
def run_command(
    preview_url: Annotated[str, typer.Option()],
    pr: Annotated[int, typer.Option(min=1)],
    dry_run: bool = False,
    output: Path = Path("artifacts"),
) -> None:
    try:
        url = validate_url(preview_url)
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    if not dry_run:
        typer.echo("Live orchestration is not available in M0. Use --dry-run for fixtures.")
        raise typer.Exit(2)
    report = asyncio.run(replay_pipeline(pr=pr, preview_url=url))
    write_report(report, output)
    typer.echo(f"Synthetic fixture replay saved to {output}. TinyFish cost: $0.00.")


@live.command("journey")
def live_journey(
    journey: Annotated[str, typer.Option()], env: Annotated[str, typer.Option()] = "prod"
) -> None:
    if env not in {"prod", "preview"}:
        raise typer.BadParameter("--env must be prod or preview")
    journeys = {item.id: item for item in load_journeys()}
    if journey not in journeys:
        raise typer.BadParameter("Unknown journey")
    config = load_config()
    selected = journeys[journey]
    estimate = selected.max_steps * len(selected.viewports) * 0.016
    typer.echo(
        f"Estimated TinyFish Agent cost (step cap): ${estimate:.2f}. "
        f"Run budget: ${config.budget_usd_per_run:.2f}."
    )
    if estimate > config.budget_usd_per_run:
        typer.echo("Estimate exceeds the run budget; refusing the run.")
        raise typer.Exit(2)
    typer.confirm("Confirm this paid run?", abort=True)
    typer.echo("TinyFish live integration is scheduled for M1; no paid API call was made.")
    raise typer.Exit(2)

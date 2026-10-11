import asyncio
from pathlib import Path
from typing import Annotated

import typer
from dotenv import load_dotenv

from ux_guardian.agents.tinyfish import TinyFishAgent
from ux_guardian.config import Viewport, load_config, load_journeys, validate_url
from ux_guardian.demo import app as demo_app
from ux_guardian.run import replay_pipeline, write_report

app = typer.Typer(help="UX Guardian. Offline fixture replay and confirmed live journeys.")
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
    journey: Annotated[str, typer.Option()],
    env: Annotated[str, typer.Option()] = "prod",
    viewport: Viewport = "desktop",
    yes: bool = False,
) -> None:
    if env != "prod":
        raise typer.BadParameter("M1 live verification supports --env prod")
    if viewport != "desktop":
        raise typer.BadParameter("TinyFish API does not expose viewport control")
    journeys = {item.id: item for item in load_journeys()}
    if journey not in journeys:
        raise typer.BadParameter("Unknown journey")
    config = load_config()
    selected = journeys[journey]
    estimate = selected.max_steps * 0.016
    typer.echo(
        f"Estimated TinyFish Agent cost (step cap): ${estimate:.2f}. "
        f"Run budget: ${config.budget_usd_per_run:.2f}."
    )
    if estimate > config.budget_usd_per_run:
        raise typer.BadParameter("Estimate exceeds the run budget")
    if not yes:
        typer.confirm("Confirm this paid run?", abort=True)
    agent = TinyFishAgent(config=config)
    try:
        result = asyncio.run(
            agent.run_journey(base_url=config.production_url, journey=selected, viewport=viewport)
        )
    except ValueError as error:
        typer.echo(str(error))
        raise typer.Exit(2) from error
    typer.echo(f"{'PASS' if result.passed else 'FAIL'}: {result.journey_id} ({result.run_id})")
    for step in result.steps:
        typer.echo(f"{step.n}. {step.action} - {step.observation}")
        typer.echo(f"   Screenshot: {step.screenshot_path or 'unavailable'}")
    typer.echo(f"Replay: {result.replay_url or 'unavailable'}")
    typer.echo(f"Actual cost: ${result.cost_usd:.3f}")
    if not result.passed:
        raise typer.Exit(1)

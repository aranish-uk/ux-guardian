import asyncio
import hashlib
import json
from importlib.resources import files
from pathlib import Path
from typing import Annotated, cast

import typer
from dotenv import load_dotenv
from pydantic import ValidationError

from ux_guardian.agents.tinyfish import TinyFishAgent
from ux_guardian.config import Environment, Viewport, load_config, load_journeys, validate_url
from ux_guardian.demo import app as demo_app
from ux_guardian.diff.analyzer import Predictions, analyze, git_diff, normalize_diff
from ux_guardian.llm import OpenAiLlmClient
from ux_guardian.report.models import Report
from ux_guardian.run import live_checks, replay_pipeline, write_report

app = typer.Typer(help="UX Guardian. Offline fixture replay and confirmed live journeys.")
live = typer.Typer(help="Explicitly confirmed paid-run entry point.")
app.add_typer(live, name="live")
app.add_typer(demo_app, name="demo")


@app.callback()
def setup() -> None:
    load_dotenv(Path(".env"), override=False)


class RecordedLlm:
    def __init__(self, response: Predictions) -> None:
        self.response = response

    async def complete_json(self, *, system: str, prompt: str) -> dict[str, object]:
        return self.response.model_dump()


@live.command("models")
def live_models() -> None:
    """One free models.list request; prints model IDs only."""

    async def discover() -> list[str]:
        client = OpenAiLlmClient(load_config())
        try:
            return await client.list_models()
        finally:
            await client.close()

    try:
        typer.echo("\n".join(asyncio.run(discover())))
    except ValueError as error:
        raise typer.BadParameter(str(error)) from None


def analysis_command(
    base: str,
    head: str,
    diff_file: Path | None,
    llm_fixture: Path | None,
    output: Path | None,
    use_live: bool,
) -> None:
    changed = (
        normalize_diff(diff_file.read_text(encoding="utf-8")) if diff_file else git_diff(base, head)
    )
    fingerprint = hashlib.sha256(
        json.dumps([f.model_dump() for f in changed], sort_keys=True).encode()
    ).hexdigest()
    llm = None
    if not use_live:
        if llm_fixture:
            record = json.loads(llm_fixture.read_text(encoding="utf-8"))
        else:
            records = json.loads(
                files("ux_guardian.fixtures").joinpath("m3_llm.json").read_text(encoding="utf-8")
            )
            record = records.get(fingerprint)
        if record:
            if record["diff_sha256"] != fingerprint:
                raise typer.BadParameter("LLM fixture does not match this diff")
            llm = RecordedLlm(Predictions.model_validate(record["response"]))

    async def execute():
        if not use_live:
            return await analyze(changed, load_journeys(), llm)
        client = OpenAiLlmClient(load_config())
        try:
            # Explicit demo verification also reviews glob-owned hunks; additive only.
            return await analyze(changed, load_journeys(), client, review_all=True)
        finally:
            await client.close()

    try:
        result = asyncio.run(execute())
    except ValidationError:
        raise typer.BadParameter("LLM output failed schema validation; body omitted") from None
    except ValueError as error:
        raise typer.BadParameter(str(error)) from None
    typer.echo(result.outcome)
    for item in result.affected:
        typer.echo(f"{item.journey_id} [{item.source}]: {item.reason}")
    for item in result.low_confidence:
        typer.echo(f"{item.journey_id} [low confidence, advisory only]: {item.reason}")
    if result.reasoning:
        typer.echo(result.reasoning)
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(
                {
                    "diff_sha256": fingerprint,
                    "model": load_config().llm_model,
                    "response": result.llm_response.model_dump() if result.llm_response else None,
                    "analysis": result.model_dump(),
                },
                indent=2,
            ),
            encoding="utf-8",
        )


@app.command("analyze")
def analyze_command(
    base: str = "feat/m0",
    head: str = "HEAD",
    diff_file: Path | None = None,
    llm_fixture: Path | None = None,
    output: Path | None = None,
) -> None:
    """Offline glob/shared selection and exact-diff recorded LLM replay."""
    analysis_command(base, head, diff_file, llm_fixture, output, False)


@live.command("analyze")
def live_analyze_command(
    base: str = "feat/m0",
    head: str = "HEAD",
    diff_file: Path | None = None,
    output: Path | None = None,
) -> None:
    """One live OpenAI structured-output call. No TinyFish Agents."""
    typer.echo("One billable OpenAI LLM call; TinyFish Agent runs: 0.")
    analysis_command(base, head, diff_file, None, output, True)


@app.command("run")
def run_command(
    preview_url: Annotated[str, typer.Option()],
    pr: Annotated[int, typer.Option(min=1)],
    dry_run: bool = False,
    output: Path = Path("artifacts"),
    checks_fixture: Path | None = None,
) -> None:
    try:
        url = validate_url(preview_url)
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    if not dry_run:
        typer.echo("Live orchestration is not available in M0. Use --dry-run for fixtures.")
        raise typer.Exit(2)
    template = (
        Report.model_validate_json(checks_fixture.read_text(encoding="utf-8"))
        if checks_fixture
        else Report.model_validate_json(
            files("ux_guardian.fixtures")
            .joinpath("m2_mobile_overlay.json")
            .read_text(encoding="utf-8")
        )
    )
    report = asyncio.run(replay_pipeline(pr=pr, preview_url=url, template=template))
    write_report(report, output)
    typer.echo(f"Fixture replay saved to {output}. TinyFish cost: $0.00.")


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


@live.command("checks")
def live_checks_command(
    env: str = "both",
    output: Path = Path("artifacts") / "checks",
    preview_url: str | None = None,
) -> None:
    """Run free Fetch and deterministic desktop/mobile checks. No Agent calls."""
    if env not in {"both", "prod", "preview"}:
        raise typer.BadParameter("Use --env both, prod, or preview")
    config = load_config()
    if preview_url:
        url = validate_url(preview_url)
        # Live overrides are restricted to this demo's Vercel deployments.
        from urllib.parse import urlsplit

        host = urlsplit(url).hostname or ""
        if not (host.startswith("ux-guardian-demo-") and host.endswith("-aranish-uk.vercel.app")):
            raise typer.BadParameter("Live checks require a UX Guardian demo preview")
        config = config.model_copy(update={"preview_url": url})
    typer.echo("Estimated TinyFish cost: $0.00 (Fetch only). Agent runs: 0.")
    environments: list[Environment] = (
        ["preview", "prod"] if env == "both" else [cast(Environment, env)]
    )
    report = asyncio.run(
        live_checks(
            config=config, journeys=load_journeys(), environments=environments, output=output
        )
    )
    write_report(report, output)
    for check in report.check_results:
        typer.echo(
            f"{check.journey_id} {check.env} {check.viewport}: {'PASS' if check.passed else 'FAIL'}"
        )
    for finding in report.findings:
        typer.echo(f"{finding.severity}: {finding.title}")
    if report.fetch.service_error:
        typer.echo(report.fetch.service_error)
    typer.echo(f"{len(report.findings)} confirmed findings. Evidence saved to {output}.")

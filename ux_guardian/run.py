"""M0 fixture replay. Live orchestration is built in M1–M5."""

import json
from importlib.resources import files
from pathlib import Path

from ux_guardian.agents.fixture import FixtureAgent
from ux_guardian.config import Environment, load_config, load_journeys
from ux_guardian.judge.judge import Verdict, judge
from ux_guardian.report.models import Report
from ux_guardian.report.render import render
from ux_guardian.security import redact, redact_data
from ux_guardian.swarm import RunRequest, run_pool


def replay_report() -> Report:
    raw = files("ux_guardian.fixtures").joinpath("report.json").read_text(encoding="utf-8")
    return Report.model_validate_json(raw)


async def replay_pipeline(*, preview_url: str, pr: int, template: Report | None = None) -> Report:
    """Replay acquisition, bounded fan-out, comparison and rendering from fixtures.

    Journey selection and enrichment are already recorded in the fixture; their
    real implementations belong to M3/M5. No supplied URL is contacted.
    """
    saved = template if template is not None else replay_report()
    config = load_config()
    journeys = load_journeys()
    runs = []
    environments: list[Environment] = ["preview", "prod"]
    for env in environments:
        url = preview_url if env == "preview" else config.production_url
        requests = [
            RunRequest(base_url=url, journey=journey, viewport=viewport, env=env)
            for journey in journeys
            for viewport in journey.viewports
        ]
        runs.extend(
            await run_pool(FixtureAgent(saved.runs, env), requests, concurrency=config.concurrency)
        )
    retries = [run.model_copy(deep=True) for run in saved.runs if run.attempt > 1]
    findings = []
    sections: dict[Verdict, list[str]] = {
        Verdict.PREEXISTING: [],
        Verdict.CANDIDATE: [],
        Verdict.IMPROVED: [],
    }
    confirmed_journeys: set[str] = set()
    for journey in journeys:
        for viewport in journey.viewports:
            preview = next(
                run
                for run in runs
                if run.env == "preview"
                and run.journey_id == journey.id
                and run.viewport == viewport
            )
            prod = next(
                run
                for run in runs
                if run.env == "prod" and run.journey_id == journey.id and run.viewport == viewport
            )
            retry = next(
                (
                    run
                    for run in retries
                    if run.env == "preview"
                    and run.journey_id == journey.id
                    and run.viewport == viewport
                ),
                None,
            )
            deterministic = any(
                check.agrees
                for check in saved.checks
                if check.env == "preview"
                and check.journey_id == journey.id
                and check.viewport == viewport
            )
            verdict = judge(
                preview_pass=preview.passed,
                prod_pass=prod.passed,
                deterministic_agrees=deterministic,
                failed_step=preview.blocked_at_step,
                retry_failed_step=(retry.blocked_at_step if retry and not retry.passed else None),
            )
            if verdict == Verdict.CONFIRMED:
                confirmed_journeys.add(journey.id)
            elif verdict in sections:
                sections[verdict].append(f"{journey.name} ({viewport}): {preview.observed_problem}")
    for finding in saved.findings:
        if finding.journey_id in confirmed_journeys:
            findings.append(finding.model_copy(deep=True))
    return saved.model_copy(
        update={
            "pr": pr,
            "preview_url": preview_url,
            "prod_url": config.production_url,
            "runs": runs + retries,
            "findings": findings,
            "fixture": True,
            "preexisting": sections[Verdict.PREEXISTING],
            "flaky": sections[Verdict.CANDIDATE],
            "improved": sections[Verdict.IMPROVED],
        }
    )


def write_report(report: Report, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    (output / "report.json").write_text(
        json.dumps(
            redact_data(report.model_dump(mode="json", by_alias=True)), ensure_ascii=False, indent=2
        )
        + "\n",
        encoding="utf-8",
    )
    (output / "report.md").write_text(redact(render(report)), encoding="utf-8")

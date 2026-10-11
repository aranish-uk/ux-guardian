"""Offline fixture replay and M2 entry-check orchestration; never publishes."""

import asyncio
import json
from importlib.resources import files
from pathlib import Path
from time import monotonic
from typing import Literal

from ux_guardian.agents.base import LlmClient
from ux_guardian.agents.fixture import FixtureAgent
from ux_guardian.checks.models import CheckResult, FetchResult
from ux_guardian.checks.playwright import run_checks
from ux_guardian.config import Config, Environment, Journey, load_config, load_journeys
from ux_guardian.diff.analyzer import ChangedFile, glob_matches, journey_path, shared_reason
from ux_guardian.enrich.fix import DiffHunk, FixContext, FixFinding, render_fix, suggest_fix
from ux_guardian.judge.judge import Verdict, judge, judge_evidence, regression_signals
from ux_guardian.judge.severity import assign_severity
from ux_guardian.report.models import Affected, Finding, Report
from ux_guardian.report.render import render
from ux_guardian.security import redact, redact_data
from ux_guardian.swarm import RunRequest, run_pool
from ux_guardian.tinyfish.fetch import fetch_precheck
from ux_guardian.tinyfish.search import SearchClient, should_search


async def enrich_findings(
    report: Report, config: Config, journeys: list[Journey],
    changed: list[ChangedFile], llm: LlmClient | None, *, max_calls: int = 3,
) -> None:
    """Best-effort FR9 enrichment of confirmed findings only; never acquire evidence."""
    search = SearchClient() if config.include_search else None
    for index, finding in enumerate(report.findings):
        finding.fix_suggestion = "Fix suggestion unavailable"
        if llm is None or index >= min(3, max_calls):
            continue
        try:
            journey = next(j for j in journeys if j.id == finding.journey_id)
            linked = [
                f for f in changed if shared_reason(f) or any(
                    glob_matches(journey_path(p), pattern)
                    for p in f.paths for pattern in journey.owns
                )
            ]
            relevant = linked or [
                f for f in changed
                if Path(f.filename).suffix in {".tsx", ".jsx", ".ts", ".js", ".css", ".html"}
            ]
            checks = [c for c in report.check_results
                      if c.env == "preview" and c.journey_id == finding.journey_id]
            runs = [r for r in report.runs
                    if r.env == "preview" and r.journey_id == finding.journey_id and not r.passed]
            blocked = {c.viewport for c in checks if c.hard_signals}
            viewport: Literal["desktop", "mobile", "all"] = (
                "all" if len(blocked) != 1 else "mobile" if "mobile" in blocked else "desktop"
            )
            ctx = FixContext(
                finding=FixFinding.model_validate({
                    "title": finding.title, "severity": finding.severity,
                    "journey": finding.journey_id, "viewport": viewport,
                    "failing_step": (runs[0].blocked_at_step or 1) if runs else 1,
                }),
                observed_problem="\n".join(r.observed_problem for r in runs)
                    or "\n".join([finding.title, *finding.evidence]),
                console_errors=list(dict.fromkeys(e for c in checks for e in c.console_errors)),
                failed_requests=list(dict.fromkeys(e for c in checks for e in c.failed_requests)),
                hunks=[DiffHunk(path=p, patch=f.patch) for f in relevant for p in f.paths],
            )
            result = await asyncio.wait_for(
                suggest_fix(ctx, llm, search if should_search(ctx) else None), timeout=30,
            )
            finding.fix_suggestion = render_fix(result)
        except Exception:
            # Do not leak provider response bodies or let optional intelligence block CI.
            finding.fix_suggestion = "Fix suggestion unavailable"


def replay_report() -> Report:
    raw = files("ux_guardian.fixtures").joinpath("report.json").read_text(encoding="utf-8")
    return Report.model_validate_json(raw)


async def replay_pipeline(*, preview_url: str, pr: int, template: Report | None = None) -> Report:
    """Replay acquisition, bounded fan-out, comparison and rendering from fixtures.

    Journey selection and available enrichment are recorded in the fixture.
    No supplied URL is contacted and no enrichment API is called.
    """
    saved = template if template is not None else replay_report()
    config = load_config()
    journeys = load_journeys()
    if saved.check_results:
        replay_config = config.model_copy(update={"preview_url": preview_url})
        return checks_report(
            config=replay_config,
            journeys=journeys,
            checks=saved.check_results,
            fetch=saved.fetch,
            pr=pr,
            fixture=True,
        )
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


def checks_report(
    *,
    config: Config,
    journeys: list[Journey],
    checks: list[CheckResult],
    fetch: FetchResult,
    pr: int = 1,
    fixture: bool = False,
) -> Report:
    report = Report(
        pr=pr,
        sha="local",
        preview_url=config.preview_url,
        prod_url=config.production_url,
        fixture=fixture,
        affected=[
            Affected(
                journey_id=j.id, name=j.name, reason="All configured journeys (M2 entry checks)"
            )
            for j in journeys
        ],
        runs=[],
        checks=[],
        findings=[],
        check_results=checks,
        fetch=fetch,
    )
    for journey in journeys:
        confirmed: list[tuple[CheckResult, CheckResult]] = []
        for viewport in ("desktop", "mobile"):
            preview = next(
                (
                    c
                    for c in checks
                    if c.journey_id == journey.id and c.env == "preview" and c.viewport == viewport
                ),
                None,
            )
            prod = next(
                (
                    c
                    for c in checks
                    if c.journey_id == journey.id and c.env == "prod" and c.viewport == viewport
                ),
                None,
            )
            if not preview or not prod:
                continue
            verdict = judge_evidence(preview=preview, prod=prod, fetch=fetch)
            if verdict == Verdict.CONFIRMED:
                confirmed.append((preview, prod))
            elif verdict != Verdict.OK:
                section = {
                    Verdict.PREEXISTING: report.preexisting,
                    Verdict.IMPROVED: report.improved,
                    Verdict.CANDIDATE: report.flaky,
                }[verdict]
                section.append(f"{journey.name} ({viewport}): {verdict.value}")
        if confirmed:
            first, baseline = confirmed[0]
            hard_http = any(
                c.http_status is not None and 400 <= c.http_status < 600 for c, _ in confirmed
            )
            hard_http |= any(
                p.env == "preview"
                and p.journey_id == journey.id
                and p.http_status is not None
                and 400 <= p.http_status < 600
                for p in fetch.pages
            ) and any(f.hard and f.journey_id == journey.id for f in fetch.flags)
            severity = assign_severity(
                hard_error=hard_http, blocked_viewports=len(confirmed), total_viewports=2
            )
            evidence = [
                f"{c.viewport}: {signal}"
                for c, p in confirmed
                for signal in sorted(regression_signals(c, p))
            ]
            evidence.extend(
                f"Fetch: {f.evidence}" for f in fetch.flags if f.journey_id == journey.id
            )
            report.findings.append(
                Finding(
                    journey_id=journey.id,
                    severity=severity,
                    title=f"{journey.name} blocked on "
                    + ", ".join(c.viewport for c, _ in confirmed),
                    repro_steps=[
                        f"Open {config.preview_url + journey.entry_path} at "
                        f"{config.viewports[first.viewport]['width']}px width.",
                        "Inspect the critical controls and compare with production.",
                    ],
                    preview_screenshot=first.screenshot_path,
                    prod_screenshot=baseline.screenshot_path,
                    evidence=evidence,
                    fix_suggestion="Fix suggestion unavailable",
                )
            )
    return report


async def live_checks(
    *,
    config: Config,
    journeys: list[Journey],
    environments: list[Environment],
    output: Path,
) -> Report:
    start = monotonic()
    fetch = (
        await fetch_precheck(config=config, journeys=journeys, environments=environments)
        if config.include_fetch_precheck
        else FetchResult()
    )
    checks = await run_checks(
        config=config, journeys=journeys, environments=environments, output=output / "screenshots"
    )
    report = checks_report(config=config, journeys=journeys, checks=checks, fetch=fetch)
    report.duration_seconds = round(monotonic() - start, 2)
    return report

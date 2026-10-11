"""Manual CI pipeline over trusted code and PR files from the GitHub API."""

import math
import os
from pathlib import Path
from time import monotonic
from urllib.parse import urlsplit

import httpx

from ux_guardian.agents.base import BrowserAgent
from ux_guardian.agents.tinyfish import TinyFishAgent
from ux_guardian.config import Config, Journey, load_config, load_journeys, validate_url
from ux_guardian.diff.analyzer import Affected as Selection
from ux_guardian.diff.analyzer import analyze, normalize_diff
from ux_guardian.enrich.fix import FixSuggestion
from ux_guardian.github.pr import GitHubPr
from ux_guardian.judge.judge import Verdict, judge_evidence
from ux_guardian.llm import OpenAiLlmClient
from ux_guardian.report.models import Affected, Report
from ux_guardian.run import checks_report, enrich_findings, live_checks, write_report
from ux_guardian.security import redact


def preview_config(config: Config, preview_url: str) -> Config:
    url = validate_url(preview_url)
    parsed = urlsplit(url)
    host = parsed.hostname or ""
    if (
        parsed.scheme != "https"
        or parsed.port not in (None, 443)
        or parsed.path
        or not (host.startswith("ux-guardian-demo-") and host.endswith("-aranish-uk.vercel.app"))
    ):
        raise ValueError("CI requires a UX Guardian demo Vercel preview URL")
    return config.model_copy(
        update={"preview_url": url, "budget_usd_per_run": min(2.0, config.budget_usd_per_run)}
    )


async def add_agents(
    report: Report, config: Config, journeys: list[Journey], agent: BrowserAgent
) -> None:
    """Desktop pairs only; reserve their full step estimates before submitting.

    Agent-only failures stay unconfirmed in this slim M4 implementation. The
    deterministic judge remains authoritative; retry enrichment is deferred.
    """
    if not journeys:
        return
    reserved = 0.0
    step_cap = min(25, math.floor(config.budget_usd_per_run / (2 * len(journeys) * 0.016)))
    for journey in journeys:
        if step_cap < 1:
            report.flaky.append(f"{journey.name}: Agent pair skipped by budget cap.")
            continue
        journey = journey.model_copy(update={"max_steps": min(journey.max_steps, step_cap)})
        estimate = 2 * journey.max_steps * 0.016
        if max(reserved, sum(r.cost_usd for r in report.runs)) + estimate > (
            config.budget_usd_per_run
        ):
            report.flaky.append(f"{journey.name}: Agent pair skipped by budget cap.")
            continue
        reserved += estimate
        for env, url in (("preview", config.preview_url), ("prod", config.production_url)):
            run = await agent.run_journey(base_url=url, journey=journey, viewport="desktop")
            report.runs.append(run.model_copy(update={"env": env}))
        preview, prod = report.runs[-2:]
        desktop = [
            c for c in report.check_results
            if c.journey_id == journey.id and c.viewport == "desktop"
        ]
        verdict = judge_evidence(
            preview=next(c for c in desktop if c.env == "preview"),
            prod=next(c for c in desktop if c.env == "prod"),
            fetch=report.fetch, preview_agent=preview, prod_agent=prod,
        )
        if verdict == Verdict.CANDIDATE:
            report.flaky.append(
                f"{journey.name}: Agent-only failure needs confirmation. "
                f"{preview.observed_problem} Replay: {preview.replay_url or 'unavailable'}"
            )
        elif verdict == Verdict.PREEXISTING:
            report.preexisting.append(f"{journey.name}: Agent failed on preview and production.")
        elif verdict == Verdict.IMPROVED:
            report.improved.append(
                f"{journey.name}: Agent passed on preview, failed on production."
            )
        for finding in report.findings:
            if finding.journey_id == journey.id:
                finding.replay_url = preview.replay_url
                if not preview.passed and preview.steps:
                    finding.repro_steps = [
                        f"{step.action}: {step.observation}" for step in preview.steps
                    ]
    report.cost.agent_usd = sum(run.cost_usd for run in report.runs)
    report.cost.total_usd = report.cost.agent_usd


async def ci_pipeline(
    *, pr: int, preview_url: str, agent_runs: bool = False,
    output: Path = Path("artifacts"), client: httpx.AsyncClient | None = None,
) -> tuple[str, bool]:
    config = preview_config(load_config(), preview_url)
    if client is None:
        async with httpx.AsyncClient(timeout=30) as owned:
            return await ci_pipeline(
                pr=pr, preview_url=preview_url, agent_runs=agent_runs, output=output, client=owned
            )
    started = monotonic()
    github = GitHubPr(
        os.environ.get("GITHUB_REPOSITORY", ""), os.environ.get("GITHUB_TOKEN", ""), client
    )
    metadata = await github.metadata(pr)
    changed = normalize_diff(await github.changed_files(pr))
    if metadata.get("changed_files", len(changed)) != len(changed):
        raise ValueError("GitHub returned an incomplete PR file list; refusing partial analysis")
    journeys = load_journeys()
    llm = OpenAiLlmClient(config) if os.environ.get("LLM_API_KEY") else None
    try:
        analysis = await analyze(changed, journeys, llm)
    finally:
        if llm:
            await llm.close()
    if analysis.pending_files:
        # Missing intelligence must not produce a misleading clean/untested run.
        selected = {item.journey_id for item in analysis.affected}
        analysis.affected.extend(
            Selection(journey_id=j.id, source="shared", reason="Conservative coverage: "
                      "unmatched files need LLM review (LLM_API_KEY unavailable).")
            for j in journeys if j.id not in selected
        )
    selected_ids = {item.journey_id for item in analysis.affected}
    selected_journeys = [j for j in journeys if j.id in selected_ids]
    if selected_journeys:
        report = await live_checks(
            config=config, journeys=selected_journeys, environments=["preview", "prod"],
            output=output,
        )
    else:
        from ux_guardian.checks.models import FetchResult

        report = checks_report(config=config, journeys=[], checks=[], fetch=FetchResult())
    report.pr = pr
    report.sha = metadata["head"]["sha"]
    report.affected = [
        Affected(journey_id=item.journey_id,
                 name=next(j.name for j in journeys if j.id == item.journey_id),
                 reason=item.reason, source=item.source)
        for item in analysis.affected
    ]
    report.analysis_reasoning = analysis.reasoning
    if not selected_journeys:
        report.analysis_reasoning = (
            "No customer-facing journeys affected. " + report.analysis_reasoning
        ).strip()
    run_id = os.environ.get("GITHUB_RUN_ID")
    if run_id:
        report.artifact_url = (
            f"https://github.com/{github.repository}/actions/runs/{run_id}#artifacts"
        )
    if agent_runs and selected_journeys:
        step_cap = min(
            25, math.floor(config.budget_usd_per_run / (2 * len(selected_journeys) * 0.016))
        )
        estimate = sum(2 * min(j.max_steps, step_cap) * 0.016 for j in selected_journeys)
        print(f"TinyFish Agent estimate: ${estimate:.2f}; budget cap: "
              f"${config.budget_usd_per_run:.2f}. Explicit --agent-runs authorization.")
        agent = TinyFishAgent(
            config=config, output=output / "runs",
            allowed_urls=[config.preview_url, config.production_url],
        )
        await add_agents(report, config, selected_journeys, agent)
    fix_llm = None
    try:
        if report.findings and os.environ.get("LLM_API_KEY"):
            fix_llm = OpenAiLlmClient(config, output_model=FixSuggestion)
        await enrich_findings(
            report, config, selected_journeys, changed, fix_llm,
            max_calls=3 - int(analysis.llm_response is not None),
        )
    except Exception:
        for finding in report.findings:
            finding.fix_suggestion = "Fix suggestion unavailable"
    finally:
        if fix_llm:
            try:
                await fix_llm.close()
            except Exception:
                pass
    report.duration_seconds = round(monotonic() - started, 2)
    write_report(report, output)
    body = (output / "report.md").read_text(encoding="utf-8")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with Path(summary).open("a", encoding="utf-8") as stream:
            stream.write(body)
    url = await github.upsert_comment(pr, redact(body))
    return url, any(f.severity in config.fail_on for f in report.findings)

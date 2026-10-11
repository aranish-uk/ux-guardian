"""Deterministic FR10 markdown from saved evidence, never from a new agent run."""

import re
from html import escape

from ux_guardian.report.models import Report
from ux_guardian.security import redact_model


def cell(value: str) -> str:
    return escape(value).replace("|", "&#124;").replace("\n", " ")


def render(report: Report) -> str:
    report = redact_model(report)
    verdict = (
        f"{len(report.findings)} confirmed "
        + ("regression" if len(report.findings) == 1 else "regressions")
        if report.findings else "No regressions"
    )
    lines = [
        "<!-- ux-guardian -->",
        f"## UX Guardian — {verdict}",
        "",
        f"[Preview]({report.preview_url}) · [Production]({report.prod_url}) · "
        f"{report.duration_seconds:g}s · TinyFish ${report.cost.total_usd:.2f}",
        "",
    ]
    if report.fixture:
        label = "Recorded evidence replay" if report.check_results else "Synthetic fixture replay"
        lines += [f"> {label} — no website was tested and no API was called.", ""]
    if report.analysis_reasoning:
        lines += [cell(report.analysis_reasoning), ""]
    lines += [
        "| Journey | Why tested | Preview desktop | Prod desktop | Preview mobile | Prod mobile |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for affected in report.affected:
        values = []
        for viewport, env in [
            ("desktop", "preview"),
            ("desktop", "prod"),
            ("mobile", "preview"),
            ("mobile", "prod"),
        ]:
            runs = [
                r
                for r in report.runs
                if r.journey_id == affected.journey_id and r.viewport == viewport and r.env == env
            ]
            checks = [
                c
                for c in report.check_results
                if c.journey_id == affected.journey_id and c.viewport == viewport and c.env == env
            ]
            values.append(
                "PASS"
                if checks and checks[0].passed
                else "FAIL"
                if checks
                else "PASS"
                if runs and runs[0].passed
                else "FAIL"
                if runs
                else "Not run"
            )
            if checks and runs:
                values[-1] += " / Agent " + ("PASS" if runs[0].passed else "FAIL (see evidence)")
        lines.append(
            f"| {cell(affected.name)} | {cell(affected.reason)} | " + " | ".join(values) + " |"
        )
    lines.append("")
    for finding in report.findings:
        lines += [
            "<details>",
            f"<summary>{finding.severity} — {cell(finding.title)}</summary>",
            "",
            "**Repro steps**",
            "",
        ]
        lines += [f"{n}. {cell(step)}" for n, step in enumerate(finding.repro_steps, 1)]
        lines += [
            "",
            "| Preview | Production |",
            "| --- | --- |",
            f"| {screenshot(finding.preview_screenshot, 'Preview', report)} | "
            f"{screenshot(finding.prod_screenshot, 'Production', report)} |",
            "",
            "**Evidence**",
            "",
        ]
        lines += [f"- {cell(signal)}" for signal in finding.evidence]
        lines += ["", "**Fix suggestion**", "", finding.fix_suggestion, ""]
        lines += ["</details>", ""]
    lines += [
        "### TinyFish agent journeys (desktop)", "",
        "| Journey | Env | Result | Steps | Cost | Final step | Run ID |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    names = {affected.journey_id: affected.name for affected in report.affected}
    for run in report.runs:
        if run.viewport != "desktop":
            continue
        result = "PASS" if run.passed else "FAIL" if run.status == "COMPLETED" else run.status
        image = screenshot(run.steps[-1].screenshot_path if run.steps else "",
                           "Final step", report, width=220)
        lines.append(
            f"| {cell(names.get(run.journey_id, run.journey_id))} | "
            f"{'Preview' if run.env == 'preview' else 'Production'} | {cell(result)} | "
            f"{len(run.steps)} | ${run.cost_usd:.2f} | {image} | {cell(run.run_id[:8])} |"
        )
    if not any(run.viewport == "desktop" for run in report.runs):
        lines += ["", "No desktop agent journeys were run."]
    lines.append("")
    for title, items in [
        ("Pre-existing issues", report.preexisting),
        ("Flaky / needs human look", report.flaky),
        ("Improved", report.improved),
    ]:
        lines += ["<details>", f"<summary>{title} ({len(items)})</summary>", ""]
        for item in items:
            lines.append(f"- {cell(item)}")
            if title == "Flaky / needs human look":
                for run in report.runs:
                    name = names.get(run.journey_id, run.journey_id)
                    if (run.env == "preview" and not run.passed and run.steps
                            and (item.startswith(name + ":") or item.startswith(name + " ("))):
                        source = run.steps[-1].screenshot_path
                        if source in report.asset_urls:
                            lines += ["", screenshot(source, "Final step", report, width=220), ""]
        if not items:
            lines.append("None.")
        lines += ["", "</details>", ""]
    lines += [
        "Re-run: dispatch the UX Guardian workflow with the PR number and preview URL. "
        "`/ux-guardian rerun` is planned after MVP.",
        "",
        f"Cost: Agent ${report.cost.agent_usd:.2f} · Fetch ${report.cost.fetch_usd:.2f} · "
        f"Search ${report.cost.search_usd:.2f} · Total ${report.cost.total_usd:.2f}",
        "",
    ]
    if report.artifact_url:
        lines += [f"[Full evidence (zip)]({report.artifact_url})", ""]
    markdown = "\n".join(lines)
    # Old artifacts and free-form agent/LLM text may contain live URLs too.
    # This boundary also protects report.md, PR comments and the step summary.
    for url in {r.replay_url for r in report.runs} | {f.replay_url for f in report.findings}:
        if url:
            markdown = markdown.replace(escape(url), "").replace(url, "")
    markdown = re.sub(
        r"https?://[^\s<>\"'()]*tinyfish\.io\b[^\s<>\"'()]*", "", markdown,
        flags=re.IGNORECASE,
    )
    return re.sub(r"Replay:[ \t]*(?=\n|$)", "", markdown, flags=re.IGNORECASE)


def screenshot(source: str, label: str, report: Report, *, width: int = 260) -> str:
    if not source:
        return "Not recorded"
    url = report.asset_urls.get(source, "")
    if not url and report.artifact_url:
        return f"[{label} screenshot: {cell(source)}]({report.artifact_url})"
    url = url or source
    return f'<img width="{width}" alt="{cell(label)}" src="{cell(url)}">'

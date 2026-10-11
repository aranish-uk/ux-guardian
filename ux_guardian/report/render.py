"""Deterministic FR10 markdown from saved evidence, never from a new agent run."""

from html import escape

from ux_guardian.report.models import Report
from ux_guardian.security import redact_model


def cell(value: str) -> str:
    return escape(value).replace("|", "&#124;").replace("\n", " ")


def render(report: Report) -> str:
    report = redact_model(report)
    verdict = (
        f"{len(report.findings)} confirmed regressions" if report.findings else "No regressions"
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
        lines += ["> Synthetic fixture replay — no website was tested and no API was called.", ""]
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
            values.append("PASS" if runs and runs[0].passed else "FAIL" if runs else "Not run")
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
            f"| {screenshot(finding.preview_screenshot, 'Preview')} | "
            f"{screenshot(finding.prod_screenshot, 'Production')} |",
            "",
            "**Evidence**",
            "",
        ]
        lines += [f"- {cell(signal)}" for signal in finding.evidence]
        lines += ["", "**Fix suggestion**", "", finding.fix_suggestion, ""]
        if finding.replay_url:
            lines += [f"[TinyFish replay]({finding.replay_url})", ""]
        lines += ["</details>", ""]
    for title, items in [
        ("Pre-existing issues", report.preexisting),
        ("Flaky / needs human look", report.flaky),
        ("Improved", report.improved),
    ]:
        lines += ["<details>", f"<summary>{title} ({len(items)})</summary>", ""]
        lines += [f"- {cell(item)}" for item in items] if items else ["None."]
        lines += ["", "</details>", ""]
    lines += [
        "Re-run: push again once the Action is configured (M4). "
        "`/ux-guardian rerun` is planned after MVP.",
        "",
        f"Cost: Agent ${report.cost.agent_usd:.2f} · Fetch ${report.cost.fetch_usd:.2f} · "
        f"Search ${report.cost.search_usd:.2f} · Total ${report.cost.total_usd:.2f}",
        "",
    ]
    return "\n".join(lines)


def screenshot(url: str, label: str) -> str:
    return f"![{label}]({url})" if url else "Not recorded in this fixture"

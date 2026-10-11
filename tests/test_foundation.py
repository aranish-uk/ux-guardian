import asyncio
import json
import secrets
from pathlib import Path

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from ux_guardian.agents.base import AgentRun
from ux_guardian.cli import app
from ux_guardian.config import SAFETY_PREAMBLE, Config, Journey, Viewport, load_journeys
from ux_guardian.judge.judge import Verdict, judge
from ux_guardian.judge.severity import Severity, assign_severity, lower_severity
from ux_guardian.run import replay_pipeline, replay_report, write_report
from ux_guardian.swarm import RunRequest, run_pool


@pytest.mark.parametrize(
    ("preview", "prod", "expected"),
    [
        (False, True, Verdict.CANDIDATE),
        (False, False, Verdict.PREEXISTING),
        (True, True, Verdict.OK),
        (True, False, Verdict.IMPROVED),
    ],
)
def test_truth_table(preview: bool, prod: bool, expected: Verdict) -> None:
    assert judge(preview_pass=preview, prod_pass=prod) == expected


def test_confirmation() -> None:
    assert judge(preview_pass=False, prod_pass=True, deterministic_agrees=True) == Verdict.CONFIRMED
    assert judge(preview_pass=False, prod_pass=True, failed_step=4, retry_failed_step=3) == (
        Verdict.CONFIRMED
    )
    assert judge(preview_pass=False, prod_pass=True, failed_step=4, retry_failed_step=5) == (
        Verdict.CANDIDATE
    )
    assert (
        judge(preview_pass=False, prod_pass=False, deterministic_agrees=True) == Verdict.PREEXISTING
    )


@pytest.mark.parametrize(
    ("hard", "blocked", "total", "expected"),
    [
        (True, 0, 2, Severity.P0),
        (False, 2, 2, Severity.P0),
        (False, 1, 2, Severity.P1),
        (False, 0, 2, Severity.P2),
    ],
)
def test_severity(hard: bool, blocked: int, total: int, expected: Severity) -> None:
    assert (
        assign_severity(hard_error=hard, blocked_viewports=blocked, total_viewports=total)
        == expected
    )


def test_llm_cannot_raise_severity() -> None:
    with pytest.raises(ValueError):
        lower_severity(Severity.P1, Severity.P0, justification="hypothesis")
    with pytest.raises(ValueError):
        lower_severity(Severity.P0, Severity.P1, justification="")
    assert lower_severity(Severity.P0, Severity.P1, justification="desktop works") == Severity.P1


def test_completed_status_does_not_mean_success() -> None:
    run = AgentRun(
        run_id="fixture",
        env="prod",
        journey_id="sign-in",
        viewport="mobile",
        status="COMPLETED",
        completed=False,
        success_criteria_met=True,
    )
    assert not run.passed
    assert not run.model_copy(update={"completed": True, "success_criteria_met": False}).passed
    assert not run.model_copy(update={"completed": True, "status": "FAILED"}).passed


def test_manifest_and_config_validation() -> None:
    journeys = load_journeys(Path(".ux-guardian") / "journeys.yaml")
    assert [j.id for j in journeys] == ["sign-in", "search-cart", "checkout"]
    assert all(j.safe_goal.startswith(SAFETY_PREAMBLE) for j in journeys)
    with pytest.raises(ValidationError):
        Config(production_url="file:///secret")
    with pytest.raises(ValidationError):
        Config(concurrency=0)
    with pytest.raises(ValidationError):
        Config(budget_usd_per_run=-1)
    with pytest.raises(ValidationError):
        Journey(
            id="bad",
            name="Bad",
            entry_path="https://elsewhere.test",
            goal="noop",
            success_criteria=["ok"],
        )


def test_swarm_bounds_concurrency_and_preserves_order() -> None:
    class FakeAgent:
        active = 0
        maximum = 0

        async def run_journey(
            self, *, base_url: str, journey: Journey, viewport: Viewport
        ) -> AgentRun:
            self.active += 1
            self.maximum = max(self.maximum, self.active)
            await asyncio.sleep(0.01)
            self.active -= 1
            return AgentRun(
                run_id=journey.id,
                env="prod",
                journey_id=journey.id,
                viewport=viewport,
                status="COMPLETED",
                completed=True,
                success_criteria_met=True,
            )

    agent = FakeAgent()
    journeys = load_journeys(Path(".ux-guardian") / "journeys.yaml")
    requests = [
        RunRequest(base_url="http://localhost:3000", journey=j, viewport="desktop", env="prod")
        for j in journeys
    ]
    results = asyncio.run(run_pool(agent, requests, concurrency=2))
    assert agent.maximum == 2
    assert [r.journey_id for r in results] == [j.id for j in journeys]


def test_dry_run_replays_without_network(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        app,
        [
            "run",
            "--preview-url",
            "https://offline.invalid",
            "--pr",
            "7",
            "--dry-run",
            "--output",
            str(tmp_path),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "fixture" in result.output.lower()
    assert (tmp_path / "report.json").exists()
    markdown = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert "<!-- ux-guardian -->" in markdown
    assert "https://offline.invalid" in markdown
    assert "$0.00" in markdown


def test_cli_refuses_live_pipeline_and_invalid_urls() -> None:
    runner = CliRunner()
    assert runner.invoke(
        app, ["run", "--preview-url", "https://example.test", "--pr", "1"]
    ).exit_code
    assert runner.invoke(
        app, ["run", "--preview-url", "file:///secret", "--pr", "1", "--dry-run"]
    ).exit_code
    result = runner.invoke(
        app, ["live", "journey", "--journey", "sign-in", "--env", "prod"], input="n\n"
    )
    assert result.exit_code != 0
    assert "$0.40" in result.output
    assert "confirm" in result.output.lower()



def test_report_snapshot() -> None:
    from ux_guardian.report.render import render

    report = replay_report()
    expected = (Path("tests") / "snapshots" / "report.md").read_text(encoding="utf-8")
    assert render(report) == expected


def test_fixture_pipeline_judges_runs_instead_of_trusting_findings() -> None:
    template = replay_report()
    template.checks = []
    template.runs = [run for run in template.runs if run.attempt == 1]
    report = asyncio.run(
        replay_pipeline(preview_url="https://offline.invalid", pr=3, template=template)
    )
    assert not report.findings
    assert len(report.flaky) == 1
    assert len(report.runs) == 12


def test_fixture_pipeline_confirms_recorded_retry() -> None:
    report = asyncio.run(replay_pipeline(preview_url="https://offline.invalid", pr=3))
    assert len(report.findings) == 1
    assert report.findings[0].severity == Severity.P1
    assert len(report.runs) == 13


def test_saved_report_redacts_escaped_secrets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prefix = secrets.token_urlsafe(24)
    secret = prefix + "\"'&|\\\n"
    monkeypatch.setenv("TEST_PASSWORD", secret)
    report = replay_report()
    report.findings[0].title += secret
    write_report(report, tmp_path)
    data = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    safe_json = secret not in data["findings"][0]["title"]
    assert safe_json, "Credential was not redacted before JSON encoding"
    assert "[REDACTED]" in data["findings"][0]["title"]
    safe_markdown = secret not in (tmp_path / "report.md").read_text(encoding="utf-8")
    assert safe_markdown, "Credential was not redacted in markdown"
    markdown = (tmp_path / "report.md").read_text(encoding="utf-8")
    safe_prefix = prefix not in markdown
    assert safe_prefix, "Escaped credential remains in markdown"
    assert "[REDACTED]" in markdown


def test_mcp_redacts_before_rendering(monkeypatch: pytest.MonkeyPatch) -> None:
    from ux_guardian import mcp_server

    prefix = secrets.token_urlsafe(24)
    secret = prefix + "\"'&|\\\n"
    monkeypatch.setenv("TEST_PASSWORD", secret)
    report = replay_report()
    report.findings[0].title += secret
    monkeypatch.setattr(mcp_server, "replay_report", lambda: report)
    identifier = asyncio.run(mcp_server.start("https://offline.invalid"))
    output = asyncio.run(mcp_server.results(identifier))
    safe_output = prefix not in output
    assert safe_output, "Escaped credential remains in MCP output"
    assert "[REDACTED]" in output


def test_vendor_import_boundary() -> None:
    import ast

    for path in Path("ux_guardian").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            imports = (
                [alias.name for alias in node.names]
                if isinstance(node, ast.Import)
                else [node.module or ""]
                if isinstance(node, ast.ImportFrom)
                else []
            )
            assert not any(name.startswith("browser_use") for name in imports)
            if any(name == "tinyfish" or name.startswith("tinyfish.") for name in imports):
                assert path == Path("ux_guardian") / "agents" / "tinyfish.py" or (
                    path.is_relative_to(Path("ux_guardian") / "tinyfish")
                )

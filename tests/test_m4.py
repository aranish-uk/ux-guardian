import asyncio
import json
from importlib.resources import files
from pathlib import Path

import httpx
import pytest
import yaml
from typer.testing import CliRunner

from ux_guardian import ci
from ux_guardian.agents.base import AgentRun
from ux_guardian.cli import app
from ux_guardian.config import Config, Journey, Viewport, load_config, load_journeys
from ux_guardian.github.pr import MARKER, GitHubPr
from ux_guardian.report.models import Report
from ux_guardian.report.render import render

PREVIEW = "https://ux-guardian-demo-test-aranish-uk.vercel.app"
FIXTURES = files("ux_guardian.fixtures")


def test_comment_create_then_update_and_pagination():
    requests = []
    stored = []

    def handle(request):
        requests.append(request)
        assert request.headers["Authorization"] == "Bearer fixture-token"
        if request.method == "GET":
            page = int(request.url.params["page"])
            if stored and page == 1:
                return httpx.Response(200, json=[{"body": "Other comment"}] * 100)
            return httpx.Response(200, json=stored if stored else [])
        body = json.loads(request.content)["body"]
        stored[:] = [{"id": 12, "body": body, "user": {"type": "Bot"}}]
        return httpx.Response(201, json={"html_url": "https://github.com/o/r/issues/1#comment-12"})

    async def execute():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            github = GitHubPr("o/r", "fixture-token", client)
            first = await github.upsert_comment(1, MARKER + "\nfirst")
            second = await github.upsert_comment(1, MARKER + "\nsecond")
            assert first == second

    asyncio.run(execute())
    mutations = [r for r in requests if r.method != "GET"]
    assert [r.method for r in mutations] == ["POST", "PATCH"]
    assert mutations[-1].url.path == "/repos/o/r/issues/comments/12"
    assert stored[0]["body"].endswith("second")


def test_github_rejects_fork_and_sanitizes_error():
    async def execute():
        def handle(request):
            if request.url.path.endswith("/pulls/1"):
                return httpx.Response(200, json={"head": {"repo": {"full_name": "fork/r"}}})
            return httpx.Response(403, text="credential-sensitive-body")

        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            github = GitHubPr("o/r", "fixture-token", client)
            with pytest.raises(ValueError, match="Fork"):
                await github.metadata(1)
            with pytest.raises(ValueError, match="body omitted") as error:
                await github.changed_files(1)
            assert "credential-sensitive-body" not in str(error.value)

    asyncio.run(execute())


@pytest.mark.parametrize("url", [
    "https://example.com", "https://ux-guardian-demo-test-aranish-uk.vercel.app.evil.test",
    PREVIEW + "/login", PREVIEW + ":444", "http://localhost:3000",
])
def test_preview_origin_restriction(url):
    with pytest.raises(ValueError):
        ci.preview_config(load_config(), url)


@pytest.mark.parametrize("upload_failure", [False, True])
def test_ci_runs_selected_fixture_checks_and_publishes(monkeypatch, tmp_path, upload_failure):
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    monkeypatch.setenv("GITHUB_TOKEN", "fixture-token")
    monkeypatch.setenv("GITHUB_RUN_ID", "123")
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(tmp_path / "summary.md"))
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    acquired = []
    published = []
    assets_published = []
    saved = Report.model_validate_json(FIXTURES.joinpath("m2_mobile_overlay.json").read_text())

    async def checks(*, config, journeys, environments, output):
        acquired.extend(j.id for j in journeys)
        assert environments == ["preview", "prod"]
        assert config.preview_url == PREVIEW
        recorded = [c.model_copy(deep=True) for c in saved.check_results
                    if c.journey_id == "sign-in"]
        directory = output / "screenshots"
        directory.mkdir()
        for check in recorded:
            path = directory / f"{check.env}-{check.viewport}.png"
            path.write_bytes(b"fixture-png")
            check.screenshot_path = str(path)
        return ci.checks_report(
            config=config, journeys=journeys,
            checks=recorded,
            fetch=saved.fetch,
        )

    def handle(request):
        if "/git/" in request.url.path:
            if request.url.path.endswith("/git/ref/heads/ux-guardian-assets"):
                return httpx.Response(404)
            if upload_failure and request.url.path.endswith("/git/blobs"):
                return httpx.Response(403)
            if request.url.path.endswith("/git/refs"):
                assets_published.append(True)
            return httpx.Response(201, json={"sha": "fixture-sha"})
        if request.url.path.endswith("/pulls/7"):
            return httpx.Response(200, json={
                "head": {"sha": "head-sha", "repo": {"full_name": "o/r"}}
            })
        if request.url.path.endswith("/files"):
            return httpx.Response(200, json=[{
                "filename": "demo-app/components/auth/login.tsx", "patch": "fixture patch"
            }])
        if request.method == "GET":
            return httpx.Response(200, json=[])
        assert bool(assets_published) != upload_failure
        published.append(json.loads(request.content)["body"])
        return httpx.Response(201, json={"html_url": "https://github.com/o/r/pull/7#comment-1"})

    monkeypatch.setattr(ci, "live_checks", checks)
    monkeypatch.setattr(ci, "TinyFishAgent", lambda **kw: pytest.fail("Agent enabled by default"))

    async def execute():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            return await ci.ci_pipeline(pr=7, preview_url=PREVIEW, output=tmp_path, client=client)

    url, failed = asyncio.run(execute())
    assert url.endswith("#comment-1") and not failed  # Default fail_on is P0; mobile is P1.
    assert acquired == ["sign-in"]
    report = Report.model_validate_json((tmp_path / "report.json").read_text())
    assert report.sha == "head-sha" and report.pr == 7
    assert len(report.findings) == 1 and report.findings[0].severity == "P1"
    assert not report.runs and not report.fixture
    body = published[0]
    assert "1 confirmed regression\n" in body
    assert "1 confirmed regressions" not in body
    assert "actions/runs/123#artifacts" in body
    assert "![Preview]" not in body
    assert bool(report.asset_urls) != upload_failure
    assert ('<img width="260"' in body) != upload_failure
    assert ("raw.githubusercontent.com/o/r/ux-guardian-assets/pr-7/run-123/" in body) != (
        upload_failure
    )
    assert "TinyFish replay" not in body
    assert "Full evidence (zip)" in body
    assert render(report) == body
    assert (tmp_path / "summary.md").read_text(encoding="utf-8") == body
    assert (tmp_path / "report.md").read_text(encoding="utf-8") == body


def test_desktop_agent_pairs_budget_and_unconfirmed(monkeypatch):
    journeys = load_journeys()
    saved = Report.model_validate_json(FIXTURES.joinpath("m2_clean.json").read_text())
    report = saved.model_copy(deep=True)
    called = []

    class FakeAgent:
        async def run_journey(
            self, *, base_url: str, journey: Journey, viewport: Viewport
        ) -> AgentRun:
            called.append((journey.id, base_url, viewport))
            passed = base_url == saved.prod_url
            return AgentRun(
                run_id="fixture", env="prod", journey_id=journey.id, viewport=viewport,
                status="COMPLETED", completed=passed, success_criteria_met=passed,
                blocked_at_step=None if passed else 2, cost_usd=journey.max_steps * 0.016,
            )

    config = Config(preview_url=saved.preview_url, production_url=saved.prod_url,
                    budget_usd_per_run=2)
    asyncio.run(ci.add_agents(report, config, journeys, FakeAgent()))
    assert len(called) == 6 and all(c[2] == "desktop" for c in called)
    assert len(report.runs) == 6 and report.cost.agent_usd == pytest.approx(1.92)
    assert not report.findings
    assert sum("needs confirmation" in item for item in report.flaky) == 3


def test_ci_cli_prints_url_and_failure_status(monkeypatch):
    async def pipeline(**kwargs):
        assert kwargs["agent_runs"] is False
        return "https://github.com/o/r/pull/7#comment-1", True

    monkeypatch.setattr(ci, "ci_pipeline", pipeline)
    result = CliRunner().invoke(app, ["ci", "--pr", "7", "--preview-url", PREVIEW])
    assert result.exit_code == 1
    assert "https://github.com/o/r/pull/7#comment-1" in result.output


def test_dispatch_workflow_contract():
    # BaseLoader preserves GitHub's YAML `on` key as a string.
    workflow = yaml.load(
        (Path(".github") / "workflows" / "ux-guardian.yml").read_text(), Loader=yaml.BaseLoader
    )
    inputs = workflow["on"]["workflow_dispatch"]["inputs"]
    assert inputs["agent_runs"]["default"] == "false"
    assert inputs["base_ref"]["default"] == "main"
    assert inputs["preview_url"]["required"] == inputs["pr_number"]["required"] == "true"
    assert workflow["permissions"] == {
        "contents": "write", "pull-requests": "write", "deployments": "read", "statuses": "read"
    }
    steps = workflow["jobs"]["guardian"]["steps"]
    assert steps[0]["with"]["ref"] == "${{ inputs.base_ref || 'main' }}"
    assert steps[0]["with"]["fetch-depth"] == "0"
    assert any(s.get("run") == "uv sync --locked" for s in steps)
    assert steps[-1]["if"] == "always()"


def test_artifact_report_reproduces_from_json():
    report = Report.model_validate_json(FIXTURES.joinpath("report.json").read_text())
    report.artifact_url = "https://github.com/o/r/actions/runs/123#artifacts"
    assert render(Report.model_validate_json(report.model_dump_json())) == render(report)


@pytest.mark.parametrize("case", ["clean", "unmatched", "fork", "broken-cart"])
def test_ci_selection_and_acquisition_boundaries(case, monkeypatch, tmp_path):
    from ux_guardian import run

    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    monkeypatch.setenv("GITHUB_TOKEN", "fixture-token")
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    events = []
    bodies = []
    fixture_name = "m3_broken_cart.json" if case == "broken-cart" else "m2_clean.json"
    saved = Report.model_validate_json(FIXTURES.joinpath(fixture_name).read_text())

    async def fetch(*, config, journeys, environments):
        events.append(("fetch", [j.id for j in journeys]))
        return saved.fetch

    async def checks(*, config, journeys, environments, output):
        events.append(("checks", [j.id for j in journeys]))
        ids = {j.id for j in journeys}
        return [c for c in saved.check_results if c.journey_id in ids]

    class FakeLlm:
        def __init__(self, config):
            pass

        async def complete_json(self, *, system, prompt):
            events.append(("llm", []))
            return {"affected": [], "reasoning": "Harmless marketing copy only."}

        async def close(self):
            pass

    if case == "clean":
        monkeypatch.setenv("LLM_API_KEY", "fixture-llm-key")
        monkeypatch.setattr(ci, "OpenAiLlmClient", FakeLlm)
    monkeypatch.setattr(run, "fetch_precheck", fetch)
    monkeypatch.setattr(run, "run_checks", checks)
    monkeypatch.setattr(ci, "TinyFishAgent", lambda **kw: pytest.fail("Paid call attempted"))

    def handle(request):
        if request.url.path.endswith("/pulls/7"):
            return httpx.Response(200, json={"head": {
                "sha": "demo-sha", "repo": {"full_name": "fork/r" if case == "fork" else "o/r"}
            }})
        if request.url.path.endswith("/files"):
            events.append(("files", []))
            filename = "demo-app/app/cart/page.tsx" if case == "broken-cart" else "helper.ts"
            return httpx.Response(200, json=[{"filename": filename, "patch": "fixture patch"}])
        if request.method == "GET":
            return httpx.Response(200, json=[])
        bodies.append(json.loads(request.content)["body"])
        return httpx.Response(201, json={"html_url": "https://github.com/o/r/pull/7#comment-1"})

    async def execute():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            return await ci.ci_pipeline(
                pr=7, preview_url=PREVIEW, agent_runs=case == "clean",
                output=tmp_path, client=client,
            )

    if case == "fork":
        with pytest.raises(ValueError, match="Fork"):
            asyncio.run(execute())
        assert not events and not bodies and not (tmp_path / "report.json").exists()
        return
    _, failed = asyncio.run(execute())
    report = Report.model_validate_json((tmp_path / "report.json").read_text(encoding="utf-8"))
    if case == "clean":
        assert [e[0] for e in events] == ["files", "llm"]
        assert not report.affected and not report.findings
        assert "Harmless marketing copy" in bodies[0]
    elif case == "unmatched":
        assert [e[0] for e in events] == ["files", "fetch", "checks"]
        assert len(report.affected) == 3
        assert all("Conservative coverage" in a.reason for a in report.affected)
        assert not failed
    else:
        assert [e[0] for e in events] == ["files", "fetch", "checks"]
        assert "checkout" in events[-1][1]
        assert failed and report.findings[0].severity == "P0"

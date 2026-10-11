import asyncio
import json
from importlib.resources import files
from pathlib import Path

import httpx
import pytest

from ux_guardian import ci, run
from ux_guardian.config import Config, load_journeys
from ux_guardian.diff.analyzer import ChangedFile
from ux_guardian.report.models import Report
from ux_guardian.report.render import render
from ux_guardian.run import enrich_findings


@pytest.mark.parametrize("failure", [False, True])
def test_confirmed_fix_is_rendered_or_unavailable(failure):
    report = Report.model_validate_json(
        files("ux_guardian.fixtures").joinpath("m2_mobile_overlay.json").read_text()
    )
    report.check_results[0].console_errors = ["fixture console error"]
    report.check_results[0].failed_requests = ["GET /fixture failed"]
    prompts = []

    class Llm:
        async def complete_json(self, *, system, prompt):
            prompts.append(json.loads(prompt)["context"])
            if failure:
                raise RuntimeError("private failure body")
            return {
                "root_cause": "Overlay intercepts input.",
                "suggestion_markdown": "Remove pointer interception.",
                "patch": "--- a/demo-app/components/auth/login.tsx\n"
                         "+++ b/demo-app/components/auth/login.tsx\n"
                         "@@ -1 +1 @@\n-overlay\n+button\n",
                "confidence": "high", "sources": [],
            }

    asyncio.run(enrich_findings(
        report, Config(include_search=False), load_journeys(),
        [ChangedFile(filename="demo-app/components/auth/login.tsx", patch="auth patch"),
         ChangedFile(filename="demo-app/app/cart/page.tsx", patch="unrelated patch")], Llm(),
    ))
    body = render(report)
    assert len(prompts) == 1
    assert prompts[0]["hunks"] == [
        {"path": "demo-app/components/auth/login.tsx", "patch": "auth patch"}
    ]
    assert "fixture console error" in prompts[0]["console_errors"]
    assert "GET /fixture failed" in prompts[0]["failed_requests"]
    assert "Pending diff-grounded" not in body
    if failure:
        assert "Fix suggestion unavailable" in body
        assert "private failure body" not in body
    else:
        assert "Overlay intercepts input." in body
        assert "```diff\n" in body and "<summary>Suggested patch</summary>" in body
        assert "```suggestion" not in body
        assert body == (Path("tests") / "snapshots" / "m5_confirmed.md").read_text("utf-8")


def test_enrichment_caps_calls_and_falls_back_to_ui_hunks():
    report = Report.model_validate_json(
        files("ux_guardian.fixtures").joinpath("m2_mobile_overlay.json").read_text()
    )
    report.findings = [report.findings[0].model_copy(deep=True) for _ in range(4)]
    calls = []

    class Llm:
        async def complete_json(self, *, system, prompt):
            calls.append(json.loads(prompt)["context"])
            raise TimeoutError()

    asyncio.run(enrich_findings(
        report, Config(include_search=False), load_journeys(),
        [ChangedFile(filename="components/shared.tsx", patch="shared patch"),
         ChangedFile(filename="README.md", patch="docs")], Llm(),
    ))
    assert len(calls) == 3
    assert all(c["hunks"] == [{"path": "components/shared.tsx", "patch": "shared patch"}]
               for c in calls)
    assert all("Fix suggestion unavailable" in f.fix_suggestion for f in report.findings)


@pytest.mark.parametrize("failure", [False, True])
def test_ci_publishes_fix_and_counts_analysis_in_call_cap(monkeypatch, tmp_path, failure):
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    monkeypatch.setenv("GITHUB_TOKEN", "fixture")
    monkeypatch.setenv("LLM_API_KEY", "fixture")
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    models = []
    calls = []
    bodies = []

    class Llm:
        def __init__(self, config, *, output_model=None):
            self.fix = output_model is not None
            models.append(config.llm_model)

        async def complete_json(self, *, system, prompt):
            calls.append(self.fix)
            if not self.fix:
                return {"affected": [], "reasoning": "Shared helper reviewed."}
            if failure:
                raise RuntimeError("sensitive provider body")
            return {"root_cause": "Overlay intercepts input.", "suggestion_markdown": "Remove it.",
                    "patch": None, "confidence": "medium", "sources": []}

        async def close(self):
            pass

    async def checks(**kwargs):
        report = Report.model_validate_json(
            files("ux_guardian.fixtures").joinpath("m2_mobile_overlay.json").read_text()
        )
        report.findings = [report.findings[0].model_copy(deep=True) for _ in range(4)]
        return report

    def handle(request):
        if request.url.path.endswith("/pulls/7"):
            return httpx.Response(200, json={"head": {
                "sha": "fixture", "repo": {"full_name": "o/r"}}})
        if request.url.path.endswith("/files"):
            return httpx.Response(200, json=[
                {"filename": "demo-app/components/auth/login.tsx", "patch": "auth patch"},
                {"filename": "helper.ts", "patch": "helper patch"},
            ])
        if request.method == "GET":
            return httpx.Response(200, json=[])
        bodies.append(json.loads(request.content)["body"])
        return httpx.Response(201, json={"html_url": "https://github.com/o/r/pull/7#comment"})

    monkeypatch.setattr(ci, "OpenAiLlmClient", Llm)
    monkeypatch.setattr(ci, "live_checks", checks)
    monkeypatch.setattr(run, "SearchClient", lambda: pytest.fail("Search not needed"))
    config = Config(include_search=False)
    monkeypatch.setattr(ci, "load_config", lambda: config)

    async def execute():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            return await ci.ci_pipeline(pr=7,
                preview_url="https://ux-guardian-demo-test-aranish-uk.vercel.app",
                output=tmp_path, client=client)

    url, failed = asyncio.run(execute())
    assert url.endswith("#comment") and not failed
    assert calls == [False, True, True]
    assert models == [config.llm_model, config.llm_model]
    assert "Pending diff-grounded" not in bodies[0]
    assert "Fix suggestion unavailable" in bodies[0]
    assert ("Overlay intercepts input." in bodies[0]) is not failure
    saved = Report.model_validate_json((tmp_path / "report.json").read_text("utf-8"))
    assert render(saved) == bodies[0]


def test_enrichment_timeout_is_thirty_seconds_and_nonblocking(monkeypatch):
    report = Report.model_validate_json(
        files("ux_guardian.fixtures").joinpath("m2_mobile_overlay.json").read_text()
    )
    wait_for = asyncio.wait_for

    async def short_wait(awaitable, *, timeout):
        assert timeout == 30
        return await wait_for(awaitable, timeout=0.001)

    class Llm:
        async def complete_json(self, *, system, prompt):
            await asyncio.sleep(1)
            raise AssertionError("Should be cancelled")

    monkeypatch.setattr(run.asyncio, "wait_for", short_wait)
    asyncio.run(enrich_findings(report, Config(include_search=False), load_journeys(), [], Llm()))
    assert report.findings[0].fix_suggestion == "Fix suggestion unavailable"


@pytest.mark.parametrize("external", [False, True])
def test_pipeline_search_only_for_external_evidence(monkeypatch, external):
    report = Report.model_validate_json(
        files("ux_guardian.fixtures").joinpath("m2_mobile_overlay.json").read_text()
    )
    for check in report.check_results:
        check.console_errors = []
        check.failed_requests = []
    report.check_results[0].console_errors = ["React invalid hook call"] if external else []
    searches = []

    class Search:
        async def search(self, query):
            searches.append(query)
            return []

    class Llm:
        async def complete_json(self, *, system, prompt):
            return {"root_cause": "Investigate.", "suggestion_markdown": "Review evidence.",
                    "patch": None, "confidence": "low", "sources": []}

    monkeypatch.setattr(run, "SearchClient", Search)
    asyncio.run(enrich_findings(report, Config(), load_journeys(), [], Llm()))
    assert len(searches) == int(external)

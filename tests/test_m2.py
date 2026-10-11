import asyncio
import json
from pathlib import Path

import httpx
import pytest
from PIL import Image
from playwright.async_api import async_playwright

from ux_guardian.agents.base import AgentRun
from ux_guardian.checks.models import CheckResult, FetchPage, FetchResult, SelectorResult
from ux_guardian.checks.playwright import inspect_selectors, screenshot_diff
from ux_guardian.config import Config, Environment, Viewport, load_journeys
from ux_guardian.judge.judge import Verdict, judge, judge_evidence
from ux_guardian.judge.severity import Severity, assign_severity
from ux_guardian.run import checks_report
from ux_guardian.tinyfish.fetch import compare_pages, fetch_precheck


def check(env: Environment, failed: bool = False, viewport: Viewport = "mobile") -> CheckResult:
    return CheckResult(
        journey_id="sign-in",
        env=env,
        viewport=viewport,
        url="https://demo.test/login",
        http_status=200,
        selectors=[
            SelectorResult(
                selector="button",
                present=True,
                visible=True,
                enabled=True,
                receives_events=not failed,
            )
        ],
    )


@pytest.mark.parametrize(
    ("preview_fail", "prod_fail", "expected"),
    [
        (True, False, Verdict.CONFIRMED),
        (True, True, Verdict.PREEXISTING),
        (False, False, Verdict.OK),
        (False, True, Verdict.IMPROVED),
    ],
)
def test_deterministic_only_mobile_truth_table(
    preview_fail: bool,
    prod_fail: bool,
    expected: Verdict,
) -> None:
    assert (
        judge_evidence(preview=check("preview", preview_fail), prod=check("prod", prod_fail))
        == expected
    )


@pytest.mark.parametrize("mode", ["missing", "hidden", "disabled", "overlay", "http", "console"])
def test_every_hard_signal_confirms_without_agent(mode: str) -> None:
    preview = check("preview")
    if mode == "http":
        preview.http_status = 404
    elif mode == "console":
        preview.console_errors = ["Journey cannot initialize"]
        preview.blocking_console_errors = list(preview.console_errors)
    else:
        preview.selectors[0] = SelectorResult(
            selector="button",
            present=mode != "missing",
            visible=mode != "hidden",
            enabled=mode != "disabled",
            receives_events=mode != "overlay",
        )
    assert judge_evidence(preview=preview, prod=check("prod")) == Verdict.CONFIRMED


@pytest.mark.parametrize(
    ("step", "retry", "expected"),
    [
        (4, 1, Verdict.CONFIRMED),
        (4, 4, Verdict.CONFIRMED),
        (4, 5, Verdict.CANDIDATE),
        (4, 0, Verdict.CANDIDATE),
        (None, 1, Verdict.CANDIDATE),
        (4, None, Verdict.CANDIDATE),
    ],
)
def test_agent_confirmation_boundaries(step: int | None, retry: int | None, expected: Verdict):
    assert (
        judge(preview_pass=False, prod_pass=True, failed_step=step, retry_failed_step=retry)
        == expected
    )


def test_agent_only_desktop_candidate_needs_retry() -> None:
    preview = check("preview", viewport="desktop")
    prod = check("prod", viewport="desktop")
    run = AgentRun(
        run_id="fixture",
        journey_id="sign-in",
        env="preview",
        viewport="desktop",
        status="COMPLETED",
        completed=False,
        blocked_at_step=3,
    )
    baseline = run.model_copy(
        update={"env": "prod", "completed": True, "success_criteria_met": True}
    )
    assert (
        judge_evidence(preview=preview, prod=prod, preview_agent=run, prod_agent=baseline)
        == Verdict.CANDIDATE
    )
    assert (
        judge_evidence(
            preview=preview,
            prod=prod,
            preview_agent=run,
            prod_agent=baseline,
            retry=run.model_copy(update={"attempt": 2}),
        )
        == Verdict.CONFIRMED
    )
    preview.selectors[0].receives_events = False
    assert (
        judge_evidence(preview=preview, prod=prod, preview_agent=run, prod_agent=baseline)
        == Verdict.CONFIRMED
    )


def test_noise_and_unknown_baseline_never_confirm() -> None:
    preview = check("preview")
    preview.console_errors = ["Nonblocking warning"]
    preview.failed_requests = ["analytics timed out"]
    preview.pixel_diff_count = 100000
    assert judge_evidence(preview=preview, prod=check("prod")) == Verdict.OK
    preview.selectors[0].receives_events = False
    prod = check("prod")
    prod.http_status = None
    prod.navigation_error = "timeout"
    assert judge_evidence(preview=preview, prod=prod) == Verdict.CANDIDATE


def test_preexisting_signal_cannot_confirm_agent_candidate() -> None:
    preview = check("preview", True)
    prod = check("prod", True)
    assert judge_evidence(preview=preview, prod=prod) == Verdict.PREEXISTING
    preview.console_errors = ["new noise"]
    preview.blocking_console_errors = ["new noise"]
    assert judge_evidence(preview=preview, prod=prod) == Verdict.PREEXISTING
    prod.console_errors = ["Nonblocking warning"]
    assert judge_evidence(preview=preview, prod=prod) == Verdict.PREEXISTING


@pytest.mark.parametrize(
    ("blocked", "http", "expected"),
    [
        (0, False, Severity.P2),
        (1, False, Severity.P1),
        (2, False, Severity.P0),
        (1, True, Severity.P0),
    ],
)
def test_hard_selector_severity_is_viewport_specific(blocked: int, http: bool, expected: Severity):
    assert (
        assign_severity(hard_error=http, blocked_viewports=blocked, total_viewports=2) == expected
    )


def test_fetch_flags_advisory_except_explicit_origin_status() -> None:
    journeys = load_journeys()[:1]
    pages = [
        FetchPage(
            journey_id="sign-in",
            env="prod",
            url="https://prod.test/login",
            text="Your account " + "rendered page " * 10,
            http_status=200,
        ),
        FetchPage(
            journey_id="sign-in", env="preview", url="https://preview.test/login", text="Short"
        ),
    ]
    flags = compare_pages(pages, journeys)
    assert {flag.signal for flag in flags} == {"near_empty", "missing_keywords"}
    assert not any(flag.hard for flag in flags)
    assert (
        judge_evidence(
            preview=check("preview"),
            prod=check("prod"),
            fetch=FetchResult(pages=pages, flags=flags),
        )
        == Verdict.OK
    )
    pages[1].error = "extraction failed"
    assert "fetch_error" in {flag.signal for flag in compare_pages(pages, journeys)}
    pages[1].http_status = 404
    flags = compare_pages(pages, journeys)
    assert any(flag.hard for flag in flags)
    assert (
        judge_evidence(
            preview=check("preview"),
            prod=check("prod"),
            fetch=FetchResult(pages=pages, flags=flags),
        )
        == Verdict.CONFIRMED
    )
    pages[0].error = "also failed"
    assert not compare_pages(pages, journeys)


def test_fetch_exact_batch_contract_and_redaction(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TINYFISH_API_KEY", "fixture-key")
    monkeypatch.setenv("TEST_PASSWORD", "fixture-secret")
    config = Config(production_url="https://prod.test", preview_url="https://preview.test")
    journeys = load_journeys()
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert str(request.url) == "https://api.fetch.tinyfish.ai"
        assert request.method == "POST"
        assert request.headers["X-API-Key"] == "fixture-key"
        body = json.loads(request.content)
        assert body["format"] == "markdown" and body["ttl"] == 0
        assert len(body["urls"]) == 6
        return httpx.Response(
            200,
            json={
                "results": [
                    {"url": url, "text": "fixture-secret " + "page text " * 20}
                    for url in reversed(body["urls"])
                ],
                "errors": [],
            },
        )

    result = asyncio.run(
        fetch_precheck(
            config=config,
            journeys=journeys,
            environments=["preview", "prod"],
            transport=httpx.MockTransport(handler),
        )
    )
    assert len(calls) == 1 and len(result.pages) == 6
    assert all("fixture-secret" not in p.text and "[REDACTED]" in p.text for p in result.pages)
    assert not result.service_error


@pytest.mark.parametrize("status", [401, 429, 500, 302])
def test_fetch_service_failure_is_not_site_failure(status: int, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("TINYFISH_API_KEY", "fixture-key")
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(status, headers={"Location": "https://foreign.test"})

    result = asyncio.run(
        fetch_precheck(
            config=Config(),
            journeys=load_journeys(),
            environments=["preview", "prod"],
            transport=httpx.MockTransport(handler),
        )
    )
    assert result.service_error and not result.flags
    assert len(calls) == 1


def test_report_aggregates_mobile_only_without_agent() -> None:
    journey = load_journeys()[0]
    checks = [
        check(env, failed=(env == "preview" and viewport == "mobile"), viewport=viewport)
        for env in ("preview", "prod")
        for viewport in ("desktop", "mobile")
    ]
    report = checks_report(config=Config(), journeys=[journey], checks=checks, fetch=FetchResult())
    assert not report.runs and len(report.findings) == 1
    assert report.findings[0].severity == Severity.P1
    checks[0].http_status = 404
    report = checks_report(config=Config(), journeys=[journey], checks=checks, fetch=FetchResult())
    assert report.findings[0].severity == Severity.P0


def test_fetch_origin_error_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TINYFISH_API_KEY", "fixture-key")
    config = Config(production_url="https://prod.test", preview_url="https://preview.test")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "results": [{"url": config.production_url + "/login", "text": "Normal page " * 10}],
                "errors": [
                    {"url": config.preview_url + "/login", "error": "page_not_found", "status": 404}
                ],
            },
        )

    result = asyncio.run(
        fetch_precheck(
            config=config,
            journeys=load_journeys()[:1],
            environments=["preview", "prod"],
            transport=httpx.MockTransport(handler),
        )
    )
    assert result.pages[0].http_status == 404
    assert result.pages[1].fetched and result.pages[1].http_status is None
    assert any(f.hard for f in result.flags)
    assert (
        judge_evidence(preview=check("preview"), prod=check("prod"), fetch=result)
        == Verdict.CONFIRMED
    )


def test_incomplete_or_failed_prod_check_is_not_passing_selector_baseline() -> None:
    prod = check("prod")
    prod.selectors = []
    assert judge_evidence(preview=check("preview", True), prod=prod) == Verdict.CANDIDATE
    prod.http_status = 404
    assert judge_evidence(preview=check("preview", True), prod=prod) == Verdict.PREEXISTING


@pytest.mark.parametrize(
    ("preview_pass", "prod_pass", "expected"),
    [
        (False, True, Verdict.CANDIDATE),
        (False, False, Verdict.PREEXISTING),
        (True, True, Verdict.OK),
        (True, False, Verdict.IMPROVED),
    ],
)
def test_agent_only_truth_table(preview_pass: bool, prod_pass: bool, expected: Verdict) -> None:
    preview = check("preview", viewport="desktop")
    prod = check("prod", viewport="desktop")
    run = AgentRun(
        run_id="fixture",
        env="preview",
        journey_id="sign-in",
        viewport="desktop",
        status="COMPLETED",
        completed=preview_pass,
        success_criteria_met=preview_pass,
    )
    baseline = run.model_copy(
        update={"env": "prod", "completed": prod_pass, "success_criteria_met": prod_pass}
    )
    assert (
        judge_evidence(preview=preview, prod=prod, preview_agent=run, prod_agent=baseline)
        == expected
    )


@pytest.mark.parametrize(
    ("viewports", "status", "expected"),
    [
        (["mobile"], 200, Severity.P1),
        (["desktop"], 200, Severity.P1),
        (["desktop", "mobile"], 200, Severity.P0),
        (["mobile"], 404, Severity.P0),
        (["desktop"], 500, Severity.P0),
        (["mobile"], 302, Severity.P1),
    ],
)
def test_report_severity_combinations(viewports: list[str], status: int, expected: Severity):
    checks = [
        check(env, failed=(env == "preview" and viewport in viewports), viewport=viewport)
        for env in ("preview", "prod")
        for viewport in ("desktop", "mobile")
    ]
    for item in checks:
        if item.env == "preview" and item.viewport in viewports:
            item.http_status = status
    report = checks_report(
        config=Config(), journeys=load_journeys()[:1], checks=checks, fetch=FetchResult()
    )
    assert len(report.findings) == 1 and report.findings[0].severity == expected


def test_pixel_diff_pads_different_sizes_and_never_verdict(tmp_path: Path) -> None:
    left, right, diff = (tmp_path / name for name in ("left.png", "right.png", "diff.png"))
    Image.new("RGBA", (10, 10), "red").save(left)
    Image.new("RGBA", (10, 12), "white").save(right)
    assert screenshot_diff(left, right, diff) > 0
    with Image.open(diff) as image:
        assert image.size == (10, 12)


def test_browser_overlay_is_visible_enabled_but_cannot_receive_input() -> None:
    async def exercise() -> None:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch()
            try:
                page = await browser.new_page()
                # Inline content only, no local server or external network.
                await page.set_content("""<button id="covered" onclick="window.clicked=true"
                    style="position:absolute;left:0;top:0;width:100px;height:100px">Submit</button>
                    <div style="position:absolute;left:0;top:0;width:100px;height:100px;
                    z-index:10"></div><button id="disabled" disabled>Disabled</button>
                    <button id="hidden" style="display:none">Hidden</button>
                    <button id="ok" style="position:absolute;left:200px;top:200px"
                    onclick="window.clicked=true">Okay</button>""")
                results = await inspect_selectors(
                    page, ["#covered", "#disabled", "#hidden", "#missing", "#ok"]
                )
                assert results[0].visible and results[0].enabled
                assert not results[0].receives_events
                assert [r.passed for r in results] == [False, False, False, False, True]
                assert not await page.evaluate("Boolean(window.clicked)")
            finally:
                await browser.close()

    asyncio.run(exercise())

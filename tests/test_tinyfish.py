import asyncio
import json
from pathlib import Path

import httpx
import pytest

from ux_guardian.agents.tinyfish import TinyFishAgent
from ux_guardian.config import Config, load_journeys


def test_mapping_redaction_and_screenshots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_EMAIL", "secret-email")
    monkeypatch.setenv("TEST_PASSWORD", "secret-password")
    calls = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.host == "images.example":
            assert "X-API-Key" not in request.headers
            return httpx.Response(200, content=b"png")
        if request.method == "POST":
            goal = json.loads(request.content)["goal"]
            assert goal.startswith("Never submit payment, never send messages, never delete data.")
            assert "secret-email" in goal
            return httpx.Response(200, json={"run_id": "test-run"})
        return httpx.Response(
            200,
            json={
                "status": "COMPLETED",
                "result": {
                    "completed": True,
                    "success_criteria_met": True,
                    "final_page_summary": "Your account secret-email",
                    "steps": [
                        {"n": 1, "action": "type secret-password", "observation": "secret-email"}
                    ],
                },
                "steps": [
                    {"action": "type secret-password", "screenshot": "https://images.example/1"}
                ],
            },
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            agent = TinyFishAgent(config=Config(), api_key="key", client=client, output=tmp_path)
            return await agent.run_journey(
                base_url=Config().production_url, journey=load_journeys()[0], viewport="desktop"
            )

    result = asyncio.run(run())
    assert result.passed
    assert result.cost_usd == 0.016
    assert Path(result.steps[0].screenshot_path).read_bytes() == b"png"
    assert "secret-" not in result.model_dump_json()
    assert "secret-" not in (tmp_path / "test-run" / "responses.json").read_text()


def test_budget_guard(tmp_path: Path) -> None:
    agent = TinyFishAgent(config=Config(budget_usd_per_run=0.1), api_key="key", output=tmp_path)
    with pytest.raises(ValueError, match="budget"):
        asyncio.run(
            agent.run_journey(
                base_url=Config().production_url, journey=load_journeys()[0], viewport="desktop"
            )
        )


@pytest.mark.parametrize("mode", ["failed", "cap", "timeout", "gated", "denied"])
def test_failure_caps_and_degradation(tmp_path: Path, mode: str) -> None:
    posts = []

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "agent.tinyfish.ai"
        assert request.headers.get("X-API-Key") == "key"
        assert "Authorization" not in request.headers
        if request.method == "POST":
            posts.append(str(request.url))
            if request.url.path.endswith("/cancel"):
                return httpx.Response(200, json={})
            if mode == "denied":
                return httpx.Response(403, text="account access denied")
            if mode == "gated" and len(posts) == 1:
                return httpx.Response(403, text="capture_config capability not enabled")
            return httpx.Response(200, json={"run_id": "test-run"})
        return httpx.Response(
            200,
            json={
                "status": "RUNNING" if mode in {"cap", "timeout"} else "COMPLETED",
                "result": {"completed": False, "success_criteria_met": True},
                "steps": [{"action": "blocked"}] * (25 if mode == "cap" else 1),
            },
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            agent = TinyFishAgent(
                config=Config(max_duration_seconds=1),
                api_key="key",
                client=client,
                output=tmp_path,
                poll_seconds=0.01,
                gated_options=True,
            )
            return await agent.run_journey(
                base_url=Config().production_url, journey=load_journeys()[1], viewport="desktop"
            )

    if mode == "denied":
        with pytest.raises(ValueError, match="403"):
            asyncio.run(run())
        assert len(posts) == 1
    else:
        result = asyncio.run(run())
        assert not result.passed
        if mode in {"cap", "timeout"}:
            assert posts[-1].endswith("/cancel")
            assert result.status == "CANCELLED"
        if mode == "gated":
            assert len(posts) == 2


@pytest.mark.parametrize("screenshot_status", [200, 401, 403, 404, 500, -1])
def test_screenshot_auth_and_nonfatal_errors(
    tmp_path: Path, screenshot_status: int, caplog: pytest.LogCaptureFixture
) -> None:
    calls = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.host, request.url.path))
        assert "Authorization" not in request.headers
        if request.url.host == "storage.example":
            assert "X-API-Key" not in request.headers
            if screenshot_status == -1:
                raise httpx.ConnectError("private signed URL", request=request)
            return httpx.Response(screenshot_status, content=b"png")
        assert request.url.host == "agent.tinyfish.ai"
        assert request.headers.get("X-API-Key") == "key"
        if request.url.path == "/v1/automation/run-async":
            return httpx.Response(200, json={"run_id": "test-run"})
        if request.url.path == "/v1/runs/test-run":
            assert request.url.params["screenshots"] == "url"
            return httpx.Response(
                200,
                json={
                    "status": "COMPLETED",
                    "result": {"completed": True, "success_criteria_met": True},
                    "steps": [
                        {
                            "action": "open",
                            "screenshot": "https://agent.tinyfish.ai/runs/test-run/steps/step-id/screenshot",
                        },
                        {
                            "action": "finish",
                            "screenshot": "https://storage.example/image?sig=private",
                        },
                    ],
                },
            )
        assert request.url.path == "/v1/runs/test-run/steps/step-id/screenshot"
        if screenshot_status == -1:
            raise httpx.ConnectError("private signed URL", request=request)
        return httpx.Response(screenshot_status, content=b"png")

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(respond), headers={"X-API-Key": "client-default"}
        ) as client:
            agent = TinyFishAgent(config=Config(), api_key="key", client=client, output=tmp_path)
            return await agent.run_journey(
                base_url=Config().production_url, journey=load_journeys()[1], viewport="desktop"
            )

    result = asyncio.run(run())
    assert result.passed
    assert len(calls) == 4
    assert not any(path.endswith("/cancel") for _, _, path in calls)
    assert all(bool(step.screenshot_path) == (screenshot_status == 200) for step in result.steps)
    if screenshot_status != 200:
        assert ("unavailable" if screenshot_status == -1 else str(screenshot_status)) in caplog.text
        assert "sig=private" not in caplog.text


def test_submit_401_stops_without_poll_or_cancel(tmp_path: Path) -> None:
    calls = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(401)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            agent = TinyFishAgent(config=Config(), api_key="key", client=client, output=tmp_path)
            await agent.run_journey(
                base_url=Config().production_url, journey=load_journeys()[1], viewport="desktop"
            )

    with pytest.raises(ValueError, match="submit.*401"):
        asyncio.run(run())
    assert len(calls) == 1


@pytest.mark.parametrize("option", ["mobile", "foreign", "steps"])
def test_rejects_invalid_live_requests(tmp_path: Path, option: str) -> None:
    agent = TinyFishAgent(config=Config(), api_key="key", output=tmp_path)
    journey = load_journeys()[1]
    if option == "steps":
        journey = journey.model_copy(update={"max_steps": 26})
    with pytest.raises(ValueError):
        asyncio.run(
            agent.run_journey(
                base_url="https://foreign.example"
                if option == "foreign"
                else Config().production_url,
                journey=journey,
                viewport="mobile" if option == "mobile" else "desktop",
            )
        )


def test_mobile_cli_refused_before_confirmation() -> None:
    from typer.testing import CliRunner

    from ux_guardian.cli import app

    result = CliRunner().invoke(
        app,
        [
            "live",
            "journey",
            "--journey",
            "sign-in",
            "--env",
            "prod",
            "--viewport",
            "mobile",
            "--yes",
        ],
    )
    assert result.exit_code != 0
    assert "viewport control" in result.output


def test_cli_displays_mocked_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from typer.testing import CliRunner

    from ux_guardian.agents.base import AgentRun, Step
    from ux_guardian.cli import app

    async def run(self, **kwargs):
        return AgentRun(
            run_id="mocked",
            env="prod",
            journey_id="sign-in",
            viewport="desktop",
            status="COMPLETED",
            completed=True,
            success_criteria_met=True,
            steps=[
                Step(
                    n=1,
                    action="Sign in",
                    observation="Your account",
                    screenshot_path=str(tmp_path / "step.jpg"),
                )
            ],
            cost_usd=0.016,
        )

    monkeypatch.setattr(TinyFishAgent, "run_journey", run)
    result = CliRunner().invoke(
        app, ["live", "journey", "--journey", "sign-in", "--env", "prod"], input="y\n"
    )
    assert result.exit_code == 0, result.output
    assert "PASS: sign-in (mocked)" in result.output
    assert "Screenshot:" in result.output
    assert "Actual cost: $0.016" in result.output


@pytest.mark.parametrize(
    "completed,criteria,status",
    [
        (True, True, "COMPLETED"),
        (False, True, "COMPLETED"),
        (True, False, "COMPLETED"),
        (True, True, "FAILED"),
    ],
)
def test_recorded_sign_in(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, completed: bool, criteria: bool, status: str
) -> None:
    fixture = json.loads(
        (Path("ux_guardian") / "fixtures" / "tinyfish_sign_in.json").read_text(encoding="utf-8")
    )
    fixture["status"] = status
    fixture["result"]["completed"] = completed
    fixture["result"]["success_criteria_met"] = criteria
    monkeypatch.setenv("TEST_EMAIL", "offline-email")
    monkeypatch.setenv("TEST_PASSWORD", "offline-password")

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "agent.tinyfish.ai"
        assert request.headers.get("X-API-Key") == "key"
        if request.url.path == "/v1/automation/run-async":
            return httpx.Response(200, json={"run_id": fixture["run_id"]})
        if request.url.path.endswith("/screenshot"):
            assert request.url.path.startswith("/v1/runs/")
            return httpx.Response(200, content=b"recorded-image-placeholder")
        return httpx.Response(200, json=fixture)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            agent = TinyFishAgent(config=Config(), api_key="key", client=client, output=tmp_path)
            return await agent.run_journey(
                base_url=Config().production_url, journey=load_journeys()[0], viewport="desktop"
            )

    result = asyncio.run(run())
    assert result.passed == (completed and criteria and status == "COMPLETED")
    assert result.run_id == "3dc7ff0c-1d92-451c-b6dc-dab71679e2dd"
    assert result.cost_usd == 0.112
    assert len(result.steps) == 7
    assert "Your account" in result.steps[4].observation
    assert len([s for s in result.steps if s.screenshot_path]) == 6


def test_adapter_queue_and_budget_reservations(tmp_path: Path) -> None:
    active = 0
    maximum = 0
    submitted = 0

    async def respond(request: httpx.Request) -> httpx.Response:
        nonlocal active, maximum, submitted
        if request.method == "POST":
            submitted += 1
            active += 1
            maximum = max(maximum, active)
            return httpx.Response(200, json={"run_id": f"run-{submitted}"})
        await asyncio.sleep(0.01)
        active -= 1
        return httpx.Response(
            200,
            json={
                "status": "COMPLETED",
                "num_of_steps": 25,
                "result": {"completed": True, "success_criteria_met": True},
            },
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            agent = TinyFishAgent(
                config=Config(concurrency=2, budget_usd_per_run=0.8),
                api_key="key",
                client=client,
                output=tmp_path,
            )
            results = await asyncio.gather(
                *[
                    agent.run_journey(
                        base_url=Config().production_url,
                        journey=load_journeys()[1],
                        viewport="desktop",
                    )
                    for _ in range(3)
                ],
                return_exceptions=True,
            )
            assert agent.reserved == 0
            return results

    results = asyncio.run(run())
    assert maximum == 2
    assert submitted == 2
    assert sum(isinstance(r, ValueError) for r in results) == 1

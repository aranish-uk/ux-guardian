import asyncio
import json
from importlib.resources import files
from pathlib import Path
from unittest.mock import AsyncMock

import httpx2 as httpx
import pytest
from openai import AsyncOpenAI
from pydantic import ValidationError
from typer.testing import CliRunner

from ux_guardian.cli import RecordedLlm, app
from ux_guardian.config import Config, load_journeys
from ux_guardian.diff.analyzer import (
    ChangedFile,
    Prediction,
    Predictions,
    analyze,
    glob_matches,
    normalize_diff,
    patch_context,
)
from ux_guardian.llm import OpenAiLlmClient
from ux_guardian.report.models import Report
from ux_guardian.report.render import render
from ux_guardian.run import replay_pipeline

FIXTURES = files("ux_guardian.fixtures")


def recorded(label: str):
    changed = normalize_diff(FIXTURES.joinpath(f"m3_demo_{label}.diff").read_text("utf-8"))
    records = json.loads(FIXTURES.joinpath("m3_llm.json").read_text("utf-8"))
    record = next(
        r
        for r in records.values()
        if r["branch"]
        == {
            "a": "demo/mobile-signin-overlay",
            "b": "demo/broken-cart-route",
            "c": "demo/copy-change",
        }[label]
    )
    return changed, Predictions.model_validate(record["response"])


@pytest.mark.parametrize(
    "label,expected",
    [
        ("a", {"sign-in", "search-cart", "checkout"}),
        ("b", {"search-cart", "checkout"}),
        ("c", set()),
    ],
)
def test_real_demo_selection_and_input_equivalence(label, expected):
    changed, response = recorded(label)
    api = FIXTURES.joinpath(f"m3_demo_{label}_files.json").read_text("utf-8")
    assert normalize_diff(api) == changed
    mocked = AsyncMock(return_value=response.model_dump())
    llm = RecordedLlm(response)
    llm.complete_json = mocked
    result = asyncio.run(analyze(changed, load_journeys(), llm, review_all=True))
    mocked.assert_awaited_once()
    assert {item.journey_id for item in result.affected} == expected
    if label == "c":
        assert result.outcome == "No customer-facing journeys affected"
    if label == "a":
        assert {item.source for item in result.affected} == {"shared"}


def test_authoritative_and_additive_only_unmatched_hunks():
    llm = RecordedLlm(
        Predictions(
            affected=[
                Prediction(journey_id="checkout", reason="Shared cart helper", confidence="medium")
            ],
            reasoning="Helper reaches checkout",
        )
    )
    mocked = AsyncMock(return_value=llm.response.model_dump())
    llm.complete_json = mocked
    result = asyncio.run(
        analyze(
            [
                ChangedFile(filename="demo-app/app/login/page.tsx", patch="owned login hunk"),
                ChangedFile(filename="demo-app/lib/cart.ts", patch="unmatched helper hunk"),
            ],
            load_journeys(),
            llm,
        )
    )
    assert {item.journey_id: item.source for item in result.affected} == {
        "sign-in": "glob",
        "checkout": "llm",
    }
    prompt = mocked.call_args.kwargs["prompt"]
    assert "unmatched helper hunk" in prompt
    assert "owned login hunk" not in prompt


def test_low_confidence_does_not_select_runs():
    result = asyncio.run(
        analyze(
            [ChangedFile(filename="marketing.tsx")],
            load_journeys(),
            RecordedLlm(
                Predictions(
                    affected=[
                        Prediction(
                            journey_id="search-cart",
                            reason="Speculative copy impact",
                            confidence="low",
                        )
                    ],
                    reasoning="Cosmetic only",
                )
            ),
        )
    )
    assert result.affected == []
    assert len(result.low_confidence) == 1
    assert result.outcome == "No customer-facing journeys affected"


@pytest.mark.parametrize(
    "response",
    [
        {
            "affected": [{"journey_id": "unknown", "reason": "x", "confidence": "high"}],
            "reasoning": "x",
        },
        {
            "affected": [{"journey_id": "sign-in", "reason": "x", "confidence": "certain"}],
            "reasoning": "x",
        },
        {"affected": [{"journey_id": "sign-in", "confidence": "high"}], "reasoning": "x"},
    ],
)
def test_invalid_llm_output_rejected(response):
    llm = AsyncMock()
    llm.complete_json.return_value = response
    with pytest.raises((ValueError, ValidationError)):
        asyncio.run(analyze([ChangedFile(filename="shared.tsx")], load_journeys(), llm))


@pytest.mark.parametrize(
    "filename,patch",
    [
        ("demo-app/app/layout.tsx", ""),
        ("app/globals.css", ""),
        ("middleware.ts", ""),
        (
            "demo-app/package.json",
            ' {\n   "dependencies": {\n-    "next": "16.3"\n+    "next": "16.4"\n   }',
        ),
        (
            "package.json",
            ' {\n   "dependencies": {\n-    "next": "workspace:*"\n'
            '+    "next": "file:../next"\n   }',
        ),
        ("package.json", ""),
        (
            "package.json",
            '@@ -20 +20 @@\n-  "helper": "workspace:*"\n+  "helper": "file:../helper"',
        ),
    ],
)
def test_shared_dependencies_authoritative(filename, patch):
    llm = AsyncMock()
    result = asyncio.run(
        analyze([ChangedFile(filename=filename, patch=patch)], load_journeys(), llm)
    )
    assert {item.journey_id for item in result.affected} == {j.id for j in load_journeys()}
    assert {item.source for item in result.affected} == {"shared"}
    llm.complete_json.assert_not_awaited()


@pytest.mark.parametrize(
    "patch",
    [
        ' {\n   "scripts": {\n-    "build": "next build"\n+    "build": "next build --debug"\n   }',
        '@@ -2 +2 @@\n-  "version": "1.0"\n+  "version": "2.0"',
    ],
)
def test_package_script_change_is_not_dependency_change(patch):
    result = asyncio.run(
        analyze(
            [
                ChangedFile(
                    filename="package.json",
                    patch=patch,
                )
            ],
            load_journeys(),
        )
    )
    assert result.affected == []
    assert result.pending_files == ["package.json"]


@pytest.mark.parametrize(
    "path,pattern,expected",
    [
        ("app/(auth)/login/page.tsx", "app/(auth)/**", True),
        ("app/login/page.tsx", "app/*/page.tsx", True),
        ("app/login/deep/page.tsx", "app/*/page.tsx", False),
        ("components/auth/button.tsx", "components/**/button.tsx", True),
        ("components/button.tsx", "components/**/button.tsx", True),
    ],
)
def test_glob_semantics(path, pattern, expected):
    assert glob_matches(path, pattern) == expected


def test_rename_old_owner_deleted_added_binary_and_plain_unified():
    renamed = normalize_diff(
        "diff --git a/app/login/a.tsx b/shared.tsx\n"
        "similarity index 100%\nrename from app/login/a.tsx\nrename to shared.tsx\n"
    )
    assert renamed[0].previous_filename == "app/login/a.tsx"
    result = asyncio.run(analyze(renamed, load_journeys()))
    assert result.affected[0].journey_id == "sign-in"
    plain = normalize_diff(
        "--- a/app/cart/page.tsx\n+++ /dev/null\n@@ -1 +0,0 @@\n-old\n"
        "--- /dev/null\n+++ b/app/bag/page.tsx\n@@ -0,0 +1 @@\n+new\n"
    )
    assert [f.status for f in plain] == ["removed", "added"]
    binary = normalize_diff("diff --git a/public/a.png b/public/a.png\nBinary files differ\n")
    assert binary[0].filename == "public/a.png"


def test_patch_budget_ui_first_redaction_and_no_llm_for_empty(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "secret-for-test")
    context = patch_context(
        [
            ChangedFile(filename="a.lock", patch="lock" * 1000),
            ChangedFile(filename="z.tsx", patch="@@ -1 +1 @@\n+secret-for-test\n" + "❤" * 1000),
        ],
        120,
    )
    assert len(context.encode("utf-8")) <= 120
    assert "z.tsx" in context and "a.lock" not in context
    assert "secret-for-test" not in context
    llm = AsyncMock()
    result = asyncio.run(analyze([], load_journeys(), llm))
    assert result.outcome == "No customer-facing journeys affected"
    llm.complete_json.assert_not_awaited()


def test_response_secrets_redacted(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "secret-for-test")
    result = asyncio.run(
        analyze(
            [ChangedFile(filename="helper.ts")],
            load_journeys(),
            RecordedLlm(
                Predictions(
                    affected=[
                        Prediction(
                            journey_id="checkout",
                            reason="secret-for-test",
                            confidence="high",
                        )
                    ],
                    reasoning="secret-for-test",
                )
            ),
        )
    )
    assert "secret-for-test" not in result.model_dump_json()


@pytest.mark.parametrize("label", ["a", "b", "c"])
def test_offline_cli_exact_diff_recording(label, monkeypatch):
    monkeypatch.setattr(
        "ux_guardian.cli.OpenAiLlmClient", lambda *a, **k: pytest.fail("SDK called")
    )
    path = Path(str(FIXTURES.joinpath(f"m3_demo_{label}.diff")))
    response = CliRunner().invoke(app, ["analyze", "--diff-file", str(path)])
    assert response.exit_code == 0, response.output
    assert (
        "No customer-facing journeys affected" if label == "c" else "Journeys affected"
    ) in response.output


def test_sdk_structured_output_and_configured_model_without_network():
    requests = []

    def handle(request: httpx.Request):
        requests.append(request)
        if request.url.path == "/v1/models":
            return httpx.Response(
                200,
                json={
                    "object": "list",
                    "data": [
                        {
                            "id": "configured-test-model",
                            "object": "model",
                            "created": 0,
                            "owned_by": "test",
                        }
                    ],
                },
            )
        body = json.loads(request.content)
        assert body["model"] == "configured-test-model"
        assert body["text"]["format"]["type"] == "json_schema"
        assert body["text"]["format"]["strict"] is True
        assert body["store"] is False
        return httpx.Response(
            200,
            json={
                "id": "resp_fixture",
                "object": "response",
                "created_at": 0,
                "model": "configured-test-model",
                "status": "completed",
                "output": [
                    {
                        "id": "msg_fixture",
                        "type": "message",
                        "role": "assistant",
                        "status": "completed",
                        "content": [
                            {
                                "type": "output_text",
                                "annotations": [],
                                "text": '{"affected": [], "reasoning": "Copy only"}',
                            }
                        ],
                    }
                ],
            },
        )

    async def execute():
        sdk = AsyncOpenAI(
            api_key="fake-test-key",
            max_retries=0,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle)),
        )
        client = OpenAiLlmClient(Config(llm_model="configured-test-model"), sdk)
        try:
            assert await client.list_models() == ["configured-test-model"]
            assert await client.complete_json(system="test", prompt="test") == {
                "affected": [],
                "reasoning": "Copy only",
            }
        finally:
            await client.close()

    asyncio.run(execute())
    assert len(requests) == 2


def test_sdk_error_sanitized_and_no_retry():
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(401, json={"error": {"message": "secret-sensitive-body"}})

    async def execute():
        sdk = AsyncOpenAI(
            api_key="fake-test-key",
            max_retries=0,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle)),
        )
        client = OpenAiLlmClient(Config(), sdk)
        try:
            with pytest.raises(ValueError, match="body omitted") as error:
                await client.complete_json(system="test", prompt="test")
            assert "secret-sensitive-body" not in str(error.value)
        finally:
            await client.close()

    asyncio.run(execute())
    assert len(requests) == 1


def test_broken_cart_recorded_p0(monkeypatch):
    def no_live(*args, **kwargs):
        pytest.fail("Replay attempted live acquisition")

    monkeypatch.setattr("ux_guardian.run.run_checks", no_live)
    monkeypatch.setattr("ux_guardian.run.fetch_precheck", no_live)
    template = Report.model_validate_json(
        FIXTURES.joinpath("m3_broken_cart.json").read_text("utf-8")
    )
    report = asyncio.run(replay_pipeline(pr=3, preview_url=template.preview_url, template=template))
    assert len(report.findings) == 1
    assert report.findings[0].severity == "P0"
    checks = [c for c in report.check_results if c.journey_id == "checkout"]
    assert all(c.http_status == 404 for c in checks if c.env == "preview")
    assert all(c.passed for c in checks if c.env == "prod")
    assert not report.runs and report.cost.total_usd == 0
    assert render(template) == (Path("tests") / "snapshots" / "m3_broken_cart.md").read_text(
        "utf-8"
    )


def test_unrecorded_diff_requires_review_and_stale_fixture_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "ux_guardian.cli.OpenAiLlmClient", lambda *a, **k: pytest.fail("SDK called")
    )
    diff = tmp_path / "new.diff"
    diff.write_text("--- a/helper.ts\n+++ b/helper.ts\n@@ -1 +1 @@\n-old\n+new\n", encoding="utf-8")
    runner = CliRunner()
    result = runner.invoke(app, ["analyze", "--diff-file", str(diff)])
    assert "LLM review required" in result.output
    assert "No customer-facing journeys affected" not in result.output
    stale = tmp_path / "stale.json"
    stale.write_text(json.dumps({"diff_sha256": "wrong", "response": {}}), encoding="utf-8")
    result = runner.invoke(app, ["analyze", "--diff-file", str(diff), "--llm-fixture", str(stale)])
    assert result.exit_code != 0
    assert "does not match" in result.output


def test_unsupported_provider_and_missing_key(monkeypatch):
    with pytest.raises(ValueError, match="Unsupported"):
        OpenAiLlmClient(Config(llm_provider="other"))
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    with pytest.raises(ValueError, match="LLM_API_KEY"):
        OpenAiLlmClient(Config())

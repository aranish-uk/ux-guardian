import asyncio
import json
import subprocess
from pathlib import Path

import httpx
import pytest

from ux_guardian.enrich.fix import (
    DiffHunk,
    FixContext,
    FixFinding,
    FixSuggestion,
    render_fix,
    suggest_fix,
    validate_patch,
)
from ux_guardian.enrich.llm import OpenAiFixClient
from ux_guardian.tinyfish.search import SearchClient, should_search

PATCH = "--- a/app.css\n+++ b/app.css\n@@ -1 +1 @@\n-old\n+new\n"


def context(problem: str = "Submit button covered by overlay") -> FixContext:
    return FixContext(
        finding=FixFinding(
            title="Covered sign in",
            severity="P1",
            journey="sign-in",
            viewport="mobile",
            failing_step="Click Sign in",
        ),
        observed_problem=problem,
        hunks=[DiffHunk(path="app.css", patch=PATCH)],
    )


def suggestion(patch: str | None = PATCH, confidence: str = "high") -> FixSuggestion:
    return FixSuggestion.model_validate(
        {
            "root_cause": "Overlay intercepts input.",
            "suggestion_markdown": "Remove pointer interception.",
            "patch": patch,
            "confidence": confidence,
            "sources": [],
        }
    )


class FakeLlm:
    def __init__(self, output: FixSuggestion) -> None:
        self.output = output
        self.calls = 0
        self.prompt = ""

    async def complete_json(self, *, system: str, prompt: str) -> dict[str, object]:
        assert "untrusted" in system
        self.calls += 1
        self.prompt = prompt
        return self.output.model_dump()


def test_render_single_hunk_snapshot() -> None:
    assert render_fix(suggestion()) == (
        "**Root-cause hypothesis:** Overlay intercepts input.\n\n"
        "Remove pointer interception.\n\nConfidence: high\n\n```suggestion\nnew\n```"
    )


@pytest.mark.parametrize(
    "patch",
    [
        PATCH + "--- a/b.ts\n+++ b/b.ts\n@@ -1 +1 @@\n-x\n+y\n",
        PATCH + "@@ -3 +3 @@\n-x\n+y\n",
        "--- a/app.css\n+++ b/new.css\n@@ -1 +1 @@\n-old\n+new\n",
    ],
)
def test_render_diff_variants(patch: str) -> None:
    assert "```diff\n" in render_fix(suggestion(patch))


def test_render_low_and_untrusted_fences() -> None:
    s = suggestion(confidence="low")
    s.suggestion_markdown += "\n```diff\nunsafe\n```\n"
    rendered = render_fix(s)
    assert "**Hypothesis:**" in rendered
    assert "```" not in rendered
    assert "unsafe" not in rendered


def test_render_context_and_deletion_replacement() -> None:
    patch = "--- a/app.css\n+++ b/app.css\n@@ -1,3 +1,2 @@\n before\n-old\n after\n"
    assert "```suggestion\nbefore\nafter\n```" in render_fix(suggestion(patch))
    assert "```suggestion\n\n```" in render_fix(
        suggestion("--- a/app.css\n+++ b/app.css\n@@ -1 +0,0 @@\n-old\n")
    )
    assert "```suggestion\nnew\n```" in render_fix(
        suggestion("--- /dev/null\n+++ b/app.css\n@@ -0,0 +1 @@\n+new\n")
    )
    assert "```suggestion\n\n```" in render_fix(
        suggestion("--- a/app.css\n+++ /dev/null\n@@ -1 +0,0 @@\n-old\n")
    )


@pytest.mark.parametrize(
    "patch,allowed",
    [
        (PATCH, True),
        (PATCH.replace("app.css", "foreign.css"), False),
        (PATCH + PATCH.replace("app.css", "foreign.css"), False),
        (PATCH.replace("+++ b/app.css", "+++ b/foreign.css"), False),
        (PATCH.replace("app.css", "../app.css"), False),
        (PATCH.replace("app.css", ".git/config"), False),
        (PATCH.replace("@@ -1 +1 @@", "@@ -1,9 +1 @@"), False),
        ("diff --git a/app.css b/app.css\nGIT binary patch\n", False),
        ("diff --git a/app.css b/new.css\nrename from app.css\nrename to new.css\n", False),
        ("not a patch", False),
        ("diff --git a/foreign.css b/foreign.css\n" + PATCH, False),
        ("diff --git a/app.css b/app.css\nnew file mode 120000\n" + PATCH, False),
    ],
)
def test_patch_file_gate(patch: str, allowed: bool) -> None:
    llm = FakeLlm(suggestion(patch))
    result = asyncio.run(suggest_fix(context(), llm))
    assert (result.patch is not None) == allowed
    assert llm.calls == 1


def test_low_patch_gate_and_citation_gate() -> None:
    s = suggestion(confidence="low")
    s.sources = ["https://invented.example/docs"]
    result = asyncio.run(suggest_fix(context(), FakeLlm(s)))
    assert result.patch is None
    assert result.sources == []


def test_validate_patch_does_not_mutate(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True)
    file = tmp_path / "app.css"
    file.write_text("old\n", encoding="utf-8")
    assert validate_patch(PATCH, tmp_path)
    assert not validate_patch(PATCH.replace("-old", "-missing"), tmp_path)
    assert not validate_patch("garbage", tmp_path)
    assert not validate_patch(PATCH, tmp_path / "absent")
    assert file.read_text(encoding="utf-8") == "old\n"
    assert subprocess.check_output(["git", "diff", "--cached"], cwd=tmp_path) == b""


@pytest.mark.parametrize(
    "problem,expected",
    [
        ("Submit covered by overlay", False),
        ("GET /cart 404", False),
        ("TypeError: Cannot read properties of undefined", False),
        ("Network request failed", False),
        ("next step is reactive", False),
        ("React invalid hook call", True),
        ("Next.js hydration failed", True),
        ("ChunkLoadError loading chunk", True),
        ("CORS blocked external API", True),
        ("net::ERR_CERT_AUTHORITY_INVALID", True),
        ("axios request failed", True),
        ("third-party package error", True),
        ("Cannot find module '@vendor/widget'", True),
        ("Cannot find module './local'", False),
    ],
)
def test_search_heuristics(problem: str, expected: bool) -> None:
    assert should_search(context(problem)) == expected


def test_search_hunk_and_console_heuristics() -> None:
    ctx = context()
    ctx.console_errors = ["React hydration mismatch"]
    assert should_search(ctx)
    ctx.console_errors = []
    ctx.hunks = [DiffHunk(path="widget.ts", patch="+import x from '@vendor/widget';")]
    assert should_search(ctx)


def test_cache_auth_and_two_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TINYFISH_API_KEY", "test-secret")
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert request.method == "GET"
        assert request.url.host == "api.search.tinyfish.ai"
        assert request.headers["X-API-Key"] == "test-secret"
        assert request.url.params["query"] == "React docs"
        return httpx.Response(
            200,
            json={
                "results": [
                    {"url": "javascript:alert(1)"},
                    {"url": "https://docs.example/one"},
                    {"url": "https://docs.example/one"},
                    {"url": "https://docs.example/two"},
                    {"url": "https://docs.example/three"},
                ]
            },
        )

    async def run() -> None:
        client = SearchClient(transport=httpx.MockTransport(handler))
        first, second = await asyncio.gather(
            client.search(" React  docs "), client.search("React docs")
        )
        assert [r.url for r in first] == ["https://docs.example/one", "https://docs.example/two"]
        first[0].title = "mutation"
        assert second[0].title == ""
        assert (await client.search("React docs"))[0].title == ""

    asyncio.run(run())
    assert len(calls) == 1


def test_rolling_rate_limiter_and_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TINYFISH_API_KEY", "test-secret")
    now = [0.0]
    times: list[float] = []
    sleeps: list[float] = []

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        now[0] += seconds

    def handler(request: httpx.Request) -> httpx.Response:
        times.append(now[0])
        return httpx.Response(200, json={"results": []})

    async def run() -> None:
        client = SearchClient(
            transport=httpx.MockTransport(handler), clock=lambda: now[0], sleep=sleep
        )
        await asyncio.gather(*(client.search(f"query {i}") for i in range(61)))
        await client.search("query 0")

    asyncio.run(run())
    assert times == [0.0] * 30 + [60.0] * 30 + [120.0]
    assert sleeps == [60.0, 60.0]


@pytest.mark.parametrize("status", [301, 401, 429, 500])
def test_search_failures_cached_no_redirect(monkeypatch: pytest.MonkeyPatch, status: int) -> None:
    monkeypatch.setenv("TINYFISH_API_KEY", "test-secret")
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(status, headers={"Location": "https://foreign.example"})

    async def run() -> None:
        client = SearchClient(transport=httpx.MockTransport(handler))
        assert await client.search("React docs") == []
        assert await client.search("React docs") == []

    asyncio.run(run())
    assert len(calls) == 1


def test_search_missing_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TINYFISH_API_KEY", raising=False)

    def handler(request: httpx.Request) -> httpx.Response:
        pytest.fail("Missing key must not make a request")

    assert asyncio.run(SearchClient(transport=httpx.MockTransport(handler)).search("React")) == []


def test_grounding_and_redaction(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TINYFISH_API_KEY", "test-secret")
    monkeypatch.setenv("TEST_PASSWORD", "private-password")

    def handler(request: httpx.Request) -> httpx.Response:
        assert "private-password" not in str(request.url)
        return httpx.Response(200, json={"results": [{"url": "https://react.dev/errors"}]})

    ctx = context("React error private-password")
    s = suggestion()
    s.sources = ["https://fake.example", "https://react.dev/errors"]
    llm = FakeLlm(s)
    result = asyncio.run(
        suggest_fix(ctx, llm, SearchClient(transport=httpx.MockTransport(handler)))
    )
    assert result.sources == ["https://react.dev/errors"]
    assert "private-password" not in llm.prompt


def test_obvious_failure_skips_search() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        pytest.fail("App overlay does not need docs")

    result = asyncio.run(
        suggest_fix(
            context(), FakeLlm(suggestion()), SearchClient(transport=httpx.MockTransport(handler))
        )
    )
    assert result.patch == PATCH


def test_openai_structured_output(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_API_KEY", "llm-secret")
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert request.url == "https://api.openai.com/v1/chat/completions"
        assert request.headers["Authorization"] == "Bearer llm-secret"
        payload = json.loads(request.content)
        schema = payload["response_format"]["json_schema"]
        assert schema["strict"] is True
        assert schema["schema"]["additionalProperties"] is False
        assert set(schema["schema"]["required"]) == set(FixSuggestion.model_fields)
        assert "llm-secret" not in json.dumps(payload)
        return httpx.Response(
            200, json={"choices": [{"message": {"content": suggestion().model_dump_json()}}]}
        )

    client = OpenAiFixClient(transport=httpx.MockTransport(handler))
    result = asyncio.run(suggest_fix(context("llm-secret"), client))
    assert result.patch == PATCH
    assert len(calls) == 1


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(401),
        httpx.Response(200, json={"choices": []}),
        httpx.Response(200, json={"choices": [{"message": {"refusal": "no"}}]}),
    ],
)
def test_openai_failure_becomes_hypothesis(
    monkeypatch: pytest.MonkeyPatch, response: httpx.Response
) -> None:
    monkeypatch.setenv("LLM_API_KEY", "llm-secret")
    client = OpenAiFixClient(transport=httpx.MockTransport(lambda request: response))
    result = asyncio.run(suggest_fix(context(), client))
    assert result.confidence == "low"
    assert result.patch is None


@pytest.mark.parametrize("confidence", ["high", "medium", "low"])
def test_confidence_gate(confidence: str) -> None:
    result = asyncio.run(suggest_fix(context(), FakeLlm(suggestion(confidence=confidence))))
    assert (result.patch is None) == (confidence == "low")


def test_unknown_package_dependency() -> None:
    ctx = context()
    ctx.hunks = [DiffHunk(path="package.json", patch='+  "@acme/widget": "^2.0.0"')]
    assert should_search(ctx)


def test_unterminated_fence_cannot_bypass_gate() -> None:
    s = suggestion(confidence="low")
    s.suggestion_markdown = "Investigate.\n```diff\nunsafe"
    s.root_cause = "Unknown.\n~~~diff\nunsafe"
    rendered = render_fix(s)
    assert "unsafe" not in rendered
    assert "```" not in rendered and "~~~" not in rendered


@pytest.mark.parametrize("name", ["mobile_overlay", "broken_cart"])
def test_live_fixture_replay_without_network(name: str, tmp_path: Path) -> None:
    fixture = json.loads(
        (Path(__file__).parents[1] / "ux_guardian" / "fixtures" / f"m5_{name}_fix.json").read_text(
            encoding="utf-8"
        )
    )
    ctx = FixContext.model_validate(fixture["context"])
    s = FixSuggestion.model_validate(fixture["suggestion"])
    llm = FakeLlm(s)
    result = asyncio.run(suggest_fix(ctx, llm))
    assert result == s
    assert render_fix(result) == fixture["rendered"]
    assert fixture["provenance"]["patch_applies"] is True
    assert result.patch is not None
    # Reconstruct just the preview fragments needed by these recorded patches.
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True)
    for hunk in ctx.hunks:
        if "+++ /dev/null" in hunk.patch:
            continue
        lines = hunk.patch.splitlines()
        start = next(i for i, line in enumerate(lines) if line.startswith("@@ "))
        content = (
            "\n".join(line[1:] for line in lines[start + 1 :] if line.startswith(("+", " "))) + "\n"
        )
        dest = tmp_path / Path(hunk.path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")
    assert validate_patch(result.patch, tmp_path)

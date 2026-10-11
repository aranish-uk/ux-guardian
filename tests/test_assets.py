import asyncio
import base64
import json
from importlib.resources import files
from pathlib import Path

import httpx
import pytest

from ux_guardian.github.pr import GitHubPr
from ux_guardian.report.models import Report
from ux_guardian.report.render import render


def evidence(tmp_path):
    report = Report.model_validate_json(files("ux_guardian.fixtures").joinpath(
        "report.json"
    ).read_text(encoding="utf-8"))
    report.pr = 42
    shot = tmp_path / "screenshots" / "preview.png"
    shot.parent.mkdir()
    shot.write_bytes(b"png-evidence")
    report.findings[0].preview_screenshot = str(shot)
    report.findings[0].prod_screenshot = ""
    report.runs = report.runs[:1]
    report.runs[0].run_id = "abcdefgh-final"
    for step in report.runs[0].steps:
        path = tmp_path / f"step-{step.n}.jpg"
        path.write_bytes(f"step-{step.n}".encode())
        step.screenshot_path = str(path)
    report.artifact_url = "https://github.com/o/r/actions/runs/123#artifacts"
    return report


@pytest.mark.parametrize("existing", [False, True])
def test_upload_sequence_and_inline_urls(tmp_path, existing):
    from ux_guardian.report.assets import upload_evidence

    report = evidence(tmp_path)
    requests = []

    def handle(request):
        assert request.headers["Authorization"] == "Bearer fixture-token"
        path = request.url.path.removeprefix("/repos/o/r")
        body = json.loads(request.content) if request.content else None
        requests.append((request.method, path, body))
        if path == "/git/ref/heads/ux-guardian-assets":
            return httpx.Response(200, json={"object": {"sha": "old"}}) if existing else (
                httpx.Response(404)
            )
        if path == "/git/commits/old":
            return httpx.Response(200, json={"tree": {"sha": "old-tree"}})
        if path == "/git/blobs":
            assert body is not None
            assert body["encoding"] == "base64"
            assert base64.b64decode(body["content"]) in (
                b"png-evidence", f"step-{report.runs[0].steps[-1].n}".encode()
            )
            return httpx.Response(201, json={"sha": f"blob-{len(requests)}"})
        return httpx.Response(201, json={"sha": "new"})

    async def execute():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            return await upload_evidence(report, GitHubPr("o/r", "fixture-token", client),
                                         run_id="123", output=tmp_path)

    urls = asyncio.run(execute())
    assert len(urls) == 2
    assert all(url.startswith("https://raw.githubusercontent.com/o/r/ux-guardian-assets/"
                             "pr-42/run-123/") for url in urls.values())
    mutations = [(method, path) for method, path, _ in requests if method != "GET"]
    assert mutations == [("POST", "/git/blobs")] * 2 + [
        ("POST", "/git/trees"), ("POST", "/git/commits"),
        ("PATCH", "/git/refs/heads/ux-guardian-assets") if existing else ("POST", "/git/refs")
    ]
    tree = next(body for _, path, body in requests if path == "/git/trees")
    commit = next(body for _, path, body in requests if path == "/git/commits")
    assert commit["parents"] == (["old"] if existing else [])
    assert tree.get("base_tree") == ("old-tree" if existing else None)
    assert {item["path"] for item in tree["tree"]} == {
        "pr-42/run-123/shots/preview.png", "pr-42/run-123/agent/abcdefgh-final.jpg"
    }
    report.asset_urls = urls
    report.findings[0].replay_url = "https://dead-streaming.example.invalid"
    report.runs[0].replay_url = "https://dead-streaming.example.invalid"
    body = render(report)
    assert '<img width="260"' in body and '<img width="220"' in body
    assert "TinyFish replay" not in body
    assert "TinyFish agent journeys (desktop)" in body
    assert "abcdefgh" in body and "Full evidence (zip)" in body
    assert "streaming" not in body
    assert render(Report.model_validate_json(report.model_dump_json())) == body
    assert body == (Path("tests") / "snapshots" / "hosted_report.md").read_text("utf-8")


def test_missing_and_outside_output_screenshots_never_uploaded(tmp_path, caplog):
    from ux_guardian.report.assets import upload_evidence

    report = evidence(tmp_path)
    report.findings[0].preview_screenshot = str(tmp_path / "missing.png")
    outside = tmp_path.parent / "outside.png"
    outside.write_bytes(b"private-evidence")
    report.runs[0].steps[-1].screenshot_path = str(outside)

    async def execute():
        def handle(request):
            pytest.fail("Missing or outside screenshots must not cause any API calls")

        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            return await upload_evidence(report, GitHubPr("o/r", "fixture-token", client),
                                         run_id="123", output=tmp_path)

    assert asyncio.run(execute()) == {}
    assert "unavailable" in caplog.text


@pytest.mark.parametrize("step_index", [0, -1])
def test_finding_agent_screenshot_does_not_publish_intermediate_steps(tmp_path, step_index):
    from ux_guardian.report.assets import upload_evidence

    report = evidence(tmp_path)
    report.findings[0].preview_screenshot = report.runs[0].steps[step_index].screenshot_path
    trees = []

    def handle(request):
        if "/git/ref/" in request.url.path:
            return httpx.Response(404)
        if request.url.path.endswith("/trees"):
            trees.append(json.loads(request.content))
        return httpx.Response(201, json={"sha": "fixture"})

    async def execute():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            return await upload_evidence(report, GitHubPr("o/r", "fixture-token", client),
                                         run_id="123", output=tmp_path)

    urls = asyncio.run(execute())
    assert len(urls) == 1
    assert [entry["path"] for entry in trees[0]["tree"]] == [
        "pr-42/run-123/agent/abcdefgh-final.jpg"
    ]


@pytest.mark.parametrize("failure", ["ref", "blob", "tree", "commit", "update", "transport"])
def test_upload_failure_preserves_artifact_fallback(tmp_path, caplog, failure):
    from ux_guardian.report.assets import upload_evidence

    report = evidence(tmp_path)

    def handle(request):
        path = request.url.path
        if failure == "transport":
            raise httpx.ConnectError("secret-url-and-token", request=request)
        stage = ("ref" if "/git/ref/" in path else "blob" if path.endswith("/blobs") else
                 "tree" if path.endswith("/trees") else
                 "commit" if path.endswith("/commits") else "update")
        if stage == failure:
            return httpx.Response(403, text="sensitive-response")
        if stage == "ref":
            return httpx.Response(404)
        return httpx.Response(201, json={"sha": "new"})

    async def execute():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            return await upload_evidence(report, GitHubPr("o/r", "fixture-token", client),
                                         run_id="123", output=tmp_path)

    assert asyncio.run(execute()) == {}
    assert "upload" in caplog.text.lower()
    assert "sensitive-response" not in caplog.text and "secret-url-and-token" not in caplog.text
    body = render(report)
    assert report.artifact_url in body
    assert "raw.githubusercontent.com" not in body
    assert '<img width=' not in body
    assert "TinyFish replay" not in body

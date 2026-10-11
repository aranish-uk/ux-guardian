import asyncio
import json
import subprocess

import httpx
import pytest
import yaml

from ux_guardian.agents.tinyfish import TinyFishAgent
from ux_guardian.config import Config, load_journeys
from ux_guardian.github.pr import GitHubPr


@pytest.mark.parametrize("case", [
    "preview", "fallback", "closed", "fork", "manual", "no-pr", "no-url"
])
def test_deployment_resolution_without_network(case):
    from pathlib import Path

    workflow = yaml.load(
        (Path(".github") / "workflows" / "ux-guardian.yml").read_text(), Loader=yaml.BaseLoader
    )
    assert "deployment_status" in workflow["on"]
    resolver = workflow["jobs"]["resolve"]
    assert "deployment_status.state == 'success'" in resolver["if"]
    assert "contains(" in resolver["if"] and "'Preview'" in resolver["if"]
    guardian = workflow["jobs"]["guardian"]
    assert guardian["concurrency"] == {
        "group": "ux-guardian-pr-${{ needs.resolve.outputs.pr_number }}",
        "cancel-in-progress": "true",
    }
    script = resolver["steps"][0]["with"]["script"]
    context = {
        "eventName": "workflow_dispatch" if case == "manual" else "deployment_status",
        "repo": {"owner": "o", "repo": "r"},
        "payload": {
            "deployment": {"sha": "abc"},
            "deployment_status": {
                "environment_url": "" if case == "fallback" else "https://preview.test",
                "target_url": "https://fallback.test",
            },
            "inputs": {"pr_number": "9", "preview_url": "https://manual.test",
                       "agent_runs": "false"},
        },
    }
    pulls = [{"number": 7, "state": "closed" if case == "closed" else "open",
              "head": {"repo": {"full_name": "fork/r" if case == "fork" else "o/r"}}}]
    if case == "no-pr":
        pulls = []
    if case == "no-url":
        context["payload"]["deployment_status"] = {}
    harness = """
    const outputs = {}, logs = [];
    const core = {setOutput: (k,v) => outputs[k] = String(v), info: v => logs.push(v)};
    const github = {rest: {repos: {listPullRequestsAssociatedWithCommit: 'commits/pulls'}},
      paginate: async (endpoint, args) => {
        if (endpoint !== 'commits/pulls' || args.commit_sha !== 'abc') throw Error('Wrong API');
        return pulls;
      }};
    (async () => { SCRIPT })().then(() => console.log(JSON.stringify({outputs, logs})));
    """.replace("SCRIPT", script)
    code = f"const context = {json.dumps(context)}, pulls = {json.dumps(pulls)};\n" + harness
    result = subprocess.run(["node", "-e", code], check=True, capture_output=True, text=True)
    resolved = json.loads(result.stdout)
    if case in {"closed", "fork", "no-pr", "no-url"}:
        assert "should_run" not in resolved["outputs"]
        assert "Skipping UX Guardian" in resolved["logs"][0]
    else:
        outputs = resolved["outputs"]
        assert outputs["should_run"] == "true"
        assert outputs["pr_number"] == ("9" if case == "manual" else "7")
        expected_url = {"manual": "https://manual.test", "fallback": "https://fallback.test"}
        assert outputs["preview_url"] == expected_url.get(case, "https://preview.test")
        assert outputs["agent_runs"] == ("false" if case == "manual" else "true")


def test_missing_patch_rename_uses_local_three_dot_diff(tmp_path):
    def git(*args):
        return subprocess.run(
            ["git", *args], cwd=tmp_path, check=True, capture_output=True, text=True
        ).stdout.strip()

    git("init")
    git("config", "user.name", "Fixture")
    git("config", "user.email", "fixture@example.test")
    (tmp_path / "old.ts").write_text("old\n", encoding="utf-8")
    git("add", ".")
    git("commit", "-m", "base")
    base = git("rev-parse", "HEAD")
    git("mv", "old.ts", "new.ts")
    (tmp_path / "new.ts").write_text("new\n", encoding="utf-8")
    git("add", ".")
    git("commit", "-m", "rename")
    head = git("rev-parse", "HEAD")

    async def execute():
        async with httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=[{
                "filename": "new.ts", "previous_filename": "old.ts", "status": "renamed"
            }])
        )) as client:
            return await GitHubPr("o/r", "fixture", client).changed_files(
                1, base_sha=base, head_sha=head, repo_dir=tmp_path
            )

    rows = asyncio.run(execute())
    assert rows[0]["previous_filename"] == "old.ts"
    assert "-old" in rows[0]["patch"] and "+new" in rows[0]["patch"]


@pytest.mark.parametrize("env", ["preview", "prod"])
def test_run_artifact_persists_actual_environment(tmp_path, monkeypatch, env):
    monkeypatch.setenv("TEST_EMAIL", "fixture@example.test")
    monkeypatch.setenv("TEST_PASSWORD", "fixture-password")
    config = Config(preview_url="https://preview.test", production_url="https://prod.test")
    url = config.preview_url if env == "preview" else config.production_url

    def respond(request):
        if request.method == "POST":
            return httpx.Response(200, json={"run_id": "fixture"})
        return httpx.Response(200, json={
            "status": "COMPLETED", "result": {"completed": True, "steps": []}
        })

    async def execute():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            agent = TinyFishAgent(
                config=config, api_key="fixture", client=client, output=tmp_path,
                allowed_urls=[config.preview_url, config.production_url],
            )
            return await agent.run_journey(
                base_url=url, journey=load_journeys()[0], viewport="desktop"
            )

    run = asyncio.run(execute())
    assert run.env == env
    assert json.loads((tmp_path / "fixture" / "run.json").read_text())["env"] == env

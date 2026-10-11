"""Publish downloaded screenshots to the dedicated orphan evidence branch."""

import base64
import logging
import re
from pathlib import Path
from typing import Any
from urllib.parse import quote

from ux_guardian.github.pr import GitHubPr
from ux_guardian.report.models import Report

BRANCH = "ux-guardian-assets"
logger = logging.getLogger(__name__)


async def upload_evidence(
    report: Report, github: GitHubPr, *, run_id: str, output: Path,
) -> dict[str, str]:
    """Return local-path → durable-URL mappings only after the ref is published.

    Missing files and API errors never prevent reporting. No response bodies,
    exception messages, credentials, or signed screenshot URLs are logged.
    """
    try:
        if not re.fullmatch(r"[0-9]+", run_id):
            raise ValueError("Invalid GitHub run ID")
        root = output.resolve()
        prefix = f"pr-{report.pr}/run-{run_id}"
        evidence: dict[str, tuple[str, bytes]] = {}

        def add(source: str, destination: str | None = None) -> None:
            if not source or source in evidence:
                return
            path = Path(source).resolve()
            if not path.is_relative_to(root) or not path.is_file():
                logger.warning("Evidence screenshot unavailable; retaining artifact fallback")
                return
            relative = path.relative_to(root)
            if relative.parts[0] == "screenshots":
                relative = Path(*relative.parts[1:])
            target = destination or "shots/" + relative.as_posix()
            evidence[source] = (f"{prefix}/{target}", path.read_bytes())

        agent_sources = {step.screenshot_path for run in report.runs for step in run.steps}
        for run in report.runs:
            if not re.fullmatch(r"[A-Za-z0-9_-]+", run.run_id):
                raise ValueError("Invalid Agent run ID")
            if run.steps:
                add(run.steps[-1].screenshot_path, f"agent/{run.run_id}.jpg")
        for check in report.check_results:
            add(check.screenshot_path)
        for finding in report.findings:
            for source in (finding.preview_screenshot, finding.prod_screenshot):
                if source not in agent_sources:
                    add(source)
        if not evidence:
            return {}

        response = await github.client.get(
            github.root + f"/git/ref/heads/{BRANCH}", headers=github.headers
        )
        parent = None
        base_tree = None
        if response.status_code != 404:
            if response.is_error:
                raise ValueError("Cannot read assets ref")
            parent = response.json()["object"]["sha"]
            commit = await github.request("GET", f"/git/commits/{parent}")
            base_tree = commit["tree"]["sha"]
        entries = []
        for target, content in evidence.values():
            blob = await github.request("POST", "/git/blobs", json={
                "content": base64.b64encode(content).decode("ascii"), "encoding": "base64",
            })
            entries.append({"path": target, "mode": "100644", "type": "blob",
                            "sha": blob["sha"]})
        tree_body: dict[str, Any] = {"tree": entries}
        if base_tree:
            tree_body["base_tree"] = base_tree
        tree = await github.request("POST", "/git/trees", json=tree_body)
        commit = await github.request("POST", "/git/commits", json={
            "message": f"Evidence for PR #{report.pr}, run {run_id}",
            "tree": tree["sha"], "parents": [parent] if parent else [],
        })
        if parent:
            await github.request("PATCH", f"/git/refs/heads/{BRANCH}", json={
                "sha": commit["sha"], "force": False,
            })
        else:
            await github.request("POST", "/git/refs", json={
                "ref": f"refs/heads/{BRANCH}", "sha": commit["sha"],
            })
        return {
            source: f"https://raw.githubusercontent.com/{github.repository}/{BRANCH}/"
                    + quote(target, safe="/")
            for source, (target, _) in evidence.items()
        }
    except Exception as error:
        logger.warning("Evidence upload failed (%s); retaining artifact links",
                       type(error).__name__)
        return {}

"""Small GitHub REST client; never checks out or executes PR code."""

import re
from typing import Any

import httpx

MARKER = "<!-- ux-guardian -->"


class GitHubPr:
    def __init__(self, repository: str, token: str, client: httpx.AsyncClient) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
            raise ValueError("GITHUB_REPOSITORY must be owner/repo")
        if not token:
            raise ValueError("GITHUB_TOKEN is required")
        self.repository = repository
        self.client = client
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        self.root = f"https://api.github.com/repos/{repository}"

    async def request(self, method: str, path: str, **kwargs: Any) -> Any:
        response = await self.client.request(
            method, self.root + path, headers=self.headers, **kwargs
        )
        if response.is_error:
            raise ValueError(f"GitHub API HTTP {response.status_code}; response body omitted")
        return response.json()

    async def pages(self, path: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        page = 1
        while True:
            batch = await self.request("GET", path, params={"per_page": 100, "page": page})
            rows.extend(batch)
            if len(batch) < 100:
                return rows
            page += 1

    async def metadata(self, pr: int) -> dict[str, Any]:
        data = await self.request("GET", f"/pulls/{pr}")
        if data["head"]["repo"] is None or (
            data["head"]["repo"]["full_name"].lower() != self.repository.lower()
        ):
            raise ValueError("Fork PRs are not supported; no tests or comment posted")
        return data

    async def changed_files(self, pr: int) -> list[dict[str, Any]]:
        return await self.pages(f"/pulls/{pr}/files")

    async def upsert_comment(self, pr: int, body: str) -> str:
        if not body.startswith(MARKER):
            raise ValueError("Report must begin with the UX Guardian marker")
        comments = await self.pages(f"/issues/{pr}/comments")
        existing = next(
            (
                comment
                for comment in comments
                if (comment.get("body") or "").startswith(MARKER)
            ),
            None,
        )
        path = f"/issues/comments/{existing['id']}" if existing else f"/issues/{pr}/comments"
        result = await self.request("PATCH" if existing else "POST", path, json={"body": body})
        return result["html_url"]

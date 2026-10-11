"""Optional documentation grounding, scoped to one run per client instance.

Contract: https://docs.tinyfish.ai/search-api/reference
"""

import asyncio
import os
import re
import time
from collections import deque
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel

from ux_guardian.security import redact

if TYPE_CHECKING:
    from ux_guardian.enrich.fix import FixContext

SEARCH_URL = "https://api.search.tinyfish.ai"
# Names are deliberately bounded: ordinary UI words such as "overlay", "cart",
# "reactive" and "next" should not turn obvious app regressions into searches.
LIBRARY = re.compile(
    r"\b(?:react|react-dom|next\.js|nextjs|vue|vuejs|angular|svelte|nuxt|vite|webpack|"
    r"axios|lodash|jquery|tailwind(?:css)?|bootstrap|stripe|firebase|supabase|"
    r"prisma|zod|radix|material-ui|mui|sentry)\b|"
    r"node_modules[/\\](@?[\w.-]+(?:[/\\][\w.-]+)?)|"
    r"(?:from\s*|require\s*\()['\"](?![./])(@?[\w.-]+(?:/[\w.-]+)?)['\"]",
    re.IGNORECASE,
)
EXTERNAL_ERROR = re.compile(
    r"\b(?:cors|err_[a-z_]+|chunkloaderror|hydration (?:failed|error|mismatch)|"
    r"minified react error|invalid hook call)\b|"
    r"cannot find module\s+['\"](?![./])|"
    r"(?:third.party|external)\s+(?:api|service|library|package|error)",
    re.IGNORECASE,
)


def search_query(ctx: "FixContext") -> str | None:
    """Extract relevant evidence rather than sending entire patches to Search."""
    evidence = [ctx.observed_problem, *ctx.console_errors, *ctx.failed_requests]
    for text in evidence:
        if EXTERNAL_ERROR.search(text) or LIBRARY.search(text):
            return redact(text)[:500]
    for hunk in ctx.hunks:
        for line in hunk.patch.splitlines():
            match = LIBRARY.search(line)
            if match:
                return redact(match.group(0)) + " documentation"
            if hunk.path.endswith("package.json"):
                dependency = re.match(
                    r'^[+-]\s*"(@?[\w.-]+(?:/[\w.-]+)?)"\s*:\s*"[~^\d][^"]*"', line
                )
                if dependency:
                    return redact(dependency[1]) + " documentation"
    return None


def should_search(ctx: "FixContext") -> bool:
    return search_query(ctx) is not None


def valid_source(url: str) -> bool:
    try:
        parsed = urlsplit(url)
        return (
            parsed.scheme in {"https", "http"}
            and bool(parsed.hostname)
            and not parsed.username
            and not parsed.password
            and not any(char.isspace() or char in "<>`" for char in url)
        )
    except ValueError:
        return False


class SearchResult(BaseModel):
    url: str
    title: str = ""
    snippet: str = ""


class SearchClient:
    """Create a fresh instance per pipeline run; cache hits consume no quota.

    All calls on an instance share a lock, coalescing concurrent identical queries.
    Errors are cached as empty results and never retried automatically.
    """

    def __init__(
        self,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._transport = transport
        self._clock = clock
        self._sleep = sleep
        self._requests: deque[float] = deque()
        self._cache: dict[str, list[SearchResult]] = {}
        self._lock = asyncio.Lock()

    async def _acquire(self) -> None:
        while True:
            now = self._clock()
            while self._requests and now - self._requests[0] >= 60:
                self._requests.popleft()
            if len(self._requests) < 30:
                self._requests.append(now)
                return
            await self._sleep(max(0.001, 60 - (now - self._requests[0])))

    async def search(self, query: str) -> list[SearchResult]:
        query = " ".join(redact(query).split())
        if not query:
            return []
        async with self._lock:
            if query in self._cache:
                return [item.model_copy() for item in self._cache[query]]
            key = os.environ.get("TINYFISH_API_KEY")
            if not key:
                self._cache[query] = []
                return []
            await self._acquire()
            results: list[SearchResult] = []
            async with httpx.AsyncClient(
                transport=self._transport, timeout=30, follow_redirects=False
            ) as client:
                try:
                    response = await client.get(
                        SEARCH_URL, params={"query": query}, headers={"X-API-Key": key}
                    )
                    response.raise_for_status()
                    payload = response.json()
                    if not isinstance(payload, dict) or not isinstance(
                        payload.get("results"), list
                    ):
                        raise ValueError("Invalid Search response")
                    seen: set[str] = set()
                    for item in payload["results"]:
                        if not isinstance(item, dict):
                            continue
                        url = item.get("url")
                        if not isinstance(url, str) or not valid_source(url) or url in seen:
                            continue
                        # Do not cite URLs containing a configured secret.
                        if redact(url) != url:
                            continue
                        seen.add(url)
                        results.append(
                            SearchResult(
                                url=url,
                                title=redact(str(item.get("title", ""))),
                                snippet=redact(str(item.get("snippet", ""))),
                            )
                        )
                        if len(results) == 2:
                            break
                except (httpx.HTTPError, ValueError):
                    pass  # Optional enrichment failure never blocks reporting.
            self._cache[query] = results
            return [item.model_copy() for item in results]

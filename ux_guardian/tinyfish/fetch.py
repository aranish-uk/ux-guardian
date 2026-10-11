"""One free batch request, with no retry and no report publishing.

Contract: https://docs.tinyfish.ai/fetch-api/reference
"""

import os
import re

import httpx

from ux_guardian.checks.models import FetchFlag, FetchPage, FetchResult
from ux_guardian.config import Config, Environment, Journey
from ux_guardian.security import redact

FETCH_URL = "https://api.fetch.tinyfish.ai"
NEAR_EMPTY_CHARS = 40


def compare_pages(pages: list[FetchPage], journeys: list[Journey]) -> list[FetchFlag]:
    flags = []
    for journey in journeys:
        preview = next(
            (p for p in pages if p.journey_id == journey.id and p.env == "preview"), None
        )
        prod = next((p for p in pages if p.journey_id == journey.id and p.env == "prod"), None)
        if not preview or not prod:
            continue
        prod_ok = not prod.error and (prod.http_status is None or 200 <= prod.http_status < 300)
        if not prod_ok:
            continue
        if preview.http_status is not None and not 200 <= preview.http_status < 300:
            flags.append(
                FetchFlag(
                    journey_id=journey.id,
                    signal="http_status",
                    evidence=f"Fetch preview HTTP {preview.http_status}",
                    hard=prod.fetched or prod.http_status is not None,
                )
            )
        if preview.error:
            flags.append(
                FetchFlag(journey_id=journey.id, signal="fetch_error", evidence=preview.error)
            )
        elif len(preview.text.strip()) < NEAR_EMPTY_CHARS:
            flags.append(
                FetchFlag(
                    journey_id=journey.id,
                    signal="near_empty",
                    evidence="Preview extracted text is under 40 characters",
                )
            )
        keywords = set()
        for criterion in journey.success_criteria:
            quoted = re.findall(r'["\u201c]([^"\u201d]+)["\u201d]', criterion)
            keywords.update(quoted or re.findall(r"[\w-]{4,}", criterion))
        missing = sorted(
            word
            for word in keywords
            if word.casefold() in prod.text.casefold()
            and word.casefold() not in preview.text.casefold()
        )
        if missing:
            flags.append(
                FetchFlag(
                    journey_id=journey.id,
                    signal="missing_keywords",
                    evidence="Missing success-criteria text: " + ", ".join(missing),
                )
            )
    return flags


async def fetch_precheck(
    *,
    config: Config,
    journeys: list[Journey],
    environments: list[Environment],
    transport: httpx.AsyncBaseTransport | None = None,
) -> FetchResult:
    pages = [
        FetchPage(
            journey_id=j.id,
            env=env,
            url=(config.preview_url if env == "preview" else config.production_url) + j.entry_path,
        )
        for j in journeys
        for env in environments
    ]
    urls = list(dict.fromkeys(p.url for p in pages))
    if len(urls) > 10:
        raise ValueError("Fetch supports at most 10 entry URLs per request")
    key = os.environ.get("TINYFISH_API_KEY")
    if not key:
        return FetchResult(pages=pages, service_error="TINYFISH_API_KEY is required for Fetch")
    async with httpx.AsyncClient(
        transport=transport, timeout=150, follow_redirects=False
    ) as client:
        try:
            response = await client.post(
                FETCH_URL,
                headers={"X-API-Key": key},
                json={"urls": urls, "format": "markdown", "ttl": 0},
            )
            response.raise_for_status()
            payload = response.json()
            if (
                not isinstance(payload, dict)
                or not isinstance(payload.get("results"), list)
                or not isinstance(payload.get("errors", []), list)
            ):
                raise ValueError("Invalid Fetch response")
        except (httpx.HTTPError, ValueError):
            return FetchResult(pages=pages, service_error="Fetch service request failed")
    results = {
        item["url"]: item
        for item in payload["results"]
        if isinstance(item, dict) and isinstance(item.get("url"), str)
    }
    errors = {
        item["url"]: item
        for item in payload.get("errors", [])
        if isinstance(item, dict) and isinstance(item.get("url"), str)
    }
    for page in pages:
        item = results.get(page.url)
        error = errors.get(page.url)
        if item:
            text = item.get("text")
            page.text = redact(text) if isinstance(text, str) else ""
            # Only explicit origin status is a hard signal. API HTTP errors,
            # extractor errors and empty text do not imply a target-site 404.
            # The exact successful origin HTTP status is not exposed.
            page.fetched = True
        else:
            page.error = "Fetch entry failed" if error else "Fetch entry missing from response"
            if error and error.get("error") in {"target_http_error", "page_not_found"}:
                status = error.get("status")
                page.http_status = (
                    status if isinstance(status, int) and not isinstance(status, bool) else None
                )
    return FetchResult(pages=pages, flags=compare_pages(pages, journeys))

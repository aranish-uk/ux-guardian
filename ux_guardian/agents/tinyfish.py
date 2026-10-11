"""TinyFish REST adapter: bounded paid runs and redacted evidence."""

import asyncio
import json
import logging
import os
import re
from pathlib import Path
from time import monotonic
from typing import Any

import httpx

from ux_guardian.agents.base import AgentRun, Step
from ux_guardian.config import Config, Environment, Journey, Viewport
from ux_guardian.security import redact_data, redact_model

PRICE_PER_STEP = 0.016
OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "completed": {"type": "boolean"},
        "success_criteria_met": {"type": "boolean"},
        "blocked_at_step": {"type": "string"},
        "observed_problem": {"type": "string"},
        "final_page_summary": {"type": "string"},
        "steps": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "n": {"type": "integer"},
                    "action": {"type": "string"},
                    "observation": {"type": "string"},
                },
            },
        },
    },
    "required": ["completed", "steps", "success_criteria_met"],
}


class TinyFishAgent:
    def __init__(
        self,
        *,
        config: Config,
        api_key: str | None = None,
        client: httpx.AsyncClient | None = None,
        output: Path = Path("artifacts") / "runs",
        env: Environment = "prod",
        allowed_urls: list[str] | None = None,
        poll_seconds: float = 2,
        gated_options: bool = False,
    ) -> None:
        self.config = config
        self.api_key = api_key or os.environ.get("TINYFISH_API_KEY", "")
        self.client = client
        self.output = output
        self.env: Environment = env
        self.allowed_urls = allowed_urls or [config.production_url]
        self.poll_seconds = poll_seconds
        self.gated_options = gated_options
        self.semaphore = asyncio.Semaphore(config.concurrency)
        self.spent = 0.0
        self.reserved = 0.0

    async def run_journey(self, *, base_url: str, journey: Journey, viewport: Viewport) -> AgentRun:
        if base_url not in self.allowed_urls:
            raise ValueError("Only configured demo URLs are allowed")
        if viewport != "desktop":
            raise ValueError("TinyFish API does not expose viewport control")
        if not self.api_key:
            raise ValueError("TINYFISH_API_KEY is required")
        if journey.max_steps > 25:
            raise ValueError("Live max_steps must be 25 or less")
        async with self.semaphore:
            estimate = journey.max_steps * PRICE_PER_STEP
            if self.spent + self.reserved + estimate > self.config.budget_usd_per_run:
                raise ValueError("Estimated cost exceeds run budget")
            self.reserved += estimate
            try:
                if self.client is not None:
                    return await self._run(self.client, base_url, journey, viewport)
                async with httpx.AsyncClient(timeout=30) as client:
                    return await self._run(client, base_url, journey, viewport)
            finally:
                self.reserved -= estimate

    async def _run(
        self, client: httpx.AsyncClient, base_url: str, journey: Journey, viewport: Viewport
    ) -> AgentRun:
        goal = journey.safe_goal
        for name, value in {
            "BASE_URL": base_url,
            "TEST_EMAIL": os.environ.get("TEST_EMAIL", ""),
            "TEST_PASSWORD": os.environ.get("TEST_PASSWORD", ""),
        }.items():
            if "{{" + name + "}}" in goal and not value:
                raise ValueError(f"{name} is required")
            goal = goal.replace("{{" + name + "}}", value)
        goal += "\nStay on this demo origin: " + base_url
        goal += "\nVerify every success criterion before reporting success_criteria_met=true:\n"
        goal += "\n".join(journey.success_criteria)
        body: dict[str, Any] = {
            "url": base_url + journey.entry_path,
            "goal": goal,
            "output_schema": OUTPUT_SCHEMA,
        }
        if self.gated_options:
            body.update(
                capture_config={"screenshots": True},
                agent_config={"mode": "strict", "max_steps": journey.max_steps},
            )
        headers = {"X-API-Key": self.api_key}
        root = "https://agent.tinyfish.ai/v1"
        response = await client.post(root + "/automation/run-async", headers=headers, json=body)
        if response.status_code == 403 and self.gated_options:
            # Retry only an explicitly identified capability rejection, never account denial.
            message = response.text.lower()
            if any(word in message for word in ("capture_config", "agent_config", "capability")):
                body.pop("capture_config", None)
                body.pop("agent_config", None)
                response = await client.post(
                    root + "/automation/run-async", headers=headers, json=body
                )
        self._check(response, operation="submit")
        submitted = response.json()
        run_id = submitted["run_id"]
        if not re.fullmatch(r"[A-Za-z0-9_-]+", run_id):
            raise ValueError("Invalid run ID")
        directory = self.output / run_id
        directory.mkdir(parents=True, exist_ok=True)
        responses = [submitted]
        paths: dict[int, str] = {}
        started = monotonic()
        data: dict[str, Any] = {}
        cancelled = False
        try:
            while True:
                response = await client.get(
                    root + "/runs/" + run_id, headers=headers, params={"screenshots": "url"}
                )
                self._check(response)
                data = response.json()
                responses.append(data)
                api_steps = data.get("steps") or []
                count = max(len(api_steps), data.get("num_of_steps") or 0)
                over_cap = count >= journey.max_steps
                terminal = data.get("status") in {"COMPLETED", "FAILED", "CANCELLED"}
                if (over_cap and not terminal) or count > journey.max_steps:
                    self._check(
                        await client.post(root + "/runs/" + run_id + "/cancel", headers=headers)
                    )
                    cancelled = True
                for n, item in enumerate(api_steps, 1):
                    url = item.get("screenshot") or item.get("screenshot_url")
                    if isinstance(url, dict):
                        url = url.get("url")
                    if url and n not in paths:
                        parsed = httpx.URL(url)
                        image_headers = {}
                        if (
                            parsed.scheme == "https"
                            and parsed.host == "agent.tinyfish.ai"
                            and parsed.port in (None, 443)
                            and parsed.path.startswith(("/runs/", "/v1/runs/"))
                            and parsed.path.endswith("/screenshot")
                        ):
                            if parsed.path.startswith("/runs/"):
                                parsed = parsed.copy_with(path="/v1" + parsed.path)
                            image_headers = headers
                        try:
                            request = client.build_request("GET", parsed, headers=image_headers)
                            # Explicitly strip client defaults from external signed URLs.
                            request.headers.pop("Authorization", None)
                            if not image_headers:
                                request.headers.pop("X-API-Key", None)
                            image = await client.send(request, auth=None, follow_redirects=False)
                            if not image.is_success:
                                logging.getLogger(__name__).warning(
                                    "Screenshot step %s HTTP %s; continuing without image",
                                    n,
                                    image.status_code,
                                )
                                continue
                            path = directory / f"step-{n:02}.jpg"
                            path.write_bytes(image.content)
                            paths[n] = str(path)
                        except (httpx.RequestError, OSError):
                            logging.getLogger(__name__).warning(
                                "Screenshot step %s unavailable; continuing without image", n
                            )
                if terminal or cancelled:
                    break
                if monotonic() - started >= self.config.max_duration_seconds:
                    self._check(
                        await client.post(root + "/runs/" + run_id + "/cancel", headers=headers)
                    )
                    cancelled = True
                    break
                await asyncio.sleep(self.poll_seconds)
        except BaseException:
            await client.post(root + "/runs/" + run_id + "/cancel", headers=headers)
            raise
        finally:
            (directory / "responses.json").write_text(
                json.dumps(redact_data(responses), indent=2), encoding="utf-8"
            )
            self.spent += (
                max(len(data.get("steps") or []), data.get("num_of_steps") or 0) * PRICE_PER_STEP
            )
        result = data.get("result") or {}
        if isinstance(result, str):
            try:
                result = json.loads(result)
            except ValueError:
                result = {}
        result_steps = result.get("steps") or []
        steps = []
        for n, item in enumerate(data.get("steps") or result_steps, 1):
            observation = next(
                (s.get("observation", "") for s in result_steps if s.get("n") == n), ""
            )
            steps.append(
                Step(
                    n=n,
                    action=str(item.get("action") or ""),
                    observation=str(observation),
                    screenshot_path=paths.get(n, ""),
                )
            )
        blocked = str(result.get("blocked_at_step") or "")
        cost = max(len(data.get("steps") or []), data.get("num_of_steps") or 0) * PRICE_PER_STEP
        run = redact_model(
            AgentRun(
                run_id=run_id,
                env=self.env,
                journey_id=journey.id,
                viewport=viewport,
                status="CANCELLED" if cancelled else data["status"],
                completed=result.get("completed") is True,
                success_criteria_met=result.get("success_criteria_met") is True,
                blocked_at_step=int(blocked) if blocked.isdigit() and int(blocked) > 0 else None,
                observed_problem=str(result.get("observed_problem") or data.get("error") or ""),
                steps=steps,
                replay_url=data.get("streaming_url") or "",
                cost_usd=cost,
            )
        )
        (directory / "run.json").write_text(run.model_dump_json(indent=2), encoding="utf-8")
        return run

    @staticmethod
    def _check(response: httpx.Response, operation: str = "API") -> None:
        if response.is_error:
            # Never include response bodies, request goals or credentials in exceptions.
            raise ValueError(
                f"TinyFish {operation} HTTP {response.status_code}; no automatic retry"
            )

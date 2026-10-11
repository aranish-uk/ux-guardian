"""Journey-driven adaptation of vibetest-use's semaphore/gather swarm."""

import asyncio
from dataclasses import dataclass

from ux_guardian.agents.base import AgentRun, BrowserAgent
from ux_guardian.config import Environment, Journey, Viewport


@dataclass(frozen=True)
class RunRequest:
    base_url: str
    journey: Journey
    viewport: Viewport
    env: Environment


async def run_pool(
    agent: BrowserAgent, requests: list[RunRequest], *, concurrency: int = 2
) -> list[AgentRun]:
    if concurrency < 1:
        raise ValueError("concurrency must be positive")
    semaphore = asyncio.Semaphore(concurrency)

    async def run_single_agent(request: RunRequest) -> AgentRun:
        async with semaphore:
            result = await agent.run_journey(
                base_url=request.base_url, journey=request.journey, viewport=request.viewport
            )
            return result.model_copy(update={"env": request.env})

    # Upstream's bounded fan-out is preserved; errors now propagate rather than
    # disappearing from the results and leaving a misleading passing summary.
    return list(await asyncio.gather(*(run_single_agent(request) for request in requests)))

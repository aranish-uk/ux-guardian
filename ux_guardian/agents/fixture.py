"""Saved synthetic evidence only. No SDK, credentials, or network."""

from ux_guardian.agents.base import AgentRun
from ux_guardian.config import Environment, Journey, Viewport


class FixtureAgent:
    def __init__(self, runs: list[AgentRun], env: Environment) -> None:
        self._runs = {
            (run.journey_id, run.viewport): run
            for run in runs
            if run.env == env and run.attempt == 1
        }

    async def run_journey(self, *, base_url: str, journey: Journey, viewport: Viewport) -> AgentRun:
        return self._runs[journey.id, viewport].model_copy(deep=True)

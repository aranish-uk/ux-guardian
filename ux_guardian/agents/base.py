from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from ux_guardian.config import Environment, Journey, Viewport


class Contract(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


class Step(Contract):
    n: int = Field(ge=1)
    action: str
    observation: str
    screenshot_path: str = ""


class AgentRun(Contract):
    run_id: str
    env: Environment
    journey_id: str
    viewport: Viewport
    status: str
    completed: bool
    success_criteria_met: bool = False
    blocked_at_step: int | None = None
    observed_problem: str = ""
    steps: list[Step] = Field(default_factory=list)
    replay_url: str = ""
    cost_usd: float = Field(default=0, ge=0)
    attempt: int = Field(default=1, ge=1, le=2)

    @property
    def passed(self) -> bool:
        return self.status == "COMPLETED" and self.completed and self.success_criteria_met


class BrowserAgent(Protocol):
    async def run_journey(
        self, *, base_url: str, journey: Journey, viewport: Viewport
    ) -> AgentRun: ...


class LlmClient(Protocol):
    async def complete_json(self, *, system: str, prompt: str) -> dict[str, object]: ...

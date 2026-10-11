from pydantic import Field

from ux_guardian.agents.base import AgentRun, Contract
from ux_guardian.checks.models import CheckResult, FetchResult
from ux_guardian.config import Environment, Viewport
from ux_guardian.judge.severity import Severity


class Affected(Contract):
    journey_id: str
    name: str
    reason: str
    source: str = "fixture"


class Check(Contract):
    journey_id: str
    env: Environment
    viewport: Viewport
    signal: str
    agrees: bool = False


class Finding(Contract):
    journey_id: str
    severity: Severity
    title: str
    repro_steps: list[str]
    preview_screenshot: str = ""
    prod_screenshot: str = ""
    evidence: list[str]
    fix_suggestion: str
    replay_url: str = ""


class Cost(Contract):
    agent_usd: float = 0
    fetch_usd: float = 0
    search_usd: float = 0
    total_usd: float = 0


class Report(Contract):
    pr: int = Field(ge=1)
    sha: str
    preview_url: str
    prod_url: str
    duration_seconds: float = 0
    fixture: bool = True
    artifact_url: str = ""
    asset_urls: dict[str, str] = Field(default_factory=dict)
    analysis_reasoning: str = ""
    affected: list[Affected]
    runs: list[AgentRun]
    checks: list[Check]
    findings: list[Finding]
    preexisting: list[str] = Field(default_factory=list)
    flaky: list[str] = Field(default_factory=list)
    improved: list[str] = Field(default_factory=list)
    cost: Cost = Field(default_factory=Cost)
    check_results: list[CheckResult] = Field(default_factory=list)
    fetch: FetchResult = Field(default_factory=FetchResult)

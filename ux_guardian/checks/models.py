from pydantic import Field

from ux_guardian.agents.base import Contract
from ux_guardian.config import Environment, Viewport


class SelectorResult(Contract):
    selector: str
    present: bool
    visible: bool = False
    enabled: bool = False
    receives_events: bool = False

    @property
    def passed(self) -> bool:
        return self.present and self.visible and self.enabled and self.receives_events


class CheckResult(Contract):
    journey_id: str
    env: Environment
    viewport: Viewport
    url: str
    http_status: int | None = None
    console_errors: list[str] = Field(default_factory=list)
    blocking_console_errors: list[str] = Field(default_factory=list)
    failed_requests: list[str] = Field(default_factory=list)
    selectors: list[SelectorResult] = Field(default_factory=list)
    screenshot_path: str = ""
    navigation_error: str = ""
    pixel_diff_path: str = ""
    pixel_diff_count: int | None = None

    @property
    def hard_signals(self) -> set[str]:
        signals: set[str] = set()
        if self.http_status is not None and not 200 <= self.http_status < 300:
            signals.add("http_status")
        for selector in self.selectors:
            if not selector.passed:
                # Compare the control, not its failure mode (hidden vs missing).
                signals.add(f"selector:{selector.selector}")
        signals.update(f"console:{error}" for error in self.blocking_console_errors)
        return signals

    @property
    def passed(self) -> bool:
        return self.http_status is not None and not self.navigation_error and not self.hard_signals


class FetchPage(Contract):
    journey_id: str
    env: Environment
    url: str
    text: str = ""
    error: str = ""
    http_status: int | None = None
    fetched: bool = False


class FetchFlag(Contract):
    journey_id: str
    signal: str
    evidence: str
    hard: bool = False


class FetchResult(Contract):
    pages: list[FetchPage] = Field(default_factory=list)
    flags: list[FetchFlag] = Field(default_factory=list)
    service_error: str = ""

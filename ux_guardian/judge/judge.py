from enum import StrEnum

from ux_guardian.agents.base import AgentRun
from ux_guardian.checks.models import CheckResult, FetchResult


class Verdict(StrEnum):
    CANDIDATE = "flaky"
    CONFIRMED = "confirmed"
    PREEXISTING = "preexisting"
    OK = "ok"
    IMPROVED = "improved"


def judge(
    *,
    preview_pass: bool,
    prod_pass: bool,
    deterministic_agrees: bool = False,
    failed_step: int | None = None,
    retry_failed_step: int | None = None,
) -> Verdict:
    if preview_pass:
        return Verdict.OK if prod_pass else Verdict.IMPROVED
    if not prod_pass:
        return Verdict.PREEXISTING
    retry_agrees = (
        failed_step is not None
        and retry_failed_step is not None
        and 1 <= retry_failed_step <= failed_step
    )
    return Verdict.CONFIRMED if deterministic_agrees or retry_agrees else Verdict.CANDIDATE


def judge_evidence(
    *,
    preview: CheckResult,
    prod: CheckResult,
    fetch: FetchResult | None = None,
    preview_agent: AgentRun | None = None,
    prod_agent: AgentRun | None = None,
    retry: AgentRun | None = None,
) -> Verdict:
    """Compare each hard signal to its own prod baseline, never to an agent.

    A prod failure in one control cannot suppress a new preview failure in
    another. A transport timeout is unknown, and cannot establish a baseline.
    Agent-only comparisons require two runs on the same desktop journey.
    """
    if (preview.journey_id, preview.viewport) != (prod.journey_id, prod.viewport):
        raise ValueError("Checks must compare the same journey and viewport")
    if preview.env != "preview" or prod.env != "prod":
        raise ValueError("Checks must compare preview against production")
    if (
        (preview_agent and preview_agent.env != "preview")
        or (prod_agent and prod_agent.env != "prod")
        or (retry and (retry.env != "preview" or retry.attempt != 2))
    ):
        raise ValueError("Agent comparison requires matching environments and a second attempt")
    for run in (preview_agent, prod_agent, retry):
        if run and (
            run.journey_id != preview.journey_id
            or run.viewport != "desktop"
            or preview.viewport != "desktop"
        ):
            raise ValueError("Agent evidence is desktop-only and journey-specific")
    new_hard = regression_signals(preview, prod)
    fetch_hard = bool(
        fetch and any(flag.hard and flag.journey_id == preview.journey_id for flag in fetch.flags)
    )
    if new_hard or fetch_hard:
        return Verdict.CONFIRMED
    if preview_agent and prod_agent:
        return judge(
            preview_pass=preview_agent.passed,
            prod_pass=prod_agent.passed,
            failed_step=preview_agent.blocked_at_step,
            retry_failed_step=retry.blocked_at_step if retry and not retry.passed else None,
        )
    if preview.navigation_error or prod.navigation_error or prod.http_status is None:
        return Verdict.CANDIDATE
    return judge(preview_pass=preview.passed, prod_pass=prod.passed)


def regression_signals(preview: CheckResult, prod: CheckResult) -> set[str]:
    """A missing baseline observation cannot be treated as a passing control."""
    if prod.http_status is None or not 200 <= prod.http_status < 300 or prod.navigation_error:
        return set()
    signals = set()
    if "http_status" in preview.hard_signals:
        signals.add("http_status")
    for control in preview.selectors:
        baseline = next((c for c in prod.selectors if c.selector == control.selector), None)
        if not control.passed and baseline and baseline.passed:
            signals.add(f"selector:{control.selector}")
    # An error already seen in prod is not new, even if it did not block
    # prod there. Do not re-label a pre-existing blocked control via new noise.
    if all(c.passed for c in prod.selectors):
        signals.update(
            f"console:{error}"
            for error in preview.blocking_console_errors
            if error not in prod.console_errors and error not in prod.blocking_console_errors
        )
    return signals

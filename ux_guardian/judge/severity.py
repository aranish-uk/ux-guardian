from enum import StrEnum


class Severity(StrEnum):
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"


def assign_severity(*, hard_error: bool, blocked_viewports: int, total_viewports: int) -> Severity:
    if total_viewports < 1 or not 0 <= blocked_viewports <= total_viewports:
        raise ValueError("Invalid viewport counts")
    if hard_error or blocked_viewports == total_viewports:
        return Severity.P0
    return Severity.P1 if blocked_viewports else Severity.P2


def lower_severity(current: Severity, proposed: Severity, *, justification: str) -> Severity:
    if proposed < current:
        raise ValueError("LLM cannot raise severity")
    if proposed != current and not justification.strip():
        raise ValueError("Lowering severity requires a justification")
    return proposed

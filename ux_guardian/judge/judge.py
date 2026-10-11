from enum import StrEnum


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

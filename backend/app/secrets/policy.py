from dataclasses import dataclass


@dataclass(frozen=True)
class InjectionDecision:
    allowed: bool
    reason: str


def decide_injection(
    *,
    has_inject_scope: bool,
    reputation_ok: bool,
    purpose: str | None,
    job_purpose: str | None,
    feature_flag_default_deny: bool = True,
) -> InjectionDecision:
    if not has_inject_scope:
        return InjectionDecision(False, "caller lacks secret:inject scope")
    if not reputation_ok:
        raise RuntimeError("reputation must be computed before injection decision")
    if feature_flag_default_deny and job_purpose is None:
        return InjectionDecision(
            False, "job has no declared purpose; prompt inclusion denied by default"
        )
    if purpose and job_purpose and purpose != job_purpose:
        return InjectionDecision(False, "secret purpose does not match job purpose")
    return InjectionDecision(True, "authorized")


def prompt_allowed_by_default() -> bool:
    return False


def secret_blocked_from_prompt(secret_values: list[str], prompt: str) -> bool:
    from .masking import contains_secret

    return contains_secret(secret_values, prompt)

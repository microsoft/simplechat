# functions_orchestration_admission.py
"""Fail-closed contract selection for new orchestration plans only."""

from collections.abc import Mapping


HARNESS_ADMISSION_READY = True


def get_new_plan_contract_version(
    settings: Mapping[str, object] | None, *, admission_ready: bool = False
) -> int:
    """Select v2 only after both admin opt-ins and server readiness are true.

    Callers supply normalized settings and server-owned rollout readiness, never
    request data. This is not authorization: existing capability/model access and
    budgets still apply. Do not use it to dispatch saved plans, reads or recovery;
    those retain their recorded contract version when admission is switched off.
    """
    if admission_ready is not True or not isinstance(settings, Mapping):
        return 1
    if (
        settings.get("enable_chat_orchestration") is True
        and settings.get("enable_chat_orchestration_harness") is True
    ):
        return 2
    return 1

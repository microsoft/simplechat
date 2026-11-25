# functions_workflow_policy_errors.py
"""Bootstrap-free, non-retryable workflow policy failures shared by the runner and journal."""

import re

from functions_model_capabilities import ModelTokenBudgetError


# A request's sizes, in the units of its estimator, under the names telemetry keeps. The
# telemetry filter replaces the value of any key containing "token" with a present flag, as
# it would a credential, so the audit's own names never reach the log.
_CONTEXT_BUDGET_LOG_COUNTS = (
    ("input_tokens", "input_size"), ("input_budget_tokens", "input_budget"),
    ("context_window_tokens", "context_window"),
    ("effective_context_window_tokens", "effective_context_window"),
    ("max_input_tokens", "max_input"), ("max_output_tokens", "max_output"),
    ("output_reserve_tokens", "output_reserve"), ("safety_tokens", "safety_margin"),
)
# Closed codes. The estimator says whether the sizes are tokens or a byte upper bound.
_CONTEXT_BUDGET_LOG_CODES = (
    ("limit_source", "limit_source"), ("limit_status", "limit_status"),
    ("output_reservation", "output_reservation"), ("decision", "budget_decision"),
    ("token_estimator", "size_estimator"),
)
_CONTEXT_BUDGET_CODE_RE = re.compile(r"[a-z][a-z0-9_]{0,39}(?:\+[a-z][a-z0-9_]{0,39})?")
_MODEL_BUDGET_MESSAGES = {
    "model_context_invalid": "The selected model's token configuration is invalid. Review its token limits and response length.",
    "model_context_unavailable": "Configure verified token limits and a response length for the selected text-generation model.",
    "model_generation_unbounded": "The selected model needs a verified total-generation token allowance, including reasoning.",
}


class WorkflowPolicyError(ValueError):
    """An application refusal that must finish the attempt, not replay its operations."""

    def __init__(self, code, public_message):
        self.code = code
        self.public_message = public_message
        super().__init__(public_message)


class WorkflowTaskPolicyError(RuntimeError):
    """Keep the task runner's RuntimeError contract while preserving a reviewed policy reason."""

    def __init__(self, code, public_message):
        self.code = code
        self.public_message = public_message
        super().__init__(public_message)


class WorkflowContextBudgetError(WorkflowPolicyError):
    """Required input remains durable but cannot fit the selected request."""

    def __init__(self, audit):
        self.audit = audit
        budget_name = (
            "the compatibility input budget (model limits are unverified)"
            if audit.get("limit_source") == "compatibility_policy"
            else "the selected model's input budget"
        )
        super().__init__(
            "workflow_context_budget_exceeded",
            f"The complete workflow input exceeds {budget_name} "
            f"({audit['input_tokens']} estimated tokens; {audit['input_budget_tokens']} available). "
            "The upstream result is retained without truncation. Configure verified model limits, "
            "select a larger context window, or process the input in explicit batches.",
        )


def context_budget_log_fields(audit):
    """What a budget audit may say in telemetry: counts and closed codes, never content.

    A limit drawn from two origins is joined with "+" in the audit and with "_and_" here,
    because telemetry keeps a code only when it is one lowercase word.
    """
    if not isinstance(audit, dict):
        return {}
    fields = {name: audit[key] for key, name in _CONTEXT_BUDGET_LOG_COUNTS if type(audit.get(key)) is int}
    for key, name in _CONTEXT_BUDGET_LOG_CODES:
        value = audit.get(key)
        if type(value) is str and _CONTEXT_BUDGET_CODE_RE.fullmatch(value):
            fields[name] = value.replace("+", "_and_")
    return fields


def workflow_policy_failure(error):
    """Project only application-owned policy failures, never arbitrary provider exception text."""
    if isinstance(error, (WorkflowPolicyError, WorkflowTaskPolicyError)):
        return {"error_code": error.code, "error": error.public_message}
    if isinstance(error, ModelTokenBudgetError):
        code = error.code if error.code in _MODEL_BUDGET_MESSAGES else "model_context_invalid"
        return {"error_code": code, "error": _MODEL_BUDGET_MESSAGES[code]}
    return None

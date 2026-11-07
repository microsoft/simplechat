# functions_workflow_policy_errors.py
"""Bootstrap-free, non-retryable workflow policy failures shared by the runner and journal."""

from functions_model_capabilities import ModelTokenBudgetError


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


def workflow_policy_failure(error):
    """Project only application-owned policy failures, never arbitrary provider exception text."""
    if isinstance(error, (WorkflowPolicyError, WorkflowTaskPolicyError)):
        return {"error_code": error.code, "error": error.public_message}
    if isinstance(error, ModelTokenBudgetError):
        code = error.code if error.code in _MODEL_BUDGET_MESSAGES else "model_context_invalid"
        return {"error_code": code, "error": _MODEL_BUDGET_MESSAGES[code]}
    return None

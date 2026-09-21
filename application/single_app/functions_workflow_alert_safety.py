# functions_workflow_alert_safety.py
"""Public projections for current and historical workflow alert diagnostics."""

from copy import deepcopy


WORKFLOW_ALERT_EVALUATION_ERROR_CODE = "workflow_alert_evaluation_failed"
WORKFLOW_ALERT_EVALUATION_ERROR_MESSAGE = (
    "Alert conditions could not be evaluated. Review the workflow model configuration or contact an administrator."
)
WORKFLOW_ALERT_EVALUATOR_UNAVAILABLE_MESSAGE = "No model evaluator was available for this run."
_LEGACY_ERROR_PREFIX = "Alert condition could not be evaluated:"
_RENDERED_FIELDS = ("message", "title", "alert_detail", "alert_summary", "trigger_reason")


def _is_diagnostic_match(match):
    if not isinstance(match, dict):
        return False
    reason = match.get("reason")
    legacy_error = (
        not match.get("source")
        and match.get("condition_type") == "model_evaluation"
        and isinstance(reason, str) and reason.startswith(_LEGACY_ERROR_PREFIX)
    )
    return (
        legacy_error or match.get("source") == "model_evaluation_error"
        or match.get("reason_code") == WORKFLOW_ALERT_EVALUATION_ERROR_CODE
    )


def _diagnostic_reasons(payload):
    return [
        match["reason"] for match in payload.get("matched_rules") or []
        if _is_diagnostic_match(match) and isinstance(match.get("reason"), str)
    ]


def _replace_rendered_reasons(payload, reasons):
    for field in _RENDERED_FIELDS:
        text = payload.get(field)
        if not isinstance(text, str):
            continue
        for reason in reasons:
            if reason:
                text = text.replace(reason, WORKFLOW_ALERT_EVALUATION_ERROR_MESSAGE)
        payload[field] = text


def sanitize_workflow_alert_decision(decision):
    """Remove known diagnostic fields without altering legitimate model explanations."""
    if not isinstance(decision, dict):
        raise ValueError("Workflow alert decisions must be objects.")
    cleaned = deepcopy(decision)
    reasons = _diagnostic_reasons(cleaned)
    for match in cleaned.get("matched_rules") or []:
        if _is_diagnostic_match(match):
            match["reason"] = WORKFLOW_ALERT_EVALUATION_ERROR_MESSAGE
            match["reason_code"] = WORKFLOW_ALERT_EVALUATION_ERROR_CODE
    if isinstance(cleaned.get("reasons"), list):
        cleaned["reasons"] = [
            WORKFLOW_ALERT_EVALUATION_ERROR_MESSAGE if reason in reasons else reason
            for reason in cleaned["reasons"]
        ]
    evaluation = cleaned.get("model_evaluation")
    if isinstance(evaluation, dict) and evaluation.get("error"):
        if evaluation["error"] != WORKFLOW_ALERT_EVALUATOR_UNAVAILABLE_MESSAGE:
            evaluation["error"] = WORKFLOW_ALERT_EVALUATION_ERROR_MESSAGE
            evaluation["error_code"] = WORKFLOW_ALERT_EVALUATION_ERROR_CODE
    _replace_rendered_reasons(cleaned, reasons)
    return cleaned


def sanitize_workflow_alert_record(record):
    """Project stored runs and workflow notifications without mutating their records."""
    if not isinstance(record, dict):
        raise ValueError("Workflow alert records must be objects.")
    cleaned = dict(record)
    if isinstance(record.get("alert_decision"), dict):
        cleaned["alert_decision"] = sanitize_workflow_alert_decision(record["alert_decision"])
    if record.get("notification_type") == "workflow_priority_alert" and isinstance(record.get("metadata"), dict):
        reasons = _diagnostic_reasons(record["metadata"])
        cleaned["metadata"] = sanitize_workflow_alert_decision(record["metadata"])
        _replace_rendered_reasons(cleaned, reasons)
    return cleaned

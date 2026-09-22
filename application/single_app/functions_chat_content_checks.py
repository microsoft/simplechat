# functions_chat_content_checks.py
"""Shared chat checkpoints, independent of document admission and review.

Application settings, clients, logging, and Flask context are resolved only at
execution boundaries. The evaluator can be imported without bootstrapping Azure.
Private check results are never part of the ordinary browser message contract.
"""

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import logging
from typing import Literal

from content_screening.contracts import ContentUnit, ScreeningValidationError, hash_payload, text_fingerprint
from content_screening.engine import inspect_text_units
from content_screening.policies import compose_policy, policy_is_active
from functions_content_safety import (
    analyze_content_safety_text,
    build_content_safety_violation_message,
)


CHECK_METADATA = "chat_content_checks"
CHECK_CONTEXT_KEY = "simplechat.chat_content_checks"
SCANNERS = ("content_screening", "content_safety")
CHECKPOINTS = ("chat_input", "chat_output")
REMOVED_REPLY_MESSAGE = "This AI reply was removed because it did not meet the application's content rules."
UNCHECKED_REPLY_MESSAGE = "This AI reply is unavailable because the required content checks could not finish."
BLOCKED_INPUT_MESSAGE = "Your message was blocked by the application's content rules. Please revise it and try again."
UNCHECKED_INPUT_MESSAGE = "The required content checks could not finish. Please try sending your message again."
SAFE_MESSAGE_FIELDS = (
    "id", "conversation_id", "timestamp", "created_at", "updated_at",
    "model_deployment_name", "model_icon", "agent_name", "agent_display_name",
    "agent_icon", "agent_tags", "reply_to_message_id", "message_kind",
)
SAFE_METADATA_FIELDS = (
    "thread_info", "user_info", "sender", "token_usage", "model_selection",
    "source_conversation_id", "source_message_id", "source_thought_user_id",
    "explicit_ai_invocation", "orchestration_turn_id",
)
ANSWER_FIELDS = (
    "hybrid_citations", "web_search_citations", "agent_citations",
    "cited_hybrid_citations", "cited_web_search_citations",
    "generated_artifacts", "generated_analysis_artifacts", "generated_tabular_outputs",
)

CHAT_CONTENT_FORM_DEFAULTS = {
    "enable_content_screening_workspace_uploads": True,
    "enable_content_screening_chat_input": False,
    "enable_content_screening_chat_output": False,
    "enable_content_safety_chat_input": True,
    "enable_content_safety_chat_output": False,
    "chat_content_output_mode": "stream_then_check",
    "chat_content_scan_failure_action": "allow_unchecked",
}


def chat_content_form_updates(form_data, current_settings):
    """Old open forms must not reset controls added after the page was loaded."""
    return {
        key: (
            form_data.get(key) == "on" if isinstance(default, bool)
            else form_data.get(key, default)
        ) if form_data.get("chat_content_settings_present") == "1"
        else current_settings.get(key, default)
        for key, default in CHAT_CONTENT_FORM_DEFAULTS.items()
    }


@dataclass(frozen=True)
class ChatContentDecision:
    checkpoint: Literal["chat_input", "chat_output"]
    status: Literal["not_required", "passed", "findings", "not_checked"]
    decision: Literal["allow", "allow_unchecked", "block"]
    metadata: dict
    notice: str | None = None

    @property
    def blocked(self):
        return self.decision == "block"


def _timestamp():
    return datetime.now(timezone.utc).isoformat()


def enabled_chat_scanners(settings, checkpoint):
    if checkpoint not in CHECKPOINTS:
        raise ValueError("Invalid chat checkpoint.")
    return [
        scanner for scanner in SCANNERS
        if settings.get(f"enable_{scanner}") is True
        and settings.get(
            f"enable_{scanner}_{checkpoint}",
            scanner == "content_safety" and checkpoint == "chat_input",
        ) is True
    ]


def _unchecked(scanner, code):
    return {
        "scanner": scanner, "status": "not_checked", "complete": False,
        "finding_count": 0, "error_code": code,
    }


def evaluate_chat_content(
    text, checkpoint, settings, *, baseline_loader=None, safety_client=None,
    model_evaluator=None, required_scanners=None, log=None,
):
    """Evaluate exactly this text; a known finding always overrides allow-on-error."""
    enabled = enabled_chat_scanners(settings, checkpoint)
    required = list(required_scanners) if required_scanners is not None else enabled
    if any(scanner not in SCANNERS for scanner in required) or len(set(required)) != len(required):
        raise ValueError("Invalid chat scanners.")
    if not isinstance(text, str):
        raise ScreeningValidationError("Chat content must be text.")
    try:
        fingerprint = text_fingerprint(text)
    except UnicodeError:
        raise ScreeningValidationError("Chat text must contain valid Unicode.") from None
    if not required or not text.strip():
        return ChatContentDecision(checkpoint, "not_required", "allow", {})

    results = []
    for scanner in required:
        if scanner not in enabled:
            results.append(_unchecked(scanner, "chat_scanner_disabled"))
            continue
        if scanner == "content_screening":
            try:
                baseline = baseline_loader() if callable(baseline_loader) else None
                if not isinstance(baseline, dict):
                    results.append(_unchecked(scanner, "screening_policy_unavailable"))
                    continue
                policy = compose_policy(baseline)
                if not policy_is_active(policy):
                    results.append(_unchecked(scanner, "screening_policy_empty"))
                    continue
                inspection = inspect_text_units(
                    [ContentUnit("chat-text", text, {"kind": "chat_text"})],
                    policy, model_evaluator=model_evaluator,
                )
                complete = inspection.status in ("pass", "findings") and inspection.error_code is None
                results.append({
                    "scanner": scanner,
                    "status": "findings" if inspection.findings else "passed" if complete else "not_checked",
                    "complete": complete,
                    "finding_count": len(inspection.findings),
                    "policy_fingerprint": policy["fingerprint"],
                    "error_code": inspection.error_code,
                    "categories": sorted({finding.category for finding in inspection.findings}),
                    "rule_ids": sorted({finding.rule_id for finding in inspection.findings})[:100],
                    "coverage": {
                        "units_total": inspection.units_total,
                        "required_windows": sum(item.get("required_windows", 0) for item in inspection.detectors),
                        "completed_windows": sum(item.get("completed_windows", 0) for item in inspection.detectors),
                    },
                })
            except Exception as error:
                results.append(_unchecked(scanner, "screening_check_failed"))
                if log:
                    log(scanner, "screening_check_failed", type(error).__name__)
        else:
            try:
                analysis = analyze_content_safety_text(text, safety_client)
                results.append({
                    "scanner": scanner, "status": analysis.status, "complete": analysis.complete,
                    "finding_count": sum(item["severity"] >= 4 for item in analysis.categories)
                    + analysis.blocklist_match_count,
                    "categories": analysis.categories,
                    "blocklist_match_count": analysis.blocklist_match_count,
                    "error_code": analysis.error_code,
                    "coverage": {
                        "required_windows": analysis.required_windows,
                        "completed_windows": analysis.completed_windows,
                    },
                })
            except Exception as error:
                results.append(_unchecked(scanner, "content_safety_check_failed"))
                if log:
                    log(scanner, "content_safety_check_failed", type(error).__name__)

    for result in results:
        if not result["complete"] and log:
            log(result["scanner"], result.get("error_code") or "chat_check_incomplete", None)
    findings = any(result["finding_count"] for result in results)
    complete = all(result["complete"] for result in results)
    status = "findings" if findings else "passed" if complete else "not_checked"
    decision = (
        "block" if findings or not complete and settings.get("chat_content_scan_failure_action") == "block"
        else "allow" if complete else "allow_unchecked"
    )
    metadata = {
        "schema_version": 1, "checkpoint": checkpoint,
        "origin": "user" if checkpoint == "chat_input" else "assistant",
        "status": status, "complete": complete, "decision": decision,
        "content_fingerprint": fingerprint,
        "attempted_at": _timestamp(), "scanners": results,
    }
    notice = None
    if decision == "block":
        if checkpoint == "chat_output":
            notice = REMOVED_REPLY_MESSAGE if findings else UNCHECKED_REPLY_MESSAGE
        elif not findings:
            notice = UNCHECKED_INPUT_MESSAGE
        elif any(item["scanner"] == "content_safety" and item["finding_count"] for item in results):
            safety = next(item for item in results if item["scanner"] == "content_safety")
            notice = build_content_safety_violation_message(
                settings, ["Content Safety policy violation"],
                [item for item in safety.get("categories", []) if item["severity"] >= 4], [],
            )
        else:
            notice = BLOCKED_INPUT_MESSAGE
    return ChatContentDecision(checkpoint, status, decision, metadata, notice)


def _request_context():
    # Background Flask request copies share this server-owned environ, not client JSON.
    from flask import has_request_context, request

    if not has_request_context():
        return None
    return request.environ.setdefault(CHECK_CONTEXT_KEY, {"inputs": {}, "messages": {}})


def check_chat_content(text, checkpoint, *, user_id, settings=None, required_scanners=None):
    """Wire application dependencies only for a checkpoint that is actually enabled."""
    if settings is None:
        from functions_settings import get_settings

        settings = get_settings()
    enabled = enabled_chat_scanners(settings, checkpoint)
    if not enabled and required_scanners is None:
        return ChatContentDecision(checkpoint, "not_required", "allow", {})
    from functions_appinsights import log_event

    context = _request_context()
    settings_fingerprint = hash_payload({
        key: value for key, value in settings.items()
        if key.startswith(("enable_content_", "chat_content_"))
    })
    try:
        content_fingerprint = text_fingerprint(text)
    except (UnicodeError, ScreeningValidationError):
        log_event(
            "[CHAT_CONTENT_CHECKS] Invalid chat text was rejected.",
            extra={"checkpoint": checkpoint}, level=logging.WARNING,
        )
        raise ScreeningValidationError("Chat text must contain valid Unicode.") from None
    cache_key = (str(user_id), checkpoint, content_fingerprint, settings_fingerprint)
    if checkpoint == "chat_input" and context is not None and required_scanners is None:
        cached = context["inputs"].get(cache_key)
        if cached is not None:
            return cached

    def baseline_loader():
        from content_screening.repository import get_repository

        document = get_repository().get_policy("global", "global")
        return document["policy"] if document else None

    def log_failure(scanner, code, error_type):
        log_event(
            "[CHAT_CONTENT_CHECKS] Required chat check did not complete.",
            extra={"scanner": scanner, "checkpoint": checkpoint, "code": code, "error_type": error_type},
            level=logging.WARNING,
        )

    safety_client = None
    if "content_safety" in enabled:
        from config import CLIENTS

        safety_client = CLIENTS.get("content_safety_client")
    result = evaluate_chat_content(
        text, checkpoint, settings,
        baseline_loader=baseline_loader, safety_client=safety_client,
        required_scanners=required_scanners, log=log_failure,
    )
    if result.metadata:
        result.metadata["actor_user_id"] = str(user_id)
    if checkpoint == "chat_input" and context is not None and required_scanners is None:
        context["inputs"][cache_key] = result
    return result


def attach_chat_check(message, result):
    if result.status != "not_required":
        message.setdefault("metadata", {})[CHECK_METADATA] = deepcopy(result.metadata)
        message["metadata"]["content_moderation"] = {
            "revision": result.metadata.get("attempted_at"),
        }
    return message


def orchestration_input_text(message, answered_questions):
    parts = [str(message or "")]
    for question in answered_questions or []:
        answer = question.get("answer") if isinstance(question, dict) else None
        if answer is not None:
            parts.append(answer if isinstance(answer, str) else json.dumps(answer, sort_keys=True, ensure_ascii=False))
    return "\n\n".join(parts)


def blocked_chat_payload(result, *, conversation_id=None, message_id=None):
    return {
        "done": True, "blocked": True, "role": "safety", "replace_content": True,
        "reply": result.notice, "content": result.notice, "full_content": result.notice,
        "conversation_id": conversation_id, "message_id": message_id,
        "hybrid_citations": [], "web_search_citations": [], "agent_citations": [],
    }


def retract_message_content(message, result):
    """Return an ordinary-history replacement without rejected content or derived links."""
    previous = message.get("metadata") or {}
    metadata = {key: deepcopy(previous[key]) for key in SAFE_METADATA_FIELDS if key in previous}
    metadata[CHECK_METADATA] = deepcopy(result.metadata)
    orchestration = previous.get("orchestration")
    if isinstance(orchestration, dict):
        metadata["orchestration"] = {
            key: deepcopy(orchestration[key])
            for key in ("run_id", "turn_id", "attempt_index", "retry_of_run_id", "status", "outcome")
            if key in orchestration
        }
    metadata["content_moderation"] = {
        "removed": True, "revision": result.metadata.get("attempted_at") or _timestamp(),
    }
    safe = {key: deepcopy(message[key]) for key in SAFE_MESSAGE_FIELDS if key in message}
    safe.update({
        "role": "safety", "content": result.notice, "metadata": metadata, "augmented": False,
        **{key: [] for key in ANSWER_FIELDS},
    })
    return safe


def prepare_checked_reply(message, *, user_id, settings=None):
    """Check before normal reply persistence and remember the authoritative transport form."""
    if message.get("role") != "assistant" or not isinstance(message.get("content"), str):
        return message
    result = check_chat_content(
        message["content"], "chat_output", user_id=user_id, settings=settings,
    )
    if result.status == "not_required":
        return message
    if result.blocked:
        replacement = retract_message_content(message, result)
        message.clear()
        message.update(replacement)
    else:
        attach_chat_check(message, result)
    context = _request_context()
    if context is not None and message.get("id"):
        context["messages"][message["id"]] = deepcopy(message)
    return message


def remember_checked_reply(message):
    context = _request_context()
    if context is not None and message.get("id"):
        context["messages"][message["id"]] = deepcopy(message)
    return message


def strip_private_chat_checks(value, *, metadata=False):
    """Keep failure diagnostics out of public JSON, SSE, inspectors, and exports."""
    if isinstance(value, dict):
        return {
            key: strip_private_chat_checks(item, metadata=key == "metadata")
            for key, item in value.items() if not (metadata and key == CHECK_METADATA)
        }
    if isinstance(value, list):
        return [strip_private_chat_checks(item) for item in value]
    return value


def public_chat_payload(payload):
    """A terminal replacement must beat any accumulated text and stale caller variables."""
    if not isinstance(payload, dict):
        return strip_private_chat_checks(payload)
    context = _request_context()
    message = context["messages"].get(payload.get("message_id")) if context is not None else None
    result = dict(payload)
    if message is not None:
        result.update({
            "full_content": message["content"], "replace_content": True, "role": message["role"],
            "metadata": message.get("metadata", {}),
        })
        for key in ("reply", "content", "partial_content"):
            if key in result:
                result[key] = message["content"]
        if message["role"] == "safety":
            result = {
                key: result[key] for key in (
                    "conversation_id", "conversation_title", "conversation_kind",
                    "message_id", "user_message_id", "request_id", "m365_pending_actions",
                ) if key in result
            }
            result.update({
                "done": True, "blocked": True, "content": message["content"],
                "reply": message["content"], "full_content": message["content"],
                "role": "safety", "replace_content": True,
                "metadata": message.get("metadata", {}),
                "augmented": False, **{key: [] for key in ANSWER_FIELDS},
            })
    return strip_private_chat_checks(result)


def should_withhold_chat_event(payload, settings):
    if (
        settings.get("chat_content_output_mode") != "check_before_display"
        or not enabled_chat_scanners(settings, "chat_output")
        or not isinstance(payload, dict)
        or payload.get("done") or payload.get("error")
        or payload.get("auth_required") is True
        or payload.get("cancelled") or payload.get("canceled")
    ):
        return False
    if payload.get("type") in (
        "user_message_persisted", "conversation_metadata", "m365_pending_action",
        "m365_approval_required", "m365_sign_in_required",
    ):
        return False
    return True

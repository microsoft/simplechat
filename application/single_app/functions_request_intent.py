# functions_request_intent.py
"""Shared request-intent decision for actions a chat turn can start on its own.

Keyword detectors only nominate an action. This module decides, per action, whether the
user actually asked for it, records that decision for the turn, and lets the code that
performs the action check it again. Understanding the request and enforcing the decision
are deliberately separate: the detectors consult the decision as a convenience, while the
action entry points (background run submission, file publication) enforce it.

Permissions are tracked per action. "No files" restricts file creation only, and
"no background processing" restricts detached runs only.
"""

import hashlib
import json
import logging
import re
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar

from functions_appinsights import log_event


REQUEST_INTENT_CONTRACT_VERSION = "request-intent-v1"

ACTION_FILE_EXPORT = "file_export"
ACTION_BACKGROUND_RUN = "background_run"
REQUEST_INTENT_ACTIONS = (ACTION_FILE_EXPORT, ACTION_BACKGROUND_RUN)

PERMISSION_ALLOWED = "allowed"
PERMISSION_WITHHELD = "withheld"

SOURCE_NOT_NOMINATED = "not_nominated"
SOURCE_KEYWORDS = "keywords"
SOURCE_OPT_OUT = "opt_out"
SOURCE_USER_OVERRIDE = "user_override"
SOURCE_MODEL = "model"
SOURCE_FALLBACK = "fallback"
SOURCE_UNCHECKED = "unchecked"

REQUEST_INTENT_MODE_OFF = "off"
REQUEST_INTENT_MODE_SHADOW = "shadow"
REQUEST_INTENT_MODE_ACTIVE = "active"
REQUEST_INTENT_MODES = {
    REQUEST_INTENT_MODE_OFF,
    REQUEST_INTENT_MODE_SHADOW,
    REQUEST_INTENT_MODE_ACTIVE,
}
REQUEST_INTENT_DEFAULT_MODE = REQUEST_INTENT_MODE_ACTIVE

REQUEST_INTENT_MODEL_MAX_TOKENS = 400
REQUEST_INTENT_PRIOR_ASSISTANT_MAX_CHARS = 1200
REQUEST_INTENT_USER_MESSAGE_MAX_CHARS = 12000
_TURN_DECISION_TTL_SECONDS = 30 * 60
_TURN_DECISION_MAX_ENTRIES = 2000

_NEGATION = r"(?:do\s+not|don['’]?t|must\s+not|mustn['’]?t|should\s+not|shouldn['’]?t|never|please\s+do\s+not)"
_FILE_VERBS = r"(?:create|generate|produce|make|write|save|export|output|attach|build|emit)"
_FILE_OPT_OUT_PATTERNS = (
    re.compile(rf"\b{_NEGATION}\b[^.!?;\n]{{0,80}}\b{_FILE_VERBS}\b[^.!?;\n]{{0,40}}\bfiles?\b"),
    re.compile(r"\bno\s+(?:new\s+|downloadable\s+|output\s+|export\s+)?files?\b"),
    re.compile(r"\bwithout\s+(?:creating|generating|producing|making|writing|saving|exporting)\s+(?:any\s+|a\s+)?files?\b"),
)
_BACKGROUND_OPT_OUT_PATTERNS = (
    re.compile(
        rf"\b{_NEGATION}\b[^.!?;\n]{{0,80}}\b(?:background|asynchronous|async|detached)\s+"
        r"(?:processing|process|job|jobs|run|runs|task|tasks|work|export|exports)\b"
    ),
    re.compile(rf"\b{_NEGATION}\b[^.!?;\n]{{0,60}}\bin\s+the\s+background\b"),
    re.compile(r"\bno\s+background\s+(?:processing|process|job|jobs|run|runs|task|tasks|work|export|exports)\b"),
    re.compile(r"\bwithout\s+(?:any\s+)?background\s+(?:processing|jobs?|runs?|tasks?|work)\b"),
)
# "In chat only" is about where the answer is delivered. It rules out a file and a detached
# run, and nothing else.
_CHAT_ONLY_PATTERNS = (
    re.compile(r"\bin[\s-]+(?:the\s+)?chat\s+only\b"),
    re.compile(r"\bonly\s+in[\s-]+(?:the\s+|this\s+)?chat\b"),
    re.compile(r"\bchat[\s-]+only\b"),
)

_current_decision = ContextVar("request_intent_decision", default=None)
_gating_suspended = ContextVar("request_intent_gating_suspended", default=False)
_turn_decisions = {}
_turn_decisions_lock = threading.Lock()


class RequestIntentWithheldError(Exception):
    """Raised when an action entry point is reached for an action the turn withheld."""

    def __init__(self, action):
        super().__init__(f"The request did not authorize the {action} action.")
        self.action = action


def _normalize_message(user_message):
    return re.sub(r"\s+", " ", str(user_message or "").strip().casefold())


def request_intent_message_key(user_message):
    """Return the stable key that ties a decision to one exact user message."""
    normalized = _normalize_message(user_message)
    if not normalized:
        return ""
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def normalize_request_intent_check_mode(settings=None, mode=None):
    """Return a supported request-intent check mode."""
    raw_mode = mode
    if raw_mode is None:
        raw_mode = (settings or {}).get("request_intent_check_mode", REQUEST_INTENT_DEFAULT_MODE)
    normalized_mode = str(raw_mode or "").strip().lower()
    if normalized_mode in REQUEST_INTENT_MODES:
        return normalized_mode
    return REQUEST_INTENT_DEFAULT_MODE


def explicit_side_effect_opt_out(user_message):
    """Return the actions the user unambiguously ruled out, without a model call.

    This is a deterministic safety net that applies in every mode. It is intentionally
    narrow: it recognizes direct statements about files and background processing, not
    every way of declining a format. Anything subtler is left to the model check.
    """
    normalized = _normalize_message(user_message)
    if not normalized:
        return set()

    opted_out = set()
    if any(pattern.search(normalized) for pattern in _FILE_OPT_OUT_PATTERNS):
        opted_out.add(ACTION_FILE_EXPORT)
    if any(pattern.search(normalized) for pattern in _BACKGROUND_OPT_OUT_PATTERNS):
        opted_out.add(ACTION_BACKGROUND_RUN)
    if any(pattern.search(normalized) for pattern in _CHAT_ONLY_PATTERNS):
        opted_out.update((ACTION_FILE_EXPORT, ACTION_BACKGROUND_RUN))
    return opted_out


@contextmanager
def request_intent_gating_suspended():
    """Run the keyword detectors as if no decision existed."""
    token = _gating_suspended.set(True)
    try:
        yield
    finally:
        _gating_suspended.reset(token)


def _parse_json_object(text):
    raw_text = str(text or "").strip()
    if not raw_text:
        return None
    candidates = [raw_text]
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw_text, re.DOTALL)
    if fenced:
        candidates.insert(0, fenced.group(1))
    start, end = raw_text.find("{"), raw_text.rfind("}")
    if 0 <= start < end:
        candidates.append(raw_text[start:end + 1])
    for candidate in candidates:
        try:
            payload = json.loads(candidate)
        except (TypeError, ValueError):
            continue
        if isinstance(payload, dict):
            return payload
    return None


def _describe_nominated_actions(nominated):
    lines = []
    file_export = nominated.get(ACTION_FILE_EXPORT)
    if file_export:
        formats = ", ".join(str(item).upper() for item in file_export.get("formats") or [])
        lines.append(f"- file_export: create a downloadable file ({formats or 'format unspecified'}).")
    background_run = nominated.get(ACTION_BACKGROUND_RUN)
    if background_run:
        kinds = []
        if background_run.get("full_export"):
            kinds.append("a complete export of every row")
        if background_run.get("full_analysis"):
            kinds.append("a complete analysis of every row")
        if background_run.get("per_row_output"):
            kinds.append("one result per row")
        lines.append(
            "- background_run: start a background job that continues after this reply and "
            f"delivers {' and '.join(kinds) or 'the complete result'} to the chat later."
        )
    return "\n".join(lines)


def build_request_intent_messages(user_message, nominated, prior_assistant_text=None):
    """Build the short classification prompt for the nominated actions."""
    instructions = (
        "You decide whether a chat application should start actions on a user's behalf. "
        "Keyword matching flagged the actions listed below as possibly requested by the "
        "latest user message. Keywords are unreliable: the user may have mentioned a format "
        "or a file only to forbid it, to describe a later step, or to describe their input.\n\n"
        "For each listed action answer \"wanted\", \"not_wanted\" or \"unclear\".\n"
        "- file_export is wanted only if the user is asking, in this message, to receive a "
        "file now. It is not_wanted if they forbid files or that format, assign file creation "
        "to a later step or to someone else, ask for the answer in the chat instead of a file, "
        "or only mention the format while describing something else.\n"
        "- background_run is wanted if the user wants the complete result for the whole "
        "dataset and has not objected to background, asynchronous or detached processing. "
        "People rarely say \"background\"; asking for every row to be exported or analyzed "
        "is enough. It is not_wanted if they forbid background processing, or forbid the file "
        "that the job would produce.\n"
        "Use \"unclear\" when you cannot tell. Judge the latest user message; use the earlier "
        "assistant message only to resolve references such as \"yes, do that\".\n\n"
        "Reply with JSON only:\n"
        "{\"file_export\": \"wanted|not_wanted|unclear\", \"formats\": [\"json\"], "
        "\"background_run\": \"wanted|not_wanted|unclear\", \"reason\": \"short\"}\n"
        "Include only the formats the user wants to receive as files. Omit an action that is "
        "not listed below."
    )
    request_parts = [f"Possibly requested actions:\n{_describe_nominated_actions(nominated)}"]
    prior_text = str(prior_assistant_text or "").strip()
    if prior_text:
        request_parts.append(
            "Previous assistant message (context only):\n"
            f"{prior_text[:REQUEST_INTENT_PRIOR_ASSISTANT_MAX_CHARS]}"
        )
    request_parts.append(
        "Latest user message:\n"
        f"{str(user_message or '')[:REQUEST_INTENT_USER_MESSAGE_MAX_CHARS]}"
    )
    return [
        {"role": "system", "content": instructions},
        {"role": "user", "content": "\n\n".join(request_parts)},
    ]


def _is_parameter_rejection(exc):
    """Return True when the endpoint refused the request options rather than the request."""
    if getattr(exc, "status_code", None) == 400:
        return True
    message = str(exc).lower()
    return any(marker in message for marker in ("max_tokens", "temperature", "unsupported parameter", "unsupported value"))


def assess_request_intent(create_completion, model, user_message, nominated, prior_assistant_text=None):
    """Ask the model which nominated actions the user wants. Returns None when it cannot say."""
    messages = build_request_intent_messages(user_message, nominated, prior_assistant_text)

    def read_text(response):
        return str(response.choices[0].message.content or "").strip()

    try:
        response_text = read_text(create_completion(
            model=model,
            messages=messages,
            max_tokens=REQUEST_INTENT_MODEL_MAX_TOKENS,
            temperature=0,
        ))
    except Exception as exc:
        if not _is_parameter_rejection(exc):
            raise
        response_text = ""
    if not response_text:
        # Reasoning models reject these options or spend the whole token limit before
        # answering. Ask once more with the endpoint's own defaults.
        response_text = read_text(create_completion(model=model, messages=messages))
    payload = _parse_json_object(response_text)
    if not isinstance(payload, dict):
        return None

    verdict = {}
    for action in REQUEST_INTENT_ACTIONS:
        answer = str(payload.get(action) or "").strip().lower()
        verdict[action] = answer if answer in {"wanted", "not_wanted", "unclear"} else "unclear"
    formats = payload.get("formats")
    verdict["formats"] = [
        str(item).strip().lower()
        for item in (formats if isinstance(formats, list) else [])
        if str(item or "").strip()
    ]
    return verdict


def resolve_request_intent(
    user_message,
    *,
    nominate_actions=None,
    settings=None,
    mode=None,
    create_completion=None,
    model=None,
    prior_assistant_text=None,
    suppressed_actions=None,
):
    """Build the per-action decision for one user message.

    ``nominate_actions`` is the keyword detector pass (``nominate_side_effect_actions`` in
    ``functions_tabular_orchestration``). It is passed in so this module does not depend on
    the detector modules, which consult it.

    Order of authority: an explicit user override for this turn, then an explicit opt-out
    in the message, then the model check for actions the keywords nominated. A model check
    that fails, times out or answers "unclear" withholds the action. Returns None when the
    message neither nominates nor rules out anything, so ordinary turns are untouched.
    """
    message_key = request_intent_message_key(user_message)
    if not message_key:
        return None

    check_mode = normalize_request_intent_check_mode(settings, mode=mode)
    suppressed = {action for action in (suppressed_actions or ()) if action in REQUEST_INTENT_ACTIONS}
    opted_out = explicit_side_effect_opt_out(user_message)
    nominated = dict(nominate_actions(user_message) or {}) if callable(nominate_actions) else {}
    if not nominated and not opted_out and not suppressed:
        return None

    permissions = {}
    sources = {}
    undecided = []
    for action in REQUEST_INTENT_ACTIONS:
        if action in suppressed:
            permissions[action], sources[action] = PERMISSION_WITHHELD, SOURCE_USER_OVERRIDE
        elif action in opted_out:
            permissions[action], sources[action] = PERMISSION_WITHHELD, SOURCE_OPT_OUT
        elif action not in nominated:
            permissions[action], sources[action] = PERMISSION_ALLOWED, SOURCE_NOT_NOMINATED
        else:
            permissions[action], sources[action] = PERMISSION_ALLOWED, SOURCE_KEYWORDS
            undecided.append(action)

    verdict = None
    model_status = "not_needed"
    started = time.monotonic()
    if undecided and check_mode != REQUEST_INTENT_MODE_OFF:
        if not callable(create_completion) or not model:
            # No model is available on this path, so the check could not run at all. That is
            # different from a check that ran and failed: keep today's keyword behavior.
            model_status = "unavailable"
            for action in undecided:
                sources[action] = SOURCE_UNCHECKED
        else:
            try:
                # The prior reply is only needed here, so a caller may pass a reader instead.
                prior_text = prior_assistant_text() if callable(prior_assistant_text) else prior_assistant_text
                verdict = assess_request_intent(
                    create_completion,
                    model,
                    user_message,
                    {action: nominated[action] for action in undecided},
                    prior_assistant_text=prior_text,
                )
                model_status = "answered" if verdict else "unparseable"
            except Exception as exc:
                model_status = f"error:{exc.__class__.__name__}"[:80]
                verdict = None

            if check_mode == REQUEST_INTENT_MODE_ACTIVE:
                for action in undecided:
                    answer = (verdict or {}).get(action)
                    if answer == "wanted":
                        sources[action] = SOURCE_MODEL
                    else:
                        permissions[action] = PERMISSION_WITHHELD
                        sources[action] = SOURCE_MODEL if answer == "not_wanted" else SOURCE_FALLBACK

    nominated_formats = list((nominated.get(ACTION_FILE_EXPORT) or {}).get("formats") or [])
    formats = nominated_formats
    if (
        check_mode == REQUEST_INTENT_MODE_ACTIVE
        and sources.get(ACTION_FILE_EXPORT) == SOURCE_MODEL
        and permissions.get(ACTION_FILE_EXPORT) == PERMISSION_ALLOWED
    ):
        confirmed = [item for item in nominated_formats if item in set((verdict or {}).get("formats") or [])]
        formats = confirmed or nominated_formats

    decision = {
        "contract_version": REQUEST_INTENT_CONTRACT_VERSION,
        "message_key": message_key,
        "mode": check_mode,
        "permissions": permissions,
        "sources": sources,
        "nominated": sorted(nominated),
        "formats": formats if permissions.get(ACTION_FILE_EXPORT) == PERMISSION_ALLOWED else [],
        "model_status": model_status,
        "shadow_verdict": (
            {action: (verdict or {}).get(action, "unclear") for action in undecided}
            if check_mode == REQUEST_INTENT_MODE_SHADOW and undecided
            else None
        ),
    }
    log_event(
        "[REQUEST_INTENT] Resolved side-effect permissions for a chat turn",
        {
            "mode": check_mode,
            "nominated": decision["nominated"],
            "permissions": dict(permissions),
            "sources": dict(sources),
            "model_status": model_status,
            "shadow_verdict": decision["shadow_verdict"],
            "elapsed_ms": int((time.monotonic() - started) * 1000),
        },
        level=logging.INFO,
    )
    return decision


def _prune_turn_decisions(now):
    expired = [key for key, (stored_at, _) in _turn_decisions.items() if now - stored_at > _TURN_DECISION_TTL_SECONDS]
    for key in expired:
        _turn_decisions.pop(key, None)
    overflow = len(_turn_decisions) - _TURN_DECISION_MAX_ENTRIES
    if overflow > 0:
        for key, _ in sorted(_turn_decisions.items(), key=lambda item: item[1][0])[:overflow]:
            _turn_decisions.pop(key, None)


def bind_request_intent(decision, conversation_id=None):
    """Attach a decision to the current execution context and to its conversation turn.

    The context variable serves code running in the same context. The turn registry serves
    the action entry points, which can run on another thread of the same request.
    """
    _current_decision.set(decision if isinstance(decision, dict) else None)
    normalized_conversation_id = str(conversation_id or "").strip()
    if not isinstance(decision, dict) or not normalized_conversation_id:
        return decision
    now = time.monotonic()
    with _turn_decisions_lock:
        _prune_turn_decisions(now)
        _turn_decisions[(normalized_conversation_id, decision.get("message_key"))] = (now, decision)
    return decision


def clear_request_intent(conversation_id=None, user_message=None):
    """Drop the decision for the current context and, when identified, for its turn."""
    _current_decision.set(None)
    normalized_conversation_id = str(conversation_id or "").strip()
    message_key = request_intent_message_key(user_message)
    if normalized_conversation_id and message_key:
        with _turn_decisions_lock:
            _turn_decisions.pop((normalized_conversation_id, message_key), None)


def current_request_intent(user_message, conversation_id=None):
    """Return the decision that applies to this exact message, if one was recorded."""
    if _gating_suspended.get():
        return None
    message_key = request_intent_message_key(user_message)
    if not message_key:
        return None
    decision = _current_decision.get()
    if isinstance(decision, dict) and decision.get("message_key") == message_key:
        return decision
    normalized_conversation_id = str(conversation_id or "").strip()
    if not normalized_conversation_id:
        return None
    now = time.monotonic()
    with _turn_decisions_lock:
        stored = _turn_decisions.get((normalized_conversation_id, message_key))
        if not stored:
            return None
        stored_at, stored_decision = stored
        if now - stored_at > _TURN_DECISION_TTL_SECONDS:
            _turn_decisions.pop((normalized_conversation_id, message_key), None)
            return None
        return stored_decision


def action_withheld(user_message, action, conversation_id=None):
    """Return True when the recorded decision for this message withholds the action."""
    decision = current_request_intent(user_message, conversation_id=conversation_id)
    if not decision:
        return False
    return (decision.get("permissions") or {}).get(action) == PERMISSION_WITHHELD


def enforce_action_permitted(user_message, action, conversation_id=None):
    """Stop an action at its entry point when the turn's decision withheld it."""
    if action_withheld(user_message, action, conversation_id=conversation_id):
        log_event(
            "[REQUEST_INTENT] Blocked an action the request did not authorize",
            {"action": action, "conversation_id": str(conversation_id or "").strip()},
            level=logging.WARNING,
        )
        raise RequestIntentWithheldError(action)


def filter_requested_formats(user_message, formats):
    """Apply the recorded file-export decision to keyword-detected formats."""
    decision = current_request_intent(user_message)
    if not decision or not formats:
        return formats
    if (decision.get("permissions") or {}).get(ACTION_FILE_EXPORT) == PERMISSION_WITHHELD:
        return []
    confirmed = decision.get("formats") or []
    if confirmed:
        narrowed = [item for item in formats if item in confirmed]
        return narrowed or formats
    return formats


def _withheld_actions_by_source(decision, sources):
    if not isinstance(decision, dict):
        return []
    permissions = decision.get("permissions") or {}
    decision_sources = decision.get("sources") or {}
    return [
        action
        for action in REQUEST_INTENT_ACTIONS
        if permissions.get(action) == PERMISSION_WITHHELD and decision_sources.get(action) in sources
    ]


def build_request_intent_withheld_notice(decision):
    """Tell the user what was held back when the app, not the user, made that call."""
    withheld = _withheld_actions_by_source(decision, {SOURCE_MODEL, SOURCE_FALLBACK})
    if not withheld:
        return ""
    parts = []
    if ACTION_FILE_EXPORT in withheld:
        parts.append("did not create a file")
    if ACTION_BACKGROUND_RUN in withheld:
        parts.append("did not start background processing of the full dataset")
    notice = f"Note: I {' and '.join(parts)} for this request because it was not clear that you wanted that."
    if ACTION_BACKGROUND_RUN in withheld:
        notice += " This reply covers only what fits in a single chat response."
    notice += " If you do want it, ask for it directly, for example \"create the file for all rows\"."
    return notice


def build_request_intent_system_message(decision):
    """Tell the answering model which actions are off the table for this turn."""
    if not isinstance(decision, dict):
        return None
    permissions = decision.get("permissions") or {}
    file_withheld = permissions.get(ACTION_FILE_EXPORT) == PERMISSION_WITHHELD
    background_withheld = permissions.get(ACTION_BACKGROUND_RUN) == PERMISSION_WITHHELD
    if not file_withheld and not background_withheld:
        return None

    statements = []
    if file_withheld:
        statements.append("No file will be created or attached for this turn.")
    if background_withheld:
        statements.append("No background or follow-up processing will run for this turn.")
    statements.append(
        "Answer directly in this reply. Do not say that a file, export or later result is "
        "coming, and do not ask for permission to start the work: do it now."
    )
    if background_withheld:
        statements.append(
            "If you cannot cover the whole dataset in this reply, say exactly which part you "
            "covered. Never present partial coverage as complete."
        )
    return {"role": "system", "content": " ".join(statements)}


def summarize_request_intent(decision):
    """Return the small, frontend-safe record of a decision for message metadata."""
    if not isinstance(decision, dict):
        return None
    return {
        "contract_version": decision.get("contract_version"),
        "mode": decision.get("mode"),
        "permissions": dict(decision.get("permissions") or {}),
        "sources": dict(decision.get("sources") or {}),
        "nominated": list(decision.get("nominated") or []),
    }

# support_export_contracts.py
"""Bootstrap-free, bounded contracts for administrator support bundles."""

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone


SCHEMA_VERSION = 1
MAX_RECORDS = 100000
MAX_BYTES = 50 * 1024 * 1024
MAX_CONVERSATIONS = 20
MAX_DAYS = 7
AI_TOKEN_BUDGET = 200000
EXPIRY_SECONDS = 24 * 60 * 60
SOURCES = ("telemetry", "activity", "file_processing", "console")
ACTIVE_STATES = ("waiting_for_consent", "queued", "collecting", "redacting", "ai_review")
RUNNING_STATES = ("collecting", "redacting", "ai_review")
IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
PUBLIC_LIMITS = {
    "max_days": MAX_DAYS, "max_conversations": MAX_CONVERSATIONS,
    "max_records": MAX_RECORDS, "max_bytes": MAX_BYTES,
    "ai_input_tokens": AI_TOKEN_BUDGET, "expiry_seconds": EXPIRY_SECONDS,
}


class SupportExportError(Exception):
    """A stable error safe to show without including provider/source content."""

    def __init__(self, code, message, status=400):
        super().__init__(message)
        self.code = code
        self.public_message = message
        self.status = status


def fail(code, message, status=400):
    raise SupportExportError(code, message, status)


def utc_now():
    return datetime.now(timezone.utc)


def timestamp(value, *, stored=False):
    if not isinstance(value, str) or len(value) > 64:
        fail("invalid_time", "Use a valid timestamp with an explicit timezone.")
    if ":" not in value:
        fail("invalid_time", "A calendar date alone is not a reliable diagnostic timestamp.")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        fail("invalid_time", "Use a valid timestamp with an explicit timezone.")
    if result.tzinfo is None:
        if not stored:
            fail("invalid_time", "Use a valid timestamp with an explicit timezone.")
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def iso(value):
    return value.astimezone(timezone.utc).isoformat()


def identifier(value):
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        fail("invalid_identifier", "A valid user or conversation ID is required.")
    return value


def digest(value):
    encoded = json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def identity_hash(value):
    return hashlib.sha256(identifier(value).encode("utf-8")).hexdigest()


def normalize_configuration(value):
    allowed = {"cloud", "app_resource_id", "site_resource_id"}
    if not isinstance(value, dict) or set(value) - allowed:
        fail("invalid_configuration", "Unsupported support-export configuration.")
    result = {key: value.get(key, "") for key in allowed}
    if result["cloud"] not in ("public", "usgovernment"):
        fail("invalid_cloud", "Choose Azure Commercial or Azure US Government.")
    if any(not isinstance(item, str) or len(item) > 512 for item in result.values()):
        fail("invalid_configuration", "Invalid support-export configuration.")
    prefix = r"/subscriptions/[0-9a-fA-F-]{36}/resourceGroups/[A-Za-z0-9_.()-]+/providers/"
    for key, resource in (
        ("app_resource_id", r"Microsoft\.Insights/components/"),
        ("site_resource_id", r"Microsoft\.Web/sites/"),
    ):
        result[key] = result[key].strip()
        if result[key] and not re.fullmatch(prefix + resource + r"[A-Za-z0-9_.()-]+", result[key], re.I):
            fail("invalid_resource", "Use a complete Application Insights or App Service resource ID.")
    return result


def normalize_request(value, now=None):
    allowed = {
        "all_users", "user_id", "conversation_ids", "mode", "start", "end",
        "before_minutes", "after_minutes", "sources", "include_system_context",
        "include_transcripts", "privacy", "purpose",
    }
    if not isinstance(value, dict) or set(value) - allowed:
        fail("invalid_request", "Unsupported support-export request.")
    now = now or utc_now()
    result = {}
    for key in ("all_users", "include_system_context", "include_transcripts"):
        item = value.get(key, False)
        if type(item) is not bool:
            fail("invalid_request", "Export switches must be boolean values.")
        result[key] = item
    result["user_id"] = "" if result["all_users"] else identifier(value.get("user_id"))
    conversations = value.get("conversation_ids", [])
    if not isinstance(conversations, list) or len(conversations) > MAX_CONVERSATIONS:
        fail("conversation_limit", "Select at most 20 conversations.")
    result["conversation_ids"] = sorted({identifier(item) for item in conversations})
    result["mode"] = value.get("mode", "time")
    if result["mode"] not in ("time", "conversations"):
        fail("invalid_mode", "Choose time-based or conversation-based collection.")
    if result["all_users"] and (conversations or result["include_transcripts"]):
        fail("invalid_scope", "Select one user before selecting conversations or transcripts.")
    if (result["mode"] == "conversations" or result["include_transcripts"]) and not conversations:
        fail("conversation_required", "Select at least one conversation.")
    for key in ("before_minutes", "after_minutes"):
        item = value.get(key, 15)
        if type(item) is not int or not 0 <= item <= 1440:
            fail("invalid_margin", "Before/after margins must be whole minutes from 0 to 1440.")
        result[key] = item
    result["start"] = result["end"] = None
    if result["mode"] == "time" or value.get("start") or value.get("end"):
        start = timestamp(value.get("start") or iso(now - timedelta(hours=1)))
        end = timestamp(value.get("end") or iso(now))
        if end > now + timedelta(minutes=1) or start >= end or end - start > timedelta(days=MAX_DAYS):
            fail("invalid_range", "Choose a past time range of at most 7 days, with start before end.")
        result.update(start=iso(start), end=iso(min(end, now)))
    selected_sources = value.get("sources", ["telemetry", "activity"])
    if (
        not isinstance(selected_sources, list) or not selected_sources
        or any(item not in SOURCES for item in selected_sources)
    ):
        fail("invalid_sources", "Select at least one available log source.")
    result["sources"] = sorted(set(selected_sources))
    if "console" in selected_sources and not (result["all_users"] or result["include_system_context"]):
        fail("console_context_required", "Console logs require the nearby system context option for one-user exports.")
    result["privacy"] = value.get("privacy", "deterministic")
    if result["privacy"] not in ("deterministic", "ai"):
        fail("invalid_privacy", "Choose deterministic or deterministic plus AI privacy checking.")
    purpose = value.get("purpose", "Troubleshoot a SimpleChat issue.")
    if not isinstance(purpose, str) or not purpose.strip() or len(purpose) > 500:
        fail("invalid_purpose", "Provide a support purpose of at most 500 characters.")
    result["purpose"] = purpose.strip()
    return result


def resolve_intervals(plan, conversations, now=None):
    cutoff = now or utc_now()
    if plan["mode"] == "time":
        return [[plan["start"], plan["end"]]]
    windows = []
    for conversation in conversations:
        first, last = conversation.get("first_activity"), conversation.get("last_activity")
        if not first or not last:
            fail("conversation_time_unknown", "A conversation has no reliable activity times. Use a time-based export.")
        start = timestamp(first, stored=True) - timedelta(minutes=plan["before_minutes"])
        end = min(cutoff, timestamp(last, stored=True) + timedelta(minutes=plan["after_minutes"], seconds=1))
        if plan["start"]:
            start = max(start, timestamp(plan["start"]))
            end = min(end, timestamp(plan["end"]))
        if start < end:
            windows.append((start, end))
    if not windows:
        fail("empty_intervals", "The selected conversations do not overlap the chosen time range.")
    windows.sort()
    if max(end for _, end in windows) - windows[0][0] > timedelta(days=MAX_DAYS):
        fail("range_limit", "Conversation windows span more than 7 days. Narrow the explicit time range.")
    merged = []
    for start, end in windows:
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(end, merged[-1][1])
        else:
            merged.append([start, end])
    return [[iso(start), iso(end)] for start, end in merged]


def within_intervals(value, intervals):
    instant = timestamp(value, stored=True)
    return any(timestamp(start) <= instant < timestamp(end) for start, end in intervals)


def check_size(records, byte_count):
    if records > MAX_RECORDS or byte_count > MAX_BYTES:
        fail("bundle_limit", "The bundle exceeds 100,000 records or 50 MiB. Narrow its scope.", 413)

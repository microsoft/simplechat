# functions_m365_approvals.py
"""Subject-owned Microsoft 365 decisions, preferences, and grant audit.

Dependencies are resolved at operation time, not while config is bootstrapping.
The approval container keeps its /group_id partition; that field is a physical
partition only and never confers group or administrator authorization.
"""

import copy
import hashlib
import json
import logging
import uuid
from collections.abc import Mapping
from datetime import datetime, time, timedelta, timezone
from typing import Any, Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from azure.core import MatchConditions
from azure.cosmos import exceptions as cosmos_exceptions

from functions_m365_operations import (
    M365_ACTION_DEFINITIONS,
    M365_FILE_SOURCES,
    M365_SHARING_DURATIONS,
)

TYPE_SOURCE_SHARING = "m365_source_sharing"
TYPE_EXTENDED_ANALYSIS = "m365_extended_analysis"
TYPE_WORKFLOW_RUN_AS = "m365_workflow_run_as"
M365_APPROVAL_TYPES = frozenset({
    TYPE_SOURCE_SHARING, TYPE_EXTENDED_ANALYSIS, TYPE_WORKFLOW_RUN_AS,
})
M365_SOURCES = tuple(definition["source"] for definition in M365_ACTION_DEFINITIONS.values())
SHARING_DURATIONS = M365_SHARING_DURATIONS
PENDING_APPROVAL_DAYS = 3
POLICY_RECORD_ID = "m365-user-policy"
MAX_PAGE_SIZE = 100
UTC = timezone.utc


class M365PolicyError(Exception):
    """A stable, non-content-bearing policy failure."""

    def __init__(self, code: str, message: str, **details):
        super().__init__(message)
        self.code = code
        self.payload = {"error": code, "message": message, **details}


class M365ApprovalRequired(M365PolicyError):
    def __init__(self, approval):
        safe = sanitize_m365_approval(approval)
        super().__init__(
            "m365_approval_required",
            "Your Microsoft 365 approval is required before this work can continue.",
            approval_id=safe["id"],
            request_type=safe["request_type"],
            subject_user_id=safe["subject_user_id"],
            resume_key=safe["resume_key"],
            execution_status=safe["execution_status"],
            approval=safe,
        )
        self.approval_id = safe["id"]
        self.request_type = safe["request_type"]


class M365SourceDenied(M365PolicyError):
    def __init__(self, source, approval_id=None):
        super().__init__(
            "m365_source_declined",
            "Continue without this Microsoft 365 source.",
            source=source,
            approval_id=approval_id,
        )


class M365ApprovalConflict(M365PolicyError):
    def __init__(self):
        super().__init__(
            "m365_approval_conflict",
            "This Microsoft 365 request changed. Refresh it before deciding.",
        )


def utc_now():
    return datetime.now(UTC)


def utc_datetime(value):
    parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
    if not isinstance(parsed, datetime) or parsed.tzinfo is None:
        raise ValueError("An aware timestamp is required.")
    return parsed.astimezone(UTC)


def validate_timezone(value):
    if not isinstance(value, str) or not value or len(value) > 100:
        raise ValueError("A confirmed IANA timezone is required.")
    try:
        return ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError("A valid IANA timezone is required.") from exc


def local_midnight_expiry(acknowledged_at, timezone_name):
    """Return the first next local midnight, including DST offset changes."""
    acknowledged_at = utc_datetime(acknowledged_at)
    zone = validate_timezone(timezone_name)
    next_date = acknowledged_at.astimezone(zone).date() + timedelta(days=1)
    midnight = datetime.combine(next_date, time.min, tzinfo=zone)
    return midnight.astimezone(UTC)


def normalize_sharing_policy(value=None):
    if isinstance(value, Mapping):
        value = value.get("maximum_sharing_acknowledgement", "always")
    if value is None:
        value = "always"
    if value not in SHARING_DURATIONS:
        raise ValueError("Invalid Microsoft 365 sharing policy.")
    return value


def strictest_sharing_policy(*values):
    normalized = [normalize_sharing_policy(value) for value in values]
    return min(normalized or ["always"], key=SHARING_DURATIONS.index)


def _json_value(value):
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise ValueError("Microsoft 365 context must contain JSON-compatible values.")


def material_fingerprint(value):
    encoded = json.dumps(
        _json_value(value), sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_workflow_review(review):
    """Accept only the owner's non-secret, human-readable consent projection."""
    required = {"instructions", "capabilities", "runtime_inputs", "triggers", "destinations"}
    if not isinstance(review, dict) or set(review) != required:
        raise ValueError("A complete workflow consent review is required.")
    if any(not isinstance(value, str) or not value.strip() for value in review.values()):
        raise ValueError("Workflow consent review sections must be bounded, nonempty text.")
    if len(json.dumps(review, ensure_ascii=True).encode("utf-8")) > 1_500_000:
        raise ValueError("The complete workflow consent review exceeds 1.5 MB. Split this workflow before requesting consent.")
    return copy.deepcopy(review)


def _identifier(value):
    if (
        not isinstance(value, str) or not value or len(value) > 256
        or any(ord(char) < 32 for char in value)
    ):
        raise ValueError("A valid Microsoft 365 context identifier is required.")
    return value


def _source(value, file_only=False):
    if not isinstance(value, str) or value not in (M365_FILE_SOURCES if file_only else M365_SOURCES):
        raise ValueError("Invalid Microsoft 365 source.")
    return value


def approval_context(context):
    result = {
        name: getattr(context, name, None)
        for name in (
            "actor_user_id", "data_user_id", "tenant_id", "conversation_id",
            "request_id", "workflow_id", "run_id", "step_id", "agent_id",
            "audience_version", "workflow_fingerprint", "connection_id", "binding_id",
            "group_id",
        )
    }
    for name in ("actor_user_id", "data_user_id", "tenant_id"):
        _identifier(result[name])
    for value in result.values():
        if value is not None:
            _identifier(value)
    result["shared"] = bool(context.shared)
    result["action_ids"] = sorted(_identifier(action_id) for action_id in context.action_configs)[:64]
    result["action_count"] = len(context.action_configs)
    result["action_fingerprint"] = material_fingerprint(context.action_configs)
    return result


def request_scope_fingerprint(context):
    snapshot = approval_context(context)
    _identifier(snapshot["request_id"])
    # A grant covers one logical request, not an individual tool within it.
    snapshot.pop("step_id", None)
    return material_fingerprint(snapshot)


def logical_request_fingerprint(context):
    snapshot = approval_context(context)
    _identifier(snapshot["request_id"])
    return material_fingerprint({
        name: snapshot[name] for name in (
            "actor_user_id", "data_user_id", "tenant_id", "conversation_id",
            "request_id", "workflow_id", "run_id",
        )
    })


def is_m365_approval(approval):
    return isinstance(approval, dict) and approval.get("request_type") in M365_APPROVAL_TYPES


def is_m365_approval_subject(approval, user_id):
    return bool(
        user_id
        and is_m365_approval(approval)
        and approval.get("approval_scope") == "user"
        and approval.get("subject_user_id") == user_id
        and approval.get("group_id") == user_id
    )


def sanitize_m365_approval(approval):
    fields = (
        "id", "group_id", "request_type", "approval_scope", "subject_user_id",
        "requester_id", "status", "created_at", "expires_at", "approved_at",
        "resolved_at",
        "approved_by_id", "resume_key", "execution_status", "continuation_status",
        "context", "sources", "decisions", "analysis_choice", "proposal", "binding",
        "decision_event_id", "terminal_reason", "notification_status",
    )
    result = {key: copy.deepcopy(approval[key]) for key in fields if key in approval}
    result["group_name"] = "Microsoft 365"
    result["reason"] = {
        TYPE_SOURCE_SHARING: (
            "Allow answers and retained source evidence to be published to conversation "
            "participants. Revocation does not remove already-published history."
        ),
        TYPE_EXTENDED_ANALYSIS: (
            "Choose deeper staged file analysis or a faster answer with disclosed limits."
        ),
        TYPE_WORKFLOW_RUN_AS: (
            "Allow this workflow revision to use your connected Microsoft 365 account. "
            "Connecting your account alone does not authorize a workflow."
        ),
    }[approval["request_type"]]
    result["can_approve"] = approval.get("status") == "pending"
    result["can_deny"] = result["can_approve"]
    return result


def effective_sharing_grant(decision, ceiling, context, source_generation, now=None):
    """Evaluate original acknowledgement time; never renew a short grant."""
    now = utc_datetime(now or utc_now())
    if decision.get("duration") not in SHARING_DURATIONS:
        return None
    if decision.get("generation") != source_generation:
        return None
    effective = strictest_sharing_policy(decision["duration"], ceiling)
    acknowledged_at = utc_datetime(decision["acknowledged_at"])
    if acknowledged_at > now:
        return None
    expires_at = None
    if effective == "request":
        if decision.get("request_scope") != request_scope_fingerprint(context):
            return None
    elif effective == "today":
        expires_at = utc_datetime(decision["day_expires_at"])
        if now >= expires_at:
            return None
    original_expiry = decision.get("expires_at")
    if original_expiry:
        original_expiry = utc_datetime(original_expiry)
        if now >= original_expiry:
            return None
        expires_at = min(expires_at, original_expiry) if expires_at else original_expiry
    return {
        "effective_duration": effective,
        "acknowledged_at": acknowledged_at.isoformat(),
        "expires_at": expires_at.isoformat() if expires_at else None,
        "timezone": decision["timezone"],
        "generation": source_generation,
    }


def _default_container():
    # config owns cloud clients; importing it only after an actual operation
    # avoids making this lower-level policy module a bootstrap dependency.
    from config import cosmos_approvals_container
    return cosmos_approvals_container


def _default_notification(approval):
    # Notification initialization depends on config and group/settings modules.
    from functions_notifications import create_m365_approval_notification
    return create_m365_approval_notification(approval)


def _log(message, extra, level=logging.WARNING):
    # Logging has a settings/bootstrap dependency and is deliberately deferred.
    from functions_appinsights import log_event
    log_event(f"[APPROVALS] {message}", extra=extra, level=level)


class M365ApprovalService:
    """Conditional decisions and append-only audit in a subject partition."""

    def __init__(
        self, container_factory: Callable = _default_container,
        notification_sender: Callable = _default_notification,
        decision_validator: Callable | None = None,
        clock: Callable = utc_now,
    ):
        self.container_factory = container_factory
        self.notification_sender = notification_sender
        self.decision_validator = decision_validator
        self.clock = clock

    @property
    def container(self):
        return self.container_factory()

    def _read(self, item_id, subject_user_id):
        try:
            return self.container.read_item(item=item_id, partition_key=subject_user_id)
        except cosmos_exceptions.CosmosResourceNotFoundError:
            return None

    def _create_once(self, document):
        try:
            return self.container.create_item(body=document)
        except cosmos_exceptions.CosmosResourceExistsError:
            existing = self._read(document["id"], document["group_id"])
            if existing is None:
                raise M365ApprovalConflict()
            return existing

    def _state(self, subject_user_id):
        _identifier(subject_user_id)
        state = self._read(POLICY_RECORD_ID, subject_user_id)
        if state is not None:
            return state
        return self._create_once({
            "id": POLICY_RECORD_ID,
            "group_id": subject_user_id,
            "record_kind": "m365_user_policy",
            "subject_user_id": subject_user_id,
            "timezone": None,
            "sources": {source: "ask" for source in M365_SOURCES},
            "extended_analysis": {source: "ask" for source in M365_FILE_SOURCES},
            "source_generations": {source: 0 for source in M365_SOURCES},
            "analysis_generations": {source: 0 for source in M365_FILE_SOURCES},
            "analysis_preference_events": {},
            "ttl": -1,
        })

    def _audit_document(self, subject, event_type, event_id, **safe_fields):
        return {
            "id": event_id,
            "group_id": subject,
            "record_kind": "m365_audit",
            "subject_user_id": subject,
            "event_type": event_type,
            "created_at": self.clock().isoformat(),
            "ttl": -1,
            **safe_fields,
        }

    def _batch(self, subject, replacements, event):
        operations = [
            ("replace", (previous["id"], updated), {"if_match_etag": previous["_etag"]})
            for previous, updated in replacements
        ]
        operations.append(("create", (event,)))
        try:
            self.container.execute_item_batch(
                batch_operations=operations, partition_key=subject,
            )
        except (
            cosmos_exceptions.CosmosBatchOperationError,
            cosmos_exceptions.CosmosHttpResponseError,
        ) as exc:
            if exc.status_code in (409, 412, 424):
                raise M365ApprovalConflict() from exc
            raise

    def _notify(self, approval):
        if approval.get("notification_status") == "delivered":
            return approval
        notification = self.notification_sender(sanitize_m365_approval(approval))
        if notification is None:
            _log("Microsoft 365 notification remains pending", {"approval_id": approval["id"]})
            return approval
        updated = {**approval, "notification_status": "delivered"}
        try:
            return self.container.replace_item(
                item=approval["id"], body=updated,
                partition_key=approval["group_id"], etag=approval["_etag"],
                match_condition=MatchConditions.IfNotModified,
            )
        except cosmos_exceptions.CosmosHttpResponseError as exc:
            if exc.status_code != 412:
                raise
            return self._read(approval["id"], approval["group_id"])

    def get_preferences(self, subject_user_id):
        state = self._state(subject_user_id)
        return {
            "timezone": state.get("timezone"),
            "sources": copy.deepcopy(state["sources"]),
            "extended_analysis": copy.deepcopy(state["extended_analysis"]),
        }

    def update_preferences(self, subject_user_id, changes):
        if not isinstance(changes, dict) or set(changes) - {"timezone", "sources", "extended_analysis"}:
            raise ValueError("Invalid Microsoft 365 preferences.")
        state = self._state(subject_user_id)
        updated = copy.deepcopy(state)
        event_id = f"m365-audit-{uuid.uuid4()}"
        changed = {}
        if "timezone" in changes:
            confirmed_timezone = changes["timezone"]
            if confirmed_timezone is not None:
                confirmed_timezone = validate_timezone(confirmed_timezone).key
            if state.get("timezone") != confirmed_timezone:
                updated["timezone"] = confirmed_timezone
                changed["timezone"] = confirmed_timezone
        for area, choices, sources in (
            ("sources", ("ask", *SHARING_DURATIONS), M365_SOURCES),
            ("extended_analysis", ("ask", "always", "fast"), M365_FILE_SOURCES),
        ):
            area_changes = changes.get(area, {})
            if not isinstance(area_changes, dict) or set(area_changes) - set(sources):
                raise ValueError("Invalid Microsoft 365 preferences.")
            for source, choice in area_changes.items():
                if choice not in choices:
                    raise ValueError("Invalid Microsoft 365 preference choice.")
                if updated[area][source] == choice:
                    continue
                updated[area][source] = choice
                generation_key = "source_generations" if area == "sources" else "analysis_generations"
                updated[generation_key][source] += 1
                changed.setdefault(area, {})[source] = choice
                if area == "extended_analysis":
                    updated["analysis_preference_events"][source] = event_id
        if not changed:
            return self.get_preferences(subject_user_id)
        event = self._audit_document(
            subject_user_id, "preferences_changed", event_id, preferences=changed,
        )
        self._batch(subject_user_id, [(state, updated)], event)
        return self.get_preferences(subject_user_id)

    def revoke_source(self, subject_user_id, source):
        source = _source(source)
        state = self._state(subject_user_id)
        updated = copy.deepcopy(state)
        updated["sources"][source] = "ask"
        updated["source_generations"][source] += 1
        event = self._audit_document(
            subject_user_id, "source_revoked", f"m365-audit-{uuid.uuid4()}", source=source,
            generation=updated["source_generations"][source],
        )
        self._batch(subject_user_id, [(state, updated)], event)
        return {"source": source, "revoked": True, "published_snapshots_retained": True}

    def _records(self, subject, request_type, **filters):
        clauses = ["c.record_kind = 'm365_approval'", "c.request_type = @request_type"]
        parameters = [{"name": "@request_type", "value": request_type}]
        for key, value in filters.items():
            if key not in {"tenant_id", "request_scope", "logical_request", "status"}:
                raise ValueError("Invalid approval query.")
            clauses.append(f"c.{key} = @{key}")
            parameters.append({"name": f"@{key}", "value": value})
        return self.container.query_items(
            query=f"SELECT * FROM c WHERE {' AND '.join(clauses)} ORDER BY c.created_at DESC",
            parameters=parameters, partition_key=subject, max_item_count=MAX_PAGE_SIZE,
        )

    def _create_request(self, context, request_type, sources, state, **details):
        snapshot = approval_context(context)
        scope = request_scope_fingerprint(context)
        source_snapshot = {
            source: {
                "maximum_sharing_acknowledgement": normalize_sharing_policy(policy),
                "allowed_durations": list(
                    SHARING_DURATIONS[:SHARING_DURATIONS.index(normalize_sharing_policy(policy)) + 1]
                ),
                "generation": state["source_generations"][source],
            }
            for source, policy in sources.items()
        }
        if request_type == TYPE_WORKFLOW_RUN_AS:
            key = material_fingerprint({
                "request_type": request_type, "subject_user_id": context.data_user_id,
                "tenant_id": context.tenant_id, "binding": details["binding"],
            })
        else:
            key = material_fingerprint({
                "request_type": request_type, "scope": scope,
                "sources": source_snapshot, "details": details,
            })
        while True:
            existing = self._read(f"m365-{key}", context.data_user_id)
            if existing is None or existing["status"] == "pending":
                break
            if request_type == TYPE_WORKFLOW_RUN_AS and existing["status"] == "approved":
                return self._notify(existing)
            key = material_fingerprint([key, "renewal", existing.get("decision_event_id"), existing["status"]])
        now = self.clock()
        approval = self._create_once({
            "id": f"m365-{key}",
            "group_id": context.data_user_id,
            "record_kind": "m365_approval",
            "request_type": request_type,
            "approval_scope": "user",
            "subject_user_id": context.data_user_id,
            "requester_id": context.actor_user_id,
            "tenant_id": context.tenant_id,
            "status": "pending",
            "created_at": now.isoformat(),
            "expires_at": (now + timedelta(days=PENDING_APPROVAL_DAYS)).isoformat(),
            "ttl": -1,
            "context": snapshot,
            "request_scope": scope,
            "logical_request": logical_request_fingerprint(context),
            "sources": source_snapshot,
            "resume_key": key,
            "execution_status": "awaiting_approval",
            "continuation_status": "waiting",
            "notification_status": "pending",
            **details,
        })
        return self._notify(approval)

    def get_approval(self, approval_id, subject_user_id):
        approval = self._read(_identifier(approval_id), _identifier(subject_user_id))
        if not is_m365_approval_subject(approval, subject_user_id):
            raise LookupError("Microsoft 365 approval not found.")
        if approval["status"] == "pending" and utc_datetime(approval["expires_at"]) <= self.clock():
            approval = self.expire(approval)
        return approval

    def _transition(self, approval, status, *, state=None, decisions=None, **fields):
        now = self.clock().isoformat()
        event_id = f"m365-audit-{approval['id']}-{status}"
        updated = {
            **approval, "status": status, "resolved_at": now,
            "execution_status": "queued", "continuation_status": "pending",
            "continuation_lease": None,
            "notification_status": "pending", "decision_event_id": event_id,
            **fields,
        }
        if status == "approved":
            updated["approved_at"] = now
        if decisions is not None:
            updated["decisions"] = decisions
        event = self._audit_document(
            approval["subject_user_id"], status, event_id,
            approval_id=approval["id"], request_type=approval["request_type"],
            context=approval["context"], decisions=decisions,
            analysis_choice=fields.get("analysis_choice"),
        )
        replacements = [(approval, updated)]
        if state is not None:
            replacements.append(state)
        self._batch(approval["subject_user_id"], replacements, event)
        return self._notify(self._read(approval["id"], approval["group_id"]))

    def expire(self, approval):
        if approval["status"] != "pending" or utc_datetime(approval["expires_at"]) > self.clock():
            return approval
        try:
            return self._transition(approval, "expired", terminal_reason="approval_expired")
        except M365ApprovalConflict:
            return self._read(approval["id"], approval["group_id"])

    def decide(self, approval_id, subject_user_id, decision):
        approval = self.get_approval(approval_id, subject_user_id)
        if not isinstance(decision, dict):
            raise ValueError("Invalid Microsoft 365 decision.")
        if approval["status"] != "pending":
            if approval.get("decision_request") == decision:
                return {**sanitize_m365_approval(approval), "transition_applied": False}
            raise M365ApprovalConflict()
        if self.decision_validator is None:
            raise M365PolicyError(
                "m365_approval_validation_unavailable",
                "The current conversation or workflow must be revalidated before this decision.",
            )
        if self.decision_validator(approval) is not True:
            self._transition(approval, "invalidated", terminal_reason="context_changed")
            raise M365ApprovalConflict()
        state = self._state(subject_user_id)
        updated_state = copy.deepcopy(state)
        request_type = approval["request_type"]
        allowed = {"decisions"} if request_type == TYPE_SOURCE_SHARING else {"choice"}
        if set(decision) != allowed:
            raise ValueError("Invalid Microsoft 365 decision fields.")
        fields = {"approved_by_id": subject_user_id, "decision_request": copy.deepcopy(decision)}
        decisions = None
        if request_type == TYPE_SOURCE_SHARING:
            choices = decision["decisions"]
            if not isinstance(choices, dict) or set(choices) != set(approval["sources"]):
                raise ValueError("Choose an outcome for every requested Microsoft 365 source.")
            decisions = {}
            for source, choice in choices.items():
                expected = approval["sources"][source]
                if expected["generation"] != state["source_generations"][source]:
                    self._transition(
                        approval, "invalidated", state=(state, copy.deepcopy(state)),
                        terminal_reason="source_grant_revoked",
                    )
                    raise M365ApprovalConflict()
                if not isinstance(choice, dict) or set(choice) - {"duration", "timezone"}:
                    raise ValueError("Invalid Microsoft 365 sharing decision.")
                duration = choice.get("duration")
                if duration == "no":
                    decisions[source] = {"duration": "no", "generation": expected["generation"]}
                    continue
                if duration not in expected["allowed_durations"]:
                    raise ValueError("Sharing duration exceeds this action's allowed maximum.")
                timezone_name = choice.get("timezone")
                now = self.clock()
                day_expiry = local_midnight_expiry(now, timezone_name).isoformat()
                decisions[source] = {
                    "duration": duration, "timezone": timezone_name,
                    "acknowledged_at": now.isoformat(),
                    "day_expires_at": day_expiry,
                    "expires_at": day_expiry if duration == "today" else None,
                    "generation": expected["generation"],
                    "request_scope": approval["request_scope"],
                }
                saved_preference = state["sources"][source]
                if duration != "request" and (
                    saved_preference == "ask"
                    or SHARING_DURATIONS.index(duration) >= SHARING_DURATIONS.index(saved_preference)
                ):
                    updated_state["sources"][source] = duration
            status = "approved" if any(value["duration"] != "no" for value in decisions.values()) else "denied"
        elif request_type == TYPE_EXTENDED_ANALYSIS:
            choice = decision["choice"]
            if choice not in ("request", "always", "fast"):
                raise ValueError("Invalid extended analysis choice.")
            source = next(iter(approval["sources"]))
            if approval["analysis_generation"] != state["analysis_generations"][source]:
                self._transition(
                    approval, "invalidated", state=(state, copy.deepcopy(state)),
                    terminal_reason="analysis_preference_changed",
                )
                raise M365ApprovalConflict()
            status = "denied" if choice == "fast" else "approved"
            fields["analysis_choice"] = choice
            if choice == "always":
                updated_state["extended_analysis"][source] = "always"
                updated_state["analysis_preference_events"][source] = f"m365-audit-{approval_id}-{status}"
        else:
            choice = decision["choice"]
            if choice not in ("approve", "deny"):
                raise ValueError("Invalid workflow Run as decision.")
            status = "approved" if choice == "approve" else "denied"
        try:
            updated = self._transition(
                approval, status, state=(state, updated_state), decisions=decisions, **fields,
            )
        except M365ApprovalConflict:
            current = self.get_approval(approval_id, subject_user_id)
            if current.get("decision_request") == decision:
                return {**sanitize_m365_approval(current), "transition_applied": False}
            raise
        return {**sanitize_m365_approval(updated), "transition_applied": True}

    def _grant_use(self, context, source, approval, effective):
        scope = request_scope_fingerprint(context)
        event_id = f"m365-use-{material_fingerprint([scope, source, approval['id'], effective])}"
        event = self._audit_document(
            context.data_user_id, "grant_used", event_id,
            approval_id=approval["id"], decision_event_id=approval.get("decision_event_id"),
            source=source, context=approval_context(context), effective_grant=effective,
        )
        state = self._state(context.data_user_id)
        if state["source_generations"][source] != effective["generation"]:
            raise M365ApprovalConflict()
        if self._read(event_id, context.data_user_id) is None:
            try:
                self._batch(context.data_user_id, [(state, copy.deepcopy(state))], event)
            except M365ApprovalConflict:
                current = self._state(context.data_user_id)
                if (
                    current["source_generations"][source] != effective["generation"]
                    or self._read(event_id, context.data_user_id) is None
                ):
                    raise
        return {
            "source": source, "approval_id": approval["id"], "audit_id": event_id,
            "decision_event_id": approval.get("decision_event_id"), **effective,
        }

    def authorize_sources(self, context, sources):
        if not isinstance(sources, Mapping) or not sources:
            raise ValueError("At least one Microsoft 365 source is required.")
        sources = {_source(source): normalize_sharing_policy(policy) for source, policy in sources.items()}
        if not context.shared:
            return {source: {"source": source, "sharing_required": False} for source in sources}
        if not context.conversation_id or not context.audience_version:
            raise M365PolicyError("m365_context_required", "An authoritative conversation audience is required.")
        state = self._state(context.data_user_id)
        scope = request_scope_fingerprint(context)
        granted = {}
        pending = []
        for approval in self._records(
            context.data_user_id, TYPE_SOURCE_SHARING,
            tenant_id=context.tenant_id, logical_request=logical_request_fingerprint(context),
        ):
            if approval["status"] == "pending":
                approval = self.expire(approval)
            if approval["status"] in ("denied", "expired"):
                for source in set(sources) & set(approval["sources"]):
                    raise M365SourceDenied(source, approval["id"])
            for source, choice in approval.get("decisions", {}).items():
                if source in sources and choice.get("duration") == "no":
                    raise M365SourceDenied(source, approval["id"])
            if (
                approval["status"] == "invalidated"
                and approval["request_scope"] == scope
                and approval.get("terminal_reason") == "context_changed"
            ):
                raise M365PolicyError(
                    "m365_context_changed",
                    "The conversation or workflow changed. Revalidate this request before continuing.",
                )
            if approval["status"] == "pending" and approval["request_scope"] == scope:
                pending.append(approval)
        for source, ceiling in sources.items():
            for approval in self._records(
                context.data_user_id, TYPE_SOURCE_SHARING,
                tenant_id=context.tenant_id, status="approved",
            ):
                choice = approval.get("decisions", {}).get(source)
                if not choice:
                    continue
                effective = effective_sharing_grant(
                    choice, ceiling, context, state["source_generations"][source], self.clock(),
                )
                if effective:
                    granted[source] = self._grant_use(context, source, approval, effective)
                    break
        missing = {source: policy for source, policy in sources.items() if source not in granted}
        if missing:
            for approval in pending:
                if all(
                    source in approval["sources"]
                    and approval["sources"][source]["generation"] == state["source_generations"][source]
                    and approval["sources"][source]["maximum_sharing_acknowledgement"] == policy
                    for source, policy in missing.items()
                ):
                    raise M365ApprovalRequired(approval)
            raise M365ApprovalRequired(self._create_request(
                context, TYPE_SOURCE_SHARING, missing, state,
            ))
        return granted

    def authorize_extended_analysis(self, context, source, proposal=None):
        source = _source(source, file_only=True)
        proposal = {} if proposal is None else proposal
        if (
            not isinstance(proposal, dict)
            or set(proposal) - {"file_count", "download_count", "total_bytes", "context_tokens"}
            or any(type(value) is not int or value < 0 for value in proposal.values())
        ):
            raise ValueError("Extended analysis requires safe, nonnegative coverage counts.")
        state = self._state(context.data_user_id)
        preference = state["extended_analysis"][source]
        if preference in ("always", "fast"):
            event_id = state["analysis_preference_events"].get(source)
            if not event_id:
                raise M365PolicyError("m365_preference_invalid", "Save your analysis preference again.")
            use_id = f"m365-analysis-use-{material_fingerprint([request_scope_fingerprint(context), source, event_id])}"
            self._create_once(self._audit_document(
                context.data_user_id, "analysis_preference_used", use_id,
                context=approval_context(context), source=source,
                preference_event_id=event_id, choice=preference,
            ))
            return {"mode": "fast" if preference == "fast" else "extended", "audit_id": use_id}
        scope = request_scope_fingerprint(context)
        for approval in self._records(
            context.data_user_id, TYPE_EXTENDED_ANALYSIS,
            tenant_id=context.tenant_id, request_scope=scope,
        ):
            if source not in approval["sources"] or approval["analysis_generation"] != state["analysis_generations"][source]:
                continue
            approval = self.expire(approval)
            if approval["status"] in ("approved", "denied", "expired"):
                return {
                    "mode": "extended" if approval["status"] == "approved" else "fast",
                    "approval_id": approval["id"], "audit_id": approval["decision_event_id"],
                }
            if approval["status"] == "pending":
                raise M365ApprovalRequired(approval)
        raise M365ApprovalRequired(self._create_request(
            context, TYPE_EXTENDED_ANALYSIS, {source: "always"}, state,
            proposal=proposal, analysis_generation=state["analysis_generations"][source],
        ))

    def create_workflow_binding(self, context, sources, connection, *, review=None):
        review = validate_workflow_review(review)
        if not context.workflow_id or not context.workflow_fingerprint or not context.connection_id:
            raise ValueError("An explicit workflow revision and connection are required.")
        if (
            connection.get("id") != context.connection_id
            or connection.get("user_id") != context.data_user_id
            or connection.get("tenant_id") != context.tenant_id
            or connection.get("status") != "connected"
        ):
            raise M365PolicyError("m365_connection_required", "Connect your own Microsoft 365 account first.")
        sources = sorted({_source(source) for source in sources})
        if not sources or not set(sources).issubset(connection["sources"]):
            raise ValueError("The connection must authorize the selected workflow sources.")
        state = self._state(context.data_user_id)
        return self._create_request(
            context, TYPE_WORKFLOW_RUN_AS, {source: "always" for source in sources}, state,
            binding={
                "workflow_id": context.workflow_id,
                "workflow_fingerprint": context.workflow_fingerprint,
                "connection_id": connection["id"],
                "connection_generation": connection["generation"],
                "sources": sources,
                "conversation_id": context.conversation_id,
                "audience_version": context.audience_version,
                "review": review,
                "review_fingerprint": material_fingerprint(review),
            },
        )

    def ensure_workflow_binding(self, context, sources, connection, *, review=None):
        """Reuse consent only for the exact approved revision, audience and account."""
        sources = sorted({_source(source) for source in sources})
        for approval in self._records(
            context.data_user_id, TYPE_WORKFLOW_RUN_AS, tenant_id=context.tenant_id,
        ):
            binding = approval.get("binding", {})
            if (
                approval["status"] in {"denied", "cancelled"}
                and binding.get("workflow_id") == context.workflow_id
                and approval["context"].get("run_id") == context.run_id
            ):
                raise M365PolicyError(
                    "m365_workflow_declined",
                    "The selected account declined this workflow run. Start a new run before requesting authorization again.",
                )
            if (
                approval["status"] in {"approved", "pending"}
                and binding.get("workflow_id") == context.workflow_id
                and binding.get("workflow_fingerprint") == context.workflow_fingerprint
                and binding.get("connection_id") == context.connection_id == connection.get("id")
                and binding.get("connection_generation") == connection.get("generation")
                and binding.get("conversation_id") == context.conversation_id
                and binding.get("audience_version") == context.audience_version
                and binding.get("sources") == sources
                and binding.get("review")
                and connection.get("user_id") == context.data_user_id
                and connection.get("tenant_id") == context.tenant_id
                and connection.get("status") == "connected"
            ):
                approval = self.expire(approval)
                if approval["status"] in {"approved", "pending"}:
                    return approval
        if review is None:
            raise M365PolicyError(
                "m365_workflow_review_required",
                "The workflow owner must provide its instructions, capabilities, inputs, triggers and destinations for your review.",
            )
        return self.create_workflow_binding(context, sources, connection, review=review)

    def validate_workflow_binding(self, context, connection, source=None):
        if not context.binding_id:
            raise M365PolicyError("m365_run_as_required", "An approved workflow Run as binding is required.")
        approval = self.get_approval(context.binding_id, context.data_user_id)
        binding = approval.get("binding", {})
        if (
            approval["request_type"] == TYPE_WORKFLOW_RUN_AS
            and approval["status"] == "pending"
            and approval["tenant_id"] == context.tenant_id
            and binding.get("workflow_id") == context.workflow_id
            and binding.get("workflow_fingerprint") == context.workflow_fingerprint
            and binding.get("connection_id") == context.connection_id
            and binding.get("conversation_id") == context.conversation_id
            and binding.get("audience_version") == context.audience_version
            and connection.get("id") == context.connection_id
            and connection.get("generation") == binding.get("connection_generation")
            and connection.get("status") == "connected"
        ):
            raise M365ApprovalRequired(approval)
        if (
            approval["request_type"] != TYPE_WORKFLOW_RUN_AS or approval["status"] != "approved"
            or approval["tenant_id"] != context.tenant_id
            or binding.get("workflow_id") != context.workflow_id
            or binding.get("workflow_fingerprint") != context.workflow_fingerprint
            or binding.get("connection_id") != context.connection_id
            or binding.get("conversation_id") != context.conversation_id
            or binding.get("audience_version") != context.audience_version
            or connection.get("id") != context.connection_id
            or connection.get("user_id") != context.data_user_id
            or connection.get("tenant_id") != context.tenant_id
            or connection.get("generation") != binding.get("connection_generation")
            or connection.get("status") != "connected"
            or (source is not None and source not in binding.get("sources", []))
        ):
            raise M365PolicyError(
                "m365_run_as_invalid",
                "The workflow, audience, or connected account changed. Renew Run as approval.",
            )
        return sanitize_m365_approval(approval)

    def revoke_workflow_binding(self, binding_id, subject_user_id):
        approval = self.get_approval(binding_id, subject_user_id)
        if approval["request_type"] != TYPE_WORKFLOW_RUN_AS:
            raise LookupError("Workflow Run as binding not found.")
        if approval["status"] == "revoked":
            return sanitize_m365_approval(approval)
        return sanitize_m365_approval(self._transition(
            approval, "revoked", terminal_reason="subject_revoked",
        ))

    def claim_continuation(self, approval_id, subject_user_id, worker_id, lease_seconds=60):
        """Claim the decision outbox, not permission to bypass execution validation."""
        _identifier(worker_id)
        if type(lease_seconds) is not int or not 1 <= lease_seconds <= 300:
            raise ValueError("Continuation lease must be between 1 and 300 seconds.")
        approval = self.get_approval(approval_id, subject_user_id)
        lease = approval.get("continuation_lease")
        if (
            approval["status"] == "pending"
            or approval.get("continuation_status") == "delivered"
            or (lease and utc_datetime(lease["expires_at"]) > self.clock())
        ):
            raise M365ApprovalConflict()
        claim = {
            "id": str(uuid.uuid4()), "worker_id": worker_id,
            "expires_at": (self.clock() + timedelta(seconds=lease_seconds)).isoformat(),
            "decision_event_id": approval["decision_event_id"],
        }
        updated = {
            **approval, "continuation_status": "claimed",
            "continuation_lease": claim,
        }
        try:
            self.container.replace_item(
                item=approval_id, body=updated, partition_key=subject_user_id,
                etag=approval["_etag"], match_condition=MatchConditions.IfNotModified,
            )
        except cosmos_exceptions.CosmosHttpResponseError as exc:
            if exc.status_code == 412:
                raise M365ApprovalConflict() from exc
            raise
        return {
            "approval": sanitize_m365_approval(updated),
            "claim_id": claim["id"], "lease_expires_at": claim["expires_at"],
        }

    def record_execution_status(self, approval_id, subject_user_id, request_id, status):
        """Called by the execution owner, not a user decision or permission grant."""
        if status not in {"running", "awaiting_approval", "awaiting_sign_in", "recovery_required", "cancelled", "failed", "completed"}:
            raise ValueError("Invalid Microsoft 365 execution status.")
        approval = self.get_approval(approval_id, subject_user_id)
        if approval["context"].get("request_id") != request_id:
            raise M365PolicyError("m365_request_mismatch", "This approval belongs to another execution request.")
        if status == "cancelled" and approval["status"] == "pending":
            return sanitize_m365_approval(self._transition(
                approval, "cancelled", terminal_reason="execution_cancelled",
                execution_status="cancelled", continuation_status="delivered",
            ))
        if approval["status"] == "pending":
            raise M365ApprovalConflict()
        if approval.get("execution_status") == status:
            return sanitize_m365_approval(approval)
        updated = {
            **approval, "execution_status": status,
            "continuation_status": "delivered", "continuation_lease": None,
        }
        event = self._audit_document(
            subject_user_id, "execution_status", f"m365-execution-{uuid.uuid4()}",
            approval_id=approval_id, context=approval["context"], execution_status=status,
        )
        self._batch(subject_user_id, [(approval, updated)], event)
        return sanitize_m365_approval(updated)

    def complete_continuation(self, approval_id, subject_user_id, claim_id, execution_status):
        if execution_status not in {"resumed", "awaiting_sign_in", "cancelled", "failed", "completed"}:
            raise ValueError("Invalid Microsoft 365 execution status.")
        approval = self.get_approval(approval_id, subject_user_id)
        lease = approval.get("continuation_lease") or {}
        if (
            approval.get("continuation_status") != "claimed" or lease.get("id") != claim_id
            or lease.get("decision_event_id") != approval.get("decision_event_id")
            or utc_datetime(lease["expires_at"]) <= self.clock()
        ):
            raise M365ApprovalConflict()
        updated = {
            **approval, "continuation_status": "delivered",
            "execution_status": execution_status, "continuation_lease": None,
        }
        event = self._audit_document(
            subject_user_id, "continuation_delivered", f"m365-continuation-{claim_id}",
            approval_id=approval_id, decision_event_id=approval["decision_event_id"],
            context=approval["context"], execution_status=execution_status,
        )
        self._batch(subject_user_id, [(approval, updated)], event)
        return sanitize_m365_approval(updated)

    def list_records(
        self, subject_user_id, *, audit=False, continuation_token=None,
        page_size=20, conversation_id=None, request_type=None,
    ):
        _identifier(subject_user_id)
        if type(page_size) is not int or not 1 <= page_size <= MAX_PAGE_SIZE:
            raise ValueError("Page size must be between 1 and 100.")
        if continuation_token is not None and (
            not isinstance(continuation_token, str) or len(continuation_token) > 16384
        ):
            raise ValueError("Invalid continuation token.")
        kind = "m365_audit" if audit else "m365_approval"
        clauses = ["c.record_kind = @kind"]
        parameters = [{"name": "@kind", "value": kind}]
        if request_type is not None:
            if request_type not in M365_APPROVAL_TYPES or audit:
                raise ValueError("Invalid Microsoft 365 approval type.")
            clauses.append("c.request_type = @request_type")
            parameters.append({"name": "@request_type", "value": request_type})
        if conversation_id is not None:
            clauses.append("c.context.conversation_id = @conversation_id")
            parameters.append({"name": "@conversation_id", "value": _identifier(conversation_id)})
        iterator = self.container.query_items(
            query=f"SELECT * FROM c WHERE {' AND '.join(clauses)} ORDER BY c.created_at DESC",
            parameters=parameters, partition_key=subject_user_id, max_item_count=page_size,
        ).by_page(continuation_token=continuation_token)
        page = next(iterator, [])
        records = []
        for item in page:
            if audit:
                records.append({key: value for key, value in item.items() if not key.startswith("_") and key != "ttl"})
            else:
                item = self.expire(item)
                records.append(sanitize_m365_approval(item))
        return {"items": records, "continuation_token": iterator.continuation_token}

    def list_conversation_audit(self, conversation_id, *, continuation_token=None, page_size=20):
        """Only the authoritative conversation-read route may call this adapter."""
        _identifier(conversation_id)
        if type(page_size) is not int or not 1 <= page_size <= MAX_PAGE_SIZE:
            raise ValueError("Page size must be between 1 and 100.")
        if continuation_token is not None and (
            not isinstance(continuation_token, str) or len(continuation_token) > 16384
        ):
            raise ValueError("Invalid continuation token.")
        iterator = self.container.query_items(
            query=(
                "SELECT * FROM c WHERE c.record_kind = 'm365_audit' "
                "AND c.context.conversation_id = @conversation_id ORDER BY c.created_at DESC"
            ),
            parameters=[{"name": "@conversation_id", "value": conversation_id}],
            enable_cross_partition_query=True, max_item_count=page_size,
        ).by_page(continuation_token=continuation_token)
        records = []
        for item in next(iterator, []):
            if item.get("context", {}).get("conversation_id") != conversation_id:
                raise M365PolicyError("m365_audit_scope_mismatch", "The audit does not match this conversation.")
            safe = {
                key: item[key]
                for key in ("id", "event_type", "created_at", "approval_id", "decision_event_id", "source", "analysis_choice")
                if key in item
            }
            safe["context"] = {
                key: value for key, value in item["context"].items()
                if key in {"conversation_id", "data_user_id", "request_id", "workflow_id", "run_id"}
            }
            if item.get("effective_grant"):
                safe["effective_grant"] = {
                    key: value for key, value in item["effective_grant"].items()
                    if key in {"effective_duration", "acknowledged_at", "expires_at"}
                }
            if item.get("decisions"):
                safe["decisions"] = {
                    source: {
                        key: value for key, value in decision.items()
                        if key in {"duration", "acknowledged_at", "expires_at"}
                    }
                    for source, decision in item["decisions"].items()
                }
            records.append(safe)
        return {"items": records, "continuation_token": iterator.continuation_token}

    def expire_pending(self, page_size=100, continuation_token=None):
        if type(page_size) is not int or not 1 <= page_size <= MAX_PAGE_SIZE:
            raise ValueError("Page size must be between 1 and 100.")
        iterator = self.container.query_items(
            query="SELECT * FROM c WHERE c.record_kind = 'm365_approval' AND c.status = 'pending' AND c.expires_at <= @now",
            parameters=[{"name": "@now", "value": self.clock().isoformat()}],
            enable_cross_partition_query=True, max_item_count=page_size,
        ).by_page(continuation_token=continuation_token)
        expired = [sanitize_m365_approval(self.expire(item)) for item in next(iterator, [])]
        return {"items": expired, "continuation_token": iterator.continuation_token}

    def list_pending_continuations(self, page_size=100, continuation_token=None):
        """Server-only paginated outbox; each returned item still needs a claim."""
        if type(page_size) is not int or not 1 <= page_size <= MAX_PAGE_SIZE:
            raise ValueError("Page size must be between 1 and 100.")
        iterator = self.container.query_items(
            query=(
                "SELECT * FROM c WHERE c.record_kind = 'm365_approval' AND "
                "(c.continuation_status = 'pending' OR "
                "(c.continuation_status = 'claimed' AND c.continuation_lease.expires_at <= @now))"
            ),
            parameters=[{"name": "@now", "value": self.clock().isoformat()}],
            enable_cross_partition_query=True, max_item_count=page_size,
        ).by_page(continuation_token=continuation_token)
        return {
            "items": [sanitize_m365_approval(item) for item in next(iterator, [])],
            "continuation_token": iterator.continuation_token,
        }


_service = M365ApprovalService()


def configure_m365_approvals(**dependencies):
    """Called by an initialized owner; factories perform no bootstrap I/O."""
    global _service
    _service = M365ApprovalService(**dependencies)
    return _service


def get_m365_approval_service():
    return _service


def get_m365_preferences(subject_user_id):
    return _service.get_preferences(subject_user_id)


def update_m365_preferences(subject_user_id, changes):
    return _service.update_preferences(subject_user_id, changes)


def decide_m365_approval(approval_id, subject_user_id, decision):
    return _service.decide(approval_id, subject_user_id, decision)

# functions_control_center_activity_display.py
"""Readable labels, summaries and names for Control Center activity records.

The Activity Logs table, its detail drawer and its CSV export share this presentation, so
an activity reads the same everywhere. The module has no Flask or Azure bootstrap
dependency: storage handles are passed in by the route, which keeps the presentation
testable with fakes. Names come from SimpleChat's own user_settings, groups and
public_workspaces documents (the same source the classic Control Center used), never from
Microsoft Graph, and are returned only to Control Center administrators.
"""

import time
from collections import OrderedDict


ACTIVITY_LOOKUP_LIMIT = 10
ACTIVITY_SEARCH_PEOPLE_MAX = 25
ACTIVITY_SEARCH_PEOPLE_MIN_LENGTH = 2
ACTIVITY_NAME_BATCH = 100
ACTIVITY_TEXT_LIMIT = 500
ACTIVITY_FACT_LIMIT = 16
SYSTEM_ACTOR_IDS = frozenset({"system", "unknown"})

ACTIVITY_CATEGORY_LABELS = {
    "sign_in": "Sign-in and consent",
    "chat": "Chat and conversations",
    "documents": "Documents",
    "tokens": "Token usage",
    "groups": "Groups",
    "public_workspaces": "Public workspaces",
    "administration": "Approvals and administration",
    "agents": "Agents, actions and workflows",
    "data": "Data and sync",
    "other": "Other",
}

# Labels for the activity types SimpleChat writes. Unlisted types are humanized, so a new
# writer still reads sensibly before it is added here.
ACTIVITY_TYPES = {
    "user_login": ("User login", "sign_in"),
    "terms_of_use_accepted": ("Terms of use accepted", "sign_in"),
    "terms_of_use_declined": ("Terms of use declined", "sign_in"),
    "user_agreement_accepted": ("User agreement accepted", "sign_in"),
    "web_search_consent_acceptance": ("Web search consent accepted", "sign_in"),
    "chat_activity": ("Chat activity", "chat"),
    "conversation_creation": ("Conversation created", "chat"),
    "conversation_deletion": ("Conversation deleted", "chat"),
    "conversation_archival": ("Conversation archived", "chat"),
    "document_creation": ("Document created", "documents"),
    "document_deletion": ("Document deleted", "documents"),
    "document_metadata_update": ("Document metadata updated", "documents"),
    "document_upload": ("Document uploaded", "documents"),
    "token_usage": ("Token usage", "tokens"),
    "group_status_change": ("Group status changed", "groups"),
    "group_member_deleted": ("Group member removed", "groups"),
    "add_member_directly": ("Group member added", "groups"),
    "admin_add_member_csv": ("Group members imported", "groups"),
    "update_member_role": ("Group member role changed", "groups"),
    "public_workspace_status_change": ("Public workspace status changed", "public_workspaces"),
    "add_workspace_member_directly": ("Workspace manager added", "public_workspaces"),
    "admin_add_workspace_member_csv": ("Workspace managers imported", "public_workspaces"),
    "public_add_member_directly": ("Public workspace member added", "public_workspaces"),
    "public_member_removed": ("Public workspace member removed", "public_workspaces"),
    "public_membership_requested": ("Public workspace access requested", "public_workspaces"),
    "public_membership_request_canceled": ("Public workspace request canceled", "public_workspaces"),
    "public_update_member_role": ("Public workspace role changed", "public_workspaces"),
    "admin_take_ownership_approved": ("Group ownership taken (approved)", "administration"),
    "transfer_ownership_approved": ("Group ownership transferred (approved)", "administration"),
    "delete_group_approved": ("Group deleted (approved)", "administration"),
    "delete_all_documents_approved": ("Group documents deleted (approved)", "administration"),
    "delete_all_user_documents_approved": ("User documents deleted (approved)", "administration"),
    "admin_take_workspace_ownership_approved": ("Workspace ownership taken (approved)", "administration"),
    "transfer_workspace_ownership_approved": ("Workspace ownership transferred (approved)", "administration"),
    "delete_workspace_documents_approved": ("Workspace documents deleted (approved)", "administration"),
    "delete_workspace_approved": ("Workspace deleted (approved)", "administration"),
    "admin_action": ("Admin action", "administration"),
    "governance": ("Governance change", "administration"),
    "retention_policy_force_push": ("Retention policy pushed", "administration"),
    "admin_feedback_email_submission": ("Feedback email sent", "administration"),
    "admin_release_notifications_registration": ("Release notifications registered", "administration"),
    "user_support_feedback_email_submission": ("Support feedback sent", "other"),
    "agent_creation": ("Agent created", "agents"),
    "agent_update": ("Agent updated", "agents"),
    "agent_deletion": ("Agent deleted", "agents"),
    "agent_run": ("Agent used", "agents"),
    "agent_template_submission": ("Agent template submitted", "agents"),
    "agent_template_approval": ("Agent template approved", "agents"),
    "agent_template_rejection": ("Agent template rejected", "agents"),
    "agent_template_deletion": ("Agent template deleted", "agents"),
    "action_creation": ("Action created", "agents"),
    "action_update": ("Action updated", "agents"),
    "action_deletion": ("Action deleted", "agents"),
    "workflow_creation": ("Workflow created", "agents"),
    "workflow_update": ("Workflow updated", "agents"),
    "workflow_deletion": ("Workflow deleted", "agents"),
    "workflow_run": ("Workflow run", "agents"),
    "file_sync": ("File sync", "data"),
    "data_management": ("Data management", "data"),
    "index_auto_fix": ("Search index fields added", "data"),
}

# Where each writer records who acted. Records written by approvals, membership changes and
# status changes often have no top-level user_id, so the first present field wins.
ACTOR_ID_PATHS = (
    ("user_id",), ("admin_user_id",), ("requester_id",), ("added_by_user_id",),
    ("changed_by_user_id",), ("changed_by", "user_id"), ("removed_by", "user_id"),
    ("admin", "user_id"), ("actor", "user_id"),
)
ACTOR_EMAIL_PATHS = (
    ("admin_email",), ("requester_email",), ("added_by_email",), ("changed_by_email",),
    ("changed_by", "email"), ("removed_by", "email"), ("admin", "email"), ("actor", "email"),
)
GROUP_ID_PATHS = (
    ("workspace_context", "group_id"), ("group_id",), ("group", "group_id"),
    ("workspace_context", "group_workspace_id"),
)
GROUP_NAME_PATHS = (("group", "group_name"), ("group_name",), ("workspace_context", "workspace_name"))
PUBLIC_ID_PATHS = (
    ("workspace_context", "public_workspace_id"), ("public_workspace_id",),
    ("public_workspace", "public_workspace_id"), ("public_workspace", "workspace_id"),
)
PUBLIC_NAME_PATHS = (
    ("public_workspace", "workspace_name"), ("public_workspace", "public_workspace_name"),
    ("workspace_context", "public_workspace_name"), ("public_workspace_name",), ("workspace_name",),
    ("workspace_context", "workspace_name"),
)
WORKSPACE_TYPES = {
    "personal": "personal", "group": "group", "public": "public", "public_workspace": "public",
    "admin": "admin", "global": "global",
}


def _value(record, *path):
    value = record
    for part in path:
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def _text(value):
    """A trimmed display string; containers and booleans are not display text."""
    if isinstance(value, bool) or value is None or isinstance(value, (dict, list)):
        return ""
    text = str(value).strip()
    return text[:ACTIVITY_TEXT_LIMIT]


def _first_text(record, paths):
    for path in paths:
        text = _text(_value(record, *path))
        if text:
            return text
    return ""


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value


def _count(value):
    number = _number(value)
    if number is None:
        return ""
    return f"{int(number):,}" if float(number).is_integer() else f"{number:,.2f}"


def _bytes(value):
    number = _number(value)
    if number is None or number < 0:
        return ""
    for unit in ("bytes", "KB", "MB", "GB"):
        if number < 1024 or unit == "GB":
            return f"{int(number):,} bytes" if unit == "bytes" else f"{number:,.1f} {unit}"
        number /= 1024
    return ""


def humanize(value):
    """Turn a stored identifier such as document_action_chat into 'Document action chat'."""
    text = _text(value).replace("_", " ").replace("-", " ")
    text = " ".join(text.split())
    return text[:1].upper() + text[1:] if text else ""


def _yes_no(value):
    return ("Yes" if value else "No") if isinstance(value, bool) else ""


def activity_label(activity_type):
    known = ACTIVITY_TYPES.get(activity_type) if isinstance(activity_type, str) else None
    return known[0] if known else (humanize(activity_type) or "Unknown activity")


def activity_category(activity_type):
    known = ACTIVITY_TYPES.get(activity_type) if isinstance(activity_type, str) else None
    return known[1] if known else "other"


def activity_type_catalog():
    """Every labelled activity type, in category order, for the Activity filter."""
    order = list(ACTIVITY_CATEGORY_LABELS)
    entries = [
        {"activity_type": key, "label": label, "category": category,
         "category_label": ACTIVITY_CATEGORY_LABELS[category]}
        for key, (label, category) in ACTIVITY_TYPES.items()
    ]
    return sorted(entries, key=lambda item: (order.index(item["category"]), item["label"].casefold()))


def label_activity_facets(facets):
    """Add the label and category to summary facets without changing their counts."""
    return [
        {**facet, "label": activity_label(facet.get("activity_type")),
         "category": activity_category(facet.get("activity_type"))}
        for facet in facets
    ]


def activity_actor(record):
    """Who acted: a user ID when one was recorded, otherwise an email, otherwise the system."""
    actor_id = ""
    for path in ACTOR_ID_PATHS:
        candidate = _value(record, *path)
        if isinstance(candidate, str) and candidate.strip():
            actor_id = candidate.strip()
            break
    email = _first_text(record, ACTOR_EMAIL_PATHS)
    if actor_id.casefold() in SYSTEM_ACTOR_IDS:
        return {"id": "", "email": email, "kind": "user" if email else "system"}
    return {"id": actor_id, "email": email, "kind": "user" if actor_id or email else "system"}


def activity_workspace(record):
    """Where the activity happened, using every location the writers record.

    These locations mirror GROUP_REFERENCE_FIELDS and PUBLIC_REFERENCE_FIELDS in the query
    module, so a workspace shown in a row is one its filter matches.
    """
    stored_type = WORKSPACE_TYPES.get(_text(record.get("workspace_type")).casefold(), "")
    group_id = _first_text(record, GROUP_ID_PATHS)
    public_id = _first_text(record, PUBLIC_ID_PATHS)
    # Public workspace ownership approvals record only a bare workspace_id.
    if not group_id and not public_id and stored_type in ("", "public"):
        public_id = _text(record.get("workspace_id"))
    if group_id and stored_type != "public":
        return {"type": "group", "id": group_id, "recorded_name": _first_text(record, GROUP_NAME_PATHS)}
    if public_id and stored_type != "group":
        return {"type": "public", "id": public_id, "recorded_name": _first_text(record, PUBLIC_NAME_PATHS)}
    return {"type": stored_type, "id": "", "recorded_name": ""}


def activity_status(record):
    """'failed' when the record says it failed or errored, else None."""
    for path in (("status",), ("document", "status"), ("additional_context", "status"), ("run", "status")):
        text = _text(_value(record, *path)).casefold()
        if "fail" in text or "error" in text:
            return "failed"
    if _text(_value(record, "additional_context", "error")) or _text(_value(record, "run", "error")):
        return "failed"
    return None


class _Facts:
    def __init__(self):
        self.items = []
        self.labels = set()

    def add(self, label, value):
        text = value if isinstance(value, str) else _text(value)
        if text and label not in self.labels and len(self.items) < ACTIVITY_FACT_LIMIT:
            self.items.append({"label": label, "value": text})
            self.labels.add(label)


def _member(record):
    return (_text(record.get("member_name")) or _text(_value(record, "removed_member", "name"))
            or _text(_value(record, "added_member", "name")) or _text(record.get("member_email"))
            or _text(_value(record, "removed_member", "email")) or _text(record.get("target_user_name"))
            or "a member")


def _entity_name(record):
    return (_text(_value(record, "entity", "display_name")) or _text(_value(record, "entity", "name"))
            or _text(_value(record, "agent", "display_name")) or _text(_value(record, "agent", "name")))


def _workspace_label(record):
    workspace = activity_workspace(record)
    return workspace["recorded_name"] or workspace["id"]


def _describe_chat(record, facts):
    context = record.get("additional_context") if isinstance(record.get("additional_context"), dict) else {}
    source_labels = {"document_action_chat": "Document action", "collaboration_chat": "Multi-user collaboration",
                     "standard_chat": "Standard chat"}
    message = humanize(record.get("message_type")) or "Message"
    source = (humanize(context.get("document_action_type"))
              or source_labels.get(_text(context.get("conversation_source")))
              or humanize(context.get("conversation_source")))
    place = humanize(record.get("chat_context") or record.get("workspace_type"))
    summary = " · ".join(part for part in (message, source, place) if part)
    length = _number(record.get("message_length"))
    detail = f"{_count(length)} characters" if length else ""
    facts.add("Message type", message)
    facts.add("Source", source)
    facts.add("Context", place)
    facts.add("Conversation ID", record.get("conversation_id"))
    facts.add("Characters", _count(length))
    facts.add("Document search", _yes_no(record.get("has_document_search")))
    facts.add("Image generation", _yes_no(record.get("has_image_generation")))
    facts.add("Agent", context.get("agent_name"))
    facts.add("Reasoning effort", context.get("reasoning_effort"))
    facts.add("Visibility", humanize(context.get("visibility_mode")))
    return summary, detail


def _describe_document(record, facts, activity_type):
    document = record.get("document") if isinstance(record.get("document"), dict) else {}
    file_name = _text(document.get("file_name")) or "Unknown file"
    file_type = _text(document.get("file_type"))
    pages = _number(document.get("page_count"))
    updated = record.get("updated_fields") if isinstance(record.get("updated_fields"), dict) else {}
    if activity_type == "document_metadata_update":
        detail = f"Updated: {', '.join(sorted(str(key) for key in updated))}" if updated else ""
    else:
        detail = " · ".join(part for part in (
            file_type.lstrip(".").upper(), _bytes(document.get("file_size_bytes")),
            f"{_count(pages)} pages" if pages else "",
        ) if part)
    facts.add("File name", file_name)
    facts.add("File type", file_type)
    facts.add("Size", _bytes(document.get("file_size_bytes")))
    facts.add("Pages", _count(pages))
    facts.add("Processing status", document.get("status"))
    facts.add("Updated fields", ", ".join(sorted(str(key) for key in updated)))
    facts.add("Embedding tokens", _count(_value(record, "embedding_usage", "total_tokens")))
    facts.add("Embedding model", _value(record, "embedding_usage", "model_deployment_name"))
    facts.add("Document ID", document.get("document_id"))
    return file_name, detail


def _describe_tokens(record, facts):
    usage = record.get("usage") if isinstance(record.get("usage"), dict) else {}
    total = _count(usage.get("total_tokens")) or "0"
    model = _text(usage.get("model"))
    token_type = humanize(record.get("token_type"))
    summary = " · ".join(part for part in (f"{total} tokens", model) if part)
    prompt, completion = _count(usage.get("prompt_tokens")), _count(usage.get("completion_tokens"))
    file_name = _text(_value(record, "embedding_details", "file_name"))
    detail = " · ".join(part for part in (
        token_type, f"prompt {prompt}" if prompt else "", f"completion {completion}" if completion else "",
        file_name,
    ) if part)
    facts.add("Token type", token_type)
    facts.add("Total tokens", total)
    facts.add("Prompt tokens", prompt)
    facts.add("Completion tokens", completion)
    facts.add("Model", model)
    facts.add("File", file_name)
    facts.add("Conversation ID", _value(record, "chat_details", "conversation_id"))
    facts.add("Message ID", _value(record, "chat_details", "message_id"))
    facts.add("Document ID", _value(record, "embedding_details", "document_id"))
    return summary, detail


def _describe_status_change(record, facts):
    change = record.get("status_change") if isinstance(record.get("status_change"), dict) else {}
    old, new = _text(change.get("old_status")) or "unknown", _text(change.get("new_status")) or "unknown"
    reason = _text(change.get("reason"))
    facts.add("Previous status", old)
    facts.add("New status", new)
    facts.add("Reason", reason)
    facts.add("Changed by", _value(record, "changed_by", "email"))
    return f"{humanize(old)} → {humanize(new)}", reason or _workspace_label(record)


def _describe_membership(record, facts, activity_type):
    member = _member(record)
    target = _workspace_label(record)
    old_role, new_role = _text(record.get("old_role")), _text(record.get("new_role"))
    role = _text(record.get("member_role"))
    if activity_type in ("update_member_role", "public_update_member_role"):
        summary = f"{member}: {old_role or 'unknown'} → {new_role or 'unknown'}"
    elif activity_type in ("group_member_deleted", "public_member_removed"):
        summary = f"Removed {member}"
    elif activity_type in ("public_membership_requested", "public_membership_request_canceled"):
        summary = _text(record.get("description")) or activity_label(activity_type)
    else:
        summary = f"Added {member}"
    detail = " · ".join(part for part in (f"Role: {role}" if role else "", target) if part)
    facts.add("Member", member if member != "a member" else "")
    facts.add("Member email", record.get("member_email") or _value(record, "removed_member", "email"))
    facts.add("Role", role)
    facts.add("Previous role", old_role)
    facts.add("New role", new_role)
    facts.add("Removed by", _value(record, "removed_by", "email"))
    return summary, detail


def _describe_approval(record, facts):
    summary = _text(record.get("description")) or activity_label(record.get("activity_type"))
    requester = _text(record.get("requester_email")) or _text(record.get("admin_email"))
    approver = _text(record.get("approver_email"))
    detail = " · ".join(part for part in (
        f"Requested by {requester}" if requester else "", f"approved by {approver}" if approver else "",
    ) if part)
    facts.add("Requested by", requester)
    facts.add("Approved by", approver)
    facts.add("Previous owner", record.get("old_owner_email"))
    facts.add("New owner", record.get("new_owner_email"))
    facts.add("Documents deleted", _count(record.get("documents_deleted")))
    facts.add("Target user", record.get("target_user_name") or record.get("target_user_email"))
    facts.add("Approval ID", record.get("approval_id"))
    return summary, detail


def _describe_file_sync(record, facts):
    context = record.get("workspace_context") if isinstance(record.get("workspace_context"), dict) else {}
    extra = record.get("additional_context") if isinstance(record.get("additional_context"), dict) else {}
    counts = extra.get("counts") if isinstance(extra.get("counts"), dict) else {}
    source = _text(context.get("source_name")) or _text(extra.get("source_name")) or "Unknown source"
    action = humanize(record.get("action")) or "Sync event"
    detail = " · ".join(
        f"{humanize(key)} {_count(counts.get(key))}"
        for key in ("scanned", "queued", "unchanged", "skipped", "deleted", "failed")
        if _count(counts.get(key))
    )
    facts.add("Action", action)
    facts.add("Source", source)
    facts.add("Scope", humanize(context.get("scope_type") or record.get("workspace_type")))
    facts.add("Run ID", extra.get("run_id"))
    for key in ("scanned", "queued", "unchanged", "skipped", "deleted", "failed"):
        facts.add(humanize(key), _count(counts.get(key)))
    facts.add("Error", extra.get("error"))
    facts.add("Source ID", context.get("source_id"))
    return f"{action} · {source}", detail


def _describe_data_management(record, facts):
    extra = record.get("additional_context") if isinstance(record.get("additional_context"), dict) else {}
    context = record.get("workspace_context") if isinstance(record.get("workspace_context"), dict) else {}
    action = humanize(record.get("action")) or "Data management event"
    operation = humanize(extra.get("operation") or context.get("operation"))
    status = humanize(extra.get("status"))
    job = _text(extra.get("job_id") or context.get("job_id"))
    facts.add("Action", action)
    facts.add("Operation", operation)
    facts.add("Status", status)
    facts.add("Backup type", humanize(extra.get("backup_type") or context.get("backup_type")))
    facts.add("Job ID", job)
    return " · ".join(part for part in (action, operation) if part), " · ".join(
        part for part in (status, f"Job {job}" if job else "") if part
    )


def _describe_agents(record, facts, activity_type):
    name = _entity_name(record) or "Unnamed"
    run = record.get("run") if isinstance(record.get("run"), dict) else {}
    scope = humanize(record.get("workspace_type"))
    status = humanize(run.get("status") or _value(record, "entity", "status"))
    detail = " · ".join(part for part in (
        scope, status, humanize(run.get("trigger_source")), _text(record.get("model_deployment_name")),
    ) if part)
    facts.add("Name", name)
    facts.add("Operation", humanize(record.get("operation")))
    facts.add("Scope", scope)
    facts.add("Status", status)
    facts.add("Trigger", humanize(run.get("trigger_source")))
    facts.add("Model", record.get("model_deployment_name"))
    facts.add("Error", run.get("error"))
    facts.add("Review reason", record.get("review_reason"))
    facts.add("Run ID", run.get("id"))
    facts.add("Conversation ID", run.get("conversation_id") or record.get("conversation_id"))
    return name, detail


def _describe_governance(record, facts):
    context = record.get("workspace_context") if isinstance(record.get("workspace_context"), dict) else {}
    action = humanize(record.get("action")) or "Governance change"
    scope, target = humanize(context.get("scope")), _text(context.get("target_id"))
    facts.add("Action", action)
    facts.add("Scope", scope)
    facts.add("Target", target)
    return action, " · ".join(part for part in (scope, target) if part)


def describe_activity(record):
    """Return label, category, one-line summary, secondary detail, facts and failure state."""
    record = record if isinstance(record, dict) else {}
    activity_type = _text(record.get("activity_type"))
    facts = _Facts()
    summary, detail = "", ""
    if activity_type == "user_login":
        method = _text(record.get("login_method")) or _text(_value(record, "details", "login_method"))
        summary, detail = "Signed in", f"Method: {method}" if method else ""
        facts.add("Login method", method)
    elif activity_type == "chat_activity":
        summary, detail = _describe_chat(record, facts)
    elif activity_type in ("conversation_creation", "conversation_deletion", "conversation_archival"):
        conversation = record.get("conversation") if isinstance(record.get("conversation"), dict) else {}
        summary = _text(conversation.get("title")) or "Untitled conversation"
        tags = conversation.get("tags") if isinstance(conversation.get("tags"), list) else []
        detail = ", ".join(_text(tag) for tag in tags if _text(tag))
        facts.add("Title", summary)
        facts.add("Conversation ID", conversation.get("conversation_id"))
        facts.add("Tags", detail)
    elif activity_type in ("document_creation", "document_deletion", "document_metadata_update"):
        summary, detail = _describe_document(record, facts, activity_type)
    elif activity_type == "token_usage":
        summary, detail = _describe_tokens(record, facts)
    elif activity_type in ("group_status_change", "public_workspace_status_change"):
        summary, detail = _describe_status_change(record, facts)
    elif activity_type in (
        "group_member_deleted", "add_member_directly", "admin_add_member_csv", "update_member_role",
        "add_workspace_member_directly", "admin_add_workspace_member_csv", "public_add_member_directly",
        "public_member_removed", "public_update_member_role", "public_membership_requested",
        "public_membership_request_canceled",
    ):
        summary, detail = _describe_membership(record, facts, activity_type)
    elif activity_type.endswith("_approved"):
        summary, detail = _describe_approval(record, facts)
    elif activity_type == "file_sync":
        summary, detail = _describe_file_sync(record, facts)
    elif activity_type == "data_management":
        summary, detail = _describe_data_management(record, facts)
    elif activity_type == "governance":
        summary, detail = _describe_governance(record, facts)
    elif activity_category(activity_type) == "agents":
        summary, detail = _describe_agents(record, facts, activity_type)
    description = _text(record.get("description"))
    if not summary:
        summary = description or humanize(record.get("action")) or activity_label(activity_type)
    facts.add("Description", description if description != summary else "")
    facts.add("Action", humanize(record.get("action")))
    return {
        "activity_type": activity_type,
        "label": activity_label(activity_type),
        "category": activity_category(activity_type),
        "summary": summary,
        "detail": detail if detail != summary else "",
        "facts": facts.items,
        "status": activity_status(record),
    }


class ActivityNameCache:
    """A small TTL cache for display names, shared across pages and exports."""

    def __init__(self, ttl_seconds=300, max_entries=5000, clock=time.monotonic):
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self.clock = clock
        self.entries = OrderedDict()

    def get(self, kind, key):
        entry = self.entries.get((kind, key))
        if not entry:
            return False, None
        expires_at, value = entry
        if expires_at <= self.clock():
            self.entries.pop((kind, key), None)
            return False, None
        return True, value

    def set(self, kind, key, value):
        self.entries[(kind, key)] = (self.clock() + self.ttl_seconds, value)
        self.entries.move_to_end((kind, key))
        while len(self.entries) > self.max_entries:
            self.entries.popitem(last=False)


def _lookup(container, kind, ids, query, project, cache):
    """Resolve IDs in batches with one parameterized query each; cache misses as None."""
    found = {}
    pending = []
    for item_id in dict.fromkeys(item for item in ids if isinstance(item, str) and item):
        hit, value = cache.get(kind, item_id) if cache else (False, None)
        if hit:
            found[item_id] = value
        else:
            pending.append(item_id)
    for start in range(0, len(pending), ACTIVITY_NAME_BATCH):
        batch = pending[start:start + ACTIVITY_NAME_BATCH]
        rows = container.query_items(
            query=query, parameters=[{"name": "@ids", "value": batch}], enable_cross_partition_query=True,
        )
        resolved = {row["id"]: project(row) for row in rows if isinstance(row, dict) and row.get("id") in batch}
        for item_id in batch:
            found[item_id] = resolved.get(item_id)
            if cache:
                cache.set(kind, item_id, found[item_id])
    return found


def collect_activity_name_ids(records, filters=None):
    """The user, group and public workspace IDs a page of records and its filters mention."""
    people, groups, public = [], [], []
    for record in records:
        if not isinstance(record, dict):
            continue
        actor = activity_actor(record)
        if actor["id"]:
            people.append(actor["id"])
        workspace = activity_workspace(record)
        if workspace["type"] == "group" and workspace["id"]:
            groups.append(workspace["id"])
        elif workspace["type"] == "public" and workspace["id"]:
            public.append(workspace["id"])
    if filters:
        reference = activity_filter_workspace(filters)
        if filters.get("user_id"):
            people.append(filters["user_id"])
        if reference["type"] == "group":
            groups.append(reference["id"])
        elif reference["type"] == "public":
            public.append(reference["id"])
    return people, groups, public


def resolve_activity_names(records, filters=None, *, user_container, groups_container, public_container, cache=None):
    """Batched name lookups for one page: at most one query per kind for uncached IDs."""
    people, groups, public = collect_activity_name_ids(records, filters)
    return {
        "people": _lookup(
            user_container, "person", people,
            "SELECT c.id, c.display_name, c.email FROM c WHERE ARRAY_CONTAINS(@ids, c.id)",
            lambda row: {"display_name": _text(row.get("display_name")), "email": _text(row.get("email"))},
            cache,
        ),
        "groups": _lookup(
            groups_container, "group", groups,
            "SELECT c.id, c.name FROM c WHERE ARRAY_CONTAINS(@ids, c.id)",
            lambda row: _text(row.get("name")), cache,
        ),
        "public_workspaces": _lookup(
            public_container, "public", public,
            "SELECT c.id, c.name FROM c WHERE ARRAY_CONTAINS(@ids, c.id)",
            lambda row: _text(row.get("name")), cache,
        ),
    }


def empty_activity_names():
    return {"people": {}, "groups": {}, "public_workspaces": {}}


def _person_view(actor_id, email, names):
    person = names["people"].get(actor_id) if actor_id else None
    return {
        "id": actor_id,
        "name": (person or {}).get("display_name", ""),
        "email": (person or {}).get("email") or email,
        "kind": "user" if actor_id or email else "system",
        "resolved": bool(person),
    }


def _workspace_view(workspace, names):
    lookup = {"group": names["groups"], "public": names["public_workspaces"]}.get(workspace["type"], {})
    current = lookup.get(workspace["id"]) if workspace["id"] else None
    return {
        "type": workspace["type"],
        "id": workspace["id"],
        "name": current or workspace["recorded_name"],
        "resolved": bool(current),
    }


def present_activity_record(record, names):
    """The presentation the table, drawer and export share for one record."""
    view = describe_activity(record)
    actor = activity_actor(record if isinstance(record, dict) else {})
    view["actor"] = _person_view(actor["id"], actor["email"], names)
    view["workspace"] = _workspace_view(activity_workspace(record if isinstance(record, dict) else {}), names)
    return view


def present_activity_rows(records, names):
    return [present_activity_record(record, names) for record in records]


def activity_filter_workspace(filters):
    """The specific workspace a filter set names, using the same precedence as the query."""
    workspace_type = filters.get("workspace_type") or ""
    group_id = filters.get("group_id") or (filters.get("workspace_id") if workspace_type == "group" else "")
    public_id = filters.get("public_workspace_id") or (filters.get("workspace_id") if workspace_type == "public" else "")
    if group_id:
        return {"type": "group", "id": group_id}
    if public_id:
        return {"type": "public", "id": public_id}
    return {"type": workspace_type, "id": ""}


def activity_filter_labels(filters, names):
    """Names for the person and workspace filters, so the toolbar never shows a bare ID."""
    labels = {}
    if filters.get("user_id"):
        person = _person_view(filters["user_id"], "", names)
        labels["person"] = {key: person[key] for key in ("id", "name", "email", "resolved")}
    reference = activity_filter_workspace(filters)
    if reference["id"]:
        labels["workspace"] = _workspace_view({**reference, "recorded_name": ""}, names)
    return labels


def activity_csv_columns(view):
    """Readable export columns from a presentation, in the export header's order."""
    summary = view["summary"] + (f" ({view['detail']})" if view.get("detail") else "")
    return (
        view["actor"]["name"], view["actor"]["email"], view["label"], summary,
        view["workspace"]["id"], view["workspace"]["name"],
    )


def _search_term(term):
    term = term.strip() if isinstance(term, str) else ""
    return term if len(term) >= ACTIVITY_SEARCH_PEOPLE_MIN_LENGTH else ""


def _ranked(rows, term, *fields):
    folded = term.casefold()

    def rank(row):
        values = [_text(row.get(field)).casefold() for field in fields]
        if row.get("id") == term or folded in values:
            return 0
        if any(value.startswith(folded) for value in values):
            return 1
        return 2
    return sorted(rows, key=lambda row: (rank(row), _text(row.get(fields[0])).casefold(), _text(row.get("id"))))


def search_activity_people(container, term, limit=ACTIVITY_LOOKUP_LIMIT):
    """SimpleChat users whose name or email contains the term, or whose ID is the term."""
    term = _search_term(term)
    if not term:
        return []
    rows = container.query_items(
        query=("SELECT TOP @limit c.id, c.display_name, c.email FROM c WHERE c.id = @term "
               "OR CONTAINS(c.display_name, @term, true) OR CONTAINS(c.email, @term, true)"),
        parameters=[{"name": "@limit", "value": limit}, {"name": "@term", "value": term}],
        enable_cross_partition_query=True,
    )
    people = [
        {"id": row["id"], "display_name": _text(row.get("display_name")), "email": _text(row.get("email"))}
        for row in rows if isinstance(row, dict) and isinstance(row.get("id"), str)
    ]
    return _ranked(people, term, "display_name", "email")[:limit]


def search_activity_people_ids(container, term):
    """IDs for search expansion: up to ACTIVITY_SEARCH_PEOPLE_MAX, with a truncation flag."""
    if not _search_term(term):
        return [], False
    people = search_activity_people(container, term, ACTIVITY_SEARCH_PEOPLE_MAX + 1)
    return [person["id"] for person in people[:ACTIVITY_SEARCH_PEOPLE_MAX]], len(people) > ACTIVITY_SEARCH_PEOPLE_MAX


def search_activity_workspaces(groups_container, public_container, term, limit=ACTIVITY_LOOKUP_LIMIT):
    """Groups and public workspaces whose name contains the term, or whose ID is the term."""
    term = _search_term(term)
    if not term:
        return []
    found = []
    for workspace_type, container in (("group", groups_container), ("public", public_container)):
        rows = container.query_items(
            query="SELECT TOP @limit c.id, c.name FROM c WHERE c.id = @term OR CONTAINS(c.name, @term, true)",
            parameters=[{"name": "@limit", "value": limit}, {"name": "@term", "value": term}],
            enable_cross_partition_query=True,
        )
        matches = [
            {"type": workspace_type, "id": row["id"], "name": _text(row.get("name"))}
            for row in rows if isinstance(row, dict) and isinstance(row.get("id"), str)
        ]
        found.extend(_ranked(matches, term, "name")[:limit])
    return found

# functions_document_provenance.py
"""Server-owned provenance ("origin") for workspace documents.

Documents that a workflow or a chat creates carry a hidden, versioned ``origin``
record on each document version. The record is derived only from server-held
bindings: a generated artifact's source binding, its workflow or orchestration
producer, the publication receipt, and chat-upload metadata. Clients can never
set or edit it. Browsers receive at most the coarse ``origin_kind`` on document
responses, plus an access-checked ``origin_summary`` on single-document detail
reads that ask for one.

Other application modules are imported lazily because ``functions_documents``
imports this module at load time.
"""

import logging
import re
import uuid
from collections.abc import Mapping
from importlib import import_module
from urllib.parse import quote

from flask import g, has_request_context, session


ORIGIN_FIELD = "origin"
ORIGIN_KIND_FIELD = "origin_kind"
ORIGIN_SUMMARY_FIELD = "origin_summary"
ORIGIN_FIELD_NAMES = (ORIGIN_FIELD, ORIGIN_KIND_FIELD, ORIGIN_SUMMARY_FIELD)
ORIGIN_SCHEMA_VERSION = 1
ORIGIN_KIND_WORKFLOW = "workflow"
ORIGIN_KIND_CHAT = "chat"
ORIGIN_KINDS = frozenset({ORIGIN_KIND_WORKFLOW, ORIGIN_KIND_CHAT})
WORKFLOW_ORIGIN_TAG = "workflow"
ORIGIN_SUMMARY_PARAM = "origin_summary"
ORIGIN_WORKFLOW_FILTER_PARAM = "origin_workflow_id"
ORIGIN_RUN_FILTER_PARAM = "origin_run_id"
ORIGIN_CONVERSATION_FILTER_PARAM = "origin_conversation_id"
ORIGIN_FILTER_PARAMS = frozenset({
    ORIGIN_WORKFLOW_FILTER_PARAM,
    ORIGIN_RUN_FILTER_PARAM,
    ORIGIN_CONVERSATION_FILTER_PARAM,
})
WORKFLOW_FALLBACK_LABEL = "Created by a workflow"
CHAT_FALLBACK_LABEL = "Created in a chat"
UNTITLED_WORKFLOW_LABEL = "Untitled workflow"
UNTITLED_CONVERSATION_LABEL = "Untitled conversation"
ORIGIN_NOT_FOUND_MESSAGE = "Origin not found."

_MAX_TEXT_LENGTH = 1024
_MAX_LABEL_TEXT_LENGTH = 200
_MAX_TIMESTAMP_LENGTH = 64
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f]")
_SERVER_TAG = re.compile(r"[a-z0-9_-]{1,50}\Z")
_ORIGIN_KEY_NAMES = frozenset({"origin", "originkind", "originsummary"})
_WORKFLOW_SCOPE_TYPES = frozenset({"personal", "group"})
_WORKFLOW_REQUIRED_FIELDS = frozenset({"version", "kind", "workflow_scope", "workflow_id"})
_WORKFLOW_OPTIONAL_FIELDS = frozenset({"run_id", "task_id", "node_id", "output_key", "definition_revision"})
_CHAT_REQUIRED_FIELDS = frozenset({"version", "kind", "conversation_id"})
_CHAT_OPTIONAL_FIELDS = frozenset({
    "message_id",
    "orchestration_run_id",
    "orchestration_step_id",
    "collaboration_conversation_id",
})
_SUMMARY_STASH = "_document_origin_summaries"
_TRUE_VALUES = frozenset({"1", "true"})
_EXPECTED_ACCESS_ERRORS = (PermissionError, LookupError, ValueError)


def _log_event(message, **kwargs):
    """Log through ``functions_appinsights.log_event``.

    Imported lazily: ``content_screening.access`` loads this module on every document
    request path, and importing Azure Monitor there would make that path heavy to import.
    """
    import_module("functions_appinsights").log_event(message, **kwargs)


class DocumentOriginError(ValueError):
    """Raised when an origin is malformed or when a client tries to supply one."""

    code = "document_origin_server_managed"
    public_message = "Document origin is server-managed."
    status_code = 400

    def __init__(self, message=None):
        super().__init__(message or self.public_message)


class DocumentOriginFilterError(ValueError):
    """Raised when document origin filter parameters are invalid or name an inaccessible origin."""

    def __init__(self, public_message, status_code=400):
        super().__init__(public_message)
        self.public_message = public_message
        self.status_code = status_code


def _is_origin_text(value):
    return (
        isinstance(value, str)
        and bool(value)
        and value == value.strip()
        and len(value) <= _MAX_TEXT_LENGTH
        and not _CONTROL_CHARACTERS.search(value)
    )


def _id_text(value):
    return value if _is_origin_text(value) else None


def _mapping(value):
    return value if isinstance(value, Mapping) else {}


def _is_not_found(exc):
    return getattr(exc, "status_code", None) == 404


def _validated_scope(value):
    if not isinstance(value, Mapping) or set(value) != {"type", "id"}:
        raise DocumentOriginError("Workflow origin scope is invalid.")
    scope_type = value.get("type")
    scope_id = value.get("id")
    if scope_type not in _WORKFLOW_SCOPE_TYPES or not _is_origin_text(scope_id):
        raise DocumentOriginError("Workflow origin scope is invalid.")
    return {"type": scope_type, "id": scope_id}


def validate_origin(origin):
    """Return a normalized copy of a server-built or stored origin, or raise DocumentOriginError."""
    if not isinstance(origin, Mapping):
        raise DocumentOriginError("Document origin must be an object.")
    version = origin.get("version")
    if type(version) is not int or version != ORIGIN_SCHEMA_VERSION:
        raise DocumentOriginError("Document origin version is not supported.")
    kind = origin.get("kind")
    if kind == ORIGIN_KIND_WORKFLOW:
        required, optional = _WORKFLOW_REQUIRED_FIELDS, _WORKFLOW_OPTIONAL_FIELDS
    elif kind == ORIGIN_KIND_CHAT:
        required, optional = _CHAT_REQUIRED_FIELDS, _CHAT_OPTIONAL_FIELDS
    else:
        raise DocumentOriginError("Document origin kind is not supported.")
    keys = set(origin)
    if not required <= keys or keys - required - optional:
        raise DocumentOriginError("Document origin fields are invalid.")
    normalized = {"version": ORIGIN_SCHEMA_VERSION, "kind": kind}
    for key in sorted(keys - {"version", "kind"}):
        value = origin[key]
        if key == "workflow_scope":
            normalized[key] = _validated_scope(value)
        elif not _is_origin_text(value):
            raise DocumentOriginError(f"Document origin field {key} is invalid.")
        elif key == "definition_revision" and not _DIGEST.match(value):
            raise DocumentOriginError("Document origin definition revision is invalid.")
        else:
            normalized[key] = value
    if "orchestration_step_id" in normalized and "orchestration_run_id" not in normalized:
        raise DocumentOriginError("A document origin orchestration step needs its run.")
    return normalized


def _present(fields):
    return {key: value for key, value in fields.items() if value is not None}


def build_workflow_origin(
    *, scope_type, scope_id, workflow_id, run_id=None, task_id=None, node_id=None,
    output_key=None, definition_revision=None,
):
    """Build a validated workflow origin; optional values that are None are omitted."""
    origin = {
        "version": ORIGIN_SCHEMA_VERSION,
        "kind": ORIGIN_KIND_WORKFLOW,
        "workflow_scope": {"type": scope_type, "id": scope_id},
        "workflow_id": workflow_id,
    }
    origin.update(_present({
        "run_id": run_id,
        "task_id": task_id,
        "node_id": node_id,
        "output_key": output_key,
        "definition_revision": definition_revision,
    }))
    return validate_origin(origin)


def build_chat_origin(
    *, conversation_id, message_id=None, orchestration_run_id=None, orchestration_step_id=None,
    collaboration_conversation_id=None,
):
    """Build a validated chat origin; an orchestration step is kept only with its run."""
    if orchestration_run_id is None:
        orchestration_step_id = None
    origin = {
        "version": ORIGIN_SCHEMA_VERSION,
        "kind": ORIGIN_KIND_CHAT,
        "conversation_id": conversation_id,
    }
    origin.update(_present({
        "message_id": message_id,
        "orchestration_run_id": orchestration_run_id,
        "orchestration_step_id": orchestration_step_id,
        "collaboration_conversation_id": collaboration_conversation_id,
    }))
    return validate_origin(origin)


def chat_upload_origin(*, conversation_id, message_id=None, collaboration_conversation_id=None):
    """Return the chat origin for a file uploaded into an authorized chat, or None if unprovable."""
    try:
        return build_chat_origin(
            conversation_id=conversation_id,
            message_id=_id_text(message_id),
            collaboration_conversation_id=_id_text(collaboration_conversation_id),
        )
    except DocumentOriginError as exc:
        _log_event(
            "[DocumentProvenance] A chat upload was saved without an origin because its conversation "
            "reference is not a valid origin value.",
            extra={"error": str(exc)},
            level=logging.WARNING,
        )
        return None


def stored_document_origin(document):
    """Return the validated origin stored on a document version, or None."""
    if not isinstance(document, Mapping) or document.get(ORIGIN_FIELD) is None:
        return None
    try:
        return validate_origin(document[ORIGIN_FIELD])
    except DocumentOriginError:
        return None


def document_origin_kind(document):
    """Return ``'workflow'``, ``'chat'``, or None for a document version."""
    origin = stored_document_origin(document)
    return origin["kind"] if origin else None


def apply_document_provenance(metadata, *, origin=None, server_tags=None):
    """Stamp new document-version metadata with its server-derived origin and server tags.

    Any origin fields already present (for example carried from a copied record) are removed
    first, so each version holds only the origin its own creator supplied.
    """
    for field_name in ORIGIN_FIELD_NAMES:
        metadata.pop(field_name, None)
    if origin is not None:
        metadata[ORIGIN_FIELD] = validate_origin(origin)
    tags = [tag for tag in (server_tags or ()) if isinstance(tag, str) and _SERVER_TAG.match(tag)]
    if tags:
        current = metadata.get("tags")
        merged = [tag for tag in current if isinstance(tag, str)] if isinstance(current, list) else []
        for tag in tags:
            if tag not in merged:
                merged.append(tag)
        metadata["tags"] = merged
    return metadata


def _read_conversation(conversation_id):
    if not _is_origin_text(conversation_id):
        return None
    try:
        conversation = import_module("config").cosmos_conversations_container.read_item(
            item=conversation_id,
            partition_key=conversation_id,
        )
    except Exception as exc:
        if not _is_not_found(exc):
            _log_event(
                "[DocumentProvenance] A conversation could not be read for document provenance.",
                extra={"conversation_id": conversation_id, "error_type": type(exc).__name__},
                level=logging.WARNING,
            )
        return None
    return conversation if isinstance(conversation, Mapping) else None


def _read_collaboration_conversation(conversation_id):
    if not _is_origin_text(conversation_id):
        return None
    try:
        conversation = import_module("functions_collaboration").get_collaboration_conversation(conversation_id)
    except Exception as exc:
        if not _is_not_found(exc):
            _log_event(
                "[DocumentProvenance] A shared conversation could not be read for document provenance.",
                extra={"conversation_id": conversation_id, "error_type": type(exc).__name__},
                level=logging.WARNING,
            )
        return None
    return conversation if isinstance(conversation, Mapping) else None


def _load_scope_workflow(scope_type, scope_id, workflow_id):
    if not (_is_origin_text(scope_id) and _is_origin_text(workflow_id)):
        return None
    try:
        if scope_type == "group":
            workflow = import_module("functions_group_workflows").get_group_workflow(scope_id, workflow_id)
            if isinstance(workflow, Mapping) and workflow.get("group_id") != scope_id:
                return None
        elif scope_type == "personal":
            workflow = import_module("functions_personal_workflows").get_personal_workflow(scope_id, workflow_id)
        else:
            return None
    except Exception as exc:
        _log_event(
            "[DocumentProvenance] A workflow could not be read for document provenance.",
            extra={"workflow_id": workflow_id, "scope_type": scope_type, "error_type": type(exc).__name__},
            level=logging.WARNING,
        )
        return None
    return workflow if isinstance(workflow, Mapping) else None


def _proven_definition_revision(workflow, run_id):
    """Return the run's definition revision only when the runtime journal proves it."""
    if not isinstance(workflow, Mapping) or workflow.get("definition_version") != 3 or not run_id:
        return None
    try:
        store = import_module("functions_workflow_runtime_store").workflow_runtime_store(workflow, run_id)
        control = store.read()
    except Exception:
        return None
    revision = control.get("definition_revision") if isinstance(control, Mapping) else None
    return revision if isinstance(revision, str) and _DIGEST.match(revision) else None


def _receipt_output_key(receipt, workflow_id, run_id):
    producer = _mapping(_mapping(receipt).get("producer"))
    if not run_id or producer.get("workflow_id") != workflow_id or producer.get("run_id") != run_id:
        return None
    return _id_text(_mapping(receipt).get("output_name"))


def _is_run_conversation(conversation_id, workflow_id, run_id):
    expected = uuid.uuid5(uuid.NAMESPACE_URL, f"workflow-conversation:{workflow_id}:{run_id}")
    return str(expected) == conversation_id


def _latest_conversation_run_id(scope_type, scope_id, conversation_id, workflow_id):
    try:
        if scope_type == "group":
            run = import_module("functions_group_workflows").get_latest_group_workflow_run_for_conversation(
                scope_id, conversation_id, workflow_id=workflow_id,
            )
        else:
            run = import_module("functions_personal_workflows").get_latest_personal_workflow_run_for_conversation(
                scope_id, conversation_id, workflow_id=workflow_id,
            )
    except Exception as exc:
        _log_event(
            "[DocumentProvenance] The latest workflow run could not be read for document provenance.",
            extra={"conversation_id": conversation_id, "error_type": type(exc).__name__},
            level=logging.WARNING,
        )
        return None
    return _id_text(run.get("id")) if isinstance(run, Mapping) else None


def _conversation_scope(conversation):
    group_id = conversation.get("group_id")
    if group_id:
        return "group", group_id
    return "personal", conversation.get("user_id")


def _saved_output_origin(binding, receipt):
    scope = _mapping(binding.get("scope"))
    producer = _mapping(binding.get("producer"))
    scope_type, scope_id = scope.get("type"), scope.get("id")
    workflow_id = producer.get("workflow_id")
    run_id = _id_text(producer.get("run_id"))
    workflow = _load_scope_workflow(scope_type, scope_id, workflow_id)
    return build_workflow_origin(
        scope_type=scope_type,
        scope_id=scope_id,
        workflow_id=workflow_id,
        run_id=run_id,
        task_id=_id_text(producer.get("task_id")),
        node_id=_id_text(producer.get("node_id")),
        output_key=_receipt_output_key(receipt, workflow_id, run_id),
        definition_revision=_proven_definition_revision(workflow, run_id),
    )


def _producer_workflow_origin(conversation, producer, receipt):
    scope_type, scope_id = _conversation_scope(conversation)
    workflow_id = producer.get("workflow_id")
    run_id = _id_text(producer.get("run_id"))
    workflow = _load_scope_workflow(scope_type, scope_id, workflow_id)
    return build_workflow_origin(
        scope_type=scope_type,
        scope_id=scope_id,
        workflow_id=workflow_id,
        run_id=run_id,
        task_id=_id_text(producer.get("task_id")),
        node_id=_id_text(producer.get("node_id")),
        output_key=_receipt_output_key(receipt, workflow_id, run_id),
        definition_revision=_proven_definition_revision(workflow, run_id),
    )


def _conversation_workflow_origin(conversation, receipt):
    """Stamp an artifact published inside a workflow conversation as that workflow's output.

    The run is recorded only when the per-run conversation id proves it, so a reused
    conversation never attributes a document to the wrong run.
    """
    scope_type, scope_id = _conversation_scope(conversation)
    workflow_id = conversation.get("workflow_id")
    conversation_id = conversation.get("id")
    receipt_producer = _mapping(_mapping(receipt).get("producer"))
    candidate = None
    if _is_origin_text(workflow_id) and receipt_producer.get("workflow_id") == workflow_id:
        candidate = _id_text(receipt_producer.get("run_id"))
    if candidate is None and _is_origin_text(workflow_id) and _is_origin_text(scope_id):
        candidate = _latest_conversation_run_id(scope_type, scope_id, conversation_id, workflow_id)
    run_id = candidate if candidate and _is_run_conversation(conversation_id, workflow_id, candidate) else None
    workflow = _load_scope_workflow(scope_type, scope_id, workflow_id)
    return build_workflow_origin(
        scope_type=scope_type,
        scope_id=scope_id,
        workflow_id=workflow_id,
        run_id=run_id,
        output_key=_receipt_output_key(receipt, workflow_id, run_id),
        definition_revision=_proven_definition_revision(workflow, run_id),
    )


def derive_publication_origin(artifact, *, source_receipt=None):
    """Derive a published chat artifact's origin from server-held bindings only.

    Precedence: a workflow saved-output binding, then a workflow producer or a workflow
    conversation, then an orchestration producer, then the chat that holds the artifact.
    Returns None when the origin cannot be proven; raises DocumentOriginError when the
    server-held values are not valid origin values.
    """
    artifact = _mapping(artifact)
    metadata = _mapping(artifact.get("metadata"))
    binding = _mapping(metadata.get("generated_artifact_source"))
    receipt = source_receipt if isinstance(source_receipt, Mapping) else _mapping(binding.get("source_receipt"))
    if binding.get("kind") == "workflow_saved_output":
        return _saved_output_origin(binding, receipt)

    conversation_id = artifact.get("conversation_id")
    conversation = _read_conversation(conversation_id)
    if conversation is None:
        _log_event(
            "[DocumentProvenance] A published artifact was saved without an origin because its "
            "conversation could not be read.",
            extra={"conversation_id": conversation_id},
            level=logging.WARNING,
        )
        return None

    producer = _mapping(metadata.get("analysis_producer"))
    in_workflow_conversation = conversation.get("chat_type") == "workflow"
    if producer.get("kind") == "workflow":
        if not in_workflow_conversation:
            _log_event(
                "[DocumentProvenance] A published artifact was saved without an origin because its "
                "workflow producer is outside a workflow conversation.",
                extra={"conversation_id": conversation_id},
                level=logging.WARNING,
            )
            return None
        return _producer_workflow_origin(conversation, producer, receipt)
    if in_workflow_conversation:
        return _conversation_workflow_origin(conversation, receipt)

    orchestration = {}
    if binding.get("kind") == "orchestration_retained_output":
        orchestration = _mapping(binding.get("producer"))
    elif producer.get("kind") == "orchestration":
        orchestration = producer
    return build_chat_origin(
        conversation_id=conversation_id,
        message_id=_id_text(artifact.get("id")),
        orchestration_run_id=_id_text(orchestration.get("run_id")),
        orchestration_step_id=_id_text(orchestration.get("step_id")),
        collaboration_conversation_id=_id_text(conversation.get("collaboration_conversation_id")),
    )


def _workflow_tag_allowed(user_id, destination):
    """Create the destination's ``workflow`` tag definition when the actor may manage tags there."""
    destination = _mapping(destination)
    scope = destination.get("workspace_scope")
    tag_arguments = {"workspace_type": scope}
    try:
        if scope == "group":
            group_id = destination.get("group_id")
            import_module("functions_group_document_access").require_group_document_management_context(
                user_id, group_id, "manage_tags",
            )
            tag_arguments["group_id"] = group_id
        elif scope == "public":
            workspace_id = destination.get("public_workspace_id")
            import_module("functions_public_document_access").require_public_document_management_context(
                user_id, workspace_id, "manage_tags",
            )
            tag_arguments["public_workspace_id"] = workspace_id
        elif scope != "personal":
            return False
    except Exception as exc:
        _log_event(
            "[DocumentProvenance] The workflow tag was skipped because the publishing user cannot "
            "manage tags in the destination workspace. The origin is still recorded.",
            extra={"workspace_scope": scope, "error_type": type(exc).__name__},
            level=logging.INFO,
        )
        return False
    try:
        import_module("functions_documents").get_or_create_tag_definition(
            user_id, WORKFLOW_ORIGIN_TAG, **tag_arguments,
        )
    except Exception as exc:
        _log_event(
            "[DocumentProvenance] The workflow tag was skipped because its tag definition could not be saved.",
            extra={"workspace_scope": scope, "error_type": type(exc).__name__},
            level=logging.WARNING,
        )
        return False
    return True


def publication_origin_fields(user_id, artifact, *, source_receipt=None, destination=None):
    """Return ``create_document`` keyword arguments that stamp a published artifact's origin.

    Never raises: provenance must not block publication, so a failure is logged and the
    document is created without an origin. Only workflow origins receive the ``workflow`` tag.
    """
    try:
        origin = derive_publication_origin(artifact, source_receipt=source_receipt)
    except Exception as exc:
        _log_event(
            "[DocumentProvenance] A published artifact was saved without an origin because its "
            "origin could not be derived.",
            extra={"error_type": type(exc).__name__, "error": str(exc)},
            level=logging.WARNING,
        )
        return {}
    if origin is None:
        return {}
    fields = {"origin": origin}
    if origin["kind"] == ORIGIN_KIND_WORKFLOW and _workflow_tag_allowed(user_id, destination):
        fields["server_tags"] = [WORKFLOW_ORIGIN_TAG]
    return fields


def _session_user_roles():
    if not has_request_context():
        return []
    user = session.get("user")
    roles = user.get("roles") if isinstance(user, Mapping) else None
    return list(roles) if isinstance(roles, (list, tuple)) else []


def _current_settings():
    return import_module("functions_settings").get_settings() or {}


def _collaboration_enabled(settings):
    return bool(_mapping(settings).get("enable_collaborative_conversations", False))


def _display_text(value, fallback):
    if not isinstance(value, str):
        return fallback
    text = " ".join(_CONTROL_CHARACTERS.sub(" ", value).split())
    if not text:
        return fallback
    if len(text) > _MAX_LABEL_TEXT_LENGTH:
        text = text[:_MAX_LABEL_TEXT_LENGTH - 1].rstrip() + "\u2026"
    return text


def workflow_origin_href(scope_type, scope_id, workflow_id, run_id=None):
    """Return the V2 route that opens a workflow, and optionally one run, in its history."""
    query = f"workflow_id={quote(workflow_id, safe='')}"
    if run_id:
        query += f"&run_id={quote(run_id, safe='')}"
    if scope_type == "group":
        return f"/groups/{quote(scope_id, safe='')}/workflows?{query}"
    return f"/workspace/workflows?{query}"


def chat_origin_href(conversation_id):
    """Return the V2 route that opens a conversation on the chat page."""
    return f"/chat?conversationId={quote(conversation_id, safe='')}"


def _authorized_workflow(user_id, scope_type, scope_id, workflow_id, settings, user_roles):
    """Return the origin workflow only when this reader may open it in the workflow history."""
    settings_module = import_module("functions_settings")
    if scope_type == "personal":
        if not user_id or scope_id != user_id:
            return None
        if not settings_module.is_user_workflows_enabled_for_user(settings, user_roles=user_roles):
            return None
    elif scope_type == "group":
        if not _mapping(settings).get("enable_group_workspaces"):
            return None
        if not settings_module.is_group_workflows_enabled_for_group(settings, scope_id):
            return None
        member_roles = import_module("functions_group_workflow_policy").GROUP_WORKFLOW_MEMBER_ROLES
        try:
            import_module("functions_group").assert_group_role(user_id, scope_id, allowed_roles=member_roles)
        except (PermissionError, LookupError):
            return None
    else:
        return None
    return _load_scope_workflow(scope_type, scope_id, workflow_id)


def _authorized_run(user_id, scope_type, scope_id, workflow, workflow_id, run_id):
    """Return the origin run only when it belongs to the workflow and this reader may read it."""
    if not run_id or not isinstance(workflow, Mapping):
        return None
    try:
        if scope_type == "group":
            run = import_module("functions_group_workflows").get_group_workflow_run(scope_id, run_id)
        else:
            run = import_module("functions_personal_workflows").get_personal_workflow_run(scope_id, run_id)
        if not isinstance(run, Mapping) or run.get("workflow_id") != workflow_id:
            return None
        import_module("functions_workflow_results").authorize_workflow_run_read(
            workflow, run_id, reader_user_id=user_id,
        )
    except _EXPECTED_ACCESS_ERRORS:
        return None
    except Exception as exc:
        _log_event(
            "[DocumentProvenance] A workflow run could not be authorized for a document origin.",
            extra={"workflow_id": workflow_id, "run_id": run_id, "error_type": type(exc).__name__},
            level=logging.WARNING,
        )
        return None
    return run


def _workflow_origin_summary(user_id, origin, settings, user_roles):
    scope = origin["workflow_scope"]
    workflow_id = origin["workflow_id"]
    workflow = _authorized_workflow(user_id, scope["type"], scope["id"], workflow_id, settings, user_roles)
    if workflow is None:
        return None
    summary = {
        "kind": ORIGIN_KIND_WORKFLOW,
        "label": f"Created by {_display_text(workflow.get('name'), UNTITLED_WORKFLOW_LABEL)}",
        "href": workflow_origin_href(scope["type"], scope["id"], workflow_id),
    }
    run_id = origin.get("run_id")
    run = _authorized_run(user_id, scope["type"], scope["id"], workflow, workflow_id, run_id)
    if run is not None:
        summary["href"] = workflow_origin_href(scope["type"], scope["id"], workflow_id, run_id)
        started_at = run.get("started_at")
        if _is_origin_text(started_at) and len(started_at) <= _MAX_TIMESTAMP_LENGTH:
            summary["run_started_at"] = started_at
    return summary


def _participating_collaboration(user_id, collaboration_id):
    collaboration = _read_collaboration_conversation(collaboration_id)
    if collaboration is None:
        return None
    try:
        import_module("functions_collaboration").assert_user_can_participate_in_collaboration_conversation(
            user_id, collaboration,
        )
    except _EXPECTED_ACCESS_ERRORS:
        return None
    return collaboration


def _chat_summary(conversation_id, title):
    return {
        "kind": ORIGIN_KIND_CHAT,
        "label": f"Created in chat \u00b7 {_display_text(title, UNTITLED_CONVERSATION_LABEL)}",
        "href": chat_origin_href(conversation_id),
    }


def _chat_origin_summary(user_id, origin, settings):
    conversation = _read_conversation(origin["conversation_id"])
    if conversation is None:
        return None
    try:
        context = import_module("functions_collaboration").build_conversation_participation_context(
            user_id, conversation,
        )
    except _EXPECTED_ACCESS_ERRORS:
        return None
    collaboration_id = (
        _id_text(_mapping(context).get("collaboration_conversation_id"))
        or origin.get("collaboration_conversation_id")
    )
    if collaboration_id and _collaboration_enabled(settings):
        collaboration = _participating_collaboration(user_id, collaboration_id)
        if collaboration is not None:
            return _chat_summary(collaboration_id, collaboration.get("title"))
    if _mapping(context).get("is_owner"):
        return _chat_summary(origin["conversation_id"], conversation.get("title"))
    return None


def _fallback_summary(kind):
    label = WORKFLOW_FALLBACK_LABEL if kind == ORIGIN_KIND_WORKFLOW else CHAT_FALLBACK_LABEL
    return {"kind": kind, "label": label}


def resolve_origin_summary(user_id, document, *, settings=None, user_roles=None):
    """Resolve a browser-safe summary of a document's origin for one reader.

    Readers who may open the origin get its name or title and a V2 link. Everyone else
    (including when the origin was deleted) gets plain text with no names, titles, or ids.
    """
    origin = stored_document_origin(document)
    if origin is None:
        return None
    summary = None
    try:
        if settings is None:
            settings = _current_settings()
        if user_roles is None:
            user_roles = _session_user_roles()
        if origin["kind"] == ORIGIN_KIND_WORKFLOW:
            summary = _workflow_origin_summary(user_id, origin, settings, user_roles)
        else:
            summary = _chat_origin_summary(user_id, origin, settings)
    except Exception as exc:
        _log_event(
            "[DocumentProvenance] A document origin summary could not be resolved; plain text is shown.",
            extra={"origin_kind": origin["kind"], "error_type": type(exc).__name__},
            level=logging.WARNING,
        )
        summary = None
    return summary or _fallback_summary(origin["kind"])


def summary_requested(args):
    """Return True when a detail read opted in with ``origin_summary=1`` or ``origin_summary=true``."""
    value = args.get(ORIGIN_SUMMARY_PARAM) if args is not None else None
    return isinstance(value, str) and value.strip().lower() in _TRUE_VALUES


def remember_document_origin_summary(user_id, record):
    """Resolve a detail read's origin summary and keep it for the response guard to attach."""
    if not has_request_context() or document_origin_kind(record) is None:
        return None
    document_id = record.get("id")
    if not isinstance(document_id, str) or not document_id:
        return None
    summary = resolve_origin_summary(user_id, record)
    if summary is None:
        return None
    summaries = getattr(g, _SUMMARY_STASH, None)
    if not isinstance(summaries, dict):
        summaries = {}
        setattr(g, _SUMMARY_STASH, summaries)
    summaries[document_id] = summary
    return summary


def attached_origin_summary(payload):
    """Return a projected single-document payload with its remembered origin summary attached."""
    if not has_request_context() or not isinstance(payload, dict):
        return payload
    summaries = getattr(g, _SUMMARY_STASH, None)
    if not isinstance(summaries, dict) or not summaries:
        return payload
    document_id = payload.get("id")
    summary = summaries.get(document_id) if isinstance(document_id, str) else None
    if not isinstance(summary, dict) or payload.get(ORIGIN_KIND_FIELD) != summary.get("kind"):
        return payload
    return {**payload, ORIGIN_SUMMARY_FIELD: dict(summary)}


def _single_filter_value(args, name):
    if args is None:
        return None
    values = args.getlist(name) if hasattr(args, "getlist") else (
        [] if args.get(name) is None else [args.get(name)]
    )
    values = [value for value in values if value != ""]
    if not values:
        return None
    if len(values) > 1:
        raise DocumentOriginFilterError(f"Provide {name} at most once.")
    if not _is_origin_text(values[0]):
        raise DocumentOriginFilterError(f"{name} is invalid.")
    return values[0]


def _workflow_filter(user_id, workflow_id, run_id, group_id, settings, user_roles):
    scope = None
    workflow = _authorized_workflow(user_id, "personal", user_id, workflow_id, settings, user_roles)
    if workflow is not None:
        scope = ("personal", user_id)
    elif group_id:
        workflow = _authorized_workflow(user_id, "group", group_id, workflow_id, settings, user_roles)
        if workflow is not None:
            scope = ("group", group_id)
    if scope is None:
        raise DocumentOriginFilterError(ORIGIN_NOT_FOUND_MESSAGE, 404)
    if run_id is not None and _authorized_run(user_id, scope[0], scope[1], workflow, workflow_id, run_id) is None:
        raise DocumentOriginFilterError(ORIGIN_NOT_FOUND_MESSAGE, 404)
    conditions = [
        "c.origin.kind = @origin_kind",
        "c.origin.workflow_scope.type = @origin_scope_type",
        "c.origin.workflow_scope.id = @origin_scope_id",
        "c.origin.workflow_id = @origin_workflow_id",
    ]
    parameters = [
        {"name": "@origin_kind", "value": ORIGIN_KIND_WORKFLOW},
        {"name": "@origin_scope_type", "value": scope[0]},
        {"name": "@origin_scope_id", "value": scope[1]},
        {"name": "@origin_workflow_id", "value": workflow_id},
    ]
    if run_id is not None:
        conditions.append("c.origin.run_id = @origin_run_id")
        parameters.append({"name": "@origin_run_id", "value": run_id})
    return conditions, parameters


def _conversation_filter_allowed(user_id, conversation_id, settings):
    try:
        conversation = _read_conversation(conversation_id)
        if conversation is not None:
            context = _mapping(import_module("functions_collaboration").build_conversation_participation_context(
                user_id, conversation,
            ))
            return bool(context.get("is_owner")) or (
                bool(context.get("collaboration_conversation_id")) and _collaboration_enabled(settings)
            )
        if not _collaboration_enabled(settings):
            return False
        return _participating_collaboration(user_id, conversation_id) is not None
    except _EXPECTED_ACCESS_ERRORS:
        return False
    except Exception as exc:
        _log_event(
            "[DocumentProvenance] A conversation origin filter could not be authorized.",
            extra={"error_type": type(exc).__name__},
            level=logging.WARNING,
        )
        return False


def origin_list_filter(user_id, args, *, group_id=None, settings=None, user_roles=None):
    """Return ``(conditions, parameters)`` for a document list origin filter, or None.

    The caller appends the conditions to its own scoped, parameterized Cosmos query, so the
    filter never widens the list's partition or access scope. Raises DocumentOriginFilterError
    (400 for malformed input, 404 when the reader cannot open the named origin).
    """
    workflow_id = _single_filter_value(args, ORIGIN_WORKFLOW_FILTER_PARAM)
    run_id = _single_filter_value(args, ORIGIN_RUN_FILTER_PARAM)
    conversation_id = _single_filter_value(args, ORIGIN_CONVERSATION_FILTER_PARAM)
    if workflow_id is None and run_id is None and conversation_id is None:
        return None
    if run_id is not None and workflow_id is None:
        raise DocumentOriginFilterError(f"{ORIGIN_RUN_FILTER_PARAM} requires {ORIGIN_WORKFLOW_FILTER_PARAM}.")
    if conversation_id is not None and workflow_id is not None:
        raise DocumentOriginFilterError("Filter documents by a workflow or by a conversation, not both.")
    if settings is None:
        settings = _current_settings()
    if user_roles is None:
        user_roles = _session_user_roles()
    if workflow_id is not None:
        conditions, parameters = _workflow_filter(user_id, workflow_id, run_id, group_id, settings, user_roles)
    else:
        if not _conversation_filter_allowed(user_id, conversation_id, settings):
            raise DocumentOriginFilterError(ORIGIN_NOT_FOUND_MESSAGE, 404)
        conditions = [
            "c.origin.kind = @origin_kind",
            "(c.origin.conversation_id = @origin_conversation_id "
            "OR c.origin.collaboration_conversation_id = @origin_conversation_id)",
        ]
        parameters = [
            {"name": "@origin_kind", "value": ORIGIN_KIND_CHAT},
            {"name": "@origin_conversation_id", "value": conversation_id},
        ]
    conditions.append("c.is_current_version = true")
    return conditions, parameters


def origin_filter_requested(args):
    """Return True when a list request names any origin filter parameter."""
    return args is not None and any(name in args for name in ORIGIN_FILTER_PARAMS)


def _is_origin_key(key):
    return isinstance(key, str) and key.replace("_", "").replace("-", "").lower() in _ORIGIN_KEY_NAMES


def reject_origin_fields(payload):
    """Raise DocumentOriginError when a client payload names an origin field at any depth."""
    pending = [payload]
    while pending:
        current = pending.pop()
        if isinstance(current, Mapping):
            for key, value in current.items():
                if _is_origin_key(key):
                    raise DocumentOriginError()
                if isinstance(value, (Mapping, list, tuple)):
                    pending.append(value)
        elif isinstance(current, (list, tuple)):
            pending.extend(item for item in current if isinstance(item, (Mapping, list, tuple)))

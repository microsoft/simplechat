# functions_action_auth_state.py
"""Actor-private, metadata-only action authentication requests and bindings.

Azure, settings, identity storage and connector imports occur only at operation
boundaries. Neither pending records nor execution receipts contain credentials,
chat messages, model history, plan arguments, or hydrated action manifests.
"""

import hashlib
import json
import time
import uuid
from collections import deque
from contextvars import ContextVar
from copy import deepcopy
from importlib import import_module

from functions_action_auth import (
    ACTION_AUTH_PROFILES,
    ACTION_AUTH_SHARING_NOTICE,
    ActionAuthConflict,
    ActionAuthStorageError,
    ActionCredentialsRequired,
    _action_auth_actor,
    _requirement_uuid,
    action_auth_fingerprint,
    get_action_auth_destination,
    get_action_credential_requirement,
    normalize_action_identity_name,
    validate_action_credential_requirement,
)


REQUEST_TTL_SECONDS = 900
BINDING_RECORD_TYPE = "binding"
REQUEST_RECORD_TYPE = "request"
_CONTEXT_FIELDS = frozenset({"agent_info", "action_ref", "run_id", "conversation_id", "conversation_kind"})
_MAX_AGENTS = 32
_MAX_ACTIONS = 128
_MAX_DELEGATION_DEPTH = 3  # Matches the existing task-local delegation runtime.
_UNAVAILABLE = "The selected action, agent, or conversation is unavailable."
_STALE = "The action, selection, or identity changed. Check the selected action again."
_AUTHENTICATION_REJECTED = "authentication_rejected"
_resolution_receipt = ContextVar("action_auth_resolution_receipt", default=None)


class ActionAuthValidationError(ValueError):
    """A stable connector outcome, never an SDK exception or response body."""

    def __init__(self, code, message, status_code=400):
        super().__init__(message)
        self.code = code
        self.safe_message = message
        self.status_code = status_code


def _now():
    return int(time.time())


def _identifier(value, *, maximum=128):
    if (
        not isinstance(value, str) or not value or value != value.strip() or len(value) > maximum
        or any(ord(character) < 32 or character in "/\\?#" for character in value)
    ):
        raise ValueError("Invalid action authentication reference.")
    return value


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _storage():
    # Lazy bootstrap: validation and schema import must never initialize Cosmos.
    try:
        container = getattr(import_module("config"), "cosmos_personal_action_auth_container")
        if container is None:
            raise ActionAuthStorageError()
        return container
    except Exception:
        raise ActionAuthStorageError() from None


def _read_record(user_id, record_id, record_type, *, missing_ok=False):
    try:
        record = _storage().read_item(item=record_id, partition_key=user_id)
    except Exception as error:
        if getattr(error, "status_code", None) == 404:
            if missing_ok:
                return None
            raise LookupError("Authentication request not found.") from None
        raise ActionAuthStorageError() from None
    if (
        not isinstance(record, dict) or record.get("user_id") != user_id
        or record.get("id") != record_id or record.get("record_type") != record_type
    ):
        raise LookupError("Authentication request not found.")
    return record


def _create_record(record):
    try:
        _storage().create_item(body=deepcopy(record))
    except Exception as error:
        if getattr(error, "status_code", None) in (409, 412):
            raise ActionAuthConflict("Authentication is being updated. Check again.", code="action_auth_busy") from None
        raise ActionAuthStorageError() from None
    return _read_record(record["user_id"], record["id"], record["record_type"])


def _replace_record(record, **updates):
    if not record.get("_etag"):
        raise ActionAuthConflict(_STALE, code="action_auth_stale")
    body = {key: deepcopy(value) for key, value in record.items() if not key.startswith("_")}
    body.update(deepcopy(updates))
    body["updated_at"] = _now()
    # Conditional writes require Azure only while operating on persisted state.
    conditions = import_module("azure.core").MatchConditions
    try:
        _storage().replace_item(
            item=record["id"], body=body, etag=record["_etag"], match_condition=conditions.IfNotModified,
        )
    except Exception as error:
        if getattr(error, "status_code", None) in (404, 409, 412):
            raise ActionAuthConflict("Authentication changed or is being updated. Check again.", code="action_auth_conflict") from None
        raise ActionAuthStorageError() from None
    return _read_record(record["user_id"], record["id"], record["record_type"])


def _records(user_id, record_type, **filters):
    query = "SELECT * FROM c WHERE c.user_id = @user_id AND c.record_type = @record_type"
    parameters = [{"name": "@user_id", "value": user_id}, {"name": "@record_type", "value": record_type}]
    for field, value in filters.items():
        query += f" AND c.{field} = @{field}"
        parameters.append({"name": f"@{field}", "value": value})
    try:
        records = list(_storage().query_items(query=query, parameters=parameters, partition_key=user_id))
    except Exception:
        raise ActionAuthStorageError() from None
    return [
        record for record in records if isinstance(record, dict) and record.get("user_id") == user_id
        and record.get("record_type") == record_type
        and all(record.get(field) == value for field, value in filters.items())
    ]


def _settings():
    settings = import_module("functions_settings").get_settings()
    if not isinstance(settings, dict):
        raise ActionAuthStorageError()
    return settings


def _context_payload(payload, *, strict):
    if not isinstance(payload, dict) or (strict and set(payload) - _CONTEXT_FIELDS):
        raise ValueError("Supply only an agent, action, run, and conversation selection.")
    context = {key: deepcopy(payload[key]) for key in _CONTEXT_FIELDS if key in payload}
    for key in ("run_id", "conversation_id"):
        if context.get(key) not in (None, ""):
            context[key] = _identifier(context[key])
        else:
            context[key] = None
    kind = context.get("conversation_kind") or "personal"
    if kind not in ("personal", "collaboration"):
        raise ValueError("Invalid conversation selection.")
    context["conversation_kind"] = kind
    if context.get("action_ref") not in (None, ""):
        import_module("functions_action_catalog")._parse_action_ref(context["action_ref"])
    else:
        context.pop("action_ref", None)
    return context


def _conversation(user_id, context, settings):
    conversation_id = context.get("conversation_id")
    kind = context["conversation_kind"]
    if not conversation_id:
        if kind == "collaboration":
            raise ValueError("Select a shared conversation.")
        return {"id": None, "kind": "personal", "source_id": None, "owner_user_id": user_id}
    collaboration = import_module("functions_collaboration")
    config = import_module("config")
    try:
        if kind == "collaboration":
            visible = collaboration.get_collaboration_conversation(conversation_id)
            if not settings.get("enable_collaborative_conversations", False):
                raise PermissionError(_UNAVAILABLE)
            collaboration.assert_user_can_participate_in_collaboration_conversation(user_id, visible)
            if visible.get("id") != conversation_id:
                raise PermissionError(_UNAVAILABLE)
            source_id = visible.get("source_conversation_id") or None
            owner = visible.get("created_by_user_id")
            if source_id:
                source = config.cosmos_conversations_container.read_item(item=source_id, partition_key=source_id)
                if source.get("collaboration_conversation_id") != conversation_id or source.get("id") != source_id:
                    raise PermissionError(_UNAVAILABLE)
                owner = source.get("user_id")
            return {"id": conversation_id, "kind": "collaboration", "source_id": source_id, "owner_user_id": owner}
        source = config.cosmos_conversations_container.read_item(item=conversation_id, partition_key=conversation_id)
        if source.get("id") != conversation_id:
            raise PermissionError(_UNAVAILABLE)
        if collaboration.is_collaboration_source_conversation(source):
            visible_id = source.get("collaboration_conversation_id")
            if not visible_id:
                raise PermissionError(_UNAVAILABLE)
            return _conversation(
                user_id, {"conversation_id": visible_id, "conversation_kind": "collaboration"}, settings,
            )
        collaboration.build_conversation_participation_context(user_id, source)
        if source.get("user_id") != user_id:
            raise PermissionError(_UNAVAILABLE)
        return {"id": conversation_id, "kind": "personal", "source_id": conversation_id, "owner_user_id": user_id}
    except (PermissionError, LookupError):
        raise PermissionError(_UNAVAILABLE) from None
    except Exception as error:
        if getattr(error, "status_code", None) == 404:
            raise LookupError(_UNAVAILABLE) from None
        raise


def _agent_scopes(user_id, settings):
    scopes = [("global", "global")]
    if settings.get("allow_user_agents", False):
        scopes.append(("personal", user_id))
    if settings.get("enable_group_workspaces", False) and settings.get("allow_group_agents", False):
        catalog = import_module("functions_action_catalog")
        scopes.extend(("group", group["id"]) for group in catalog.resolve_current_user_groups(user_id))
    return scopes


def _resolve_agent(user_id, selection, settings, *, any_scope=False):
    delegation = import_module("functions_agent_delegation")
    if isinstance(selection, str):
        selection = {"name": selection}
    if not isinstance(selection, dict) or not (selection.get("id") or selection.get("name")):
        raise ValueError("Select a stored agent.")
    if selection.get("id"):
        # agent_reference also rejects conflicting global/group flags.
        reference = delegation.agent_reference(selection, user_id)
        return delegation.resolve_delegation_agent(reference, user_id=user_id, settings=settings)
    name = selection.get("name")
    if not isinstance(name, str) or not name.strip() or len(name) > 200:
        raise ValueError("Select a stored agent.")
    if any_scope:
        scopes = _agent_scopes(user_id, settings)
    elif selection.get("scope_type") == "global" or selection.get("is_global"):
        if selection.get("is_group"):
            raise ValueError("Agent scope is ambiguous.")
        scopes = [("global", "global")]
    elif selection.get("scope_type") == "group" or selection.get("is_group"):
        group_id = selection.get("group_id") or selection.get("scope_id")
        if not group_id:
            group_id = import_module("functions_group").require_active_group(user_id)
        scopes = [("group", _identifier(group_id))]
    else:
        if selection.get("scope_id") not in (None, user_id) or selection.get("user_id") not in (None, user_id):
            raise PermissionError(_UNAVAILABLE)
        scopes = [("personal", user_id)]
    matches = []
    for scope_type, scope_id in scopes:
        try:
            delegation._assert_scope_access(user_id, scope_type, scope_id, settings)
        except PermissionError:
            continue
        for record in delegation._list_records("agents", scope_type, scope_id):
            if record.get("name") != name:
                continue
            try:
                matches.append(delegation.resolve_delegation_agent(
                    {"id": record.get("id"), "scope_type": scope_type, "scope_id": scope_id},
                    user_id=user_id, settings=settings,
                ))
            except (PermissionError, LookupError):
                continue
    if len(matches) != 1:
        raise PermissionError(_UNAVAILABLE)
    return matches[0]


def _action_revision(action):
    return _digest({key: action.get(key) for key in (
        "id", "name", "type", "credential_requirement", "auth", "endpoint", "additionalFields",
        "is_enabled", "modified_at", "updated_at", "last_updated",
    )})


def _runtime_target(action):
    fields = action.get("additionalFields") or {}
    return (
        str(fields.get("instance") or fields.get("yamcs_instance") or "").strip(),
        str(fields.get("processor") or fields.get("yamcs_processor") or "realtime").strip(),
    )


def _requirement(action):
    requirement = get_action_credential_requirement(action)
    if requirement is None:
        return None
    validate_action_credential_requirement(action, scope_type=action.get("scope_type", "global"))
    _requirement_uuid(requirement.get("id"))
    return {
        "action_ref": action["action_ref"],
        "action_id": action["id"],
        "requirement_id": requirement["id"],
        "profile": requirement["profile"],
        "fingerprint": action_auth_fingerprint(action),
        "revision": _action_revision(action),
    }


def _assigned_actions(user_id, caller, settings):
    catalog = import_module("functions_action_catalog")
    reference = import_module("functions_agent_delegation").agent_reference(caller, user_id)
    scopes = [(reference["scope_type"], reference["scope_id"])]
    if reference["scope_type"] != "global" and settings.get("merge_global_semantic_kernel_with_workspace", False):
        scopes.append(("global", "global"))
    records = []
    for scope, scope_id in scopes:
        if not catalog._scope_enabled(settings, scope):
            continue
        records.extend((scope, scope_id, action) for action in catalog._stored_actions(scope, scope_id))
    references = caller.get("actions_to_load") or []
    if not isinstance(references, list) or len(references) > _MAX_ACTIONS:
        raise ValueError("The selected agent has too many action references.")
    for selected in references:
        if not isinstance(selected, str) or not selected:
            raise ValueError("The selected agent has an invalid action reference.")
        if selected.startswith("action:v1:"):
            scope, scope_id, action_id = catalog._parse_action_ref(selected)
            matches = [(s, owner, action) for s, owner, action in records if (s, owner, action.get("id")) == (scope, scope_id, action_id)]
        else:
            exact = [(s, owner, action) for s, owner, action in records if action.get("id") == selected]
            matches = exact or [(s, owner, action) for s, owner, action in records if action.get("name") == selected]
        if len(matches) > 1:
            raise ActionAuthConflict("An attached action is ambiguous. Select an exact action.", code="action_auth_stale")
        if not matches:
            continue
        scope, scope_id, raw = matches[0]
        if raw.get("is_enabled", True) is not True:
            continue
        if raw.get("type") == "agent":
            # The existing resolver enforces current caller attachment, governance,
            # workspace constraints and target membership; never disclose denied targets.
            try:
                _, action, target = import_module("functions_agent_delegation").resolve_delegation_call(
                    raw["id"], caller_agent=caller, user_id=user_id, settings=settings,
                )
            except (PermissionError, LookupError, ValueError):
                continue
            yield "delegate", action, target
        else:
            try:
                action = catalog.resolve_action_manifest(
                    user_id, catalog._action_ref(scope, scope_id, raw["id"]), settings=settings,
                )
            except (PermissionError, LookupError):
                continue
            yield "action", action, None


def _run_selection(user_id, run_id, conversation, settings):
    if not settings.get("enable_chat_orchestration", False):
        raise PermissionError(_UNAVAILABLE)
    run = import_module("functions_orchestration_runs").get_orchestration_run(
        run_id, user_id, conversation_id=conversation["source_id"] or conversation["id"], strict=True,
    )
    if not run or run.get("user_id") != user_id or run.get("id") != run_id:
        raise PermissionError(_UNAVAILABLE)
    if run.get("conversation_id") not in (conversation["id"], conversation["source_id"]):
        raise PermissionError(_UNAVAILABLE)
    if run.get("started_at") or run.get("completed_at") or run.get("status") in ("running", "completed", "cancelled", "failed", "superseded"):
        raise ActionAuthConflict("This plan has already started or is no longer available.", code="action_auth_stale")
    plan = run.get("plan") or {}
    if not isinstance(plan, dict) or not isinstance(plan.get("steps", []), list) or len(plan.get("steps", [])) > _MAX_ACTIONS:
        raise ValueError("The selected plan is invalid.")
    seed = (run.get("seeds") or {}).get("agent")
    agents, actions, signature = [], [], []
    for step in plan.get("steps", []):
        if not isinstance(step, dict) or not step.get("enabled", True):
            continue
        arguments = step.get("arguments") or {}
        if not isinstance(arguments, dict):
            raise ValueError("The selected plan is invalid.")
        capability = step.get("capability_id")
        if capability == "action_invoke":
            ref = arguments.get("action_ref")
            import_module("functions_action_catalog")._parse_action_ref(ref)
            actions.append(ref)
            signature.append({"step_id": step.get("id"), "action_ref": ref})
        elif capability == "agent_invoke" or arguments.get("agent_name"):
            name = arguments.get("agent_name")
            selection = seed if isinstance(seed, dict) and seed.get("name") == name else {"name": name}
            agent = _resolve_agent(user_id, selection, settings, any_scope=selection is not seed)
            agents.append(agent)
            signature.append({
                "step_id": step.get("id"),
                "agent": import_module("functions_agent_delegation").agent_reference(agent, user_id),
            })
    return agents, actions, _digest({
        "id": run_id, "revision": run.get("revision"), "plan_id": plan.get("plan_id"),
        "plan_revision": plan.get("revision"), "steps": signature,
    })


def _collect(user_id, context):
    settings = _settings()
    if context.get("run_id") and not context.get("conversation_id"):
        run = import_module("functions_orchestration_runs").get_orchestration_run(context["run_id"], user_id, strict=True)
        if not run or run.get("user_id") != user_id or run.get("id") != context["run_id"]:
            raise PermissionError(_UNAVAILABLE)
        context = {**context, "conversation_id": _identifier(run.get("conversation_id")), "conversation_kind": "personal"}
    conversation = _conversation(user_id, context, settings)
    roots, direct_refs = [], []
    selection = {"conversation_id": conversation["id"], "conversation_kind": conversation["kind"]}
    if context.get("agent_info"):
        root = _resolve_agent(user_id, context["agent_info"], settings)
        roots.append(root)
        selection["agent_info"] = import_module("functions_agent_delegation").agent_reference(root, user_id)
    if context.get("action_ref"):
        direct_refs.append(context["action_ref"])
        selection["action_ref"] = context["action_ref"]
    run_revision = None
    if context.get("run_id"):
        run_agents, run_actions, run_revision = _run_selection(user_id, context["run_id"], conversation, settings)
        roots.extend(run_agents)
        direct_refs.extend(run_actions)
        selection["run_id"] = context["run_id"]
    catalog = import_module("functions_action_catalog")
    manifests, references, graph = {}, {}, []

    def add_action(action):
        required = _requirement(action)
        if required is None:
            return
        requirement_id = required["requirement_id"]
        if requirement_id in references and references[requirement_id] != required:
            raise ActionAuthConflict("The selected actions contain conflicting requirements.", code="action_auth_stale")
        references[requirement_id] = required
        manifests[requirement_id] = action
        if len(references) > _MAX_ACTIONS:
            raise ValueError("Too many credential requirements.")

    for action_ref in dict.fromkeys(direct_refs):
        add_action(catalog.resolve_action_manifest(user_id, action_ref, settings=settings))
    queue = deque((root, 0) for root in roots)
    visited = set()
    while queue:
        caller, depth = queue.popleft()
        reference = import_module("functions_agent_delegation").agent_reference(caller, user_id)
        key = _digest(reference)
        if key in visited or depth > _MAX_DELEGATION_DEPTH:
            continue
        visited.add(key)
        if len(visited) > _MAX_AGENTS:
            raise ValueError("The selected agent call graph is too large.")
        graph.append({
            "agent": reference,
            "revision": _digest({key: caller.get(key) for key in (
                "_etag", "updated_at", "last_updated", "modified_at", "actions_to_load", "agent_type", "is_enabled",
            )}),
        })
        if caller.get("agent_type", "local") != "local":
            continue
        for kind, action, target in _assigned_actions(user_id, caller, settings):
            if kind == "action":
                add_action(action)
            elif depth < _MAX_DELEGATION_DEPTH:
                graph.append({"delegation_id": action["id"], "revision": _action_revision(action)})
                queue.append((target, depth + 1))
    snapshot = {
        "conversation": conversation,
        "selection": selection,
        "requirements": sorted(references.values(), key=lambda value: value["requirement_id"]),
        "graph": sorted(graph, key=lambda value: json.dumps(value, sort_keys=True)),
        "run_revision": run_revision,
    }
    return snapshot, manifests


def _identity_metadata(user_id, identity_id=None):
    identities = import_module("functions_workspace_identities")
    try:
        if identity_id:
            result = identities.get_workspace_identity_metadata("personal", user_id, identity_id)
            if result.get("user_id") != user_id or result.get("scope_type") != "personal":
                raise LookupError("Workspace identity not found.")
            return result
        return [
            identity for identity in identities.list_workspace_identity_metadata("personal", user_id)
            if identity.get("user_id") == user_id and identity.get("scope_type") == "personal"
        ]
    except (LookupError, PermissionError):
        raise LookupError("Workspace identity not found.") from None
    except Exception:
        raise ActionAuthStorageError() from None


def _identity_revision(identity):
    if not identity.get("_etag"):
        raise ActionAuthConflict(_STALE, code="action_auth_stale")
    return identity["_etag"]


def _compatible(identity, profile):
    if not isinstance(profile, str) or profile not in ACTION_AUTH_PROFILES:
        return False
    auth_type = ACTION_AUTH_PROFILES[profile]["auth_type"]
    identities = import_module("functions_workspace_identities")
    return bool(
        identity.get("type") == "workspace_identity"
        and identities.identity_supports_usage(identity, "action", source_type="action", auth_types={auth_type})
        and identity.get("has_password" if auth_type == "username_password" else "has_secret")
        and (auth_type != "username_password" or identity.get("has_username"))
    )


def _binding_id(user_id, requirement_id):
    return f"binding-{uuid.uuid5(uuid.NAMESPACE_URL, f'action-auth:{user_id}:{requirement_id}')}"


def _binding(user_id, required):
    return _read_record(user_id, _binding_id(user_id, required["requirement_id"]), BINDING_RECORD_TYPE, missing_ok=True)


def _valid_binding(binding, required, identity):
    return bool(
        binding and binding.get("status") == "active" and identity
        and binding.get("requirement_id") == required["requirement_id"]
        and binding.get("action_id") == required["action_id"]
        and binding.get("fingerprint") == required["fingerprint"]
        and binding.get("profile") == required["profile"]
        and binding.get("identity_id") == identity.get("id")
        and binding.get("identity_revision") == _identity_revision(identity)
        and _compatible(identity, binding.get("profile"))
    )


def _write_binding(user_id, required, action, identity, previous=None, *, validated=False):
    requirement = get_action_credential_requirement(action)
    rejections = _binding_rejections(previous) if previous is not None else {}
    revision = _identity_revision(identity)
    rejections = {
        key: marker for key, marker in rejections.items()
        if marker["identity_id"] != identity["id"] or marker["identity_revision"] == revision
    }
    if validated:
        rejections.pop(_digest(_identity_rejection_key(identity, required)), None)
    values = {
        "requirement_id": required["requirement_id"], "action_id": required["action_id"],
        "fingerprint": required["fingerprint"], "profile": requirement["profile"],
        "identity_id": identity["id"], "identity_revision": revision,
        "status": "active", "authentication_rejected_at": None,
        "authentication_rejections": rejections, "ttl": -1,
    }
    if previous is not None:
        return _replace_record(previous, **values)
    return _create_record({
        "id": _binding_id(user_id, required["requirement_id"]), "user_id": user_id,
        "record_type": BINDING_RECORD_TYPE, "created_at": _now(), "updated_at": _now(), **values,
    })


def _binding_receipt(binding):
    return {
        key: binding.get(key) for key in ("id", "identity_id", "identity_revision", "fingerprint", "_etag")
    }


def _resolution_scope(*, create=False):
    """An opaque execution/request scope, never a credential or a shared plugin cache."""
    frame = import_module("agent_execution_context").current_agent_execution()
    if frame:
        return ("execution", frame.budget.root_id, frame.invocation_id, id(frame))
    flask = import_module("flask")
    if flask.has_request_context():
        scope = getattr(flask.g, "_action_auth_resolution_scope", None)
        if scope is None and create:
            scope = str(uuid.uuid4())
            flask.g._action_auth_resolution_scope = scope
        return ("request", scope) if scope is not None else None
    return None


def _rejection_key(binding):
    return tuple(binding.get(key) for key in ("identity_id", "identity_revision", "fingerprint", "profile"))


def _identity_rejection_key(identity, required):
    return (identity["id"], _identity_revision(identity), required["fingerprint"], required["profile"])


def _binding_rejections(binding):
    """Keep failed revisions independent of a binding's current recipient/identity."""
    history = binding.get("authentication_rejections") or {}
    if not isinstance(history, dict):
        raise ActionAuthStorageError()
    markers = {}
    for key, marker in history.items():
        if (
            not isinstance(marker, dict)
            or not all(isinstance(value, str) and value for value in _rejection_key(marker))
            or key != _digest(_rejection_key(marker))
        ):
            raise ActionAuthStorageError()
        markers[key] = {
            field: deepcopy(marker[field]) for field in (
                "identity_id", "identity_revision", "fingerprint", "profile", "rejection_id", "rejected_at",
            ) if field in marker
        }
    if binding.get("status") == _AUTHENTICATION_REJECTED:
        key = _rejection_key(binding)
        if not all(isinstance(value, str) and value for value in key):
            raise ActionAuthStorageError()
        # Preserve rejections produced before revision history was recorded.
        markers.setdefault(_digest(key), {
            **{field: binding[field] for field in ("identity_id", "identity_revision", "fingerprint", "profile")},
            "rejection_id": binding.get("_etag"),
            "rejected_at": binding.get("authentication_rejected_at"),
        })
    return markers


def _clear_validated_rejections(user_id, identity, required, rejected, current_binding):
    """A successful explicit probe clears only the rejected revisions observed before it."""
    validated_key = _identity_rejection_key(identity, required)
    marker_id = _digest(validated_key)
    refreshed = []
    for previous in rejected:
        expected = _binding_rejections(previous).get(marker_id)
        if previous["id"] == current_binding["id"] or expected is None:
            continue
        current = _read_record(user_id, previous["id"], BINDING_RECORD_TYPE, missing_ok=True)
        if not current or current.get("_etag") != previous.get("_etag"):
            continue
        markers = _binding_rejections(current)
        if markers.get(marker_id) != expected:
            continue
        markers.pop(marker_id)
        updates = {"authentication_rejections": markers}
        if current.get("status") == _AUTHENTICATION_REJECTED and _rejection_key(current) == validated_key:
            updates.update(status="active", authentication_rejected_at=None)
        refreshed.append((previous, _replace_record(current, **updates)))
    return refreshed


def _inspect_requirements(user_id, snapshot, manifests, *, reuse_approved=False):
    identities = _identity_metadata(user_id) if manifests else []
    by_id = {identity["id"]: identity for identity in identities}
    bindings = _records(user_id, BINDING_RECORD_TYPE) if manifests else []
    approved = [binding for binding in bindings if binding.get("status") == "active"]
    rejected = {
        _rejection_key(marker) for binding in bindings for marker in _binding_rejections(binding).values()
    }
    missing, receipts, candidates = [], {}, {}
    for required in snapshot["requirements"]:
        action = manifests[required["requirement_id"]]
        requirement = get_action_credential_requirement(action)
        profile = requirement["profile"]
        binding = _binding(user_id, required)
        bound_identity = by_id.get((binding or {}).get("identity_id"))
        bound_rejected = bool(bound_identity and _identity_rejection_key(bound_identity, required) in rejected)
        if _valid_binding(binding, required, bound_identity) and not bound_rejected:
            receipts[required["requirement_id"]] = _binding_receipt(binding)
            continue
        named = [
            identity for identity in identities
            if normalize_action_identity_name(identity.get("name")) == normalize_action_identity_name(requirement["identity_name"])
        ]
        compatible = [identity for identity in named if _compatible(identity, profile)]
        if bound_identity and _compatible(bound_identity, profile) and bound_identity not in compatible:
            compatible.append(bound_identity)
        approved_ids = {
            existing["identity_id"] for existing in approved
            if existing.get("fingerprint") == required["fingerprint"]
            and existing.get("profile") == profile
            and _rejection_key(existing) not in rejected
            and existing.get("identity_id") in by_id
            and existing.get("identity_revision") == _identity_revision(by_id[existing["identity_id"]])
        }
        if reuse_approved and len(compatible) == 1 and compatible[0]["id"] in approved_ids:
            try:
                binding = _write_binding(user_id, required, action, compatible[0], previous=binding)
            except ActionAuthConflict:
                binding = _binding(user_id, required)
                if not _valid_binding(binding, required, by_id.get((binding or {}).get("identity_id"))):
                    raise
            receipts[required["requirement_id"]] = _binding_receipt(binding)
            continue
        candidates[required["requirement_id"]] = {
            identity["id"]: _identity_revision(identity) for identity in compatible
        }
        credential_rejected = bound_rejected or any(
            _identity_rejection_key(identity, required) in rejected for identity in compatible
        )
        reason = _AUTHENTICATION_REJECTED if credential_rejected else "ambiguous" if len(compatible) > 1 else (
            "approval_required" if compatible else "incompatible" if named or bound_identity else "missing"
        )
        missing.append({
            "id": required["requirement_id"], "action_id": action["id"],
            "action_name": str(action.get("displayName") or action.get("display_name") or action.get("name") or "Yamcs")[:200],
            "identity_name": requirement["identity_name"], "profile": profile,
            "auth_type": ACTION_AUTH_PROFILES[profile]["auth_type"],
            "destination": get_action_auth_destination(action), "reason": reason,
            "fields": list(deepcopy(ACTION_AUTH_PROFILES[profile]["fields"])),
            "identities": [
                {"id": identity["id"], "name": str(identity.get("name") or "")[:120], "auth_type": ACTION_AUTH_PROFILES[profile]["auth_type"]}
                for identity in compatible
            ],
        })
    return missing, receipts, candidates


def _response(snapshot, missing, request_id=None, *, status=None):
    uses_personal = bool(snapshot["requirements"])
    shared = snapshot["conversation"]["kind"] == "collaboration"
    return {
        "status": status or ("credentials_required" if missing else "ready"),
        "request_id": request_id, "uses_personal_credentials": uses_personal,
        "shared_conversation": shared,
        "sharing_notice": ACTION_AUTH_SHARING_NOTICE if uses_personal and shared else None,
        "requirements": deepcopy(missing),
    }


def _new_request(user_id, snapshot, manifests):
    missing, receipts, candidates = _inspect_requirements(user_id, snapshot, manifests, reuse_approved=True)
    if not snapshot["requirements"]:
        return _response(snapshot, missing)
    request_id = f"auth-{uuid.uuid4()}"
    _create_record({
        "id": request_id, "user_id": user_id, "record_type": REQUEST_RECORD_TYPE,
        "status": "pending", "snapshot": snapshot, "binding_receipts": receipts,
        "candidate_revisions": candidates, "saved_requirements": [],
        "created_at": _now(), "updated_at": _now(), "expires_at": _now() + REQUEST_TTL_SECONDS,
        "ttl": REQUEST_TTL_SECONDS, "save_claim": None,
    })
    return _response(snapshot, missing, request_id)


def preflight_action_auth(user_id, payload):
    user_id = _action_auth_actor(user_id)
    context = _context_payload(payload, strict=True)
    snapshot, manifests = _collect(user_id, context)
    return _new_request(user_id, snapshot, manifests)


def _request(user_id, request_id, *, allow_cancelled=False, allow_saving=False):
    request_id = _identifier(request_id)
    record = _read_record(user_id, request_id, REQUEST_RECORD_TYPE)
    if record.get("expires_at", 0) <= _now():
        raise ActionAuthConflict("This authentication request expired. Check the selected action again.", code="action_auth_expired")
    if record.get("status") == "claimed":
        raise ActionAuthConflict("This authentication request was already used.", code="action_auth_already_used")
    if record.get("status") == "cancelled":
        if allow_cancelled:
            return record
        raise ActionAuthConflict("This authentication request was cancelled.", code="action_auth_cancelled")
    if record.get("status") != "pending":
        raise ActionAuthConflict(_STALE, code="action_auth_stale")
    if record.get("save_claim") and not allow_saving:
        raise ActionAuthConflict("Credentials are being saved. Please wait.", code="action_auth_busy")
    return record


def _materialized_personal_conversation(user_id, saved, current):
    previous = saved["conversation"]
    conversation = current["conversation"]
    if (
        previous.get("id") is not None or previous.get("kind") != "personal"
        or previous.get("owner_user_id") != user_id
        or not conversation.get("id") or conversation.get("kind") != "personal"
        or conversation.get("owner_user_id") != user_id
        or conversation.get("source_id") != conversation["id"]
    ):
        return False
    comparison = deepcopy(current)
    comparison["conversation"] = deepcopy(previous)
    comparison["selection"]["conversation_id"] = None
    if comparison != saved:
        return False
    # A null selection means an unstarted personal chat, not permission to move
    # a private approval into shared history or a different existing chat turn.
    config = import_module("config")
    conversation_id = conversation["id"]
    try:
        source = config.cosmos_conversations_container.read_item(item=conversation_id, partition_key=conversation_id)
        if (
            source.get("id") != conversation_id or source.get("user_id") != user_id
            or source.get("collaboration_conversation_id")
            or source.get("conversation_kind") not in (None, "", "personal")
            or source.get("chat_type") not in (None, "", "new", "user", "personal")
            or not source.get("_etag")
        ):
            raise ActionAuthConflict(_STALE, code="action_auth_stale")
        messages = config.cosmos_messages_container.query_items(
            query=(
                "SELECT TOP 1 c.id FROM c WHERE c.conversation_id = @conversation_id "
                "AND (NOT IS_DEFINED(c.role) OR NOT ARRAY_CONTAINS(@draft_roles, c.role))"
            ),
            parameters=[
                {"name": "@conversation_id", "value": conversation_id},
                {"name": "@draft_roles", "value": ["file", "image", "image_chunk"]},
            ],
            partition_key=conversation_id,
        )
        if next(iter(messages), None) is not None:
            raise ActionAuthConflict("This conversation already contains a turn. Check the selected action again.", code="action_auth_stale")
        latest = config.cosmos_conversations_container.read_item(item=conversation_id, partition_key=conversation_id)
        if latest.get("_etag") != source["_etag"]:
            raise ActionAuthConflict(_STALE, code="action_auth_stale")
    except ActionAuthConflict:
        raise
    except Exception:
        raise ActionAuthStorageError() from None
    return True


def _revalidate(
    user_id, record, *, context=None, reuse_approved=True, materialize_conversation=False, refresh_identities=False,
):
    if record.get("status") != "pending" or record.get("expires_at", 0) <= _now():
        raise ActionAuthConflict(_STALE, code="action_auth_stale")
    if record.get("save_claim"):
        current = _read_record(user_id, record["id"], REQUEST_RECORD_TYPE)
        if current.get("status") == "cancelled":
            raise ActionAuthConflict("This authentication request was cancelled.", code="action_auth_cancelled")
        if current.get("save_claim") != record["save_claim"] or current.get("_etag") != record.get("_etag"):
            raise ActionAuthConflict(_STALE, code="action_auth_stale")
    saved = record["snapshot"]
    snapshot, manifests = _collect(user_id, context or saved["selection"])
    if snapshot != saved and not (
        materialize_conversation and _materialized_personal_conversation(user_id, saved, snapshot)
    ):
        raise ActionAuthConflict(_STALE, code="action_auth_stale")
    missing, receipts, candidates = _inspect_requirements(user_id, snapshot, manifests, reuse_approved=reuse_approved)
    if not refresh_identities:
        for requirement_id, expected in record.get("binding_receipts", {}).items():
            if receipts.get(requirement_id) != expected:
                raise ActionAuthConflict(_STALE, code="action_auth_stale")
    return snapshot, manifests, missing, receipts, candidates


def get_action_auth_request(user_id, request_id):
    user_id = _action_auth_actor(user_id)
    record = _request(user_id, request_id, allow_cancelled=True)
    if record["status"] == "cancelled":
        return _response(record["snapshot"], [], request_id, status="cancelled")
    snapshot, _, missing, receipts, candidates = _revalidate(user_id, record, refresh_identities=True)
    saved_requirements = [identifier for identifier in record.get("saved_requirements", []) if identifier in receipts]
    if (
        receipts != record.get("binding_receipts", {})
        or candidates != record.get("candidate_revisions", {})
        or saved_requirements != record.get("saved_requirements", [])
    ):
        # Check again refreshes only owned identity observations. Selection,
        # action configuration, conversation and destination snapshots stay pinned.
        _replace_record(
            record, binding_receipts=receipts, candidate_revisions=candidates, saved_requirements=saved_requirements,
        )
    return _response(snapshot, missing, request_id)


def _credential_input(payload, profile):
    fields = {field["name"] for field in ACTION_AUTH_PROFILES[profile]["fields"]}
    if not isinstance(payload, dict) or set(payload) != fields:
        raise ValueError("Supply only the required credential fields.")
    values = {}
    placeholder = import_module("functions_workspace_identities").ui_trigger_word
    for field in fields:
        value = payload[field]
        maximum = 255 if field == "username" else 8192
        if not isinstance(value, str) or not value or len(value) > maximum or value == placeholder:
            raise ValueError("Provide valid values for the required credential fields.")
        if field == "username":
            value = value.strip()
            if not value:
                raise ValueError("A username is required.")
        values[field] = value
    return {"auth_type": ACTION_AUTH_PROFILES[profile]["auth_type"], **values}


def _read_identity_auth(user_id, identity_id, revision, profile):
    identities = import_module("functions_workspace_identities")
    try:
        auth = identities.get_workspace_identity_auth("personal", user_id, identity_id, expected_etag=revision)
        if auth.get("auth_type") != ACTION_AUTH_PROFILES[profile]["auth_type"]:
            raise ActionAuthConflict(_STALE, code="action_auth_stale")
        fields = {field["name"] for field in ACTION_AUTH_PROFILES[profile]["fields"]}
        credentials = _credential_input({field: auth.get(field) for field in fields}, profile)
        if _identity_revision(_identity_metadata(user_id, identity_id)) != revision:
            raise ActionAuthConflict(_STALE, code="action_auth_stale")
        return credentials
    except (ActionAuthConflict, LookupError, PermissionError):
        raise
    except Exception:
        raise ActionAuthStorageError() from None


def _validate_credentials(action, credentials):
    client = import_module("functions_yamcs_client")
    try:
        result = client.validate_yamcs_credentials(action, credentials)
    except client.YamcsAuthenticationError:
        raise ActionAuthValidationError("action_auth_rejected", "Yamcs did not accept these credentials.", 422) from None
    except client.YamcsPermissionError:
        raise ActionAuthValidationError("action_auth_permission_denied", "The account does not have the required Yamcs permission.", 403) from None
    except client.YamcsConnectionError:
        raise ActionAuthValidationError("action_auth_connection_failed", "Yamcs could not be reached securely. Please try again.", 503) from None
    except Exception:
        raise ActionAuthValidationError("action_auth_connection_failed", "The Yamcs connection could not be validated.", 503) from None
    if result is not True and (not isinstance(result, dict) or result.get("success") is not True):
        raise ActionAuthValidationError("action_auth_connection_failed", "The Yamcs connection could not be validated.", 503)


def _release_save_claim(record):
    current = _read_record(record["user_id"], record["id"], REQUEST_RECORD_TYPE)
    if current.get("save_claim") == record.get("save_claim") and current.get("status") == "pending":
        _replace_record(current, save_claim=None)


def save_action_auth_credentials(user_id, request_id, payload):
    user_id = _action_auth_actor(user_id)
    if (
        not isinstance(payload, dict)
        or set(payload) - {"requirement_id", "identity_id", "credentials", "confirm_destination"}
        or payload.get("confirm_destination") is not True
    ):
        raise ValueError("Confirm the displayed destination before saving credentials.")
    requirement_id = _requirement_uuid(payload.get("requirement_id"))
    record = _request(user_id, request_id)
    snapshot, manifests, missing, receipts, _ = _revalidate(user_id, record)
    if requirement_id not in manifests:
        raise ValueError("Select a requirement from this authentication request.")
    if requirement_id in record.get("saved_requirements", []):
        # A repeated click/transport retry cannot replace the credential again.
        return _response(snapshot, missing, request_id)
    if requirement_id in receipts:
        return _response(snapshot, missing, request_id)
    action = manifests[requirement_id]
    requirement = get_action_credential_requirement(action)
    profile = requirement["profile"]
    required = next(item for item in snapshot["requirements"] if item["requirement_id"] == requirement_id)
    identity_id = payload.get("identity_id")
    identity = None
    identity_revision = None
    if identity_id:
        identity_id = _identifier(identity_id)
        identity = _identity_metadata(user_id, identity_id)
        if not _compatible(identity, profile):
            raise ValueError("Select an owned identity with the required credential type and action use.")
        identity_revision = _identity_revision(identity)
        expected = record.get("candidate_revisions", {}).get(requirement_id, {}).get(identity_id)
        if expected and expected != identity_revision:
            raise ActionAuthConflict(_STALE, code="action_auth_stale")
    supplied = payload.get("credentials")
    if supplied is None and identity is None:
        raise ValueError("Provide credentials or select an owned identity.")
    credentials = _credential_input(supplied, profile) if supplied is not None else None
    previous_binding = _binding(user_id, required)
    claim = {"id": str(uuid.uuid4()), "requirement_id": requirement_id}
    record = _replace_record(record, save_claim=claim)
    identities = import_module("functions_workspace_identities")
    created_identity = identity is None
    try:
        _revalidate(user_id, record)
        rejected = [
            binding for binding in _records(user_id, BINDING_RECORD_TYPE)
            if identity is not None
            and _digest(_identity_rejection_key(identity, required)) in _binding_rejections(binding)
        ]
        if credentials is None:
            credentials = _read_identity_auth(user_id, identity_id, identity_revision, profile)
        _validate_credentials(action, credentials)
        if identity is not None and _identity_revision(_identity_metadata(user_id, identity_id)) != identity_revision:
            raise ActionAuthConflict(_STALE, code="action_auth_stale")
        _revalidate(user_id, record)
        latest_binding = _binding(user_id, required)
        if (latest_binding or {}).get("_etag") != (previous_binding or {}).get("_etag"):
            raise ActionAuthConflict(_STALE, code="action_auth_stale")
        if identity is None:
            identity_id = str(uuid.uuid4())
            written_identity = identities.create_workspace_identity(
                "personal", user_id, {
                    "name": requirement["identity_name"], "provider": "action",
                    "usage_contexts": ["action"], "supported_source_types": ["action"], "credentials": credentials,
                }, user_id, identity_id=identity_id,
            )
        elif supplied is not None:
            written_identity = identities.update_workspace_identity(
                "personal", user_id, identity_id, {"credentials": credentials}, user_id,
                expected_etag=identity_revision,
            )
        if created_identity or supplied is not None:
            if (
                not isinstance(written_identity, dict)
                or written_identity.get("id") != identity_id or written_identity.get("user_id") != user_id
                or written_identity.get("scope_type") != "personal"
            ):
                raise ActionAuthConflict(_STALE, code="action_auth_stale")
            identity_revision = _identity_revision(written_identity)
        _revalidate(user_id, record, reuse_approved=False)
        # Updating an identity revokes its old bindings; refresh this exact binding
        # after the conditional identity write rather than overwriting stale metadata.
        current_binding = _binding(user_id, required)
        if (current_binding or {}).get("_etag") != (previous_binding or {}).get("_etag"):
            own_revocation = bool(
                supplied is not None and not created_identity and previous_binding and current_binding
                and current_binding.get("status") == "revoked"
                and current_binding.get("identity_id") == identity_id
                and current_binding.get("identity_revision") == previous_binding.get("identity_revision")
                and current_binding.get("fingerprint") == previous_binding.get("fingerprint")
            )
            if not own_revocation:
                raise ActionAuthConflict(_STALE, code="action_auth_stale")
        identity = _identity_metadata(user_id, identity_id)
        if _identity_revision(identity) != identity_revision or not _compatible(identity, profile):
            raise ActionAuthConflict(_STALE, code="action_auth_stale")
        binding = _write_binding(user_id, required, action, identity, previous=current_binding, validated=True)
        cleared = _clear_validated_rejections(user_id, identity, required, rejected, binding)
        receipts = {**record.get("binding_receipts", {}), requirement_id: _binding_receipt(binding)}
        for before, after in cleared:
            previous_receipt = record.get("binding_receipts", {}).get(before.get("requirement_id"))
            if (
                previous_receipt == _binding_receipt(before)
                and after.get("status") == "active"
                and all(before.get(key) == after.get(key) for key in (
                    "id", "user_id", "requirement_id", "action_id", "profile",
                    "identity_id", "identity_revision", "fingerprint",
                ))
            ):
                # Clearing history must not stale a ready binding whose approved
                # identity and recipient are unchanged by this successful probe.
                receipts[before["requirement_id"]] = _binding_receipt(after)
        record = _replace_record(
            record, save_claim=None, binding_receipts=receipts,
            saved_requirements=[*record.get("saved_requirements", []), requirement_id],
        )
    except Exception as error:
        # Identity helpers clean uncommitted staged secrets. A committed identity
        # remains owned data even if its approval loses a later metadata race.
        _release_save_claim(record)
        if isinstance(error, (
            ActionAuthConflict, ActionAuthStorageError, ActionAuthValidationError,
            PermissionError, LookupError, ValueError,
        )):
            raise
        raise ActionAuthStorageError() from None
    finally:
        if credentials is not None:
            credentials.clear()
    snapshot, _, missing, _, _ = _revalidate(user_id, record)
    return _response(snapshot, missing, request_id)


def cancel_action_auth_request(user_id, request_id):
    user_id = _action_auth_actor(user_id)
    record = _request(user_id, request_id, allow_cancelled=True, allow_saving=True)
    if record["status"] != "cancelled":
        record = _replace_record(record, status="cancelled", save_claim=None)
    return _response(record["snapshot"], [], request_id, status="cancelled")


def authorize_action_auth_execution(user_id, payload, *, claim=True):
    """Gate execution using only contract selectors, never persisting ordinary chat data."""
    user_id = _action_auth_actor(user_id)
    context = _context_payload(payload, strict=False)
    request_id = payload.get("action_auth_request_id")
    if request_id:
        record = _request(user_id, request_id)
        snapshot, _, missing, receipts, _ = _revalidate(
            user_id, record, context=context, materialize_conversation=True,
        )
        if missing:
            raise ActionCredentialsRequired(_response(snapshot, missing, request_id))
        if claim:
            record = _replace_record(
                record, status="claimed", claimed_at=_now(), execution_receipt=str(uuid.uuid4()),
                binding_receipts=receipts, snapshot=snapshot,
            )
        elif snapshot != record["snapshot"]:
            record = _replace_record(record, snapshot=snapshot, binding_receipts=receipts)
        return {"request_id": record["id"], "receipt_id": record.get("execution_receipt"), "uses_personal_credentials": True}
    snapshot, manifests = _collect(user_id, context)
    if not snapshot["requirements"]:
        return None
    missing, _, _ = _inspect_requirements(user_id, snapshot, manifests, reuse_approved=True)
    if missing:
        flask = import_module("flask")
        if flask.has_request_context():
            response = _new_request(user_id, snapshot, manifests)
        else:
            # Explicit worker actors can use ready bindings, but cannot manufacture
            # interactive requests or borrow a request/session from another actor.
            response = _response(snapshot, missing)
        raise ActionCredentialsRequired(response)
    return {"request_id": None, "receipt_id": None, "uses_personal_credentials": True}


def revoke_action_identity_bindings(user_id, identity_id, *, identity_revision=None):
    """Revoke owned bindings, optionally limited to a superseded identity revision.

    Omitting the revision intentionally revokes all bindings, including on deletion.
    """
    user_id = _identifier(user_id)
    identity_id = _identifier(identity_id)
    filters = {"identity_id": identity_id}
    if identity_revision is not None:
        if not isinstance(identity_revision, str) or not identity_revision:
            raise ValueError("An identity revision is required for scoped revocation.")
        filters["identity_revision"] = identity_revision
    for binding in _records(user_id, BINDING_RECORD_TYPE, **filters):
        if binding.get("status") != "revoked":
            _replace_record(binding, status="revoked")


def _resolve_action_credentials(user_id, action):
    """Use-time action governance, recipient fingerprint, binding and identity checks."""
    user_id = _action_auth_actor(user_id, require_context=True)
    _resolution_receipt.set(None)
    validate_action_credential_requirement(action, scope_type="global")
    requirement = get_action_credential_requirement(action)
    if requirement is None:
        raise ValueError("This action does not use personal credentials.")
    action_id = _identifier(action.get("id"), maximum=1023)
    catalog = import_module("functions_action_catalog")
    action_ref = catalog._action_ref("global", "global", action_id)
    if action.get("action_ref") not in (None, action_ref):
        raise PermissionError(_UNAVAILABLE)
    current = catalog.resolve_action_manifest(user_id, action_ref)
    current_requirement = get_action_credential_requirement(current)
    if (
        current_requirement is None or current_requirement.get("id") != requirement.get("id")
        or action_auth_fingerprint(current) != action_auth_fingerprint(action)
        or _runtime_target(current) != _runtime_target(action)
    ):
        raise ActionAuthConflict(_STALE, code="action_auth_stale")
    context = {"conversation_id": None, "conversation_kind": "personal"}
    frame = import_module("agent_execution_context").current_agent_execution()
    if frame and frame.identity.conversation_id:
        context["conversation_id"] = frame.identity.conversation_id
    else:
        flask = import_module("flask")
        if flask.has_request_context():
            context["conversation_id"] = getattr(flask.g, "conversation_id", None)
    conversation = _conversation(user_id, context, _settings())
    required = _requirement(current)
    snapshot = {"conversation": conversation, "requirements": [required]}
    missing, _, _ = _inspect_requirements(user_id, snapshot, {required["requirement_id"]: current})
    if missing:
        raise ActionCredentialsRequired(_response(snapshot, missing), action_ref=action_ref)
    binding = _binding(user_id, required)
    identity = _identity_metadata(user_id, binding["identity_id"])
    if not _valid_binding(binding, required, identity):
        raise ActionAuthConflict(_STALE, code="action_auth_stale")
    credentials = _read_identity_auth(user_id, identity["id"], binding["identity_revision"], current_requirement["profile"])
    # A revocation racing the Key Vault fetch must still stop this invocation.
    try:
        latest_action = catalog.resolve_action_manifest(user_id, action_ref)
        latest = _binding(user_id, required)
        latest_identity = _identity_metadata(user_id, identity["id"])
        if (
            _action_revision(latest_action) != _action_revision(current)
            or not latest or latest.get("_etag") != binding.get("_etag")
            or not _valid_binding(latest, required, latest_identity)
        ):
            raise ActionAuthConflict(_STALE, code="action_auth_stale")
    except Exception:
        credentials.clear()
        raise
    _resolution_receipt.set({
        "user_id": user_id,
        "scope": _resolution_scope(create=True),
        "action_id": current["id"],
        "requirement_id": required["requirement_id"],
        "profile": required["profile"],
        "binding": _binding_receipt(binding),
    })
    return credentials


def _invalidate_action_credentials(user_id, action):
    """Reject a resolved revision with an actor-scoped conditional metadata write."""
    user_id = _action_auth_actor(user_id, require_context=True)
    validate_action_credential_requirement(action, scope_type="global")
    requirement = get_action_credential_requirement(action)
    receipt = _resolution_receipt.get()
    _resolution_receipt.set(None)
    if (
        requirement is None or not receipt or receipt.get("user_id") != user_id
        or receipt.get("scope") != _resolution_scope()
        or receipt.get("action_id") != action.get("id")
        or receipt.get("requirement_id") != requirement.get("id")
        or receipt.get("profile") != requirement.get("profile")
        or receipt["binding"].get("fingerprint") != action_auth_fingerprint(action)
    ):
        raise ActionAuthConflict(_STALE, code="action_auth_stale")
    expected = receipt["binding"]
    required = {"requirement_id": receipt["requirement_id"]}
    binding = _binding(user_id, required)
    if (
        binding is None or binding.get("_etag") != expected.get("_etag")
        or binding.get("status") != "active"
        or any(binding.get(key) != expected.get(key) for key in ("id", "identity_id", "identity_revision", "fingerprint"))
        or binding.get("action_id") != receipt["action_id"]
        or binding.get("profile") != receipt["profile"]
    ):
        return None
    try:
        identity = _identity_metadata(user_id, expected["identity_id"])
    except LookupError:
        return None
    if _identity_revision(identity) != expected["identity_revision"]:
        return None
    marker = {
        **{key: binding[key] for key in ("identity_id", "identity_revision", "fingerprint", "profile")},
        "rejection_id": str(uuid.uuid4()),
        "rejected_at": _now(),
    }
    rejections = _binding_rejections(binding)
    rejections[_digest(_rejection_key(marker))] = marker
    _replace_record(
        binding, status=_AUTHENTICATION_REJECTED, authentication_rejected_at=marker["rejected_at"],
        authentication_rejections=rejections,
    )
    return None

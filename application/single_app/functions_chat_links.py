# functions_chat_links.py
"""Storage and authorization for compact workspace chat launch links."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import logging
import secrets

from azure.cosmos.exceptions import (
    CosmosResourceExistsError,
    CosmosResourceNotFoundError,
)

from chat_link_contract import (
    CHAT_LINK_LIFETIME_DAYS,
    normalize_chat_link_reference,
)
from config import cosmos_chat_links_container
from content_screening.access import strict_source_authority
from content_screening.contracts import (
    DocumentHeldError,
    ScreeningConflictError,
    SourceAuthorityUnavailableError,
    SourceAuthorityUnverifiedError,
)
from cosmos_document_utils import normalize_cosmos_document
from document_source_selection import (
    DocumentSourceSelectionError,
    normalize_document_source_selection,
)
from functions_agent_catalog import (
    build_accessible_agent_catalog,
    build_agent_catalog_key,
    is_chat_agent_allowed_by_governance,
)
from functions_appinsights import log_event
from functions_chat_model_catalog import build_chat_model_catalog
from functions_document_source_discovery import admit_document_source_selection, source_catalog
from functions_group import get_user_groups
from functions_model_capabilities import REASONING_EFFORTS
from functions_settings import get_settings, get_user_settings


CHAT_LINK_SCHEMA_VERSION = 1
CHAT_LINK_RECORD_TYPE = "workspace_chat_link"
CHAT_LINK_MAX_DOCUMENTS = 500
CHAT_LINK_LIST_DEFAULT_PAGE_SIZE = 25
CHAT_LINK_LIST_MAX_PAGE_SIZE = 50
CHAT_LINK_COLLISION_ATTEMPTS = 5
CHAT_LINK_LIST_CONTINUATION_MAX_LENGTH = 16384


class ChatLinkError(Exception):
    """Stable, user-safe failure at the chat-link boundary."""

    def __init__(self, code, message, status_code):
        super().__init__(message)
        self.code = code
        self.public_message = message
        self.status_code = status_code


class ChatLinkValidationError(ChatLinkError):
    def __init__(self, message="Choose valid chat-link settings."):
        super().__init__("chat_link_invalid", message, 400)


class ChatLinkPermissionError(ChatLinkError):
    def __init__(self):
        super().__init__(
            "chat_link_forbidden",
            "You don't have permission to use this linked configuration.",
            403,
        )


class ChatLinkUnavailableError(ChatLinkError):
    def __init__(self):
        super().__init__(
            "chat_link_unavailable",
            "This chat link is unavailable. It may have expired, been revoked, "
            "or reference unavailable resources.",
            404,
        )


class ChatLinkConflictError(ChatLinkError):
    def __init__(self):
        super().__init__(
            "chat_link_configuration_changed",
            "The linked chat configuration changed. Resolve the link again before sending.",
            409,
        )


class ChatLinkServiceError(ChatLinkError):
    def __init__(self):
        super().__init__(
            "chat_link_service_unavailable",
            "Chat links could not be loaded. Please retry.",
            503,
        )


def utc_now():
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


def iso_utc(value):
    """Serialize a UTC datetime with the stable app representation."""
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_utc(value):
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def normalize_chat_link_lifetime(value):
    """Validate a client-selected lifetime, including no expiry."""
    if value is None:
        return None
    if type(value) is not int or value not in CHAT_LINK_LIFETIME_DAYS:
        raise ChatLinkValidationError(
            "Choose a valid chat-link lifetime: 7 days, 30 days, 90 days, 1 year, or never."
        )
    return value


def _normalize_routing(value):
    if type(value) is not dict or set(value) != {"kind", "selection_key"}:
        raise ChatLinkValidationError("Choose exactly one agent or model.")
    kind = value.get("kind")
    selection_key = value.get("selection_key")
    if kind not in {"agent", "model"}:
        raise ChatLinkValidationError("Choose exactly one agent or model.")
    if not isinstance(selection_key, str) or not selection_key.strip() or len(selection_key.strip()) > 512:
        raise ChatLinkValidationError("Choose a valid agent or model.")
    return {"kind": kind, "selection_key": selection_key.strip()}


def _normalize_workspace(value):
    if type(value) is not dict:
        raise ChatLinkValidationError("Choose one workspace.")
    kind = value.get("kind")
    if kind == "personal" and set(value) == {"kind"}:
        return {"kind": "personal"}
    if kind in {"group", "public"} and set(value) == {"kind", "id"}:
        workspace_id = value.get("id")
        if not isinstance(workspace_id, str) or not workspace_id.strip() or len(workspace_id.strip()) > 512:
            raise ChatLinkValidationError("Choose one workspace.")
        return {"kind": kind, "id": workspace_id.strip()}
    raise ChatLinkValidationError("Choose one workspace.")


def normalize_chat_link_reasoning_effort(value):
    """Return one supported provider reasoning value, or model/agent default."""
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ChatLinkValidationError("Choose a valid reasoning effort.")
    normalized = value.strip().lower()
    if normalized not in REASONING_EFFORTS:
        raise ChatLinkValidationError("Choose a valid reasoning effort.")
    return normalized


def normalize_chat_link_configuration(value):
    """Return the strict server-owned subset of a creation payload."""
    if type(value) is not dict:
        raise ChatLinkValidationError()
    expected = {"routing", "workspace", "document_source_selection", "lifetime_days"}
    allowed = expected | {"reasoning_effort"}
    if not expected.issubset(value) or not set(value).issubset(allowed):
        raise ChatLinkValidationError()

    workspace = _normalize_workspace(value["workspace"])
    routing = _normalize_routing(value["routing"])
    lifetime_days = normalize_chat_link_lifetime(value["lifetime_days"])
    reasoning_effort = normalize_chat_link_reasoning_effort(
        value.get("reasoning_effort")
    )
    try:
        document_selection = normalize_document_source_selection(
            value["document_source_selection"]
        )
    except DocumentSourceSelectionError as error:
        raise ChatLinkValidationError(error.public_message) from error

    if (
        not document_selection
        or document_selection["mode"] != "selected"
        or not document_selection["sources"]
    ):
        raise ChatLinkValidationError(
            "Choose one workspace or one or more explicit documents."
        )
    if len(document_selection["sources"]) > CHAT_LINK_MAX_DOCUMENTS:
        raise ChatLinkValidationError(
            f"Chat links support up to {CHAT_LINK_MAX_DOCUMENTS} selected documents."
        )
    source_kinds = {source.get("kind") for source in document_selection["sources"]}
    if source_kinds not in ({"document"}, {"workspace"}):
        raise ChatLinkValidationError(
            "Choose one workspace or explicit documents from that workspace."
        )
    if source_kinds == {"workspace"} and len(document_selection["sources"]) != 1:
        raise ChatLinkValidationError("Choose only one workspace.")
    for source in document_selection["sources"]:
        if source.get("scope") != workspace:
            raise ChatLinkValidationError(
                "Every linked source must belong to the selected workspace."
            )
    if routing["kind"] == "agent" and reasoning_effort is not None:
        raise ChatLinkValidationError(
            "Agents use their own configured reasoning effort."
        )

    return {
        "routing": routing,
        "workspace": workspace,
        "document_source_selection": document_selection,
        "lifetime_days": lifetime_days,
        "reasoning_effort": reasoning_effort,
    }


def _normalize_record(record):
    if not isinstance(record, dict):
        raise ChatLinkUnavailableError()
    if (
        record.get("record_type") != CHAT_LINK_RECORD_TYPE
        or record.get("schema_version") != CHAT_LINK_SCHEMA_VERSION
    ):
        raise ChatLinkUnavailableError()

    reference = normalize_chat_link_reference(record.get("id"))
    creator_id = record.get("created_by_user_id")
    created_at = _parse_utc(record.get("created_at"))
    expires_at = _parse_utc(record.get("expires_at")) if record.get("expires_at") else None
    if (
        not reference
        or not isinstance(creator_id, str)
        or not creator_id.strip()
        or not created_at
        or (record.get("expires_at") and not expires_at)
    ):
        raise ChatLinkUnavailableError()

    try:
        lifetime_days = normalize_chat_link_lifetime(record.get("lifetime_days"))
        config = normalize_chat_link_configuration({
            "routing": record.get("routing"),
            "workspace": record.get("workspace"),
            "document_source_selection": record.get("document_source_selection"),
            "lifetime_days": lifetime_days,
            "reasoning_effort": record.get("reasoning_effort"),
        })
    except ChatLinkValidationError as error:
        raise ChatLinkUnavailableError() from error

    if lifetime_days is None and record.get("expires_at") is not None:
        raise ChatLinkUnavailableError()
    if lifetime_days is not None and (
        expires_at is None or type(record.get("ttl")) is not int or record["ttl"] <= 0
    ):
        raise ChatLinkUnavailableError()

    normalized = {
        "id": reference,
        "record_type": CHAT_LINK_RECORD_TYPE,
        "schema_version": CHAT_LINK_SCHEMA_VERSION,
        "created_by_user_id": creator_id,
        "created_at": iso_utc(created_at),
        "expires_at": iso_utc(expires_at) if expires_at else None,
        "lifetime_days": lifetime_days,
        "_reasoning_effort_bound": "reasoning_effort" in record,
        **config,
    }
    if expires_at:
        normalized["ttl"] = int(record["ttl"])
    return normalized


def _read_record(reference, container=None):
    normalized_reference = normalize_chat_link_reference(reference)
    if not normalized_reference:
        raise ChatLinkUnavailableError()
    target = container or cosmos_chat_links_container
    try:
        response = target.read_item(
            item=normalized_reference,
            partition_key=normalized_reference,
        )
    except CosmosResourceNotFoundError as error:
        raise ChatLinkUnavailableError() from error
    except Exception as error:
        log_event(
            "[CHAT_LINKS] Could not read a chat link.",
            extra={"error_type": type(error).__name__},
            level=logging.WARNING,
        )
        raise ChatLinkServiceError() from error
    try:
        return _normalize_record(normalize_cosmos_document(response))
    except ChatLinkError:
        raise
    except Exception as error:
        log_event(
            "[CHAT_LINKS] A stored chat link failed strict normalization.",
            extra={"error_type": type(error).__name__},
            level=logging.ERROR,
        )
        raise ChatLinkUnavailableError() from error


def _record_is_expired(record, now=None):
    expires_at = _parse_utc(record.get("expires_at"))
    return bool(expires_at and expires_at <= (now or utc_now()))


def _safe_agent_projection(agent):
    return {
        "selection_key": str(agent.get("catalog_key") or ""),
        "display_name": str(agent.get("display_name") or agent.get("name") or "Agent"),
        "scope_type": str(agent.get("scope_type") or "personal"),
        "scope_id": agent.get("scope_id"),
    }


def _safe_model_projection(model):
    return {
        "selection_key": str(model.get("selection_key") or ""),
        "display_name": str(
            model.get("display_name")
            or model.get("request_model")
            or model.get("deployment_name")
            or "Model"
        ),
        "scope_type": str(model.get("scope_type") or "global"),
        "scope_id": model.get("scope_id"),
    }


def _resolve_agent(user_id, routing, settings):
    candidates = build_accessible_agent_catalog(user_id, settings=settings)
    agent = next(
        (
            item
            for item in candidates
            if str(item.get("catalog_key") or "") == routing["selection_key"]
        ),
        None,
    )
    if not agent:
        raise ChatLinkPermissionError()
    scope_type = str(agent.get("scope_type") or "personal").strip().lower()
    if not is_chat_agent_allowed_by_governance(user_id, agent, scope_type):
        raise ChatLinkPermissionError()
    assigned_knowledge = agent.get("assigned_knowledge")
    if (
        isinstance(assigned_knowledge, dict)
        and assigned_knowledge.get("enabled") is True
        and assigned_knowledge.get("allow_user_workspace_context") is not True
    ):
        raise ChatLinkUnavailableError()
    return agent, _safe_agent_projection(agent)


def _resolve_model(user_id, routing, settings):
    user_settings = get_user_settings(user_id) or {}
    user_settings_dict = (
        user_settings.get("settings", {}) if isinstance(user_settings, dict) else {}
    )
    user_groups = get_user_groups(user_id) or []
    models = build_chat_model_catalog(
        user_id=user_id,
        settings=settings,
        user_settings_dict=user_settings_dict,
        user_groups_raw=user_groups,
    )
    model = next(
        (
            item
            for item in models
            if str(item.get("selection_key") or "") == routing["selection_key"]
        ),
        None,
    )
    if not model:
        raise ChatLinkPermissionError()
    return model, _safe_model_projection(model)


def _resolve_workspace(user_id, workspace, document_selection, settings):
    try:
        catalog = source_catalog(user_id, settings)
    except Exception as error:
        log_event(
            "[CHAT_LINKS] Could not load workspaces for a chat link.",
            extra={"error_type": type(error).__name__},
            level=logging.WARNING,
        )
        raise ChatLinkServiceError() from error

    workspace_entry = next(
        (
            item
            for item in catalog
            if item.get("kind") == workspace["kind"]
            and item.get("id") == workspace.get("id")
        ),
        None,
    )
    if not workspace_entry:
        if workspace["kind"] == "personal":
            raise ChatLinkUnavailableError()
        raise ChatLinkPermissionError()

    try:
        with strict_source_authority():
            admitted_selection, _sources = admit_document_source_selection(
                document_selection,
                user_id,
                settings=settings,
            )
    except PermissionError as error:
        raise ChatLinkPermissionError() from error
    except (
        DocumentHeldError,
        ScreeningConflictError,
        LookupError,
    ) as error:
        raise ChatLinkUnavailableError() from error
    except (
        SourceAuthorityUnavailableError,
        SourceAuthorityUnverifiedError,
    ) as error:
        raise ChatLinkServiceError() from error
    except DocumentSourceSelectionError as error:
        raise ChatLinkUnavailableError() from error
    except Exception as error:
        log_event(
            "[CHAT_LINKS] Document authorization for a chat link failed.",
            extra={"error_type": type(error).__name__},
            level=logging.WARNING,
        )
        raise ChatLinkServiceError() from error

    if admitted_selection != document_selection:
        raise ChatLinkConflictError()
    return {
        **workspace,
        "display_name": str(workspace_entry.get("name") or "Workspace"),
    }


def resolve_chat_link_configuration(user_id, config, *, settings=None):
    """Reauthorize one normalized configuration and return server-owned resolution data."""
    if (
        not isinstance(user_id, str)
        or not user_id.strip()
        or len(user_id.strip()) > 512
    ):
        raise ChatLinkPermissionError()
    user_id = user_id.strip()
    settings = get_settings() if settings is None else settings
    routing = config["routing"]
    try:
        if routing["kind"] == "agent":
            routing_record, routing_projection = _resolve_agent(
                user_id, routing, settings
            )
        else:
            routing_record, routing_projection = _resolve_model(
                user_id, routing, settings
            )
            reasoning_effort = config["reasoning_effort"]
            reasoning_policy = (
                routing_record.get("reasoning_capabilities")
                if isinstance(routing_record, dict)
                else None
            )
            supported_efforts = (
                reasoning_policy.get("efforts")
                if isinstance(reasoning_policy, dict)
                and reasoning_policy.get("status") == "supported"
                else []
            )
            if (
                reasoning_effort is not None
                and reasoning_effort not in (supported_efforts or [])
            ):
                raise ChatLinkValidationError(
                    "The selected reasoning effort is not available for this model."
                )
        workspace = _resolve_workspace(
            user_id,
            config["workspace"],
            config["document_source_selection"],
            settings,
        )
    except ChatLinkError:
        raise
    except Exception as error:
        log_event(
            "[CHAT_LINKS] Chat link authorization failed.",
            extra={"error_type": type(error).__name__},
            level=logging.WARNING,
        )
        raise ChatLinkServiceError() from error
    return {
        "routing": {"kind": routing["kind"], **routing_projection},
        "routing_record": routing_record,
        "workspace": workspace,
    }


def _resolved_projection(record, resolution):
    all_documents = any(
        source.get("kind") == "workspace"
        for source in record["document_source_selection"]["sources"]
    )
    return {
        "reference": record["id"],
        "path": f"/l/{record['id']}",
        "created_at": record["created_at"],
        "expires_at": record["expires_at"],
        "lifetime_days": record["lifetime_days"],
        "routing": deepcopy(resolution["routing"]),
        "workspace": deepcopy(resolution["workspace"]),
        "document_source_selection": deepcopy(
            record["document_source_selection"]
        ),
        "document_count": (
            None
            if all_documents
            else len(record["document_source_selection"]["sources"])
        ),
        "all_documents": all_documents,
        "reasoning_effort": record["reasoning_effort"],
        "reasoning_effort_bound": record.get("_reasoning_effort_bound", False),
    }


def resolve_chat_link(reference, user_id, *, settings=None, container=None, now=None):
    """Point-read and fully reauthorize a link for the current user."""
    record = _read_record(reference, container=container)
    if _record_is_expired(record, now=now):
        raise ChatLinkUnavailableError()
    try:
        resolution = resolve_chat_link_configuration(
            user_id,
            record,
            settings=settings,
        )
    except ChatLinkValidationError as error:
        raise ChatLinkUnavailableError() from error
    return {
        "record": record,
        "routing_record": resolution["routing_record"],
        "projection": _resolved_projection(record, resolution),
    }


def create_chat_link(
    user_id,
    payload,
    *,
    settings=None,
    container=None,
    now=None,
):
    """Validate, authorize, and atomically persist an immutable chat link."""
    if (
        not isinstance(user_id, str)
        or not user_id.strip()
        or len(user_id.strip()) > 512
    ):
        raise ChatLinkPermissionError()
    user_id = user_id.strip()
    config = normalize_chat_link_configuration(payload)
    resolution = resolve_chat_link_configuration(user_id, config, settings=settings)
    created_at = now or utc_now()
    expires_at = (
        created_at + timedelta(days=config["lifetime_days"])
        if config["lifetime_days"] is not None
        else None
    )
    target = container or cosmos_chat_links_container

    for _attempt in range(CHAT_LINK_COLLISION_ATTEMPTS):
        reference = secrets.token_urlsafe(16)
        normalized_reference = normalize_chat_link_reference(reference)
        if not normalized_reference:
            continue
        record = {
            "id": normalized_reference,
            "record_type": CHAT_LINK_RECORD_TYPE,
            "schema_version": CHAT_LINK_SCHEMA_VERSION,
            "created_by_user_id": user_id,
            "created_at": iso_utc(created_at),
            "expires_at": iso_utc(expires_at) if expires_at else None,
            "lifetime_days": config["lifetime_days"],
            "reasoning_effort": config["reasoning_effort"],
            "routing": deepcopy(config["routing"]),
            "workspace": deepcopy(config["workspace"]),
            "document_source_selection": deepcopy(
                config["document_source_selection"]
            ),
        }
        if expires_at:
            record["ttl"] = int((expires_at - created_at).total_seconds())
        try:
            persisted = normalize_cosmos_document(target.create_item(body=record))
            normalized = _normalize_record(persisted)
            return {
                "record": normalized,
                "projection": _resolved_projection(normalized, resolution),
            }
        except CosmosResourceExistsError:
            continue
        except Exception as error:
            log_event(
                "[CHAT_LINKS] Could not create a chat link.",
                extra={"error_type": type(error).__name__},
                level=logging.ERROR,
            )
            raise ChatLinkServiceError() from error

    log_event(
        "[CHAT_LINKS] Could not allocate a unique chat link reference.",
        level=logging.ERROR,
        extra={"attempts": CHAT_LINK_COLLISION_ATTEMPTS},
    )
    raise ChatLinkServiceError()


def _list_projection(record, *, include_creator):
    all_documents = any(
        source.get("kind") == "workspace"
        for source in record["document_source_selection"]["sources"]
    )
    projected = {
        "reference": record["id"],
        "path": f"/l/{record['id']}",
        "created_at": record["created_at"],
        "expires_at": record["expires_at"],
        "lifetime_days": record["lifetime_days"],
        "routing": {
            "kind": record["routing"]["kind"],
            "selection_key": record["routing"]["selection_key"],
        },
        "workspace": deepcopy(record["workspace"]),
        "document_count": (
            None
            if all_documents
            else len(record["document_source_selection"]["sources"])
        ),
        "all_documents": all_documents,
        "reasoning_effort": record["reasoning_effort"],
    }
    if include_creator:
        projected["created_by_user_id"] = record["created_by_user_id"]
    return projected


def list_chat_links(
    *,
    created_by_user_id=None,
    page_size=CHAT_LINK_LIST_DEFAULT_PAGE_SIZE,
    continuation_token=None,
    container=None,
    now=None,
):
    """List active records for one creator or, when omitted, all creators."""
    if type(page_size) is not int:
        raise ChatLinkValidationError("Choose a valid page size.")
    if page_size < 1 or page_size > CHAT_LINK_LIST_MAX_PAGE_SIZE:
        raise ChatLinkValidationError(
            f"Choose a page size from 1 to {CHAT_LINK_LIST_MAX_PAGE_SIZE}."
        )
    if continuation_token not in (None, ""):
        if (
            not isinstance(continuation_token, str)
            or len(continuation_token) > CHAT_LINK_LIST_CONTINUATION_MAX_LENGTH
        ):
            raise ChatLinkValidationError("Choose a valid continuation token.")
    elif continuation_token == "":
        continuation_token = None

    parameters = [{"name": "@now", "value": iso_utc(now or utc_now())}]
    conditions = [
        "c.record_type = @record_type",
        "c.schema_version = @schema_version",
        "(NOT IS_DEFINED(c.expires_at) OR c.expires_at = null OR c.expires_at > @now)",
    ]
    parameters.extend([
        {"name": "@record_type", "value": CHAT_LINK_RECORD_TYPE},
        {"name": "@schema_version", "value": CHAT_LINK_SCHEMA_VERSION},
    ])
    if created_by_user_id is not None:
        if not isinstance(created_by_user_id, str) or not created_by_user_id.strip():
            raise ChatLinkValidationError("Choose a valid owner.")
        conditions.append("c.created_by_user_id = @created_by_user_id")
        parameters.append({
            "name": "@created_by_user_id",
            "value": created_by_user_id,
        })
    query = f"SELECT * FROM c WHERE {' AND '.join(conditions)} ORDER BY c.created_at DESC"
    target = container or cosmos_chat_links_container
    try:
        query_iterable = target.query_items(
            query=query,
            parameters=parameters,
            enable_cross_partition_query=True,
            max_item_count=page_size,
        )
        pages = query_iterable.by_page(continuation_token=continuation_token)
        page = next(pages, [])
        next_token = getattr(pages, "continuation_token", None)
        records = [
            _normalize_record(normalize_cosmos_document(item))
            for item in page
        ]
    except ChatLinkError:
        raise
    except Exception as error:
        log_event(
            "[CHAT_LINKS] Could not list chat links.",
            extra={"error_type": type(error).__name__},
            level=logging.WARNING,
        )
        raise ChatLinkServiceError() from error
    return {
        "links": [
            _list_projection(item, include_creator=created_by_user_id is None)
            for item in records
            if not _record_is_expired(item, now=now)
        ],
        "continuation_token": next_token,
        "has_more": bool(next_token),
    }


def revoke_chat_link(
    reference,
    actor_user_id,
    *,
    allow_admin=False,
    container=None,
):
    """Hard-delete a link when the caller owns it or has the dedicated admin path."""
    record = _read_record(reference, container=container)
    if not allow_admin and record["created_by_user_id"] != actor_user_id:
        raise ChatLinkUnavailableError()
    target = container or cosmos_chat_links_container
    try:
        target.delete_item(
            item=record["id"],
            partition_key=record["id"],
        )
    except CosmosResourceNotFoundError as error:
        raise ChatLinkUnavailableError() from error
    except Exception as error:
        log_event(
            "[CHAT_LINKS] Could not revoke a chat link.",
            extra={"error_type": type(error).__name__},
            level=logging.WARNING,
        )
        raise ChatLinkServiceError() from error
    return None


def _normalized_model_request(model):
    return {
        "model_deployment": str(
            model.get("deployment_name")
            or model.get("request_model")
            or model.get("model_id")
            or ""
        ).strip(),
        "model_id": str(model.get("model_id") or "").strip(),
        "model_endpoint_id": str(model.get("endpoint_id") or "").strip(),
        "model_provider": str(model.get("provider") or "").strip(),
        "model_scope_type": str(model.get("scope_type") or "").strip(),
        "model_scope_id": str(model.get("scope_id") or "").strip(),
    }


def authorize_chat_link_request(data, user_id, *, settings=None, container=None):
    """Reauthorize and bind a request to the exact link it claims to carry."""
    if not isinstance(data, dict) or "chat_link_reference" not in data:
        return None
    reference = normalize_chat_link_reference(data.get("chat_link_reference"))
    if not reference:
        raise ChatLinkValidationError("The chat link reference is invalid.")

    resolution = resolve_chat_link(
        reference,
        user_id,
        settings=settings,
        container=container,
    )
    record = resolution["record"]
    try:
        request_selection = normalize_document_source_selection(
            data.get("document_source_selection")
        )
    except DocumentSourceSelectionError as error:
        raise ChatLinkConflictError() from error
    if request_selection != record["document_source_selection"]:
        raise ChatLinkConflictError()
    if (
        record.get("_reasoning_effort_bound", False)
        and record["routing"]["kind"] == "model"
    ):
        try:
            request_reasoning = normalize_chat_link_reasoning_effort(
                data.get("reasoning_effort")
            )
        except ChatLinkValidationError as error:
            raise ChatLinkConflictError() from error
        if request_reasoning != record["reasoning_effort"]:
            raise ChatLinkConflictError()

    if record["routing"]["kind"] == "agent":
        request_agent = data.get("agent_info")
        if not isinstance(request_agent, dict):
            raise ChatLinkConflictError()
        request_key = str(request_agent.get("catalog_key") or "").strip()
        derived_key = build_agent_catalog_key(request_agent)
        routing_record = resolution["routing_record"]
        identity_matches = (
            str(request_agent.get("id") or "").strip()
            == str(routing_record.get("id") or "").strip()
            and bool(request_agent.get("is_global")) == bool(routing_record.get("is_global"))
            and bool(request_agent.get("is_group")) == bool(routing_record.get("is_group"))
            and str(request_agent.get("group_id") or "").strip()
            == str(routing_record.get("group_id") or "").strip()
        )
        if (
            request_key != record["routing"]["selection_key"]
            and derived_key != record["routing"]["selection_key"]
            and not identity_matches
        ):
            raise ChatLinkConflictError()
    else:
        if isinstance(data.get("agent_info"), dict) and data.get("agent_info"):
            raise ChatLinkConflictError()
        expected = _normalized_model_request(resolution["routing_record"])
        if expected["model_endpoint_id"]:
            compared_fields = expected
            for key, expected_value in compared_fields.items():
                if str(data.get(key) or "").strip() != expected_value:
                    raise ChatLinkConflictError()
        else:
            requested_deployment = str(
                data.get("model_deployment") or data.get("model_id") or ""
            ).strip()
            if requested_deployment != expected["model_deployment"]:
                raise ChatLinkConflictError()
    return resolution

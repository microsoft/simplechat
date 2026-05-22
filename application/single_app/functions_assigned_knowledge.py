# functions_assigned_knowledge.py

import logging
from copy import deepcopy
from typing import Any, Dict, List, Optional

from config import (
    cosmos_group_documents_container,
    cosmos_public_documents_container,
    cosmos_user_documents_container,
)
from functions_appinsights import log_event
from functions_documents import (
    get_document_record,
    sanitize_tags_for_filter,
    select_current_documents,
    sort_documents,
)
from functions_group import find_group_by_id, get_user_role_in_group
from functions_public_workspaces import (
    find_public_workspace_by_id,
    get_all_public_workspaces,
    get_user_visible_public_workspace_ids_from_settings,
)
from functions_source_review import normalize_review_url


ASSIGNED_KNOWLEDGE_SETTINGS_KEY = "assigned_knowledge"
ASSIGNED_KNOWLEDGE_USER_ACTION_SEARCH = "search"
ASSIGNED_KNOWLEDGE_USER_ACTION_ANALYZE = "analyze"
ASSIGNED_KNOWLEDGE_USER_ACTION_COMPARE = "compare"
ASSIGNED_KNOWLEDGE_WEB_SOURCE_MODE_URL_REVIEW = "url_review"
ASSIGNED_KNOWLEDGE_WEB_SOURCE_MODE_DEEP_RESEARCH = "deep_research"
ASSIGNED_KNOWLEDGE_VALID_WEB_SOURCE_MODES = {
    ASSIGNED_KNOWLEDGE_WEB_SOURCE_MODE_URL_REVIEW,
    ASSIGNED_KNOWLEDGE_WEB_SOURCE_MODE_DEEP_RESEARCH,
}
ASSIGNED_KNOWLEDGE_VALID_USER_ACTIONS = {
    ASSIGNED_KNOWLEDGE_USER_ACTION_SEARCH,
    ASSIGNED_KNOWLEDGE_USER_ACTION_ANALYZE,
    ASSIGNED_KNOWLEDGE_USER_ACTION_COMPARE,
}
ASSIGNED_KNOWLEDGE_DEFAULT_USER_ACTIONS = [
    ASSIGNED_KNOWLEDGE_USER_ACTION_SEARCH,
    ASSIGNED_KNOWLEDGE_USER_ACTION_ANALYZE,
    ASSIGNED_KNOWLEDGE_USER_ACTION_COMPARE,
]
ASSIGNED_KNOWLEDGE_DEFAULT = {
    "enabled": False,
    "scopes": {
        "personal": False,
        "group_ids": [],
        "public_workspace_ids": [],
    },
    "document_ids": [],
    "tags": [],
    "web_sources": [],
    "allow_user_workspace_context": False,
    "allowed_user_workspace_actions": ASSIGNED_KNOWLEDGE_DEFAULT_USER_ACTIONS,
}
ASSIGNED_KNOWLEDGE_MAX_DOCUMENT_IDS = 200
ASSIGNED_KNOWLEDGE_MAX_TAGS = 50
ASSIGNED_KNOWLEDGE_MAX_SOURCE_IDS = 50
ASSIGNED_KNOWLEDGE_MAX_WEB_SOURCES = 50
ASSIGNED_KNOWLEDGE_CATALOG_DOCUMENT_LIMIT = 1000


class AssignedKnowledgeError(ValueError):
    """Raised when an assigned knowledge configuration is invalid."""


def _copy_default_assigned_knowledge() -> Dict[str, Any]:
    return deepcopy(ASSIGNED_KNOWLEDGE_DEFAULT)


def _dedupe_strings(values: Any, *, limit: int = 200) -> List[str]:
    if values is None:
        return []
    if isinstance(values, str):
        candidates = [values]
    elif isinstance(values, list):
        candidates = values
    else:
        return []

    cleaned = []
    seen = set()
    for item in candidates:
        if not isinstance(item, str):
            continue
        value = item.strip()
        if not value or value in seen:
            continue
        seen.add(value)
        cleaned.append(value)
        if len(cleaned) >= limit:
            break
    return cleaned


def _normalize_user_workspace_actions(raw_actions: Any) -> List[str]:
    if raw_actions is None:
        return list(ASSIGNED_KNOWLEDGE_DEFAULT_USER_ACTIONS)
    actions = _dedupe_strings(raw_actions, limit=len(ASSIGNED_KNOWLEDGE_VALID_USER_ACTIONS))
    if not actions:
        return []

    normalized_actions = []
    seen_actions = set()
    for action in actions:
        normalized_action = action.strip().lower()
        if normalized_action == "comparison":
            normalized_action = ASSIGNED_KNOWLEDGE_USER_ACTION_COMPARE
        if normalized_action not in ASSIGNED_KNOWLEDGE_VALID_USER_ACTIONS or normalized_action in seen_actions:
            continue
        seen_actions.add(normalized_action)
        normalized_actions.append(normalized_action)

    return normalized_actions


def _normalize_web_source_mode(raw_mode: Any) -> str:
    normalized_mode = str(raw_mode or "").strip().lower()
    if normalized_mode in {"deep", "deep-research", "research", "source_review"}:
        return ASSIGNED_KNOWLEDGE_WEB_SOURCE_MODE_DEEP_RESEARCH
    if normalized_mode == ASSIGNED_KNOWLEDGE_WEB_SOURCE_MODE_DEEP_RESEARCH:
        return ASSIGNED_KNOWLEDGE_WEB_SOURCE_MODE_DEEP_RESEARCH
    return ASSIGNED_KNOWLEDGE_WEB_SOURCE_MODE_URL_REVIEW


def _extract_web_source_entries(raw_web_sources: Any) -> List[Any]:
    if raw_web_sources is None:
        return []
    if isinstance(raw_web_sources, str):
        return raw_web_sources.replace(",", "\n").splitlines()
    if isinstance(raw_web_sources, list):
        return raw_web_sources
    if isinstance(raw_web_sources, dict):
        entries = raw_web_sources.get("sources") or raw_web_sources.get("urls") or []
        default_mode = _normalize_web_source_mode(raw_web_sources.get("mode"))
        if raw_web_sources.get("deep_research") is True:
            default_mode = ASSIGNED_KNOWLEDGE_WEB_SOURCE_MODE_DEEP_RESEARCH
        extracted_entries = []
        for entry in _extract_web_source_entries(entries):
            if isinstance(entry, dict):
                extracted_entries.append({"url": entry.get("url"), "mode": entry.get("mode") or default_mode})
            else:
                extracted_entries.append({"url": entry, "mode": default_mode})
        return extracted_entries
    return []


def _normalize_web_sources(raw_web_sources: Any) -> List[Dict[str, str]]:
    web_sources_by_url: Dict[str, Dict[str, str]] = {}
    ordered_urls = []
    for entry in _extract_web_source_entries(raw_web_sources):
        if isinstance(entry, dict):
            raw_url = entry.get("url") or entry.get("href") or entry.get("link")
            if entry.get("deep_research") is True:
                mode = ASSIGNED_KNOWLEDGE_WEB_SOURCE_MODE_DEEP_RESEARCH
            else:
                mode = _normalize_web_source_mode(entry.get("mode"))
        else:
            raw_url = entry
            mode = ASSIGNED_KNOWLEDGE_WEB_SOURCE_MODE_URL_REVIEW

        normalized_url, _ = normalize_review_url(raw_url)
        if not normalized_url:
            continue
        if normalized_url not in web_sources_by_url:
            ordered_urls.append(normalized_url)
            web_sources_by_url[normalized_url] = {"url": normalized_url, "mode": mode}
        elif mode == ASSIGNED_KNOWLEDGE_WEB_SOURCE_MODE_DEEP_RESEARCH:
            web_sources_by_url[normalized_url]["mode"] = mode
        if len(ordered_urls) >= ASSIGNED_KNOWLEDGE_MAX_WEB_SOURCES:
            break

    return [web_sources_by_url[url] for url in ordered_urls]


def _extract_scope_ids(raw_assigned_knowledge: Dict[str, Any]) -> Dict[str, Any]:
    scopes = raw_assigned_knowledge.get("scopes")
    if not isinstance(scopes, dict):
        scopes = {}

    personal_enabled = bool(scopes.get("personal") or raw_assigned_knowledge.get("personal"))
    group_ids = _dedupe_strings(
        scopes.get("group_ids") or raw_assigned_knowledge.get("group_ids"),
        limit=ASSIGNED_KNOWLEDGE_MAX_SOURCE_IDS,
    )
    public_workspace_ids = _dedupe_strings(
        scopes.get("public_workspace_ids") or raw_assigned_knowledge.get("public_workspace_ids"),
        limit=ASSIGNED_KNOWLEDGE_MAX_SOURCE_IDS,
    )

    source_entries = raw_assigned_knowledge.get("sources")
    if isinstance(source_entries, list):
        for entry in source_entries:
            if not isinstance(entry, dict):
                continue
            source_scope = str(entry.get("scope") or "").strip().lower()
            source_id = str(entry.get("id") or entry.get("source_id") or "").strip()
            if source_scope == "personal":
                personal_enabled = True
            elif source_scope == "group" and source_id:
                group_ids.append(source_id)
            elif source_scope == "public" and source_id:
                public_workspace_ids.append(source_id)

    return {
        "personal": personal_enabled,
        "group_ids": _dedupe_strings(group_ids, limit=ASSIGNED_KNOWLEDGE_MAX_SOURCE_IDS),
        "public_workspace_ids": _dedupe_strings(public_workspace_ids, limit=ASSIGNED_KNOWLEDGE_MAX_SOURCE_IDS),
    }


def _enforce_scope_policy(scopes: Dict[str, Any], *, agent_scope: str, group_id: Optional[str]) -> Dict[str, Any]:
    normalized_agent_scope = str(agent_scope or "personal").strip().lower()
    if normalized_agent_scope == "group":
        active_group_id = str(group_id or "").strip()
        if not active_group_id:
            raise AssignedKnowledgeError("Group assigned knowledge requires an active group.")
        return {
            "personal": False,
            "group_ids": [active_group_id],
            "public_workspace_ids": [],
        }
    if normalized_agent_scope == "global":
        return {
            "personal": False,
            "group_ids": [],
            "public_workspace_ids": scopes.get("public_workspace_ids", []),
        }
    return {
        "personal": bool(scopes.get("personal")),
        "group_ids": [],
        "public_workspace_ids": scopes.get("public_workspace_ids", []),
    }


def normalize_assigned_knowledge(
    raw_assigned_knowledge: Any,
    *,
    agent_scope: str = "personal",
    group_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Return the canonical assigned knowledge shape without performing access checks."""
    if not isinstance(raw_assigned_knowledge, dict):
        return _copy_default_assigned_knowledge()

    enabled = bool(raw_assigned_knowledge.get("enabled"))
    normalized = _copy_default_assigned_knowledge()
    if not enabled:
        return normalized

    scopes = _enforce_scope_policy(
        _extract_scope_ids(raw_assigned_knowledge),
        agent_scope=agent_scope,
        group_id=group_id,
    )
    document_ids = _dedupe_strings(
        raw_assigned_knowledge.get("document_ids") or raw_assigned_knowledge.get("selected_document_ids"),
        limit=ASSIGNED_KNOWLEDGE_MAX_DOCUMENT_IDS,
    )
    tags = sanitize_tags_for_filter(raw_assigned_knowledge.get("tags"))[:ASSIGNED_KNOWLEDGE_MAX_TAGS]
    web_sources = _normalize_web_sources(raw_assigned_knowledge.get("web_sources"))
    allow_user_workspace_context = bool(raw_assigned_knowledge.get("allow_user_workspace_context"))
    raw_user_workspace_actions = raw_assigned_knowledge.get("allowed_user_workspace_actions")
    if raw_user_workspace_actions is None:
        raw_user_workspace_actions = raw_assigned_knowledge.get("allowed_user_context_actions")
    allowed_user_workspace_actions = _normalize_user_workspace_actions(raw_user_workspace_actions)

    normalized.update({
        "enabled": True,
        "scopes": scopes,
        "document_ids": document_ids,
        "tags": tags,
        "web_sources": web_sources,
        "allow_user_workspace_context": allow_user_workspace_context,
        "allowed_user_workspace_actions": allowed_user_workspace_actions,
    })
    return normalized


def _visible_public_workspace_id_set(user_id: str) -> set:
    return set(_dedupe_strings(get_user_visible_public_workspace_ids_from_settings(user_id) or []))


def _validate_public_workspace_ids(
    user_id: str,
    public_workspace_ids: List[str],
    *,
    is_admin: bool,
) -> List[str]:
    if not public_workspace_ids:
        return []

    visible_ids = _visible_public_workspace_id_set(user_id) if not is_admin else None
    validated_ids = []
    for workspace_id in public_workspace_ids:
        if visible_ids is not None and workspace_id not in visible_ids:
            raise AssignedKnowledgeError("Assigned public workspace is not visible to this user.")
        if not find_public_workspace_by_id(workspace_id):
            raise AssignedKnowledgeError("Assigned public workspace was not found.")
        validated_ids.append(workspace_id)
    return validated_ids


def _validate_group_ids(user_id: str, group_ids: List[str]) -> List[str]:
    validated_ids = []
    for group_id in group_ids:
        group_doc = find_group_by_id(group_id)
        if not group_doc:
            raise AssignedKnowledgeError("Assigned group was not found.")
        if not get_user_role_in_group(group_doc, user_id):
            raise AssignedKnowledgeError("Assigned group is not available to this user.")
        validated_ids.append(group_id)
    return validated_ids


def _document_exists_in_sources(user_id: str, document_id: str, scopes: Dict[str, Any]) -> bool:
    if scopes.get("personal") and get_document_record(user_id, document_id):
        return True

    for group_id in scopes.get("group_ids", []):
        if get_document_record(user_id, document_id, group_id=group_id):
            return True

    for public_workspace_id in scopes.get("public_workspace_ids", []):
        if get_document_record(user_id, document_id, public_workspace_id=public_workspace_id):
            return True

    return False


def validate_assigned_knowledge_for_agent(
    raw_assigned_knowledge: Any,
    *,
    user_id: str,
    agent_scope: str = "personal",
    group_id: Optional[str] = None,
    is_admin: bool = False,
) -> Dict[str, Any]:
    """Normalize and validate assigned knowledge for an agent save operation."""
    normalized = normalize_assigned_knowledge(
        raw_assigned_knowledge,
        agent_scope=agent_scope,
        group_id=group_id,
    )
    if not normalized.get("enabled"):
        return normalized

    scopes = normalized["scopes"]
    scopes["public_workspace_ids"] = _validate_public_workspace_ids(
        user_id,
        scopes.get("public_workspace_ids", []),
        is_admin=is_admin,
    )
    if scopes.get("group_ids"):
        scopes["group_ids"] = _validate_group_ids(user_id, scopes.get("group_ids", []))

    has_source_scope = bool(
        scopes.get("personal")
        or scopes.get("group_ids")
        or scopes.get("public_workspace_ids")
    )
    has_web_sources = bool(normalized.get("web_sources"))
    if not has_source_scope and not has_web_sources:
        raise AssignedKnowledgeError("Choose at least one knowledge source or web source before enabling assigned knowledge.")

    missing_document_ids = [
        document_id
        for document_id in normalized.get("document_ids", [])
        if not _document_exists_in_sources(user_id, document_id, scopes)
    ]
    if missing_document_ids:
        raise AssignedKnowledgeError("One or more assigned documents are not available in the selected sources.")

    return normalized


def apply_assigned_knowledge_to_agent_payload(
    agent: Dict[str, Any],
    *,
    user_id: str,
    agent_scope: str = "personal",
    group_id: Optional[str] = None,
    is_admin: bool = False,
) -> Dict[str, Any]:
    """Validate assigned knowledge and write the canonical value into other_settings."""
    cleaned_agent = dict(agent or {})
    other_settings = cleaned_agent.get("other_settings")
    if not isinstance(other_settings, dict):
        other_settings = {}

    normalized = validate_assigned_knowledge_for_agent(
        other_settings.get(ASSIGNED_KNOWLEDGE_SETTINGS_KEY),
        user_id=user_id,
        agent_scope=agent_scope,
        group_id=group_id,
        is_admin=is_admin,
    )
    other_settings[ASSIGNED_KNOWLEDGE_SETTINGS_KEY] = normalized
    cleaned_agent["other_settings"] = other_settings
    return cleaned_agent


def get_agent_assigned_knowledge(
    agent: Dict[str, Any],
    *,
    agent_scope: str = "personal",
    group_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Return normalized assigned knowledge from an agent record without access validation."""
    other_settings = agent.get("other_settings") if isinstance(agent, dict) else {}
    if not isinstance(other_settings, dict):
        other_settings = {}
    return normalize_assigned_knowledge(
        other_settings.get(ASSIGNED_KNOWLEDGE_SETTINGS_KEY),
        agent_scope=agent_scope,
        group_id=group_id,
    )


def build_assigned_knowledge_runtime_filters(agent: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Build the document search override used by chat when an agent has assigned knowledge."""
    if not isinstance(agent, dict):
        return None

    if agent.get("is_group"):
        agent_scope = "group"
        group_id = agent.get("group_id")
    elif agent.get("is_global"):
        agent_scope = "global"
        group_id = None
    else:
        agent_scope = "personal"
        group_id = None

    assigned_knowledge = get_agent_assigned_knowledge(
        agent,
        agent_scope=agent_scope,
        group_id=group_id,
    )
    if not assigned_knowledge.get("enabled"):
        return None

    scopes = assigned_knowledge.get("scopes", {})
    personal_enabled = bool(scopes.get("personal"))
    group_ids = scopes.get("group_ids", []) or []
    public_workspace_ids = scopes.get("public_workspace_ids", []) or []
    web_sources = assigned_knowledge.get("web_sources", []) or []
    enabled_scope_count = sum([
        1 if personal_enabled else 0,
        1 if group_ids else 0,
        1 if public_workspace_ids else 0,
    ])

    if enabled_scope_count > 1:
        document_scope = "all"
    elif group_ids:
        document_scope = "group"
    elif public_workspace_ids:
        document_scope = "public"
    elif personal_enabled:
        document_scope = "personal"
    else:
        document_scope = None

    has_workspace_knowledge = bool(document_scope)
    has_web_sources = bool(web_sources)
    if not has_workspace_knowledge and not has_web_sources:
        return None

    return {
        "enabled": True,
        "doc_scope": document_scope,
        "has_workspace_knowledge": has_workspace_knowledge,
        "has_web_sources": has_web_sources,
        "document_ids": assigned_knowledge.get("document_ids", []) or [],
        "tags_filter": assigned_knowledge.get("tags", []) or [],
        "web_sources": web_sources,
        "active_group_ids": group_ids,
        "active_public_workspace_ids": public_workspace_ids,
        "document_filter_mode": "union",
        "allow_user_workspace_context": bool(assigned_knowledge.get("allow_user_workspace_context")),
        "allowed_user_workspace_actions": _normalize_user_workspace_actions(
            assigned_knowledge.get("allowed_user_workspace_actions")
        ),
        "assigned_knowledge": assigned_knowledge,
    }


def _query_documents(container: Any, query: str, parameters: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    try:
        documents = list(
            container.query_items(
                query=query,
                parameters=parameters,
                enable_cross_partition_query=True,
            )
        )
        return sort_documents(select_current_documents(documents))[:ASSIGNED_KNOWLEDGE_CATALOG_DOCUMENT_LIMIT]
    except Exception as ex:
        log_event(
            "[AssignedKnowledge] Failed to query assigned knowledge catalog documents",
            level=logging.WARNING,
            debug_only=True,
            extra={"error": str(ex)},
        )
        return []


def _serialize_catalog_document(
    document: Dict[str, Any],
    *,
    scope: str,
    source_id: str,
    source_name: str,
) -> Dict[str, Any]:
    tags = sanitize_tags_for_filter(document.get("tags", []))
    return {
        "id": document.get("id") or document.get("document_id") or "",
        "file_name": document.get("file_name") or document.get("title") or "Untitled document",
        "title": document.get("title") or document.get("file_name") or "Untitled document",
        "scope": scope,
        "source_id": source_id,
        "source_name": source_name,
        "tags": tags,
    }


def _append_tag_counts(tag_counts: Dict[str, int], documents: List[Dict[str, Any]]) -> None:
    for document in documents:
        for tag in sanitize_tags_for_filter(document.get("tags", [])):
            tag_counts[tag] = tag_counts.get(tag, 0) + 1


def _get_personal_catalog_documents(user_id: str) -> List[Dict[str, Any]]:
    query = """
        SELECT * FROM c
        WHERE c.user_id = @user_id
            OR ARRAY_CONTAINS(c.shared_user_ids, @user_id)
            OR EXISTS(SELECT VALUE s FROM s IN c.shared_user_ids WHERE STARTSWITH(s, @user_id_prefix))
    """
    return _query_documents(
        cosmos_user_documents_container,
        query,
        [
            {"name": "@user_id", "value": user_id},
            {"name": "@user_id_prefix", "value": f"{user_id},"},
        ],
    )


def _get_group_catalog_documents(group_id: str) -> List[Dict[str, Any]]:
    query = """
        SELECT * FROM c
        WHERE c.group_id = @group_id
            OR ARRAY_CONTAINS(c.shared_group_ids, @group_id)
            OR EXISTS(SELECT VALUE s FROM s IN c.shared_group_ids WHERE STARTSWITH(s, @group_id_prefix))
    """
    return _query_documents(
        cosmos_group_documents_container,
        query,
        [
            {"name": "@group_id", "value": group_id},
            {"name": "@group_id_prefix", "value": f"{group_id},"},
        ],
    )


def _get_public_catalog_documents(public_workspace_ids: List[str]) -> List[Dict[str, Any]]:
    if not public_workspace_ids:
        return []
    conditions = []
    parameters = []
    for index, workspace_id in enumerate(public_workspace_ids):
        parameter_name = f"@workspace_id_{index}"
        conditions.append(f"c.public_workspace_id = {parameter_name}")
        parameters.append({"name": parameter_name, "value": workspace_id})

    query = f"SELECT * FROM c WHERE {' OR '.join(conditions)}"
    return _query_documents(cosmos_public_documents_container, query, parameters)


def _public_workspace_source_map(user_id: str, *, is_admin: bool) -> Dict[str, Dict[str, str]]:
    visible_ids = None if is_admin else _visible_public_workspace_id_set(user_id)
    workspaces = get_all_public_workspaces() or []
    source_map = {}
    for workspace in workspaces:
        workspace_id = str(workspace.get("id") or "").strip()
        if not workspace_id:
            continue
        if visible_ids is not None and workspace_id not in visible_ids:
            continue
        source_map[workspace_id] = {
            "scope": "public",
            "id": workspace_id,
            "label": workspace.get("name") or "Public workspace",
        }
    return source_map


def build_assigned_knowledge_catalog(
    *,
    user_id: str,
    agent_scope: str,
    group_id: Optional[str] = None,
    is_admin: bool = False,
) -> Dict[str, Any]:
    """Build the source, document, and tag catalog for the agent modal."""
    normalized_scope = str(agent_scope or "personal").strip().lower()
    sources = []
    documents = []
    tag_counts = {}

    if normalized_scope == "personal":
        sources.append({"scope": "personal", "id": "personal", "label": "Personal workspace"})
        personal_documents = _get_personal_catalog_documents(user_id)
        _append_tag_counts(tag_counts, personal_documents)
        documents.extend([
            _serialize_catalog_document(
                document,
                scope="personal",
                source_id="personal",
                source_name="Personal workspace",
            )
            for document in personal_documents
        ])

        public_sources = _public_workspace_source_map(user_id, is_admin=False)
        sources.extend(public_sources.values())
        public_documents = _get_public_catalog_documents(list(public_sources.keys()))
        _append_tag_counts(tag_counts, public_documents)
        for document in public_documents:
            source_id = str(document.get("public_workspace_id") or "")
            source = public_sources.get(source_id, {})
            documents.append(_serialize_catalog_document(
                document,
                scope="public",
                source_id=source_id,
                source_name=source.get("label") or "Public workspace",
            ))
    elif normalized_scope == "group":
        active_group_id = str(group_id or "").strip()
        group_doc = find_group_by_id(active_group_id) if active_group_id else None
        group_name = (group_doc or {}).get("name") or "Current group"
        if active_group_id:
            sources.append({"scope": "group", "id": active_group_id, "label": group_name})
            group_documents = _get_group_catalog_documents(active_group_id)
            _append_tag_counts(tag_counts, group_documents)
            documents.extend([
                _serialize_catalog_document(
                    document,
                    scope="group",
                    source_id=active_group_id,
                    source_name=group_name,
                )
                for document in group_documents
            ])
    elif normalized_scope == "global":
        public_sources = _public_workspace_source_map(user_id, is_admin=is_admin)
        sources.extend(public_sources.values())
        public_documents = _get_public_catalog_documents(list(public_sources.keys()))
        _append_tag_counts(tag_counts, public_documents)
        for document in public_documents:
            source_id = str(document.get("public_workspace_id") or "")
            source = public_sources.get(source_id, {})
            documents.append(_serialize_catalog_document(
                document,
                scope="public",
                source_id=source_id,
                source_name=source.get("label") or "Public workspace",
            ))

    tags = [
        {"name": name, "count": count}
        for name, count in sorted(tag_counts.items(), key=lambda item: item[0])
    ]
    return {
        "sources": sources,
        "documents": documents,
        "tags": tags,
    }
# document_source_selection.py
"""Bootstrap-free v2 document-source intent and scoped union filter construction."""

import json
from contextlib import contextmanager
from contextvars import ContextVar


_DOCUMENT_SOURCE_SCOPE = ContextVar("document_source_scope", default=None)


@contextmanager
def document_source_scope(user_id, sources):
    token = _DOCUMENT_SOURCE_SCOPE.set((user_id, sources))
    try:
        yield
    finally:
        _DOCUMENT_SOURCE_SCOPE.reset(token)


def assert_document_in_source_scope(document, user_id):
    """Constrain direct reads as well as search, including independently bound workers."""
    scope = _DOCUMENT_SOURCE_SCOPE.get()
    if scope is None:
        # Flask state survives stream_with_context; worker threads bind the ContextVar.
        from flask import g, has_request_context
        scope = getattr(g, "document_source_scope", None) if has_request_context() else None
    if scope is None:
        return
    actor, sources = scope
    if actor != user_id or not any(document_matches_source(document, source) for source in sources):
        raise PermissionError("That document is outside the selected sources.")


def document_matches_source(document, source):
    scope = source["scope"]
    kind = "public" if document.get("public_workspace_id") else "group" if document.get("group_id") else "personal"
    if scope["kind"] != kind:
        return False
    if kind == "public" and document.get("public_workspace_id") != scope["id"]:
        return False
    if kind == "group" and document.get("group_id") != scope["id"] and not any(
        entry in (scope["id"], f"{scope['id']},approved") for entry in document.get("shared_group_ids") or []
    ):
        return False
    return (
        source["kind"] == "workspace"
        or (source["kind"] == "document" and document.get("id") == source["id"])
        or (source["kind"] == "tag" and isinstance(document.get("tags"), list) and source["tag"] in document["tags"])
    )


class DocumentSourceSelectionError(ValueError):
    """A stable, user-safe selection error."""

    @property
    def public_message(self):
        return self.args[0]


def normalize_document_source_selection(value):
    if value is None:
        return None
    if (
        type(value) is not dict or set(value) != {"version", "mode", "sources"}
        or type(value["version"]) is not int or value["version"] != 1
        or value["mode"] not in ("all", "selected")
        or type(value["sources"]) is not list or len(value["sources"]) > 500
    ):
        raise DocumentSourceSelectionError("Choose valid document sources.")
    if value["mode"] == "all":
        if value["sources"]:
            raise DocumentSourceSelectionError("Search all documents cannot also restrict sources.")
        return {"version": 1, "mode": "all", "sources": []}
    sources = []
    seen = set()
    for source in value["sources"]:
        if type(source) is not dict:
            raise DocumentSourceSelectionError("Choose valid document sources.")
        kind = source.get("kind")
        field = "tag" if kind == "tag" else "id"
        expected = {"kind", "scope"} | ({field} if kind != "workspace" else set())
        scope = source.get("scope")
        if (
            kind not in ("workspace", "document", "tag") or set(source) != expected
            or type(scope) is not dict or scope.get("kind") not in ("personal", "group", "public")
            or set(scope) != ({"kind"} if scope.get("kind") == "personal" else {"kind", "id"})
        ):
            raise DocumentSourceSelectionError("Choose valid document sources.")
        normalized_scope = {"kind": scope["kind"]}
        if scope["kind"] != "personal":
            normalized_scope["id"] = _identifier(scope["id"])
        normalized = {"kind": kind, "scope": normalized_scope}
        if kind != "workspace":
            normalized[field] = _identifier(source.get(field))
        key = json.dumps(normalized, sort_keys=True)
        if key not in seen:
            seen.add(key)
            sources.append(normalized)
    if not sources:
        raise DocumentSourceSelectionError("Choose at least one source or turn document search off.")
    return {"version": 1, "mode": "selected", "sources": sources}


def _identifier(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 512:
        raise DocumentSourceSelectionError("Choose valid document sources.")
    return value.strip()


def selection_scope_fields(sources):
    """Compatibility projection for existing scope, manifest and plugin owners."""
    groups = sorted({s["scope"]["id"] for s in sources if s["scope"]["kind"] == "group"})
    public = sorted({s["scope"]["id"] for s in sources if s["scope"]["kind"] == "public"})
    kinds = {s["scope"]["kind"] for s in sources}
    documents_only = all(s["kind"] == "document" for s in sources)
    return {
        "doc_scope": next(iter(kinds)) if len(kinds) == 1 else "all",
        "active_group_ids": groups, "active_group_id": groups[0] if groups else None,
        "active_public_workspace_ids": public,
        "active_public_workspace_id": public[0] if public else None,
        "selected_document_ids": [s["id"] for s in sources] if documents_only else [],
        "selected_document_id": None,
        "tags": [],
        "hybrid_search": True,
    }


def source_union_filter(sources, scope_kind):
    """Return an OData restriction for one index; never a cross-workspace tag filter."""
    clauses = []
    for source in sources:
        scope = source["scope"]
        if scope["kind"] != scope_kind:
            continue
        owner = None
        if scope_kind != "personal":
            field = "group_id" if scope_kind == "group" else "public_workspace_id"
            owner = f"{field} eq '{_odata(scope['id'])}'"
            if scope_kind == "group":
                owner = f"({owner} or shared_group_ids/any(g: g eq '{_odata(scope['id'])},approved'))"
        content = None
        if source["kind"] == "document":
            content = f"document_id eq '{_odata(source['id'])}'"
        elif source["kind"] == "tag":
            content = f"document_tags/any(t: t eq '{_odata(source['tag'])}')"
        clauses.append(f"({owner} and {content})" if owner and content else owner or content or "true")
    return f"({' or '.join(clauses)})" if clauses else "false"


def _odata(value):
    return value.replace("'", "''")

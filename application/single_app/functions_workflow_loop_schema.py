# functions_workflow_loop_schema.py
"""Pure authored iterable validation; source authorization belongs to the reader."""

from functions_workflow_definitions import WorkflowDefinitionError, _name, _object, _text


WORKFLOW_LOOP_MAX_ITEMS = 5000
WORKFLOW_QUERY_FILTERS = frozenset({"search", "classification", "author", "keywords", "abstract", "tags"})
WORKFLOW_DOCUMENT_ITEM_SCHEMA = {
    "type": "object",
    "required": ["document_id", "scope_type", "scope_id"],
    "properties": {
        "document_id": {"type": "string"},
        "scope_type": {"type": "string", "enum": ["personal", "group", "public"]},
        "scope_id": {"type": "string"},
    },
}


def _scope(value, *, document=False):
    allowed = {"scope_type", "scope_id", "document_id"} if document else {"scope_type", "scope_id"}
    source = _object(value, allowed, "Iterable document" if document else "Iterable scope")
    scope_type = source.get("scope_type")
    if not isinstance(scope_type, str) or scope_type not in {"personal", "group", "public"}:
        raise WorkflowDefinitionError("An iterable requires an explicit personal, group or public scope.")
    normalized = {"scope_type": scope_type}
    if scope_type == "personal":
        if "scope_id" in source:
            raise WorkflowDefinitionError("Personal iterable ownership is server-derived; omit scope_id.")
    else:
        normalized["scope_id"] = _text(source.get("scope_id"), "Iterable scope id")
    if document:
        normalized["document_id"] = _text(source.get("document_id"), "Iterable document id", 256)
    return normalized


def normalize_workflow_iterable(value, *, max_items):
    """Validate authored sources without resolving documents, results or permissions."""
    if type(max_items) is not int or not 1 <= max_items <= WORKFLOW_LOOP_MAX_ITEMS:
        raise WorkflowDefinitionError(f"Loop max_items must be an integer between 1 and {WORKFLOW_LOOP_MAX_ITEMS}.")
    if not isinstance(value, dict):
        raise WorkflowDefinitionError("A loop iterable must be an object.")
    kind = value.get("kind")
    if kind == "input":
        _object(value, {"kind", "name"}, "Input iterable")
        return {"kind": kind, "name": _name(value.get("name"), "Iterable input name")}
    if kind == "documents":
        _object(value, {"kind", "documents"}, "Documents iterable")
        documents = value.get("documents")
        if not isinstance(documents, list) or len(documents) > max_items:
            raise WorkflowDefinitionError("Selected documents must be a list within the loop's max_items limit.")
        normalized, identities = [], set()
        for document in documents:
            source = _scope(document, document=True)
            identity = (source["scope_type"], source.get("scope_id"), source["document_id"])
            if identity in identities:
                raise WorkflowDefinitionError("Selected documents must not contain duplicate document identities.")
            identities.add(identity)
            normalized.append(source)
        return {"kind": kind, "documents": normalized}
    if kind != "workspace_query":
        raise WorkflowDefinitionError("An iterable must select a saved input, documents or a workspace query.")
    _object(value, {"kind", "scopes", "filters", "content", "selection"}, "Workspace query iterable")
    scopes = value.get("scopes")
    if not isinstance(scopes, list) or not 1 <= len(scopes) <= 100:
        raise WorkflowDefinitionError("A workspace query requires 1 to 100 explicit scopes.")
    normalized_scopes, identities = [], set()
    for scope in scopes:
        source = _scope(scope)
        identity = (source["scope_type"], source.get("scope_id"))
        if identity in identities:
            raise WorkflowDefinitionError("Workspace query scopes must be unique.")
        identities.add(identity)
        normalized_scopes.append(source)
    filters = _object(value.get("filters"), WORKFLOW_QUERY_FILTERS, "Workspace query filters")
    normalized_filters = {}
    for name, raw in filters.items():
        if name == "tags":
            if not isinstance(raw, list) or len(raw) > 100:
                raise WorkflowDefinitionError("Query tags must be a list of at most 100 tags.")
            tags = [_text(tag, "Query tag", 256) for tag in raw]
            if len(set(tags)) != len(tags):
                raise WorkflowDefinitionError("Query tags must not contain duplicates.")
            normalized_filters[name] = tags
        else:
            normalized_filters[name] = _text(raw, "Query metadata filter", 1000)
    content = None
    if "content" in value:
        raw = _object(value["content"], {"mode", "query"}, "Query content")
        mode = raw.get("mode")
        if not isinstance(mode, str) or mode not in {"keyword", "hybrid"}:
            raise WorkflowDefinitionError("Query content supports keyword or hybrid matching.")
        content = {"mode": mode, "query": _text(raw.get("query"), "Content query", 4000)}
    selection = value.get("selection")
    if not isinstance(selection, dict):
        raise WorkflowDefinitionError("A workspace query requires an explicit selection policy.")
    mode = selection.get("mode")
    if mode == "all_matches":
        _object(selection, {"mode"}, "All matches selection")
        if content and content["mode"] != "keyword":
            raise WorkflowDefinitionError("All matches supports metadata or keyword content, not exhaustive hybrid relevance.")
        normalized_selection = {"mode": mode}
    elif mode == "best_n":
        _object(selection, {"mode", "count"}, "Best N selection")
        count = selection.get("count")
        if type(count) is not int or not 1 <= count <= max_items:
            raise WorkflowDefinitionError("Best N count must be a positive integer within the loop's max_items limit.")
        if content is None:
            raise WorkflowDefinitionError("Best N requires an explicit keyword or hybrid content query.")
        normalized_selection = {"mode": mode, "count": count}
    else:
        raise WorkflowDefinitionError("A workspace query must select all_matches or best_n.")
    result = {
        "kind": kind, "scopes": normalized_scopes, "filters": normalized_filters,
        "selection": normalized_selection,
    }
    if content is not None:
        result["content"] = content
    return result

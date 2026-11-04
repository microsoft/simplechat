# document_chunk_counts.py
"""Exact Search key counts, including acknowledged writes not yet visible to search."""

from contextvars import ContextVar

from flask import g, has_request_context


_chunk_writes = ContextVar("document_chunk_writes", default=None)
INDEXED_CHUNK_COUNT_VERSION_FIELD = "indexed_chunk_count_version"


def _count_identity(document):
    scope_field = next(
        (field for field in ("public_workspace_id", "group_id", "user_id") if document.get(field) is not None),
        "user_id",
    )
    return (
        scope_field, document.get(scope_field), document.get("id"), document.get("version") or 1,
        document.get("_etag"),
    )


def remember_verified_chunk_count(document, count):
    """Keep a detail lookup through fresh-source response guards, never across requests or revisions."""
    if has_request_context() and document.get("_etag"):
        counts = g.setdefault("_verified_document_chunk_counts", {})
        counts[_count_identity(document)] = count


def chunk_count_for_response(document):
    """An unrecorded historical zero is unknown, not evidence that the index is empty."""
    if has_request_context() and document.get("_etag"):
        counts = g.get("_verified_document_chunk_counts", {})
        identity = _count_identity(document)
        if identity in counts:
            return counts[identity]
    count = document.get("num_chunks")
    if type(count) is not int or count < 0:
        return None
    recorded_version = document.get(INDEXED_CHUNK_COUNT_VERSION_FIELD)
    if recorded_version is not None:
        return count if recorded_version == (document.get("version") or 1) else None
    if count > 0:
        return count
    return None


def begin_chunk_tracking():
    return _chunk_writes.set({})


def end_chunk_tracking(token):
    _chunk_writes.reset(token)


def record_chunk_uploads(search_client, documents, results):
    writes = _chunk_writes.get()
    if writes is None:
        return
    succeeded_keys = {
        result.get("key") if isinstance(result, dict) else result.key
        for result in results
        if (result.get("succeeded", False) if isinstance(result, dict) else result.succeeded)
    }
    for document in documents:
        if document["id"] in succeeded_keys:
            writes[(id(search_client), document["id"])] = {
                field: document.get(field)
                for field in ("document_id", "version", "user_id", "group_id", "public_workspace_id")
            }


def record_chunk_deletions(search_client, keys):
    writes = _chunk_writes.get()
    if writes is not None:
        for key in keys:
            writes[(id(search_client), key)] = None


def count_indexed_chunks(search_client, document_id, version, scope_field, scope_value):
    """Count distinct keys for one source version, never pages or approximate Search totals."""
    if scope_field not in {"user_id", "group_id", "public_workspace_id"}:
        raise ValueError("Invalid document chunk scope.")
    if not document_id or not scope_value:
        raise ValueError("A document id and workspace scope are required.")
    version = int(version)
    if version < 1:
        raise ValueError("A positive document version is required.")

    def literal(value):
        return str(value).replace("'", "''")

    base_filter = (
        f"document_id eq '{literal(document_id)}' and "
        f"{scope_field} eq '{literal(scope_value)}' and version eq {version}"
    )
    keys = set()
    last_key = None
    page_size = 1000
    while True:
        page_filter = base_filter
        if last_key is not None:
            page_filter += f" and id gt '{literal(last_key)}'"
        results = search_client.search(
            search_text="*", filter=page_filter, select=["id"],
            order_by=["id asc"], top=page_size,
        )
        page = [result["id"] for result in results]
        if not page:
            break
        if page != sorted(set(page)) or (last_key is not None and page[0] <= last_key):
            raise RuntimeError("Search chunk key paging did not advance.")
        keys.update(page)
        if len(page) < page_size:
            break
        last_key = page[-1]

    # Search is near-real-time. Apply this job's acknowledged mutations by key;
    # an overwrite is still one chunk, and an unacknowledged write is not invented.
    for (client_id, key), chunk in (_chunk_writes.get() or {}).items():
        if client_id != id(search_client):
            continue
        if chunk is None:
            keys.discard(key)
        elif chunk["document_id"] == document_id:
            if chunk["version"] == version and chunk[scope_field] == scope_value:
                keys.add(key)
            else:
                keys.discard(key)
    return len(keys)

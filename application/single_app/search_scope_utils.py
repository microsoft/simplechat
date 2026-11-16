# search_scope_utils.py
"""Pure search scope and identifier normalization, safe during bootstrap."""

VALID_SEARCH_SCOPES = {"all", "personal", "group", "public"}


def normalize_search_scope(doc_scope, default_scope="all"):
    normalized_scope = str(doc_scope or default_scope).strip().lower()
    if normalized_scope not in VALID_SEARCH_SCOPES:
        return default_scope
    return normalized_scope


def normalize_search_id_list(raw_ids):
    if raw_ids is None:
        return []
    if isinstance(raw_ids, str):
        candidate_ids = [value.strip() for value in raw_ids.split(",") if value.strip()]
    elif isinstance(raw_ids, list):
        candidate_ids = [str(value).strip() for value in raw_ids if str(value).strip()]
    else:
        candidate_ids = [str(raw_ids).strip()] if str(raw_ids).strip() else []
    normalized_ids = []
    seen_ids = set()
    for candidate_id in candidate_ids:
        if candidate_id not in seen_ids:
            seen_ids.add(candidate_id)
            normalized_ids.append(candidate_id)
    return normalized_ids

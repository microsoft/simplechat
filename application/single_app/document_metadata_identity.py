# document_metadata_identity.py
"""Bootstrap-free identities shared by source records and access projections."""

import json
from collections.abc import Mapping

from content_screening.contracts import SCREENING_FIELD, hash_payload


def document_cache_identity(document: Mapping, *, document_id=None) -> str:
    identifier = document["id"] if document_id is None else document_id
    identity = f"{identifier}:v{document.get('version') or 1}"
    if document.get("_etag"):
        identity = f"{identity}:revision:{document['_etag']}"
    if SCREENING_FIELD in document:
        identity = f"{identity}:screening:{hash_payload(document[SCREENING_FIELD])}"
    return identity


def document_family_identity(document: Mapping, source_scope=None) -> str:
    if source_scope is None:
        source_scope = (
            "public" if document.get("public_workspace_id") or document.get("owner_public_workspace_id")
            else "group" if document.get("group_id") or document.get("owner_group_id")
            else "personal"
        )
    owner_fields = {
        "public": ("owner_public_workspace_id", "public_workspace_id"),
        "group": ("owner_group_id", "group_id"),
        "personal": ("owner_user_id", "user_id"),
    }
    owner = next(
        (document.get(field) for field in owner_fields[source_scope] if document.get(field)),
        "unknown",
    )
    family = document.get("revision_family_id")
    legacy = (
        document.get("xsd_revision_identity")
        if document.get("document_kind") == "xml_schema"
        else document.get("file_name")
    )
    return json.dumps(
        [source_scope, str(owner), "family" if family else "legacy", str(family or legacy or "")],
        separators=(",", ":"),
    )

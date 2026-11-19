# functions_legacy_document_upgrade.py
"""Scope-explicit upgrade of documents stored before processing progress was tracked.

A document without ``percentage_complete`` predates progress tracking. The classic upgrade
routes backfill those documents for the *saved* active group or public workspace, and the
public path of ``upgrade_legacy_documents`` writes through its personal branch, so it never
reaches a public workspace's documents. The V2 workspaces name their scope in the request
path instead, so these functions take the scope from the caller's explicit target: the route
authorizes it, and ``authorize`` is asked again before every document is written, so a role
or status change part-way through stops the upgrade rather than finishing it.
"""

import logging

from werkzeug.exceptions import HTTPException

from config import cosmos_group_documents_container, cosmos_public_documents_container
from functions_appinsights import log_event
from functions_documents import update_document


# One request upgrades at most this many documents, which keeps it bounded in time and memory.
# The list flag stays set while documents remain, and the receipt says so.
MAX_LEGACY_UPGRADE_DOCUMENTS = 500
LEGACY_UPGRADE_FAILED = "legacy_upgrade_failed"
LEGACY_UPGRADE_FAILURE_MESSAGE = "Unable to update this document."

_LEGACY_PROJECTION = "c.id, c.file_name, c.number_of_pages, c.num_chunks"
_GROUP_LEGACY_QUERY = (
    f"SELECT TOP @limit {_LEGACY_PROJECTION} FROM c "
    "WHERE c.group_id = @owner AND NOT IS_DEFINED(c.percentage_complete)"
)
_PUBLIC_LEGACY_QUERY = (
    f"SELECT TOP @limit {_LEGACY_PROJECTION} FROM c "
    "WHERE c.public_workspace_id = @owner AND NOT IS_DEFINED(c.percentage_complete)"
)


def legacy_upgrade_fields(document):
    """The values that bring one legacy document to the current format.

    The same values the classic upgrade writes, so both interfaces leave a document in the
    same state.
    """
    pages = document.get("number_of_pages", document.get("num_chunks", 1))
    return {
        "status": "Processing complete",
        "percentage_complete": 100,
        "num_chunks": pages,
        "number_of_pages": pages,
        "current_file_chunk": document.get("num_chunks", 1),
        "num_file_chunks": 1,
        "enhanced_citations": False,
        "document_classification": "None",
        "title": "",
        "authors": [],
        "organization": "",
        "publication_date": "",
        "keywords": [],
        "abstract": "",
    }


def _legacy_documents(container, query, owner_id):
    """The workspace's legacy documents, at most one request's worth, and whether more remain."""
    rows = list(container.query_items(
        query=query,
        parameters=[
            {"name": "@owner", "value": owner_id},
            {"name": "@limit", "value": MAX_LEGACY_UPGRADE_DOCUMENTS + 1},
        ],
        enable_cross_partition_query=True,
    ))
    return rows[:MAX_LEGACY_UPGRADE_DOCUMENTS], len(rows) > MAX_LEGACY_UPGRADE_DOCUMENTS


def _receipt_message(label, upgraded, failed, remaining):
    message = f"Upgraded {upgraded} {label} document(s) to the new format."
    if failed:
        message += f" {failed} could not be updated."
    if remaining:
        message += " More older documents remain; update again to continue."
    return message


def upgrade_legacy_scope_documents(user_id, *, authorize, group_id=None, public_workspace_id=None):
    """Upgrade the legacy documents of exactly one group or public workspace.

    ``authorize`` is called before the first read and again before each document; it must
    raise to refuse, and a refusal (an ``HTTPException``) propagates untouched. Any other
    failure is recorded against its document and the rest are still upgraded, so one bad
    document never blocks the others. Returns ``(receipt, status)``: 200 when every
    document was upgraded, 207 when any could not be.
    """
    if (group_id is None) == (public_workspace_id is None):
        raise ValueError("Name exactly one group or public workspace to upgrade.")
    if group_id is not None:
        container, query, owner_id = cosmos_group_documents_container, _GROUP_LEGACY_QUERY, group_id
        scope_field, label, scope_extra = "group_id", "group", {"shared_group_ids": []}
    else:
        container, query, owner_id = cosmos_public_documents_container, _PUBLIC_LEGACY_QUERY, public_workspace_id
        scope_field, label, scope_extra = "public_workspace_id", "public workspace", {}

    authorize()
    documents, remaining = _legacy_documents(container, query, owner_id)
    upgraded = 0
    errors = []
    for document in documents:
        authorize()
        try:
            update_document(
                document_id=document["id"], user_id=user_id, **{scope_field: owner_id},
                **legacy_upgrade_fields(document), **scope_extra,
            )
            upgraded += 1
        except HTTPException:
            raise
        except Exception as error:
            log_event(
                "[DOCUMENTS] A legacy document could not be upgraded.",
                extra={"document_id": document["id"], scope_field: owner_id, "exception_type": type(error).__name__},
                level=logging.ERROR,
            )
            errors.append({
                "document_id": document["id"], "file_name": document.get("file_name"),
                "error": LEGACY_UPGRADE_FAILED, "message": LEGACY_UPGRADE_FAILURE_MESSAGE,
            })
    log_event(
        "[DOCUMENTS] Legacy documents upgraded.",
        extra={
            scope_field: owner_id, "user_id": user_id, "upgraded_count": upgraded,
            "failed_count": len(errors), "remaining": remaining,
        },
    )
    receipt = {
        "message": _receipt_message(label, upgraded, len(errors), remaining),
        "upgraded_count": upgraded, "remaining": remaining, "errors": errors, scope_field: owner_id,
    }
    return receipt, 207 if errors else 200

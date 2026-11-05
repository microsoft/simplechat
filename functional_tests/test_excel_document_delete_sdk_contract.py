# test_excel_document_delete_sdk_contract.py
"""
Owner-runtime SDK contract for Excel document and private-inventory cleanup.
Version: 0.261.405
Implemented in: 0.261.405

The actual deletion function consumes installed-SDK CosmosDict point responses.
External logging, Search, and blob side effects are isolated and scope checked.
"""

import ast
from pathlib import Path
import os
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

import pytest
from azure.core import MatchConditions
from azure.cosmos._cosmos_responses import CosmosDict
from azure.cosmos.exceptions import CosmosResourceNotFoundError

APP = Path(__file__).resolve().parents[1] / "application" / "single_app"
sys.path.insert(0, str(APP))

from content_screening.contracts import ScreeningConflictError, subject_from_document  # noqa: E402
from test_support.offline_bootstrap import OfflineContainer  # noqa: E402


def load_delete(container, calls):
    source = ast.parse((APP / "functions_documents.py").read_text(encoding="utf-8"))
    node = next(node for node in source.body if isinstance(node, ast.FunctionDef) and node.name == "delete_document")
    namespace = {
        "os": os, "cosmos_user_documents_container": container,
        "cosmos_group_documents_container": container, "cosmos_public_documents_container": container,
        "SCREENING_FIELD": "content_screening", "EXCEL_INVENTORY_FIELD": "excel_native_inventory",
        "ScreeningConflictError": ScreeningConflictError,
        "CosmosResourceNotFoundError": CosmosResourceNotFoundError, "MatchConditions": MatchConditions,
        "subject_from_document": subject_from_document,
        "prepare_document_deletion": lambda document, actor: calls.append(("private_cleanup", document, actor)),
        "clear_excel_inventory_cache": lambda subject: calls.append(("cache_cleanup", subject)),
        "delete_from_blob_storage": lambda document, **kwargs: calls.append(("source_cleanup", document, kwargs)),
        "delete_document_access_index_for_document_fail_open": lambda document, **kwargs: {"success": True},
        "assert_group_document_source_writable": lambda document: None,
    }
    exec(compile(ast.Module(body=[node], type_ignores=[]), "functions_documents.py", "exec"), namespace)
    return namespace["delete_document"]


@pytest.mark.parametrize("scope", ["personal", "group", "public"])
def test_real_delete_owner_handles_sdk_points_and_scope_bound_native_cleanup(scope):
    container, calls = OfflineContainer(), []
    document = {"id": "document", "user_id": "owner", "file_name": "review.xlsx", "version": 1}
    kwargs = {}
    if scope == "group":
        document["group_id"] = "group"
        kwargs["group_id"] = "group"
    elif scope == "public":
        document["public_workspace_id"] = "public"
        kwargs["public_workspace_id"] = "public"
    saved = container.upsert_item(document)
    assert isinstance(saved, CosmosDict)
    delete = load_delete(container, calls)
    debug, activity = ModuleType("functions_debug"), ModuleType("functions_activity_logging")
    debug.debug_print = lambda *args: None
    activity.log_document_deletion_transaction = lambda **kwargs: calls.append(("activity", kwargs))
    with patch.dict(sys.modules, {"functions_debug": debug, "functions_activity_logging": activity}):
        delete("owner", "document", strict=True, expected_etag=saved["_etag"], **kwargs)
    assert "document" not in container.items
    private = next(call for call in calls if call[0] == "private_cleanup")
    assert isinstance(private[1], CosmosDict)
    assert private[1]["id"] == "document" and private[2] == "owner"
    assert next(call for call in calls if call[0] == "cache_cleanup")[1] == subject_from_document(document)
    source = next(call for call in calls if call[0] == "source_cleanup")
    assert source[2]["strict"] is True


def test_stale_sdk_etag_prevents_private_inventory_deletion():
    container, calls = OfflineContainer(), []
    container.upsert_item({"id": "document", "user_id": "owner", "file_name": "review.xlsx", "version": 1})
    delete = load_delete(container, calls)
    debug = ModuleType("functions_debug")
    debug.debug_print = lambda *args: None
    with patch.dict(sys.modules, {"functions_debug": debug}):
        with pytest.raises(ScreeningConflictError):
            delete("owner", "document", strict=True, expected_etag="stale")
    assert not calls and "document" in container.items

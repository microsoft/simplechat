# test_content_screening_activity.py
"""
Functional tests for retry-safe screening activity records.
Version: 0.261.106
Implemented in: 0.261.106

Exercises the existing activity-log functions with a fake Cosmos boundary so
publication reconciliation preserves document/embedding reporting without
duplicating records or logging source text on a storage failure.
"""

import ast
from copy import deepcopy
from datetime import datetime
import logging
from pathlib import Path
from typing import Optional
import uuid

from azure.cosmos.exceptions import CosmosResourceExistsError


class ActivityContainer:
    def __init__(self):
        self.records = {}
        self.failure = None

    def create_item(self, body):
        if self.failure:
            raise self.failure
        key = body["id"], body["user_id"]
        if key in self.records:
            raise CosmosResourceExistsError(status_code=409)
        self.records[key] = deepcopy(body)

    def read_item(self, item, partition_key):
        return deepcopy(self.records[(item, partition_key)])


def namespace():
    source = Path(__file__).resolve().parents[1] / "application" / "single_app" / "functions_activity_logging.py"
    wanted = {"_create_activity_record", "log_document_creation_transaction", "log_token_usage"}
    tree = ast.parse(source.read_text(encoding="utf-8"))
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in wanted]
    logs = []
    state = {
        "uuid": uuid, "datetime": datetime, "Optional": Optional, "logging": logging,
        "CosmosResourceExistsError": CosmosResourceExistsError,
        "cosmos_activity_logs_container": ActivityContainer(),
        "log_event": lambda *args, **kwargs: logs.append((args, kwargs)),
        "debug_print": lambda *args, **kwargs: None,
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), "exec"), state)
    return state, logs


def test_document_and_embedding_reconciliation_are_idempotent():
    state, _logs = namespace()
    creation = state["log_document_creation_transaction"]
    arguments = dict(
        user_id="owner", document_id="document", workspace_type="personal",
        file_name="Screened document", idempotency_key="document-release",
    )
    first = creation(**arguments)
    second = creation(**arguments)
    assert first == second
    usage = state["log_token_usage"]
    tokens = dict(user_id="owner", token_type="embedding", total_tokens=12, model="embedding", idempotency_key="scan-embedding")
    assert usage(**tokens) == usage(**tokens)
    assert len(state["cosmos_activity_logs_container"].records) == 2


def test_legacy_calls_keep_independent_activity_records():
    state, _logs = namespace()
    arguments = dict(user_id="owner", document_id="document", workspace_type="personal", file_name="example.txt")
    first = state["log_document_creation_transaction"](**arguments)
    second = state["log_document_creation_transaction"](**arguments)
    assert first["id"] != second["id"]


def test_failed_activity_write_is_explicit_and_does_not_echo_provider_details():
    state, logs = namespace()
    state["cosmos_activity_logs_container"].failure = RuntimeError("PRIVATE_PROVIDER_SECRET")
    result = state["log_document_creation_transaction"](
        user_id="owner", document_id="document", workspace_type="personal", file_name="Screened document",
    )
    assert result is None
    assert logs
    assert "PRIVATE_PROVIDER_SECRET" not in repr(logs)

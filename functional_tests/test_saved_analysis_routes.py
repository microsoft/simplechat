# test_saved_analysis_routes.py
"""
Functional tests for the saved Analyze result reader route.
Version: 0.261.109
Implemented in: 0.261.109

The production route runs against serialized saved results, including page
bounds, current source access, evidence selection, and stale references.
"""

import ast
import hashlib
import json
import logging
from pathlib import Path
from urllib.parse import urlencode

import pytest
from azure.core.exceptions import AzureError
from azure.cosmos.exceptions import CosmosResourceNotFoundError
from flask import Flask, jsonify, request

from test_saved_analysis_service import read_options, saved, saved_chat


@pytest.fixture
def analysis_client(saved_chat):
    fixture = saved_chat
    path = Path(__file__).resolve().parents[1] / "application" / "single_app" / "route_backend_analysis_results.py"
    function = next(
        node for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.FunctionDef) and node.name == "get_saved_analysis_result"
    )
    function.decorator_list = []
    state = {"user_id": "reader"}

    def diagnostic_bytes(user_id, binding, reference, *, offset, limit, **kwargs):
        content = fixture["store"].contents[(
            binding["user_id"], binding["conversation_id"], binding["message_id"], reference["sha256"],
        )]
        end = min(offset + limit, len(content))
        page = content[offset:end]
        return {
            "content": page, "offset": offset, "next_offset": end if end < len(content) else None,
            "total_bytes": len(content), "sha256": reference["sha256"], "complete": end == len(content),
            "media_type": "application/json",
            "integrity": {"page_sha256": hashlib.sha256(page.encode("ascii")).hexdigest()},
        }

    namespace = {
        "get_current_user_id": lambda: state["user_id"],
        "MAX_ANALYSIS_PAGE_RECORDS": saved.MAX_ANALYSIS_PAGE_RECORDS,
        "MAX_ANALYSIS_DIAGNOSTIC_PAGE_BYTES": saved.MAX_ANALYSIS_DIAGNOSTIC_PAGE_BYTES,
        "read_saved_analysis_page": lambda user_id, context, **kwargs: saved.read_saved_analysis_page(
            user_id, context, **kwargs, **read_options(fixture), diagnostics_page_reader=diagnostic_bytes,
        ),
        "request": request, "jsonify": jsonify, "logging": logging,
        "AzureError": AzureError, "CosmosResourceNotFoundError": CosmosResourceNotFoundError,
        "WorkflowResultStorageUnavailableError": saved.WorkflowResultStorageUnavailableError,
        "log_event": lambda *args, **kwargs: None,
    }
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(path), "exec"), namespace)
    app = Flask("saved-analysis-tests")
    app.add_url_rule("/api/analysis_results", view_func=namespace["get_saved_analysis_result"])
    return app.test_client(), state, fixture


def result_url(fixture, **extra):
    return "/api/analysis_results?" + urlencode({
        **saved.saved_analysis_context(fixture["descriptor"]), **extra,
    })


def test_second_page_is_available_without_reanalysis(analysis_client):
    client, state, fixture = analysis_client
    response = client.get(result_url(fixture, offset=25, limit=25))
    assert response.status_code == 200
    assert response.json["total_records"] == 60
    assert response.json["records"][0]["record_id"] == "record-25"
    assert response.json["next_offset"] == 50


def test_source_revocation_returns_no_result_data(analysis_client):
    client, state, fixture = analysis_client
    fixture["state"]["source_allowed"] = False
    response = client.get(result_url(fixture))
    assert response.status_code == 403
    assert set(response.json) == {"error"}
    assert "Control" not in response.get_data(as_text=True)


def test_record_evidence_uses_the_same_result_version(analysis_client):
    client, state, fixture = analysis_client
    response = client.get(result_url(fixture, representation="evidence", record_id="record-3"))
    assert response.status_code == 200
    assert response.json["evidence"][0]["evidence_id"] == "evidence-3"
    assert response.json["result_sha256"] == fixture["descriptor"]["result_sha256"]


@pytest.mark.parametrize("extra", [{"offset": -1}, {"limit": 101}, {"limit": "no"}, {"representation": "raw_sql"}])
def test_invalid_ranges_or_representations_are_rejected(analysis_client, extra):
    client, state, fixture = analysis_client
    assert client.get(result_url(fixture, **extra)).status_code == 400
    assert fixture["store"].reads == []


def test_stale_result_does_not_silently_switch_versions(analysis_client):
    client, state, fixture = analysis_client
    response = client.get(result_url(fixture, result_sha256="0" * 64))
    assert response.status_code == 409
    assert set(response.json) == {"error"}


def test_missing_user_is_not_an_authorized_result_read(analysis_client):
    client, state, fixture = analysis_client
    state["user_id"] = None
    assert client.get(result_url(fixture)).status_code == 401
    assert fixture["store"].reads == []


def test_explicit_diagnostics_are_audit_only_byte_transport(analysis_client):
    client, _, fixture = analysis_client
    response = client.get(result_url(fixture, representation="diagnostics"))
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert response.json["audit_only"] is True
    assert response.json["canonical_model_input"] is False
    assert response.json["transport"]["offset_unit"] == "bytes"
    assert "RAW-NOTE-ONLY" in json.loads(response.json["content"])["value"]["analysis"]["raw_analysis_items"][0]["text"]
    default = client.get(result_url(fixture))
    assert "RAW-NOTE-ONLY" not in default.get_data(as_text=True)


@pytest.mark.parametrize("limit,status", [(65536, 200), (65537, 400), (0, 400)])
def test_diagnostic_limits_are_bytes_not_record_counts(analysis_client, limit, status):
    client, _, fixture = analysis_client
    assert client.get(result_url(fixture, representation="diagnostics", limit=limit)).status_code == status

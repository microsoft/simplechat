# test_m365_json_response_finalization.py
"""
Regression tests for the M365 after-request hook and file/stream responses.
Version: 0.261.048
Implemented in: 0.261.048

Loads the actual response hook into a minimal Flask app without importing the
cloud-initializing application bootstrap. Exercises real Flask file responses,
conditional requests, streams, and buffered JSON with outbound networking blocked.
"""

import ast
from io import BytesIO
from pathlib import Path
import socket
from unittest.mock import Mock

from flask import Flask, Response, jsonify, send_file
import pytest


APP_ROOT = Path(__file__).resolve().parents[1] / "application" / "single_app"
SCHEMA_URL = "/static/json/schemas/plugin.schema.json"
SCHEMA_PATH = APP_ROOT / "static" / "json" / "schemas" / "plugin.schema.json"


@pytest.fixture
def response_app(monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError("Response hook tests must not contact cloud services.")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    app = Flask(__name__, static_folder=str(APP_ROOT / "static"), static_url_path="/static")
    app.config["TESTING"] = True
    complete = Mock()
    tree = ast.parse((APP_ROOT / "app.py").read_text(encoding="utf-8"))
    hook = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "finalize_m365_json_request"
    )
    namespace = {"app": app, "complete_m365_request": complete}
    exec(compile(ast.Module(body=[hook], type_ignores=[]), "app.py", "exec"), namespace)
    return app, complete, namespace["finalize_m365_json_request"]


def test_static_plugin_schema_is_delivered_unchanged(response_app):
    app, complete, _ = response_app
    with app.test_client() as client:
        response = client.get(SCHEMA_URL)
        assert response.status_code == 200
        assert response.mimetype == "application/json"
        assert response.data == SCHEMA_PATH.read_bytes()
        assert response.get_json()["$ref"] == "#/definitions/Plugin"
        assert response.headers["Content-Length"] == str(SCHEMA_PATH.stat().st_size)
        assert response.headers["ETag"]
        assert response.headers["Last-Modified"]
        response.close()
    complete.assert_not_called()


def test_static_schema_preserves_head_range_and_conditional_requests(response_app):
    app, complete, _ = response_app
    with app.test_client() as client:
        initial = client.get(SCHEMA_URL)
        etag = initial.headers["ETag"]
        modified = initial.headers["Last-Modified"]
        initial.close()

        head = client.head(SCHEMA_URL)
        assert head.status_code == 200
        assert head.data == b""
        assert head.headers["Content-Length"] == str(SCHEMA_PATH.stat().st_size)
        head.close()

        partial = client.get(SCHEMA_URL, headers={"Range": "bytes=0-9"})
        assert partial.status_code == 206
        assert partial.data == SCHEMA_PATH.read_bytes()[:10]
        assert partial.headers["Content-Range"] == f"bytes 0-9/{SCHEMA_PATH.stat().st_size}"
        partial.close()

        for headers in ({"If-None-Match": etag}, {"If-Modified-Since": modified}):
            cached = client.get(SCHEMA_URL, headers=headers)
            assert cached.status_code == 304
            assert cached.data == b""
            cached.close()
    complete.assert_not_called()


def test_json_download_remains_direct_passthrough(response_app):
    app, complete, finalize = response_app
    with app.test_request_context("/download"):
        response = send_file(
            BytesIO(b'{"export": "unchanged"}'),
            mimetype="application/json",
            as_attachment=True,
            download_name="export.json",
        )
        assert response.direct_passthrough
        original_iterable = response.response
        assert finalize(response) is response
        assert response.direct_passthrough
        assert response.response is original_iterable
        assert b"".join(response.response) == b'{"export": "unchanged"}'
        assert response.headers["Content-Disposition"] == "attachment; filename=export.json"
        response.close()
    complete.assert_not_called()


def test_buffered_passthrough_json_is_not_parsed(response_app):
    app, complete, finalize = response_app
    with app.test_request_context("/download"):
        response = Response([b'{"success":true}'], mimetype="application/json", direct_passthrough=True)
        assert not response.is_streamed
        assert finalize(response) is response
        assert response.direct_passthrough
        response.close()
    complete.assert_not_called()


@pytest.mark.parametrize("mimetype", ["application/json", "application/problem+json", "text/event-stream"])
def test_stream_is_not_consumed_or_finalized_early(response_app, mimetype):
    app, complete, finalize = response_app
    consumed = []

    def chunks():
        consumed.append("first")
        yield b'{"success":'
        consumed.append("last")
        yield b"true}"

    with app.test_request_context("/stream"):
        stream = chunks()
        response = Response(stream, mimetype=mimetype)
        assert response.is_streamed
        assert not response.direct_passthrough
        assert finalize(response) is response
        assert response.response is stream
        assert consumed == []
        complete.assert_not_called()
        assert b"".join(response.response) == b'{"success":true}'
        assert consumed == ["first", "last"]
        response.close()


@pytest.mark.parametrize(
    "payload,status,expected_success",
    [
        ({"result": "done"}, 200, True),
        ({}, 200, True),
        ({"success": True}, 201, True),
        ({"error": "request failed"}, 200, False),
        ({"pending": True}, 202, False),
        ({"success": False}, 200, False),
        ({"result": "denied"}, 403, False),
        ({"error": "server failure"}, 500, False),
        ([], 200, False),
        (None, 200, False),
        ("result", 200, False),
    ],
)
def test_buffered_json_keeps_existing_completion_contract(response_app, payload, status, expected_success):
    app, complete, _ = response_app

    def result():
        return jsonify(payload), status

    app.add_url_rule("/result", view_func=result)
    with app.test_client() as client:
        response = client.get("/result")
        assert response.status_code == status
        assert response.get_json() == payload
        response.close()
    complete.assert_called_once_with(success=expected_success)


def test_non_json_response_is_untouched(response_app):
    app, complete, finalize = response_app
    response = Response("plain text", mimetype="text/plain")
    with app.test_request_context():
        assert finalize(response) is response
        assert response.get_data(as_text=True) == "plain text"
        response.close()
    complete.assert_not_called()


def test_completion_failures_are_not_silenced(response_app):
    app, complete, finalize = response_app
    complete.side_effect = RuntimeError("Completion failed")
    with app.test_request_context():
        with pytest.raises(RuntimeError, match="Completion failed"):
            finalize(jsonify({"result": "done"}))

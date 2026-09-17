# test_v2_artifact_download_cors.py
"""
Functional regression for separately hosted V2 artifact attachment headers.
Version: 0.261.113
Implemented in: 0.261.113

The production response hook must expose Content-Disposition to the exact
configured frontend origin without granting other origins credentialed access.
"""

import ast
from pathlib import Path

import pytest
from flask import Flask, Response, request

from test_support.app_stubs import stubbed_config


TRUSTED_ORIGIN = "https://v2.example.test"
APP_FILE = Path(__file__).resolve().parents[1] / "application" / "single_app" / "app.py"


@pytest.fixture
def cors_client():
    tree = ast.parse(APP_FILE.read_text(encoding="utf-8"))
    hook = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "add_security_headers")
    hook.decorator_list = []
    namespace = {"request": request}
    exec(compile(ast.Module(body=[hook], type_ignores=[]), str(APP_FILE), "exec"), namespace)
    app = Flask(__name__)
    app.after_request(namespace["add_security_headers"])
    app.add_url_rule("/api/chat_artifacts/download", view_func=lambda: Response(
        b"finding,source\nSole supplier,Supplier\n", content_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="findings.csv"'},
    ))
    with stubbed_config(
        SECURITY_HEADERS={}, ENABLE_STRICT_TRANSPORT_SECURITY=False, HSTS_MAX_AGE=31536000,
        V2_UI_ALLOWED_ORIGINS={TRUSTED_ORIGIN},
    ):
        yield app.test_client()


def test_allowed_split_origin_can_read_the_attachment_header(cors_client):
    response = cors_client.get("/api/chat_artifacts/download", headers={"Origin": TRUSTED_ORIGIN})
    assert response.status_code == 200
    assert response.headers["Access-Control-Allow-Origin"] == TRUSTED_ORIGIN
    assert response.headers["Access-Control-Allow-Credentials"] == "true"
    exposed = {header.strip().lower() for header in response.headers["Access-Control-Expose-Headers"].split(",")}
    assert "content-disposition" in exposed
    assert "Origin" in response.headers["Vary"]
    assert response.headers["Content-Disposition"].startswith("attachment;")


@pytest.mark.parametrize("origin", [None, "https://untrusted.example.test", TRUSTED_ORIGIN + ".untrusted.test"])
def test_other_origins_do_not_gain_credentialed_attachment_access(cors_client, origin):
    response = cors_client.get("/api/chat_artifacts/download", headers={"Origin": origin} if origin else {})
    assert "Access-Control-Allow-Origin" not in response.headers
    assert "Access-Control-Allow-Credentials" not in response.headers
    assert "Access-Control-Expose-Headers" not in response.headers

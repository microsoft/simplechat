#!/usr/bin/env python3
# test_ui_modern_url_variable.py
"""
Functional test for the ui=modern address variable and the Classic interface label.
Version: 0.261.479
Implemented in: 0.261.479

This test ensures that ``ui=modern`` on a classic address opens its V2 page the same way
``ui=classic`` keeps a page classic, that a classic-only policy ignores it, that the classic
"Switch to modern UI" link carries it, and that the interface is labeled Classic (not Legacy)
wherever a person chooses between the two.
"""

import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_ROOT = os.path.join(REPO_ROOT, "application", "single_app")
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, APP_ROOT)

import functions_ui_mode  # noqa: E402
import functions_ui_redirect as redirect_module  # noqa: E402


def read(*parts):
    with open(os.path.join(REPO_ROOT, *parts), encoding="utf-8") as handle:
        return handle.read()


def evaluate(**overrides):
    inputs = dict(
        method="GET",
        path="/chats",
        query_string="",
        accept="text/html",
        signed_in=True,
        has_app_role=True,
        ui_mode=functions_ui_mode.UI_MODE_CLASSIC,
        bundle_available=True,
    )
    inputs.update(overrides)
    return redirect_module.evaluate_ui_redirect(**inputs)


def test_ui_modern_opens_the_v2_page_for_a_classic_preference():
    assert evaluate().reason == redirect_module.REASON_CLASSIC_MODE
    decision = evaluate(query_string="conversationId=c1&ui=modern")
    assert decision.location == "/v2/chat?conversationId=c1&ui=modern"
    assert decision.reason == redirect_module.REASON_MODERN_REQUEST
    assert evaluate(path="/workspace", query_string="ui=modern").location == "/v2/workspace?ui=modern"


def test_ui_modern_does_not_bypass_the_other_rules():
    query = "ui=modern"
    assert evaluate(query_string=query, modern_request_allowed=False).reason == redirect_module.REASON_CLASSIC_MODE
    assert evaluate(query_string=query, signed_in=False).reason == redirect_module.REASON_SIGNED_OUT
    assert evaluate(query_string=query, has_app_role=False).reason == redirect_module.REASON_NO_APP_ROLE
    assert evaluate(query_string=query, bundle_available=False).reason == redirect_module.REASON_BUNDLE_MISSING
    assert evaluate(query_string=query, method="POST").location is None
    assert evaluate(query_string=query, path="/login").location is None
    # The first ui value decides, so a classic escape ahead of it still wins.
    assert evaluate(query_string="ui=classic&ui=modern").reason == redirect_module.REASON_ESCAPE_HATCH


def test_requested_ui_reads_the_first_value_only():
    requested = redirect_module.requested_ui
    assert requested("ui=modern") == "modern" and requested(b"a=1&ui=Modern") == "modern"
    assert requested("ui=classic&ui=modern") == "classic"
    for query in ("", None, "ui=", "UI=modern", "ui=modern2", "a=ui%3Dmodern", 5):
        assert requested(query) is None, query
    assert redirect_module.has_modern_request("?ui=modern") is True
    assert redirect_module.has_modern_request("ui=classic") is False
    assert redirect_module.has_classic_escape("ui=modern") is False


def test_with_modern_request_keeps_query_and_fragment():
    add = redirect_module.with_modern_request
    assert add("/v2") == "/v2?ui=modern"
    assert add("/v2/chat?conversationId=c1") == "/v2/chat?conversationId=c1&ui=modern"
    assert add("/v2/workspace#documents") == "/v2/workspace?ui=modern#documents"
    assert redirect_module._is_safe_location(add("/v2/chat?conversationId=c1"))


def test_policy_decides_which_variable_is_honoured():
    assert functions_ui_mode.allows_modern_request({"ui_mode_policy": "both"}) is True
    assert functions_ui_mode.allows_modern_request({"ui_mode_policy": "modern"}) is True
    assert functions_ui_mode.allows_modern_request({"ui_mode_policy": "classic"}) is False
    assert functions_ui_mode.allows_classic_escape({"ui_mode_policy": "classic"}) is True
    assert functions_ui_mode.allows_classic_escape({"ui_mode_policy": "modern"}) is False


def test_the_wrapper_honours_ui_modern_and_classic_only_policy():
    from flask import Flask
    from unittest.mock import patch

    import functions_ui_pages as pages

    app = Flask(__name__)
    app.secret_key = "test"
    policy = {"ui_mode_policy": "both", "ui_default_mode": "classic"}
    app.before_request(lambda: redirect_module.redirect_classic_page_to_modern_ui(lambda: policy))
    app.add_url_rule("/chats", "chats", lambda: "classic")
    client = app.test_client()
    with client.session_transaction() as state:
        state["user"] = {"oid": "alice", "roles": ["User"]}
    headers = {"Accept": "text/html"}
    with patch.object(pages, "_probe_v2_bundle", return_value=True), \
            patch.object(functions_ui_mode, "get_ui_mode", return_value="classic"):
        result = client.get("/chats", headers=headers)
        assert result.status_code == 200 and result.get_data(as_text=True) == "classic"
        result = client.get("/chats?conversationId=c1&ui=modern", headers=headers)
        assert result.status_code == 302 and result.location == "/v2/chat?conversationId=c1&ui=modern"
        assert result.headers["Cache-Control"] == "no-store"
        policy["ui_mode_policy"] = "classic"
        result = client.get("/chats?ui=modern", headers=headers)
        assert result.status_code == 200 and result.get_data(as_text=True) == "classic"


def test_the_classic_switch_link_and_landing_page_carry_ui_modern():
    switch = read("application", "single_app", "static", "js", "ui-switch.js")
    assert "target.searchParams.set('ui', 'modern');" in switch
    source = read("application", "single_app", "app.py")
    assert "modern_request = has_modern_request(request.query_string) and allows_modern_request(settings)" in source
    assert "return redirect(with_modern_request(V2_HOME_PATH))" in source


def test_the_interface_is_labeled_classic_not_legacy():
    fields = read("application", "single_app", "admin_settings_fields.py")
    for label in ('"Classic and modern"', '"Classic only"', '{"value": "classic", "label": "Classic"}'):
        assert label in fields, label
    for label in ('"Legacy and modern"', '"Legacy only"', '"label": "Legacy"}'):
        assert label not in fields, label
    pane = read("application", "single_app", "templates", "admin", "_panes", "branding.html")
    assert ">Classic and modern<" in pane and ">Classic only<" in pane and ">Classic<" in pane
    assert "Legacy" not in pane
    sidebar = read("application", "v2_ui", "src", "components", "layout", "Sidebar.tsx")
    assert "Switch to classic UI" in sidebar and "legacy" not in sidebar.lower()


if __name__ == "__main__":
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"PASS {test.__name__}")
        except Exception as error:
            failed += 1
            print(f"FAIL {test.__name__}: {error}")
            import traceback
            traceback.print_exc()
    sys.exit(1 if failed else 0)

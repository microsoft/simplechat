#!/usr/bin/env python3
# test_access_restricted_gate.py
"""
Functional test for the Access restricted sign-in screen and the access gate.
Version: 0.261.297
Implemented in: 0.261.297

This test ensures that a suspended or blocked user can still sign in but is sent to an
Access restricted screen by every app surface: API calls get a structured 403 with the
caller's own restriction, V2 pages redirect to /v2/access-restricted and classic pages to
/access-restricted. The restricted-page routes are login-only, describe only the caller's
own restriction, restore an expired suspension, keep the Admin bypass, allow access when
settings can't be read, are exempt from the Terms of Use gate, and render notice text as
text. Real modules run in fresh processes with network access blocked, under normal and
optimized Python.
"""

import ast
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "application" / "single_app"
sys.path.insert(0, str(APP_DIR))
sys.path.insert(0, str(ROOT / "functional_tests"))

from test_support.versioning import assert_app_version_at_least  # noqa: E402

RESTRICTED_PATHS = ("/access-restricted", "/v2/access-restricted", "/api/v2/access-restriction")


def _load_access_restriction_module():
    import functions_access_restriction

    return functions_access_restriction


def test_restriction_is_described_from_the_stored_access_setting():
    """Suspensions, blocks, expiry and notices are read the way the gate enforces them."""
    from datetime import datetime, timezone

    module = _load_access_restriction_module()
    now = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)

    assert module.describe_access_restriction(None, now) == ("allow", None)
    assert module.describe_access_restriction({"status": "allow"}, now) == ("allow", None)
    assert module.describe_access_restriction({"status": "unknown"}, now) == ("allow", None)
    assert module.describe_access_restriction(
        {"status": "deny", "datetime_to_allow": "2026-10-07T11:59:59Z"}, now,
    ) == ("expired", None)

    state, suspended = module.describe_access_restriction({
        "status": "deny",
        "datetime_to_allow": "2026-10-08T14:00:00.000Z",
        "notice": {
            "kind": "suspended",
            "title": "  Account Suspension Notice  ",
            "message": "Your access is suspended pending review.",
            "reference_id": "safety-log-1",
        },
    }, now)
    assert state == "restricted"
    assert suspended == {
        "kind": "suspended",
        "until": "2026-10-08T14:00:00+00:00",
        "title": "Account Suspension Notice",
        "message": "Your access is suspended pending review.",
        "reference_id": "safety-log-1",
    }

    # A restore time without an offset is read as UTC, as Control Center reads it.
    _state, naive = module.describe_access_restriction(
        {"status": "deny", "datetime_to_allow": "2026-10-08T14:00:00"}, now,
    )
    assert naive["kind"] == "suspended" and naive["until"] == "2026-10-08T14:00:00+00:00"

    # No notice: generic copy. An unreadable restore time stays in force as a block.
    for access in (
        {"status": "deny", "datetime_to_allow": None},
        {"status": "deny", "datetime_to_allow": "not a date"},
    ):
        state, blocked = module.describe_access_restriction(access, now)
        assert state == "restricted"
        assert blocked["kind"] == "blocked" and blocked["until"] is None
        assert blocked["title"] == "Your access has been blocked"
        assert blocked["reference_id"] is None

    # A notice written for another kind of restriction no longer describes it.
    _state, mismatched = module.describe_access_restriction({
        "status": "deny",
        "datetime_to_allow": None,
        "notice": {"kind": "suspended", "title": "Old suspension", "message": "Old", "reference_id": "x"},
    }, now)
    assert mismatched["title"] == "Your access has been blocked"
    assert mismatched["reference_id"] is None

    _state, long_notice = module.describe_access_restriction({
        "status": "deny",
        "notice": {"kind": "blocked", "title": "t" * 500, "message": "m" * 9000},
    }, now)
    assert len(long_notice["title"]) == module.NOTICE_TITLE_MAX_LENGTH
    assert len(long_notice["message"]) == module.NOTICE_MESSAGE_MAX_LENGTH


def test_legacy_reasons_fallback_and_page_paths():
    """check_user_access_status keeps its reasons; the gate picks the interface's page."""
    module = _load_access_restriction_module()
    timed = {"status": "deny", "datetime_to_allow": "2999-01-01T00:00:00Z"}
    _state, restriction = module.describe_access_restriction(timed)
    assert module.legacy_access_denied_reason(timed, restriction) == "Access denied until 2999-01-01T00:00:00Z"
    blocked = {"status": "deny", "datetime_to_allow": None}
    _state, restriction = module.describe_access_restriction(blocked)
    assert module.legacy_access_denied_reason(blocked, restriction) == "Access denied by administrator"

    fallback = module.fallback_access_restriction("Access denied until 2999-01-01T00:00:00Z")
    assert fallback["kind"] == "suspended" and fallback["until"] == "2999-01-01T00:00:00+00:00"
    assert module.fallback_access_restriction("Access denied by administrator")["kind"] == "blocked"
    assert module.fallback_access_restriction(None)["kind"] == "blocked"

    assert module.public_access_restriction({**fallback, "user_id": "someone", "notes": "x"}) == fallback

    for path in ("/v2", "/v2/chat", "/api/v2/bootstrap"):
        assert module.access_restricted_page_path(path) == "/v2/access-restricted", path
    for path in ("/chats", "/api/safety/logs/my", "/v2x"):
        assert module.access_restricted_page_path(path) == "/access-restricted", path

    notice = module.build_access_restriction_notice(
        "suspended", " Title ", "Message", until="2026-10-08T14:00:00Z", reference_id="log-1",
    )
    assert notice["kind"] == "suspended" and notice["title"] == "Title"
    assert notice["until"] == "2026-10-08T14:00:00Z" and notice["reference_id"] == "log-1"
    assert notice["source"] == "safety_violation" and notice["applied_at"]
    assert module.build_access_restriction_notice("blocked", "T", "M", until="ignored")["until"] is None
    with pytest.raises(ValueError):
        module.build_access_restriction_notice("escalated", "T", "M")


def _app_assignment(source, name):
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name for target in node.targets
        ):
            return ast.literal_eval(node.value)
    raise AssertionError(f"{name} not found")


def test_restricted_paths_skip_the_terms_gate_but_keep_idle_timeout():
    """A restricted user is never bounced between the two gates, and idle sessions still end."""
    app_source = (APP_DIR / "app.py").read_text(encoding="utf-8")
    terms_exempt = _app_assignment(app_source, "TERMS_OF_USE_EXEMPT_PATHS")
    idle_exempt = _app_assignment((APP_DIR / "config.py").read_text(encoding="utf-8"), "IDLE_TIMEOUT_EXEMPT_PATHS")
    for path in RESTRICTED_PATHS:
        assert path in terms_exempt, f"{path} must be exempt from the Terms of Use gate"
        assert path not in idle_exempt, f"{path} must keep idle-timeout enforcement"

    assert (
        "register_route_blueprint('access_restriction', register_route_access_restriction, "
        "login_required_blueprint)"
    ) in app_source


GATE_PROBE = r'''
import importlib
import json
import sys
import tempfile
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

root = Path(sys.argv[1])
sys.path.insert(0, str(root / "functional_tests"))
sys.path.insert(0, str(root / "application" / "single_app"))
from test_support.offline_bootstrap import offline_app_imports
from test_support.safety_review_harness import build_gate_app, check, sign_in, sign_out

future = (datetime.now(timezone.utc) + timedelta(days=2)).replace(microsecond=0)
past = datetime.now(timezone.utc) - timedelta(minutes=5)

with offline_app_imports(), ExitStack() as stack, tempfile.TemporaryDirectory() as scratch:
    importlib.import_module(sys.argv[2])
    import functions_authentication as auth

    shell = Path(scratch) / "index.html"
    shell.write_text("<!doctype html><html><head><title>x</title></head><body>V2-SHELL</body></html>", encoding="utf-8")
    gate = build_gate_app(stack, shell)
    client = gate.client
    adapter = gate.app.url_map.bind("localhost")

    # The static page rule wins over the /v2/<path:subpath> catch-all, whatever the order.
    check(adapter.match("/v2/access-restricted")[0] == "access_restriction.v2_access_restricted", "static rule lost")
    check(adapter.match("/v2/chat")[0] == "frontend_v2.v2_app_deep_link", "catch-all moved")

    gate.user_docs["user-1"] = {"id": "user-1", "settings": {"access": {
        "status": "deny", "datetime_to_allow": None,
        "notice": {"kind": "blocked", "title": "Account Access Blocked <script>alert(1)</script>",
                   "message": "Blocked for repeated violations.", "reference_id": "safety-log-1",
                   "source": "safety_violation"},
    }}}
    gate.user_docs["user-2"] = {"id": "user-2", "settings": {"access": {
        "status": "deny", "datetime_to_allow": None,
        "notice": {"kind": "blocked", "title": "Another user's notice", "message": "Private to user 2.",
                   "reference_id": "safety-log-2"},
    }}}
    sign_in(client, "user-1")

    response = client.get("/api/v2/bootstrap")
    body = response.get_json()
    check(response.status_code == 403, f"API call was not refused: {response.status_code}")
    check(body["error"] == "access_restricted", str(body))
    check(body["message"] == "Your access to this application has been blocked by an administrator.", str(body))
    check(body["restricted_url"] == "/v2/access-restricted", str(body))
    check(set(body["restriction"]) == {"kind", "until", "title", "message", "reference_id"}, str(body))
    check(body["restriction"]["reference_id"] == "safety-log-1", str(body))
    check("user 2" not in json.dumps(body), "Another user's notice leaked")

    response = client.get("/api/notifications/count")
    check(response.status_code == 403 and response.get_json()["restricted_url"] == "/access-restricted", "classic API")

    response = client.get("/v2/chat", headers={"Accept": "text/html"})
    check(response.status_code == 302, f"V2 page not redirected: {response.status_code}")
    check(response.headers["Location"].endswith("/v2/access-restricted"), response.headers["Location"])
    response = client.get("/chats", headers={"Accept": "text/html"})
    check(response.status_code == 302 and response.headers["Location"].endswith("/access-restricted"), "classic page")

    response = client.get("/v2/access-restricted", headers={"Accept": "text/html"})
    check(response.status_code == 200 and b"V2-SHELL" in response.data, "Restricted user cannot load the V2 page")

    for query in ("", "?user_id=user-2"):
        response = client.get(f"/api/v2/access-restriction{query}")
        body = response.get_json()
        check(response.status_code == 200, f"restriction route failed: {response.status_code}")
        check(response.headers.get("Cache-Control") == "no-store", "restriction route is cacheable")
        check(body["restricted"] is True and body["restriction"]["reference_id"] == "safety-log-1", str(body))
        check("user 2" not in json.dumps(body) and "safety-log-2" not in json.dumps(body), "Cross-user read")
        check(set(body["branding"]) >= {"app_title", "classification_banner"}, str(body))

    response = client.get("/access-restricted", headers={"Accept": "text/html"})
    html = response.get_data(as_text=True)
    check(response.status_code == 200 and response.headers.get("Cache-Control") == "no-store", "classic page")
    check("&lt;script&gt;alert(1)&lt;/script&gt;" in html and "<script>alert(1)" not in html, "Notice not escaped")
    check("Blocked for repeated violations." in html and "safety-log-1" in html, "Notice missing")
    check('href="/logout"' in html and "Sign out" in html, "Sign out link missing")
    check("No automatic restore date" in html, "Block not described")

    # A suspension shows its restore time; the page renders UTC and the script localizes it.
    gate.user_docs["user-1"]["settings"]["access"] = {
        "status": "deny", "datetime_to_allow": future.isoformat().replace("+00:00", "Z"),
        "notice": {"kind": "suspended", "title": "Account Suspension Notice", "message": "Suspended.",
                   "reference_id": "safety-log-9"},
    }
    body = client.get("/api/v2/access-restriction").get_json()
    check(body["restriction"]["kind"] == "suspended", str(body))
    check(body["restriction"]["until"] == future.isoformat(), str(body))
    body = client.get("/api/v2/bootstrap").get_json()
    check(body["message"] == "Your access to this application is temporarily suspended.", str(body))
    html = client.get("/access-restricted").get_data(as_text=True)
    check(f'datetime="{future.isoformat()}"' in html and future.strftime("%Y-%m-%d %H:%M UTC") in html, "restore time")
    check("js/access-restricted.js" in html, "local time script missing")

    allowed, reason = auth.check_user_access_status("user-1")
    check(not allowed and reason == f"Access denied until {future.isoformat().replace('+00:00', 'Z')}", reason)
    gate.user_docs["user-2"]["settings"]["access"]["datetime_to_allow"] = None
    check(auth.check_user_access_status("user-2") == (False, "Access denied by administrator"), "legacy block reason")

    # An expired suspension is restored on read, which clears its notice, and access returns.
    gate.user_docs["user-1"]["settings"]["access"] = {
        "status": "deny", "datetime_to_allow": past.isoformat(),
        "notice": {"kind": "suspended", "title": "Old", "message": "Old"},
    }
    body = client.get("/api/v2/access-restriction").get_json()
    check(body == {"restricted": False, "branding": body["branding"]}, str(body))
    check(gate.user_docs["user-1"]["settings"]["access"] == {"status": "allow", "datetime_to_allow": None}, "not restored")
    check(client.get("/api/v2/bootstrap").status_code == 200, "Restored user still refused")
    html = client.get("/access-restricted").get_data(as_text=True)
    check("Your access is available" in html and 'href="/"' in html, "No continue link")

    # Admins are never restricted, whatever their settings say.
    gate.user_docs["admin-1"] = {"id": "admin-1", "settings": {"access": {"status": "deny", "datetime_to_allow": None}}}
    sign_in(client, "admin-1", roles=("Admin",))
    check(client.get("/api/v2/bootstrap").status_code == 200, "Admin bypass lost")
    check(client.get("/api/v2/access-restriction").get_json()["restricted"] is False, "Admin reported restricted")

    # Unreadable settings allow access, as the access check always has.
    gate.user_docs["user-3"] = RuntimeError("settings store unavailable")
    sign_in(client, "user-3")
    check(client.get("/api/v2/bootstrap").status_code == 200, "A storage fault locked the user out")
    check(client.get("/api/v2/access-restriction").get_json()["restricted"] is False, "fault reported restricted")

    # When the check refuses but the details can't be read again, the reason still says
    # whether access returns on its own.
    with patch.object(auth, "check_user_access_status", lambda user_id: (False, "Access denied until 2999-01-01T00:00:00Z")):
        body = client.get("/api/v2/bootstrap").get_json()
        check(body["restriction"]["kind"] == "suspended", str(body))
        check(body["restriction"]["until"] == "2999-01-01T00:00:00+00:00", str(body))

    # Login-only: no session means sign in, never the user's restriction.
    sign_out(client)
    response = client.get("/api/v2/access-restriction")
    check(response.status_code == 401, f"anonymous read allowed: {response.status_code}")
    response = client.get("/v2/access-restricted", headers={"Accept": "text/html"})
    check(response.status_code == 302 and response.headers["Location"].endswith("/login"), "anonymous page")

print("PASS: access gate and Access restricted screen")
'''


@pytest.mark.parametrize("first_import", ["functions_authentication", "route_access_restriction"])
@pytest.mark.parametrize("optimized", [False, True])
def test_real_access_gate_and_restricted_routes(first_import, optimized):
    command = [sys.executable, "-B"]
    if optimized:
        command.append("-O")
    result = subprocess.run(
        command + ["-c", GATE_PROBE, str(ROOT), first_import],
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS: access gate and Access restricted screen" in result.stdout


def test_v2_access_restricted_page_is_wired():
    """The SPA renders the page outside the bootstrap gate and follows the server's gate."""
    v2 = ROOT / "application" / "v2_ui" / "src"
    app_tsx = (v2 / "App.tsx").read_text(encoding="utf-8")
    assert "location.pathname === '/access-restricted'" in app_tsx
    assert "return <AccessRestrictedPage />;" in app_tsx
    api_client = (v2 / "lib" / "apiClient.ts").read_text(encoding="utf-8")
    assert "export function isAccessRestricted(" in api_client
    assert "'access_restricted'" in api_client
    assert "export const V2_ACCESS_RESTRICTED_PATH = '/v2/access-restricted';" in api_client
    bootstrap_store = (v2 / "stores" / "bootstrapStore.ts").read_text(encoding="utf-8")
    assert "isAccessRestricted(error.status, error.payload)" in bootstrap_store
    page = (v2 / "pages" / "AccessRestrictedPage.tsx").read_text(encoding="utf-8")
    assert "dangerouslySetInnerHTML" not in page
    assert "fetchAccessRestriction" in page and "apiUrl('/logout')" in page


def test_version():
    assert_app_version_at_least("0.261.297")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))

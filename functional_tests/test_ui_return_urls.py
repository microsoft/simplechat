#!/usr/bin/env python3
# test_ui_return_urls.py
"""
Functional test for the addresses the server builds to send a person back into the application.
Version: 0.261.445
Implemented in: 0.261.445

The server writes some classic addresses itself: the Microsoft 365 sign-in return URLs, the page it lands a
chat sign-in on, the Teams success path, the landing page after login, and the Terms of Use return path.
When the modern interface is selected, ``functions_ui_redirect`` sends every one of them to V2, so none
needs a helper that builds a V2 address. This test pins the evidence for that decision:

- every Microsoft 365 return URL in ``route_backend_m365.py`` is a classic address the redirect covers, and
  the two that name a settings card end on a fragment V2 itself rewrites after the redirect;
- the chat sign-in return carries three query keys, V2 reads none of the two that classic reads (V2 signs in
  from a popup and resumes the paused request in the page), and the redirect drops them rather than
  carrying values nobody reads;
- the Teams session carries no application role, so the redirect never applies to a Teams tab;
- the landing page after login and the Terms of Use return path are covered by the redirect and the landing
  page's own redirect.

If a new return URL is added, or V2 starts reading one of these keys from the address, a test here fails
and says what to do.
"""

import ast
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"
V2_SRC = REPO_ROOT / "application" / "v2_ui" / "src"
sys.path.insert(0, str(APP_ROOT))
sys.path.append(str(Path(__file__).resolve().parent))

import functions_ui_mode  # noqa: E402
import functions_ui_pages  # noqa: E402
import functions_ui_redirect as redirect_module  # noqa: E402
import ui_routing  # noqa: E402
from test_support.versioning import assert_app_version_at_least  # noqa: E402
from test_ui_route_parity_registry import app_declared_routes, declared_covering  # noqa: E402


M365_ROUTES = APP_ROOT / "route_backend_m365.py"
AUTHENTICATION_ROUTES = APP_ROOT / "route_frontend_authentication.py"
CONFIG = APP_ROOT / "config.py"

# name -> (what the server's redirect leaves in the address, what V2 makes of the fragment afterwards)
EXPECTED_M365_RETURN_URLS = {
    "CLASSIC_CHAT_CONNECTION_URL": ("/v2/settings?tab=preferences", "/v2/settings?tab=preferences&section=m365-chat-connection"),
    "CLASSIC_CHAT_CONNECTED_URL": ("/v2/settings?tab=preferences", "/v2/settings?tab=preferences&section=m365-chat-connection"),
    "CLASSIC_WORKFLOW_CONNECTION_URL": ("/v2/settings?tab=preferences", "/v2/settings?tab=preferences&section=m365-workflow-connection"),
    "CLASSIC_WORKFLOW_CONNECTED_URL": ("/v2/settings?tab=preferences", "/v2/settings?tab=preferences&section=m365-workflow-connection"),
    "CLASSIC_CHATS_URL": ("/v2/chat", "/v2/chat"),
}
# Classic-only flags of the full-page sign-in return. V2 signs in from a popup and reads the connection
# from its API, so it reads none of them from the address.
CLASSIC_ONLY_RETURN_KEYS = ("m365_request_id", "m365_auth", "m365_chat_connection", "m365_connection")


def read(path):
    assert path.is_file(), f"Missing expected file: {path}"
    return path.read_text(encoding="utf-8")


def module_constants(path, prefix):
    tree = ast.parse(read(path))
    found = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if name.startswith(prefix):
                found[name] = ast.literal_eval(node.value)
    return found


def modern_decision(path, query_string="", **overrides):
    inputs = dict(
        method="GET", path=path, query_string=query_string, accept="text/html,*/*;q=0.8", xhr=False,
        fetch_dest="document", fetch_mode="navigate", signed_in=True, has_app_role=True,
        ui_mode=functions_ui_mode.UI_MODE_MODERN, bundle_available=True,
        custom_page_embeddable=lambda slug: True,
    )
    inputs.update(overrides)
    return redirect_module.evaluate_ui_redirect(**inputs)


def test_version_is_at_least_the_implementing_release():
    assert_app_version_at_least("0.261.445")


# ---------------------------------------------------------------------------
# Microsoft 365
# ---------------------------------------------------------------------------

def test_every_microsoft_365_return_url_is_known_and_covered_by_the_redirect():
    constants = module_constants(M365_ROUTES, "CLASSIC_")
    assert set(constants) == set(EXPECTED_M365_RETURN_URLS), (
        "A Microsoft 365 return URL was added or removed. Decide whether the redirect covers it (it does for "
        "any classic page in ui_route_map.json) and add it to EXPECTED_M365_RETURN_URLS with the address V2 ends on."
    )
    declared = app_declared_routes()
    for name, url in constants.items():
        parts = urlsplit(url)
        on_server, after_fragment = EXPECTED_M365_RETURN_URLS[name]

        decision = modern_decision(parts.path, parts.query)
        assert decision.location == on_server, f"{name}: {url} -> {decision}"

        # The server never sees the fragment; V2 rewrites it, and it names a route V2 declares.
        with_fragment = ui_routing.resolve_v2_target(parts.path, parts.query, parts.fragment)
        assert with_fragment is not None and with_fragment["path"] == after_fragment, f"{name}: {with_fragment}"
        assert declared_covering(urlsplit(after_fragment).path[len("/v2"):] or "/", declared)

        classic = modern_decision(parts.path, parts.query, ui_mode=functions_ui_mode.UI_MODE_CLASSIC)
        assert classic.location is None, f"{name} must stay classic in the classic interface."


def test_the_fragments_that_name_a_settings_card_are_rewritten_by_the_registry():
    """`#m365-chat-connection` and `#m365-connection-status` mean something only on the settings page."""
    profile = next(row for row in ui_routing.load_ui_route_map().routes if row.key == "profile")
    assert {"m365-chat-connection", "m365-connection-status"} <= set(profile.hash_map)


def test_the_chat_sign_in_return_keeps_the_conversation_and_drops_what_v2_does_not_read():
    """The page flow returns to /chats with the conversation and two classic-only flags."""
    source = read(M365_ROUTES)
    tree = ast.parse(source)
    function = next(
        node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "_complete_chat_connection"
    )
    keys = sorted({
        key.value for node in ast.walk(function) if isinstance(node, ast.Dict)
        for key in node.keys if isinstance(key, ast.Constant) and isinstance(key.value, str)
    })
    assert keys == ["conversationId", "m365_auth", "m365_request_id"], keys
    assert 'redirect(f"/chats?{query}")' in source

    decision = modern_decision("/chats", "conversationId=conv-1&m365_request_id=r-1&m365_auth=connected")
    assert decision.location == "/v2/chat?conversationId=conv-1", (
        "The conversation survives and the flags V2 never reads are dropped."
    )


def test_v2_reads_none_of_the_full_page_sign_in_flags_from_the_address():
    """If V2 starts to read one, add it to the `query_map` of the `chat` or `profile` row so the redirect
    carries it, and move it out of CLASSIC_ONLY_RETURN_KEYS."""
    reading = re.compile(
        r"(?:searchParams|URLSearchParams\([^)]*\)|query|params)\s*\.\s*(?:get|has|getAll)\(\s*['\"]("
        + "|".join(CLASSIC_ONLY_RETURN_KEYS) + r")['\"]"
    )
    offenders = []
    for path in sorted(V2_SRC.rglob("*.ts*")):
        if "generated" in path.parts:
            continue
        for match in reading.finditer(path.read_text(encoding="utf-8")):
            offenders.append(f"{path.relative_to(V2_SRC)}: {match.group(0)}")
    assert not offenders, "V2 reads a classic-only sign-in flag from the address:\n  " + "\n  ".join(offenders)

    mapped = {
        key for row in ui_routing.load_ui_route_map().routes for key in (row.query_map or {})
    }
    assert not mapped & set(CLASSIC_ONLY_RETURN_KEYS), (
        "The registry carries a flag V2 does not read: " + ", ".join(sorted(mapped & set(CLASSIC_ONLY_RETURN_KEYS)))
    )


# ---------------------------------------------------------------------------
# Teams, login and Terms of Use
# ---------------------------------------------------------------------------

def test_the_teams_success_path_resolves_and_a_teams_session_has_no_application_role():
    default = re.search(r'TEAMS_SUCCESS_REDIRECT_PATH\s*=\s*os\.getenv\("TEAMS_SUCCESS_REDIRECT_PATH",\s*"([^"]+)"\)', read(CONFIG))
    assert default and default.group(1) == "/chats"
    assert modern_decision(default.group(1)).location == "/v2/chat"

    # The Teams session user is built from claims and carries no `roles`, so it is not an application user
    # as far as the redirect is concerned (user_required refuses it for the same reason).
    tree = ast.parse(read(AUTHENTICATION_ROUTES))
    builder = next(
        node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "_build_teams_session_user"
    )
    keys = {
        key.value for node in ast.walk(builder) if isinstance(node, ast.Dict)
        for key in node.keys if isinstance(key, ast.Constant)
    }
    assert "roles" not in keys, (
        "A Teams session now carries roles, so the classic to V2 redirect would apply to Teams tabs. Check that the "
        "Teams tab host can show /v2 pages, then update docs/explanation/features/V2_INTERFACE_SELECTION_PREREQUISITES.md."
    )
    assert functions_ui_pages.has_app_user_role({"name": "Riley", "oid": "o", "tid": "t"}) is False


def test_the_landing_page_after_login_is_covered_by_the_redirect_and_the_landing_page_itself():
    source = read(AUTHENTICATION_ROUTES)
    assert source.count("redirect(url_for('public_app.index'))") >= 2, "The login flows return to the landing page."

    # Signed in with a role, in the modern interface: the landing page is V2.
    assert modern_decision("/").location == "/v2"
    # Not signed in, or signed in without a role: the landing page stays the server-rendered one.
    assert modern_decision("/", signed_in=False).location is None
    assert modern_decision("/", has_app_role=False).location is None
    assert modern_decision("/", ui_mode=functions_ui_mode.UI_MODE_CLASSIC).location is None


def test_the_terms_of_use_return_path_survives_the_redirect_as_a_same_site_path_only():
    decision = modern_decision("/terms-of-use", "next=%2Fchats%3FconversationId%3Dabc")
    assert decision.location == "/v2/terms-of-use?next=%2Fchats%3FconversationId%3Dabc"
    for hostile in ("//evil.example", "https://evil.example", "/\\evil.example", "chats"):
        dropped = modern_decision("/terms-of-use", "next=" + hostile.replace("/", "%2F").replace("\\", "%5C").replace(":", "%3A"))
        assert dropped.location == "/v2/terms-of-use", f"{hostile!r} must not be carried: {dropped}"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))

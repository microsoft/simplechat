#!/usr/bin/env python3
# test_v2_user_settings_memory_m365.py
"""
Functional test for V2 User Settings fact memory and Microsoft 365 parity.
Version: 0.261.302
Implemented in: 0.261.279
Authorization URL validation updated in: 0.261.281
Popup workflow connect and V2-only links updated in: 0.261.302

V2 Preferences now carries the classic profile page's Fact Memory section, as a workbench
for adding, searching, editing and deleting memories, and its Microsoft 365 sharing and
workflows section: sharing preferences, per-source revocation, chat reconnect, the workflow
connection and workflow authorizations. This file pins the routes, the CSRF contract and the
confirmation gates those cards depend on.
"""

import ast
import re
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))

from test_support.versioning import assert_app_version_at_least


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = REPO_ROOT / "application" / "single_app"
V2_SRC = REPO_ROOT / "application" / "v2_ui" / "src"
SETTINGS_DIR = V2_SRC / "components" / "settings"
PREFERENCES_TSX = SETTINGS_DIR / "PreferencesTab.tsx"
FACT_MEMORY_TSX = SETTINGS_DIR / "FactMemoryBench.tsx"
M365_CARDS_TSX = SETTINGS_DIR / "M365Cards.tsx"
M365_CONNECT_TS = V2_SRC / "lib" / "m365Connect.ts"
PROFILE_ROUTE = APP_DIR / "route_frontend_profile.py"
M365_ROUTE = APP_DIR / "route_backend_m365.py"


def _read(path):
    assert path.is_file(), f"Missing expected file: {path}"
    return path.read_text(encoding="utf-8")


def _route_functions(path):
    """Map each route decorator path+method to whether its body validates the M365 CSRF token."""
    tree = ast.parse(_read(path))
    routes = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        for decorator in node.decorator_list:
            if not (isinstance(decorator, ast.Call) and getattr(decorator.func, "attr", "") == "route"):
                continue
            route_path = decorator.args[0].value if decorator.args else ""
            methods = ["GET"]
            for keyword in decorator.keywords:
                if keyword.arg == "methods":
                    methods = [element.value for element in keyword.value.elts]
            body_source = ast.unparse(node)
            for method in methods:
                routes[(route_path, method)] = "validate_m365_csrf()" in body_source
    return routes


def test_version_is_at_least_the_implementation():
    assert_app_version_at_least("0.261.281")


def test_preferences_groups_memory_and_connected_accounts():
    source = _read(PREFERENCES_TSX)
    assert 'id="memory-data"' in source
    assert 'label="Memory and data"' in source
    assert 'id="connected-accounts"' in source
    assert "<FactMemoryBench />" in source
    assert "<M365Cards />" in source
    # Retention moved into Memory and data and is still gated by its admin flag.
    assert "enabled('enable_retention_policy_personal') && <RetentionCard" in source
    assert 'id="data-privacy"' not in source
    # Fact memory is shown even when the capability is off, as on the classic page.
    memory_group = source.split('id="memory-data"', 1)[1].split("</SettingsGroup>", 1)[0]
    assert "enabled('enable_fact_memory_plugin')" not in memory_group


def test_fact_memory_bench_uses_the_profile_routes():
    source = _read(FACT_MEMORY_TSX)
    assert "api.get<FactMemoryPayload>('/api/profile/fact-memory'" in source
    assert "api.post<{ fact?: FactMemoryItem }>('/api/profile/fact-memory'" in source
    assert "api.put<{ fact?: FactMemoryItem }>(" in source
    assert "api.delete(`/api/profile/fact-memory/${encodeURIComponent(selected.id)}`)" in source
    assert "memory_type: newType" in source
    assert "memory_type: draftType" in source
    # Classic wording for the two kinds of memory, and the admin badge.
    assert "Instruction: always apply to future responses" in source
    assert "Fact: recall only when relevant" in source
    assert "Enabled by admin" in source and "Disabled by admin" in source


def test_fact_memory_bench_has_search_filter_and_confirmed_delete():
    source = _read(FACT_MEMORY_TSX)
    assert 'type="search"' in source
    assert '<option value="all">All types</option>' in source
    assert "<ConfirmDialog" in source
    # Delete only runs from the dialog, never directly from the button.
    assert "onClick={() => setConfirmDelete(true)}" in source
    assert "onConfirm={() => void remove()}" in source


def test_fact_memory_routes_match_the_bench():
    source = _read(PROFILE_ROUTE)
    for route, method in (
        ("'/api/profile/fact-memory'", "GET"),
        ("'/api/profile/fact-memory'", "POST"),
        ("'/api/profile/fact-memory/<fact_id>'", "PUT"),
        ("'/api/profile/fact-memory/<fact_id>'", "DELETE"),
    ):
        assert f"@bp.route({route}, methods=['{method}'])" in source
    assert "'enabled': bool(settings.get('enable_fact_memory_plugin', False))" in source


def test_every_m365_write_the_cards_call_validates_csrf():
    routes = _route_functions(M365_ROUTE)
    writes = [
        ("/api/m365/preferences", "PATCH"),
        ("/api/m365/sources/<source>/revoke", "POST"),
        ("/api/m365/chat/connection/connect", "POST"),
        ("/api/m365/connections/connect", "POST"),
        ("/api/m365/connections/disconnect", "POST"),
        ("/api/m365/bindings/<binding_id>/revoke", "POST"),
    ]
    for key in writes:
        assert key in routes, f"Missing M365 route {key}"
        assert routes[key], f"{key} no longer validates the M365 CSRF token"
    for key in (
        ("/api/m365/preferences", "GET"),
        ("/api/m365/chat/connection", "GET"),
        ("/api/m365/connections", "GET"),
        ("/api/m365/bindings", "GET"),
    ):
        assert key in routes, f"Missing M365 route {key}"


def test_m365_cards_send_and_refresh_the_csrf_token():
    source = _read(M365_CARDS_TSX)
    assert "'X-M365-CSRF-Token': csrfToken" in source
    assert "error.status === 403 && code === 'm365_csrf_invalid'" in source
    assert "m365Request<T>(path, options, true)" in source
    for path in (
        "'/api/m365/preferences'",
        "'/api/m365/chat/connection'",
        "'/api/m365/connections'",
        "'/api/m365/connections/disconnect'",
        "`/api/m365/sources/${encodeURIComponent(source)}/revoke`",
        "`/api/m365/bindings/${encodeURIComponent(binding.id)}/revoke`",
        "`/api/m365/bindings?${query}`",
    ):
        assert path in source, f"M365 cards no longer call {path}"
    # Connecting runs in the shared popup helper, which sends the token it just read.
    connect_source = _read(M365_CONNECT_TS)
    for path in ("'/api/m365/chat/connection/connect'", "'/api/m365/connections/connect'"):
        assert path in connect_source, f"The connect helper no longer calls {path}"
    assert connect_source.count("headers: { 'X-M365-CSRF-Token': requireCsrf(current.csrf_token) }") == 2


def test_m365_cards_mirror_classic_choices():
    source = _read(M365_CARDS_TSX)
    for label in (
        "Ask before sharing",
        "Prefer this request only",
        "Prefer today",
        "Prefer always, until revoked",
        "Ask before deeper analysis",
        "Always allow deeper analysis within service limits",
        "Use a faster answer with coverage limitations",
    ):
        assert label in source, f"Missing classic M365 choice: {label}"
    assert "const ANALYSIS_SOURCES: readonly AnalysisSource[] = ['onedrive', 'spo'];" in source
    assert "Intl.DateTimeFormat().resolvedOptions().timeZone" in source


def test_m365_revocations_are_confirmed_and_redirects_validated():
    source = _read(M365_CARDS_TSX)
    # Every write except saving preferences and starting a connection is a revocation that
    # goes through the shared confirmation dialog.
    for path in ("/revoke`", "'/api/m365/connections/disconnect'"):
        for match in re.finditer(re.escape(path), source):
            preceding = source[max(0, match.start() - 900):match.start()]
            assert "onRevoke({" in preceding, f"{path} is not behind the confirmation dialog"
    assert "<ConfirmDialog" in source
    assert "Answers and evidence already published to conversations are not removed." in source
    # Workflow and chat connect run in a popup that reports back, so V2 never navigates to the
    # sign-in or lands on a classic page; the popup goes only to a validated HTTPS sign-in URL.
    assert "window.location.assign" not in source
    assert "await connectMicrosoft365Workflow(selected)" in source
    assert "await connectMicrosoft365(selected)" in source
    connect_source = _read(M365_CONNECT_TS)
    assert "export function normalizeAuthorizationUrl(value: unknown): string" in connect_source
    assert "target.protocol !== 'https:'" in connect_source
    assert "popup.location.replace(normalizeAuthorizationUrl(authorizationUrl))" in connect_source
    assert connect_source.count("body: { sources, completion: 'popup' }") == 2
    # Failures reported by the result page reach the user; the opener checks source and origin.
    assert "data.type === CONNECT_FAILED_TYPE && data.kind === signIn.kind" in connect_source
    assert "event.source !== popup" in connect_source


def test_m365_links_stay_in_v2():
    """Settings and approvals links are V2 routes, never classic Profile or Approvals pages."""
    for path in (
        M365_CARDS_TSX,
        V2_SRC / "components" / "chat" / "OrchestrationM365Notice.tsx",
        V2_SRC / "components" / "chat" / "WorkflowProposalCard.tsx",
        V2_SRC / "components" / "chat" / "WorkflowRunCard.tsx",
        V2_SRC / "components" / "approvals" / "PendingActionsPanel.tsx",
        V2_SRC / "components" / "approvals" / "PendingActionCard.tsx",
        V2_SRC / "components" / "approvals" / "PausedRequestsPanel.tsx",
        V2_SRC / "components" / "chat" / "PendingActionSlots.tsx",
        V2_SRC / "stores" / "m365PendingActionsStore.ts",
        V2_SRC / "lib" / "m365PendingActions.ts",
    ):
        source = _read(path)
        assert not re.search(r"['\"`]/profile", source), f"{path.name} links to the classic Profile page"
        assert not re.search(r"['\"`]/approvals['\"`]", source), f"{path.name} links to the classic Approvals page"
        assert "M365_PROFILE_CONNECTION_HREF" not in source, f"{path.name} uses the removed classic link"
        assert not re.search(r"href=\{M365_[A-Z_]+_HREF\}", source), f"{path.name} renders a V2 route as a bare anchor"
    settings_page = _read(V2_SRC / "pages" / "SettingsPage.tsx")
    assert "searchParams.get('section')" in settings_page
    assert "jumpToSection(requestedSection)" in settings_page


if __name__ == "__main__":
    tests = [
        test_version_is_at_least_the_implementation,
        test_preferences_groups_memory_and_connected_accounts,
        test_fact_memory_bench_uses_the_profile_routes,
        test_fact_memory_bench_has_search_filter_and_confirmed_delete,
        test_fact_memory_routes_match_the_bench,
        test_every_m365_write_the_cards_call_validates_csrf,
        test_m365_cards_send_and_refresh_the_csrf_token,
        test_m365_cards_mirror_classic_choices,
        test_m365_revocations_are_confirmed_and_redirects_validated,
        test_m365_links_stay_in_v2,
    ]
    failures = 0
    for test in tests:
        try:
            test()
            print(f"PASS {test.__name__}")
        except AssertionError as error:
            failures += 1
            print(f"FAIL {test.__name__}: {error}")
    print(f"{len(tests) - failures}/{len(tests)} passed")
    sys.exit(1 if failures else 0)

#!/usr/bin/env python3
# test_v2_classic_links.py
"""
Functional test for the V2 side of the classic to V2 redirect.
Version: 0.261.445
Implemented in: 0.261.445

The server redirects a classic URL to V2, and V2 has two jobs of its own: a browser keeps a URL fragment
across a redirect, so ``/workspace#documents-tab`` arrives as ``/v2/workspace#documents-tab`` and V2 must
turn the fragment into the route it names; and "Back to classic UI" must open the classic version of the
page on screen, not only the classic chat page.

``lib/classicLinks.ts`` is the TypeScript twin of ``resolve_classic_target`` and of the fragment half of
``resolve_v2_target`` in ``ui_routing.py``. This test ensures that:

- the twin gives the very answers the server's resolver gives, for every row of the registry, for the V2
  subroutes, query values and fragments each row declares, and for hostile addresses (run under node, with
  the cases produced here from the real ``ui_route_map.json``);
- the classic address "Open this page in classic" builds leads back, through the redirect, to the V2 page it
  came from, and always carries ``ui=classic``;
- the fragment translation replaces the address once, never loops, reads own keys only and ignores any
  fragment the registry does not list;
- the pieces are wired: the app mounts the translation once, the boot error and the missing-bundle page link
  to the classic page with the escape pair, and the account menu's link comes from ``classicBackHref``.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlencode, urlsplit

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"
V2_DIR = REPO_ROOT / "application" / "v2_ui"
V2_SRC = V2_DIR / "src"
LOGIC_CHECK_TS = Path(__file__).resolve().parent / "test_v2_classic_links_logic.ts"
sys.path.insert(0, str(APP_ROOT))
sys.path.append(str(Path(__file__).resolve().parent))

import functions_ui_redirect  # noqa: E402
import ui_routing  # noqa: E402
from test_support.versioning import assert_app_version_at_least  # noqa: E402


SAMPLE = "abc-123"
V2_PARAM_RE = re.compile(r":([A-Za-z_][A-Za-z0-9_]*)")
CLASSIC_TOKEN_RE = re.compile(r"<(?:[a-z_]+:)?(?P<name>[A-Za-z_][A-Za-z0-9_]*)>")

# Addresses a person, a script or an attacker could put in front of V2.
HOSTILE_V2_ADDRESSES = [
    ("//evil.example/settings", ""), ("/\\evil.example", ""), ("/%2e%2e/settings", ""), ("/settings/..", ""),
    ("/settings/./", ""), ("/settings//", ""), ("//settings", ""), ("/settings%2f..", ""),
    ("/groups/a%2fb", ""), ("/groups/a%5cb", ""), ("/groups/%00", ""), ("/groups/a b", ""),
    ("/groups/\u00e9", ""), ("/groups/%C3%A9", ""), ("/groups/" + "a" * 257, ""), ("/" + "a" * 2100, ""),
    ("/settings\n", ""), ("/settings\u0000", ""), ("/settings?x", ""), ("/settings#x", ""), ("", ""),
    ("settings", ""), ("/v2", ""), ("/v2/", ""), ("/v2/v2/settings", ""), ("/v2settings", ""),
    ("/chat/", ""), ("/CHAT", ""), ("/Chat", ""), ("/groups/directory", ""), ("/groups/create", ""),
    ("/groups/.", ""), ("/groups/..", ""), ("/groups/%2e", ""), ("/groups/abc%20def", ""),
    ("/groups/abc%2", ""), ("/groups/abc%zz", ""), ("/custom/..", ""), ("/custom/a%2fb", ""),
    ("/public/directory", ""), ("/public/abc/members", ""), ("/no/such/page", ""), ("/dev/alert-lab", ""),
    ("/settings", "?" + "a=1&" * 80), ("/settings", "?tab=" + "x" * 5000),
    ("/settings", "?tab=feedback&tab=violations"), ("/settings", "?tab=__proto__"),
    ("/settings", "?tab=constructor"), ("/settings", "?__proto__=x&constructor=y"),
    ("/settings", "?tab=%ff%fe"), ("/settings", "?tab=feedback&section=%00"),
    ("/chat", "?conversationId=%ff%fe"), ("/chat", "?conversationId=a+b"),
    ("/chat", "?conversationId=%2e%2e%2f"), ("/chat", "?conversationId=a%00b"),
    ("/chat", "?conversationId=" + "x" * 1025), ("/chat", "?conversationId"), ("/chat", "?=x&&=&"),
    ("/terms-of-use", "?next=%2F%2Fevil.example"), ("/terms-of-use", "?next=https%3A%2F%2Fevil.example"),
    ("/terms-of-use", "?next=%2F%5Cevil.example"), ("/terms-of-use", "?next=%2Fchats%3FconversationId%3Dabc"),
]

HOSTILE_FRAGMENTS = [
    "nope", "constructor", "__proto__", "toString", "documents-tab%00", "documents-tab%0a", "%E0%A4%A", "%",
    "a" * 300, "documents-tab/../x", "DOCUMENTS-TAB", "documents-tab ", " documents-tab", "javascript:alert(1)",
    "<script>alert(1)</script>", "//evil.example", "\\\\evil.example", "documents-tab#documents-tab",
]


def registry_rows():
    return json.loads(ui_routing.UI_ROUTE_MAP_PATH.read_text(encoding="utf-8"))["routes"]


def fill_v2(pattern):
    return V2_PARAM_RE.sub(SAMPLE, pattern)


def fill_classic(rule):
    return CLASSIC_TOKEN_RE.sub(SAMPLE, rule)


def read(path):
    assert path.is_file(), f"Missing expected file: {path}"
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# The cases, produced from the real registry by the server's own resolver
# ---------------------------------------------------------------------------

def build_reverse_cases():
    cases = []

    def add(label, pathname, search="", fragment=""):
        cases.append({
            "label": label,
            "pathname": pathname,
            "search": search,
            "hash": fragment,
            "expected": ui_routing.resolve_classic_target(pathname, search, fragment),
        })

    for row in registry_rows():
        if not row.get("v2"):
            continue
        key = row["key"]
        base = fill_v2(row["v2"])
        prefix = "" if base == "/" else base
        for pattern in [row["v2"], *row.get("v2_subroutes", [])]:
            path = fill_v2(pattern)
            add(f"{key} {pattern}", path)
            add(f"{key} {pattern} under /v2", "/v2" + ("" if path == "/" else path))
            if path != "/":
                add(f"{key} {pattern} with a trailing slash", path + "/")
            add(f"{key} {pattern} with keys the row does not map", path, "?zzz=1&utm_source=mail")
            add(f"{key} {pattern} with the escape pair", path, "?ui=classic")
            add(f"{key} {pattern} with a fragment", path, "", "#documents-tab")
        for reserved_param, names in (row.get("v2_reserved") or {}).items():
            for name in names:
                path = V2_PARAM_RE.sub(lambda match: name if match.group(1) == reserved_param else SAMPLE, row["v2"])
                add(f"{key} reserved {reserved_param}={name}", path)
        for classic_key, spec in (row.get("query_map") or {}).items():
            rule = {"to": spec} if isinstance(spec, str) else spec
            if "path" in rule:
                for suffix in rule["path"].values():
                    add(f"{key} {classic_key} suffix {suffix}", prefix + suffix)
                continue
            v2_key = rule["to"]
            values = list(rule["values"].values()) if "values" in rule else [SAMPLE]
            for value in values:
                add(f"{key} {v2_key}={value}", base, "?" + urlencode({v2_key: value}))
            add(f"{key} {v2_key} with a value the row does not list", base, "?" + urlencode({v2_key: "zz-not-a-value"}))
            add(f"{key} {v2_key} twice", base, f"?{v2_key}=first&{v2_key}=second")
            add(f"{key} {v2_key} empty", base, f"?{v2_key}=")
            add(f"{key} {v2_key} with a control character", base, f"?{v2_key}=a%0Ab")
            add(f"{key} {v2_key} with spaces and symbols", base, "?" + urlencode({v2_key: "a b&c=d/\u00e9+!'()*"}))
            add(f"{key} {v2_key} overlong", base, "?" + urlencode({v2_key: "x" * 2000}))
            if rule.get("local_path"):
                for value in ("/chats", "//evil.example", "https://evil.example", "/\\evil.example", "/%5Cevil", "chats"):
                    add(f"{key} {v2_key}={value}", base, "?" + urlencode({v2_key: value}))
        for fragment_name, rule in (row.get("hash_map") or {}).items():
            if "path" in rule:
                add(f"{key} #{fragment_name} as a route", prefix + rule["path"])
            if "query" in rule:
                add(f"{key} #{fragment_name} as query values", base, "?" + urlencode(rule["query"]))
                add(f"{key} #{fragment_name} with only some of its query values", base,
                    "?" + urlencode(dict(list(rule["query"].items())[:1])))

    for pathname, search in HOSTILE_V2_ADDRESSES:
        add(f"hostile {pathname[:40]!r} {search[:30]!r}", pathname, search)
    return cases


def forward_search(router_path):
    parts = urlsplit(router_path)
    return parts.path, (f"?{parts.query}" if parts.query else "")


def build_forward_cases():
    cases = []

    def add(label, classic_path, classic_query, fragment, shown=None):
        # What the browser leaves in the address bar, exactly as `location.hash` reads it.
        hash_text = shown if shown is not None else f"#{fragment}"
        arrival = ui_routing.resolve_v2_target(classic_path, classic_query)
        whole = ui_routing.resolve_v2_target(classic_path, classic_query, hash_text)
        if arrival is None or whole is None:
            return
        pathname, search = forward_search(arrival["router_path"])
        cases.append({
            "label": label,
            "pathname": pathname,
            "search": search,
            "hash": hash_text,
            "arrival": arrival["router_path"],
            "expected": whole["router_path"],
        })

    for row in registry_rows():
        if not row.get("hash_map") or not row.get("v2"):
            continue
        classic_path = fill_classic(row["classic"])
        queries = [""]
        for classic_key, spec in (row.get("query_map") or {}).items():
            rule = {"to": spec} if isinstance(spec, str) else spec
            if "path" in rule:
                queries += [f"{classic_key}={value}" for value in rule["path"]]
            elif "values" in rule:
                queries += [f"{classic_key}={value}" for value in rule["values"]]
            else:
                queries.append(f"{classic_key}={SAMPLE}")
        for fragment in row["hash_map"]:
            for query in queries:
                add(f"{row['key']} #{fragment} on ?{query}", classic_path, query, fragment)
            add(f"{row['key']} #{fragment} percent-encoded", classic_path, "", fragment,
                shown="#" + fragment.replace("-", "%2D"))
            add(f"{row['key']} #{fragment} in capitals", classic_path, "", fragment, shown="#" + fragment.upper())
        for fragment in HOSTILE_FRAGMENTS:
            add(f"{row['key']} hostile fragment {fragment[:20]!r}", classic_path, "", fragment, shown=f"#{fragment}")
    return cases


REVERSE_CASES = build_reverse_cases()
FORWARD_CASES = build_forward_cases()


# ---------------------------------------------------------------------------
# Python side
# ---------------------------------------------------------------------------

def test_version_is_at_least_the_implementing_release():
    assert_app_version_at_least("0.261.445")


def test_the_cases_cover_the_registry():
    """A thin case list would make the TypeScript differential vacuous."""
    answered = [case for case in REVERSE_CASES if case["expected"] is not None]
    assert len(REVERSE_CASES) >= 200, len(REVERSE_CASES)
    assert len(answered) >= 80, len(answered)
    assert len(REVERSE_CASES) - len(answered) >= 25

    # Every row that has a V2 page of its own answers for it at least once. A row that shares its V2 route
    # with an earlier row (the HTML spelling of a custom page) is the one the earlier row answers for.
    answering = {case["expected"]["key"] for case in answered}
    seen_routes = set()
    shadowed = set()
    for row in registry_rows():
        if row["status"] not in ("native", "partial") or not row.get("v2"):
            continue
        if row["v2"] in seen_routes:
            shadowed.add(row["key"])
        seen_routes.add(row["v2"])
    unanswered = {
        row["key"] for row in registry_rows()
        if row["status"] in ("native", "partial") and row.get("v2") and row["key"] not in answering
    }
    assert unanswered == shadowed, f"Rows no case leads back to: {sorted(unanswered - shadowed)}"

    assert len(FORWARD_CASES) >= 40, len(FORWARD_CASES)
    assert any(case["expected"] != case["arrival"] for case in FORWARD_CASES)
    assert any(case["expected"] == case["arrival"] for case in FORWARD_CASES)


def test_the_classic_address_leads_back_through_the_redirect_to_the_row_it_came_from():
    """Open this page in classic, followed in the modern interface (without the escape pair), must not
    land on a different page: the classic address resolves forward to the same registry row."""
    checked = 0
    for case in REVERSE_CASES:
        expected = case["expected"]
        if expected is None:
            continue
        classic = urlsplit(expected["path"])
        forward = ui_routing.resolve_v2_target(classic.path, classic.query, classic.fragment)
        assert forward is not None, f"{case['label']}: {expected['path']} does not lead back to V2."
        assert forward["key"] == expected["key"], f"{case['label']}: {expected['path']} -> {forward}"
        checked += 1
    assert checked >= 80


def test_every_classic_address_built_is_safe_and_the_escape_pair_is_not_part_of_it():
    for case in REVERSE_CASES:
        expected = case["expected"]
        if expected is None:
            continue
        path = expected["path"]
        assert path.startswith("/") and not path.startswith("//") and "\\" not in path and " " not in path, path
        assert "ui=classic" not in path, "The escape pair is added by withClassicEscape, never by the resolver."
        assert not path.startswith("/v2"), path


def test_the_escape_pair_matches_the_one_the_server_honours():
    source = read(V2_SRC / "lib" / "classicLinks.ts")
    param = re.search(r"export const CLASSIC_ESCAPE_PARAM = '([^']+)';", source)
    value = re.search(r"export const CLASSIC_ESCAPE_VALUE = '([^']+)';", source)
    assert param and value
    assert (param.group(1), value.group(1)) == (
        functions_ui_redirect.ESCAPE_QUERY_KEY, functions_ui_redirect.ESCAPE_QUERY_VALUE,
    )
    assert functions_ui_redirect.has_classic_escape(f"x=1&{param.group(1)}={value.group(1)}")
    assert not functions_ui_redirect.has_classic_escape(f"{param.group(1)}=modern")


def test_classic_links_is_a_pure_module_over_the_generated_registry():
    source = read(V2_SRC / "lib" / "classicLinks.ts")
    code = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    code = re.sub(r"(?m)^\s*//.*$", "", code)
    imports = re.findall(r"^import[^;]*?from\s+'([^']+)';", code, flags=re.M | re.S)
    assert sorted(imports) == ["./conversationUrl", "./generated/uiRouteMap"], imports
    for forbidden in (r"\bwindow\b", r"\bdocument\b", r"\blocalStorage\b", r"\bsessionStorage\b", r"\bfetch\b",
                      r"\beval\(", r"\binnerHTML\b", r"dangerouslySetInnerHTML", r"\bnew Function\b"):
        assert not re.search(forbidden, code), f"classicLinks.ts must stay a pure module ({forbidden})."


def test_the_app_mounts_the_fragment_translation_once_below_the_router():
    app = read(V2_SRC / "App.tsx")
    assert app.count("useClassicFragmentTranslation()") == 1
    assert "from './lib/useClassicFragmentTranslation'" in app
    assert "createBrowserRouter" in read(V2_SRC / "main.tsx") and "<App />" in read(V2_SRC / "main.tsx")

    hook = read(V2_SRC / "lib" / "useClassicFragmentTranslation.ts")
    assert hook.count("navigate(") == 1 and "{ replace: true }" in hook, (
        "The fragment is swapped for its route in place; a new history entry would make Back return to it."
    )
    assert "translateClassicFragment(pathname, search, hash)" in hook


def test_every_way_back_to_the_classic_interface_carries_the_escape_pair():
    app = read(V2_SRC / "App.tsx")
    assert "withClassicEscape(classicChatHref(null))" in app, "The boot error's link must carry ui=classic."

    sidebar = read(V2_SRC / "components" / "layout" / "Sidebar.tsx")
    assert "classicBackHref(location.pathname, location.search, location.hash, activeConversationId)" in sidebar
    assert "classicChatHref" not in sidebar, "The account menu's link is context-aware; classicBackHref keeps the chat carry-over."

    assert 'href="/chats?ui=classic"' in read(APP_ROOT / "route_frontend_v2.py"), (
        "The missing-bundle page's link must carry ui=classic so a selected modern interface cannot redirect it back."
    )


# ---------------------------------------------------------------------------
# The TypeScript twin, executed
# ---------------------------------------------------------------------------

def test_the_typescript_twin_agrees_with_the_server_resolver_and_keeps_its_promises():
    """Execute the TypeScript checks, skipping when the front-end toolchain is absent."""
    if not (V2_DIR / "node_modules").exists():
        pytest.skip("application/v2_ui/node_modules is absent; run npm install to include")
    assert LOGIC_CHECK_TS.exists(), "The TypeScript classic links checks are missing"

    # functional_tests/ has no node_modules of its own, so the bundle is written where node can resolve
    # bare imports from.
    bundle = V2_DIR / "node_modules" / ".cache-classic-links-check.mjs"
    cases_file = V2_DIR / "node_modules" / ".cache-classic-links-cases.json"
    cases_file.write_text(json.dumps({"reverse": REVERSE_CASES, "forward": FORWARD_CASES}), encoding="utf-8")
    try:
        subprocess.run(
            [
                "npx", "esbuild", str(LOGIC_CHECK_TS),
                "--bundle", "--platform=node", "--format=esm", "--packages=external",
                "--define:import.meta.env={}",
                f"--outfile={bundle}", "--log-level=error",
            ],
            cwd=str(V2_DIR),
            check=True,
            shell=(sys.platform == "win32"),
        )
        result = subprocess.run(
            ["node", str(bundle)],
            cwd=str(V2_DIR),
            capture_output=True,
            text=True,
            env={**os.environ, "CLASSIC_LINKS_CASES": str(cases_file)},
            shell=(sys.platform == "win32"),
        )
    finally:
        for path in (bundle, cases_file):
            if path.exists():
                path.unlink()

    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr)
        raise AssertionError("the TypeScript classic links checks failed")
    passed = result.stdout.count("  ok  ")
    assert passed >= 14, f"Only {passed} classic links checks ran; the runner likely broke."
    assert "differential checks skipped" not in result.stdout, "The server resolver's cases were not checked"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))

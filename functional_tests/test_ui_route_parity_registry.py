#!/usr/bin/env python3
# test_ui_route_parity_registry.py
"""
Guard for the classic to V2 page route registry.
Version: 0.261.445
Implemented in: 0.261.445

``application/single_app/ui_route_map.json`` maps every classic (server-rendered) page route to
the V2 (React, /v2) route that replaces it. The interface selector will read it to redirect
classic URLs to V2 and to offer "open this page in classic", so it has to stay complete and
truthful. This guard fails when:

- a classic page route is added, renamed or removed without a matching registry row;
- a page template is not claimed by a row, or a row claims a template that does not exist;
- a native, alias or partial row names a V2 route that ``App.tsx`` does not declare;
- a gap, partial, deliberate, dead, standalone or api_surface row lacks what its status needs;
- a gap row exists, or a partial row is not in the explicit list of expected partial rows;
- the generated TypeScript copy is stale.

A gap row (a page with no V2 answer yet) may no longer exist: every classic page now has a V2 page
(native, alias or partial), is deliberately server-rendered (standalone) or is not a page. The
partial rows are an explicit, shrinking list (``EXPECTED_PARTIAL_KEYS``), and each must say what
still hands off to classic. A gap row whose V2 route is declared in ``App.tsx`` is still reported as
a warning first, because the hard guard would otherwise only say that the row exists.

It also pins the resolvers: path parameters, query, fragment, V2 to classic, rows that must not
resolve, and hostile input (``//host``, backslashes, encoded dots and slashes, control
characters, schemes) that must never produce anything but a same-site path.

Every failure message names the row to add or fix.
"""

import ast
import contextlib
import copy
import io
import json
import re
import subprocess
import sys
import warnings
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from unittest import mock
from urllib.parse import urlsplit

sys.path.append(str(Path(__file__).resolve().parent))

from test_support.app_stubs import import_app_module
from test_support.versioning import assert_app_version_at_least


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"
TEMPLATES_DIR = APP_ROOT / "templates"
V2_SRC = REPO_ROOT / "application" / "v2_ui" / "src"
APP_TSX = V2_SRC / "App.tsx"
REGISTRY_JSON = APP_ROOT / "ui_route_map.json"
GENERATED_TS = V2_SRC / "lib" / "generated" / "uiRouteMap.ts"
BUILD_SCRIPT = REPO_ROOT / "scripts" / "build_ui_route_map.py"
DOCS_INVENTORY_SCRIPT = REPO_ROOT / "scripts" / "build_docs_inventory.py"

REGISTRY_HINT = "application\\single_app\\ui_route_map.json"
TEST_HINT = "functional_tests\\test_ui_route_parity_registry.py"

ui_routing = import_app_module("ui_routing")


# ---------------------------------------------------------------------------
# What is not a classic page
# ---------------------------------------------------------------------------

# Routes outside the /api and /external namespaces that are still not classic pages. Each entry
# is (file, path or path prefix ending in '/', reason). An entry that no longer matches a
# route fails the staleness check, so the list cannot rot.
NON_PAGE_ROUTES = (
    ("route_frontend_v2.py", "/v2", "The V2 single-page application shell itself."),
    ("route_frontend_v2.py", "/v2/<path:subpath>", "The V2 shell for every client-side V2 route."),
    (
        "route_access_restriction.py",
        "/v2/access-restricted",
        "The V2 shell, served ahead of the /v2 catch-all so a restricted user can reach V2's Access restricted page.",
    ),
    (
        "route_frontend_conversations.py",
        "/conversation/<conversation_id>/messages",
        "A JSON endpoint under a non-/api path, not a page.",
    ),
    ("route_backend_feedback.py", "/feedback/", "The feedback JSON API under a non-/api path."),
    ("route_inbound_mcp.py", "/.well-known/", "OAuth discovery metadata (JSON) for the inbound MCP server."),
)
NON_PAGE_NAMESPACES = ("/api/", "/external/")

# Page templates that no route renders and no template includes. They are dead files; they
# need no row, but they must stay unreferenced or this list is stale.
UNRENDERED_TEMPLATES = {
    "my_feedback.html": "Replaced by the Profile Feedback tab; /my_feedback now redirects there.",
    "my_groups.html": "Replaced by the Profile Groups tab; /my_groups now redirects there.",
    "my_public_workspaces.html": "Replaced by the Profile Public workspaces tab; /my_public_workspaces now redirects there.",
    "my_safety_violations.html": "Replaced by the Profile Violations tab; /safety_violations now redirects there.",
    "public_workspace_modals.html": "A partial that no template includes.",
}

STATUS_GUIDE = (
    "Pick the status like this: native (V2 fully replaces the page), alias (the route only redirects "
    "to another classic page), partial (V2 has the page but part of it is missing or still hands off "
    "to classic; say what in notes and add a plan_ref), gap (no V2 page yet; plan_ref and the planned "
    "v2 route), standalone (must stay server-rendered: sign-in, OAuth callbacks), deliberate (not "
    "ported on purpose; say why), dead (unreachable or broken), api_surface (developer tool or static "
    "endpoint)."
)
PLAN_REF_RE = re.compile(r"Phase \d+(?: \(.+\))?")

# The partial rows that are expected to remain: pages whose V2 version still hands part of the job to
# classic. A partial row that is not listed, and a listed key that is no longer partial, both fail,
# so the lists only shrink: whoever finishes a page flips its row in the registry and removes its key
# in the same change.
#
# `home` and `terms-of-use` are partial by design, not for lack of work: their signed-out and
# pre-sign-in states are served by the server in both interfaces, so the redirect applies to signed-in
# application users only. They are permanent, so their notes must name what stays handed off.
PARTIAL_BY_DESIGN_KEYS = frozenset({"home", "terms-of-use"})
# Pages whose V2 work is still being finished. Their notes describe the hand-off as it stood when the
# registry was written, so a stale one is reported as a warning until the page is flipped. Every page
# is finished at 0.261.445, so the list is empty; a new unfinished page is added here with its row.
PARTIAL_UNFINISHED_KEYS = frozenset()
EXPECTED_PARTIAL_KEYS = PARTIAL_BY_DESIGN_KEYS | PARTIAL_UNFINISHED_KEYS
# What a partial row's notes must contain so the hand-off is named, not implied.
HAND_OFF_NOTE_RE = re.compile(r"still classic|handed off|hands? off", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Registry data
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def registry_data():
    return json.loads(REGISTRY_JSON.read_text(encoding="utf-8"))


def rows():
    return registry_data()["routes"]


def registry():
    return ui_routing.load_ui_route_map()


def current_map():
    """The registry parsed from the data ``rows()`` reads, so a test can alter the data and resolve against it."""
    return ui_routing.parse_ui_route_map(registry_data())


def rows_by_key():
    return {row["key"]: row for row in rows()}


# ---------------------------------------------------------------------------
# Classic route enumeration (AST, the way route_tests/test_route_blueprint_policy_inventory.py does)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RouteDecl:
    file_name: str
    function_name: str
    path: str
    methods: tuple  # None when the decorator's methods are not a literal list
    line: int
    node: ast.AST

    @property
    def get_capable(self):
        return self.methods is None or "GET" in self.methods

    @property
    def effective_methods(self):
        return None if self.methods is None else set(self.methods)

    def describe(self):
        verbs = "GET" if self.methods is None else "/".join(self.methods)
        return f"{self.file_name}:{self.line} {verbs} {self.path} ({self.function_name})"


def dotted_name(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = dotted_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    if isinstance(node, ast.Call):
        return dotted_name(node.func)
    return ""


@lru_cache(maxsize=1)
def route_declarations():
    """Every route decorator in the application's Python files."""
    declarations = []
    for file_path in sorted(APP_ROOT.glob("*.py")):
        source = file_path.read_text(encoding="utf-8")
        if ".route(" not in source:
            continue
        tree = ast.parse(source, filename=str(file_path))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                if not isinstance(decorator, ast.Call) or not dotted_name(decorator.func).endswith(".route"):
                    continue
                if not (decorator.args and isinstance(decorator.args[0], ast.Constant)
                        and isinstance(decorator.args[0].value, str)):
                    continue
                methods = ("GET",)
                for keyword in decorator.keywords:
                    if keyword.arg == "methods":
                        try:
                            literal = ast.literal_eval(keyword.value)
                            methods = tuple(str(item).upper() for item in literal)
                        except (ValueError, SyntaxError):
                            methods = None
                declarations.append(RouteDecl(
                    file_name=file_path.name,
                    function_name=node.name,
                    path=decorator.args[0].value,
                    methods=methods,
                    line=node.lineno,
                    node=node,
                ))
    return tuple(declarations)


def non_page_exclusion(declaration):
    for file_name, path, reason in NON_PAGE_ROUTES:
        if declaration.file_name != file_name:
            continue
        if declaration.path == path or (path.endswith("/") and declaration.path.startswith(path)):
            return reason
    return None


def candidate_page_routes():
    """GET-capable routes outside the API namespaces that are not on the explicit exclusion list."""
    return [
        declaration for declaration in route_declarations()
        if declaration.get_capable
        and not declaration.path.startswith(NON_PAGE_NAMESPACES)
        and non_page_exclusion(declaration) is None
    ]


# ---------------------------------------------------------------------------
# App.tsx route parsing
# ---------------------------------------------------------------------------

def _skip_string(source, start):
    """Index just past the string literal that opens at ``start``."""
    quote = source[start]
    index = start + 1
    length = len(source)
    while index < length:
        char = source[index]
        if char == "\\":
            index += 2
            continue
        if char == quote:
            return index + 1
        if char == "\n" and quote != "`":
            return index
        index += 1
    return length


def strip_comments(source):
    """Remove // and /* */ comments, leaving string literals (and their '/*') intact."""
    out = []
    index = 0
    length = len(source)
    while index < length:
        char = source[index]
        following = source[index + 1] if index + 1 < length else ""
        if char in "'\"`":
            end = _skip_string(source, index)
            out.append(source[index:end])
            index = end
        elif char == "/" and following == "/":
            newline = source.find("\n", index)
            index = length if newline == -1 else newline
        elif char == "/" and following == "*":
            close = source.find("*/", index + 2)
            out.append(" ")
            index = length if close == -1 else close + 2
        else:
            out.append(char)
            index += 1
    return "".join(out)


def _tag_end(source, start):
    """End index (just past '>') of the JSX tag opened at ``start``, and whether it self-closes."""
    depth = 0
    index = start
    length = len(source)
    while index < length:
        char = source[index]
        if char in "'\"`":
            index = _skip_string(source, index)
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
        elif char == ">" and depth <= 0:
            return index + 1, source[start:index].rstrip().endswith("/")
        index += 1
    return length, False


_ROUTE_TAG_RE = re.compile(r"<(/?)Route(?![A-Za-z0-9_])")
_PATH_ATTR_RE = re.compile(
    r"""(?:^|\s)path\s*=\s*(?:"(?P<dq>[^"]*)"|'(?P<sq>[^']*)'|\{\s*(?:"(?P<bdq>[^"]*)"|'(?P<bsq>[^']*)'|`(?P<bt>[^`$]*)`)\s*\})"""
)
_INDEX_ATTR_RE = re.compile(r"(?:^|\s)index(?=\s|/|$)")
_PATHNAME_COMPARE_RES = (
    re.compile(r"""pathname\s*===?\s*['"](/[^'"]*)['"]"""),
    re.compile(r"""['"](/[^'"]*)['"]\s*===?\s*[A-Za-z_.]*pathname"""),
)


def _join_route_path(parent, own):
    if own.startswith("/"):
        joined = own
    elif parent in ("", "/"):
        joined = "/" + own
    else:
        joined = f"{parent}/{own}"
    joined = re.sub(r"/{2,}", "/", joined)
    return joined if joined == "/" else joined.rstrip("/")


def declared_v2_routes(source):
    """The V2 route patterns a TSX source declares, relative to the /v2 basename.

    Reads ``<Route path=...>`` elements (nested ones join onto their parent, ``index`` routes
    take their parent's path) and the ``pathname === '/x'`` comparisons the shell uses for the
    pages that render outside the router. A catch-all ``*`` is not a page and is left out; a
    path built from an expression cannot be read and is skipped.
    """
    code = strip_comments(source)
    found = []
    stack = []
    position = 0
    while True:
        match = _ROUTE_TAG_RE.search(code, position)
        if match is None:
            break
        if match.group(1):
            if stack:
                stack.pop()
            position = match.end()
            continue
        end, self_closing = _tag_end(code, match.end())
        attributes = code[match.end():end - 1]
        parent = stack[-1] if stack else ""
        path_match = _PATH_ATTR_RE.search(attributes)
        own = None
        if path_match:
            own = next((value for value in path_match.groupdict().values() if value is not None), None)
        if own is not None:
            absolute = _join_route_path(parent, own)
            found.append(absolute)
        elif _INDEX_ATTR_RE.search(attributes):
            absolute = parent or "/"
            found.append(absolute)
        else:
            absolute = parent
        if not self_closing:
            stack.append(absolute)
        position = end
    for pattern in _PATHNAME_COMPARE_RES:
        found.extend(match.group(1) for match in pattern.finditer(code))
    unique = []
    for path in found:
        # A top-level catch-all is a redirect for unknown URLs, not a page, and would cover everything.
        if path not in ("*", "/*") and path not in unique:
            unique.append(path)
    return unique


def split_pattern(pattern):
    return () if pattern == "/" else tuple(pattern[1:].split("/"))


def route_covers(declared, wanted):
    """Whether a declared route pattern serves the wanted pattern, and whether it is the same text."""
    declared_segments = split_pattern(declared)
    wanted_segments = split_pattern(wanted)
    splat = bool(declared_segments) and declared_segments[-1] == "*"
    if splat:
        declared_segments = declared_segments[:-1]
        if len(wanted_segments) < len(declared_segments):
            return False
    elif len(declared_segments) != len(wanted_segments):
        return False
    for declared_segment, wanted_segment in zip(declared_segments, wanted_segments):
        if declared_segment.startswith(":"):
            continue
        if declared_segment != wanted_segment or wanted_segment.startswith(":"):
            return False
    return True


def declared_covering(wanted, declared_routes):
    return [declared for declared in declared_routes if route_covers(declared, wanted)]


@lru_cache(maxsize=1)
def app_declared_routes():
    return tuple(declared_v2_routes(APP_TSX.read_text(encoding="utf-8")))


# ---------------------------------------------------------------------------
# Helpers for messages
# ---------------------------------------------------------------------------

def row_example(declaration):
    key = re.sub(r"[^a-z0-9]+", "-", declaration.function_name.lower()).strip("-")
    row = {
        "key": key,
        "classic": declaration.path,
        "methods": list(declaration.methods or ("GET",)),
        "status": "gap",
        "v2": "/" + key,
        "plan_ref": "Phase N",
        "notes": "What the page does and what V2 lacks.",
    }
    return json.dumps(row)


def fail(title, lines, advice=""):
    detail = "\n".join(f"  - {line}" for line in lines)
    suffix = f"\n{advice}" if advice else ""
    raise AssertionError(f"{title}\n{detail}{suffix}")


# ---------------------------------------------------------------------------
# (a) every classic page route has a row
# ---------------------------------------------------------------------------

def test_version_is_at_least_the_implementing_release():
    assert_app_version_at_least("0.261.445")


def test_registry_loads_and_every_row_is_well_formed():
    loaded = registry()
    assert len(loaded.routes) == len(rows())
    assert {route.key for route in loaded.routes} == {row["key"] for row in rows()}


def test_every_classic_page_route_has_a_registry_row():
    covered = {row["classic"] for row in rows() if "GET" in row["methods"]}
    uncovered = [declaration for declaration in candidate_page_routes() if declaration.path not in covered]
    if uncovered:
        fail(
            f"{len(uncovered)} classic page route(s) have no row in {REGISTRY_HINT}:",
            [declaration.describe() for declaration in uncovered],
            "Add one row per route, for example:\n  " + row_example(uncovered[0]) + "\n" + STATUS_GUIDE
            + f"\nIf the route is not a page (a JSON or static endpoint, or the V2 shell), add it to "
            f"NON_PAGE_ROUTES in {TEST_HINT} with the reason.",
        )


def test_non_page_exclusions_still_match_a_route():
    stale = [
        f"{file_name} {path}"
        for file_name, path, _reason in NON_PAGE_ROUTES
        if not any(
            declaration.file_name == file_name
            and (declaration.path == path or (path.endswith("/") and declaration.path.startswith(path)))
            for declaration in route_declarations()
        )
    ]
    if stale:
        fail(
            "NON_PAGE_ROUTES lists routes that no longer exist:",
            stale,
            f"Delete those entries from NON_PAGE_ROUTES in {TEST_HINT}.",
        )
    assert all(reason.strip() for _file, _path, reason in NON_PAGE_ROUTES), "Every exclusion needs a reason."


def test_no_row_describes_a_route_the_code_does_not_declare():
    declared = {}
    for declaration in route_declarations():
        declared.setdefault(declaration.path, []).append(declaration)
    problems = []
    for row in rows():
        candidates = declared.get(row["classic"], [])
        if not candidates:
            problems.append(f"Row '{row['key']}' names {row['classic']}, which no route declares. Fix `classic` or delete the row.")
            continue
        wanted = set(row["methods"])
        if not any(candidate.effective_methods is None or candidate.effective_methods == wanted for candidate in candidates):
            actual = sorted({"/".join(candidate.methods or ("?",)) for candidate in candidates})
            problems.append(
                f"Row '{row['key']}' lists methods {sorted(wanted)} for {row['classic']}, but the code declares {actual}. Fix `methods`."
            )
    if problems:
        fail(f"Rows in {REGISTRY_HINT} that do not match the code:", problems)


# ---------------------------------------------------------------------------
# (b) templates
# ---------------------------------------------------------------------------

def load_docs_inventory():
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    try:
        import build_docs_inventory
    finally:
        sys.path.pop(0)
    return build_docs_inventory


TEMPLATE_REFERENCE_RE = re.compile(r"""\{%-?\s*(?:extends|include|import|from)\s+["']([^"']+)["']""")


@lru_cache(maxsize=1)
def app_pages():
    """Top-level page templates with the routes that render them (the docs inventory's own extraction)."""
    return tuple(load_docs_inventory().extract_app_pages())


@lru_cache(maxsize=1)
def templates_used_by_other_templates():
    """Layouts and partials: templates another template extends, includes or imports."""
    referenced = set()
    for path in TEMPLATES_DIR.rglob("*.html"):
        referenced.update(
            name for name in TEMPLATE_REFERENCE_RE.findall(path.read_text(encoding="utf-8", errors="ignore"))
            if name != path.name
        )
    return referenced


def test_every_page_template_belongs_to_a_row():
    pages = app_pages()
    layouts = templates_used_by_other_templates()
    claims = {}
    for row in rows():
        for template in row.get("templates", []):
            claims.setdefault(template, []).append(row)

    problems = []
    for page in pages:
        template = page["template"]
        route_urls = page.get("route_urls") or ([page["route_url"]] if page.get("route_url") else [])
        if template in UNRENDERED_TEMPLATES:
            if template in claims or route_urls or template in layouts:
                problems.append(
                    f"{template} is listed in UNRENDERED_TEMPLATES but a route, a row or another template uses it; "
                    f"remove it from that list."
                )
            continue
        if template in claims:
            if route_urls and not any(row["classic"] in route_urls for row in claims[template]):
                problems.append(
                    f"{template} is rendered by {', '.join(route_urls)}, but only row(s) "
                    f"{', '.join(row['key'] for row in claims[template])} claim it. Claim it on the row for {route_urls[0]}."
                )
            continue
        if not route_urls and template in layouts:
            continue  # A layout or partial that a claimed page extends or includes.
        hint = f" (rendered by {', '.join(route_urls)})" if route_urls else ""
        problems.append(
            f"{template}{hint} is not claimed by any row. Add \"templates\": [\"{template}\"] to the row for the "
            f"route that renders it, or add a row for it. If no route renders it and no template extends or "
            f"includes it, it is dead: list it in UNRENDERED_TEMPLATES in {TEST_HINT}."
        )

    on_disk = {path.name for path in TEMPLATES_DIR.glob("*.html")}
    for template, claimers in claims.items():
        if template not in on_disk and not (TEMPLATES_DIR / template).is_file():
            problems.append(
                f"Row '{claimers[0]['key']}' claims {template}, which is not in templates\\. Fix or remove it from `templates`."
            )
    for template in UNRENDERED_TEMPLATES:
        if template not in on_disk:
            problems.append(f"UNRENDERED_TEMPLATES lists {template}, which no longer exists. Remove it from {TEST_HINT}.")
    if problems:
        fail(f"Page templates and rows disagree ({REGISTRY_HINT}):", problems)


def test_hash_fragments_are_real_element_ids_on_the_classic_page():
    problems = []
    for row in rows():
        fragments = row.get("hash_map")
        if not fragments:
            continue
        text = "\n".join((TEMPLATES_DIR / name).read_text(encoding="utf-8") for name in row.get("templates", []))
        for fragment in fragments:
            if not re.search(r"""\bid\s*=\s*["']%s["']""" % re.escape(fragment), text):
                problems.append(
                    f"Row '{row['key']}' maps the fragment #{fragment}, but no element on its template(s) "
                    f"{row.get('templates')} has that id. Fix the fragment or `templates`."
                )
    if problems:
        fail(f"Fragments in {REGISTRY_HINT} that the classic page does not have:", problems)


# ---------------------------------------------------------------------------
# (c) V2 targets exist
# ---------------------------------------------------------------------------

def test_resolvable_rows_point_at_routes_app_tsx_declares():
    declared = app_declared_routes()
    problems = []
    for row in rows():
        if row["status"] not in ("native", "alias", "partial"):
            continue
        targets = [("v2", row["v2"])]
        targets += [("v2_subroutes", sub) for sub in row.get("v2_subroutes", [])]
        for suffix_source in [entry.get("path") for entry in row.get("hash_map", {}).values()] + [
            suffix
            for rule in row.get("query_map", {}).values() if isinstance(rule, dict)
            for suffix in rule.get("path", {}).values()
        ]:
            if suffix_source:
                base = "" if row["v2"] == "/" else row["v2"]
                targets.append(("a hash_map or query_map route segment", base + suffix_source))
        for label, pattern in targets:
            if not declared_covering(pattern, declared):
                problems.append(
                    f"Row '{row['key']}' ({row['status']}) {label} {pattern!r} is not declared in application\\v2_ui\\src\\App.tsx."
                )
    if problems:
        fail(
            f"Rows in {REGISTRY_HINT} whose V2 route does not exist:",
            problems,
            "Fix the row's `v2` (a <Route path> in App.tsx; :params are matched by name-agnostic segments), add the "
            "route to App.tsx, or set the status to gap with a plan_ref until the page exists.\nDeclared V2 routes: "
            + ", ".join(sorted(declared)),
        )


def test_gap_rows_whose_v2_page_has_landed_are_reported():
    """A gap row is a safe lie: it keeps the page classic. Report it so it gets flipped, but do not block."""
    declared = app_declared_routes()
    overtaken = [
        f"Row '{row['key']}' is gap, but App.tsx now declares {row['v2']!r}. Set its status to native, or to partial "
        f"with a plan_ref and notes saying what is left, and remove plan_ref if it is native."
        for row in rows()
        if row["status"] == "gap" and row["v2"] and declared_covering(row["v2"], declared)
    ]
    if overtaken:
        message = f"Gap rows in {REGISTRY_HINT} whose page has landed:\n  - " + "\n  - ".join(overtaken)
        print(f"NOTICE: {message}")
        warnings.warn(message, UserWarning, stacklevel=1)


def test_v2_parameters_never_swallow_another_v2_page():
    """A :param row would claim a literal sibling such as /groups/directory unless the row reserves it."""
    declared = [path for path in app_declared_routes() if ":" not in path and "*" not in path]
    all_patterns = {
        pattern
        for row in rows() if row["v2"] and row["status"] in ("native", "alias", "partial")
        for pattern in [row["v2"], *row.get("v2_subroutes", [])]
    }
    problems = []
    for row in rows():
        if row["status"] not in ("native", "partial") or not row["v2"]:
            continue
        reserved = row.get("v2_reserved", {})
        for pattern in [row["v2"], *row.get("v2_subroutes", [])]:
            segments = split_pattern(pattern)
            params = [index for index, segment in enumerate(segments) if segment.startswith(":")]
            if not params:
                continue
            for literal in declared:
                literal_segments = split_pattern(literal)
                if len(literal_segments) != len(segments) or not route_covers(pattern, literal):
                    continue
                values = [(segments[index][1:], literal_segments[index]) for index in params]
                if all(value in reserved.get(name, []) for name, value in values):
                    continue
                if literal in all_patterns:
                    continue
                example = {name: [value] for name, value in values}
                problems.append(
                    f"App.tsx declares {literal!r}, which also matches row '{row['key']}' pattern {pattern!r}. "
                    f"Add \"v2_reserved\": {json.dumps(example)} to the row (V2-only page), or give {literal!r} its own row."
                )
    for row in rows():
        for name, values in row.get("v2_reserved", {}).items():
            for value in values:
                if not any(
                    value in split_pattern(literal) and route_covers(pattern, literal)
                    for pattern in [row["v2"], *row.get("v2_subroutes", [])] if pattern
                    for literal in declared
                ):
                    problems.append(
                        f"Row '{row['key']}' reserves {value!r} for :{name}, but App.tsx declares no such route. Remove the entry."
                    )
    if problems:
        fail(f"V2 parameter routes in {REGISTRY_HINT} that collide with other V2 pages:", sorted(set(problems)))


def v2_source_tokens():
    tokens = set()
    quoted = re.compile(r"""(['"`])([A-Za-z0-9_.-]{1,64})\1""")
    keyed = re.compile(r"[?&]([A-Za-z0-9_.-]{1,64})=")
    for path in V2_SRC.rglob("*.ts*"):
        if "generated" in path.parts:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        tokens.update(match.group(2) for match in quoted.finditer(text))
        tokens.update(match.group(1) for match in keyed.finditer(text))
    return tokens


def test_v2_query_keys_the_rows_produce_are_read_by_v2():
    tokens = v2_source_tokens()
    problems = []
    for row in rows():
        if row["status"] not in ("native", "alias", "partial"):
            continue
        produced = set(row.get("v2_query", {}))
        for rule in row.get("query_map", {}).values():
            if isinstance(rule, str):
                produced.add(rule)
            elif "to" in rule:
                produced.add(rule["to"])
        for entry in row.get("hash_map", {}).values():
            produced.update(entry.get("query", {}))
        for key in sorted(produced):
            if key not in tokens:
                problems.append(f"Row '{row['key']}' produces the V2 query key {key!r}, which no V2 source mentions. Fix the key.")
    if problems:
        fail(f"V2 query keys in {REGISTRY_HINT} that V2 does not read:", problems)


# ---------------------------------------------------------------------------
# (d) documented rows
# ---------------------------------------------------------------------------

def test_rows_carry_what_their_status_needs():
    problems = []
    for row in rows():
        key = row["key"]
        status = row["status"]
        notes = (row.get("notes") or "").strip()
        plan_ref = row.get("plan_ref")
        if status == "gap":
            if not plan_ref:
                problems.append(f"Row '{key}' is gap: add plan_ref (for example \"Phase 2\") naming the plan phase that builds it.")
            if not row["v2"] and not notes:
                problems.append(f"Row '{key}' is gap with no planned `v2`: set `v2`, or explain in notes why it has none.")
        elif status == "partial":
            if not plan_ref:
                problems.append(f"Row '{key}' is partial: add plan_ref naming the plan phase that closes the gap.")
            if not notes:
                problems.append(f"Row '{key}' is partial: add notes saying what V2 still lacks or hands off to classic.")
        elif status in ("deliberate", "dead", "standalone", "api_surface"):
            if not notes:
                problems.append(f"Row '{key}' is {status}: add notes saying why (it has no V2 page).")
        elif status == "alias":
            if not row.get("alias_target"):
                problems.append(f"Row '{key}' is alias: add alias_target, the classic URL it redirects to (for example \"/profile?tab=groups\").")
        if plan_ref and not PLAN_REF_RE.fullmatch(plan_ref):
            problems.append(f"Row '{key}' plan_ref {plan_ref!r} should look like \"Phase 5\" or \"Phase 5 (5c delete group)\".")
        if status in ("native", "alias") and plan_ref:
            problems.append(f"Row '{key}' is {status} but still has plan_ref {plan_ref!r}; remove it.")
    if problems:
        fail(f"Rows in {REGISTRY_HINT} that are not documented well enough:", problems)


def test_no_gap_rows_remain_and_partial_rows_are_the_expected_ones():
    """Every classic page has a V2 answer; what still hands off to classic is a short, named list."""
    problems = []
    for row in rows():
        if row["status"] == "gap":
            problems.append(
                f"Row '{row['key']}' is gap. No classic page may be left without a V2 answer: set it to native "
                f"(V2 fully replaces it), partial (add it to EXPECTED_PARTIAL_KEYS in {TEST_HINT} and say in notes what "
                f"still hands off), or standalone (it must stay server-rendered, with notes saying why)."
            )
    partial = {row["key"] for row in rows() if row["status"] == "partial"}
    for key in sorted(partial - EXPECTED_PARTIAL_KEYS):
        problems.append(
            f"Row '{key}' is partial but is not in EXPECTED_PARTIAL_KEYS in {TEST_HINT}. Finish the V2 page and set the "
            f"row to native, or add the key to the list with notes that say what still hands off to classic."
        )
    for key in sorted(EXPECTED_PARTIAL_KEYS - partial):
        problems.append(
            f"EXPECTED_PARTIAL_KEYS lists '{key}', which is no longer a partial row. Remove it from the list in "
            f"{TEST_HINT}: the list only shrinks."
        )
    by_key = rows_by_key()
    stale = []
    for key in sorted(partial & EXPECTED_PARTIAL_KEYS):
        notes = by_key[key].get("notes") or ""
        if HAND_OFF_NOTE_RE.search(notes):
            continue
        message = (
            f"Row '{key}' is partial, so its notes must say precisely what still hands off to classic. Add a "
            f"sentence that starts \"Still classic:\" (or says what is \"handed off\" and why), or flip the row."
        )
        if key in PARTIAL_BY_DESIGN_KEYS:
            problems.append(message)
        else:
            stale.append(message)
    if problems:
        fail(f"The partial and gap rows in {REGISTRY_HINT} are not what the guard expects:", problems)
    if stale:
        # Reported, not failed: these pages are being finished and the row is flipped when they are.
        text = f"Partial rows in {REGISTRY_HINT} whose notes do not name the hand-off:\n  - " + "\n  - ".join(stale)
        print(f"NOTICE: {text}")
        warnings.warn(text, UserWarning, stacklevel=1)


def alias_redirect(declaration):
    """(endpoint, keyword arguments) of the redirect(url_for(...)) an alias route returns, or None."""
    for node in ast.walk(declaration.node):
        if not (isinstance(node, ast.Call) and dotted_name(node.func) == "redirect" and node.args):
            continue
        target = node.args[0]
        if not (isinstance(target, ast.Call) and dotted_name(target.func) == "url_for"
                and target.args and isinstance(target.args[0], ast.Constant)):
            continue
        arguments = {
            keyword.arg: keyword.value.value
            for keyword in target.keywords
            if keyword.arg and isinstance(keyword.value, ast.Constant)
        }
        return target.args[0].value, arguments
    return None


def test_alias_rows_redirect_where_they_say_and_resolve_to_the_same_v2_page():
    problems = []
    for row in rows():
        if row["status"] != "alias":
            continue
        declarations = [d for d in route_declarations() if d.path == row["classic"] and d.get_capable]
        redirect = alias_redirect(declarations[0]) if declarations else None
        if redirect is None:
            problems.append(f"Row '{row['key']}' is alias, but {row['classic']} does not return redirect(url_for(...)). Change its status.")
            continue
        endpoint, arguments = redirect
        function_name = endpoint.rsplit(".", 1)[-1]
        targets = [d for d in route_declarations() if d.function_name == function_name and d.get_capable
                   and not d.path.startswith(NON_PAGE_NAMESPACES)]
        if len(targets) != 1:
            problems.append(f"Row '{row['key']}' redirects to {endpoint}, which does not name exactly one page route.")
            continue
        expected = targets[0].path
        if arguments:
            expected += "?" + "&".join(f"{name}={value}" for name, value in arguments.items())
        if row.get("alias_target") != expected:
            problems.append(
                f"Row '{row['key']}' says alias_target {row.get('alias_target')!r}, but {row['classic']} redirects to {expected!r}. Fix alias_target."
            )
            continue
        target = urlsplit(expected)
        route_map = current_map()
        via_target = ui_routing.resolve_v2_target(target.path, target.query, route_map=route_map)
        direct = ui_routing.resolve_v2_target(row["classic"], route_map=route_map)
        if via_target is None or direct is None or via_target["path"] != direct["path"]:
            problems.append(
                f"Row '{row['key']}' resolves to {direct and direct['path']!r}, but its alias target {expected!r} resolves to "
                f"{via_target and via_target['path']!r}. Make the alias row's v2/v2_query match the target row."
            )
    if problems:
        fail(f"Alias rows in {REGISTRY_HINT} that do not match their redirect:", problems)


# ---------------------------------------------------------------------------
# (e) generated TypeScript
# ---------------------------------------------------------------------------

def load_build_script():
    import importlib.util
    spec = importlib.util.spec_from_file_location("build_ui_route_map_under_test", BUILD_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_generated_typescript_and_document_table_are_current():
    result = subprocess.run(
        [sys.executable, str(BUILD_SCRIPT), "--check"],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, (
        "application\\v2_ui\\src\\lib\\generated\\uiRouteMap.ts or the page table in "
        "docs\\explanation\\features\\V2_CLASSIC_PAGE_PARITY.md is out of date with ui_route_map.json.\n"
        "Regenerate them with: python scripts\\build_ui_route_map.py\n" + result.stderr
    )


def test_check_flag_exits_non_zero_when_an_output_is_stale_or_missing():
    build = load_build_script()
    changed = copy.deepcopy(registry_data())
    changed["routes"][0]["notes"] = changed["routes"][0]["notes"] + " Edited."
    changed_map = build.ui_routing.parse_ui_route_map(changed)

    stderr = io.StringIO()
    with mock.patch.object(sys, "argv", ["build_ui_route_map.py", "--check"]), \
            mock.patch.object(build.ui_routing, "load_ui_route_map", return_value=changed_map), \
            contextlib.redirect_stderr(stderr):
        assert build.main() == 1
    assert "out of date" in stderr.getvalue() and "uiRouteMap.ts" in stderr.getvalue()
    assert "build_ui_route_map.py" in stderr.getvalue()

    # Only the document table differs: the TypeScript is the committed copy.
    reflagged = copy.deepcopy(registry_data())
    reflagged["routes"][0]["plan_ref"] = "Phase 9"
    committed_typescript = GENERATED_TS.read_text(encoding="utf-8")
    stderr = io.StringIO()
    with mock.patch.object(sys, "argv", ["build_ui_route_map.py", "--check"]), \
            mock.patch.object(build.ui_routing, "load_ui_route_map", return_value=build.ui_routing.parse_ui_route_map(reflagged)), \
            mock.patch.object(build, "render_typescript", return_value=committed_typescript), \
            contextlib.redirect_stderr(stderr):
        assert build.main() == 1
    assert "V2_CLASSIC_PAGE_PARITY.md" in stderr.getvalue() and "uiRouteMap.ts" not in stderr.getvalue()

    missing = Path(__file__).with_name("__never_generated__.ts")
    assert not missing.exists()
    with mock.patch.object(sys, "argv", ["build_ui_route_map.py", "--check", "--output", str(missing)]), \
            contextlib.redirect_stderr(io.StringIO()):
        assert build.main() == 1
    assert not missing.exists(), "--check must never write the file."

    unmarked = REPO_ROOT / "docs" / "explanation" / "features" / "V2_SUPPORT_MENU.md"
    stderr = io.StringIO()
    with mock.patch.object(sys, "argv", ["build_ui_route_map.py", "--check", "--doc", str(unmarked)]), \
            contextlib.redirect_stderr(stderr):
        assert build.main() == 2
    assert "ui-route-map:begin" in stderr.getvalue()


def test_generator_refuses_a_malformed_registry_with_the_row_named():
    build = load_build_script()
    broken = copy.deepcopy(registry_data())
    broken["routes"][1]["status"] = "natve"
    stderr = io.StringIO()
    with mock.patch.object(sys, "argv", ["build_ui_route_map.py", "--check"]), \
            mock.patch.object(build.ui_routing, "load_ui_route_map",
                              side_effect=lambda *_a, **_k: build.ui_routing.parse_ui_route_map(broken)), \
            contextlib.redirect_stderr(stderr):
        assert build.main() == 2
    assert "natve" in stderr.getvalue() and "native" in stderr.getvalue()


def test_generated_typescript_lists_every_row():
    text = GENERATED_TS.read_text(encoding="utf-8")
    assert text.startswith("// uiRouteMap.ts\n// Generated by scripts\\build_ui_route_map.py")
    for row in rows():
        assert f"key: '{row['key']}'" in text, f"Row '{row['key']}' is missing from the generated TypeScript."


# ---------------------------------------------------------------------------
# App.tsx parser
# ---------------------------------------------------------------------------

def test_route_parser_reads_flat_nested_index_and_pathname_routes():
    source = """
    // <Route path="/commented" element={<X />} />
    const a = '/*';
    export function App() {
        if (location.pathname === '/standalone') return <Standalone />;
        return (
            <Routes>
                <Route path="/" element={<Home />} />
                {/* <Route path="/also-commented" /> */}
                <Route path="/groups/:groupId/:section?" element={<Nav to={{ pathname: '/x', search: a }} replace />} />
                <Route path={'/braced'} element={<Y onChange={(next) => next > 1 ? 1 : 2} />} />
                <Route path="admin" element={<Layout />}>
                    <Route index element={<AdminHome />} />
                    <Route path="review/:section" element={<Review />}>
                        <Route path=":view" element={<View />} />
                    </Route>
                    <Route path="/absolute" element={<Z />} />
                </Route>
                <Route path="/files/*" element={<Files />} />
                {flag ? <Route path={`/ticked`} element={<T />} /> : null}
                <Route path={computed} element={<C />} />
                <Route path="*" element={<Navigate to="/" />} />
            </Routes>
        );
    }
    """
    routes = declared_v2_routes(source)
    assert "/commented" not in routes and "/also-commented" not in routes
    assert {
        "/", "/groups/:groupId/:section?", "/braced", "/admin", "/admin/review/:section", "/admin/review/:section/:view",
        "/absolute", "/files/*", "/ticked", "/standalone",
    } <= set(routes)
    assert "*" not in routes and "/computed" not in routes and "/x" not in routes


def test_route_matching_treats_params_as_wildcards_and_splats_as_prefixes():
    assert route_covers("/groups/:groupId", "/groups/:groupId")
    assert route_covers("/groups/:groupId", "/groups/abc")
    assert route_covers("/admin/review/:section/:view", "/admin/review/feedback/queue")
    assert not route_covers("/groups/directory", "/groups/:groupId")
    assert not route_covers("/groups/:groupId", "/groups")
    assert route_covers("/files/*", "/files/a/b") and route_covers("/files/*", "/files")
    assert not route_covers("/files/*", "/other")
    assert route_covers("/", "/") and not route_covers("/", "/chat")


def test_app_tsx_declares_the_router_pages_this_guard_depends_on():
    routes = set(app_declared_routes())
    assert {"/chat", "/workspace", "/settings", "/approvals", "/terms-of-use", "/access-restricted"} <= routes, (
        "The App.tsx parser no longer finds the core V2 routes; check functional_tests route parsing against App.tsx."
    )


# ---------------------------------------------------------------------------
# Sweep: nothing outside the page scope quietly became a page
# ---------------------------------------------------------------------------

def test_routes_in_scope_are_all_accounted_for_somewhere():
    """Every declared GET route is an API/external route, an excluded non-page, or a registry row."""
    unaccounted = []
    covered = {row["classic"] for row in rows() if "GET" in row["methods"]}
    for declaration in route_declarations():
        if not declaration.get_capable or declaration.path.startswith(NON_PAGE_NAMESPACES):
            continue
        if non_page_exclusion(declaration) is None and declaration.path not in covered:
            unaccounted.append(declaration.describe())
    assert not unaccounted, "Routes with neither a row nor an exclusion:\n  " + "\n  ".join(unaccounted)


# ---------------------------------------------------------------------------
# (f) resolvers
# ---------------------------------------------------------------------------

def forward(path, query="", fragment="", **kwargs):
    result = ui_routing.resolve_v2_target(path, query, fragment, **kwargs)
    return None if result is None else result["path"]


def backward(path, query="", fragment=""):
    result = ui_routing.resolve_classic_target(path, query, fragment)
    return None if result is None else result["path"]


def synthetic_map(*extra_rows):
    base = {
        "key": "thing", "classic": "/thing/<thing_id>", "methods": ["GET"], "status": "native",
        "v2": "/thing/:thingId", "path_params": {"thing_id": "thingId"},
    }
    data = {"schema_version": 1, "routes": [base, *extra_rows]}
    return ui_routing.parse_ui_route_map(data, source="synthetic.json")


def test_forward_carries_path_parameters_and_mapped_query_keys_only():
    assert forward("/groups/abc-123") == "/v2/groups/abc-123"
    assert forward("/public_workspaces/w1") == "/v2/public/w1"
    assert forward("/groups/a%20b") == "/v2/groups/a%20b", "An existing escape must not be encoded twice."
    assert forward("/chats", "conversation_id=abc&junk=1&utm_source=mail") == "/v2/chat?conversationId=abc"
    assert forward("/chats", "conversationId=first&conversation_id=second") == "/v2/chat?conversationId=first"
    assert forward("/chats", "prompt_id=p1&prompt_scope=group&prompt_scope_id=g1&openPrompt=1") == (
        "/v2/chat?prompt=p1&prompt_scope=group&prompt_scope_id=g1"
    )
    assert forward("/chats", "conversationId=a%26b%3Dc") == "/v2/chat?conversationId=a%26b%3Dc"
    assert forward("/approvals", "m365_approval=a1&anything=else") == "/v2/approvals?m365_approval=a1"
    assert forward("/content-review", "review_id=r1&tab=policy") == "/v2/content-review?scan_id=r1"
    assert forward("/", "") == "/v2"
    result = ui_routing.resolve_v2_target("/chats", "conversationId=abc")
    assert result["router_path"] == "/chat?conversationId=abc" and result["key"] == "chat"
    assert result["status"] in ("native", "partial")
    # The classic path parameters come back, for a caller that must check the page the URL names.
    assert result["params"] == {}
    assert ui_routing.resolve_v2_target("/custom/handbook")["params"] == {"slug": "handbook"}
    assert ui_routing.resolve_v2_target("/custom/handbook.html")["params"] == {"slug": "handbook"}
    assert ui_routing.resolve_v2_target("/groups/abc-123")["params"] == {"group_id": "abc-123"}


def test_forward_translates_tab_values_and_alias_rows():
    assert forward("/profile", "tab=public-workspaces") == "/v2/settings?tab=public"
    assert forward("/profile", "tab=settings") == "/v2/settings?tab=preferences"
    assert forward("/profile", "tab=violations") == "/v2/settings?tab=violations"
    assert forward("/profile", "tab=not-a-tab") == "/v2/settings", "An unknown value is dropped, not copied."
    assert forward("/profile") == "/v2/settings"
    assert forward("/my_groups", "tab=ignored&x=1") == "/v2/settings?tab=groups"
    assert forward("/my_public_workspaces") == "/v2/settings?tab=public"
    assert forward("/my_feedback") == "/v2/settings?tab=feedback"
    assert forward("/safety_violations") == "/v2/settings?tab=violations"


def test_forward_maps_fragments_and_feature_actions_to_sections():
    assert forward("/workspace", "", "plugins-tab") == "/v2/workspace/actions"
    assert forward("/workspace", "", "#documents-table") == "/v2/workspace/documents"
    assert forward("/workspace", "feature_action=file_sync") == "/v2/workspace/sync"
    assert forward("/workspace", "feature_action=file_sync", "prompts-tab") == "/v2/workspace/sync", (
        "The query string wins over the fragment when both name a section."
    )
    assert forward("/workspace", "", "no-such-fragment") == "/v2/workspace"
    assert forward("/workspace", "feature_action=unknown") == "/v2/workspace"
    assert forward("/approvals", "", "agent-template-approvals") == "/v2/approvals/agent-templates"
    assert forward("/profile", "tab=stats", "m365-connection-status") == (
        "/v2/settings?tab=preferences&section=m365-workflow-connection"
    )
    assert forward("/profile", "", "m365%2Dchat%2Dconnection") == "/v2/settings?tab=preferences&section=m365-chat-connection"
    assert forward("/workspace", "", "documents-tab\u0000") == "/v2/workspace", "A hostile fragment is ignored, never copied."


def test_forward_resolves_only_rows_that_have_a_v2_page():
    for path in ("/login", "/logout", "/getAToken", "/view_pdf", "/view_document", "/conversations",
                 "/conversation/abc", "/robots933456.txt", "/swagger", "/custom/assets/a/css/x.css", "/no/such/page"):
        assert forward(path) is None, f"{path} must stay classic."
    assert forward("/set_active_group", method="POST") is None
    assert forward("/admin/settings", method="POST") is None, "A form post must never be redirected."
    assert forward("/admin/settings", method="HEAD") == "/v2/admin"
    assert forward("/admin/settings", method="get") == "/v2/admin"

    gap_map = synthetic_map({
        "key": "later", "classic": "/later", "methods": ["GET"], "status": "gap", "v2": "/later",
        "plan_ref": "Phase 1", "notes": "Not built.",
    })
    assert ui_routing.resolve_v2_target("/later", route_map=gap_map) is None
    assert ui_routing.resolve_classic_target("/later", route_map=gap_map) is None
    assert ui_routing.resolve_v2_target("/thing/t1", route_map=gap_map)["path"] == "/v2/thing/t1"


def test_forward_prefers_the_most_specific_classic_rule():
    specific = synthetic_map(
        {"key": "dotted", "classic": "/thing/<thing_id>.html", "methods": ["GET"], "status": "partial",
         "v2": "/thing/:thingId", "path_params": {"thing_id": "thingId"}, "plan_ref": "Phase 1", "notes": "n"},
    )
    assert ui_routing.resolve_v2_target("/thing/abc.html", route_map=specific)["key"] == "dotted"
    assert ui_routing.resolve_v2_target("/thing/abc.html", route_map=specific)["path"] == "/v2/thing/abc"
    assert ui_routing.resolve_v2_target("/thing/abc", route_map=specific)["key"] == "thing"


def test_classic_only_query_keeps_an_embed_frame_out_of_the_redirect():
    framed = synthetic_map({
        "key": "page", "classic": "/page/<slug>", "methods": ["GET"], "status": "native", "v2": "/page/:slug",
        "path_params": {"slug": "slug"}, "classic_only_query": {"embed": "1"},
    })
    assert ui_routing.resolve_v2_target("/page/a", route_map=framed)["path"] == "/v2/page/a"
    assert ui_routing.resolve_v2_target("/page/a", "embed=0", route_map=framed)["path"] == "/v2/page/a"
    assert ui_routing.resolve_v2_target("/page/a", "x=1&embed=1", route_map=framed) is None
    assert ui_routing.resolve_v2_target("/page/a", "?embed=1", route_map=framed) is None
    assert ui_routing.resolve_v2_target("/page/a", b"embed=1", route_map=framed) is None
    # The real custom page rows carry it, so flipping them from gap cannot make V2's own frame redirect into V2.
    for key in ("custom-page", "custom-page-html"):
        assert rows_by_key()[key]["classic_only_query"] == {"embed": "1"}


HOSTILE_PATHS = (
    "//evil.example", "///evil.example", "/\\evil.example", "/\\\\evil.example", "/%2e%2e//evil.example",
    "/%2E%2E/evil", "/%2e/chats", "https://evil.example/chats", "http:evil.example",
    # xss-check: ignore reviewed: hostile input the resolver must refuse; it is never rendered or followed.
    "javascript:alert(1)",
    "data:text/html,x", "evil.example/chats", "/chats\x00", "/chats\r\nSet-Cookie: a=b", "/chats%0d%0aSet-Cookie:a=b",
    "/chats%00", "/chats%7f", "/groups/..", "/groups/%2e%2e", "/groups/a%2fb", "/groups/a%2Fb", "/groups/a%5cb",
    "/groups/a b", "/groups/a\tb", "/groups//x", "/groups/a/../b", "/./chats", "/chats/", "/chats//", "/chats?x=1",
    "/chats#frag", "", "/", None, 5, b"/chats",
)


def test_forward_never_returns_anything_but_a_same_site_path_for_hostile_input():
    for hostile in HOSTILE_PATHS:
        result = ui_routing.resolve_v2_target(hostile)
        if hostile == "/":
            assert result is not None and result["path"] == "/v2"
            continue
        assert result is None, f"{hostile!r} must be refused, got {result}"
    hostile_queries = (
        "conversationId=//evil.example", "conversationId=https://evil.example", "next=//evil.example",
        "next=/\\evil.example", "next=https://evil.example", "next=%2F%2Fevil.example", "next=%2f%5cevil.example",
        "evil=1&__proto__=x", "conversationId=a%00b", "conversationId=a%0d%0ab", "conversationId=" + "x" * 5000,
        "&".join(f"k{index}=v" for index in range(200)), "conversationId", "=x", "%zz=1&conversationId=ok",
    )
    for query in hostile_queries:
        result = ui_routing.resolve_v2_target("/terms-of-use", query)
        if result is None:
            continue
        assert result["path"].startswith("/v2") and result["path"][3:4] in ("", "/", "?"), result
        assert "evil" not in result["path"].lower(), f"A caller-supplied host was echoed for {query!r}: {result}"
        assert "\\" not in result["path"] and not any(ord(char) < 0x20 for char in result["path"])
    assert forward("/terms-of-use", "next=/chats%3Fa%3D1") == "/v2/terms-of-use?next=%2Fchats%3Fa%3D1"
    assert forward("/terms-of-use", "next=//evil.example") == "/v2/terms-of-use"
    assert forward("/terms-of-use", "next=/\\evil.example") == "/v2/terms-of-use"
    assert forward("/chats", "conversationId=" + "x" * 5000) is None
    assert forward("/chats", "&".join(f"k{index}=v" for index in range(200))) is None
    assert forward("/chats", "conversationId=a%00b") == "/v2/chat", "A value with control characters is not carried."


def test_forward_output_is_always_a_single_slash_path_under_the_v2_basename():
    for row in rows():
        if row["status"] not in ("native", "alias", "partial"):
            continue
        classic = re.sub(r"<(?:[a-z]+:)?([A-Za-z_]+)>", "abc-123", row["classic"])
        result = ui_routing.resolve_v2_target(classic)
        assert result is not None, f"Row '{row['key']}' did not resolve for {classic}."
        assert result["path"] == "/v2" or result["path"].startswith("/v2/") or result["path"].startswith("/v2?")
        assert not result["path"].startswith("//") and "\\" not in result["path"]
        assert result["key"] == row["key"], f"{classic} resolved through row '{result['key']}', not '{row['key']}'."


def test_reverse_maps_v2_pages_back_to_their_classic_pages():
    assert backward("/chat", "conversationId=abc&x=1") == "/chats?conversationId=abc"
    assert backward("/v2/chat", "prompt=p1&prompt_scope=group&prompt_scope_id=g1") == (
        "/chats?prompt_id=p1&prompt_scope=group&prompt_scope_id=g1"
    )
    assert backward("/workspace") == "/workspace"
    assert backward("/workspace/documents") == "/workspace#documents-tab"
    assert backward("/v2/workspace/actions/some-id") == "/workspace#plugins-tab"
    assert backward("/workspace/tags") == "/workspace?feature_action=document_tag_system"
    assert backward("/settings", "tab=preferences") == "/profile?tab=settings"
    assert backward("/settings", "tab=public&x=1") == "/profile?tab=public-workspaces"
    assert backward("/settings", "tab=preferences&section=m365-chat-connection") == "/profile?tab=settings#m365-chat-connection"
    assert backward("/groups/abc/members") == "/groups/abc"
    assert backward("/groups/abc/documents") == "/group_workspaces", "A workspace section is the classic workspace page."
    assert backward("/groups") == "/group_workspaces"
    assert backward("/public/w1/settings") == "/public_workspaces/w1"
    assert backward("/public/directory") == "/public_directory"
    assert backward("/approvals/agent-templates") == "/approvals#agent-template-approvals"
    assert backward("/admin/settings/keyvault-section") == "/admin/settings"
    assert backward("/admin/review/safety/violations") == "/admin/safety_violations"
    assert backward("/control-center/users") == "/admin/control-center"
    assert backward("/") == "/" and backward("/v2") == "/" and backward("/v2/") == "/"
    assert backward("/chat/") == "/chats", "React Router ignores one trailing slash."
    assert ui_routing.resolve_classic_target("/groups/abc/members")["key"] == "group-manage"


def test_reverse_has_no_answer_for_v2_only_pages_aliases_and_unknown_paths():
    assert backward("/groups/directory") is None, "V2's group directory is not a group id."
    assert backward("/admin/review/feedback/dashboard") is None
    assert backward("/dev/alert-lab") is None
    assert backward("/no/such/page") is None
    assert backward("/settings", "tab=groups") == "/profile?tab=groups", "The canonical Profile row answers, not the alias."


def test_reverse_refuses_hostile_input():
    for hostile in ("//evil.example", "/v2//evil.example", "/v2/\\evil", "/\\evil", "/v2/%2e%2e/evil", "/v2/..", "/v2/chat/../x",
                    "https://evil.example/chat", "/chat\x00", "/chat%0d%0a", "/groups/a%2fb", "", None, 5):
        assert ui_routing.resolve_classic_target(hostile) is None, f"{hostile!r} must be refused."
    assert backward("/terms-of-use", "next=//evil.example") == "/terms-of-use"
    assert backward("/chat", "conversationId=a%00b") == "/chats"
    assert backward("/chat", "&".join(f"k{index}=v" for index in range(200))) is None


def test_forward_then_reverse_returns_the_classic_address():
    for classic_path, query, fragment, expected in (
        ("/chats", "conversationId=abc", "", "/chats?conversationId=abc"),
        ("/workspace", "", "plugins-tab", "/workspace#plugins-tab"),
        ("/workspace", "", "documents-tab", "/workspace#documents-tab"),
        ("/profile", "tab=public-workspaces", "", "/profile?tab=public-workspaces"),
        ("/profile", "tab=settings", "m365-chat-connection", "/profile?tab=settings#m365-chat-connection"),
        ("/public_workspaces/w1", "", "", "/public_workspaces/w1"),
        ("/approvals", "m365_approval=a1", "", "/approvals?m365_approval=a1"),
        ("/public_directory", "", "", "/public_directory"),
        ("/admin/feedback_review", "", "", "/admin/feedback_review"),
        # V2 merges the group workspace and manage pages, so the workspace page answers for both.
        ("/groups/abc-123", "", "", "/group_workspaces"),
    ):
        moved = ui_routing.resolve_v2_target(classic_path, query, fragment)
        assert moved is not None, classic_path
        parts = urlsplit(moved["path"])
        back = ui_routing.resolve_classic_target(parts.path, parts.query)
        assert back is not None and back["path"] == expected, f"{classic_path} -> {moved['path']} -> {back}"


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

def parse_with(*row_changes, drop=()):
    data = copy.deepcopy(registry_data())
    for index, changes in row_changes:
        for name, value in changes.items():
            data["routes"][index][name] = value
    for index, name in drop:
        del data["routes"][index][name]
    return ui_routing.parse_ui_route_map(data, source="test.json")


def problems_of(action):
    try:
        action()
    except ui_routing.UiRouteMapError as error:
        return list(error.problems), str(error)
    raise AssertionError("The registry should have been rejected.")


def test_loader_reports_every_malformed_row_with_the_row_and_the_fix():
    keys = [row["key"] for row in rows()]
    chat = keys.index("chat")
    problems, text = problems_of(lambda: parse_with(
        (chat, {"status": "natve"}),
        (keys.index("my-groups"), {"methods": ["get"]}),
        (keys.index("home"), {"classic": "chats"}),
    ))
    assert len(problems) == 3
    assert any("'chat'" in line and "'natve'" in line and "native" in line for line in problems)
    assert any("'my-groups'" in line and "methods" in line for line in problems)
    assert any("'home'" in line and "classic" in line for line in problems)
    assert "3 problems" in text and "V2_CLASSIC_PAGE_PARITY.md" in text


def test_loader_rejects_structurally_unsafe_or_inconsistent_rows():
    keys = [row["key"] for row in rows()]
    cases = (
        ({"v2": "chat"}, "must be a route path that starts with '/'"),
        ({"v2": "/chat//x"}, "segment"),
        ({"v2": "/ch at"}, "segment"),
        ({"v2": None}, "needs a `v2` route"),
        ({"query_map": {"a": {"to": "b", "path": {"x": "/y"}}}}, "exactly one"),
        ({"query_map": {"a b": "c"}}, "usable query key"),
        ({"query_map": {"a": {"values": {"x": "y"}}}}, "exactly one"),
        ({"hash_map": {"x": {}}}, "'path' and/or 'query'"),
        ({"hash_map": {"x": {"path": "documents"}}}, "route segment"),
        ({"v2_query": {"tab": 5}}, "text"),
        ({"v2_subroutes": ["/other/:x"]}, "must extend"),
        ({"v2_reserved": {"nope": ["x"]}}, "not a parameter"),
        ({"templates": ["../x.html"]}, "template file names"),
        ({"alias_target": "//evil.example"}, "same-site path"),
        ({"surprise": True}, "unknown fields"),
    )
    chat = keys.index("chat")
    for changes, expected in cases:
        problems, _text = problems_of(lambda changes=changes: parse_with((chat, changes)))
        assert any(expected in line for line in problems), f"{changes} -> {problems}"
    problems, _text = problems_of(lambda: parse_with((chat, {"path_params": {"nope": "x"}})))
    assert any("not a placeholder" in line for line in problems)
    problems, _text = problems_of(lambda: parse_with((keys.index("group-manage"), {"path_params": {"group_id": "other"}})))
    assert any("not a parameter" in line or "supplies" in line for line in problems)
    problems, _text = problems_of(lambda: parse_with((keys.index("login"), {"v2": "/login"})))
    assert any("no V2 page" in line for line in problems)
    problems, _text = problems_of(lambda: parse_with((chat, {"key": "Not Kebab"})))
    assert any("kebab-case" in line for line in problems)
    problems, _text = problems_of(lambda: parse_with((chat, {"key": "home"})))
    assert any("keys must be unique" in line for line in problems)
    problems, _text = problems_of(lambda: parse_with((chat, {"classic": "/"})))
    assert any("exactly one row" in line for line in problems)
    problems, _text = problems_of(lambda: parse_with(drop=[(0, "status")]))
    assert any("missing required fields" in line for line in problems)
    problems, _text = problems_of(lambda: ui_routing.parse_ui_route_map({"schema_version": 2, "routes": [{}]}))
    assert any("schema_version" in line for line in problems)
    problems, _text = problems_of(lambda: ui_routing.parse_ui_route_map([]))
    assert any("top level" in line for line in problems)


def test_loader_caches_and_clear_cache_rereads():
    first = ui_routing.load_ui_route_map()
    assert ui_routing.load_ui_route_map() is first
    ui_routing.clear_ui_route_map_cache()
    assert ui_routing.load_ui_route_map() is not first


def test_ui_routing_is_pure_python_with_no_application_imports():
    tree = ast.parse((APP_ROOT / "ui_routing.py").read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported <= {"json", "re", "dataclasses", "functools", "pathlib", "urllib"}, (
        f"ui_routing.py must stay pure (no Flask, settings or network): it imports {sorted(imported)}"
    )
    assert (APP_ROOT / "ui_routing.py").read_text(encoding="utf-8").startswith("# ui_routing.py")


# ---------------------------------------------------------------------------
# The guards themselves: each one must fail, and say what to do, when its rule is broken
# ---------------------------------------------------------------------------

_REMOVE = object()


def guard_failure(guard, *needles, registry_changes=None, patched=None):
    """Run a guard against altered registry data and return the failure text, checking the needles."""
    data = copy.deepcopy(registry_data())
    if registry_changes is not None:
        registry_changes(data["routes"])
    replacements = {"registry_data": lambda: data}
    replacements.update(patched or {})
    with mock.patch.dict(globals(), replacements):
        try:
            guard()
        except AssertionError as error:
            text = str(error)
        else:
            raise AssertionError(f"{guard.__name__} did not fail for the altered registry.")
    for needle in needles:
        assert needle in text, f"{guard.__name__} failure should mention {needle!r}:\n{text}"
    return text


def drop_row(key):
    def change(routes):
        routes[:] = [row for row in routes if row["key"] != key]
    return change


def edit_row(key, **changes):
    def change(routes):
        for row in routes:
            if row["key"] == key:
                for name, value in changes.items():
                    if value is _REMOVE:
                        row.pop(name, None)
                    else:
                        row[name] = value
    return change


def test_guard_names_the_row_to_add_for_a_new_classic_page_route():
    existing = route_declarations()
    new_route = RouteDecl(
        file_name="route_frontend_reports.py", function_name="reports", path="/reports", methods=("GET",), line=12, node=None,
    )
    text = guard_failure(
        test_every_classic_page_route_has_a_registry_row, "route_frontend_reports.py:12", "/reports", '"classic": "/reports"',
        "NON_PAGE_ROUTES", patched={"route_declarations": lambda: (*existing, new_route)},
    )
    assert "native (V2 fully replaces the page)" in text
    guard_failure(test_every_classic_page_route_has_a_registry_row, "/notifications", registry_changes=drop_row("notifications"))
    # A POST-only handler and an /api route are not pages.
    post_only = RouteDecl("route_frontend_reports.py", "save", "/reports/save", ("POST",), 20, None)
    api = RouteDecl("route_frontend_reports.py", "data", "/api/reports", ("GET",), 30, None)
    with mock.patch.dict(globals(), {"route_declarations": lambda: (*existing, post_only, api)}):
        test_every_classic_page_route_has_a_registry_row()


def test_guard_catches_rows_that_drifted_from_the_code():
    guard_failure(
        test_no_row_describes_a_route_the_code_does_not_declare, "'chat'", "/chat-renamed",
        registry_changes=edit_row("chat", classic="/chat-renamed"),
    )
    guard_failure(
        test_no_row_describes_a_route_the_code_does_not_declare, "'admin-settings'", "methods",
        registry_changes=edit_row("admin-settings", methods=["GET"]),
    )
    guard_failure(
        test_non_page_exclusions_still_match_a_route, "/gone/", "NON_PAGE_ROUTES",
        patched={"NON_PAGE_ROUTES": (*NON_PAGE_ROUTES, ("route_frontend_v2.py", "/gone/", "stale"))},
    )


def test_guard_catches_unclaimed_and_stale_template_claims():
    guard_failure(test_every_page_template_belongs_to_a_row, "workspace.html", "templates",
                  registry_changes=edit_row("workspace", templates=_REMOVE))
    guard_failure(test_every_page_template_belongs_to_a_row, "ghost.html", "not in templates",
                  registry_changes=edit_row("workspace", templates=["workspace.html", "ghost.html"]))
    guard_failure(test_every_page_template_belongs_to_a_row, "workspace.html", "Claim it on the row for /workspace",
                  registry_changes=lambda routes: (edit_row("workspace", templates=_REMOVE)(routes),
                                                   edit_row("agents", templates=["agents.html", "workspace.html"])(routes)))
    guard_failure(test_every_page_template_belongs_to_a_row, "my_feedback.html", "UNRENDERED_TEMPLATES",
                  registry_changes=edit_row("agents", templates=["agents.html", "my_feedback.html"]))
    guard_failure(test_hash_fragments_are_real_element_ids_on_the_classic_page, "#not-a-real-id", "'workspace'",
                  registry_changes=edit_row("workspace", hash_map={"not-a-real-id": {"path": "/documents"}}))


def test_guard_catches_v2_targets_that_do_not_exist_and_unreserved_siblings():
    guard_failure(test_resolvable_rows_point_at_routes_app_tsx_declares, "'agents'", "'/not-a-v2-page'", "App.tsx",
                  registry_changes=edit_row("agents", v2="/not-a-v2-page"))
    guard_failure(test_resolvable_rows_point_at_routes_app_tsx_declares, "'workspace'", "/workspace/:section/:resourceId/extra/deep",
                  registry_changes=edit_row("workspace", v2_subroutes=["/workspace/:section", "/workspace/:section/:resourceId/extra/deep"]))
    guard_failure(test_resolvable_rows_point_at_routes_app_tsx_declares, "'approvals'", "/approvals/agent-templates/extra/deep",
                  registry_changes=edit_row("approvals", hash_map={"agent-template-approvals": {"path": "/agent-templates/extra/deep"}}))
    guard_failure(test_v2_parameters_never_swallow_another_v2_page, "/groups/directory", "v2_reserved",
                  registry_changes=lambda routes: [row.pop("v2_reserved", None) for row in routes])
    guard_failure(test_v2_parameters_never_swallow_another_v2_page, "reserves 'nothing'",
                  registry_changes=edit_row("group-manage", v2_reserved={"groupId": ["directory", "nothing"]}))
    guard_failure(test_v2_query_keys_the_rows_produce_are_read_by_v2, "'chat'", "convId",
                  registry_changes=edit_row("chat", query_map={"conversationId": "convId"}))


def test_guard_catches_rows_that_are_not_documented_for_their_status():
    guard_failure(test_rows_carry_what_their_status_needs, "'conversations-list'", "notes",
                  registry_changes=edit_row("conversations-list", notes=_REMOVE))
    # `terms-of-use` is partial by design and stays so, unlike the rows whose pages are still being finished.
    guard_failure(test_rows_carry_what_their_status_needs, "'terms-of-use'", "plan_ref",
                  registry_changes=edit_row("terms-of-use", plan_ref=_REMOVE))
    guard_failure(test_rows_carry_what_their_status_needs, "'workflow-activity'", "plan_ref",
                  registry_changes=edit_row("workflow-activity", status="gap", plan_ref=_REMOVE))
    guard_failure(test_rows_carry_what_their_status_needs, "'my-groups'", "alias_target",
                  registry_changes=edit_row("my-groups", alias_target=_REMOVE))
    guard_failure(test_rows_carry_what_their_status_needs, "'agents'", "remove it",
                  registry_changes=edit_row("agents", plan_ref="Phase 3"))
    guard_failure(test_rows_carry_what_their_status_needs, "'home'", "Phase 5",
                  registry_changes=edit_row("home", plan_ref="soon"))


def test_guard_refuses_gap_rows_and_unexpected_or_unexplained_partial_rows():
    guard_failure(test_no_gap_rows_remain_and_partial_rows_are_the_expected_ones, "'notifications'", "is gap", "native",
                  registry_changes=edit_row("notifications", status="gap", plan_ref="Phase 1"))
    # A page that goes back to partial has to be listed, with what still hands off.
    guard_failure(test_no_gap_rows_remain_and_partial_rows_are_the_expected_ones, "'agents'", "EXPECTED_PARTIAL_KEYS",
                  registry_changes=edit_row("agents", status="partial", plan_ref="Phase 6", notes="Still classic: a section."))
    # The list only shrinks: a finished page that is still listed fails too.
    guard_failure(test_no_gap_rows_remain_and_partial_rows_are_the_expected_ones, "'agents'", "no longer a partial row",
                  patched={"EXPECTED_PARTIAL_KEYS": EXPECTED_PARTIAL_KEYS | {"agents"}})
    guard_failure(test_no_gap_rows_remain_and_partial_rows_are_the_expected_ones, "'terms-of-use'", "what still hands off",
                  registry_changes=edit_row("terms-of-use", notes="V2 has a terms page."))


def test_guard_catches_an_alias_that_no_longer_matches_its_redirect():
    guard_failure(test_alias_rows_redirect_where_they_say_and_resolve_to_the_same_v2_page, "'my-groups'", "/profile?tab=groups",
                  registry_changes=edit_row("my-groups", alias_target="/profile?tab=public-workspaces"))
    guard_failure(test_alias_rows_redirect_where_they_say_and_resolve_to_the_same_v2_page, "'my-groups'", "tab=groups",
                  registry_changes=edit_row("my-groups", v2_query={"tab": "public"}))
    guard_failure(test_alias_rows_redirect_where_they_say_and_resolve_to_the_same_v2_page, "'agents'", "does not return redirect",
                  registry_changes=edit_row("agents", status="alias", alias_target="/profile"))


def run_all():
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    failures = 0
    for test in tests:
        print(f"Running {test.__name__}...")
        try:
            test()
        except AssertionError as error:
            failures += 1
            print(f"FAILED {test.__name__}: {error}")
    print(f"{len(tests) - failures}/{len(tests)} checks passed.")
    return failures == 0


if __name__ == "__main__":
    sys.exit(0 if run_all() else 1)

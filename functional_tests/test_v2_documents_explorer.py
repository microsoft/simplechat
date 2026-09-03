#!/usr/bin/env python3
"""
Functional test for the V2 workspace documents explorer.

Version: 0.261.045
Implemented in: 0.261.045

The behavioural half of the front end lives in ``test_v2_documents_explorer_logic.ts``, run
from here. This file covers the parts that are only observable in the source, plus the new
server-side helpers, which are executed directly rather than asserted about.

What it pins:

**Settings keys must be whitelisted.** ``/api/user/settings`` validates against
``allowed_keys`` in route_backend_users.py and drops anything outside it **without
complaining** -- the POST still returns success and the value simply never arrives. A view
mode or saved view written under an unlisted key would appear to save and be gone on the next
reload.

**A new section must be registered on both sides.** ``resolveWorkspaceSections`` fails closed:
a section the server does not report is treated as unavailable. Adding Tags to the SPA alone
would produce a section that never renders, with no error to explain it.

**The new routes must carry the same guards as their neighbours.** Every document route is
``@swagger_route`` + ``@login_required`` + ``@user_required`` +
``@enabled_required("enable_user_workspace")``. Bulk delete is the one that matters most: it
removes many documents in a single unauthenticated-by-accident request.

**Sorting must not raise on a document that lacks the field.** ``sort_documents`` mapped a
missing value to ``""`` while leaving a present numeric value an ``int``, and Python 3 raises
``TypeError`` comparing the two. That was invisible while the allow-list held only strings; it
becomes a live crash the moment ``file_size`` is sortable.

**Standing views must be derived, not guessed.** "Untagged", "Processing" and "Shared with me"
are computed from the document rather than queried, so they are executed here against records
shaped like the real ones, including the legacy shape that has no ``percentage_complete``.
"""

import ast
import json
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = REPO_ROOT / "application" / "single_app"
V2_DIR = REPO_ROOT / "application" / "v2_ui"
V2_SRC = V2_DIR / "src"

sys.path.insert(0, str(REPO_ROOT / "functional_tests"))

from test_support.versioning import assert_app_version_at_least  # noqa: E402

DOCUMENTS_ROUTE = APP_DIR / "route_backend_documents.py"
USERS_ROUTE = APP_DIR / "route_backend_users.py"
SECTIONS_PY = APP_DIR / "functions_workspace_sections.py"
DOCUMENTS_FUNCTIONS = APP_DIR / "functions_documents.py"

ENDPOINTS_TS = V2_SRC / "lib" / "endpoints.ts"
EXPLORER_TS = V2_SRC / "lib" / "documentExplorer.ts"
SAVED_VIEWS_TS = V2_SRC / "lib" / "documentSavedViews.ts"
USER_SETTINGS_TS = V2_SRC / "lib" / "userSettings.ts"
SECTIONS_TSX = V2_SRC / "pages" / "workspace" / "sections.tsx"
WORKSPACE_PAGE_TSX = V2_SRC / "pages" / "workspace" / "WorkspacePage.tsx"
DOCUMENTS_SECTION_TSX = V2_SRC / "pages" / "workspace" / "DocumentsSection.tsx"
TAGS_SECTION_TSX = V2_SRC / "pages" / "workspace" / "TagsSection.tsx"
EXPLORER_TSX = V2_SRC / "components" / "documents" / "DocumentExplorer.tsx"
RAIL_TSX = V2_SRC / "components" / "documents" / "ExplorerRail.tsx"
TABLE_TSX = V2_SRC / "components" / "documents" / "DocumentTable.tsx"
TILES_TSX = V2_SRC / "components" / "documents" / "DocumentTiles.tsx"
DETAILS_TSX = V2_SRC / "components" / "documents" / "DocumentDetailsPane.tsx"
LOGIC_CHECK_TS = REPO_ROOT / "functional_tests" / "test_v2_documents_explorer_logic.ts"

# Routes added for the explorer, each with the guards its neighbours already carry.
NEW_ROUTES = [
    ("/api/documents/bulk-delete", "POST"),
    ("/api/documents/facets", "GET"),
]

REQUIRED_DECORATORS = [
    "@swagger_route(security=get_auth_security())",
    "@login_required",
    "@user_required",
    '@enabled_required("enable_user_workspace")',
]

NEW_SETTING_KEYS = ["v2DocumentsPrefs", "v2DocumentSavedViews"]


def _read(path):
    return path.read_text(encoding="utf-8")


def _load_module_functions(path, names):
    """Execute selected top-level functions from a module without importing it.

    ``route_backend_documents`` and ``functions_documents`` both import ``config``, which
    builds Azure clients at import time and cannot run without credentials. The helpers under
    test depend on nothing but ``datetime``, so the module is parsed and only those
    definitions -- plus the module-level constants they close over -- are executed.
    """
    tree = ast.parse(_read(path))
    wanted = set(names)

    def is_constant_assignment(node):
        return isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id.isupper()
            for target in node.targets
        )

    namespace = {
        "datetime": datetime,
        "timedelta": timedelta,
        "timezone": timezone,
    }

    # Constants are executed one at a time and failures are skipped: these modules also
    # define constants built from imports the extraction deliberately does not provide, and
    # only the ones the helpers under test close over need to succeed.
    for node in tree.body:
        if not is_constant_assignment(node):
            continue
        try:
            exec(
                compile(ast.Module(body=[node], type_ignores=[]), str(path), "exec"),
                namespace,
            )
        except Exception:  # noqa: BLE001
            continue

    definitions = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in wanted
    ]
    try:
        exec(
            compile(ast.Module(body=definitions, type_ignores=[]), str(path), "exec"),
            namespace,
        )
    except Exception as error:  # noqa: BLE001
        raise AssertionError(
            f"Could not execute the extracted helpers from {path.name}: {error}"
        ) from error

    missing = wanted - set(namespace)
    assert not missing, f"Could not extract {missing} from {path.name}"
    return namespace


def test_version_is_at_least_the_implementing_release():
    print("Testing version...")
    assert_app_version_at_least("0.261.045")
    print("  ok  version is at or beyond the implementing release")
    return True


def test_new_settings_keys_are_whitelisted():
    """An unlisted key is dropped silently, so this must never regress."""
    print("Testing settings key whitelist...")

    users = _read(USERS_ROUTE)
    block = re.search(r"allowed_keys = \{(.*?)\}", users, re.DOTALL)
    assert block, "Could not find allowed_keys in route_backend_users.py"
    allowed = set(re.findall(r"['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]", block.group(1)))

    settings_ts = _read(USER_SETTINGS_TS)
    writable_block = re.search(
        r"export const WRITABLE_USER_SETTING_KEYS = \[(.*?)\] as const;",
        settings_ts,
        re.DOTALL,
    )
    assert writable_block, "Could not find WRITABLE_USER_SETTING_KEYS in userSettings.ts"
    writable = set(re.findall(r"'([^']+)'", writable_block.group(1)))

    for key in NEW_SETTING_KEYS:
        assert key in allowed, (
            f"{key} is written by the explorer but is not in allowed_keys, so the server "
            "will accept the request and discard it"
        )
        assert key in writable, f"{key} must be declared in WRITABLE_USER_SETTING_KEYS"

    print(f"  ok  {', '.join(NEW_SETTING_KEYS)} are whitelisted on both sides")
    return True


def test_new_routes_carry_their_guards():
    print("Testing route guards...")

    source = _read(DOCUMENTS_ROUTE)
    for path, method in NEW_ROUTES:
        pattern = re.compile(
            r"@bp\.route\(\s*'" + re.escape(path) + r"'\s*,\s*methods=\['" + method + r"'\]\s*\)"
            r"(?P<decorators>(?:\s*@[^\n]+\n)+)\s*def\s+(?P<name>\w+)",
        )
        match = pattern.search(source)
        assert match, f"Could not find the {method} {path} route"

        decorators = match.group("decorators")
        for decorator in REQUIRED_DECORATORS:
            assert decorator in decorators, (
                f"{method} {path} is missing {decorator}; every personal document route "
                "carries all four"
            )
        print(f"  ok  {method} {path} carries all four guards")

    return True


def test_bulk_delete_reuses_the_single_delete_guards():
    """A guard added to one delete path must apply to the other."""
    print("Testing delete guard sharing...")

    source = _read(DOCUMENTS_ROUTE)

    assert "_personal_document_delete_guard(" in source, (
        "The delete guards should be factored into a shared helper"
    )
    assert source.count("_personal_document_delete_guard(") >= 3, (
        "The shared guard should be defined once and called by both delete routes; "
        "otherwise bulk delete becomes a way around a guard the single delete applies"
    )
    assert "build_synced_document_delete_guard" in source
    assert "conversation_linked_document_delete_requires_confirmation" in source

    bulk = source.split("def api_bulk_delete_user_documents")[1].split("@bp.route")[0]
    assert "needs_confirmation" in bulk, (
        "Bulk delete should report which documents were refused so the client can ask "
        "about those specifically"
    )
    assert "invalidate_personal_search_cache" in bulk, (
        "The search cache must be invalidated after a bulk delete"
    )

    print("  ok  both delete routes share one guard, and blocked documents are reported")
    return True


def test_sort_fields_are_typed_and_shared():
    """Sorting a numeric field must not raise on a document that lacks it."""
    print("Testing sort field handling...")

    functions = _read(DOCUMENTS_FUNCTIONS)
    assert "NUMERIC_DOCUMENT_SORT_FIELDS" in functions
    assert "TEXT_DOCUMENT_SORT_FIELDS" in functions
    assert "ALLOWED_DOCUMENT_SORT_FIELDS" in functions

    route = _read(DOCUMENTS_ROUTE)
    assert "allowed_sort_fields = {'_ts', 'file_name', 'title'}" not in route, (
        "The personal list route should use the shared allow-list rather than its own copy"
    )
    assert "ALLOWED_DOCUMENT_SORT_FIELDS" in route

    namespace = _load_module_functions(DOCUMENTS_FUNCTIONS, ["sort_documents", "_safe_float"])
    sort_documents = namespace["sort_documents"]

    # The regression: one document has a size, the other has never had one. Comparing an int
    # against "" is a TypeError in Python 3.
    documents = [
        {"id": "a", "file_size": 2048},
        {"id": "b"},
        {"id": "c", "file_size": 100},
    ]
    ordered = sort_documents(documents, sort_by="file_size", sort_order="asc")
    assert [item["id"] for item in ordered] == ["b", "c", "a"], ordered

    # Text fields still sort case-insensitively, and a missing value does not raise.
    names = sort_documents(
        [{"file_name": "Beta"}, {"file_name": "alpha"}, {}],
        sort_by="file_name",
        sort_order="asc",
    )
    assert [item.get("file_name") for item in names] == [None, "alpha", "Beta"], names

    # An unknown field falls back rather than raising, matching what every caller does.
    fallback = sort_documents([{"_ts": 2}, {"_ts": 1}], sort_by="nonsense", sort_order="asc")
    assert [item["_ts"] for item in fallback] == [1, 2]

    print("  ok  numeric sort fields tolerate documents that lack them")
    return True


def test_place_filters_and_facets_are_derived_correctly():
    print("Testing standing views and facet counts...")

    namespace = _load_module_functions(
        DOCUMENTS_ROUTE,
        [
            "filter_documents_by_place",
            "build_personal_document_facets",
            "_document_processing_state",
            "_parse_document_timestamp",
        ],
    )
    filter_by_place = namespace["filter_documents_by_place"]
    build_facets = namespace["build_personal_document_facets"]

    now = datetime.now(timezone.utc)
    recent_ts = int((now - timedelta(days=2)).timestamp())
    old_ts = int((now - timedelta(days=200)).timestamp())

    documents = [
        {"id": "ready", "user_id": "me", "tags": ["alpha"], "percentage_complete": 100,
         "status": "Processing complete", "_ts": recent_ts,
         "document_classification": "Internal"},
        {"id": "untagged", "user_id": "me", "tags": [], "percentage_complete": 100,
         "status": "Processing complete", "_ts": old_ts},
        {"id": "blank-tags", "user_id": "me", "tags": ["  "], "percentage_complete": 100,
         "_ts": old_ts},
        {"id": "processing", "user_id": "me", "tags": ["alpha"], "percentage_complete": 40,
         "status": "Saving page 2 of 5", "_ts": recent_ts},
        {"id": "failed", "user_id": "me", "tags": ["beta"], "percentage_complete": 55,
         "status": "Error: could not read file", "_ts": recent_ts},
        # A record predating progress tracking. It must read as ready, not as stuck.
        {"id": "legacy", "user_id": "me", "tags": ["beta"], "_ts": old_ts},
        {"id": "shared", "user_id": "someone-else", "tags": ["alpha"],
         "percentage_complete": 100, "_ts": recent_ts},
    ]

    def ids(items):
        return sorted(item["id"] for item in items)

    assert ids(filter_by_place(documents, "all", "me")) == ids(documents)
    assert ids(filter_by_place(documents, "untagged", "me")) == ["blank-tags", "untagged"], (
        "A tag that is only whitespace should not count as tagged"
    )
    assert ids(filter_by_place(documents, "processing", "me")) == ["processing"]
    assert ids(filter_by_place(documents, "errors", "me")) == ["failed"]
    assert ids(filter_by_place(documents, "shared", "me")) == ["shared"]
    assert ids(filter_by_place(documents, "recent", "me")) == [
        "failed",
        "processing",
        "ready",
        "shared",
    ]

    facets = build_facets(documents, "me")
    assert facets["total"] == 7
    assert facets["untagged"] == 2
    assert facets["processing"] == 1
    assert facets["errors"] == 1
    assert facets["shared_with_me"] == 1
    assert facets["recent"] == 4
    assert facets["by_tag"]["alpha"] == 3
    assert facets["by_tag"]["beta"] == 2
    assert facets["by_classification"]["Internal"] == 1
    assert "  " not in facets["by_tag"], "A whitespace tag should not become a facet"

    print("  ok  standing views and facet counts are derived from the documents")
    return True


def test_the_tags_section_is_registered_on_both_sides():
    """resolveWorkspaceSections fails closed, so a client-only section never renders."""
    print("Testing Tags section registration...")

    sections_py = _read(SECTIONS_PY)
    assert '"tags",' in sections_py, "tags must be in WORKSPACE_SECTION_IDS"
    assert '"tags": "knowledge"' in sections_py, "tags must be grouped under knowledge"
    assert '"tags": _section(True)' in sections_py, (
        "tags should be available on the same terms as documents"
    )

    sections_tsx = _read(SECTIONS_TSX)
    assert "id: 'tags'" in sections_tsx
    assert "TagsSection" in sections_tsx
    assert TAGS_SECTION_TSX.exists()

    print("  ok  tags is registered in both the server and the SPA registries")
    return True


def test_v1_does_not_grow_a_tab_from_the_new_section():
    """The classic interface reads only two values from the availability payload."""
    print("Testing that V1 is unaffected...")

    frontend = _read(APP_DIR / "route_frontend_workspace.py")
    assert "workspace_availability['sections']" not in frontend, (
        "The classic workspace must not iterate the section map, or adding a V2-only "
        "section would add a tab to it"
    )
    assert "workspace_availability['file_sync_enabled']" in frontend
    assert "workspace_availability['governance']" in frontend

    print("  ok  the classic workspace reads only file_sync_enabled and governance")
    return True


def test_the_client_calls_the_endpoints_that_exist():
    print("Testing endpoint coverage...")

    endpoints = _read(ENDPOINTS_TS)
    route = _read(DOCUMENTS_ROUTE)

    # Every path the explorer calls, and the route file that must define it.
    expected_paths = [
        "/api/documents?",
        "/api/documents/facets",
        "/api/documents/bulk-delete",
        "/api/documents/bulk-tag",
        "/api/documents/upload",
        "/api/documents/download",
        "/api/documents/extract_metadata",
        "/api/documents/reprocess_extraction",
        "/api/documents/tags",
    ]
    for path in expected_paths:
        assert path in endpoints, f"endpoints.ts should call {path}"
        assert path.rstrip("?") in route, (
            f"{path} is called by the client but not defined in route_backend_documents.py"
        )

    # The old fixed-page call is the specific regression: it pulled a thousand documents and
    # then filtered them in the browser, ignoring every server-side filter that exists.
    assert "page_size=1000" not in endpoints, (
        "The explorer pages server-side; a fixed 1000-row fetch defeats that"
    )
    assert "buildDocumentListParams" in endpoints, (
        "List parameters should come from the tested builder, not be assembled inline"
    )

    print(f"  ok  all {len(expected_paths)} document paths exist on both sides")
    return True


def test_the_explorer_is_wired_to_its_parts():
    print("Testing explorer composition...")

    explorer = _read(EXPLORER_TSX)
    for component in ("ExplorerRail", "ExplorerCommandBar", "DocumentTable", "DocumentTiles",
                      "DocumentDetailsPane", "ExplorerStatusBar", "FilterChips"):
        assert component in explorer, f"The explorer should render {component}"

    # Selection, filtering and paging rules must come from the tested module rather than
    # being reimplemented in the component.
    for helper in ("applySelection", "pruneSelection", "toggleSelectAll", "applyQueryChange",
                   "describeActiveFilters", "clearAllFilters", "toggleSort"):
        assert helper in explorer, f"The explorer should use {helper} from documentExplorer"

    assert "bulkDeletePersonalDocuments" in explorer
    assert "bulkTagPersonalDocuments" in explorer
    assert "onDropOnTag" in explorer, "Drag-to-tag should be wired to the rail"
    assert "application/x-simplechat-documents" in explorer, (
        "The drag payload needs an explicit type so unrelated drops are ignored"
    )
    assert "application/x-simplechat-documents" in _read(RAIL_TSX)

    # The Undo is what makes an immediately-applied bulk tag safe without a confirm step.
    assert "'Undo'" in explorer or '"Undo"' in explorer, (
        "Drag-to-tag should offer an undo rather than confirming beforehand"
    )

    print("  ok  the explorer composes its parts and reuses the tested rules")
    return True


def test_selection_is_not_a_mode():
    """The classic page requires switching multi-select on before a checkbox appears."""
    print("Testing selection model...")

    for path in (TABLE_TSX, TILES_TSX):
        source = _read(path)
        assert "event.shiftKey" in source, f"{path.name} should support Shift+click"
        assert "event.ctrlKey || event.metaKey" in source, (
            f"{path.name} should treat Ctrl and Cmd alike"
        )
        assert 'type="checkbox"' in source, f"{path.name} should always render a checkbox"

    explorer = _read(EXPLORER_TSX)
    assert "selectionModeActive" not in explorer, (
        "There should be no multi-select mode; selection works like any file manager"
    )
    assert "'a'" in explorer and "preventDefault" in explorer, (
        "Ctrl+A should select the page"
    )

    print("  ok  selection uses click/Ctrl/Shift with no mode to switch on")
    return True


def test_the_name_column_shows_the_title_over_the_file_name():
    print("Testing the name column...")

    table = _read(TABLE_TSX)
    assert "documentDisplayName" in table, (
        "The name column should use the shared two-line resolution"
    )
    assert "secondary" in table, "The file name should render beneath the title"

    explorer_lib = _read(EXPLORER_TS)
    assert "documentDisplayName" in explorer_lib

    print("  ok  the name column leads with the title and captions the file name")
    return True


def test_only_two_views_are_offered():
    print("Testing view modes...")

    sections = _read(SECTIONS_TSX)
    assert "layout: 'full'" in sections, (
        "The documents section needs the full width, not the prose measure"
    )

    page = _read(WORKSPACE_PAGE_TSX)
    assert "fullBleed" in page, "WorkspacePage should honour the full-bleed layout"
    assert "max-w-4xl" in page, "Other sections should keep their reading measure"

    explorer = _read(EXPLORER_TSX)
    assert "'tiles'" in explorer and "DocumentTable" in explorer
    # The classic interface's folder modes are deliberately not carried over; the rail
    # replaces them and is always visible.
    assert "folders-cards" not in explorer
    assert "'grid'" not in explorer

    print("  ok  two views, and the folder modes are not carried over")
    return True


def test_the_details_pane_handles_every_selection_size():
    print("Testing the details pane...")

    details = _read(DETAILS_TSX)
    assert "documents.length === 0" in details, "It should say what to do with nothing selected"
    assert "documents.length > 1" in details, "It should summarise a multi-selection"
    assert "commonTags" in details, "A multi-selection should show the tags it has in common"
    assert "totalFileSize" in details, "A multi-selection should report its combined size"

    print("  ok  the pane covers the empty, single and multiple cases")
    return True


def test_no_cdn_assets_were_introduced():
    """Browser assets must be served locally. See local_browser_assets.instructions.md."""
    print("Testing for CDN references...")

    offenders = []
    for path in sorted((V2_SRC / "components" / "documents").glob("*.tsx")) + [
        EXPLORER_TS,
        SAVED_VIEWS_TS,
        DOCUMENTS_SECTION_TSX,
        TAGS_SECTION_TSX,
    ]:
        source = _read(path)
        for match in re.finditer(r"https?://[^\s'\"`)]+", source):
            url = match.group(0)
            if "schemas" in url or "w3.org" in url:
                continue
            offenders.append(f"{path.name}: {url}")

    assert not offenders, f"Remote asset references are not allowed: {offenders}"
    print("  ok  no remote asset references")
    return True


def test_the_typescript_logic_checks_pass():
    """Execute the behavioural half, skipping when the front-end toolchain is absent."""
    print("Testing explorer logic (TypeScript)...")

    if not (V2_DIR / "node_modules").exists():
        print("  skip  application/v2_ui/node_modules is absent; run npm install to include")
        return True

    assert LOGIC_CHECK_TS.exists(), "The TypeScript logic checks are missing"

    # functional_tests/ has no node_modules of its own, so the bundle is written where node
    # can resolve bare imports from.
    bundle = V2_DIR / "node_modules" / ".cache-documents-explorer-check.mjs"
    try:
        subprocess.run(
            [
                "npx",
                "esbuild",
                str(LOGIC_CHECK_TS),
                "--bundle",
                "--platform=node",
                "--format=esm",
                "--packages=external",
                # endpoints.ts reaches apiClient.ts, which reads Vite's `import.meta.env` at
                # module scope. Node has no such object, so it is defined away here.
                "--define:import.meta.env={}",
                f"--outfile={bundle}",
                "--log-level=error",
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
            shell=(sys.platform == "win32"),
        )
    finally:
        if bundle.exists():
            bundle.unlink()

    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr)
        raise AssertionError("the TypeScript logic checks failed")

    passed = result.stdout.count("  ok  ")
    print(f"  ok  {passed} TypeScript logic checks passed")
    return True


TESTS = [
    test_version_is_at_least_the_implementing_release,
    test_new_settings_keys_are_whitelisted,
    test_new_routes_carry_their_guards,
    test_bulk_delete_reuses_the_single_delete_guards,
    test_sort_fields_are_typed_and_shared,
    test_place_filters_and_facets_are_derived_correctly,
    test_the_tags_section_is_registered_on_both_sides,
    test_v1_does_not_grow_a_tab_from_the_new_section,
    test_the_client_calls_the_endpoints_that_exist,
    test_the_explorer_is_wired_to_its_parts,
    test_selection_is_not_a_mode,
    test_the_name_column_shows_the_title_over_the_file_name,
    test_only_two_views_are_offered,
    test_the_details_pane_handles_every_selection_size,
    test_no_cdn_assets_were_introduced,
    test_the_typescript_logic_checks_pass,
]


if __name__ == "__main__":
    results = []
    for test in TESTS:
        try:
            results.append(bool(test()))
        except Exception as error:  # noqa: BLE001
            print(f"FAIL  {test.__name__}: {error}")
            import traceback

            traceback.print_exc()
            results.append(False)

    print(f"\n{sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)

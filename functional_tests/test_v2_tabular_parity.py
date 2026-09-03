#!/usr/bin/env python3
"""
Functional test for V2 tabular parity.

Version: 0.261.050
Implemented in: 0.261.050

The behavioural half lives in ``test_v2_tabular_parity_logic.ts``, run from here. This file
covers what is only observable across the two languages: that the client reads the keys the
server writes, calls the routes that exist, and that those routes are guarded.

What it pins:

**The client must read the metadata keys the server writes.** ``_build_generated_analysis_metadata``
in route_backend_chats.py writes ``generated_analysis_artifacts`` and
``generated_tabular_outputs`` onto the assistant message. Before this work the V2 client read
neither, so a generated export existed in storage with nothing in the interface leading to it
-- the failure was completely silent, because the reply still described the file it had made.

**The client must call routes that exist.** Every tabular path the SPA requests is asserted to
be registered on a Flask blueprint. A typo here produces a 404 at the exact moment a user
tries to download something, which is the worst possible time to discover it.

**Those routes must be guarded.** The runs endpoints resume and cancel work that costs model
calls, and the artifact download serves file content. All carry ``@swagger_route`` +
``@login_required`` + ``@user_required``, matching their neighbours.

**The confirmation thresholds must survive sanitization.** ``sanitize_settings_for_user``
strips ``TABULAR_GENERATION_BACKEND_SETTING_KEYS`` from the bootstrap payload. The three
large-run confirmation keys must *not* be in that list, or the dialog silently falls back to
its defaults on every installation and the administrator's configuration is ignored.

**No remote assets.** Browser JavaScript is served from local static assets only.
"""

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = REPO_ROOT / "application" / "single_app"
V2_DIR = REPO_ROOT / "application" / "v2_ui"
V2_SRC = V2_DIR / "src"

sys.path.insert(0, str(REPO_ROOT / "functional_tests"))

from test_support.versioning import assert_app_version_at_least  # noqa: E402

CHATS_ROUTE = APP_DIR / "route_backend_chats.py"
CITATIONS_ROUTE = APP_DIR / "route_enhanced_citations.py"
DOCUMENTS_ROUTE = APP_DIR / "route_backend_documents.py"
SETTINGS_PY = APP_DIR / "functions_settings.py"

ARTIFACTS_TS = V2_SRC / "lib" / "generatedArtifacts.ts"
LANES_TS = V2_SRC / "lib" / "activityLanes.ts"
ESTIMATE_TS = V2_SRC / "lib" / "tabularRunEstimate.ts"
CITATION_ROWS_TS = V2_SRC / "lib" / "agentCitationRows.ts"
CSV_TS = V2_SRC / "lib" / "csvPreview.ts"
ENDPOINTS_TS = V2_SRC / "lib" / "endpoints.ts"
ARTIFACT_CARD_TSX = V2_SRC / "components" / "chat" / "GeneratedArtifactCard.tsx"
RUN_STATUS_TSX = V2_SRC / "components" / "chat" / "TabularRunStatus.tsx"
LARGE_RUN_TSX = V2_SRC / "components" / "chat" / "LargeRunDialog.tsx"
FILE_PREVIEW_TSX = V2_SRC / "components" / "chat" / "ChatFilePreview.tsx"
MESSAGE_LIST_TSX = V2_SRC / "components" / "chat" / "MessageList.tsx"
THOUGHTS_LIST_TSX = V2_SRC / "components" / "chat" / "ThoughtsList.tsx"
INSPECTOR_TSX = V2_SRC / "components" / "chat" / "MessageInspector.tsx"
COMPOSER_TSX = V2_SRC / "components" / "chat" / "Composer.tsx"
CHAT_STORE_TS = V2_SRC / "stores" / "chatStore.ts"
TYPES_TS = V2_SRC / "lib" / "types.ts"

LOGIC_CHECK_TS = Path(__file__).with_name("test_v2_tabular_parity_logic.ts")

IMPLEMENTED_IN = "0.261.050"

# Every tabular-related path the V2 client requests, and the route file that must register it.
REQUIRED_ROUTES = {
    "/api/chat_artifacts/download": CITATIONS_ROUTE,
    "/api/enhanced_citations/tabular": CITATIONS_ROUTE,
    "/api/enhanced_citations/tabular_preview": CITATIONS_ROUTE,
    "/api/enhanced_citations/tabular_workspace": CITATIONS_ROUTE,
    "/api/get_file_content": DOCUMENTS_ROUTE,
    "/api/tabular/generated-output/runs/<run_id>": CHATS_ROUTE,
    "/api/tabular/generated-output/runs/<run_id>/resume": CHATS_ROUTE,
    "/api/tabular/generated-output/runs/<run_id>/cancel": CHATS_ROUTE,
    # Registered alongside the other blob-backed downloads rather than in the documents
    # blueprint, which is where it would first be looked for.
    "/api/workspace_documents/download": CITATIONS_ROUTE,
}

# The run-control routes, which spend money and serve file content.
GUARDED_ROUTES = [
    ("/api/tabular/generated-output/runs/<run_id>", CHATS_ROUTE),
    ("/api/tabular/generated-output/runs/<run_id>/resume", CHATS_ROUTE),
    ("/api/tabular/generated-output/runs/<run_id>/cancel", CHATS_ROUTE),
    ("/api/chat_artifacts/download", CITATIONS_ROUTE),
]

CONFIRMATION_SETTING_KEYS = [
    "enable_tabular_durable_run_confirmation",
    "tabular_durable_run_confirmation_threshold_rows",
    "tabular_durable_run_confirmation_threshold_batches",
]


def _read(path):
    assert path.exists(), f"Expected {path} to exist"
    return path.read_text(encoding="utf-8")


def test_the_client_reads_the_metadata_keys_the_server_writes():
    """A key the server writes and the client never reads is a silently unreachable file."""
    print("Testing generated-artifact metadata contract...")

    chats = _read(CHATS_ROUTE)
    artifacts = _read(ARTIFACTS_TS)

    for key in ("generated_analysis_artifacts", "generated_tabular_outputs"):
        assert f"'{key}'" in chats, f"{key} should be written by route_backend_chats.py"
        assert key in artifacts, (
            f"The V2 client must read metadata.{key}. The server writes generated exports "
            "under this key and nothing else advertises them, so not reading it leaves the "
            "file in storage with no control anywhere in the interface."
        )

    # The fields the card and the download target are built from.
    for field in (
        "artifact_message_id",
        "document_id",
        "export_run_id",
        "background_export",
        "suppress_assistant_table_export",
        "capability",
        "output_format",
        "conversation_id",
    ):
        assert field in chats, f"{field} should be normalized server-side"
        assert field in artifacts, f"The V2 client must read {field}"

    print("  ok  the client reads every key the server writes")
    return True


def test_the_dedupe_key_matches_the_server():
    """The two collections overlap, so both sides must agree on what makes an artifact one."""
    print("Testing artifact de-duplication parity...")

    chats = _read(CHATS_ROUTE)
    artifacts = _read(ARTIFACTS_TS)

    # The server's dedupe_key in _build_generated_analysis_metadata.
    assert "dedupe_key" in chats, "the server should de-duplicate artifacts"
    assert "dedupeKey" in artifacts, (
        "The client must de-duplicate too. The server appends a tabular export to both "
        "generated_analysis_artifacts and generated_tabular_outputs, so a reader that "
        "concatenates them shows every tabular export twice."
    )

    print("  ok  both sides de-duplicate on the same identifiers")
    return True


def test_every_requested_route_exists():
    """A path the SPA requests that no blueprint registers 404s at the worst moment."""
    print("Testing route existence...")

    client_sources = "\n".join(
        _read(path) for path in (ENDPOINTS_TS, ARTIFACTS_TS) if path.exists()
    )

    for path, route_file in REQUIRED_ROUTES.items():
        source = _read(route_file)
        # Flask registers the parameterised form; the client builds the concrete one.
        assert re.search(
            rf"""route\(\s*['"]{re.escape(path)}['"]""", source
        ), f"{path} must be registered in {route_file.name}"

    # And the client must actually be asking for them.
    for path in (
        "/api/chat_artifacts/download",
        "/api/tabular/generated-output/runs/",
        "/api/enhanced_citations/tabular?",
        "/api/get_file_content",
    ):
        assert path in client_sources, f"The V2 client should request {path}"

    print(f"  ok  all {len(REQUIRED_ROUTES)} tabular routes are registered and requested")
    return True


def test_the_run_control_routes_are_guarded():
    """Resume and cancel spend model calls; download serves file content."""
    print("Testing route decorators...")

    for path, route_file in GUARDED_ROUTES:
        source = _read(route_file)
        pattern = re.compile(
            rf"""route\(\s*['"]{re.escape(path)}['"][^)]*\)(?P<decorators>(?:\s*@[^\n]+\n)+)""",
        )
        match = pattern.search(source)
        assert match, f"Could not locate the decorators for {path}"

        decorators = match.group("decorators")
        for required in ("@swagger_route", "@login_required", "@user_required"):
            assert required in decorators, (
                f"{path} must carry {required}. Without it the endpoint is reachable "
                "unauthenticated, and these routes resume paid work or serve file content."
            )

    print(f"  ok  all {len(GUARDED_ROUTES)} guarded routes carry their decorators")
    return True


def test_the_confirmation_thresholds_reach_the_browser():
    """A stripped setting silently reverts the dialog to its defaults."""
    print("Testing settings sanitization...")

    settings = _read(SETTINGS_PY)

    backend_block = re.search(
        r"TABULAR_GENERATION_BACKEND_SETTING_KEYS\s*=\s*[\{\(\[](?P<body>.*?)[\}\)\]]",
        settings,
        re.DOTALL,
    )
    assert backend_block, "TABULAR_GENERATION_BACKEND_SETTING_KEYS should exist"
    stripped = backend_block.group("body")

    for key in CONFIRMATION_SETTING_KEYS:
        assert key in settings, f"{key} should be a known setting"
        assert f"'{key}'" not in stripped, (
            f"{key} must not be stripped by sanitize_settings_for_user. The large-run "
            "confirmation reads it from the bootstrap payload; stripping it makes the "
            "dialog fall back to its defaults and ignore the administrator's configuration."
        )
        # No sensitive term should accidentally match it either.
        for term in ("key", "secret", "password", "connection"):
            assert term not in key.lower(), (
                f"{key} contains '{term}', which sanitize_settings_for_user filters on"
            )

    estimate = _read(ESTIMATE_TS)
    for key in CONFIRMATION_SETTING_KEYS:
        assert key in estimate, f"The V2 estimate should read {key}"

    print("  ok  the confirmation thresholds survive sanitization")
    return True


def test_the_thought_frame_fields_are_carried():
    """A dropped activity payload is the difference between progress and a wall of text."""
    print("Testing thought payload contract...")

    chats = _read(CHATS_ROUTE)
    store = _read(CHAT_STORE_TS)
    types = _read(TYPES_TS)
    lanes = _read(LANES_TS)

    # serialize_thought_event sends these; the client dropped all but `content` before.
    for field in ("step_type", "detail", "activity", "progress"):
        assert f"'{field}'" in chats, f"the server should send {field} on a thought frame"
        assert field in store, (
            f"The V2 stream handler must carry {field}. Dropping it leaves a live tabular "
            "run rendered as an undifferentiated list of sentences with no progress."
        )
        assert field in types, f"ThoughtEntry/PersistedThought should declare {field}"

    # The lane keys the server emits.
    for kind in ("tabular_tool_invocation", "tabular_post_processing"):
        assert f"'{kind}'" in chats, f"the server should emit {kind}"
        assert kind in lanes, f"The V2 lane table must know about {kind}"

    assert "'tabular_analysis'" in chats, "the server should emit the tabular_analysis step type"
    assert "tabular_analysis" in lanes, "The V2 lane table must know the tabular_analysis step"

    print("  ok  the client carries every thought field the server sends")
    return True


def test_the_pieces_are_mounted():
    """A component nobody renders fixes nothing."""
    print("Testing component wiring...")

    message_list = _read(MESSAGE_LIST_TSX)
    composer = _read(COMPOSER_TSX)
    inspector = _read(INSPECTOR_TSX)
    thoughts = _read(THOUGHTS_LIST_TSX)

    assert "GeneratedArtifactCard" in message_list, (
        "The artifact card must be rendered by the message list, or a generated export "
        "still has nothing leading to it."
    )
    assert "readGeneratedArtifacts" in message_list, (
        "The message list must read the artifacts off the message metadata"
    )
    assert "ChatFilePreview" in message_list, "The chat-upload preview must be reachable"
    assert "suppressesAssistantText" in message_list, (
        "A finished durable run leaves a holding sentence that the artifacts replace"
    )
    assert "TabularRunStatus" in _read(ARTIFACT_CARD_TSX), (
        "A running export must show its progress from the card"
    )
    assert "ThoughtsProgressCard" in message_list, "The progress lane must be mounted"
    assert "buildLaneProgress" in thoughts, "The progress card must be built from the lane logic"
    assert "estimateLargeTabularRun" in composer, (
        "The large-run confirmation must be checked on the send path"
    )
    assert "LargeRunDialog" in composer, "The confirmation dialog must be rendered"
    assert "buildToolResultView" in inspector, (
        "A tabular tool result must be banded rather than dumped whole"
    )

    print("  ok  every new component is mounted")
    return True


def test_the_confirmation_precedes_the_send():
    """Confirming after sending would confirm nothing."""
    print("Testing confirmation ordering...")

    composer = _read(COMPOSER_TSX)

    submit = re.search(r"const submit = \(\) => \{(?P<body>.*?)\n    \};", composer, re.DOTALL)
    assert submit, "Could not locate the composer submit handler"
    body = submit.group("body")

    estimate_at = body.find("estimateLargeTabularRun")
    dispatch_at = body.find("dispatch(")
    assert estimate_at != -1, "submit must estimate the run"
    assert dispatch_at != -1, "submit must dispatch the message"
    assert estimate_at < dispatch_at, (
        "The estimate must be taken before the message is dispatched, or the confirmation "
        "appears after the expensive run has already started."
    )
    assert "shouldConfirm" in body and "return" in body, (
        "submit must return early when the run needs confirming"
    )

    print("  ok  the confirmation is raised before anything is sent")
    return True


def test_run_members_are_read_from_the_key_the_server_sends():
    """`artifact_set` is a summary. Reading members from it finds none, silently."""
    print("Testing run member contract...")

    exports = _read(APP_DIR / "functions_tabular_generated_exports.py")
    artifacts = _read(ARTIFACTS_TS)

    assert "'generated_artifacts':" in exports, (
        "The run status payload should carry its members under generated_artifacts"
    )
    assert "generated_artifacts" in artifacts, (
        "The V2 client must read run members from generated_artifacts. `artifact_set` is a "
        "summary carrying member_count but no member list, so reading members from it finds "
        "none and silently reduces a combined run -- which produces both an analysis summary "
        "and a structured export -- to a single card, dropping the other file."
    )
    assert "generated_artifact" in artifacts, (
        "The singular generated_artifact fallback must be read too"
    )

    # The summary fields that decide whether the set may be offered at all.
    for field in ("lifecycle_state", "validation_state"):
        assert f"'{field}'" in exports, f"artifact_set should report {field}"
        assert field in artifacts, f"The V2 client must check {field} before offering downloads"

    print("  ok  run members are read from the key the server sends")
    return True


def test_a_withheld_file_offers_no_download():
    """A staged file 403s. A visible download control would be dead and unexplained."""
    print("Testing approval gating...")

    citations = _read(CITATIONS_ROUTE)
    artifacts = _read(ARTIFACTS_TS)
    card = _read(ARTIFACT_CARD_TSX)

    assert "assert_generated_file_approval_allows_download" in citations, (
        "The download route should enforce the approval gate"
    )
    assert "approvalBlocksDownload" in artifacts, (
        "The V2 client must know when an artifact is withheld"
    )
    assert "approvalBlocksDownload" in card, (
        "The card must suppress its download control for a withheld file, rather than "
        "rendering a button the server answers with a 403 and no explanation."
    )
    assert "describeArtifactApproval" in card, (
        "The card must say why a withheld file is unavailable"
    )
    assert "resolveGeneratedFileApproval" in card, (
        "An approver must be able to release the file from the card"
    )

    # The four states the server can report.
    for state in ("pending_approval", "approved", "denied", "auto_denied"):
        assert state in artifacts, f"The V2 client must handle the {state} approval state"

    print("  ok  a withheld file offers no download and says why")
    return True


def test_the_upload_preview_is_gated_on_what_the_endpoint_supports():
    """`/api/get_file_content` is personal-only and workspace-gated."""
    print("Testing chat-upload preview gating...")

    documents = _read(DOCUMENTS_ROUTE)
    message_list = _read(MESSAGE_LIST_TSX)

    route = re.search(
        r"""route\(\s*['"]/api/get_file_content['"][^)]*\)(?P<decorators>(?:\s*@[^\n]+\n)+)""",
        documents,
    )
    assert route, "Could not locate the get_file_content decorators"
    assert '@enabled_required("enable_user_workspace")' in route.group("decorators"), (
        "get_file_content is expected to be workspace-gated; if that changed, the V2 gate "
        "below should change with it."
    )

    assert "enable_user_workspace" in message_list, (
        "The file preview control must be gated on enable_user_workspace. The endpoint 403s "
        "without it, so on a tenant with the workspace disabled the control cannot succeed."
    )
    assert "collaborative" in message_list, (
        "The file preview control must be withheld in shared conversations. "
        "get_file_content reads the personal conversations container and requires the "
        "caller to own the conversation, so a shared conversation always 404s."
    )

    print("  ok  the upload preview is offered only where it can work")
    return True


def test_no_remote_assets():
    """Browser JavaScript is served from local static assets only."""
    print("Testing local-only assets...")

    offenders = []
    for path in [
        ARTIFACTS_TS,
        LANES_TS,
        ESTIMATE_TS,
        CITATION_ROWS_TS,
        CSV_TS,
        ARTIFACT_CARD_TSX,
        RUN_STATUS_TSX,
        LARGE_RUN_TSX,
        FILE_PREVIEW_TSX,
        THOUGHTS_LIST_TSX,
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


def test_the_version_is_at_least_the_implementation_version():
    """The feature must not appear to predate the version that added it."""
    print("Testing version...")

    version = assert_app_version_at_least(
        IMPLEMENTED_IN,
        reason="V2 tabular parity landed in this version.",
    )
    print(f"  ok  config.py VERSION is {version}")
    return True


def test_the_typescript_logic_checks_pass():
    """Execute the behavioural half, skipping when the front-end toolchain is absent."""
    print("Testing tabular parity logic (TypeScript)...")

    if not (V2_DIR / "node_modules").exists():
        print("  skip  application/v2_ui/node_modules is absent; run npm install to include")
        return True

    assert LOGIC_CHECK_TS.exists(), "The TypeScript logic checks are missing"

    # functional_tests/ has no node_modules of its own, so the bundle is written where node
    # can resolve bare imports from.
    bundle = V2_DIR / "node_modules" / ".cache-tabular-parity-check.mjs"
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
                # generatedArtifacts is imported by endpoints.ts, which reaches apiClient.ts
                # and reads Vite's `import.meta.env` at module scope. Node has no such
                # object, so it is defined away here.
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


if __name__ == "__main__":
    tests = [
        test_the_client_reads_the_metadata_keys_the_server_writes,
        test_the_dedupe_key_matches_the_server,
        test_every_requested_route_exists,
        test_the_run_control_routes_are_guarded,
        test_the_confirmation_thresholds_reach_the_browser,
        test_the_thought_frame_fields_are_carried,
        test_the_pieces_are_mounted,
        test_the_confirmation_precedes_the_send,
        test_run_members_are_read_from_the_key_the_server_sends,
        test_a_withheld_file_offers_no_download,
        test_the_upload_preview_is_gated_on_what_the_endpoint_supports,
        test_no_remote_assets,
        test_the_version_is_at_least_the_implementation_version,
        test_the_typescript_logic_checks_pass,
    ]

    results = []
    for test in tests:
        try:
            results.append(test())
        except Exception as exc:  # noqa: BLE001
            print(f"FAIL  {test.__name__}: {exc}")
            import traceback

            traceback.print_exc()
            results.append(False)

    print(f"\n{sum(1 for result in results if result)}/{len(results)} test(s) passed")
    sys.exit(0 if all(results) else 1)

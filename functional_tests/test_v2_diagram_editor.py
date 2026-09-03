#!/usr/bin/env python3
"""
Functional test for the inline diagram editor.
Version: 0.261.043
Implemented in: 0.261.043

This test ensures a generated diagram can be edited in place — by source, by layout control, or
by asking the model — without the conversation filling up with near-duplicate diagrams, and
without weakening any of the guarantees that make rendering model output safe.

Two things here are load-bearing rather than cosmetic. The editor must not become a second place
that writes diagram markup to the DOM, because the single reviewed sink is what
test_v2_rich_rendering.py protects. And the classic client must resolve the same revisions the
V2 client does, or a conversation read in one interface disagrees with the other.
"""

import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
V2_SRC = REPO_ROOT / "application" / "v2_ui" / "src"
APP_DIR = REPO_ROOT / "application" / "single_app"

sys.path.insert(0, str(REPO_ROOT / "functional_tests"))
sys.path.insert(0, str(APP_DIR))

from test_support.versioning import assert_app_version_at_least  # noqa: E402

IMPLEMENTED_IN = "0.261.049"

EDITOR_TSX = V2_SRC / "components" / "chat" / "DiagramEditor.tsx"
MERMAID_TSX = V2_SRC / "components" / "chat" / "MermaidDiagram.tsx"
REVISIONS_TS = V2_SRC / "lib" / "blockRevisions.ts"
LAYOUT_TS = V2_SRC / "lib" / "mermaidLayout.ts"
ENDPOINTS_TS = V2_SRC / "lib" / "endpoints.ts"
STORE_TS = V2_SRC / "stores" / "chatStore.ts"

CLASSIC_DIAGRAMS_JS = APP_DIR / "static" / "js" / "chat" / "chat-inline-diagrams.js"
CLASSIC_MESSAGES_JS = APP_DIR / "static" / "js" / "chat" / "chat-messages.js"
ROUTES_PY = APP_DIR / "route_backend_chats.py"
COLLABORATION_PY = APP_DIR / "route_backend_collaboration.py"
STORAGE_PY = APP_DIR / "functions_message_block_revisions.py"
EXPORT_PY = APP_DIR / "route_backend_conversation_export.py"
COLLABORATION_TS = V2_SRC / "lib" / "collaboration.ts"
COLLABORATION_EVENTS_TS = V2_SRC / "lib" / "collaborationEvents.ts"


def _read(path):
    return path.read_text(encoding="utf-8", errors="ignore")


def _prose(path):
    """Read a file with whitespace collapsed, for asserting on wrapped prose."""
    return re.sub(r"\s+", " ", _read(path))


def test_version_is_at_least_the_implementing_release():
    """The feature must not appear in a build older than the one that introduced it."""
    assert_app_version_at_least(IMPLEMENTED_IN)
    print("  ok  application version is at or beyond the implementing release")


def test_the_editor_is_not_a_second_markup_sink():
    """Diagram markup still reaches the DOM in exactly one reviewed file."""
    sinks = sorted(
        path.name
        for path in (V2_SRC / "components").rglob("*.tsx")
        if "dangerously" + "SetInnerHTML" in _read(path)
    )
    assert sinks == ["MathBlock.tsx", "MermaidDiagram.tsx"], (
        f"unexpected HTML sink(s): {sinks}. The editor's preview is passed in as a render prop "
        "precisely so every component that draws diagram markup stays in one reviewed file."
    )

    editor = _read(EDITOR_TSX)
    assert "renderPreview" in editor, (
        "the editor must receive its preview already rendered rather than drawing one"
    )
    for banned in ("innerHTML", "insertAdjacentHTML", "DOMParser", "mermaid.render("):
        assert banned not in editor, f"{banned} in the editor would escape the sanitizer boundary"

    diagram = _read(MERMAID_TSX)
    assert "renderPreview={" in diagram, "the sink file must supply the preview"
    assert "DiagramPreview" in diagram, (
        "the preview component belongs in the sink file, beside the viewer"
    )
    print("  ok  the editor adds no new path for markup to reach the DOM")


def test_editing_never_rewrites_the_message():
    """The stored content is left alone, so masked range offsets stay valid."""
    storage = _read(STORAGE_PY)
    assert "resolve_block_sources_in_content" in storage, (
        "a resolver separate from the stored content is what keeps the overlay honest"
    )
    assert "masked_ranges" in storage, (
        "the reason the content is not rewritten belongs in the module that does not rewrite it"
    )

    routes = _read(ROUTES_PY)
    # Masking removes text by character offset, so it has to run first. Resolving first and
    # then cutting by offset would remove the wrong text. Checked as "a resolve follows this
    # particular mask call", because the older-message summariser resolves too and appears
    # earlier in the file.
    mask_call = routes.index("content = remove_masked_content(content, masked_ranges)")
    resolve_after_mask = routes.find(
        "content = resolve_block_sources_in_content(message, content)", mask_call
    )
    assert resolve_after_mask != -1, (
        "revisions must resolve after masking, or a mask cuts the wrong span out of a message "
        "whose diagram has been edited"
    )
    handoff = routes.find("if role in allowed_roles_in_history:", mask_call)
    assert resolve_after_mask < handoff, (
        "the resolve must happen before the message is handed to the model"
    )
    print("  ok  the message content is never rewritten, and masks still apply first")


def test_only_the_current_version_reaches_the_model():
    """The revision history and the scoped chat never enter the conversation."""
    routes = _read(ROUTES_PY)
    assert "resolve_block_sources_in_content" in routes, (
        "the history builder must substitute the current version"
    )

    assist = _read(APP_DIR / "functions_block_revision_assist.py")
    assert "conversation" in assist.lower(), "the isolation decision must be written down"
    # The assist prompt is built from the diagram alone; nothing may pull in chat history.
    assert "conversation_history" not in assist, (
        "the scoped edit request must not be handed the conversation"
    )

    storage = _prose(STORAGE_PY)
    assert "ever sent as conversation history" in storage, (
        "the sub-conversation's exclusion from history is the point of storing it on the block"
    )
    print("  ok  only the version on screen is sent, and the history behind it is not")


def test_export_resolves_the_current_version():
    """An export must not ship a diagram different from the one on screen."""
    export = _read(EXPORT_PY)
    assert "from functions_message_block_revisions import resolve_block_sources_in_content" in export
    # Both paths: the whole-conversation export and the single-message export.
    assert export.count("resolve_block_sources_in_content(message") >= 2, (
        "both the conversation export and the single-message export must resolve"
    )
    print("  ok  exports carry the current version of an edited diagram")


def test_the_classic_client_shows_the_current_version():
    """A conversation read in the classic interface must not show a stale diagram."""
    classic = _read(CLASSIC_DIAGRAMS_JS)
    assert "applyStoredDiagramRevisions" in classic, (
        "the classic renderer must resolve stored revisions"
    )
    assert "fingerprintSource" in classic, (
        "it can only find the right entry by computing the same fingerprint"
    )
    assert "0x811c9dc5" in classic and "0x01000193" in classic, (
        "the fingerprint must be the same FNV-1a the other two implementations use"
    )
    assert "sourceHash: fingerprintSource(payload)" in classic, (
        "the hash must come from the raw fence body; the normalized source strips trailing "
        "whitespace the reference implementation keeps, so the hashes would diverge"
    )

    messages = _read(CLASSIC_MESSAGES_JS)
    assert "applyStoredDiagramRevisions" in messages, "the renderer must actually call it"
    assert "blockRevisions: fullMessageObject?.metadata?.block_revisions" in messages, (
        "the stored revisions have to be threaded in from the message"
    )
    print("  ok  the classic interface resolves the same revisions V2 does")


def test_a_revision_cannot_break_out_of_its_fence():
    """A source containing a fence would inject markdown into someone else's message."""
    storage = _read(STORAGE_PY)
    assert "_FENCE_BREAKOUT_PATTERN" in storage, "the server must refuse a fence in a source"
    assert "Source cannot contain a code fence" in storage

    revisions = _read(REVISIONS_TS)
    assert "FENCE_BREAKOUT_PATTERN" in revisions, (
        "the editor should say so while it is being typed rather than only on save"
    )
    print("  ok  a source that would escape its own fence is refused on both sides")


def test_the_addressing_matches_the_colour_overrides():
    """Revisions and colours must agree about what a block is."""
    revisions = _read(REVISIONS_TS)
    assert "fingerprintSource" in revisions and "block_revisions" in revisions

    # Colours are filed under the ORIGINAL source's fingerprint. If editing re-keyed them, a
    # diagram someone recoloured would silently lose its colours the moment it was edited.
    diagram = _read(MERMAID_TSX)
    assert re.search(r"useBlockVisualStyle\('mermaid',\s*source,", diagram), (
        "colours must stay keyed to the original source, not the version being shown"
    )
    assert re.search(r"useBlockRevisions\('mermaid',\s*source,", diagram), (
        "revisions are addressed by the original source's fingerprint too"
    )
    assert "shownSource" in diagram, "the rendered source must be the resolved one"
    print("  ok  an edit does not orphan a diagram's saved colours")


def test_a_concurrent_edit_is_reported_rather_than_lost():
    """Two people editing one diagram in a shared conversation must not overwrite each other."""
    storage = _read(STORAGE_PY)
    assert "BlockRevisionConflictError" in storage
    assert "expected_revision_count" in storage

    routes = _read(ROUTES_PY)
    assert "), 409" in routes, "a conflict must be reported as a conflict"

    store = _read(STORE_TS)
    assert "error.status === 409" in store, "the client must explain a conflict in words"
    print("  ok  a concurrent edit produces a conflict rather than a silent overwrite")


def test_the_routes_are_declared_correctly():
    """Every route carries the decorators this codebase requires."""
    routes = _read(ROUTES_PY)
    for path in (
        "'/api/message/<message_id>/block-revision'",
        "'/api/message/<message_id>/block-revision/current'",
        "'/api/message/<message_id>/block-revision/assist'",
    ):
        index = routes.index(f"@bp.route({path}, methods=['POST'])")
        window = routes[index : index + 400]
        assert "@swagger_route(security=get_auth_security())" in window, f"{path} needs swagger"
        assert "@login_required" in window and "@user_required" in window, f"{path} needs auth"

    assert "_authorize_personal_conversation_access" in routes, (
        "the conversation must be authorized, which is also what admits a shared participant"
    )
    print("  ok  all three routes are authenticated and documented")


def test_positioning_is_not_promised():
    """Mermaid cannot place a node, and nothing may imply otherwise."""
    editor = _prose(EDITOR_TSX)
    assert "cannot be dragged" in editor, (
        "the layout tab must say plainly that boxes cannot be dragged, since that is the one "
        "thing people ask for that mermaid cannot express"
    )

    layout = _prose(LAYOUT_TS)
    assert "no syntax for placing a node" in layout

    assist = _prose(APP_DIR / "functions_block_revision_assist.py")
    assert "no syntax for placing a node at a coordinate" in assist, (
        "the model must be told too, or it will invent a way and produce a broken diagram"
    )
    print("  ok  node positioning is declined honestly rather than faked")


def test_the_endpoints_and_store_are_wired():
    """The client can actually reach all three operations."""
    endpoints = _read(ENDPOINTS_TS)
    for name in (
        "addMessageBlockRevision",
        "setMessageBlockRevision",
        "assistMessageBlockRevision",
    ):
        assert f"export const {name}" in endpoints, f"{name} is missing"

    store = _read(STORE_TS)
    for action in ("saveBlockRevision", "restoreBlockRevision", "askBlockRevision"):
        assert f"{action}:" in store, f"{action} is not implemented in the store"

    editor = _read(EDITOR_TSX)
    for tab in ("Source", "Layout", "Ask AI", "History"):
        assert f"label: '{tab}'" in editor, f"the {tab} tab is missing"
    print("  ok  every operation is reachable from the editor")


FINGERPRINT_PARITY_HARNESS = r'''
const fs = require('fs');

function extract(filePath, declaration, signature, replacement) {
    const source = fs.readFileSync(filePath, 'utf8');
    const start = source.indexOf(declaration);
    if (start === -1) {
        throw new Error(declaration + ' not found in ' + filePath);
    }
    const end = source.indexOf('\n}', start);
    let body = source.slice(start, end + 2).replace(declaration, 'function');
    return signature ? body.replace(signature, replacement) : body;
}

const [, , v2Path, classicPath, samplesPath] = process.argv;

const v2Fingerprint = eval(
    '(' + extract(v2Path, 'export function fingerprintSource', '(source: string): string', '(source)') + ')',
);

const classicSource = fs.readFileSync(classicPath, 'utf8');
const trimStart = classicSource.indexOf('const JS_TRIM_PATTERN');
const trimLine = classicSource.slice(trimStart, classicSource.indexOf('\n', trimStart) + 1);
const classicFingerprint = eval(
    trimLine + '\n(' + extract(classicPath, 'function fingerprintSource', null, null) + ')',
);

const samples = JSON.parse(fs.readFileSync(samplesPath, 'utf8'));
console.log(JSON.stringify(samples.map((sample) => [v2Fingerprint(sample), classicFingerprint(sample)])));
'''


def test_the_three_fingerprints_agree():
    """A revision is found by fingerprint, so all three implementations must compute the same one.

    The V2 client writes the hashes, the server verifies them and the classic client reads them.
    A disagreement does not break loudly: revisions simply stop resolving in whichever
    implementation drifted, and the interfaces quietly start showing different diagrams. The two
    JavaScript functions are read out of their source files and executed, rather than retyped
    here, so this compares what actually ships.
    """
    if shutil.which("node") is None:
        print("  --  skipped the fingerprint parity check: node is not available")
        return

    from functions_message_block_revisions import fingerprint_source

    samples = [
        "graph TD\n  A[Start] --> B[End]",
        "  graph TD\n  A --> B  \n",
        "graph TD\n  A[\"Caf\u00e9 \u2014 na\u00efve\"] --> B",
        # Astral characters are two UTF-16 code units, which a naive Python port gets wrong.
        "graph TD\n  A[\"\U0001F600 emoji\"] --> B[\"\U0001F680\"]",
        "graph TD\n  A[\"\u4e2d\u6587\"] --> B",
        "",
        # A byte order mark: JavaScript's trim removes it, Python's str.strip does not.
        "\ufeffgraph TD\n  A --> B\ufeff",
        "graph TD\r\n  A --> B\r\n",
        # Trailing whitespace on an interior line, which is why the classic client hashes the
        # raw fence body rather than its normalized source.
        "graph TD  \n  A --> B\t\n  B --> C",
    ]

    workspace = tempfile.mkdtemp(prefix="fingerprint-parity-")
    try:
        harness = Path(workspace) / "harness.js"
        sample_file = Path(workspace) / "samples.json"
        harness.write_text(FINGERPRINT_PARITY_HARNESS, encoding="utf-8")
        sample_file.write_text(json.dumps(samples), encoding="utf-8")

        completed = subprocess.run(
            [
                "node",
                str(harness),
                str(V2_SRC / "lib" / "visualPalettes.ts"),
                str(CLASSIC_DIAGRAMS_JS),
                str(sample_file),
            ],
            capture_output=True,
            text=True,
            timeout=60,
            shell=(sys.platform == "win32"),
        )
    finally:
        shutil.rmtree(workspace, ignore_errors=True)

    assert completed.returncode == 0, f"the parity harness failed: {completed.stderr}"

    results = json.loads(completed.stdout)
    assert len(results) == len(samples)
    for sample, (v2_hash, classic_hash) in zip(samples, results):
        python_hash = fingerprint_source(sample)
        label = sample.encode("unicode_escape").decode("ascii")
        assert v2_hash == classic_hash, (
            f"V2 and classic disagree for {label!r}: {v2_hash} vs {classic_hash}"
        )
        assert v2_hash == python_hash, (
            f"the server disagrees for {label!r}: {v2_hash} vs {python_hash}"
        )

    print(f"  ok  all three fingerprints agree across {len(samples)} samples")


def test_a_shared_conversation_can_be_edited():
    """A shared conversation's diagrams must be editable, not answer "Conversation not found".

    Shared conversations live in different Cosmos containers and are served by
    `/api/collaboration/*`. Sending a shared conversation id to the personal block-revision
    route reads the personal container, finds nothing, and reports the conversation as missing —
    which is what the first cut of this feature did for every shared thread.
    """
    collaboration = _read(COLLABORATION_PY)

    for path in (
        "/messages/<message_id>/block-revision'",
        "/messages/<message_id>/block-revision/current'",
        "/messages/<message_id>/block-revision/assist'",
    ):
        assert path in collaboration, f"the shared counterpart of {path} is missing"

    # Authorization is the collaboration one, not personal ownership: a participant is not the
    # owner of the source conversation and would fail a plain ownership comparison.
    assert "assert_user_can_participate_in_collaboration_conversation" in collaboration, (
        "shared edits must authorize participation rather than ownership"
    )
    assert "_authorize_personal_conversation_access" not in collaboration, (
        "the personal ownership check would reject every participant"
    )

    # The shared routes must read and write the collaboration containers.
    assert "get_collaboration_message(message_id)" in collaboration
    assert "cosmos_collaboration_messages_container.upsert_item" in collaboration

    # And they must reuse the storage rules rather than reimplementing them, so the two
    # families cannot drift on caps, pruning or fence-breakout refusal.
    assert "from functions_message_block_revisions import" in collaboration
    assert "apply_block_revision" in collaboration and "set_current_revision" in collaboration

    print("  ok  shared conversations have their own authorized block revision routes")


def test_a_shared_edit_reaches_the_model():
    """A shared message is a mirror, so an edit has to be written through to its source.

    The shared AI request is delegated to the personal chat path with the *source* conversation
    id, and the history builder reads the personal container. An edit stored only on the shared
    mirror would be visible to whoever is reading the shared thread while the model, the export
    and the conversation owner all continued to see the original diagram.
    """
    collaboration = _read(COLLABORATION_PY)

    assert "_sync_collaboration_block_revisions_to_source" in collaboration, (
        "a shared edit must be mirrored onto the source message"
    )
    # Called on every write path, not just one of them.
    assert collaboration.count("_sync_collaboration_block_revisions_to_source(message_doc)") >= 1
    assert "_save_collaboration_block_revisions" in collaboration, (
        "the write, the source sync and the broadcast belong together so a route cannot skip one"
    )
    assert collaboration.count("_save_collaboration_block_revisions(") >= 4, (
        "every shared block revision route must go through the shared save helper"
    )

    # The sync mirrors the same metadata key the resolver reads.
    assert "BLOCK_REVISIONS_METADATA_KEY" in collaboration

    # The delegation this relies on: the shared stream runs the personal chat path against the
    # source conversation, which is where the resolver already runs.
    assert "'conversation_id': source_conversation_id" in collaboration, (
        "if the shared stream stopped delegating to the source conversation, syncing revisions "
        "there would no longer put them in front of the model"
    )

    print("  ok  a shared edit is mirrored to the source, so the model sees the current version")


def test_the_client_picks_the_right_endpoint_family():
    """The client must branch on conversation kind rather than trying one and falling back."""
    store = _read(STORE_TS)

    # Each action's text is bounded by the start of the next one rather than by a fixed window.
    # A generous window overlaps the following action, so a branch deleted from one would be
    # satisfied by its neighbour's and the regression would go unnoticed.
    starts = {
        action: store.index(f"{action}: async ({{")
        for action in ("saveBlockRevision", "restoreBlockRevision", "askBlockRevision")
    }
    boundaries = sorted(starts.values()) + [store.index("mergeBlockRevisions:", max(starts.values()))]

    for action, start in starts.items():
        end = next(boundary for boundary in boundaries if boundary > start)
        body = store[start:end]
        assert "isSharedBlockRevision(get(), conversationId, conversationKind)" in body, (
            f"{action} must choose its endpoint from the kind captured when the edit was made"
        )
        assert "conversation_id: conversationId" in body, (
            f"{action} must still send the conversation id on the personal route"
        )

    # The kind is captured with the id rather than resolved at write time, because the rail row
    # a late lookup would consult may no longer describe the conversation the edit belongs to.
    # `blockVisualStyle.ts` carries it for the same reason; this keeps the two consistent.
    assert "conversationKind === null" in store, (
        "a captured kind must win over a lookup, with the lookup only as a fallback"
    )
    revisions = _read(REVISIONS_TS)
    assert "activeConversationKind" in revisions, (
        "the hook must capture the conversation's kind when the edit is made"
    )

    collaboration = _read(COLLABORATION_TS)
    for name in (
        "addCollaborationBlockRevision",
        "setCollaborationBlockRevision",
        "assistCollaborationBlockRevision",
    ):
        assert f"export const {name}" in collaboration, f"{name} is missing"
        assert name in store, f"{name} is never called"

    print("  ok  the client sends a shared conversation to the collaboration routes")


def test_a_shared_edit_is_broadcast_to_the_other_readers():
    """Editing a shared diagram changes what everyone sees, so everyone should be told."""
    collaboration = _read(COLLABORATION_PY)
    assert "'collaboration.message.block_revised'" in collaboration, (
        "a shared edit must be published to the conversation's event stream"
    )

    events = _read(COLLABORATION_EVENTS_TS)
    assert "collaboration.message.block_revised" in events, "the client must handle the event"
    assert "onMessageBlockRevised" in events

    store = _read(STORE_TS)
    assert "onMessageBlockRevised:" in store, "the thread must apply the broadcast"
    # Only the revision map is replaced; replacing the whole message would clobber local state.
    index = store.index("onMessageBlockRevised:")
    window = store[index : index + 1200]
    assert "block_revisions: blockRevisions" in window

    print("  ok  a shared edit reaches the other participants live")


def test_the_typescript_logic_checks_pass():
    """Run the bundled behaviour checks, when the front-end toolchain is installed."""
    ui_dir = REPO_ROOT / "application" / "v2_ui"
    check = Path(__file__).with_name("test_v2_diagram_editor_logic.ts")

    assert check.exists(), "the logic check file is missing"

    if not (ui_dir / "node_modules").exists():
        print("  --  skipped the TypeScript checks: run npm install in application/v2_ui")
        return

    bundle = ui_dir / "node_modules" / ".cache-diagram-editor-check.mjs"
    try:
        subprocess.run(
            [
                "npx",
                "esbuild",
                str(check),
                "--bundle",
                "--platform=node",
                "--format=esm",
                "--packages=external",
                f"--outfile={bundle}",
                "--log-level=error",
            ],
            cwd=str(ui_dir),
            check=True,
            shell=(sys.platform == "win32"),
        )
        result = subprocess.run(
            ["node", str(bundle)],
            cwd=str(ui_dir),
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
    assert passed > 30, f"expected the full check suite, saw {passed} checks"
    print(f"  ok  {passed} TypeScript logic checks passed")


TESTS = [
    test_version_is_at_least_the_implementing_release,
    test_the_editor_is_not_a_second_markup_sink,
    test_editing_never_rewrites_the_message,
    test_only_the_current_version_reaches_the_model,
    test_export_resolves_the_current_version,
    test_the_classic_client_shows_the_current_version,
    test_a_revision_cannot_break_out_of_its_fence,
    test_the_addressing_matches_the_colour_overrides,
    test_a_concurrent_edit_is_reported_rather_than_lost,
    test_the_routes_are_declared_correctly,
    test_positioning_is_not_promised,
    test_the_endpoints_and_store_are_wired,
    test_a_shared_conversation_can_be_edited,
    test_a_shared_edit_reaches_the_model,
    test_the_client_picks_the_right_endpoint_family,
    test_a_shared_edit_is_broadcast_to_the_other_readers,
    test_the_three_fingerprints_agree,
    test_the_typescript_logic_checks_pass,
]


if __name__ == "__main__":
    failures = 0
    for test in TESTS:
        try:
            test()
        except Exception as exc:  # noqa: BLE001 - surface any failure with a traceback
            failures += 1
            print(f"FAIL  {test.__name__}: {exc}")
            import traceback

            traceback.print_exc()

    total = len(TESTS)
    print(f"\n{total - failures}/{total} checks passed")
    sys.exit(0 if failures == 0 else 1)

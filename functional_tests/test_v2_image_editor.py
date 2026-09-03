#!/usr/bin/env python3
"""
Functional test for the inline image editor.
Version: 0.261.058
Implemented in: 0.261.058

This test ensures a generated image can be changed in place — by asking the model, by rewriting
its prompt, or by changing how it is rendered — without the conversation filling up with
near-duplicate images, and that the wiring around it holds.

Three things here are load-bearing rather than cosmetic.

The message's own content is never rewritten, exactly as for diagrams. The revision travels in
metadata and the image is served from a URL carrying the revision id, which is the only reason
an edit becomes visible at all: `/api/image/<id>` is otherwise identical before and after, and
is served with a long cache.

Region editing is offered only where `/images/edits` exists. DALL-E 3 has no such endpoint, and
an APIM deployment records no model name, so both fall back to whole-image regeneration and say
so rather than failing after a reader has selected a region and waited.

And every route carries the swagger decorator the repository requires, including the shared
counterparts, which are what make an image editable in a conversation somebody else owns.
"""

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
V2_SRC = REPO_ROOT / "application" / "v2_ui" / "src"
APP_DIR = REPO_ROOT / "application" / "single_app"

sys.path.insert(0, str(REPO_ROOT / "functional_tests"))
sys.path.insert(0, str(APP_DIR))

from test_support.versioning import assert_app_version_at_least  # noqa: E402

IMPLEMENTED_IN = "0.261.058"

EDITOR_TSX = V2_SRC / "components" / "chat" / "ImageEditor.tsx"
MASK_TSX = V2_SRC / "components" / "chat" / "ImageMaskCanvas.tsx"
MASK_TS = V2_SRC / "lib" / "imageMask.ts"
REVISIONS_TS = V2_SRC / "lib" / "imageRevisions.ts"
IMAGES_TS = V2_SRC / "lib" / "images.ts"
ENDPOINTS_TS = V2_SRC / "lib" / "endpoints.ts"
COLLABORATION_TS = V2_SRC / "lib" / "collaboration.ts"
COLLABORATION_EVENTS_TS = V2_SRC / "lib" / "collaborationEvents.ts"
STORE_TS = V2_SRC / "stores" / "chatStore.ts"
MESSAGE_LIST_TSX = V2_SRC / "components" / "chat" / "MessageList.tsx"

STORAGE_PY = APP_DIR / "functions_message_image_revisions.py"
EDIT_PY = APP_DIR / "functions_image_edit.py"
ROUTES_PY = APP_DIR / "route_backend_chats.py"
COLLABORATION_PY = APP_DIR / "route_backend_collaboration.py"
CONVERSATIONS_PY = APP_DIR / "route_backend_conversations.py"
IMAGE_MESSAGES_PY = APP_DIR / "functions_image_messages.py"
COLLABORATION_FUNCS_PY = APP_DIR / "functions_collaboration.py"
BOOTSTRAP_PY = APP_DIR / "route_backend_v2.py"


def _read(path):
    return path.read_text(encoding="utf-8", errors="ignore")


def _prose(path):
    """Read a file with whitespace collapsed, for asserting on wrapped prose."""
    return re.sub(r"\s+", " ", _read(path))


def test_version_is_at_least_the_implementing_release():
    """The feature must not appear in a build older than the one that introduced it."""
    assert_app_version_at_least(IMPLEMENTED_IN)
    print("  ok  application version is at or beyond the implementing release")


def test_the_editor_adds_no_markup_sink():
    """Adding an image editor must not add a second place untrusted markup reaches the DOM."""
    sinks = sorted(
        path.name
        for path in (V2_SRC / "components").rglob("*.tsx")
        if "dangerously" + "SetInnerHTML" in _read(path)
    )
    assert sinks == ["MathBlock.tsx", "MermaidDiagram.tsx"], (
        f"unexpected HTML sink(s): {sinks}"
    )

    for path in (EDITOR_TSX, MASK_TSX):
        body = _read(path)
        for banned in ("innerHTML", "insertAdjacentHTML", "DOMParser"):
            assert banned not in body, f"{banned} in {path.name} would escape the sanitizer boundary"
    print("  ok  the image editor introduces no new HTML sink")


def test_editing_never_rewrites_the_message():
    """The revision is an overlay; the message keeps the image it was generated with."""
    storage = _prose(STORAGE_PY)
    assert "IMAGE_REVISIONS_METADATA_KEY = 'image_revisions'" in _read(STORAGE_PY)
    assert "Revision zero stores no bytes" in storage, (
        "the original must remain the message's own content rather than being copied"
    )

    routes = _read(ROUTES_PY)
    for handler in ("def add_message_image_revision_api", "def set_message_image_revision_api"):
        index = routes.index(handler)
        window = routes[index : index + 4500]
        for assignment in ("message_doc['content']", 'message_doc["content"]'):
            assert f"{assignment} =" not in window, (
                f"{handler} assigns to the message's content; the revision is an overlay and "
                "the stored image must stay recoverable"
            )
    print("  ok  a revision is stored beside the image rather than replacing it")


def test_an_edit_changes_the_url_so_a_cached_image_is_not_shown():
    """Without this the reader keeps seeing the image they just replaced."""
    storage = _prose(STORAGE_PY)
    assert "rev=" in _read(STORAGE_PY), "the resolved content must carry the revision id"
    assert "Cache-Control" in storage or "cache" in storage.lower()

    # Both serve routes resolve the parameter, personal and shared.
    for path, name in ((CONVERSATIONS_PY, "personal"), (COLLABORATION_PY, "collaboration")):
        body = _read(path)
        assert "resolve_served_revision" in body, f"the {name} image route ignores revisions"
        assert "request.args.get('rev')" in body, f"the {name} image route ignores the rev parameter"
        assert "immutable" in body, (
            f"the {name} route should cache a revision-addressed URL hard, since it cannot change"
        )

    # And the shared URL builder stamps it too, or the mirror would serve a stale image.
    collaboration = _read(COLLABORATION_FUNCS_PY)
    assert "resolve_image_message_content" in collaboration, (
        "build_collaboration_image_url must carry the revision"
    )
    print("  ok  an edited image is addressed by revision on both serve paths")


def test_storage_detail_never_reaches_the_browser():
    """Blob containers and paths are not something a client needs or should see.

    A blob path spells out the owner's user id and the source conversation id as well as the
    container, so every reader that returns a message has to go through the public shape. The
    collaboration metadata payload is the one that matters most: it is served to any viewer of a
    shared conversation, including a pending invitee.
    """
    storage = _read(STORAGE_PY)
    index = storage.index("def serialize_image_revisions")
    window = storage[index : index + 3000]
    assert "'blob_container'" not in window and "'blob_path'" not in window, (
        "the public shape must not carry storage locations"
    )

    # Every path that hands a message to a client.
    assert "serialize_image_revisions" in _read(IMAGE_MESSAGES_PY), (
        "hydration must publicise the stored entry before it is sent"
    )

    collaboration = _read(COLLABORATION_FUNCS_PY)
    assert collaboration.count("_publicize_image_revisions(") >= 2, (
        "both the message serializer and the metadata payload builder must publicise the entry; "
        "the metadata payload is returned verbatim to every viewer of a shared conversation"
    )
    index = collaboration.index("def build_collaboration_message_metadata_payload")
    window = collaboration[index : index + 800]
    assert "_publicize_image_revisions(" in window, (
        "build_collaboration_message_metadata_payload merges the source message's raw metadata, "
        "which carries the blob path"
    )

    metadata_route = _read(APP_DIR / "route_frontend_conversations.py")
    assert "publicize_message_image_revisions" in metadata_route, (
        "the per-message metadata route returns an image document verbatim"
    )
    print("  ok  every path to the browser reduces the entry to its public shape")


def test_every_route_carries_the_swagger_decorator():
    """Required of all routes in this repository, with no exceptions."""
    for path in (ROUTES_PY, COLLABORATION_PY):
        body = _read(path)
        for match in re.finditer(r"@bp\.route\(\s*\n?\s*'([^']*image-revision[^']*)'", body):
            window = body[match.end() : match.end() + 400]
            assert "@swagger_route(security=get_auth_security())" in window, (
                f"{match.group(1)} is missing the swagger decorator"
            )
            assert "@login_required" in window and "@user_required" in window, (
                f"{match.group(1)} is missing an authentication decorator"
            )

    routes = _read(ROUTES_PY)
    for endpoint in ("/image-revision'", "/image-revision/current'"):
        assert endpoint in routes, f"the personal {endpoint} route is missing"

    collaboration = _read(COLLABORATION_PY)
    for endpoint in ("/image-revision'", "/image-revision/current'"):
        assert endpoint in collaboration, f"the shared {endpoint} route is missing"
    print("  ok  all four routes carry the swagger and authentication decorators")


def test_there_is_no_assist_route_because_a_browser_cannot_author_an_image():
    """The diagram trio collapses to a pair here, and that should be deliberate."""
    for path in (ROUTES_PY, COLLABORATION_PY):
        assert "image-revision/assist" not in _read(path), (
            "an image assist route would duplicate the revision route: every image version "
            "already comes from the model"
        )
    assert "cannot author" in _prose(ROUTES_PY), (
        "the personal route should say why there is no assist counterpart"
    )
    assert "cannot author an image" in _prose(COLLABORATION_PY), (
        "the shared route should say the same"
    )
    print("  ok  creating and asking are one route, and the reason is written down")


def test_a_shared_edit_is_written_through_to_the_source():
    """A shared image is a mirror; its bytes and its history live on the source message."""
    collaboration = _prose(COLLABORATION_PY)
    assert "_load_collaboration_image_revision_message" in collaboration
    assert "_save_collaboration_image_revisions" in collaboration
    assert "cosmos_messages_container.upsert_item(source_doc)" in _read(COLLABORATION_PY), (
        "the authoritative source message must be written"
    )
    assert "assert_user_can_participate_in_collaboration_conversation" in _read(COLLABORATION_PY)
    assert "participate" in collaboration.lower(), (
        "a pending invitee may view a shared image but must not change it"
    )

    # And the other participants are told, or they keep showing the previous image.
    assert "collaboration.message.image_revised" in _read(COLLABORATION_PY)
    assert "collaboration.message.image_revised" in _read(COLLABORATION_EVENTS_TS)
    store = _prose(STORE_TS)
    assert "onMessageImageRevised" in store
    index = store.index("onMessageImageRevised:")
    window = store[index : index + 900]
    assert "image_revisions: imageRevisions" in window
    assert "content: imageUrl" in window, (
        "the broadcast must replace the URL as well as the history, or a participant keeps "
        "showing the copy already in their cache"
    )
    print("  ok  a shared edit reaches the source message and the other participants")


def test_capability_is_reported_rather_than_discovered_by_failing():
    """A reader should be told up front, not after selecting a region and waiting."""
    edit = _read(EDIT_PY)
    assert "dall-e-2" in edit and "gpt-image" in edit
    assert "MIN_IMAGE_EDIT_API_VERSION = '2025-04-01-preview'" in edit
    assert "resolve_image_edit_capability" in _read(BOOTSTRAP_PY), (
        "the capability must reach the client through the bootstrap payload"
    )

    bootstrap = _prose(BOOTSTRAP_PY)
    assert '"capabilities"' in _read(BOOTSTRAP_PY)
    assert "enable_" in bootstrap and "documentation inventory" in bootstrap, (
        "the reason it is not a feature flag should be written down: an invented enable_* key "
        "would look like a settings key to everything that reads the application surface"
    )

    # And the editor actually branches on it rather than always offering a mask.
    editor = _read(EDITOR_TSX)
    assert "capability.mode === 'masked'" in editor
    assert "capability.reason" in editor, "the reason must be shown, not swallowed"
    print("  ok  capability is resolved server-side and surfaced before any work is done")


def test_the_mask_is_built_at_the_image_natural_size():
    """The API requires the mask and the image to have identical pixel dimensions."""
    mask = _read(MASK_TS)
    assert "destination-out" in mask, (
        "the selection must be erased out of an opaque canvas, which produces "
        "transparent-means-edit by construction rather than by remembering to invert"
    )
    assert "fillRect(0, 0, canvas.width, canvas.height)" in mask, (
        "the canvas must start fully opaque, or nothing is preserved"
    )

    canvas = _read(MASK_TSX)
    assert "naturalWidth" in canvas and "naturalHeight" in canvas, (
        "the laid-out size is not the image's size, and a mismatched mask is rejected"
    )
    assert "pointerToImagePoint" in canvas, (
        "the pointer must be mapped through the drawn picture. Mapping through the element box "
        "compresses every coordinate whenever the image is letterboxed, so the mask covers the "
        "wrong region and the model edits the wrong part of the image on a paid call"
    )
    # Comments are stripped first: the reason letterboxing is avoided is written down in one,
    # and asserting on the raw file would read that explanation as the thing it warns about.
    markup = "\n".join(
        line for line in canvas.splitlines() if not line.strip().startswith("//")
    )
    assert "object-contain" not in markup, (
        "the wrapper shrink-wraps the image so the element box is the picture; letterboxing "
        "would put the overlay and the region grid out of step with what the reader sees"
    )
    print("  ok  the mask is rendered at natural size with the polarity built in")


def test_masking_is_not_mouse_only():
    """A feature reachable only with a pointer is one some readers cannot use at all."""
    mask = _read(MASK_TS)
    assert "MASK_REGION_KEYS" in mask and "maskRegionRect" in mask

    canvas = _read(MASK_TSX)
    assert "aria-pressed" in canvas, "the region toggles must report their state"
    assert "MASK_REGION_LABELS[region]" in canvas, "each region needs an announced name"
    assert "sr-only" in canvas, "the grid buttons need accessible names"
    print("  ok  a keyboard-operable region grid produces the same selection a drag would")


def test_the_honest_limitations_are_stated_in_the_interface():
    """A mask guides the model; it is not a pixel clamp, and pretending otherwise misleads."""
    editor = _prose(EDITOR_TSX)
    assert "not strictly bound" in editor or "can still shift" in editor, (
        "the interface must say that areas outside the selection can still change"
    )
    assert "whole image is reworked" in editor or "whole image" in editor
    print("  ok  the editor states what a mask does and does not guarantee")


def test_shared_images_resolve_in_the_client():
    """Editing a shared image is pointless if the shared image never renders."""
    images = _read(IMAGES_TS)
    assert "collaboration/conversations" in images, (
        "a shared image's content is a collaboration path, which the resolver must recognise"
    )
    assert "imageEndpointBase" in images, (
        "the history needs the endpoint without its revision parameter, or every thumbnail "
        "resolves to the same cached image"
    )
    print("  ok  a shared conversation's images resolve, and versions are addressable")


def test_the_editor_is_reachable_from_where_an_image_is_shown():
    """An entry point in the thread, in the lightbox, and on an approved proposal card."""
    message_list = _read(MESSAGE_LIST_TSX)
    assert "ImageEditor" in message_list and "useImageRevisions" in message_list
    assert "is_user_upload" in message_list, (
        "editing is offered for generated images only; a user's own upload is out of scope"
    )

    proposal = _read(V2_SRC / "components" / "chat" / "InlineImageProposal.tsx")
    assert "ImageEditor" in proposal, "an approved proposal's image should be editable too"

    lightbox = _read(V2_SRC / "components" / "chat" / "ImageLightbox.tsx")
    assert "onEdit" in lightbox
    print("  ok  the editor is reachable from the thread, the viewer and a proposal card")


def test_endpoints_are_bound_where_the_repository_keeps_them():
    """Personal calls in endpoints.ts, shared calls in collaboration.ts."""
    endpoints = _read(ENDPOINTS_TS)
    assert "addMessageImageRevision" in endpoints and "setMessageImageRevision" in endpoints
    assert "addCollaborationImageRevision" not in endpoints, (
        "shared bindings belong beside the other /api/collaboration/* calls"
    )

    collaboration = _read(COLLABORATION_TS)
    assert "addCollaborationImageRevision" in collaboration
    assert "setCollaborationImageRevision" in collaboration

    store = _read(STORE_TS)
    assert "isSharedBlockRevision(get(), conversationId, conversationKind)" in store
    index = store.index("reviseImage: async")
    window = store[index : index + 2600]
    assert "addCollaborationImageRevision" in window and "addMessageImageRevisionApi" in window, (
        "the endpoint must be chosen from the conversation's kind rather than tried and "
        "fallen back from"
    )
    print("  ok  endpoints live where the repository keeps them and are chosen by kind")


def test_the_typescript_logic_checks_pass():
    """Run the bundled behaviour checks, when the front-end toolchain is installed."""
    ui_dir = REPO_ROOT / "application" / "v2_ui"
    check = Path(__file__).with_name("test_v2_image_mask_logic.ts")

    assert check.exists(), "the logic check file is missing"

    if not (ui_dir / "node_modules").exists():
        print("  --  skipped the TypeScript checks: run npm install in application/v2_ui")
        return

    bundle = ui_dir / "node_modules" / ".cache-image-mask-check.mjs"
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
    assert passed >= 15, f"expected the full check suite, saw {passed} checks"
    print(f"  ok  {passed} TypeScript logic checks passed")


TESTS = [
    test_version_is_at_least_the_implementing_release,
    test_the_editor_adds_no_markup_sink,
    test_editing_never_rewrites_the_message,
    test_an_edit_changes_the_url_so_a_cached_image_is_not_shown,
    test_storage_detail_never_reaches_the_browser,
    test_every_route_carries_the_swagger_decorator,
    test_there_is_no_assist_route_because_a_browser_cannot_author_an_image,
    test_a_shared_edit_is_written_through_to_the_source,
    test_capability_is_reported_rather_than_discovered_by_failing,
    test_the_mask_is_built_at_the_image_natural_size,
    test_masking_is_not_mouse_only,
    test_the_honest_limitations_are_stated_in_the_interface,
    test_shared_images_resolve_in_the_client,
    test_the_editor_is_reachable_from_where_an_image_is_shown,
    test_endpoints_are_bound_where_the_repository_keeps_them,
    test_the_typescript_logic_checks_pass,
]


if __name__ == "__main__":
    failures = 0
    for test in TESTS:
        print(f"\n{test.__name__}")
        try:
            test()
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"  FAIL  {exc}")
            import traceback

            traceback.print_exc()

    print(f"\n{len(TESTS) - failures}/{len(TESTS)} passed")
    sys.exit(1 if failures else 0)

#!/usr/bin/env python3
"""
Functional test for the V2 generated-image lightbox.

Version: 0.261.025
Implemented in: 0.261.025

Clicking a generated image in the V2 chat view used to leave the app. `ImageMessage` wrapped
the thumbnail in an `<a target="_blank">`, so the browser opened the raw image in a new tab.
The classic chat view has never done that -- `chat-citations.js` catches clicks on
`.generated-image` and opens a modal -- so V2 was the odd one out.

It was also broken outright for a whole class of images. `resolveImageSource` returns a
`data:image/...` URI for small inline images, and browsers block top-level navigation to a
data URL, so for those messages clicking the image did nothing at all.

This test ensures the thumbnail opens an in-page dialog instead of navigating away, that the
dialog still offers everything the new tab did (save the file, open the raw image, view it at
actual size), and that each of the three source kinds `resolveImageSource` can return is
handled deliberately rather than assumed to behave like a plain URL.
"""

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
V2_SRC = REPO_ROOT / "application" / "v2_ui" / "src"

sys.path.insert(0, str(REPO_ROOT / "functional_tests"))

from test_support.versioning import assert_app_version_at_least  # noqa: E402

MESSAGE_LIST = V2_SRC / "components" / "chat" / "MessageList.tsx"
LIGHTBOX = V2_SRC / "components" / "chat" / "ImageLightbox.tsx"
IMAGES_LIB = V2_SRC / "lib" / "images.ts"
ENDPOINTS_LIB = V2_SRC / "lib" / "endpoints.ts"
API_CLIENT = V2_SRC / "lib" / "apiClient.ts"


def _read(path):
    return path.read_text(encoding="utf-8")


def _image_message_body():
    """The body of ImageMessage, up to the next top-level function."""
    source = _read(MESSAGE_LIST)
    match = re.search(
        r"function ImageMessage\(.*?\n(?=function |export function )",
        source,
        re.DOTALL,
    )
    assert match, "ImageMessage could not be located in MessageList.tsx"
    return match.group(0)


def test_thumbnail_opens_a_dialog_rather_than_a_new_tab():
    """The click must stay in the app."""
    print("Testing that the thumbnail no longer navigates away...")

    body = _image_message_body()

    assert 'target="_blank"' not in body, (
        "ImageMessage still opens the image in a new tab; it should open the lightbox"
    )
    assert "<a" not in body.replace("<article", ""), (
        "The image thumbnail should not be an anchor at all -- it opens a dialog, "
        "not a document"
    )

    # A button keeps the thumbnail reachable and operable from the keyboard, which a bare
    # clickable <img> would not be.
    assert re.search(r"<button\s+type=\"button\"\s+onClick=\{\(\) => setLightboxOpen\(true\)\}", body), (
        "The thumbnail must be a real button that opens the lightbox"
    )
    assert 'aria-haspopup="dialog"' in body, (
        "The thumbnail should announce that it opens a dialog"
    )
    assert "<ImageLightbox" in body and "onClose={() => setLightboxOpen(false)}" in body, (
        "ImageMessage must render the lightbox and be able to close it"
    )

    assert "import { ImageLightbox } from './ImageLightbox';" in _read(MESSAGE_LIST), (
        "MessageList must import the lightbox component"
    )

    print("Thumbnail test passed!")
    return True


def test_broken_image_fallback_survives():
    """The existing fallback must not have been lost in the rewrite."""
    print("Testing the broken-image fallback...")

    body = _image_message_body()

    assert "onError={() => setFailed(true)}" in body, (
        "A failed image load must still be caught"
    )
    assert "if (!source || failed)" in body, (
        "An unreadable or broken image must still fall back to the prompt text"
    )

    # The fallback returns early, so every hook has to run before it or React's hook order
    # breaks on the render where an image fails.
    hooks_then_return = re.search(
        r"const naming = useMemo\((.|\n)*?if \(!source \|\| failed\) \{",
        body,
    )
    assert hooks_then_return, (
        "Hooks must be declared before the early return, or hook order changes when an "
        "image fails to load"
    )

    print("Fallback test passed!")
    return True


def test_dialog_follows_the_existing_modal_conventions():
    """A dialog nobody can dismiss is worse than a new tab."""
    print("Testing dialog semantics...")

    assert LIGHTBOX.exists(), "ImageLightbox.tsx should hold the viewer"
    lightbox = _read(LIGHTBOX)

    assert 'role="dialog"' in lightbox and 'aria-modal="true"' in lightbox, (
        "The lightbox must be announced as a modal dialog"
    )
    assert re.search(r"event\.key === 'Escape'(.|\n)*?onClose\(\)", lightbox), (
        "Escape must dismiss the lightbox, as it does for every other dialog in this UI"
    )
    assert re.search(r"absolute inset-0(.|\n)*?onClick=\{onClose\}", lightbox), (
        "Clicking the backdrop must dismiss the lightbox"
    )
    assert "document.removeEventListener('keydown', onKeyDown)" in lightbox, (
        "The Escape listener must be torn down, or it accumulates on every open"
    )

    # Focus should enter the dialog and be handed back on close.
    assert "closeRef.current?.focus()" in lightbox, (
        "Opening the dialog must move focus into it"
    )
    assert "previous?.focus?.()" in lightbox, (
        "Closing the dialog must return focus to the thumbnail that opened it"
    )

    print("Dialog semantics test passed!")
    return True


def test_the_new_tab_actions_are_still_available():
    """Nothing the new tab offered may be lost by keeping the user in the app."""
    print("Testing lightbox actions...")

    lightbox = _read(LIGHTBOX)

    assert "downloadImageSource" in lightbox, "The lightbox must be able to save the image"
    assert "openImageInNewTab" in lightbox, (
        "Opening the raw image must still be reachable, since the click no longer does it"
    )

    # Fit versus actual size, toggled from the header and by clicking the image.
    assert "type ZoomMode = 'fit' | 'actual'" in lightbox, (
        "The viewer needs an explicit fit/actual-size mode"
    )
    assert lightbox.count("setZoom(fit ? 'actual' : 'fit')") >= 2, (
        "Both the header control and the image itself should toggle the zoom"
    )
    assert "object-contain" in lightbox and "max-w-none" in lightbox, (
        "Fit must constrain the image and actual size must not"
    )
    assert "overflow-auto" in lightbox, (
        "An image shown at actual size must be scrollable, or its edges are unreachable"
    )
    assert 'aria-pressed={!fit}' in lightbox, (
        "The zoom toggle must report its state to assistive technology"
    )

    # Every failure path says something rather than doing nothing visible.
    assert "toast.error" in lightbox, "A failed action must be reported"

    print("Lightbox actions test passed!")
    return True


def test_every_image_source_kind_is_handled():
    """resolveImageSource returns three kinds and none of them behaves like the others."""
    print("Testing source-kind coverage...")

    images = _read(IMAGES_LIB)

    for kind in ("data-uri", "endpoint", "external"):
        assert f"'{kind}'" in images, f"The {kind} source kind is unhandled"

    # A data URI cannot be navigated to at the top level, so it is republished as an object
    # URL. Getting this wrong is the silent failure that prompted the change.
    assert re.search(
        r"openImageInNewTab(.|\n)*?source\.kind === 'data-uri'\s*\?\s*objectUrlForDataUri",
        images,
    ), (
        "A data URI must be opened through an object URL; browsers block top-level "
        "navigation to data: URLs"
    )
    assert "revokeObjectURL" in images, (
        "The object URL must be released, or its bytes are held for the life of the page"
    )

    # `window.open` returns null when `noopener` is passed in the feature string, even on
    # success, which would make every opened tab look blocked. The opener is severed by
    # assignment instead so the return value stays meaningful.
    assert not re.search(r"window\.open\([^)]*noopener", images), (
        "`noopener` in the window.open feature string makes it return null even on "
        "success; sever the opener by assignment instead"
    )
    assert "opened.opener = null" in images, (
        "The new tab must not keep a handle back to the app"
    )

    # The authenticated endpoint needs the client's credentials mode, or the split-origin
    # deployment gets a 401 on the download.
    assert re.search(
        r"source\.kind === 'endpoint' \? \{ credentials: CREDENTIALS_MODE \}",
        images,
    ), "The authenticated image endpoint must be fetched with the client's credentials mode"
    assert "export const CREDENTIALS_MODE" in _read(API_CLIENT), (
        "CREDENTIALS_MODE must be exported for the image fetch to share it"
    )

    print("Source-kind coverage test passed!")
    return True


def test_download_fetches_bytes_rather_than_linking_to_them():
    """`<a download>` is ignored cross-origin, which is the split-origin deployment."""
    print("Testing the download path...")

    images = _read(IMAGES_LIB)

    assert re.search(
        r"export async function downloadImageSource(.|\n)*?resolveImageBlob\((.|\n)*?saveBlob\(",
        images,
    ), "The download must resolve the bytes to a blob and save that"

    # One download path, not two. saveBlob already existed for the message exports.
    assert "import { saveBlob } from './endpoints';" in images, (
        "The image download must reuse the existing saveBlob helper"
    )
    assert "export function saveBlob(" in _read(ENDPOINTS_LIB), (
        "saveBlob must be exported for images.ts to reuse it"
    )

    # A cross-origin host that sends no CORS headers cannot be read; that has to surface.
    assert re.search(r"catch \{(.|\n)*?throw new Error\((.|\n)*?hosted elsewhere", images), (
        "A CORS-refused external image must report why the download failed"
    )

    print("Download path test passed!")
    return True


def test_download_names_are_usable_and_safe():
    """A downloads folder full of opaque ids helps nobody."""
    print("Testing download file names...")

    images = _read(IMAGES_LIB)

    assert "export function imageFileName(" in images, "There must be a name derivation"
    assert "MIME_EXTENSIONS" in images, (
        "The extension must follow the actual image type rather than being assumed"
    )
    assert "IMAGE_EXTENSION_PATTERN" in images, (
        "A name that already ends in an image extension must not get a second one"
    )
    assert "UNSAFE_FILENAME_CHARS" in images, (
        "A prompt used as a file name must have illegal characters removed first"
    )

    # A whole prompt can be a paragraph; it is only usable as a name when it is short.
    assert "fromPrompt.length <= 60" in images, (
        "An over-long prompt must not become the file name"
    )

    print("File name test passed!")
    return True


def test_no_third_party_assets_were_introduced():
    """The V2 bundle stays local-only."""
    print("Testing that no remote assets were added...")

    lightbox = _read(LIGHTBOX)

    assert "lucide-react" in lightbox, "Icons should come from the bundled icon set"
    for remote in ("http://", "https://", "cdn.", "unpkg", "jsdelivr"):
        assert remote not in lightbox, (
            f"The lightbox must not reference a remote asset ({remote!r} found)"
        )

    print("Local assets test passed!")
    return True


def test_version_is_at_least_implementation_version():
    """The application version is at or beyond the version that added this."""
    print("Testing application version...")
    assert_app_version_at_least("0.261.025")
    print("Application version test passed!")
    return True


if __name__ == "__main__":
    tests = [
        test_thumbnail_opens_a_dialog_rather_than_a_new_tab,
        test_broken_image_fallback_survives,
        test_dialog_follows_the_existing_modal_conventions,
        test_the_new_tab_actions_are_still_available,
        test_every_image_source_kind_is_handled,
        test_download_fetches_bytes_rather_than_linking_to_them,
        test_download_names_are_usable_and_safe,
        test_no_third_party_assets_were_introduced,
        test_version_is_at_least_implementation_version,
    ]

    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            results.append(bool(test()))
        except Exception as exc:  # noqa: BLE001 - surface any failure with a traceback
            print(f"Test failed: {exc}")
            import traceback

            traceback.print_exc()
            results.append(False)

    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)

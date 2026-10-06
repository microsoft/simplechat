#!/usr/bin/env python3
"""
Functional test for V2 media galleries, the media viewer and the drawer's Media section.
Version: 0.261.262
Implemented in: 0.261.262

This test ensures that:
  - runs of images and clips in a reply group into galleries the way agents actually write them,
    downloads are named sensibly and a clip's still frame never touches its signed query (the
    real TypeScript runs inside react-markdown in Node: test_v2_media_gallery_logic.mjs);
  - the renderer wires the gallery without weakening its XSS boundary: no raw HTML, the default
    URL transform, and every image, clip and link the new components render reading its address
    through resolveImageSource or safeMediaUrl;
  - the conversation drawer groups images, videos and recordings into one viewer and players,
    scrolls to an item's message, and stays open when Escape belongs to a dialog it opened;
  - recordings can be downloaded, cookies are never sent to another host, and a download opens
    the file in a new tab instead of failing when its host will not let the page read it.
"""

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
V2_SRC = ROOT / "application" / "v2_ui" / "src"
CHAT_DIR = V2_SRC / "components" / "chat"
LIB_DIR = V2_SRC / "lib"

sys.path.insert(0, str(ROOT / "functional_tests"))

from test_support.versioning import assert_app_version_at_least  # noqa: E402

IMPLEMENTED_IN = "0.261.262"
NEW_COMPONENTS = ("MediaGallery.tsx", "MediaTiles.tsx", "MediaViewer.tsx")
MEDIA_ELEMENT = re.compile(r"<(a|audio|video)\b[^>]*?\b(href|src)=\{([^}]*)\}", re.S)
IMAGE_ELEMENT = re.compile(r"<img\b[^>]*?\bsrc=\{([^}]*)\}", re.S)


def _read(path):
    return path.read_text(encoding="utf-8")


def test_gallery_logic_runs_in_node():
    """Run the real plugin, download naming and still-frame helpers in Node."""
    print("Testing gallery grouping in Node...")
    subprocess.run(["node", str(ROOT / "functional_tests" / "test_v2_media_gallery_logic.mjs")], cwd=ROOT, check=True)
    print("Gallery grouping passed!")


def test_renderer_wires_galleries_without_raw_html():
    """The plugin regroups existing elements; nothing in the pipeline parses or injects HTML."""
    print("Testing the renderer wiring...")
    markdown = _read(CHAT_DIR / "AssistantMarkdown.tsx")
    assert "rehypePlugins={[rehypeRichBlockIndex, rehypeMediaGallery, rehypeHighlightSubset]}" in markdown
    assert "import { readMediaGallery, readMediaTileIndex, rehypeMediaGallery } from '../../lib/mediaGallery';" in markdown
    assert "const items = readMediaGallery(node);" in markdown
    assert "<MediaGallery items={items}>{children}</MediaGallery>" in markdown
    assert re.search(r"figcaption: \(\{ children \}\) => \(\s*<figcaption[^>]*>\s*\{renderTokens\(children\)\}", markdown), (
        "captions must pass through renderTokens so citations and masks never show as raw placeholders"
    )
    assert "const tile = readMediaTileIndex(node);" in markdown
    assert "from 'rehype-raw'" not in markdown, "raw HTML must stay off"
    assert "urlTransform=" not in markdown, "react-markdown's default URL transform must stay in place"

    plugin = _read(LIB_DIR / "mediaGallery.ts")
    for sink in ("type: 'raw'", "innerHTML", "dangerouslySetInnerHTML", "fromHtml", "rehype-raw"):
        assert sink not in plugin, f"the gallery plugin must not produce markup from text ({sink})"
    assert "!/^\\s*data:/i.test(src) && resolveImageSource(src)" in plugin, (
        "only images the app can show, and that react-markdown keeps, may join a gallery"
    )
    assert "inlineMediaKind(node.properties?.href) === 'video'" in plugin
    print("Renderer wiring passed!")


def test_new_media_components_read_addresses_safely():
    """Every image, clip and link the new components render goes through a scheme check."""
    print("Testing media addresses in the new components...")
    for name in NEW_COMPONENTS:
        text = _read(CHAT_DIR / name)
        assert "dangerouslySetInnerHTML" not in text, name
        for match in MEDIA_ELEMENT.finditer(text):
            assert "safeMediaUrl(" in match.group(3), f"{name}: <{match.group(1)} {match.group(2)}> must use safeMediaUrl"
        for match in IMAGE_ELEMENT.finditer(text):
            assert match.group(1).strip() == "source.src", f"{name}: <img src> must come from resolveImageSource"
            assert "resolveImageSource(" in text, name
        for anchor in re.finditer(r"<a\b[^>]*>", text, re.S):
            if 'target="_blank"' in anchor.group(0):
                assert 'rel="noopener noreferrer"' in anchor.group(0), f"{name}: a new-tab link must not keep its opener"

    tiles = _read(CHAT_DIR / "MediaTiles.tsx")
    assert "src={posterFrameUrl(safeMediaUrl(src))}" in tiles
    assert 'preload="metadata"' in tiles and "IntersectionObserver" in tiles, "clip tiles load their frame only once on screen"
    viewer = _read(CHAT_DIR / "MediaViewer.tsx")
    assert "<Modal" in viewer, "the viewer uses the shared dialog shell for Escape, focus trapping and focus return"
    assert "target?.closest('input, textarea, select, video, audio, [contenteditable=\"true\"]')" in viewer, (
        "arrow keys inside a clip's controls or a field must keep their usual job"
    )
    print("Media addresses passed!")


def test_drawer_groups_media_and_guards_escape():
    """The drawer lists media by kind, opens one viewer, and leaves Escape to an open dialog."""
    print("Testing the drawer's Media section...")
    drawer_assets = _read(CHAT_DIR / "DrawerAssets.tsx")
    for label in ('label="Images"', 'label="Videos"', 'label="Audio"'):
        assert label in drawer_assets, label
    assert "label={`View image: ${item.title}`}" in drawer_assets
    assert "label={`Play video: ${item.title}`}" in drawer_assets
    assert "onLocate={onLocate ? () => onLocate(item.messageId) : undefined}" in drawer_assets
    assert "<MediaViewer" in drawer_assets and "ImageLightbox" not in drawer_assets

    drawer = _read(CHAT_DIR / "ConversationDrawer.tsx")
    assert "<MediaSection items={media} onLocate={scrollToMessage} />" in drawer
    assert "event.key === 'Escape' && !document.querySelector('[role=\"dialog\"][aria-modal=\"true\"]')" in drawer
    print("Drawer Media section passed!")


def test_downloads_never_send_cookies_elsewhere_and_fall_back_to_a_tab():
    """Downloads authenticate only to the app, and open the file when a host refuses the read."""
    print("Testing media downloads...")
    download = _read(LIB_DIR / "mediaDownload.ts")
    assert "return { url, credentials: sameOrigin ? 'same-origin' : 'omit' };" in download
    assert "return { url: source.src, credentials: CREDENTIALS_MODE };" in download
    assert "return openMediaInNewTab(kind, src) ? 'opened' : 'blocked';" in download
    assert "opened.opener = null;" in download
    assert "if (error instanceof MediaUnavailableError) {" in download, "an expired link reports an error, not a new tab"

    player = _read(CHAT_DIR / "InlineAudioPlayer.tsx")
    assert "onClick={() => void download('audio', src, title)}" in player
    assert "aria-label={`Download ${title}`}" in player
    assert player.count('type="range"') == 2, "the player keeps exactly its seek and volume sliders"
    print("Media downloads passed!")


def test_version_was_incremented():
    assert_app_version_at_least(IMPLEMENTED_IN)


if __name__ == "__main__":
    tests = [
        test_gallery_logic_runs_in_node,
        test_renderer_wires_galleries_without_raw_html,
        test_new_media_components_read_addresses_safely,
        test_drawer_groups_media_and_guards_escape,
        test_downloads_never_send_cookies_elsewhere_and_fall_back_to_a_tab,
        test_version_was_incremented,
    ]
    failures = 0
    for test in tests:
        try:
            test()
        except Exception as exc:  # noqa: BLE001 - report every failing check
            failures += 1
            print(f"FAILED {test.__name__}: {exc}")
    print(f"{len(tests) - failures}/{len(tests)} tests passed")
    sys.exit(1 if failures else 0)

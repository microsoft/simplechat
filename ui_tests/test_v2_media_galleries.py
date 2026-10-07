# test_v2_media_galleries.py
"""
UI test for V2 media galleries, the media viewer and the drawer's Media section.
Version: 0.261.262
Implemented in: 0.261.262

This test ensures that a run of images and clips in a reply is laid out three to a row with each
caption under its tile while a recording keeps its own player; that an evidence list puts each
item's clip and still in a row under the item's text; that a tile opens a viewer that steps
through the gallery with its buttons and the arrow keys and hands focus back to the tile; that a
clip plays in its own tile and opens larger; and that the conversation drawer groups images,
videos and recordings, downloads a recording, steps through every image and clip, scrolls to the
message an item is in, and stays open when Escape closes the viewer. A host that will not let the
page read a file opens it in a new tab instead of failing. Only HTTP boundaries are mocked: the
real MessageList, ConversationDrawer and stores run in Chromium with production CSS, playing a
WebM clip recorded in the browser and a WAV recording built here.

Build: npm --prefix .\\application\\v2_ui run build -- --outDir ..\\..\\ui_tests\\artifacts\\orchestration-plan-editor
Run: python -m pytest .\\ui_tests\\test_v2_media_galleries.py -q
"""

import base64
import io
import re
import wave
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

from test_v2_orchestration_plan_editor import (  # noqa: F401
    HARNESS,
    ORIGIN,
    connect_options,
    editor_assets,
    editor_browser,
)

pytestmark = pytest.mark.ui

CONVERSATION = "media-chat"
MEDIA = f"{ORIGIN}/media"
# Another host, which will not let the page read its files: it shows them, but a fetch of one fails.
REMOTE = "https://media.example.test"
PIXEL = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


def silent_wav(seconds=0.6, rate=8000):
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(1)
        handle.setframerate(rate)
        handle.writeframes(b"\x80" * int(rate * seconds))
    return buffer.getvalue()


WAV = silent_wav()

RECORD_CLIP = """async () => {
    const canvas = document.createElement('canvas');
    canvas.width = 64;
    canvas.height = 48;
    const context = canvas.getContext('2d');
    const recorder = new MediaRecorder(canvas.captureStream(15), { mimeType: 'video/webm;codecs=vp8' });
    const chunks = [];
    recorder.ondataavailable = (event) => chunks.push(event.data);
    const stopped = new Promise((resolve) => { recorder.onstop = resolve; });
    let frame = 0;
    const paint = () => { context.fillStyle = frame++ % 2 ? '#2a7' : '#a27'; context.fillRect(0, 0, 64, 48); };
    paint();
    const timer = setInterval(paint, 60);
    recorder.start();
    await new Promise((resolve) => setTimeout(resolve, 2500));
    recorder.stop();
    clearInterval(timer);
    await stopped;
    const bytes = new Uint8Array(await new Blob(chunks, { type: 'video/webm' }).arrayBuffer());
    let binary = '';
    for (const byte of bytes) { binary += String.fromCharCode(byte); }
    return btoa(binary);
}"""


@pytest.fixture(scope="module")
def clip_bytes(editor_browser):
    """A short, playable WebM, recorded by the browser under test."""
    page = editor_browser.new_page()
    try:
        return base64.b64decode(page.evaluate(RECORD_CLIP))
    finally:
        page.close()


class MediaApi:
    """The HTTP boundary: the harness, the app's own media and a remote media host."""

    def __init__(self, assets, clip):
        self.assets = assets
        self.clip = clip
        self.remote = []
        self.unexpected = []

    def media(self, route, name):
        if name.startswith("missing"):
            route.fulfill(status=404, body="Media not found.", content_type="text/plain")
        elif name.endswith(".png"):
            route.fulfill(status=200, body=PIXEL, content_type="image/png")
        elif name.endswith((".mp4", ".webm")):
            route.fulfill(status=200, body=self.clip, content_type="video/webm")
        elif name.endswith(".wav"):
            route.fulfill(status=200, body=WAV, content_type="audio/wav")
        else:
            return False
        return True

    def handle(self, route):
        request = route.request
        parsed = urlsplit(request.url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        name = parsed.path.rsplit("/", 1)[-1]
        if origin == REMOTE:
            self.remote.append(f"{request.resource_type} {parsed.path}")
            # A host without CORS headers makes the page's fetch reject, the same as a network
            # failure. Playwright's fulfilled responses always pass CORS, so the read is failed here
            # while images and new tabs, which need no CORS, are still served.
            if request.resource_type == "fetch":
                route.abort()
            elif not self.media(route, name):
                route.fulfill(status=404)
            return
        if origin != ORIGIN:
            self.unexpected.append(request.url)
            route.abort()
            return
        if request.method == "GET" and parsed.path in self.assets:
            route.fulfill(path=str(self.assets[parsed.path]))
            return
        if parsed.path.startswith("/media/") and self.media(route, name):
            return
        if parsed.path == "/favicon.ico":
            route.fulfill(status=204)
            return
        self.unexpected.append(f"{request.method} {parsed.path}")
        route.fulfill(status=404, json={"error": "Unmocked request"})


@pytest.fixture
def media_ui(editor_browser, editor_assets, clip_bytes):
    context = editor_browser.new_context(viewport={"width": 1280, "height": 1000}, accept_downloads=True)
    api = MediaApi(editor_assets, clip_bytes)
    errors = []
    # On the context, so a file opened in a new tab is served too.
    context.route("**/*", api.handle)
    page = context.new_page()
    page.on("pageerror", lambda error: errors.append(str(error)))
    try:
        yield page, api
    finally:
        context.close()
        assert not api.unexpected, f"Unexpected browser requests: {api.unexpected}"
        assert not errors, errors


def reply(message_id, content):
    return {
        "id": message_id,
        "conversation_id": CONVERSATION,
        "role": "assistant",
        "content": content,
        "timestamp": "2026-10-06T16:12:20Z",
        "metadata": {},
    }


def mount(page, api, messages, mounts, drawer=None):
    page.goto(ORIGIN + HARNESS)
    page.wait_for_function("() => Boolean(window.OrchHarness)")
    for url in api.assets:
        if url.endswith(".css"):
            page.add_style_tag(url=ORIGIN + url)
    page.evaluate(
        """(spec) => {
            const H = window.OrchHarness;
            H.reset();
            H.stores.bootstrap.useBootstrapStore.setState({ data: {
                version: '0.261.262', settings: {}, branding: { app_title: 'SimpleChat' }, features: {},
                user: { id: 'ui-user', display_name: 'Pat Reader' },
                scope: { groups: [], public_workspaces: [] },
                catalogs: { models: [], agents: [], prompts: [] },
            } });
            H.stores.chat.useChatStore.setState({
                activeConversationId: spec.conversation, activeConversationKind: 'personal',
                conversations: [{ id: spec.conversation, title: 'Evidence review' }],
                messagesLoading: false, messagesError: null, streaming: false, streamingContent: '',
                streamError: null, thoughts: [], messages: spec.messages,
                drawerMode: spec.drawer, metadata: { used_documents: [] },
            });
            for (const [id, name] of spec.mounts) {
                H.mount(id, name);
            }
        }""",
        {"conversation": CONVERSATION, "messages": messages, "mounts": mounts, "drawer": drawer},
    )


EVIDENCE = reply("a-1", "\n".join([
    "Here is what the records returned.",
    "",
    "Lobby camera still \u2014 record R-1; October 4, 13:38.  ",
    f"![Lobby camera at 13:38]({MEDIA}/lobby-still-1.png?exp=1&sig=a)",
    "",
    "Badge photo \u2014 record R-1.  ",
    f"![Badge photo]({MEDIA}/badge-1.png?exp=1&sig=b)",
    "",
    "Loading dock clip \u2014 record R-2.  ",
    f"[Open video: Loading dock camera clip (2 s)]({MEDIA}/dock-clip-2.mp4?exp=1&sig=c)",
    "",
    "Receipt scan \u2014 record R-3.  ",
    f"![Receipt R-3]({MEDIA}/receipt-3.png)",
    "",
    "Initial call \u2014 recording C-1.  ",
    f"[Open audio: Call audio C-1]({MEDIA}/call-1.wav?exp=1&sig=d)",
]))

TIMELINE = reply("a-2", "\n".join([
    f"- **06:31, camera 12:** Gray sedan heading west on Main Street. [Video]({MEDIA}/clip-12-0631.mp4)  ",
    f"  ![Camera 12 still 06:31]({MEDIA}/still-12-0631.png)",
    "",
    f"- **07:01, camera 12:** Same sedan heading east. [Video]({MEDIA}/clip-12-0701.mp4)  ",
    f"  ![Camera 12 still 07:01]({MEDIA}/still-12-0701.png)",
]))


def box(locator):
    value = locator.bounding_box()
    assert value, "expected a laid-out element"
    return value


def test_reply_media_runs_render_as_three_column_galleries(media_ui):
    page, api = media_ui
    mount(page, api, [EVIDENCE, TIMELINE], [["test-root", "MessageList"]])

    evidence = page.locator("#message-a-1")
    gallery = evidence.get_by_role("group", name="Gallery: 3 images and 1 video")
    expect(gallery).to_be_visible()
    figures = gallery.locator("figure")
    expect(figures).to_have_count(4)
    expect(gallery.locator("figcaption")).to_have_text([
        "Lobby camera still \u2014 record R-1; October 4, 13:38.",
        "Badge photo \u2014 record R-1.",
        "Loading dock clip \u2014 record R-2.",
        "Receipt scan \u2014 record R-3.",
    ])
    tiles = [box(figures.nth(index).locator("[data-media-tile-kind]").first) for index in range(4)]
    assert tiles[0]["y"] == pytest.approx(tiles[1]["y"], abs=1) == pytest.approx(tiles[2]["y"], abs=1), tiles
    assert tiles[0]["x"] < tiles[1]["x"] < tiles[2]["x"], tiles
    assert tiles[3]["y"] > tiles[0]["y"] + tiles[0]["height"], "the fourth tile starts the next row"
    for tile in tiles:
        assert 150 <= tile["width"] <= 209, tiles
    # Replies with a gallery no longer show the full-width card per image.
    expect(evidence.get_by_role("button", name=re.compile("^View the full-size image"))).to_have_count(0)
    # The recording keeps its player, after the gallery, with its caption beside it.
    expect(evidence.get_by_role("group", name="Audio: Call audio C-1")).to_be_visible()
    expect(evidence.get_by_text("Initial call \u2014 recording C-1.")).to_be_visible()

    timeline = page.locator("#message-a-2")
    items = timeline.locator("li")
    expect(items).to_have_count(2)
    for index, sentence in enumerate(["Gray sedan heading west on Main Street.", "Same sedan heading east."]):
        item = items.nth(index)
        expect(item.locator("p").first).to_contain_text(sentence)
        row = item.get_by_role("group", name="Gallery: 1 image and 1 video")
        expect(row.get_by_role("button", name="Play video: Video")).to_be_visible()
        expect(row.get_by_role("button", name=re.compile("^View image: Camera 12 still"))).to_be_visible()
        clip, still = box(row.locator("[data-media-tile-kind]").nth(0)), box(row.locator("[data-media-tile-kind]").nth(1))
        assert clip["y"] == pytest.approx(still["y"], abs=1) and clip["x"] < still["x"], (clip, still)


def test_gallery_viewer_steps_through_images_and_clips(media_ui):
    page, api = media_ui
    mount(page, api, [EVIDENCE], [["test-root", "MessageList"]])
    gallery = page.get_by_role("group", name="Gallery: 3 images and 1 video")

    opener = gallery.get_by_role("button", name="View image: Badge photo \u2014 record R-1.")
    opener.click()
    viewer = page.get_by_role("dialog")
    position = viewer.locator("[data-media-viewer-position]")
    expect(viewer.get_by_role("heading", name="Badge photo \u2014 record R-1.")).to_be_visible()
    expect(position).to_have_text("Image \u00b7 2 of 4")
    expect(viewer.get_by_text("Badge photo", exact=True)).to_be_visible()
    expect(viewer.locator("[data-media-viewer] img")).to_have_attribute("src", re.compile(r"/media/badge-1\.png\?exp=1&sig=b$"))

    page.keyboard.press("ArrowRight")
    expect(position).to_have_text("Video \u00b7 3 of 4")
    clip = viewer.locator("[data-media-viewer] video")
    expect(clip).to_have_attribute("src", re.compile(r"/media/dock-clip-2\.mp4\?exp=1&sig=c$"))
    page.wait_for_function("() => { const v = document.querySelector('[data-media-viewer] video'); return v && !v.paused && v.currentTime > 0; }")

    viewer.get_by_role("button", name="Next").click()
    expect(position).to_have_text("Image \u00b7 4 of 4")
    expect(viewer.locator("[data-media-viewer] video")).to_have_count(0)
    expect(viewer.get_by_role("button", name="Next")).to_have_attribute("aria-disabled", "true")
    page.keyboard.press("ArrowRight")
    expect(position).to_have_text("Image \u00b7 4 of 4")
    viewer.get_by_role("button", name="Previous").click()
    expect(position).to_have_text("Video \u00b7 3 of 4")

    page.keyboard.press("Escape")
    expect(page.get_by_role("dialog")).to_have_count(0)
    expect(opener).to_be_focused()


def test_a_gallery_clip_plays_in_its_tile_and_opens_larger(media_ui):
    page, api = media_ui
    mount(page, api, [EVIDENCE], [["test-root", "MessageList"]])
    gallery = page.get_by_role("group", name="Gallery: 3 images and 1 video")

    gallery.get_by_role("button", name="Play video: Loading dock clip \u2014 record R-2.").click()
    inline = gallery.locator("video[controls]")
    expect(inline).to_have_count(1)
    page.wait_for_function("() => { const v = document.querySelector('[data-media-gallery] video[controls]'); return v && !v.paused && v.currentTime > 0.2; }")
    tile = box(inline)
    assert tile["width"] <= 209, tile

    gallery.get_by_role("button", name="View larger: Loading dock clip \u2014 record R-2.").click()
    viewer = page.get_by_role("dialog")
    expect(viewer.locator("[data-media-viewer-position]")).to_have_text("Video \u00b7 3 of 4")
    page.wait_for_function("() => { const v = document.querySelector('[data-media-viewer] video'); return v && !v.paused; }")
    assert page.evaluate("() => document.querySelector('[data-media-gallery] video[controls]').paused"), (
        "opening the clip larger pauses it in its tile"
    )
    assert box(viewer.locator("[data-media-viewer] video"))["width"] > tile["width"]


def test_drawer_groups_media_plays_recordings_and_finds_their_message(media_ui):
    page, api = media_ui
    mount(page, api, [EVIDENCE], [["test-root", "MessageList"], ["mount-a", "ConversationDrawer"]], drawer="documents")
    media = page.get_by_role("region", name="Media")

    expect(media.get_by_role("group", name="Images").get_by_role("button")).to_have_count(3)
    expect(media.get_by_role("group", name="Videos").get_by_role("button")).to_have_count(1)
    audio = media.get_by_role("group", name="Audio")
    expect(audio.get_by_role("group", name="Audio: Call audio C-1")).to_be_visible()

    # A recording plays from the drawer, and downloads under the name in its link.
    audio.get_by_role("button", name="Play Call audio C-1").click()
    page.wait_for_function("() => [...document.querySelectorAll('[data-drawer-media] audio')].some((a) => !a.paused || a.ended)")
    with page.expect_download() as download:
        audio.get_by_role("button", name="Download Call audio C-1").click()
    assert download.value.suggested_filename == "call-1.wav"

    # The viewer steps through the images, then the clip.
    media.get_by_role("button", name="Play video: Loading dock camera clip (2 s)").click()
    viewer = page.get_by_role("dialog")
    position = viewer.locator("[data-media-viewer-position]")
    expect(position).to_have_text("Video \u00b7 4 of 4")
    page.keyboard.press("ArrowLeft")
    expect(position).to_have_text("Image \u00b7 3 of 4")
    expect(viewer.get_by_role("heading", name="Receipt R-3")).to_be_visible()

    # Escape closes the viewer only; a second Escape closes the drawer.
    page.keyboard.press("Escape")
    expect(page.get_by_role("dialog")).to_have_count(0)
    drawer = page.get_by_role("complementary", name="Conversation details")
    expect(drawer).to_be_visible()

    # Show in conversation closes the viewer and highlights the message.
    media.get_by_role("button", name="View image: Badge photo").click()
    page.get_by_role("dialog").get_by_role("button", name="Show in conversation").click()
    expect(page.get_by_role("dialog")).to_have_count(0)
    expect(page.locator("#message-a-1")).to_have_class(re.compile(r"\bring-2\b"))

    page.keyboard.press("Escape")
    expect(drawer).to_have_count(0)


def test_media_the_page_cannot_read_opens_in_a_new_tab(media_ui):
    page, api = media_ui
    remote = reply("a-3", "\n".join([
        f"![Remote still one]({REMOTE}/media/remote-1.png?sig=r1)",
        f"![Remote still two]({REMOTE}/media/remote-2.png?sig=r2)",
        f"![Expired still]({MEDIA}/missing-3.png)",
    ]))
    mount(page, api, [remote], [["test-root", "MessageList"], ["mount-b", "Toaster"]])
    gallery = page.get_by_role("group", name="Gallery: 3 images")

    gallery.get_by_role("button", name="View image: Remote still one").click()
    viewer = page.get_by_role("dialog")
    with page.context.expect_page() as opened:
        viewer.get_by_role("button", name="Download Remote still one").click()
    tab = opened.value
    tab.wait_for_load_state()
    assert tab.url == f"{REMOTE}/media/remote-1.png?sig=r1", tab.url
    tab.close()
    assert "fetch /media/remote-1.png" in api.remote, "the page tried to save the file before opening it"
    expect(page.get_by_text("Its host does not allow a direct download")).to_be_visible()
    page.keyboard.press("Escape")

    # A link that has expired says so on its tile and in the viewer, and cannot be downloaded.
    expired = gallery.get_by_role("button", name="View image: Expired still")
    expect(expired).to_contain_text("Unavailable")
    expired.click()
    viewer = page.get_by_role("dialog")
    expect(viewer.get_by_text("This image can\u2019t be shown here.")).to_be_visible()
    viewer.get_by_role("button", name="Download Expired still").click()
    expect(page.get_by_text("The file could not be fetched (404). Its link may have expired.")).to_be_visible()

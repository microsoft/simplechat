# image_editor.py
"""
Source-backed, isolated image editor browser fixture.
Version: 0.261.194
Implemented in: 0.261.107
Held responses and stored assist turns added in: 0.261.194

Compile the production component, hooks, store and theme in memory with the installed
V2 toolchain. Never read or replace checked-in static bundles. All browser requests are
intercepted; no application credentials, image providers or live inference are used.
"""

import copy
import json
import struct
import subprocess
import zlib
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import Error as PlaywrightError, Page, Route, expect


REPO_ROOT = Path(__file__).resolve().parents[2]
UI_ROOT = REPO_ROOT / "application" / "v2_ui"
ORIGIN = "http://simplechat.test"
HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Image editor fixture</title>
<link rel="stylesheet" href="/static/image-editor-fixture/editor.css" />
</head><body><div id="root"></div>
<script type="module" src="/static/image-editor-fixture/editor.js"></script>
</body></html>"""

ENTRY = """
// image_editor_fixture.jsx
import React, { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { ImageEditor } from '@fixture-editor';
import { useImageEditCapability, useImageRevisions } from '@fixture-revisions';
import { useBootstrapStore } from '@fixture-bootstrap';
import { useChatStore } from '@fixture-chat';
import '@fixture-theme';

const initial = window.imageEditorInitial;
useBootstrapStore.setState({
    data: { capabilities: { image_edit: initial.capability }, features: {} },
    loading: false,
});
useChatStore.setState({
    activeConversationId: initial.conversationId,
    activeConversationKind: initial.shared ? 'collaborative' : 'personal',
    conversations: [{ id: initial.conversationId, title: 'Image fixture' }],
    messages: [{
        id: initial.messageId,
        role: 'image',
        content: initial.imageUrl,
        metadata: { image_revisions: initial.entry },
    }],
});
window.imageEditorFixture = {
    setCapability(capability) {
        useBootstrapStore.setState({
            data: { capabilities: { image_edit: capability }, features: {} },
        });
    },
};

function Fixture() {
    const [open, setOpen] = useState(false);
    const capability = useImageEditCapability();
    const revisions = useImageRevisions(initial.messageId, initial.prompt, initial.imageEndpoint);
    const imageSrc = useChatStore((state) => state.messages[0].content);
    useEffect(() => {
        window.imageEditorFixture.revise = revisions.revise;
    }, [revisions.revise]);
    return <>
        <button type="button" onClick={() => setOpen(true)}>Open image editor</button>
        {open && <ImageEditor mode={initial.mode || 'revise'} title="Generated mountain" imageSrc={imageSrc}
            revisions={revisions} capability={capability} reference={initial.reference}
            onClose={() => setOpen(false)} />}
    </>;
}
createRoot(document.getElementById('root')).render(<Fixture />);
"""

BUILD_SCRIPT = """
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { build, transformWithEsbuild } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

const { entry } = JSON.parse(readFileSync(0, 'utf8'));
const virtualId = '\\0image-editor-fixture.jsx';
const source = (...parts) => path.resolve('src', ...parts);
const result = await build({
    configFile: false,
    root: process.cwd(),
    publicDir: false,
    base: '/static/image-editor-fixture/',
    logLevel: 'silent',
    resolve: { alias: {
        '@fixture-editor': source('components', 'chat', 'ImageEditor.tsx'),
        '@fixture-revisions': source('lib', 'imageRevisions.ts'),
        '@fixture-bootstrap': source('stores', 'bootstrapStore.ts'),
        '@fixture-chat': source('stores', 'chatStore.ts'),
        '@fixture-theme': source('styles', 'theme.css'),
    } },
    plugins: [{
        name: 'image-editor-fixture',
        resolveId(id) { if (id === 'image-editor-fixture') return virtualId; },
        async load(id) {
            if (id === virtualId) {
                const transformed = await transformWithEsbuild(entry, 'image-editor-fixture.jsx', {
                    loader: 'jsx', jsx: 'automatic',
                });
                return transformed.code;
            }
        },
    }, react(), tailwindcss()],
    build: {
        write: false,
        sourcemap: false,
        rollupOptions: {
            input: 'image-editor-fixture',
            output: { entryFileNames: 'editor.js', chunkFileNames: '[name].js', assetFileNames: '[name][extname]' },
        },
    },
});
const assets = {};
let css = '';
for (const bundle of Array.isArray(result) ? result : [result]) {
    for (const output of bundle.output) {
        const body = output.type === 'chunk' ? output.code : Buffer.from(output.source).toString('utf8');
        const contentType = output.fileName.endsWith('.css') ? 'text/css' : 'text/javascript';
        assets['/static/image-editor-fixture/' + output.fileName] = { body, contentType };
        if (output.fileName.endsWith('.css')) css += body;
    }
}
assets['/static/image-editor-fixture/editor.css'] = { body: css, contentType: 'text/css' };
process.stdout.write(JSON.stringify(assets));
"""


def image_profile(mode="masked", **overrides):
    """Synthetic server metadata; deliberately independent of app-hosting cloud."""
    result = {
        "enabled": mode != "unavailable",
        "mode": mode,
        "model_name": "configured-image-model",
        "reason": "",
        "provider_label": "Configured image provider",
        "cloud_label": "Commercial endpoint",
        "availability": "documented",
        "availability_reason": "",
        "editing": mode in ("masked", "edit"),
        "masking": mode == "masked",
        "sizes": ["1024x1024", "1536x1024", "1024x1536"],
        "qualities": ["low", "medium", "high"],
        "backgrounds": ["opaque", "transparent"],
    }
    result.update(overrides)
    return result


def reference_profile(**overrides):
    return image_profile(
        "edit",
        **{
            "model_name": "MAI-Image-2.6",
            "provider_label": "Microsoft Foundry MAI",
            "sizes": ["1024x1024", "1024x768", "768x1024"],
            "qualities": [],
            "backgrounds": [],
            **overrides,
        },
    )


def _fixture_png():
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    width, height = 360, 240
    pixels = (b"\0" + b"\x40\x90\xc0" * width) * height
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(pixels))
        + chunk(b"IEND", b"")
    )


@pytest.fixture(scope="session")
def image_editor_assets():
    """Use only installed tooling, with output kept in memory rather than static bundles."""
    result = subprocess.run(
        ["node", "--input-type=module", "--eval", BUILD_SCRIPT],
        input=json.dumps({"entry": ENTRY}),
        cwd=UI_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=False,
    )
    if result.returncode:
        pytest.fail(f"The in-memory image editor fixture could not be built; no dependencies were installed.\n{result.stderr}")
    return json.loads(result.stdout)


class ImageEditorFixture:
    """Exercise real editor state and both request paths behind a closed browser boundary."""

    def __init__(self, page: Page, assets):
        self.page = page
        self.assets = assets
        self.requests = []
        self.chat_stream_requests = []
        self.restores = []
        self.errors = []
        self.unexpected_requests = []
        self.expected_http_errors = set()
        self.next_error = None
        # With `hold` set, revision requests wait in `held` until `release()` answers them, so a
        # test can look at the editor while a request is in flight.
        self.hold = False
        self.held = []
        self.entry = {
            "current": 1,
            "revisions": [
                {
                    "id": "original", "origin": "original", "prompt": "A mountain at dawn",
                    "instruction": "", "timestamp": "2026-09-16T12:00:00Z",
                },
                {
                    "id": "revision-1", "origin": "ai", "prompt": "A mountain at dawn",
                    "instruction": "Add snow", "method": "edit",
                    "size": "1536x1024", "quality": "high", "background": "transparent",
                    "timestamp": "2026-09-16T12:01:00Z",
                },
            ],
            "chat": [],
        }
        page.on("pageerror", lambda error: self.errors.append(str(error)))
        page.on("console", self._console)
        page.route("**/*", self._route)

    def _console(self, message):
        if message.type != "error":
            return
        if message.text.startswith("Failed to load resource:") and any(
            f"status of {code}" in message.text for code in self.expected_http_errors
        ):
            return
        self.errors.append(message.text)

    def open(self, capability=None, width=1440, shared=False, unresolved=False, mode="revise", reference=None):
        self.image_endpoint = (
            "/api/collaboration/conversations/conversation-1/images/image-1"
            if shared else "/api/image/image-1"
        )
        self.revision_endpoint = (
            "/api/collaboration/conversations/conversation-1/messages/image-1/image-revision"
            if shared else "/api/message/image-1/image-revision"
        )
        self.initial = {
            "capability": None if unresolved else capability or image_profile(),
            "conversationId": "conversation-1",
            "messageId": "image-1",
            "shared": shared,
            "prompt": "A mountain at dawn",
            "imageEndpoint": self.image_endpoint,
            "imageUrl": f"{self.image_endpoint}?rev=revision-1",
            "entry": self.entry,
            "mode": mode,
            "reference": reference,
        }
        self.page.set_viewport_size({"width": width, "height": 1000})
        self.page.add_init_script(f"window.imageEditorInitial = {json.dumps(self.initial)};")
        self.page.goto(f"{ORIGIN}/image-editor", wait_until="networkidle")
        self.page.get_by_role("button", name="Open image editor", exact=True).click()
        dialog_name = "Create image from reference" if mode == "derive" else "Edit image"
        expect(self.page.get_by_role("dialog", name=dialog_name, exact=True)).to_be_visible()

    def set_capability(self, capability):
        self.page.evaluate("(value) => window.imageEditorFixture.setCapability(value)", capability)

    def _route(self, route: Route):
        request = route.request
        parsed = urlsplit(request.url)
        path = parsed.path
        if f"{parsed.scheme}://{parsed.netloc}" != ORIGIN:
            self.unexpected_requests.append(request.url)
            route.abort()
        elif request.method == "GET" and path == "/image-editor":
            route.fulfill(content_type="text/html", body=HTML)
        elif request.method == "GET" and path in self.assets:
            asset = self.assets[path]
            route.fulfill(content_type=asset["contentType"], body=asset["body"])
        elif request.method == "GET" and path == self.image_endpoint:
            route.fulfill(content_type="image/png", body=_fixture_png())
        elif request.method == "GET" and path == "/favicon.ico":
            route.fulfill(status=204)
        elif request.method == "GET" and path == "/api/get_messages":
            route.fulfill(json={"messages": [{
                "id": self.initial["messageId"],
                "role": "image",
                "content": self.initial["imageUrl"],
                "metadata": {"image_revisions": self.initial["entry"]},
            }]})
        elif request.method == "POST" and path == "/api/chat/stream":
            body = copy.deepcopy(request.post_data_json)
            self.chat_stream_requests.append({"path": path, "body": body})
            frames = [
                {"type": "thought", "content": "Using 1 reference image(s)"},
                {
                    "type": "user_message_persisted",
                    "user_message_id": "derive-user-message",
                },
                {
                    "done": True,
                    "role": "image",
                    "message_id": "derive-image-message",
                    "user_message_id": "derive-user-message",
                    "content": "/api/image/derive-image-message",
                },
            ]
            route.fulfill(
                status=200,
                content_type="text/event-stream",
                body="".join(f"data: {json.dumps(frame)}\n\n" for frame in frames),
            )
        elif request.method == "POST" and path == self.revision_endpoint:
            body = copy.deepcopy(request.post_data_json)
            self.requests.append({"path": path, "body": body})
            if self.hold:
                self.held.append((route, body))
                return
            self._answer_revision(route, body)
        elif request.method == "POST" and path == f"{self.revision_endpoint}/current":
            body = copy.deepcopy(request.post_data_json)
            self.restores.append({"path": path, "body": body})
            self.entry["current"] = next(
                index for index, revision in enumerate(self.entry["revisions"])
                if revision["id"] == body["revision_id"]
            )
            self._revision_response(route)
        else:
            self.unexpected_requests.append(f"{request.method} {path}")
            route.abort()

    def _answer_revision(self, route, body):
        if self.next_error:
            status, message = self.next_error
            self.expected_http_errors.add(status)
            self.next_error = None
            route.fulfill(status=status, json={"error": message})
            return
        # Like the server, an id it already stored is answered from what was stored rather than
        # run again, and a change made against an out-of-date version is refused with the stored
        # state, so the page can tell whether the change that got in first was its own.
        submission = body.get("submission_id")
        if submission and any(
            turn.get("role") == "user" and turn.get("submission_id") == submission
            for turn in self.entry["chat"]
        ):
            self._revision_response(route)
            return
        expected = body.get("expected_revision_count")
        if expected is not None and expected != len(self.entry["revisions"]):
            self.expected_http_errors.add(409)
            route.fulfill(status=409, json={
                "error": "This image was revised elsewhere.",
                "image_revisions": copy.deepcopy(self.entry),
            })
            return
        revision = {
            "id": f"revision-{len(self.entry['revisions'])}",
            "origin": body["origin"],
            "method": body["operation"],
            "prompt": body.get("prompt") or self.entry["revisions"][self.entry["current"]]["prompt"],
            "instruction": body.get("instruction", ""),
            "has_mask": bool(body.get("mask")),
            "timestamp": "2026-09-16T12:02:00Z",
            **{key: body[key] for key in ("size", "quality", "background") if key in body},
        }
        self.entry["revisions"].append(revision)
        self.entry["current"] = len(self.entry["revisions"]) - 1
        # Like the server, an instruction is kept in the image's own chat under the client's id.
        if revision["instruction"]:
            stamp = {"submission_id": body["submission_id"]} if body.get("submission_id") else {}
            self.entry["chat"].extend([
                {"role": "user", "content": revision["instruction"], "timestamp": revision["timestamp"], **stamp},
                {"role": "assistant", "content": revision["prompt"], "timestamp": revision["timestamp"], **stamp},
            ])
        self._revision_response(route)

    def release(self):
        """Answer every held revision request, as the server would once each one finished."""
        held, self.held = self.held, []
        for route, body in held:
            try:
                self._answer_revision(route, body)
            except PlaywrightError:
                # The page already stopped waiting for this one, which is what Cancel does.
                pass

    def drop(self):
        """Fail every held revision request without applying it, as if it never reached the server."""
        held, self.held = self.held, []
        for route, _body in held:
            try:
                route.abort()
            except PlaywrightError:
                pass

    def wait_for_requests(self, count):
        """Let the page's requests reach the route handler, which runs while Playwright waits."""
        for _ in range(100):
            if len(self.requests) >= count:
                return
            self.page.wait_for_timeout(50)
        raise AssertionError(f"Expected {count} revision requests, saw {len(self.requests)}")

    def _revision_response(self, route):
        revision = self.entry["revisions"][self.entry["current"]]
        route.fulfill(json={
            "success": True, "message_id": "image-1",
            "image_url": f"{self.image_endpoint}?rev={revision['id']}",
            "image_revisions": self.entry,
            "method": revision.get("method", ""),
        })

    def assert_clean(self):
        assert not self.unexpected_requests, self.unexpected_requests
        assert not self.errors, self.errors

# test_chat_stale_active_group_recovery.py
"""Real legacy/V2 browser journeys through the offline Flask application.

Version: 0.261.371
Implemented in: 0.261.371

Playwright uses the existing local/Azure connection fixture. Requests are bridged
to an isolated real Flask test client, not canned bootstrap or chat responses.
Only cloud storage and model I/O are doubled; no live user data is touched.
"""

import base64
from collections import deque
import json
from pathlib import Path
from queue import Empty, Queue
import subprocess
import sys
from threading import Thread
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "functional_tests"))
sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))

from test_stale_active_group_recovery import CHAT_PROBE  # noqa: E402
from playwright_connection import connect_options  # noqa: E402,F401


pytestmark = pytest.mark.ui


class OfflineChatBackend:
    """Line-delimited IPC keeps Flask's network prohibition outside the browser."""

    def __init__(self):
        self.replies = Queue()
        self.diagnostics = deque(maxlen=40)
        self.process = subprocess.Popen(
            [
                sys.executable, "-u", "-B", "-c", CHAT_PROBE,
                str(ROOT / "application" / "single_app"),
                str(ROOT / "functional_tests"), "--bridge",
            ],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8",
        )
        self.reader = Thread(target=self._read, daemon=True)
        self.reader.start()
        try:
            ready = self._receive()
            if ready != {"ready": True}:
                raise AssertionError(f"Unexpected backend handshake: {ready}")
        except BaseException:
            self.close()
            raise

    def _read(self):
        for line in self.process.stdout:
            if line.startswith("BRIDGE:"):
                self.replies.put(json.loads(line.removeprefix("BRIDGE:")))
            else:
                self.diagnostics.append(line[-1000:])
        self.replies.put(None)

    def _receive(self):
        try:
            reply = self.replies.get(timeout=180)
        except Empty:
            raise AssertionError("Offline backend timed out:\n" + "".join(self.diagnostics)) from None
        if reply is None:
            raise AssertionError("Offline backend exited:\n" + "".join(self.diagnostics))
        return reply

    def exchange(self, command):
        self.process.stdin.write(json.dumps(command) + "\n")
        self.process.stdin.flush()
        return self._receive()

    def close(self):
        self.process.stdin.close()
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            self.process.wait(timeout=10)
        self.reader.join(timeout=5)
        self.process.stdout.close()


@pytest.fixture(scope="module")
def backend():
    instance = OfflineChatBackend()
    try:
        yield instance
    finally:
        instance.close()


@pytest.mark.parametrize("flavour,path", [("classic", "/chats"), ("v2", "/v2/chat")])
@pytest.mark.parametrize("removed_after_load", [False, True])
def test_chat_recovers_without_another_group(page, backend, flavour, path, removed_after_load):
    """Both production clients complete a turn, including an already-open tab."""
    errors = []
    streams = []
    page.on("pageerror", lambda error: errors.append(str(error)))

    def route_request(route):
        request = route.request
        url = urlsplit(request.url)
        if url.hostname != "simplechat.test":
            errors.append("Unexpected external request: " + request.url)
            route.abort()
            return
        command = {"path": url.path + ("?" + url.query if url.query else ""), "method": request.method}
        if request.post_data:
            command["json"] = request.post_data_json
        response = backend.exchange(command)
        if url.path == "/api/chat/stream":
            streams.append(response)
        route.fulfill(
            status=response["status"],
            content_type=response["content_type"],
            body=base64.b64decode(response["body"]),
        )

    page.route("**/*", route_request)
    backend.exchange({"seed": True, "member": removed_after_load})
    page.goto("http://simplechat.test" + path)
    composer = page.locator("#user-input") if flavour == "classic" else page.get_by_role(
        "textbox", name="Message", exact=True,
    )
    expect(composer).to_be_visible(timeout=60000)
    active_group = backend.exchange({"inspect": True})["active_group"]
    assert active_group == ("former" if removed_after_load else None)
    if removed_after_load:
        # Revoke the group membership without refreshing the browser's old scope.
        backend.exchange({"seed": True})
    composer.fill("Hello after group membership ended")
    send = page.locator("#send-btn") if flavour == "classic" else page.get_by_role(
        "button", name="Send message", exact=True,
    )
    expect(send).to_be_enabled()
    send.click()
    try:
        expect(page.get_by_text("Chat still works without a group.", exact=False).first).to_be_visible(
            timeout=60000,
        )
    except AssertionError:
        diagnostics = {
            "page": page.locator("body").inner_text()[-3500:],
            "errors": errors,
            "streams": [base64.b64decode(response["body"]).decode("utf-8")[-2000:] for response in streams],
            "backend": list(backend.diagnostics)[-10:],
        }
        raise AssertionError(json.dumps(diagnostics, indent=2)) from None
    assert streams and all(response["status"] == 200 for response in streams)
    assert backend.exchange({"inspect": True})["active_group"] is None
    expect(page.get_by_text("Stream interrupted before any content was received.", exact=False)).to_have_count(0)
    assert not errors, errors


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))

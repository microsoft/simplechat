# test_agent_modal_icon_controls.py
"""
UI test for agent modal icon controls.
Version: 0.250.011
Implemented in: 0.250.011

This test ensures the new-agent modal initializes icon search, icon selection,
and image mode controls without relying on an existing saved agent.
"""

from contextlib import contextmanager
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import socket
from threading import Thread

import pytest

playwright_sync = pytest.importorskip("playwright.sync_api", reason="Install Playwright to run this UI test.")


REPO_ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP_ICON_FIXTURE_CSS = """
.bi-robot::before { content: "\\f6b1"; }
.bi-calendar-check::before { content: "\\f1f2"; }
.bi-envelope::before { content: "\\f32f"; }
.bi-search::before { content: "\\f52a"; }
"""


def _get_free_local_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@contextmanager
def _start_static_test_server():
    port = _get_free_local_port()
    handler = partial(SimpleHTTPRequestHandler, directory=str(REPO_ROOT))
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    server.daemon_threads = True
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.mark.ui
def test_agent_modal_icon_controls_initialize_for_new_agent():
    """Validate that the new-agent modal wires icon search and image mode controls."""
    expect = playwright_sync.expect
    partial_path = REPO_ROOT / "application" / "single_app" / "templates" / "_agent_modal.html"
    partial_html = partial_path.read_text(encoding="utf-8")

    with playwright_sync.sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()

        try:
            with _start_static_test_server() as server_base_url:
                page.route(
                    "**/static/css/bootstrap-icons.css",
                    lambda route: route.fulfill(
                        status=200,
                        content_type="text/css",
                        body=BOOTSTRAP_ICON_FIXTURE_CSS,
                    ),
                )
                response = page.goto(server_base_url, wait_until="domcontentloaded")
                assert response is not None and response.ok

                page.set_content(
                    f"""
                    <html>
                      <body>
                        <div id="toast-container"></div>
                        {partial_html}
                        <script>
                          window.current_user_id = "test-user";
                          window.bootstrap = {{
                            Dropdown: {{
                              getInstance: () => ({{ hide: () => {{ window.__agentIconDropdownHidden = true; }} }})
                            }},
                            Modal: {{
                              getOrCreateInstance: () => ({{ show: () => {{}} }})
                            }}
                          }};
                        </script>
                        <script type="module">
                          import {{ AgentModalStepper }} from "{server_base_url}/application/single_app/static/js/agent_modal_stepper.js";
                          window.agentStepper = new AgentModalStepper();
                        </script>
                      </body>
                    </html>
                    """
                )
                page.wait_for_function("() => window.agentStepper !== undefined")
                page.wait_for_function(
                    "() => document.querySelectorAll('#agent-icon-picker-list .agent-icon-picker-option').length >= 4"
                )

                page.locator("#agent-icon-picker-search").fill("calendar")
                page.wait_for_function(
                    """
                    () => {
                        const options = Array.from(document.querySelectorAll('#agent-icon-picker-list .agent-icon-picker-option'));
                        return options.length === 1 && options[0].dataset.iconClass === 'bi-calendar-check';
                    }
                    """
                )
                page.locator("#agent-icon-picker-list .agent-icon-picker-option").click()
                expect(page.locator("#agent-icon-picker-label")).to_have_text("bi-calendar-check")
                assert page.locator("#agent-icon-class").input_value() == "bi-calendar-check"

                page.locator("label[for='agent-icon-type-image']").click()
                page.wait_for_function(
                    """
                    () => document.getElementById('agent-icon-mode').value === 'image'
                        && !document.getElementById('agent-image-icon-controls').classList.contains('d-none')
                        && document.getElementById('agent-bootstrap-icon-controls').classList.contains('d-none')
                    """
                )
                expect(page.locator("#agent-icon-image-file")).to_be_attached()

                page.evaluate(
                    """
                    () => {
                        document.getElementById('agent-icon-image-data').value = 'data:image/png;base64,AAAA';
                        window.agentStepper.clearFields();
                    }
                    """
                )
                assert page.locator("#agent-icon-mode").input_value() == "bootstrap"
                assert page.locator("#agent-icon-image-data").input_value() == ""
                assert page.locator("#agent-icon-class").input_value() == "bi-robot"
                expect(page.locator("#agent-icon-picker-label")).to_have_text("bi-robot")
        finally:
            browser.close()
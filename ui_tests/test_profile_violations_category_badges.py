# test_profile_violations_category_badges.py
"""
UI test for profile safety violation category badges.
Version: 0.241.036
Implemented in: 0.241.036

This test ensures profile safety violation categories render as tag badges and
hide categories with severity below 1 in both the table and detail modal.
"""

from contextlib import contextmanager
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import socket
from threading import Thread

import pytest
from playwright.sync_api import expect


REPO_ROOT = Path(__file__).resolve().parents[1]
HARNESS_PATH = 'ui_tests/fixtures/profile_violations_harness.html'


def _get_free_local_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


@contextmanager
def _start_static_test_server():
    port = _get_free_local_port()
    handler = partial(SimpleHTTPRequestHandler, directory=str(REPO_ROOT))
    server = ThreadingHTTPServer(('127.0.0.1', port), handler)
    server.daemon_threads = True
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        yield f'http://127.0.0.1:{port}'
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.mark.ui
def test_profile_violation_categories_render_as_filtered_badges(playwright):
    """Validate that profile violation categories render as filtered badge tags."""
    browser = playwright.chromium.launch()
    context = browser.new_context(
        viewport={"width": 1440, "height": 900},
    )
    page = context.new_page()

    try:
        with _start_static_test_server() as server_base_url:
            response = page.goto(f'{server_base_url}/{HARNESS_PATH}?tab=violations', wait_until='domcontentloaded')
            assert response is not None and response.ok

            table_body = page.locator('#profile-violations-table tbody')
            expect(table_body).to_contain_text('Violence')
            expect(table_body).to_contain_text('SelfHarm')
            expect(table_body).not_to_contain_text('Hate')
            expect(table_body.locator('.badge')).to_have_count(2)
            expect(table_body.locator('.badge').nth(0)).to_have_attribute('title', 'Severity 2')
            expect(table_body.locator('.badge').nth(1)).to_have_attribute('title', 'Severity 4')

            table_body.get_by_role('button', name='View/Edit').click()
            detail_categories = page.locator('#profile-violation-detail-categories')
            expect(detail_categories).to_contain_text('Violence')
            expect(detail_categories).to_contain_text('SelfHarm')
            expect(detail_categories).not_to_contain_text('Hate')
            expect(detail_categories.locator('.badge')).to_have_count(2)
    finally:
        context.close()
        browser.close()
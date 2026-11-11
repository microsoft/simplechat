# support_export_backend.py
"""
Production support APIs behind an isolated browser interception boundary.
Version: 0.261.428
Implemented in: 0.261.428

The real service, store, redactor, ZIP writer, and route registrars run against
SDK-default in-memory data. No live SSO, Azure logs, or settings are accessed.
"""

import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

from bs4 import BeautifulSoup


ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "application" / "single_app"), str(ROOT / "functional_tests")]

from test_support.support_exports import build_api, build_service


ORIGIN = "http://simplechat.test"
STATIC = ROOT / "application" / "single_app" / "static"
API_PATTERN = re.compile(r"^http://simplechat\.test/api/(?:admin/support-exports|support-export-consents)(?:[/?].*)?$")


class SupportBackend:
    def __init__(self, *, service=None, actor="test-admin", roles=None):
        self.data = build_service() if service is None else None
        self.service = self.data[0] if self.data else service
        self.app, self.client = build_api(self.service, actor, roles)
        self.posts = []

    def handle(self, route):
        request = route.request
        parsed = urlsplit(request.url)
        path = parsed.path + ("?" + parsed.query if parsed.query else "")
        if request.method == "POST":
            self.posts.append((parsed.path, request.post_data_json))
        if request.method == "GET" and re.fullmatch(r"/api/admin/support-exports/[0-9a-f]{32}", parsed.path):
            self.service.tick()
        response = self.client.open(
            path, method=request.method, data=request.post_data,
            headers={"Content-Type": request.headers.get("content-type", "application/json"), "Origin": ORIGIN},
        )
        headers = {key: value for key, value in response.headers.items() if key.lower() not in ("content-length", "set-cookie")}
        route.fulfill(status=response.status_code, headers=headers, body=response.data)


class ClassicSupportPage:
    def __init__(self, page, backend, *, consent=False):
        self.page, self.backend = page, backend
        self.errors = []
        self.unexpected = []
        page.on("pageerror", lambda error: self.errors.append(str(error)))
        page.route("**/*", self.route)
        templates = ROOT / "application" / "single_app" / "templates"
        if consent:
            source = (templates / "approvals.html").read_text(encoding="utf-8")
            soup = BeautifulSoup(source, "html.parser")
            content = str(soup.select_one('[data-support-exports="consent"]'))
        else:
            content = (templates / "admin" / "_support_log_export.html").read_text(encoding="utf-8")
        self.html = (
            '<!doctype html><html lang="en"><head><meta name="viewport" content="width=device-width, initial-scale=1">'
            '<link rel="stylesheet" href="/static/css/bootstrap.min.css"></head><body>'
            '<main class="container py-3">' + content + '</main>'
            '<script type="module" src="/static/js/support-exports.js"></script></body></html>'
        )

    def route(self, route):
        parsed = urlsplit(route.request.url)
        if f"{parsed.scheme}://{parsed.netloc}" != ORIGIN:
            self.unexpected.append(route.request.url)
            route.abort()
        elif API_PATTERN.match(route.request.url):
            self.backend.handle(route)
        elif parsed.path.startswith("/static/"):
            path = (STATIC / parsed.path.removeprefix("/static/")).resolve()
            if path.is_relative_to(STATIC.resolve()) and path.is_file():
                route.fulfill(path=str(path))
            else:
                self.unexpected.append(parsed.path)
                route.fulfill(status=404, body="Missing local fixture asset")
        else:
            route.fulfill(body=self.html, content_type="text/html")

    def open(self, *, width=1440, theme="light", query=""):
        self.page.set_viewport_size({"width": width, "height": 1000})
        self.page.goto(ORIGIN + "/fixture" + query, wait_until="networkidle")
        self.page.locator("html").evaluate("(element, theme) => element.dataset.bsTheme = theme", theme)

    def assert_clean(self):
        assert not self.errors, self.errors
        assert not self.unexpected, self.unexpected

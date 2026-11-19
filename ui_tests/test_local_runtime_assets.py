# test_local_runtime_assets.py
"""Exercise real local browser libraries with external runtime assets blocked.

Version: 0.261.456
Implemented in: 0.261.456
"""

from contextlib import contextmanager
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
import subprocess
import threading
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "application" / "single_app" / "static"
METADATA_URL = "/static/js/teams-2.19.0/validDomains.json"
FIXTURES = (
    "ascii_dash_table_test.html", "complete_table_support_test.html",
    "final_validation.html", "table_processing_analysis.html",
    "table_validation_final.html", "test_psv_table_conversion.html",
    "test_unicode_table_conversion.html",
)


class RepositoryHandler(SimpleHTTPRequestHandler):
    def translate_path(self, path):
        if path.startswith("/static/"):
            path = "/application/single_app/static/" + path.removeprefix("/static/")
        return super().translate_path(path)

    def log_message(self, _format, *args):
        pass


@pytest.fixture(scope="module")
def asset_origin():
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0), partial(RepositoryHandler, directory=str(ROOT))
    )
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        worker.join()


@contextmanager
def local_asset_guard(page, origin):
    attempts = []
    failures = []

    def observe(request):
        parsed = urlsplit(request.url)
        if parsed.scheme not in {"http", "https"} or request.url.startswith(origin + "/"):
            return
        if request.resource_type in {"script", "stylesheet", "font"} or re.search(
            r"\.(?:wasm|aff|dic)(?:[?#]|$)|/validDomains\.json", request.url
        ):
            attempts.append(request.url)

    def block(route):
        observe(route.request)
        route.abort()

    def response(response):
        if response.request.resource_type in {"script", "stylesheet", "font"} and response.status >= 400:
            failures.append(f"{response.status}: {response.url}")

    page.on("request", observe)
    page.on("response", response)
    page.route(re.compile(r"^https?://(?!127\.0\.0\.1:)"), block)
    page.add_init_script("""
        window.__assetCspViolations = [];
        document.addEventListener('securitypolicyviolation', event => {
            if (/^(script|style|font|worker)/.test(event.effectiveDirective)) {
                window.__assetCspViolations.push(event.blockedURI);
            }
        });
    """)
    try:
        yield attempts
        assert attempts == [], f"Attempted external runtime assets: {attempts}"
        assert failures == [], f"Missing local runtime assets: {failures}"
        violations = page.evaluate("window.__assetCspViolations || []")
        assert violations == [], f"CSP-blocked asset attempts: {violations}"
    finally:
        page.remove_listener("request", observe)
        page.remove_listener("response", response)
        page.unroute(re.compile(r"^https?://(?!127\.0\.0\.1:)"), block)


@pytest.mark.ui
@pytest.mark.parametrize("filename", FIXTURES)
def test_standalone_tables_use_real_local_assets(page, asset_origin, filename):
    with local_asset_guard(page, asset_origin):
        page.goto(f"{asset_origin}/functional_tests/{filename}", wait_until="networkidle")
        result = page.evaluate("""() => {
            const host = document.createElement('div');
            host.id = 'local-table-probe';
            host.innerHTML = DOMPurify.sanitize(marked.parse(
                ['|Local|', '|---|', '|Ready|'].join(String.fromCharCode(10))
            ));
            document.body.appendChild(host);
            return {
                marked: typeof marked.parse,
                purify: DOMPurify.version,
                unsafe: DOMPurify.sanitize('<img src=x onerror=alert(1)>')
            };
        }""")
        expect(page.locator("#local-table-probe table")).to_be_visible()
        assert result["marked"] == "function"
        assert result["purify"] == "3.4.14"
        assert "onerror" not in result["unsafe"]


@pytest.fixture(scope="module")
def v2_loader():
    source = ROOT / "application" / "v2_ui" / "src" / "lib" / "vendorAssets.ts"
    result = subprocess.run(
        ["node", "-e", """
            const esbuild = require('./application/v2_ui/node_modules/esbuild');
            const fs = require('fs');
            process.stdout.write(esbuild.transformSync(fs.readFileSync(0, 'utf8'), {
                loader: 'ts',
                format: 'esm',
                define: { 'import.meta.env.BASE_URL': '"/static/v2/"' }
            }).code);
        """],
        input=source.read_text(encoding="utf-8"),
        check=True, capture_output=True, text=True, cwd=ROOT,
    )
    return result.stdout


@pytest.mark.ui
def test_v2_lazy_libraries_and_fonts_stay_local(page, asset_origin, v2_loader):
    requests = []
    page.on("request", lambda request: requests.append(request.url))
    page.route("**/local-v2-loader.js", lambda route: route.fulfill(
        content_type="application/javascript", body=v2_loader
    ))
    with local_asset_guard(page, asset_origin):
        page.goto(f"{asset_origin}/functional_tests/final_validation.html")
        page.evaluate("""async () => {
            const loader = await import('/local-v2-loader.js');
            await Promise.all([
                loader.loadVendorScript(loader.VENDOR_PATHS.katexScript),
                loader.loadVendorStylesheet(loader.VENDOR_PATHS.katexStylesheet),
                loader.loadVendorScript(loader.VENDOR_PATHS.mermaid),
                loader.loadVendorScript(loader.VENDOR_PATHS.chartJs),
                loader.loadDomPurify(),
                loader.loadOpenLayers()
            ]);
            const host = document.createElement('div');
            host.id = 'local-runtime-results';
            const math = document.createElement('div');
            host.appendChild(math);
            document.body.appendChild(host);
            katex.render('x^2 + \\\\frac{1}{2}', math);
            mermaid.initialize({ startOnLoad: false, securityLevel: 'strict' });
            const diagram = await mermaid.render('local-runtime-diagram', 'graph TD; A-->B;');
            const parsed = new DOMParser().parseFromString(
                DOMPurify.sanitize(diagram.svg), 'image/svg+xml'
            );
            host.appendChild(document.importNode(parsed.documentElement, true));
            const canvas = document.createElement('canvas');
            host.appendChild(canvas);
            new Chart(canvas, { type: 'bar', data: {
                labels: ['Local'], datasets: [{ data: [1] }]
            }, options: { animation: false } });
            const map = document.createElement('div');
            map.style.width = '200px';
            map.style.height = '100px';
            host.appendChild(map);
            new ol.Map({ target: map, layers: [], view: new ol.View({ center: [0, 0], zoom: 1 }) });
            await document.fonts.ready;
        }""")
        expect(page.locator("#local-runtime-results svg")).to_be_visible()
        expect(page.locator("#local-runtime-results .katex")).to_be_visible()
        expect(page.locator("#local-runtime-results canvas").first).to_be_visible()
        assert any(".woff" in url for url in requests), "KaTeX fonts must actually load"
        assert any("/static/v2/vendor/" in url for url in requests)


@pytest.mark.ui
def test_classic_editor_diagram_and_swagger_stay_local(page, asset_origin):
    with local_asset_guard(page, asset_origin):
        page.goto(f"{asset_origin}/functional_tests/final_validation.html")
        page.add_script_tag(url=f"{asset_origin}/static/js/simplemde/simplemde.min.js")
        page.add_style_tag(url=f"{asset_origin}/static/css/simplemde.min.css")
        page.add_style_tag(url=f"{asset_origin}/static/swagger-ui/swagger-ui.css")
        page.add_script_tag(url=f"{asset_origin}/static/swagger-ui/swagger-ui-bundle.js")
        result = page.evaluate("""async () => {
            const textarea = document.createElement('textarea');
            document.body.appendChild(textarea);
            const editor = new SimpleMDE({
                element: textarea, spellChecker: false, autoDownloadFontAwesome: false
            });
            editor.value('**Local editor**');
            const runtime = await import('/static/js/chat/chat-mermaid-runtime.js');
            const rendered = await runtime.renderMermaidSvg('graph TD; A-->B;');
            const host = document.createElement('div');
            host.id = 'local-swagger';
            document.body.appendChild(host);
            SwaggerUIBundle({
                dom_id: '#local-swagger', validatorUrl: null,
                spec: { openapi: '3.0.0', info: { title: 'Local API', version: '1' }, paths: {} }
            });
            return { editor: editor.value(), diagram: rendered.includes('<svg') };
        }""")
        assert result == {"editor": "**Local editor**", "diagram": True}
        expect(page.locator("#local-swagger")).to_contain_text("Local API")


@pytest.mark.ui
def test_docs_assets_and_external_api_calls(page, asset_origin):
    layout = (ROOT / "docs/_layouts/default.html").read_text(encoding="utf-8")
    assets = re.findall(r"""(?:src|href)=["']\{\{\s*['"](/assets/[^'"]+)['"]\s*\|\s*relative_url""", layout)
    with local_asset_guard(page, asset_origin):
        page.goto(f"{asset_origin}/functional_tests/final_validation.html")
        for asset in assets:
            if asset.endswith(".js"):
                page.add_script_tag(url=f"{asset_origin}/docs{asset}")
            elif asset.endswith(".css") and (ROOT / "docs" / asset.lstrip("/")).is_file():
                page.add_style_tag(url=f"{asset_origin}/docs{asset}")
        page.route("https://api.runtime-test.invalid/v1/data", lambda route: route.fulfill(
            content_type="application/json", headers={"Access-Control-Allow-Origin": "*"},
            body='{"ok":true}',
        ))
        result = page.evaluate("""async () => {
            const response = await fetch('https://api.runtime-test.invalid/v1/data');
            return response.json();
        }""")
        assert result == {"ok": True}
        assert assets, "The docs layout must actually contribute asset references"


@pytest.mark.ui
def test_prism_worker_executes_only_local_code(page, asset_origin):
    with local_asset_guard(page, asset_origin):
        page.goto(f"{asset_origin}/functional_tests/final_validation.html")
        highlighted = page.evaluate("""() => new Promise((resolve, reject) => {
            const worker = new Worker('/docs/assets/vendor/prism-1.29.0/prism.min.js');
            worker.onerror = event => { worker.terminate(); reject(new Error(event.message)); };
            worker.onmessage = event => { worker.terminate(); resolve(event.data); };
            worker.postMessage(JSON.stringify({
                language: 'javascript', code: 'const local = 1;', immediateClose: true
            }));
        })""")
        assert 'class="token keyword"' in highlighted


@pytest.mark.ui
def test_network_guard_detects_fetch_based_runtime_assets(page, asset_origin):
    with pytest.raises(AssertionError, match="Attempted external runtime assets"):
        with local_asset_guard(page, asset_origin):
            page.goto(f"{asset_origin}/functional_tests/final_validation.html")
            page.evaluate("""async () => {
                try { await fetch('https://arbitrary.example/runtime.wasm'); } catch {}
            }""")


@pytest.mark.ui
@pytest.mark.parametrize("metadata_status", ["valid", "missing", "malformed"])
@pytest.mark.parametrize("parent_origin", [
    "https://teams.microsoft.com", "https://tenant.teams.microsoft.com",
    "https://gov.teams.microsoft.us", "https://teams.microsoft.com.evil.example",
])
def test_real_teams_sdk_uses_local_metadata_and_validates_parent(page, metadata_status, parent_origin):
    app_origin = "https://simplechat.test"
    metadata_requests = []
    external_assets = []
    page.route("**/*", lambda route: route.abort())

    def app_route(route):
        path = urlsplit(route.request.url).path
        if path == "/child":
            route.fulfill(content_type="text/html", body=(
                '<html><body><script src="/static/js/MicrosoftTeams.min.js"></script></body></html>'
            ))
        elif path == METADATA_URL:
            metadata_requests.append(route.request.url)
            route.fulfill(
                status=404 if metadata_status == "missing" else 200,
                content_type="application/json",
                body="{}" if metadata_status != "valid" else (STATIC / path.removeprefix("/static/")).read_text(),
            )
        elif path == "/static/js/MicrosoftTeams.min.js":
            route.fulfill(content_type="application/javascript", path=STATIC / "js/MicrosoftTeams.min.js")
        else:
            route.abort()

    page.route(f"{app_origin}/**", app_route)
    page.route(f"{parent_origin}/**", lambda route: route.fulfill(
        content_type="text/html",
        body=f"""<html><body><iframe src="{app_origin}/child"></iframe><script>
            window.addEventListener('message', event => {{
                if (event.data.func === 'initialize') {{
                    event.source.postMessage({{
                        id: event.data.id, args: ['content', 'web', 'en-us']
                    }}, '{app_origin}');
                }}
            }});
        </script></body></html>""",
    ))
    page.on("request", lambda request: external_assets.append(request.url)
            if (request.resource_type in {"script", "stylesheet", "font"} or "/validDomains.json" in request.url)
            and not request.url.startswith(app_origin + "/") else None)
    page.goto(f"{parent_origin}/parent")
    child = page.frame(url=f"{app_origin}/child")
    assert child is not None
    result = child.evaluate("""async () => {
        try {
            return await Promise.race([
                microsoftTeams.app.initialize().then(() => 'initialized', () => 'rejected'),
                new Promise(resolve => setTimeout(() => resolve('not-initialized'), 1800))
            ]);
        } catch { return 'rejected'; }
    }""")
    assert metadata_requests
    assert set(metadata_requests) == {app_origin + METADATA_URL}
    assert external_assets == []
    if parent_origin != "https://teams.microsoft.com.evil.example":
        assert result == "initialized"
    else:
        assert result != "initialized"

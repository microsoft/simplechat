# harness.py
"""Deterministic local Playwright harness for the classic Call agent modal UI tests.

Serves the real repository files from a local static HTTP server (no CDN, no
Azure/Cosmos/auth dependency) so the actual `_plugin_modal.html` /
`_agent_modal.html` partials and the real `plugin_modal_stepper.js` /
`agent_modal_stepper.js` modules execute in a genuine browser. Only API and
provider network calls are mocked per test via Playwright route handlers; the
served HTML/CSS/JS is the unmodified application source.
"""

from contextlib import contextmanager
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
import socket
from threading import Thread


REPO_ROOT = Path(__file__).resolve().parents[3]
APP_DIR = REPO_ROOT / "application" / "single_app"
TEMPLATES_DIR = APP_DIR / "templates"

# Toast/global stubs only replace things a full page normally provides (the
# app-wide toast container script and a public-workspace label helper); no
# stepper or modal behavior is stubbed here.
_GLOBAL_STUBS_SCRIPT = """
<script>
  window.__toasts = [];
  window.showToast = function (message, variant, options) {
    window.__toasts.push({ message: message, variant: variant, options: options || {} });
    var handle = { hide: function () {} };
    return handle;
  };
  window.getPublicWorkspaceLabel = function (kind) {
    var labels = {
      plural: 'Public Workspaces',
      lower_plural: 'public workspaces',
      lower_singular: 'public workspace'
    };
    return labels[kind] || 'Public Workspaces';
  };
</script>
"""

_BOOTSTRAP_ASSETS_HEAD = """
<link rel="stylesheet" href="/application/single_app/static/css/bootstrap.min.css" />
<link rel="stylesheet" href="/application/single_app/static/css/bootstrap-icons.min.css" />
"""

_BOOTSTRAP_BUNDLE_SCRIPT = (
    '<script src="/application/single_app/static/js/bootstrap/bootstrap.bundle.min.js"></script>'
)


def _get_free_local_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@contextmanager
def start_static_test_server():
    """Serve the real repository tree over plain HTTP on localhost.

    Mirrors the existing `test_agent_modal_icon_controls.py` harness pattern so
    ES module imports and local static asset links resolve against a genuine
    same-origin server, without any live app, Azure, or Cosmos dependency.
    """
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


def register_static_passthrough(page):
    """Map a bare `/static/...` request to the real Flask static folder.

    The static test server above serves the whole repository, so a request for
    `/application/single_app/static/...` already resolves correctly on its own
    and must be left alone. A handful of source files (for example
    `plugin_modal_stepper.js`'s `fetch('/static/json/schemas/plugin.schema.json')`
    call) hard-code the absolute `/static/...` path Flask itself would serve
    instead. This intercepts only that bare form and fulfills it from the real
    file on disk, so real schema/CSS/JS content is served rather than a stub;
    every other request falls through to the static test server unchanged.
    """

    def handler(route):
        request_path = urlparse(route.request.url).path.lstrip("/")
        if request_path.startswith("static/"):
            real_path = APP_DIR / request_path
            if real_path.is_file():
                route.fulfill(path=str(real_path))
                return
        route.fallback()

    page.route("**/static/**", handler)


def read_partial(template_name):
    """Return the raw source of a Jinja partial under templates/, unrendered.

    Matches the existing `test_agent_modal_icon_controls.py` precedent: the
    handful of Jinja interpolations left in these partials (unrelated settings
    defaults) render as harmless literal text and do not affect the Call agent
    controls under test.
    """
    return (TEMPLATES_DIR / template_name).read_text(encoding="utf-8")


def build_plugin_modal_page(partial_html):
    """Build a full HTML document hosting the real action modal + stepper module.

    Importing the real `plugin_modal_stepper.js` module triggers its own
    `if (document.getElementById('plugin-modal')) { window.pluginModalStepper =
    new PluginModalStepper(); }` bootstrap, exactly like the deployed app, once
    the partial markup above it has been parsed.
    """
    return f"""
    <!DOCTYPE html>
    <html lang="en">
      <head>
        <meta charset="utf-8" />
        {_BOOTSTRAP_ASSETS_HEAD}
      </head>
      <body>
        <div id="toast-container"></div>
        {partial_html}
        {_GLOBAL_STUBS_SCRIPT}
        {_BOOTSTRAP_BUNDLE_SCRIPT}
        <script type="module">
          import "/application/single_app/static/js/plugin_modal_stepper.js";
          window.__pluginModalHarnessReady = true;
        </script>
      </body>
    </html>
    """


def build_agent_modal_page(partial_html):
    """Build a full HTML document hosting the real agent modal + stepper module.

    `AgentModalStepper` has no page-level auto-bootstrap (entrypoint scripts
    always construct it explicitly with scope options), so this only exposes
    the real class on `window.AgentModalStepper`; each test instantiates it
    with the exact `(isAdmin, options)` arguments the classic entrypoint it is
    exercising would use.
    """
    return f"""
    <!DOCTYPE html>
    <html lang="en">
      <head>
        <meta charset="utf-8" />
        {_BOOTSTRAP_ASSETS_HEAD}
      </head>
      <body>
        <div id="toast-container"></div>
        {partial_html}
        {_GLOBAL_STUBS_SCRIPT}
        {_BOOTSTRAP_BUNDLE_SCRIPT}
        <script type="module">
          import {{ AgentModalStepper }} from "/application/single_app/static/js/agent_modal_stepper.js";
          window.AgentModalStepper = AgentModalStepper;
          window.__agentModalHarnessReady = true;
        </script>
      </body>
    </html>
    """


SAMPLE_AGENT_TARGETS = [
    {
        "id": "agent-writer",
        "name": "writer",
        "display_name": "Writer Agent",
        "description": "Drafts and edits long-form content.",
        "agent_type": "local",
        "scope_type": "personal",
        "scope_id": "current-user",
        "is_global": False,
        "is_group": False,
        "group_id": None,
    },
    {
        "id": "agent-researcher",
        "name": "researcher",
        "display_name": "Researcher Agent",
        "description": "Looks up supporting facts and citations.",
        "agent_type": "aifoundry",
        "scope_type": "personal",
        "scope_id": "current-user",
        "is_global": False,
        "is_group": False,
        "group_id": None,
    },
]

AGENT_ACTION_TYPES_RESPONSE = [
    {
        "type": "agent",
        "class": "AgentPlugin",
        "display": "Call agent",
        "description": "Delegate a task to the agent configured on this action.",
    },
    {
        "type": "generic",
        "class": "GenericPlugin",
        "display": "Generic API",
        "description": "A generic HTTP action.",
    },
]

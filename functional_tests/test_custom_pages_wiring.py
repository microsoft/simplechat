# test_custom_pages_wiring.py
"""
Functional test for Custom Pages wiring.
Version: 0.242.045
Implemented in: 0.242.023

This test ensures that the Custom Pages feature is wired through settings,
navigation, admin metadata management, and fail-closed host routes without
requiring live Cosmos DB connectivity.
"""

from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"


def read_text(relative_path):
    """Read a repository file as UTF-8 text."""
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def assert_contains(content, expected, description):
    """Assert that expected text is present in content."""
    if expected not in content:
        raise AssertionError(f"Missing {description}: {expected}")


def assert_not_contains(content, unexpected, description):
    """Assert that unexpected text is not present in content."""
    if unexpected in content:
        raise AssertionError(f"Unexpected {description}: {unexpected}")


def test_custom_pages_configuration():
    """Validate version, settings defaults, and Cosmos container wiring."""
    config = read_text("application/single_app/config.py")
    settings = read_text("application/single_app/functions_settings.py")

    assert_contains(config, 'VERSION = "0.242.045"', "version bump")
    assert_contains(config, 'cosmos_custom_pages_container_name = "custom_pages"', "custom pages container name")
    assert_contains(config, 'cosmos_custom_pages_container = cosmos_database.create_container_if_not_exists', "custom pages container creation")
    assert_contains(settings, "'enable_custom_pages': False", "custom pages disabled default")
    assert_contains(settings, "'custom_pages_menu_name': 'Custom Pages'", "custom pages menu name default")
    assert_contains(settings, "'custom_pages_force_menu': False", "custom pages force menu default")
    assert_contains(settings, "'access_request_button_enabled': False", "access request button disabled default")
    assert_contains(settings, "'access_request_page_url': '/custom/request-access'", "access request page URL default")


def test_custom_pages_routes_and_access_controls():
    """Validate that host routes are protected and fail closed when disabled."""
    routes = read_text("application/single_app/route_custom_pages.py")
    app = read_text("application/single_app/app.py")
    base_template = read_text("application/single_app/templates/base.html")

    for route in (
        '@app.route("/custom/<slug>", methods=["GET"])',
        '@app.route("/custom/<slug>.html", methods=["GET"])',
        '@app.route("/custom/assets/<slug>/<folder>/<path:filename>", methods=["GET"])',
        '@app.route("/api/custom/<slug>/<path:operation>", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])',
        '@app.route("/api/admin/custom-pages", methods=["GET"])',
        '@app.route("/api/admin/custom-pages/developer-guide", methods=["GET"])',
    ):
        assert_contains(routes, route, f"route declaration {route}")

    assert_contains(routes, "@swagger_route(security=get_auth_security())", "Swagger security decorator")
    assert_contains(routes, "@login_required", "login requirement")
    assert_not_contains(routes, "@user_required", "blanket user requirement on custom page routes")
    assert_contains(routes, "@admin_required", "admin requirement")
    assert_contains(routes, "if not is_custom_pages_enabled(settings):", "feature flag gate")
    assert_contains(routes, "return None, settings, _custom_pages_disabled_response()", "fail-closed disabled response")
    assert_contains(routes, "def custom_page_html_alias", "HTML alias custom page route")
    assert_contains(routes, "request-access", "request access metadata helper route")
    assert_contains(routes, "access_request_button_enabled", "access request button settings update")
    assert_contains(routes, "A custom page with this slug already exists.", "duplicate slug create guard")
    assert_contains(app, "register_route_custom_pages(app)", "custom page route registration")
    assert_contains(app, "custom_pages_nav=custom_pages_nav", "custom page navigation context")
    assert_contains(base_template, "_custom_pages_drawer.html", "custom pages drawer include")


def test_custom_pages_admin_and_navigation_wiring():
    """Validate Admin Settings and user navigation templates include Custom Pages."""
    admin_template = read_text("application/single_app/templates/admin_settings.html")
    admin_route = read_text("application/single_app/route_frontend_admin_settings.py")
    top_nav = read_text("application/single_app/templates/_top_nav.html")
    sidebar_nav = read_text("application/single_app/templates/_sidebar_nav.html")
    admin_js = read_text("application/single_app/static/js/admin/admin_custom_pages.js")

    for element_id in (
        "custom-pages-tab",
        "custom-pages-section",
        "enable_custom_pages",
        "custom_pages_menu_name",
        "custom_pages_force_menu",
        "custom_pages_restart_acknowledged",
        "customPagesRestartModal",
        "custom-pages-restart-acknowledge-btn",
        "custom-pages-guide-btn",
        "customPagesGuideModal",
        "custom-pages-guide-content",
        "customPageDesignerModal",
        "custom-pages-tbody",
        "add-custom-page-btn",
        "create-request-access-page-btn",
        "requestAccessPageCreatedModal",
        "custom_page_access_level",
        "custom-page-slug-feedback",
        "data-custom-page-file-input",
        "data-custom-page-file-add",
        "data-custom-page-file-list",
        "Deployed Files",
        "Publishing",
    ):
        assert_contains(admin_template, element_id, f"admin template element {element_id}")

    assert_contains(admin_template, "admin_custom_pages.js", "custom pages admin script include")
    assert_contains(admin_route, "enable_custom_pages = form_data.get('enable_custom_pages') == 'on'", "custom pages toggle save")
    assert_contains(admin_route, "custom_pages_restart_acknowledged = form_data.get('custom_pages_restart_acknowledged') == 'on'", "custom pages restart acknowledgement parsing")
    assert_contains(admin_route, "custom_pages_enabled_acknowledged", "custom pages restart acknowledgement activity log")
    assert_contains(admin_route, "'custom_pages_menu_name': custom_pages_menu_name", "custom pages menu name save")
    assert_contains(admin_route, "'access_request_button_enabled': bool(settings.get('access_request_button_enabled', False))", "access request setting preservation")
    index_template = read_text("application/single_app/templates/index.html")
    assert_contains(index_template, "access_request_button_enabled", "access denied request access button")
    assert_contains(top_nav, "custom_pages_nav", "top navigation custom pages")
    assert_contains(top_nav, "session.get('user') and app_settings.enable_custom_pages and custom_pages_nav", "top navigation custom pages visibility gate")
    assert_contains(top_nav, "custom-pages-dropdown-menu", "bounded custom pages top navigation menu")
    assert_contains(top_nav, "custom_pages_drawer_threshold = 5", "custom pages drawer threshold")
    assert_contains(top_nav, "custom-pages-top-drawer-trigger", "top navigation drawer trigger")
    assert_contains(top_nav, "data-custom-pages-open-drawer", "top navigation drawer trigger attribute")
    assert_not_contains(top_nav, "No custom pages registered", "top navigation empty custom pages state")
    assert_contains(sidebar_nav, "custom-pages-links-section", "sidebar custom pages section")
    assert_contains(sidebar_nav, "session.get('user') and app_settings.enable_custom_pages and custom_pages_nav", "sidebar custom pages visibility gate")
    assert_contains(sidebar_nav, "custom-pages-count-badge", "sidebar custom pages count badge")
    assert_contains(sidebar_nav, "custom-pages-menu-list", "sidebar custom pages scrollable menu")
    assert_contains(sidebar_nav, "custom_pages_drawer_threshold = 5", "sidebar custom pages drawer threshold")
    assert_contains(sidebar_nav, "data-custom-pages-open-drawer", "sidebar drawer trigger")
    assert_not_contains(sidebar_nav, "No custom pages registered", "sidebar empty custom pages state")
    assert_contains(admin_js, "fetch(\"/api/admin/custom-pages\")", "admin API list call")
    assert_contains(admin_js, "createRequestAccessPage", "request access one-click helper")
    assert_contains(admin_js, "/api/admin/custom-pages/request-access-example", "request access helper API call")
    assert_contains(admin_js, "requestAccessPageExists", "request access duplicate button state")
    assert_contains(admin_js, "validateCustomPageSlugUniqueness", "custom page slug uniqueness validation")
    assert_contains(admin_js, "Choose a unique slug before saving this custom page.", "custom page duplicate slug save guard")
    assert_contains(admin_js, "customPagesInitiallyEnabled", "custom pages restart modal initial state")
    assert_contains(admin_js, "restartAcknowledgementField.value = \"on\"", "custom pages restart acknowledgement client flag")
    assert_contains(admin_js, "loadCustomPagesGuide", "custom pages developer guide modal loader")
    assert_contains(admin_js, "DOMPurify.sanitize(marked.parse(markdown))", "custom pages developer guide sanitized markdown rendering")
    assert_contains(admin_js, "setupCustomPageFileListEditors", "custom pages file list editor setup")
    assert_contains(admin_js, "addCustomPageFile", "custom pages file list add action")
    assert_contains(admin_js, "removeCustomPageFile", "custom pages file list remove action")
    assert_contains(admin_js, "textContent", "safe DOM text rendering")

    drawer_template = read_text("application/single_app/templates/_custom_pages_drawer.html")
    assert_contains(drawer_template, "customPagesDrawer", "custom pages drawer id")
    assert_contains(drawer_template, "custom-pages-drawer-list", "custom pages drawer scroll list")
    assert_contains(drawer_template, "data-custom-pages-open-drawer", "custom pages drawer trigger handler")
    assert_contains(drawer_template, "session.get('user') and app_settings.enable_custom_pages and custom_pages_nav", "drawer custom pages visibility gate")
    assert_not_contains(drawer_template, "No custom pages registered", "drawer empty custom pages state")


def test_custom_pages_trusted_rendering_boundary():
    """Validate the trusted static HTML shell documents the XSS boundary."""
    shell = read_text("application/single_app/templates/custom_page_shell.html")
    helpers = read_text("application/single_app/functions_custom_pages.py")

    assert_contains(shell, "xss-check: ignore", "trusted HTML XSS suppression")
    assert_contains(shell, "deployment-time trusted app-team content", "trusted HTML explanation")
    assert_contains(shell, "{{ custom_page_html | safe }}", "trusted HTML render boundary")
    assert_contains(helpers, "SLUG_PATTERN", "slug validation")
    assert_contains(helpers, "validate_custom_page_file_reference", "file reference validation")
    assert_contains(helpers, "ACCESS_LEVELS", "custom page access level validation")
    assert_contains(helpers, '"access_level": str(page.get("access_level") or "app_user").strip().lower()', "custom page access level normalization")
    assert_contains(helpers, 'access_level != "authenticated"', "app-user access level enforcement")
    assert_contains(helpers, "os.path.commonpath", "path traversal guard")
    assert_contains(helpers, "_file_reference_is_declared", "asset declaration guard")
    assert_not_contains(helpers, 'if "Admin" in role_set:', "Admin custom page authorization override")
    assert_contains(helpers, "required_role_set = set(required_roles)", "custom page required role set")
    assert_contains(helpers, "if role_set.intersection(required_role_set):", "custom page exact role match")
    assert_contains(helpers, 'return "Admin" in role_set and "User" in required_role_set', "Admin implies User custom page role")


def test_custom_pages_examples_and_request_access_page():
    """Validate docs-only examples and the live Request Access page."""
    docs_example_files = [
        "docs/how-to/custom_pages_examples/simple-html/example-simple.html",
        "docs/how-to/custom_pages_examples/static-html-css-js/example-static.html",
        "docs/how-to/custom_pages_examples/static-html-css-js/example-static.css",
        "docs/how-to/custom_pages_examples/static-html-css-js/example-static.js",
        "docs/how-to/custom_pages_examples/static-html-css-js/cat.mp4",
        "docs/how-to/custom_pages_examples/python-jinja-api/example-python-dashboard.html",
        "docs/how-to/custom_pages_examples/python-jinja-api/example-python-dashboard.css",
        "docs/how-to/custom_pages_examples/python-jinja-api/example-python-dashboard.js",
        "docs/how-to/custom_pages_examples/python-jinja-api/example_python_dashboard.py",
    ]

    live_request_access_files = [
        "application/single_app/custom_pages/html/request-access.html",
        "application/single_app/custom_pages/css/request-access.css",
    ]

    for relative_path in docs_example_files + live_request_access_files:
        if not (REPO_ROOT / relative_path).exists():
            raise AssertionError(f"Missing custom page file: {relative_path}")

    removed_live_examples = [
        "application/single_app/custom_pages/html/example-simple.html",
        "application/single_app/custom_pages/html/example-static.html",
        "application/single_app/custom_pages/html/example-python-dashboard.html",
        "application/single_app/custom_pages/css/example-static.css",
        "application/single_app/custom_pages/js/example-static.js",
        "application/single_app/custom_pages/python/example_python_dashboard.py",
        "application/single_app/docs/how-to/custom_pages_examples/simple-html/example-simple.html",
        "application/single_app/docs/how-to/custom_pages_examples/static-html-css-js/example-static.html",
        "application/single_app/docs/how-to/custom_pages_examples/static-html-css-js/cat.mp4",
        "application/single_app/docs/how-to/custom_pages_examples/python-jinja-api/example_python_dashboard.py",
    ]
    for relative_path in removed_live_examples:
        if (REPO_ROOT / relative_path).exists():
            raise AssertionError(f"Example file should live in docs, not live custom_pages: {relative_path}")

    simple_html = read_text("docs/how-to/custom_pages_examples/simple-html/example-simple.html")
    static_html = read_text("docs/how-to/custom_pages_examples/static-html-css-js/example-static.html")
    static_js = read_text("docs/how-to/custom_pages_examples/static-html-css-js/example-static.js")
    python_extension = read_text("docs/how-to/custom_pages_examples/python-jinja-api/example_python_dashboard.py")
    python_template = read_text("docs/how-to/custom_pages_examples/python-jinja-api/example-python-dashboard.html")
    request_access_html = read_text("application/single_app/custom_pages/html/request-access.html")

    assert_contains(simple_html, "Hello from a custom HTML page", "simple HTML example content")
    assert_contains(static_html, "data-static-example", "static example root hook")
    assert_contains(static_html, "/custom/assets/example-static/assets/cat.mp4", "static example video asset URL")
    assert_contains(static_html, "<video", "static example video viewer")
    assert_contains(static_js, "addEventListener", "static example JavaScript behavior")
    assert_contains(python_extension, '"slug": "example-python-dashboard"', "Python example slug metadata")
    assert_contains(python_extension, "def handle_api", "Python example backend API handler")
    assert_contains(python_template, "{% extends \"base.html\" %}", "Python example Jinja template")
    assert_contains(request_access_html, "accessrequest@example.com", "request access mail recipient")
    assert_contains(request_access_html, "SimpleChat%20Access%20Request", "request access mail subject")


def test_custom_pages_developer_guide_single_source():
    """Validate the Custom Pages how-to is the source for the in-app guide."""
    dockerfile = read_text("application/single_app/Dockerfile")
    app_guide = read_text("application/single_app/docs/how-to/custom_pages.md")
    docs_guide = read_text("docs/how-to/custom_pages.md")
    index = read_text("docs/how-to/index.md")

    if "docs/how-to/custom_pages.md" in dockerfile:
        raise AssertionError("Dockerfile should not depend on repository-level docs for Custom Pages guide content.")
    assert_contains(app_guide, "# Create Custom Pages", "custom pages canonical app guide title")
    assert_contains(app_guide, "Pattern 1: Simple HTML Page", "simple HTML guide section")
    assert_contains(app_guide, "Pattern 2: Static HTML, CSS, and JavaScript Page", "static page guide section")
    assert_contains(app_guide, "Pattern 3: Python-Backed Jinja Page with Backend API", "Python-backed page guide section")
    assert_contains(docs_guide, "application/single_app/docs/how-to/custom_pages.md", "docs how-to pointer to in-app guide")
    assert_contains(docs_guide, "Do not duplicate the full guide", "docs how-to duplication warning")
    assert_contains(index, "/how-to/custom_pages/", "how-to index custom pages link")


def run_tests():
    """Run all Custom Pages wiring tests."""
    tests = [
        test_custom_pages_configuration,
        test_custom_pages_routes_and_access_controls,
        test_custom_pages_admin_and_navigation_wiring,
        test_custom_pages_trusted_rendering_boundary,
        test_custom_pages_examples_and_request_access_page,
        test_custom_pages_developer_guide_single_source,
    ]
    results = []

    for test in tests:
        print(f"Running {test.__name__}...")
        try:
            test()
            print(f"Passed {test.__name__}")
            results.append(True)
        except Exception as ex:
            print(f"Failed {test.__name__}: {ex}")
            results.append(False)

    print(f"Results: {sum(results)}/{len(results)} tests passed")
    return all(results)


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
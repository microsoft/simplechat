# test_control_center_management_pagination.py
#!/usr/bin/env python3
"""
Functional test for Control Center management pagination.
Version: 0.241.030
Implemented in: 0.241.030

This test ensures that user, group, and public workspace management views expose
consistent page-size controls, send server-side pagination parameters, and keep
public workspace table UX aligned with group management. It also validates that
management search fields include IDs.
"""

import re
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
ROUTE_FILE = ROOT_DIR / "application" / "single_app" / "route_backend_control_center.py"
TEMPLATE_FILE = ROOT_DIR / "application" / "single_app" / "templates" / "control_center.html"
JS_FILE = ROOT_DIR / "application" / "single_app" / "static" / "js" / "control-center.js"


EXPECTED_PAGE_SIZE_OPTIONS = ["10", "25", "50", "100", "250"]
PAGE_SIZE_SELECT_IDS = [
    "userManagementPerPageSelect",
    "groupManagementPerPageSelect",
    "publicWorkspaceManagementPerPageSelect",
]


def assert_contains(source, expected, description):
    """Assert that source contains the expected text."""
    if expected not in source:
        raise AssertionError(f"Missing {description}: {expected}")


def get_select_options(template_source, select_id):
    """Extract option values from a select element by id."""
    match = re.search(
        rf'<select[^>]+id="{re.escape(select_id)}"[^>]*>(.*?)</select>',
        template_source,
        flags=re.DOTALL,
    )
    if not match:
        raise AssertionError(f"Could not find select element with id {select_id}")

    return re.findall(r'<option\s+value="([^"]+)"', match.group(1))


def test_backend_pagination_parser(route_source):
    """Validate shared backend parsing and endpoint usage."""
    assert_contains(
        route_source,
        "CONTROL_CENTER_MANAGEMENT_DEFAULT_PER_PAGE = 25",
        "default management page size",
    )
    assert_contains(
        route_source,
        "CONTROL_CENTER_MANAGEMENT_MAX_PER_PAGE = 250",
        "maximum management page size",
    )
    assert route_source.count("page, per_page = parse_control_center_management_pagination(request.args)") >= 3
    assert_contains(route_source, "'total_items': total_count", "public workspace total_items alias")
    assert_contains(route_source, "workspace.get('status') or 'active'", "public workspace status filtering")
    assert_contains(route_source, "NOT IS_DEFINED(c.status)", "active group default status filtering")


def test_template_page_size_controls(template_source):
    """Validate the three management controls expose the same page-size options."""
    for select_id in PAGE_SIZE_SELECT_IDS:
        options = get_select_options(template_source, select_id)
        if options != EXPECTED_PAGE_SIZE_OPTIONS:
            raise AssertionError(f"Unexpected options for {select_id}: {options}")

    assert "id=\"publicWorkspaceStatusFilterSelect\"" in template_source
    assert "onkeyup=\"controlCenter.searchPublicWorkspaces" not in template_source
    assert "onchange=\"controlCenter.filterPublicWorkspacesByStatus" not in template_source


def test_management_search_fields_include_ids(route_source, template_source):
    """Validate management search boxes and backend filters include IDs."""
    expected_placeholders = [
        'placeholder="Search users by name, email, or ID..."',
        'placeholder="Search groups by name, owner, or ID..."',
        'placeholder="Search workspaces by name, description, owner, or ID..."',
    ]
    for placeholder in expected_placeholders:
        assert_contains(template_source, placeholder, "ID-aware search placeholder")

    expected_search_clauses = [
        "CONTAINS(LOWER(c.id), @search)",
        "CONTAINS(LOWER(c.owner.id), @search)",
        "CONTAINS(LOWER(c.owner.email), @search)",
        "CONTAINS(LOWER(c.owner.displayName), @search)",
        "CONTAINS(LOWER(c.id), @search_term)",
        "CONTAINS(LOWER(c.owner.userId), @search_term)",
        "CONTAINS(LOWER(c.owner.email), @search_term)",
        "CONTAINS(LOWER(c.owner.displayName), @search_term)",
    ]
    for clause in expected_search_clauses:
        assert_contains(route_source, clause, "ID-aware backend search clause")

    if route_source.count("CONTAINS(LOWER(c.id), @search)") < 2:
        raise AssertionError("User and group management should both search c.id")


def test_public_workspace_management_table_alignment(template_source, js_source):
    """Validate public workspace management uses the group-style table UX."""
    public_tab_match = re.search(
        r'<!-- Public Workspace Management Tab -->(.*?)<!-- Activity Logs Tab -->',
        template_source,
        flags=re.DOTALL,
    )
    if not public_tab_match:
        raise AssertionError("Could not locate public workspace management tab")

    public_tab_source = public_tab_match.group(1)
    assert_contains(public_tab_source, '<div class="card">', "public workspace management card shell")
    assert_contains(
        public_tab_source,
        'class="table table-hover group-table align-middle" id="publicWorkspacesTable"',
        "group-style public workspace table class",
    )
    for sort_key in ["name", "owner", "members", "status", "documents"]:
        assert_contains(public_tab_source, f'class="sortable" data-sort="{sort_key}"', f"sortable {sort_key} header")

    if "disablePublicWorkspaceCreation" in public_tab_source or "Disable Public Workspace Creation" in public_tab_source:
        raise AssertionError("Public workspace management should not add a disable-creation control")

    assert_contains(js_source, "window.publicWorkspaceTableSorter", "public workspace table sorter")
    assert_contains(js_source, "new GroupTableSorter('publicWorkspacesTable')", "public workspace sorter initialization")


def test_client_pagination_state(js_source):
    """Validate the client sends selected pagination parameters for each view."""
    expected_snippets = [
        "this.usersPerPage = CONTROL_CENTER_MANAGEMENT_DEFAULT_PAGE_SIZE",
        "handleUserPerPageChange(event)",
        "handleGroupPerPageChange(event)",
        "handlePublicWorkspacePerPageChange(event)",
        "renderGroupsPagination(data.pagination)",
        "renderPublicWorkspacesPagination(data.pagination)",
        "renderManagementPagination(pagination, options)",
        "paginationNav.replaceChildren()",
        "page: this.groupPage",
        "per_page: this.groupsPerPage",
        "page: this.publicWorkspacePage",
        "per_page: this.publicWorkspacesPerPage",
    ]

    for snippet in expected_snippets:
        assert_contains(js_source, snippet, "client pagination state")

    if "page: 1,\n                per_page: 100" in js_source:
        raise AssertionError("Group/public management still hard-codes page 1 and per_page 100")


def run_all_tests():
    """Run all source-level regression checks."""
    print("Testing Control Center management pagination source changes...")

    route_source = ROUTE_FILE.read_text(encoding="utf-8")
    template_source = TEMPLATE_FILE.read_text(encoding="utf-8")
    js_source = JS_FILE.read_text(encoding="utf-8")

    test_backend_pagination_parser(route_source)
    print("Backend pagination parser checks passed")

    test_template_page_size_controls(template_source)
    print("Template page-size control checks passed")

    test_management_search_fields_include_ids(route_source, template_source)
    print("Management ID search checks passed")

    test_public_workspace_management_table_alignment(template_source, js_source)
    print("Public workspace management table alignment checks passed")

    test_client_pagination_state(js_source)
    print("Client pagination state checks passed")

    print("All Control Center management pagination checks passed")
    return True


if __name__ == "__main__":
    try:
        success = run_all_tests()
    except Exception as ex:
        print(f"Test failed: {ex}")
        import traceback
        traceback.print_exc()
        success = False

    sys.exit(0 if success else 1)

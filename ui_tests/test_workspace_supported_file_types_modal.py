# test_workspace_supported_file_types_modal.py
"""
UI contract test for workspace supported file type modals.
Version: 0.261.142
Implemented in: 0.250.014
OneNote coverage ported in: 0.261.142

This test ensures personal, group, and public workspace document upload areas
stay compact and expose categorized supported file types through Bootstrap modals.
"""

import ast
from pathlib import Path

import pytest


jinja2 = pytest.importorskip("jinja2")


ROOT_DIR = Path(__file__).resolve().parents[1]
TEMPLATES_DIR = ROOT_DIR / "application" / "single_app" / "templates"
STATIC_DIR = ROOT_DIR / "application" / "single_app" / "static"

WORKSPACE_TEMPLATES = {
    "workspace.html": "workspaceSupportedFileTypesModal",
    "group_workspaces.html": "groupSupportedFileTypesModal",
    "public_workspaces.html": "publicSupportedFileTypesModal",
}


def _read(relative_path: str) -> str:
    return (ROOT_DIR / relative_path).read_text(encoding="utf-8")


def test_supported_file_type_templates_parse() -> None:
    """Validate the affected Jinja templates and shared macro parse."""
    environment = jinja2.Environment(
        loader=jinja2.FileSystemLoader(TEMPLATES_DIR),
        autoescape=jinja2.select_autoescape(["html"]),
    )

    for template_name in ["_supported_file_types_modal.html", *WORKSPACE_TEMPLATES.keys()]:
        source = (TEMPLATES_DIR / template_name).read_text(encoding="utf-8")
        environment.parse(source)


def test_workspace_upload_areas_use_compact_modal_trigger() -> None:
    """Validate upload areas link to the modal instead of rendering a long extension list."""
    for template_name, modal_id in WORKSPACE_TEMPLATES.items():
        content = (TEMPLATES_DIR / template_name).read_text(encoding="utf-8")

        assert "{{ allowed_extensions }}" not in content
        assert "workspace-upload-area text-center py-2 px-3" in content
        assert "bi-cloud-arrow-up display-4" not in content
        assert "View all supported file types" in content
        assert f'data-bs-target="#{modal_id}"' in content
        assert f"supported_file_types_modal('{modal_id}'" in content
        assert "allowed_extension_categories" in content


def test_workspace_routes_pass_supported_file_type_categories() -> None:
    """Validate routes provide categorized extension data for each workspace page."""
    route_files = [
        "application/single_app/route_frontend_workspace.py",
        "application/single_app/route_frontend_group_workspaces.py",
        "application/single_app/route_frontend_public_workspaces.py",
    ]

    for route_file in route_files:
        content = _read(route_file)

        assert "get_allowed_extension_categories(" in content
        assert "allowed_extension_categories=allowed_extension_categories" in content
        assert "allowed_extensions_str" not in content


def test_supported_file_type_modal_trigger_does_not_open_file_picker() -> None:
    """Validate modal trigger clicks are excluded from dropzone file-input clicks."""
    personal_js = _read("application/single_app/static/js/workspace/workspace-documents.js")
    public_js = _read("application/single_app/static/js/public/public_workspace.js")
    group_template = (TEMPLATES_DIR / "group_workspaces.html").read_text(encoding="utf-8")

    assert '!e.target.closest(".workspace-upload-supported-types-trigger")' in personal_js
    assert "!e.target.closest('.workspace-upload-supported-types-trigger')" in public_js
    assert '!e.target.closest(".workspace-upload-supported-types-trigger")' in group_template


def test_supported_file_type_modal_styles_exist() -> None:
    """Validate compact upload area and modal badge styles are available."""
    css = (STATIC_DIR / "css" / "workspace-responsive.css").read_text(encoding="utf-8")

    assert ".workspace-upload-area" in css
    assert "min-height: 6.5rem" in css
    assert ".workspace-upload-supported-types-trigger" in css
    assert ".supported-file-type-list" in css


def _allowed_categories():
    """Read the actual format configuration without initializing Azure clients."""
    path = ROOT_DIR / "application" / "single_app" / "config.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    namespace = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Set):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id.endswith("EXTENSIONS"):
                    namespace[target.id] = ast.literal_eval(node.value)
        elif isinstance(node, ast.FunctionDef) and node.name == "get_allowed_extension_categories":
            exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), "exec"), namespace)
    categories = namespace["get_allowed_extension_categories"]()
    return categories


def test_onenote_formats_render_in_every_workspace_modal():
    """The shared modal advertises both native formats and their text-only scope."""
    environment = jinja2.Environment(
        loader=jinja2.FileSystemLoader(TEMPLATES_DIR),
        autoescape=jinja2.select_autoescape(["html"]),
    )
    macro = environment.get_template("_supported_file_types_modal.html").module.supported_file_types_modal
    categories = _allowed_categories()
    for modal_id in WORKSPACE_TEMPLATES.values():
        markup = str(macro(modal_id, "Supported file types", categories))
        assert "OneNote (typed text and tables)" in markup
        assert '>.one</span>' in markup
        assert '>.onepkg</span>' in markup
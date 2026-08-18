#!/usr/bin/env python3
# test_content_understanding_extraction_engine.py
"""
Functional test for Enhanced extraction backed by Azure AI Content Understanding.
Version: 0.250.224
Implemented in: 0.250.221

This test ensures that the Content Understanding client parses analyzer results into the same
page shape Document Intelligence returns, that Enhanced extraction resolves to the right engine
per Azure cloud and configuration, and that Enhanced always falls back to Document Intelligence
Layout instead of failing ingestion.
"""

import sys
import types
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_support.versioning import assert_app_version_at_least  # noqa: E402


def load_content_understanding_module(azure_environment="public"):
    """Import functions_content_understanding with its Azure-dependent imports stubbed out.

    The real config module builds live Azure clients at import time, so the test injects
    minimal stand-ins for the handful of names the client module actually uses.
    """
    for module_name in (
        "config",
        "functions_appinsights",
        "functions_debug",
        "functions_settings",
        "azure",
        "azure.identity",
        "functions_content_understanding",
    ):
        sys.modules.pop(module_name, None)

    config_module = types.ModuleType("config")
    config_module.AZURE_ENVIRONMENT = azure_environment
    config_module.cognitive_services_scope = "https://cognitiveservices.azure.com/.default"
    sys.modules["config"] = config_module

    appinsights_module = types.ModuleType("functions_appinsights")
    appinsights_module.log_event = lambda *args, **kwargs: None
    sys.modules["functions_appinsights"] = appinsights_module

    debug_module = types.ModuleType("functions_debug")
    debug_module.debug_print = lambda *args, **kwargs: None
    sys.modules["functions_debug"] = debug_module

    azure_module = types.ModuleType("azure")
    identity_module = types.ModuleType("azure.identity")

    class _StubCredential:
        def get_token(self, *args, **kwargs):
            raise AssertionError("Managed identity token should not be requested in this test.")

    identity_module.DefaultAzureCredential = _StubCredential
    azure_module.identity = identity_module
    sys.modules["azure"] = azure_module
    sys.modules["azure.identity"] = identity_module

    settings_module = _build_settings_stub(azure_environment)
    sys.modules["functions_settings"] = settings_module

    sys.path.insert(0, str(APP_ROOT))
    try:
        import functions_content_understanding  # noqa: PLC0415
    finally:
        sys.path.remove(str(APP_ROOT))

    return functions_content_understanding, settings_module


def _build_settings_stub(azure_environment):
    """Build a functions_settings stand-in mirroring the real normalizer contract."""
    settings_module = types.ModuleType("functions_settings")
    settings_module.CONTENT_UNDERSTANDING_DOCUMENT_ANALYZER_DEFAULT = "prebuilt-documentSearch"
    settings_module.CONTENT_UNDERSTANDING_IMAGE_ANALYZER_DEFAULT = "prebuilt-imageSearch"
    settings_module.CONTENT_UNDERSTANDING_API_VERSION_DEFAULT = "2025-11-01"
    settings_module.EXTRACTION_ENGINE_DOCUMENT_INTELLIGENCE = "document_intelligence"
    settings_module.EXTRACTION_ENGINE_CONTENT_UNDERSTANDING = "content_understanding"

    settings_module.normalize_content_understanding_endpoint = (
        lambda value: str(value or "").strip().rstrip("/")
    )
    settings_module.normalize_content_understanding_authentication_type = (
        lambda value: "managed_identity" if str(value or "").strip().lower() == "managed_identity" else "key"
    )
    settings_module.normalize_content_understanding_api_version = (
        lambda value: str(value or "").strip() or "2025-11-01"
    )
    settings_module.normalize_content_understanding_analyzer_id = (
        lambda value, default_analyzer_id=None: str(value or "").strip()
        or (default_analyzer_id or "prebuilt-documentSearch")
    )
    settings_module.is_content_understanding_supported_environment = (
        lambda *args, **kwargs: azure_environment == "public"
    )
    settings_module.get_content_understanding_config = lambda settings: {
        "endpoint": str((settings or {}).get("azure_content_understanding_endpoint") or "").rstrip("/"),
        "key": str((settings or {}).get("azure_content_understanding_key") or ""),
        "authentication_type": (settings or {}).get("azure_content_understanding_authentication_type") or "key",
        "api_version": "2025-11-01",
        "analyzer_id": "prebuilt-documentSearch",
        "image_analyzer_id": "prebuilt-imageSearch",
    }
    settings_module.get_settings = lambda: {}
    return settings_module


def build_sample_analyzer_result():
    """Build a Content Understanding document result shaped like the documented REST response."""
    page_one_markdown = "# Quarterly Report\n\nRevenue grew.\n\n"
    page_two_markdown = "| Region | Total |\n| --- | --- |\n| West | 42 |\n"
    markdown = page_one_markdown + page_two_markdown

    return {
        "analyzerId": "prebuilt-documentSearch",
        "apiVersion": "2025-11-01",
        "contents": [
            {
                "kind": "document",
                "markdown": markdown,
                "mimeType": "application/pdf",
                "startPageNumber": 1,
                "endPageNumber": 2,
                "unit": "inch",
                "pages": [
                    {
                        "pageNumber": 1,
                        "spans": [{"offset": 0, "length": len(page_one_markdown)}],
                    },
                    {
                        "pageNumber": 2,
                        "spans": [
                            {"offset": len(page_one_markdown), "length": len(page_two_markdown)}
                        ],
                    },
                ],
                "figures": [
                    {
                        "id": "fig-1",
                        "kind": "chart",
                        "description": "A bar chart comparing quarterly revenue by region.",
                        "caption": {"content": "Figure 1: Revenue"},
                        "span": {"offset": 5, "length": 10},
                    },
                    {
                        "id": "fig-2",
                        "kind": "mermaid",
                        "description": "A flowchart of the approval process.",
                        "content": "graph TD\n  A[Start] --> B{Decision}",
                        "span": {"offset": len(page_one_markdown) + 3, "length": 8},
                    },
                ],
            }
        ],
    }


def test_page_reconstruction_from_spans():
    """Content Understanding markdown must be split back into per-page content."""
    print("Testing Content Understanding page reconstruction...")

    content_understanding, _ = load_content_understanding_module()
    pages = content_understanding.build_pages_from_content_understanding_result(
        build_sample_analyzer_result()
    )

    if len(pages) != 2:
        raise AssertionError(f"Expected 2 reconstructed pages, got {len(pages)}: {pages}")

    if pages[0]["page_number"] != 1 or pages[1]["page_number"] != 2:
        raise AssertionError(f"Page numbers were not preserved: {pages}")

    if "Quarterly Report" not in pages[0]["content"]:
        raise AssertionError("Page 1 lost its heading content.")
    if "| Region | Total |" not in pages[1]["content"]:
        raise AssertionError("Page 2 lost its markdown table.")
    if "Quarterly Report" in pages[1]["content"]:
        raise AssertionError("Page 2 incorrectly absorbed page 1 content.")

    print("Page reconstruction test passed!")
    return True


def test_figure_descriptions_attach_to_their_page():
    """Figure descriptions must land on the page whose span range contains them."""
    print("Testing Content Understanding figure attribution...")

    content_understanding, _ = load_content_understanding_module()
    pages = content_understanding.build_pages_from_content_understanding_result(
        build_sample_analyzer_result()
    )

    page_one_content = pages[0]["content"]
    page_two_content = pages[1]["content"]

    if "bar chart comparing quarterly revenue" not in page_one_content:
        raise AssertionError("Chart figure description was not attached to page 1.")
    if "flowchart of the approval process" not in page_two_content:
        raise AssertionError("Mermaid figure description was not attached to page 2.")
    if "```mermaid" not in page_two_content:
        raise AssertionError("Mermaid figure content was not preserved.")
    if "bar chart comparing quarterly revenue" in page_two_content:
        raise AssertionError("Chart figure description leaked onto page 2.")

    print("Figure attribution test passed!")
    return True


def test_inline_figure_descriptions_are_not_duplicated():
    """Descriptions already inlined in the markdown must not be appended a second time."""
    print("Testing Content Understanding figure de-duplication...")

    content_understanding, _ = load_content_understanding_module()
    description = "A bar chart comparing quarterly revenue by region."
    markdown = f"# Report\n\n{description}\n"

    result = {
        "contents": [
            {
                "kind": "document",
                "markdown": markdown,
                "startPageNumber": 1,
                "pages": [{"pageNumber": 1, "spans": [{"offset": 0, "length": len(markdown)}]}],
                "figures": [
                    {
                        "id": "fig-1",
                        "kind": "chart",
                        "description": description,
                        "span": {"offset": 10, "length": 5},
                    }
                ],
            }
        ]
    }

    pages = content_understanding.build_pages_from_content_understanding_result(result)
    if pages[0]["content"].count(description) != 1:
        raise AssertionError(
            f"Figure description was duplicated on the page: {pages[0]['content']!r}"
        )

    print("Figure de-duplication test passed!")
    return True


def test_missing_pages_falls_back_to_whole_markdown():
    """A result without per-page spans still yields a single usable page."""
    print("Testing Content Understanding page fallback...")

    content_understanding, _ = load_content_understanding_module()
    result = {"contents": [{"kind": "document", "markdown": "Just some text.", "startPageNumber": 1}]}

    pages = content_understanding.build_pages_from_content_understanding_result(result)
    if len(pages) != 1 or pages[0]["content"] != "Just some text.":
        raise AssertionError(f"Unexpected fallback page output: {pages}")

    print("Page fallback test passed!")
    return True


def test_missing_model_deployment_error_is_explained():
    """The generic Azure model-deployment failure must become actionable admin guidance."""
    print("Testing Content Understanding model deployment guidance...")

    content_understanding, _ = load_content_understanding_module()

    if not content_understanding._looks_like_missing_model_deployment(
        "No default model deployment configured for this resource."
    ):
        raise AssertionError("Missing model deployment errors were not detected.")
    if content_understanding._looks_like_missing_model_deployment("Invalid subscription key."):
        raise AssertionError("Unrelated errors were misclassified as deployment failures.")

    print("Model deployment guidance test passed!")
    return True


def test_government_cloud_blocks_content_understanding():
    """Content Understanding must refuse to run in clouds where it is unavailable."""
    print("Testing Content Understanding environment gate...")

    content_understanding, _ = load_content_understanding_module(azure_environment="usgovernment")

    is_ok, message = content_understanding.test_content_understanding_connection(
        {"endpoint": "https://example.services.ai.azure.com", "key": "fake-key"}
    )
    if is_ok:
        raise AssertionError("Content Understanding should be unavailable in usgovernment.")
    if "not available" not in message.lower():
        raise AssertionError(f"Unexpected environment gate message: {message}")

    print("Environment gate test passed!")
    return True


def read_repo_file(relative_path):
    """Read a repository file as UTF-8 text."""
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def assert_contains(content, expected_text, description):
    """Raise a clear assertion error when expected text is missing."""
    if expected_text not in content:
        raise AssertionError(f"Missing {description}: {expected_text}")


def test_engine_resolution_contract():
    """The extraction engine resolver must prefer Content Understanding but always fall back."""
    print("Testing extraction engine resolution contract...")

    settings = read_repo_file("application/single_app/functions_settings.py")
    content = read_repo_file("application/single_app/functions_content.py")

    assert_contains(settings, 'EXTRACTION_ENGINE_CONTENT_UNDERSTANDING = "content_understanding"', "Content Understanding engine constant")
    assert_contains(settings, 'EXTRACTION_ENGINE_DOCUMENT_INTELLIGENCE = "document_intelligence"', "Document Intelligence engine constant")
    assert_contains(settings, 'CONTENT_UNDERSTANDING_SUPPORTED_AZURE_ENVIRONMENTS = {"public"}', "supported cloud allowlist")
    assert_contains(settings, "def resolve_enhanced_extraction_engine", "engine resolver")
    assert_contains(settings, "def is_content_understanding_supported_environment", "environment gate helper")
    assert_contains(settings, "def is_content_understanding_configured", "configuration gate helper")
    assert_contains(settings, "def get_effective_document_intelligence_pdf_image_extraction_mode", "effective mode helper")
    assert_contains(settings, "def is_enhanced_extraction_enabled", "Enhanced toggle helper")

    assert_contains(content, "def extract_content_with_extraction_engine", "shared engine dispatcher")
    assert_contains(content, "def resolve_extraction_engine_for_mode", "mode-to-engine resolver")
    assert_contains(content, "extraction_mode='layout'", "Document Intelligence Layout fallback call")
    assert_contains(content, "so Document Intelligence Layout was used", "fallback reason text")

    print("Engine resolution contract test passed!")
    return True


def test_settings_and_admin_surface_contract():
    """New Content Understanding settings must be defaulted, redacted, persisted, and surfaced."""
    print("Testing Content Understanding settings and admin surface...")

    settings = read_repo_file("application/single_app/functions_settings.py")
    admin_route = read_repo_file("application/single_app/route_frontend_admin_settings.py")
    backend_route = read_repo_file("application/single_app/route_backend_settings.py")
    admin_html = read_repo_file("application/single_app/templates/admin_settings.html")
    admin_js = read_repo_file("application/single_app/static/js/admin/admin_settings.js")

    assert_contains(settings, "'enable_enhanced_extraction': False", "Enhanced toggle default")
    assert_contains(settings, "'azure_content_understanding_endpoint': ''", "endpoint default")
    assert_contains(settings, "'azure_content_understanding_authentication_type': 'key'", "auth type default")
    assert_contains(settings, '"azure_content_understanding_key",', "key registered as a redacted admin secret")
    assert_contains(settings, "'enable_office_embedded_image_analysis': True", "Office image analysis default")

    # The key must be stripped from user-facing settings by the shared sanitizer.
    assert_contains(settings, 'sensitive_terms = ("key",', "sanitizer strips fields containing 'key'")

    assert_contains(admin_route, "'enable_enhanced_extraction': enable_enhanced_extraction", "Enhanced toggle persistence")
    assert_contains(admin_route, "'azure_content_understanding_endpoint': azure_content_understanding_endpoint", "endpoint persistence")
    assert_contains(admin_route, "admin_secret('azure_content_understanding_key')", "key persistence via admin secret resolution")
    assert_contains(admin_route, "document_intelligence_pdf_image_extraction_mode = 'auto'", "Enhanced enable defaults the mode to Auto")
    assert_contains(admin_route, "content_understanding_supported=is_content_understanding_supported_environment()", "environment flag passed to the template")

    assert_contains(backend_route, "elif test_type == 'content_understanding':", "test connection dispatch")
    assert_contains(backend_route, "def _test_content_understanding_connection", "test connection handler")

    assert_contains(admin_html, 'id="enable_enhanced_extraction"', "Enhanced toggle input")
    assert_contains(admin_html, 'id="azure_content_understanding_endpoint"', "endpoint input")
    assert_contains(admin_html, 'id="azure_content_understanding_authentication_type"', "auth type select")
    assert_contains(admin_html, 'id="test_content_understanding_button"', "test connection button")
    assert_contains(admin_html, "contentUnderstandingSetupHelpModal", "Content Understanding setup guide modal")
    assert_contains(admin_html, "Cognitive Services User", "managed identity role guidance")
    assert_contains(admin_html, "{% if content_understanding_supported %}", "environment-aware Content Understanding block")
    assert_contains(admin_html, "is not available in the", "non-public cloud fallback notice")
    assert_contains(admin_html, 'id="enable_office_embedded_image_analysis"', "Office embedded image toggle")

    assert_contains(admin_js, "test_content_understanding_button", "test connection wiring")
    assert_contains(admin_js, "test_type: 'content_understanding'", "test connection payload")
    assert_contains(admin_js, "enhanced_extraction_settings", "Enhanced section visibility wiring")

    print("Settings and admin surface test passed!")
    return True


def test_auto_mode_detects_figures():
    """Auto mode must upgrade to Enhanced when the sampled pages contain figures."""
    print("Testing Auto mode figure detection...")

    documents = read_repo_file("application/single_app/functions_documents.py")

    assert_contains(documents, "DI_MARKDOWN_FIGURE_PATTERN", "figure detection pattern")
    assert_contains(documents, "figures or images detected in the sampled pages", "figure detection reason")
    assert_contains(documents, "def _build_office_embedded_image_chunks", "Office embedded image chunk builder")
    assert_contains(documents, "extraction_engine=extraction_engine", "engine recorded on the document")
    assert_contains(documents, "extraction_engine_reason", "engine fallback reason recorded on the document")

    print("Auto mode figure detection test passed!")
    return True


def load_settings_functions(function_names, azure_environment="public"):
    """Exec selected functions from the real functions_settings.py source in an isolated namespace.

    functions_settings imports the full Azure config at module load, so the test extracts only the
    pure helpers under test and runs them against the actual repository source.
    """
    import ast

    source = (APP_ROOT / "functions_settings.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    wanted = set(function_names)
    namespace = {
        "AZURE_ENVIRONMENT": azure_environment,
        "CONTENT_UNDERSTANDING_SUPPORTED_AZURE_ENVIRONMENTS": {"public"},
        "CONTENT_UNDERSTANDING_AUTHENTICATION_TYPES": {"key", "managed_identity"},
        "CONTENT_UNDERSTANDING_API_VERSION_DEFAULT": "2025-11-01",
        "CONTENT_UNDERSTANDING_DOCUMENT_ANALYZER_DEFAULT": "prebuilt-documentSearch",
        "CONTENT_UNDERSTANDING_IMAGE_ANALYZER_DEFAULT": "prebuilt-imageSearch",
        "EXTRACTION_ENGINE_DOCUMENT_INTELLIGENCE": "document_intelligence",
        "EXTRACTION_ENGINE_CONTENT_UNDERSTANDING": "content_understanding",
        "DOCUMENT_INTELLIGENCE_PDF_IMAGE_EXTRACTION_MODES": {"read", "layout", "auto"},
        "OFFICE_EMBEDDED_IMAGE_MIN_PIXELS_DEFAULT": 150,
        "OFFICE_EMBEDDED_IMAGE_MIN_PIXELS_MAX": 2000,
        "OFFICE_EMBEDDED_IMAGE_MAX_PER_DOCUMENT_DEFAULT": 25,
        "OFFICE_EMBEDDED_IMAGE_MAX_PER_DOCUMENT_MAX": 200,
    }

    found = set()
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in wanted:
            exec(compile(ast.Module(body=[node], type_ignores=[]), "functions_settings.py", "exec"), namespace)
            found.add(node.name)

    missing = wanted - found
    if missing:
        raise AssertionError(f"Could not locate settings functions in source: {sorted(missing)}")

    return namespace


def test_enhanced_extraction_engine_resolution_behavior():
    """Enhanced must use Content Understanding only when the cloud and configuration allow it."""
    print("Testing Enhanced extraction engine resolution behavior...")

    required = [
        "resolve_enhanced_extraction_engine",
        "is_content_understanding_supported_environment",
        "is_content_understanding_configured",
        "get_content_understanding_config",
        "normalize_content_understanding_endpoint",
        "normalize_content_understanding_authentication_type",
        "normalize_content_understanding_api_version",
        "normalize_content_understanding_analyzer_id",
    ]

    public_ns = load_settings_functions(required, azure_environment="public")
    resolve_public = public_ns["resolve_enhanced_extraction_engine"]

    configured_settings = {
        "azure_content_understanding_endpoint": "https://example.services.ai.azure.com/",
        "azure_content_understanding_key": "fake-key",
        "azure_content_understanding_authentication_type": "key",
    }
    engine, reason = resolve_public(configured_settings)
    if engine != "content_understanding":
        raise AssertionError(f"Configured public cloud should use Content Understanding, got {engine} ({reason})")
    if reason:
        raise AssertionError(f"A successful resolution should carry no fallback reason, got {reason!r}")

    # Key auth without a key is not usable, so Enhanced must fall back rather than fail.
    engine, reason = resolve_public({**configured_settings, "azure_content_understanding_key": ""})
    if engine != "document_intelligence" or "not configured" not in reason:
        raise AssertionError(f"Missing key should fall back to Document Intelligence, got {engine} ({reason})")

    # Managed identity needs no key.
    engine, _ = resolve_public({
        "azure_content_understanding_endpoint": "https://example.services.ai.azure.com",
        "azure_content_understanding_authentication_type": "managed_identity",
    })
    if engine != "content_understanding":
        raise AssertionError("Managed identity without a key should still use Content Understanding.")

    engine, reason = resolve_public({})
    if engine != "document_intelligence" or "not configured" not in reason:
        raise AssertionError(f"Empty settings should fall back to Document Intelligence, got {engine} ({reason})")

    gov_ns = load_settings_functions(required, azure_environment="usgovernment")
    engine, reason = gov_ns["resolve_enhanced_extraction_engine"](configured_settings)
    if engine != "document_intelligence":
        raise AssertionError(f"Government cloud must use Document Intelligence, got {engine}")
    if "usgovernment" not in reason:
        raise AssertionError(f"Government fallback reason should name the cloud, got {reason!r}")

    print("Engine resolution behavior test passed!")
    return True


def test_effective_extraction_mode_honors_enhanced_toggle():
    """Turning Enhanced off must force Standard regardless of the stored mode."""
    print("Testing effective extraction mode behavior...")

    namespace = load_settings_functions([
        "get_effective_document_intelligence_pdf_image_extraction_mode",
        "get_document_intelligence_pdf_image_extraction_mode",
        "normalize_document_intelligence_pdf_image_extraction_mode",
        "is_enhanced_extraction_enabled",
        "normalize_enhanced_extraction_enabled",
    ])
    get_effective_mode = namespace["get_effective_document_intelligence_pdf_image_extraction_mode"]

    disabled = {
        "enable_enhanced_extraction": False,
        "document_intelligence_pdf_image_extraction_mode": "layout",
    }
    if get_effective_mode(disabled) != "read":
        raise AssertionError("Enhanced disabled must force Standard extraction.")

    enabled_layout = {
        "enable_enhanced_extraction": True,
        "document_intelligence_pdf_image_extraction_mode": "layout",
    }
    if get_effective_mode(enabled_layout) != "layout":
        raise AssertionError("Enhanced enabled must honor the stored Enhanced mode.")

    enabled_auto = {
        "enable_enhanced_extraction": True,
        "document_intelligence_pdf_image_extraction_mode": "auto",
    }
    if get_effective_mode(enabled_auto) != "auto":
        raise AssertionError("Enhanced enabled must honor Auto mode.")

    if get_effective_mode({"enable_enhanced_extraction": True}) != "read":
        raise AssertionError("An unset mode must default to Standard.")

    print("Effective extraction mode test passed!")
    return True


def test_office_embedded_image_limits_are_clamped():
    """Embedded image limits must be clamped into safe ranges."""
    print("Testing embedded image limit normalizers...")

    namespace = load_settings_functions([
        "normalize_office_embedded_image_min_pixels",
        "normalize_office_embedded_image_max_per_document",
    ])
    normalize_min_pixels = namespace["normalize_office_embedded_image_min_pixels"]
    normalize_max_images = namespace["normalize_office_embedded_image_max_per_document"]

    cases = [
        (normalize_min_pixels, None, 150),
        (normalize_min_pixels, "not a number", 150),
        (normalize_min_pixels, -5, 1),
        (normalize_min_pixels, 999999, 2000),
        (normalize_min_pixels, "300", 300),
        (normalize_max_images, None, 25),
        (normalize_max_images, -1, 0),
        (normalize_max_images, 999999, 200),
        (normalize_max_images, "10", 10),
    ]

    for normalizer, raw_value, expected in cases:
        actual = normalizer(raw_value)
        if actual != expected:
            raise AssertionError(
                f"{normalizer.__name__}({raw_value!r}) returned {actual}, expected {expected}"
            )

    print("Embedded image limit normalizer test passed!")
    return True


def test_mermaid_content_survives_inlined_description():
    """A mermaid diagram must be kept even when its description is already inlined in the markdown."""
    print("Testing mermaid retention with an inlined description...")

    content_understanding, _ = load_content_understanding_module()
    description = "A flowchart showing the approval process."
    markdown = f"# Process\n\n{description}\n"

    result = {
        "contents": [
            {
                "kind": "document",
                "markdown": markdown,
                "startPageNumber": 1,
                "pages": [{"pageNumber": 1, "spans": [{"offset": 0, "length": len(markdown)}]}],
                "figures": [
                    {
                        "id": "fig-1",
                        "kind": "mermaid",
                        "description": description,
                        "content": "graph TD\n  A[Start] --> B{Decision}",
                        "span": {"offset": 10, "length": 5},
                    }
                ],
            }
        ]
    }

    pages = content_understanding.build_pages_from_content_understanding_result(result)
    page_content = pages[0]["content"]

    if "```mermaid" not in page_content:
        raise AssertionError(
            f"Mermaid diagram source was dropped alongside the inlined description: {page_content!r}"
        )
    if "graph TD" not in page_content:
        raise AssertionError("Mermaid diagram body was lost.")
    if page_content.count(description) != 1:
        raise AssertionError(f"Inlined description was duplicated: {page_content!r}")

    print("Mermaid retention test passed!")
    return True


def test_enhanced_extraction_upgrade_migration_contract():
    """Existing Enhanced or Auto deployments must keep Enhanced enabled after upgrading."""
    print("Testing Enhanced extraction upgrade migration...")

    settings = read_repo_file("application/single_app/functions_settings.py")

    assert_contains(settings, "legacy_enhanced_extraction = 'enable_enhanced_extraction' not in settings_item", "legacy toggle detection before merge")
    assert_contains(settings, "if legacy_enhanced_extraction and legacy_enhanced_extraction_mode in ('layout', 'auto'):", "migration condition")
    assert_contains(settings, "merged['enable_enhanced_extraction'] = True", "migration backfill")
    assert_contains(settings, "or enhanced_extraction_migration_updated", "migration persisted to Cosmos")

    # The migration must run before the merge fills the key in with its False default.
    detection_index = settings.index("legacy_enhanced_extraction = 'enable_enhanced_extraction' not in settings_item")
    merge_index = settings.index("merge_changed = deep_merge_dicts(default_settings, settings_item)")
    if detection_index > merge_index:
        raise AssertionError("Legacy toggle detection must happen before deep_merge_dicts fills the default.")

    print("Upgrade migration test passed!")
    return True


def test_diagram_only_figure_renders_a_valid_fence():
    """A diagram kept after its description is de-duplicated must still be valid markdown.

    The opening code fence has to start at column zero, otherwise markdown renderers treat it as
    ordinary paragraph text.
    """
    print("Testing diagram-only figure fence placement...")

    content_understanding, _ = load_content_understanding_module()
    description = "A flowchart showing the approval process."
    markdown = f"# Process\n\n{description}\n"

    result = {
        "contents": [
            {
                "kind": "document",
                "markdown": markdown,
                "startPageNumber": 1,
                "pages": [{"pageNumber": 1, "spans": [{"offset": 0, "length": len(markdown)}]}],
                "figures": [
                    {
                        "id": "fig-1",
                        "kind": "mermaid",
                        "description": description,
                        "content": "graph TD\n  A[Start] --> B{Decision}",
                        "span": {"offset": 10, "length": 5},
                    }
                ],
            }
        ]
    }

    pages = content_understanding.build_pages_from_content_understanding_result(result)
    page_content = pages[0]["content"]

    fence_lines = [line for line in page_content.splitlines() if line.startswith("```mermaid")]
    if not fence_lines:
        raise AssertionError(
            f"Opening mermaid fence must start at the beginning of a line: {page_content!r}"
        )

    # The fence must also close on its own line.
    closing_lines = [line for line in page_content.splitlines() if line.strip() == "```"]
    if not closing_lines:
        raise AssertionError(f"Mermaid fence was not closed on its own line: {page_content!r}")

    print("Diagram fence placement test passed!")
    return True


def test_caption_only_figure_is_not_dropped():
    """Descriptions are optional in the API schema, so a captioned figure must survive."""
    print("Testing caption-only figure retention...")

    content_understanding, _ = load_content_understanding_module()
    markdown = "# Report\n\nSome text.\n"

    result = {
        "contents": [
            {
                "kind": "document",
                "markdown": markdown,
                "startPageNumber": 1,
                "pages": [{"pageNumber": 1, "spans": [{"offset": 0, "length": len(markdown)}]}],
                "figures": [
                    {
                        "id": "fig-7",
                        "kind": "image",
                        "caption": {"content": "Figure 4: Site layout"},
                        "span": {"offset": 5, "length": 3},
                    }
                ],
            }
        ]
    }

    pages = content_understanding.build_pages_from_content_understanding_result(result)
    if "Figure 4: Site layout" not in pages[0]["content"]:
        raise AssertionError(f"A caption-only figure was dropped: {pages[0]['content']!r}")

    print("Caption-only figure test passed!")
    return True


def test_figures_survive_when_the_result_has_no_pages():
    """Figure descriptions must not be lost when the response omits per-page spans."""
    print("Testing figure retention in the no-pages fallback...")

    content_understanding, _ = load_content_understanding_module()

    result = {
        "contents": [
            {
                "kind": "document",
                "markdown": "Scanned page with a chart.",
                "startPageNumber": 1,
                "figures": [
                    {
                        "id": "fig-1",
                        "kind": "chart",
                        "description": "A pie chart of budget allocation by department.",
                        "span": {"offset": 2, "length": 4},
                    }
                ],
            }
        ]
    }

    pages = content_understanding.build_pages_from_content_understanding_result(result)
    if len(pages) != 1:
        raise AssertionError(f"Expected a single fallback page, got {pages}")
    if "pie chart of budget allocation" not in pages[0]["content"]:
        raise AssertionError(
            f"Figure description was lost in the no-pages fallback: {pages[0]['content']!r}"
        )

    print("No-pages figure retention test passed!")
    return True


def test_formula_extraction_is_opt_in_and_layout_only():
    """The Document Intelligence formula add-on is billed, so it must default off and be opt-in."""
    print("Testing formula extraction opt-in contract...")

    settings = read_repo_file("application/single_app/functions_settings.py")
    content = read_repo_file("application/single_app/functions_content.py")
    admin_route = read_repo_file("application/single_app/route_frontend_admin_settings.py")
    admin_html = read_repo_file("application/single_app/templates/admin_settings.html")

    assert_contains(settings, "'enable_document_intelligence_formula_extraction': False", "formula add-on defaults to off")
    assert_contains(settings, "def is_document_intelligence_formula_extraction_enabled", "formula gate helper")
    assert_contains(content, "DocumentAnalysisFeature.FORMULAS", "formula add-on requested")
    assert_contains(admin_route, "'enable_document_intelligence_formula_extraction': form_data.get(", "formula toggle persisted")
    assert_contains(admin_html, 'id="enable_document_intelligence_formula_extraction"', "formula toggle input")
    assert_contains(admin_html, "billed Document Intelligence add-on", "cost warning shown to admins")

    # The add-on only applies to Layout, so it must sit behind the layout branch.
    formula_index = content.index("DocumentAnalysisFeature.FORMULAS")
    guard_index = content.index('if normalized_extraction_mode == "layout" and functions_settings.is_document_intelligence_formula_extraction_enabled()')
    if guard_index > formula_index:
        raise AssertionError("Formula feature must be guarded by the layout-mode check.")

    print("Formula extraction opt-in test passed!")
    return True


def test_version_is_at_least_implementation_version():
    """The app version must be at or beyond the version this feature shipped in."""
    print("Testing application version...")
    assert_app_version_at_least("0.250.221")
    print("Version test passed!")
    return True


if __name__ == "__main__":
    tests = [
        test_page_reconstruction_from_spans,
        test_figure_descriptions_attach_to_their_page,
        test_inline_figure_descriptions_are_not_duplicated,
        test_mermaid_content_survives_inlined_description,
        test_diagram_only_figure_renders_a_valid_fence,
        test_caption_only_figure_is_not_dropped,
        test_figures_survive_when_the_result_has_no_pages,
        test_missing_pages_falls_back_to_whole_markdown,
        test_missing_model_deployment_error_is_explained,
        test_government_cloud_blocks_content_understanding,
        test_engine_resolution_contract,
        test_enhanced_extraction_engine_resolution_behavior,
        test_effective_extraction_mode_honors_enhanced_toggle,
        test_office_embedded_image_limits_are_clamped,
        test_settings_and_admin_surface_contract,
        test_auto_mode_detects_figures,
        test_enhanced_extraction_upgrade_migration_contract,
        test_formula_extraction_is_opt_in_and_layout_only,
        test_version_is_at_least_implementation_version,
    ]

    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            results.append(test())
        except Exception as error:
            print(f"Test failed: {error}")
            import traceback

            traceback.print_exc()
            results.append(False)

    print(f"\nResults: {sum(1 for result in results if result)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)

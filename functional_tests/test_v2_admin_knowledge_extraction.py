#!/usr/bin/env python3
# test_v2_admin_knowledge_extraction.py
"""
Functional test for the Knowledge group's Document Extraction tab in V2.
Version: 0.261.072
Implemented in: 0.261.072

The server-rendered extraction pane is inside out. "Enable Enhanced extraction"
is its first control, at line 13, and the Document Intelligence endpoint and key
are its last, several hundred lines below -- after the extraction mode, formula
extraction, the Content Understanding card and the Office image card. An
administrator turns a feature on and then scrolls past everything that depends
on the connection before reaching the connection itself.

Two of those cards were also missing from ``ADMIN_NAV`` entirely, so neither
interface could navigate to Content Understanding or to the Office embedded
image options even though both have existed in the markup for some time.

The checks here pin the corrected shape:

ordering
    The connection group is declared before the behaviour that depends on it.
    This is the whole reason the section was described, so it is asserted rather
    than left to review.

navigation
    Both previously unreachable cards are sections, with the ids the existing
    markup already uses so the server-rendered sidebar resolves them.

storage
    Chunk sizes live inside one ``chunk_size`` object and are clamped to what an
    embedding request can carry. A size written flat, or written past the cap,
    produces documents that silently fail to embed.
"""

import re
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))

from test_support.app_stubs import import_app_module
from test_support.nav import ADMIN_NAV
from test_support.versioning import assert_app_version_at_least


REPO_ROOT = Path(__file__).resolve().parents[1]
PANE = (
    REPO_ROOT
    / "application"
    / "single_app"
    / "templates"
    / "admin"
    / "_panes"
    / "extraction.html"
)

EXTRACTION_SECTIONS = (
    "document-intelligence-section",
    "content-understanding-section",
    "office-embedded-image-section",
    "chunk-size-section",
    # Added by the Workspaces work: upload size belongs with extraction because
    # both upload paths feed the same pipeline.
    "file-size-limit-section",
    "metadata-extraction-section",
    "multimodal-vision-section",
)

# Described so far. Multi-modal vision arrives with the model capability work.
DESCRIBED_SECTIONS = (
    "document-intelligence-section",
    "content-understanding-section",
    "office-embedded-image-section",
    "chunk-size-section",
    "metadata-extraction-section",
)

fields_module = import_app_module("admin_settings_fields")
normalize = fields_module.normalize_admin_settings_updates

FIELD_NAME_RE = re.compile(r'\sname="([^"]+)"')
JINJA_RE = re.compile(r"\{\{|\{%")


def pane_field_names():
    markup = PANE.read_text(encoding="utf-8")
    return {name for name in FIELD_NAME_RE.findall(markup) if not JINJA_RE.search(name)}


def section_fields(section_id):
    return [
        field
        for declared_section, field in fields_module.iter_fields()
        if declared_section == section_id
    ]


def test_the_previously_unreachable_cards_are_navigable():
    """Two cards existed in the markup but in no navigation, in either interface."""
    print("Testing Document Extraction sections against ADMIN_NAV...")

    assert_app_version_at_least("0.261.072")

    nav_sections = [
        section["id"]
        for group in ADMIN_NAV
        if group["id"] == "knowledge"
        for tab in group["tabs"]
        if tab["id"] == "extraction"
        for section in tab["sections"]
    ]

    assert tuple(nav_sections) == EXTRACTION_SECTIONS, (
        "The Document Extraction tab's sections changed.\n"
        f"  ADMIN_NAV: {nav_sections}\n  test: {list(EXTRACTION_SECTIONS)}"
    )

    # The ids have to be the ones already on the cards, or the server-rendered
    # sidebar links resolve to nothing.
    markup = PANE.read_text(encoding="utf-8")
    for section_id in ("content-understanding-section", "office-embedded-image-section"):
        assert f'id="{section_id}"' in markup, (
            f"{section_id} is in ADMIN_NAV but no card in extraction.html carries "
            "that id, so the classic page would link to nothing."
        )

    print(f"  All {len(nav_sections)} section(s) navigable, including the two added.")
    return True


def test_the_connection_is_declared_before_what_depends_on_it():
    """This ordering is the reason the section was described at all."""
    print("\nTesting Document Intelligence field order...")

    fields = section_fields("document-intelligence-section")
    assert fields, "document-intelligence-section declares no fields."

    order = [field.get("key") or field.get("component") for field in fields]
    groups = [(field.get("group") or {}).get("id") for field in fields]

    endpoint = order.index("azure_document_intelligence_endpoint")
    enhanced = order.index("enable_enhanced_extraction")
    formula = order.index("enable_document_intelligence_formula_extraction")
    mode = order.index("document_intelligence_pdf_image_extraction_mode")

    assert endpoint < enhanced, (
        "Enhanced extraction is declared before the Document Intelligence "
        "endpoint it needs. That is the V1 ordering, and it is what this "
        f"section exists to fix.\n  order: {order}"
    )
    assert endpoint < formula, f"Formula extraction precedes the endpoint.\n  order: {order}"
    assert endpoint < mode, f"The extraction mode precedes the endpoint.\n  order: {order}"

    # The connection group is contiguous and first, so it collapses as one unit.
    connection_positions = [index for index, group in enumerate(groups) if group == "connection"]
    assert connection_positions == list(range(len(connection_positions))), (
        "The connection fields are not contiguous at the top of the section, so "
        f"they cannot be disclosed as one group.\n  groups: {groups}"
    )

    print("  The connection is declared first, contiguously, before its dependants.")
    return True


def test_every_v1_field_is_claimed_or_still_to_come():
    """A V1 field with no V2 equivalent is invisible in the new UI."""
    print("\nTesting that V1 extraction fields are claimed...")

    claimed = fields_module.get_legacy_field_names()
    documented = set(fields_module.LEGACY_FIELDS_WITHOUT_V2_EQUIVALENT)

    # Multi-modal vision is described in the next change; its fields are still
    # discovered by the fallback scan until then.
    not_yet_described = {
        "enable_multimodal_vision",
        "multimodal_vision_model",
        "metadata_extraction_model",
        "metadata_extraction_model_selection_json",
    }

    names = pane_field_names()
    missing = sorted(names - claimed - documented - not_yet_described)

    assert not missing, (
        "These fields exist in the server-rendered extraction pane but are not "
        "described in admin_settings_fields.py, so they cannot appear in the V2 "
        "admin UI:\n  " + "\n  ".join(missing)
    )

    print(f"  {len(names - not_yet_described)} V1 field(s) claimed.")
    return True


def test_the_schema_invents_nothing():
    """A schema key with no V1 counterpart would save a setting nothing reads."""
    print("\nTesting that the schema invents no extraction fields...")

    v1_names = pane_field_names()

    invented = []
    for section_id in DESCRIBED_SECTIONS:
        for field in section_fields(section_id):
            key = field.get("key")
            if not key:
                continue
            legacy = fields_module.LEGACY_FIELD_NAMES.get(key, [key])
            if not any(name in v1_names for name in legacy):
                invented.append(f"{section_id}.{key}")

    assert not invented, (
        "These schema fields have no matching field in the V1 pane:\n  "
        + "\n  ".join(invented)
    )

    print("  Every declared field maps back to a V1 field.")
    return True


def test_apim_and_direct_are_never_shown_together():
    """Showing both paths is what makes an administrator guess which half matters."""
    print("\nTesting the APIM branch...")

    evaluate = fields_module.evaluate_dependency
    by_key = {
        field["key"]: field
        for field in section_fields("document-intelligence-section")
        if field.get("key")
    }

    direct = {
        "enable_document_intelligence_apim": False,
        "azure_document_intelligence_authentication_type": "key",
    }
    apim = {"enable_document_intelligence_apim": True}

    def visible(key, state):
        return evaluate(by_key[key].get("depends_on"), state.get)

    assert visible("azure_document_intelligence_endpoint", direct)
    assert visible("azure_document_intelligence_key", direct)
    assert not visible("azure_apim_document_intelligence_endpoint", direct)

    assert visible("azure_apim_document_intelligence_endpoint", apim)
    assert visible("azure_apim_document_intelligence_subscription_key", apim)
    assert not visible("azure_document_intelligence_endpoint", apim)
    assert not visible("azure_document_intelligence_key", apim)

    # The key only matters for key auth.
    managed = {
        "enable_document_intelligence_apim": False,
        "azure_document_intelligence_authentication_type": "managed_identity",
    }
    assert not visible("azure_document_intelligence_key", managed)
    assert visible("azure_document_intelligence_endpoint", managed)

    print("  Only the connection path in use is shown.")
    return True


def test_auto_sample_pages_appears_only_for_auto():
    """A sample-page count is meaningless unless Auto is selected."""
    print("\nTesting the auto sample pages dependency...")

    field = fields_module.get_field_definition("document_intelligence_auto_sample_pages")
    assert field, "document_intelligence_auto_sample_pages is not declared."

    evaluate = fields_module.evaluate_dependency
    for mode, expected in (("auto", True), ("read", False), ("layout", False)):
        state = {"document_intelligence_pdf_image_extraction_mode": mode}
        assert evaluate(field["depends_on"], state.get) is expected, (
            f"Sample pages visibility is wrong for mode {mode!r}."
        )

    print("  Sample pages show only in Auto mode.")
    return True


def test_chunk_sizes_are_written_into_the_chunk_size_object():
    """A chunk size written flat is a setting the extraction path never reads."""
    print("\nTesting chunk size storage...")

    current = {"chunk_size": {"txt": {"value": 400, "unit": "words"}}}

    normalized, errors, _ = normalize({"chunk_size_txt": 500}, current)
    assert not errors, errors

    assert "chunk_size_txt" not in normalized, (
        "The form-field name was written as a top-level key. The extraction path "
        "reads settings['chunk_size'], so the save would change nothing."
    )

    chunk_size = normalized.get("chunk_size")
    assert isinstance(chunk_size, dict), f"Expected chunk_size to be rebuilt: {normalized}"
    assert chunk_size["txt"]["value"] == 500, chunk_size
    assert chunk_size["txt"]["unit"] == "words", (
        "The unit was dropped. A value without its unit cannot be capped correctly."
    )

    # Editing one file type must not drop the others.
    multi = {
        "chunk_size": {
            "txt": {"value": 400, "unit": "words"},
            "pdf": {"value": 1, "unit": "pages"},
        }
    }
    normalized, errors, _ = normalize({"chunk_size_txt": 450}, multi)
    assert not errors, errors
    assert normalized["chunk_size"]["pdf"] == {"value": 1, "unit": "pages"}, (
        "Editing the TXT chunk size dropped the PDF one. update_settings merges "
        "at the top level, so the whole object has to be rebuilt from storage."
    )

    print("  Chunk sizes write into chunk_size and preserve their siblings.")
    return True


def test_every_chunk_size_field_declares_its_path():
    """A chunk field without a path silently saves to a key nothing reads."""
    print("\nTesting chunk size path declarations...")

    problems = []
    for field in section_fields("chunk-size-section"):
        key = field.get("key")
        if not key or not key.startswith("chunk_size_"):
            continue
        paths = field.get("paths") or []
        expected = f"chunk_size.{key[len('chunk_size_'):]}.value"
        if paths != [expected]:
            problems.append(f"{key}: paths {paths} != ['{expected}']")

    assert not problems, "\n  ".join(["Chunk size paths are wrong:"] + problems)

    declared = {
        field["key"]
        for field in section_fields("chunk-size-section")
        if field.get("key", "").startswith("chunk_size_")
    }
    v1_chunk_fields = {
        name for name in pane_field_names() if name.startswith("chunk_size_")
    }
    assert declared == v1_chunk_fields, (
        "The declared chunk size fields differ from the ones the V1 pane "
        f"submits.\n  only in schema: {sorted(declared - v1_chunk_fields)}\n"
        f"  only in V1: {sorted(v1_chunk_fields - declared)}"
    )

    print(f"  All {len(declared)} chunk size field(s) declare the right path.")
    return True


def test_content_understanding_is_its_own_section():
    """It was a nested card, which read as part of Enhanced extraction."""
    print("\nTesting the Content Understanding section...")

    fields = section_fields("content-understanding-section")
    keys = {field.get("key") for field in fields}

    for expected in (
        "azure_content_understanding_endpoint",
        "azure_content_understanding_authentication_type",
        "azure_content_understanding_key",
        "azure_content_understanding_api_version",
        "azure_content_understanding_analyzer_id",
        "azure_content_understanding_image_analyzer_id",
    ):
        assert expected in keys, f"{expected} is not declared in its own section."

    secret = fields_module.get_field_definition("azure_content_understanding_key")
    assert secret["type"] == "secret", (
        "The Content Understanding key must be a secret, or it is sent to the "
        "browser in plain text."
    )

    print(f"  {len(keys)} field(s) declared in the Content Understanding section.")
    return True


if __name__ == "__main__":
    tests = [
        test_the_previously_unreachable_cards_are_navigable,
        test_the_connection_is_declared_before_what_depends_on_it,
        test_every_v1_field_is_claimed_or_still_to_come,
        test_the_schema_invents_nothing,
        test_apim_and_direct_are_never_shown_together,
        test_auto_sample_pages_appears_only_for_auto,
        test_chunk_sizes_are_written_into_the_chunk_size_object,
        test_every_chunk_size_field_declares_its_path,
        test_content_understanding_is_its_own_section,
    ]

    results = []
    for test in tests:
        try:
            results.append(bool(test()))
        except Exception as exc:
            print(f"FAILED {test.__name__}: {exc}")
            import traceback

            traceback.print_exc()
            results.append(False)

    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)

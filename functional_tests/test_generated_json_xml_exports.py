#!/usr/bin/env python3
# test_generated_json_xml_exports.py
"""
Functional test for generated JSON/XML export artifacts.
Version: 0.250.153
Implemented in: 0.250.114; completed file-export cards and View actions in 0.250.152; truthful private payload streaming in 0.250.153

This test ensures JSON/XML generation requests are recognized as downloadable
artifact workflows, reuse shared serialization helpers, avoid duplicate XML
processing implementations, and preserve no-inline-output handoff behavior.
"""

import ast
import importlib.util
import sys
from pathlib import Path

from test_support.versioning import assert_app_version_at_least


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / "application" / "single_app"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))
CONFIG_FILE = APP_ROOT / "config.py"
GENERATED_EXPORTS_FILE = APP_ROOT / "functions_generated_file_exports.py"
CHAT_ROUTE_FILE = APP_ROOT / "route_backend_chats.py"
WORKFLOW_RUNNER_FILE = APP_ROOT / "functions_workflow_runner.py"
DOCUMENT_ANALYSIS_FILE = APP_ROOT / "functions_document_analysis.py"
DOCUMENTS_FILE = APP_ROOT / "functions_documents.py"
CHAT_MESSAGES_FILE = APP_ROOT / "static" / "js" / "chat" / "chat-messages.js"


def read_text(path):
    return path.read_text(encoding="utf-8")


def assert_contains(source_text, needle, description):
    if needle not in source_text:
        raise AssertionError(f"Missing {description}: {needle}")


def read_current_version():
    for line in read_text(CONFIG_FILE).splitlines():
        stripped_line = line.strip()
        if stripped_line.startswith("VERSION = "):
            return stripped_line.split('"')[1]
    raise AssertionError("Expected config.py to define VERSION")


def load_generated_exports_module():
    spec = importlib.util.spec_from_file_location(
        "functions_generated_file_exports",
        GENERATED_EXPORTS_FILE,
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_shared_json_xml_export_helpers():
    print("Testing shared JSON/XML export helpers...")
    module = load_generated_exports_module()

    parsed_json = module.normalize_json_artifact_payload(
        "Here is the file:\n```json\n{\"name\": \"Example\", \"items\": [1, 2]}\n```"
    )
    assert parsed_json == {"name": "Example", "items": [1, 2]}

    xml_payload = module.normalize_xml_artifact_payload(
        "Generated XML:\n```xml\n<Report><Name>Example</Name></Report>\n```"
    )
    assert xml_payload == "<Report><Name>Example</Name></Report>"
    assert module.normalize_xml_artifact_payload(
        "<!DOCTYPE foo [<!ENTITY xxe \"blocked\">]><Report>&xxe;</Report>"
    ) == ""
    assert module.strip_markdown_code_fence("```json\n{\"safe\": true}\n```") == '{"safe": true}'

    serialized_xml = module.serialize_generated_xml(
        [{"name": "A"}, {"name": "B"}],
        root_name="GeneratedRows",
        item_name="Row",
    )
    assert serialized_xml.startswith('<?xml version="1.0" encoding="UTF-8"?>')
    assert "<GeneratedRows>" in serialized_xml
    assert serialized_xml.count("<Row>") == 2

    assert module.normalize_generated_output_format(".xml") == "xml"
    assert module.normalize_generated_output_format("json") == "json"
    xml_guidance = module.build_generated_file_output_guidance(
        'Create a downloadable XML file.',
        requested_format='xml',
    )
    json_guidance = module.build_generated_file_output_guidance(
        'Create a downloadable JSON file.',
        requested_format='json',
    )
    for guidance in (xml_guidance, json_guidance):
        assert 'server will validate and attach the file' in guidance
        assert 'claim that files cannot be attached' in guidance
        assert 'copy or save content manually' in guidance
        assert 'Return ONLY' in guidance
    print("Shared helper checks passed")


def test_chat_route_json_xml_artifact_hooks():
    print("Testing chat route JSON/XML artifact hooks...")
    chat_source = read_text(CHAT_ROUTE_FILE)

    assert_contains(chat_source, "normalize_json_artifact_payload", "JSON artifact extraction import")
    assert_contains(chat_source, "normalize_xml_artifact_payload", "XML artifact extraction import")
    assert_contains(chat_source, "def maybe_create_assistant_file_generated_output(", "assistant JSON/XML artifact helper")
    assert_contains(chat_source, "convert into json", "natural JSON conversion marker")
    assert_contains(chat_source, r"\ba?\s*json\b", "natural JSON conversion regex")
    assert_contains(chat_source, "populate the xml", "XML template population marker")
    assert_contains(chat_source, r"\ba?\s*xml\b", "natural XML conversion regex")
    assert_contains(chat_source, "_build_assistant_file_output_handoff", "no-inline assistant handoff builder")
    assert chat_source.count("maybe_create_assistant_file_generated_output(") >= 4, (
        "Expected helper definition plus document-action, non-streaming, and streaming save path calls."
    )
    assert_contains(chat_source, "serialize_generated_xml(", "XML serialization for generated tabular exports")
    assert_contains(chat_source, "root_name='GeneratedRows'", "tabular XML root naming")
    assert_contains(chat_source, "'capability': 'file_export'", "completed file-export capability")
    assert_contains(chat_source, "'suppress_assistant_text': True", "completed handoff suppression")
    assert_contains(chat_source, 'def _build_streaming_assistant_file_status(', 'streaming file status builder')
    assert_contains(chat_source, "suppress_streamed_file_payload = requested_streamed_file_format in {'json', 'xml'}", 'private file payload streaming')
    assert chat_source.count('if not suppress_streamed_file_payload:') >= 4, (
        'Expected agent, direct-model, fallback, and appended-content payload gates.'
    )
    assert_contains(chat_source, "'Generating the {normalized_output_format} file. It will appear here when ready.'", 'truthful streaming status')
    route_tree = ast.parse(chat_source, filename=str(CHAT_ROUTE_FILE))
    status_helper = next(
        node
        for node in route_tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == '_build_streaming_assistant_file_status'
    )
    namespace = {}
    exec(compile(ast.Module(body=[status_helper], type_ignores=[]), str(CHAT_ROUTE_FILE), 'exec'), namespace)
    assert namespace['_build_streaming_assistant_file_status']('xml') == (
        'Generating the XML file. It will appear here when ready.'
    )
    assert namespace['_build_streaming_assistant_file_status']('json') == (
        'Generating the JSON file. It will appear here when ready.'
    )
    assert namespace['_build_streaming_assistant_file_status']('docx') == ''
    print("Chat route checks passed")


def test_json_xml_completed_artifact_metadata_and_view_actions():
    """JSON/XML artifacts use concise completed cards with bounded View metadata."""
    module = load_generated_exports_module()
    json_metadata = module.build_generated_file_artifact_metadata(
        {
            'capability': 'file_export',
            'file_name': 'generated.json',
            'output_format': 'json',
            'row_count': 2,
            'preview_rows': [
                {'id': 'A-1', 'status': 'ready'},
                {'id': 'A-2', 'status': 'review'},
            ],
            'summary': 'Generated JSON artifact.',
        },
        {'message': {'id': 'artifact-json', 'file_name': 'generated.json'}},
        'conversation-1',
    )
    xml_metadata = module.build_generated_file_artifact_metadata(
        {
            'capability': 'file_export',
            'file_name': 'generated.xml',
            'output_format': 'xml',
            'preview_lines': ['<Report>', '<Item id="A-1" />', '</Report>'],
            'summary': 'Generated XML artifact.',
        },
        {'message': {'id': 'artifact-xml', 'file_name': 'generated.xml'}},
        'conversation-1',
    )
    docx_metadata = module.build_generated_file_artifact_metadata(
        {
            'capability': 'file_export',
            'file_name': 'generated.docx',
            'output_format': 'docx',
            'summary': 'Generated Word artifact.',
        },
        {'message': {'id': 'artifact-docx', 'file_name': 'generated.docx'}},
        'conversation-1',
    )

    assert json_metadata['capability'] == 'file_export'
    assert json_metadata['preview_columns'] == ['id', 'status']
    assert json_metadata['row_count'] == 2
    assert json_metadata['suppress_assistant_text'] is True
    assert xml_metadata['preview_lines'][0] == '<Report>'
    assert xml_metadata['suppress_assistant_text'] is True
    assert docx_metadata['suppress_assistant_text'] is False

    chat_messages_source = read_text(CHAT_MESSAGES_FILE)
    assert_contains(chat_messages_source, "['csv', 'json', 'xml']", 'completed structured formats')
    assert_contains(chat_messages_source, '`View ${outputFormat.toUpperCase()}`', 'format-specific View label')
    assert_contains(chat_messages_source, 'showGeneratedArtifactPreviewModal', 'bounded View modal')


def test_document_analysis_xml_json_intent_and_artifacts():
    print("Testing document analysis JSON/XML intent and artifact wiring...")
    analysis_source = read_text(DOCUMENT_ANALYSIS_FILE)
    workflow_source = read_text(WORKFLOW_RUNNER_FILE)

    assert_contains(analysis_source, "def _prompt_requests_json_output(", "document-analysis JSON output intent")
    assert_contains(analysis_source, "def _prompt_requests_xml_output(", "document-analysis XML output intent")
    assert_contains(analysis_source, "Return only one complete well-formed XML document", "XML-only reduction guidance")
    assert_contains(analysis_source, "Return only valid JSON for the final answer", "JSON-only reduction guidance")
    assert_contains(analysis_source, "'xml_output_requested': xml_output_requested", "XML intent metadata")

    assert_contains(workflow_source, "def _prompt_explicitly_requests_xml_artifact(", "workflow XML artifact intent")
    assert_contains(workflow_source, "xml_payload = normalize_xml_artifact_payload(analysis_reply)", "XML payload extraction")
    assert_contains(workflow_source, "_build_document_analysis_artifact_file_name(analysis_result, 'xml')", "XML artifact filename")
    assert_contains(workflow_source, "output_format = 'xml' if xml_payload and xml_artifact_requested", "XML artifact output selection")
    assert_contains(workflow_source, "serialize_generated_json(json_payload)", "shared JSON serialization")
    print("Document analysis checks passed")


def test_xml_processing_consolidated():
    print("Testing XML processing consolidation...")
    documents_source = read_text(DOCUMENTS_FILE)

    assert documents_source.count("def process_xml(") == 1, "Expected exactly one public process_xml function."
    assert_contains(documents_source, "def _process_xml_with_token_usage(", "token-aware XML implementation")
    assert_contains(documents_source, "token_usage = save_chunks(**args)", "XML token usage accumulation")
    assert_contains(documents_source, "return total_chunks_saved, total_embedding_tokens, embedding_model_name", "XML token-aware return")
    assert "print(f\"Skipping empty XML chunk" not in documents_source
    assert_contains(documents_source, "[DOCUMENTS] XML processing failed", "XML log_event error logging")
    print("XML processing checks passed")


def test_security_review_fixes():
    print("Testing security review fix markers...")
    helper_source = read_text(GENERATED_EXPORTS_FILE)
    requirements_source = read_text(APP_ROOT / "requirements.txt")

    assert_contains(helper_source, "from defusedxml import ElementTree as DefusedElementTree", "defused XML parser import")
    assert_contains(helper_source, "DefusedElementTree.fromstring", "hardened XML parser usage")
    assert "re.fullmatch(" not in helper_source, "Generated export helper should not use regex fullmatch for code fences."
    assert_contains(requirements_source, "defusedxml==0.7.1", "defusedxml dependency pin")
    print("Security review fix checks passed")


def run_tests():
    assert_app_version_at_least("0.250.153")

    tests = [
        test_shared_json_xml_export_helpers,
        test_chat_route_json_xml_artifact_hooks,
        test_json_xml_completed_artifact_metadata_and_view_actions,
        test_document_analysis_xml_json_intent_and_artifacts,
        test_xml_processing_consolidated,
        test_security_review_fixes,
    ]
    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            test()
            print("PASS")
            results.append(True)
        except Exception as exc:
            print(f"FAIL: {exc}")
            import traceback
            traceback.print_exc()
            results.append(False)

    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    return all(results)


if __name__ == "__main__":
    sys.exit(0 if run_tests() else 1)

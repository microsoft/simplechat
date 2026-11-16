#!/usr/bin/env python3
# test_retrieval_citation_system_prompt_restoration.py
"""
Functional test for retrieval, XML/narrative fidelity, default system prompt,
and inline citation restoration.
Version: 0.261.392
Implemented in: 0.261.392

This test ensures that:
1. default_system_prompt is always preserved even when mixed_source_handoff,
   chat-uploaded file/image messages, or other augmentation system messages exist.
2. Full narrative/XML search excerpts and (Source: ..., Page: ...) [#citation_id]
   markers are preserved when mixed-source chat search is enabled.
3. Bracketed chunk IDs such as [8ed56431_1] and [15dce0d4_2; 8ed56431_2] resolve
   against hybrid_citations in V2 citations.ts, classic chat-citations.js, and
   functions_citation_tracking.py.
4. hybrid_search records the Semantic Ranker quota warning and falls back to
   vector + keyword (query_type="simple") search when Semantic Ranker quota is
   exhausted.
5. Workspace-backed chat file uploads hydrate their indexed chunk text in
   _refresh_workspace_linked_history_message when Content Screening is off.
"""

import ast
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_chat_citation_whitespace_preservation import run_citation_harness  # noqa: E402
from test_support.versioning import assert_app_version_at_least  # noqa: E402


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"
V2_DIR = REPO_ROOT / "application" / "v2_ui"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

import functions_mixed_source_orchestration as orchestration  # noqa: E402
from functions_citation_tracking import (  # noqa: E402
    build_cited_source_subsets,
    extract_explicit_document_citation_ids,
)


NAV_DOC_A = "8ed56431-1111-2222-3333-444444444444"
NAV_DOC_B = "15dce0d4-aaaa-bbbb-cccc-dddddddddddd"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _load_functions(path: Path, function_names, namespace):
    tree = ast.parse(_read(path), filename=str(path))
    selected_nodes = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in function_names
    ]
    assert {node.name for node in selected_nodes} == set(function_names)
    module = ast.Module(body=selected_nodes, type_ignores=[])
    ast.fix_missing_locations(module)
    exec(compile(module, str(path), "exec"), namespace)
    return namespace


def test_default_system_prompt_is_not_suppressed_by_mixed_source_or_file_messages():
    """default_system_prompt must still be inserted when augmentation or file system messages exist."""
    route_source = _read(APP_ROOT / "route_backend_chats.py")
    assert route_source.count("and str(msg.get('content') or '').strip() == default_system_prompt") >= 2
    assert '"retrieved document excerpts" in msg.get(\'content\', \'\')' not in route_source

    default_system_prompt = "You are PLASO, the procedure assistant."
    conversation_history_for_api = [
        {
            "role": "system",
            "content": "<Summary of previous conversation context>\nPrior turn\n</Summary of previous conversation context>",
        },
        {
            "role": "system",
            "content": "Use the mixed-source evidence handoff below with the other bounded narrative excerpts...",
        },
        {
            "role": "system",
            "content": "[User uploaded a file named 'NAV_402.xml'. Content preview:\n<procedure id='NAV_402'/>]",
        },
        {"role": "user", "content": "Summarize NAV 402"},
    ]

    has_general_system_prompt = any(
        msg.get("role") == "system"
        and str(msg.get("content") or "").strip() == default_system_prompt
        for msg in conversation_history_for_api
    )
    assert has_general_system_prompt is False


def test_mixed_source_chat_keeps_full_search_augmentation_and_inline_citation_markers():
    """Mixed-source chat must not suppress build_search_augmentation_system_prompt or truncate 4,000-char XML chunks."""
    route_source = _read(APP_ROOT / "route_backend_chats.py")
    assert "if not is_mixed_source_chat_search_enabled(settings):\n                        system_messages_for_augmentation.append({\n                            'role': 'system',\n                            'content': system_prompt_search" not in route_source
    assert "if not is_mixed_source_chat_search_enabled(settings):\n                            system_messages_for_augmentation.append({\n                                'role': 'system',\n                                'content': system_prompt_search" not in route_source

    xml_chunk = "<procedure id='NAV_402'>" + ("<step index='1'>Activate CCU</step>" * 100) + "</procedure>"
    assert len(xml_chunk) > 3500

    envelopes = orchestration.build_narrative_evidence_envelopes(
        [{"document_id": NAV_DOC_A, "file_name": "NAV_402.xml", "display_name": "NAV_402.xml"}],
        [{
            "id": f"{NAV_DOC_A}_1",
            "chunk_text": xml_chunk,
            "file_name": "NAV_402.xml",
            "page_number": 1,
            "chunk_sequence": 1,
            "score": 0.98,
        }],
        "relevance",
    )
    assert len(envelopes) == 1
    assert envelopes[0]["status"] == "completed"
    citation_entry = envelopes[0]["citations"][0]
    assert citation_entry["file_name"] == "NAV_402.xml"
    assert citation_entry["citation"] == f"(Source: NAV_402.xml, Page: 1) [#{NAV_DOC_A}_1]"


def test_bracketed_short_and_full_chunk_ids_resolve_in_tracking_and_both_ui_parsers():
    """Bracketed chunk IDs like [8ed56431_1] and [15dce0d4_2; 8ed56431_2] resolve to proper citations."""
    sample_message = (
        "NAV 402 is the Camera Activation procedure. [8ed56431_1]\n\n"
        "Initial conditions:\n"
        "- Camera Control Units (CCUs) are OFF [15dce0d4_2; 8ed56431_2]"
    )
    records = [
        {
            "citation_id": f"{NAV_DOC_A}_1",
            "document_id": NAV_DOC_A,
            "file_name": "NAV_402.xml",
            "page_number": 1,
            "location_label": "Page",
            "location_value": "1",
        },
        {
            "citation_id": f"{NAV_DOC_A}_2",
            "document_id": NAV_DOC_A,
            "file_name": "NAV_402.xml",
            "page_number": 2,
            "location_label": "Page",
            "location_value": "2",
        },
        {
            "citation_id": f"{NAV_DOC_B}_2",
            "document_id": NAV_DOC_B,
            "file_name": "PRIDE_Metadata.xml",
            "page_number": 2,
            "location_label": "Page",
            "location_value": "2",
        },
    ]

    extracted_ids = extract_explicit_document_citation_ids(sample_message)
    assert extracted_ids == ["8ed56431_1", "15dce0d4_2", "8ed56431_2"]

    tracked = build_cited_source_subsets(sample_message, hybrid_citations=records, web_search_citations=[])
    assert [c["citation_id"] for c in tracked["cited_hybrid_citations"]] == [
        f"{NAV_DOC_A}_1",
        f"{NAV_DOC_A}_2",
        f"{NAV_DOC_B}_2",
    ]

    classic = run_citation_harness({
        "nav": {"message": sample_message, "options": {"documentCitations": records}},
    })
    assert classic is not None
    classic_md = classic["nav"]["markdown"]
    assert "[8ed56431_1]" not in classic_md
    assert "[15dce0d4_2; 8ed56431_2]" not in classic_md
    assert "NAV_402.xml" in classic_md
    assert "PRIDE_Metadata.xml" in classic_md
    assert f'data-citation-id="{NAV_DOC_A}_1"' in classic_md
    assert f'data-citation-id="{NAV_DOC_B}_2"' in classic_md
    assert f'data-citation-id="{NAV_DOC_A}_2"' in classic_md

    node = shutil.which("node")
    assert node is not None
    node_runner = r"""
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { stripTypeScriptTypes } = require('node:module');

function loadTsModule(relPath, injectedExports = {}) {
    const raw = fs.readFileSync(path.resolve(process.cwd(), relPath), 'utf8');
    const stripped = stripTypeScriptTypes(raw)
        .replace(/^\s*import\s+type\s+[^;]+;\s*$/gm, '')
        .replace(/^\s*import\s+[^;]+;\s*$/gm, '')
        .replace(/^export\s+/gm, '');
    const sandbox = {
        module: { exports: {} },
        exports: {},
        ...injectedExports,
    };
    vm.runInNewContext(
        stripped + '\nmodule.exports = { ' +
        (relPath.includes('m365Citations') ? 'isM365CitationId' :
         relPath.includes('promptVariables') ? 'literalCodeRegions' :
         'parseCitations, CITATION_PLACEHOLDER') + ' };',
        sandbox
    );
    return sandbox.module.exports;
}

const m365 = loadTsModule('./src/lib/m365Citations.ts');
const promptVars = loadTsModule('./src/lib/promptVariables.ts');
const citations = loadTsModule('./src/lib/citations.ts', {
    isM365CitationId: m365.isM365CitationId,
    literalCodeRegions: promptVars.literalCodeRegions,
});
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
process.stdout.write(JSON.stringify(citations.parseCitations(input.message, input.records)));
"""
    checked = subprocess.run(
        [node, "-e", node_runner],
        input=json.dumps({"message": sample_message, "records": records}),
        cwd=V2_DIR,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert checked.returncode == 0, checked.stdout + checked.stderr
    v2_parsed = json.loads(checked.stdout)

    assert "[8ed56431_1]" not in v2_parsed["text"]
    assert "[15dce0d4_2; 8ed56431_2]" not in v2_parsed["text"]
    assert [g["fileName"] for g in v2_parsed["groups"]] == [
        "NAV_402.xml",
        "PRIDE_Metadata.xml",
        "NAV_402.xml",
    ]
    assert [g["citations"][0]["citationId"] for g in v2_parsed["groups"]] == [
        f"{NAV_DOC_A}_1",
        f"{NAV_DOC_B}_2",
        f"{NAV_DOC_A}_2",
    ]


def test_workspace_linked_chat_upload_hydrates_xml_when_screening_is_off():
    """Workspace-backed chat uploads must load their ordered chunks even when Content Screening is off."""
    xml_text = "<procedure id='NAV_402'><initial>Rover in Safe Mode</initial></procedure>"
    fake_docs_module = SimpleNamespace(
        get_ordered_document_chunks=lambda doc_id, **kwargs: [
            {"chunk_text": xml_text, "chunk_sequence": 1, "page_number": 1}
        ]
    )
    previous_docs = sys.modules.get("functions_documents")
    sys.modules["functions_documents"] = fake_docs_module
    try:
        namespace = {
            "get_current_user_id": lambda: "user-1",
            "refresh_workspace_attachment": lambda message, user_id=None: message,
            "assert_document_available": lambda doc_id, user_id, purpose=None: {
                "id": doc_id,
                "user_id": user_id,
                "file_name": "NAV_402.xml",
            },
        }
        _load_functions(
            APP_ROOT / "route_backend_chats.py",
            {"_refresh_workspace_linked_history_message"},
            namespace,
        )
        refreshed = namespace["_refresh_workspace_linked_history_message"]({
            "id": "msg-file-1",
            "role": "file",
            "filename": "NAV_402.xml",
            "file_content_source": "workspace",
            "workspace_document_id": NAV_DOC_A,
            "is_table": False,
            "metadata": {},
        })
    finally:
        if previous_docs is None:
            sys.modules.pop("functions_documents", None)
        else:
            sys.modules["functions_documents"] = previous_docs

    assert refreshed["file_content"] == xml_text


def test_semantic_ranker_quota_exhaustion_falls_back_to_simple_vector_keyword_search():
    """hybrid_search must record the quota warning and fall back to query_type='simple'."""
    search_source = _read(APP_ROOT / "functions_search.py")
    assert "_run_scoped_index_queries(use_semantic_ranker=True)" in search_source
    assert "_run_scoped_index_queries(use_semantic_ranker=False)" in search_source
    assert "if not semantic_fallback_used:\n        clear_semantic_search_quota_warning(source=\"hybrid_search\")" in search_source


def test_version_is_at_least_implementation_version():
    assert_app_version_at_least("0.261.392")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))

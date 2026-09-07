# test_chat_cited_source_tracking.py
#!/usr/bin/env python3
"""
Functional test for cited-source tracking.
Version: 0.260.024
Implemented in: 0.250.215

This test ensures returned sources remain complete while exact document and
web references drive used-document aggregates and export reference buckets.
"""

from copy import deepcopy
from pathlib import Path
import sys
import time

from test_support.versioning import assert_app_version_at_least


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"
CHAT_ROUTE = APP_ROOT / "route_backend_chats.py"
CONVERSATIONS_ROUTE = APP_ROOT / "route_backend_conversations.py"
COLLABORATION_FUNCTIONS = APP_ROOT / "functions_collaboration.py"
COLLABORATION_ROUTE = APP_ROOT / "route_backend_collaboration.py"
CONVERSATION_EXPORT_ROUTE = APP_ROOT / "route_backend_conversation_export.py"
CONVERSATION_DETAILS_JS = (
    APP_ROOT / "static" / "js" / "chat" / "chat-conversation-details.js"
)
CONVERSATION_CONTENTS_JS = (
    APP_ROOT / "static" / "js" / "chat" / "chat-conversation-contents.js"
)
CHAT_STREAMING_JS = APP_ROOT / "static" / "js" / "chat" / "chat-streaming.js"
CHAT_COLLABORATION_JS = (
    APP_ROOT / "static" / "js" / "chat" / "chat-collaboration.js"
)
CHAT_MESSAGES_JS = APP_ROOT / "static" / "js" / "chat" / "chat-messages.js"
CHAT_RETRY_JS = APP_ROOT / "static" / "js" / "chat" / "chat-retry.js"
CHAT_EDIT_JS = APP_ROOT / "static" / "js" / "chat" / "chat-edit.js"
CHAT_CITATION_TRACKING_JS = (
    APP_ROOT / "static" / "js" / "chat" / "chat-citation-tracking.js"
)
INLINE_IMAGES_JS = APP_ROOT / "static" / "js" / "chat" / "chat-inline-images.js"
INLINE_VIDEOS_JS = APP_ROOT / "static" / "js" / "chat" / "chat-inline-videos.js"
SIMPLECHAT_OPERATIONS = APP_ROOT / "functions_simplechat_operations.py"
WORKFLOW_RUNNER = APP_ROOT / "functions_workflow_runner.py"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from functions_citation_tracking import (  # noqa: E402
    CITATION_TRACKING_VERSION,
    USED_DOCUMENTS_TRACKING_VERSION,
    build_cited_source_subsets,
    build_used_documents,
    get_message_reference_citation_buckets,
    initialize_conversation_used_document_tracking,
    merge_cited_documents_into_conversation,
    rebuild_conversation_used_documents,
    resolve_citation_location,
)
from collaboration_models import (  # noqa: E402
    build_collaboration_message_doc_from_legacy,
)


def _hybrid_sources():
    return [
        {
            "file_name": "Policy.pdf",
            "document_id": "doc-policy",
            "citation_id": "doc-policy_1",
            "chunk_id": "1",
            "page_number": 1,
            "classification": "Internal",
        },
        {
            "file_name": "Policy.pdf",
            "document_id": "doc-policy",
            "citation_id": "doc-policy_2",
            "chunk_id": "2",
            "page_number": 2,
            "classification": "Internal",
        },
        {
            "file_name": "Unused.pdf",
            "document_id": "doc-unused",
            "citation_id": "doc-unused_7",
            "chunk_id": "7",
            "page_number": 7,
        },
    ]


def _web_sources():
    return [
        {
            "title": "Cited web page",
            "url": "https://Example.com:443/guidance?view=current#overview",
        },
        {
            "title": "Unused web page",
            "url": "https://example.com/unused",
        },
    ]


def test_exact_document_and_web_references_preserve_sources():
    """Match grouped document IDs and normalized URLs without mutating sources."""
    hybrid_sources = _hybrid_sources()
    web_sources = _web_sources()
    original_hybrid_sources = deepcopy(hybrid_sources)
    original_web_sources = deepcopy(web_sources)
    content = (
        "The policy requires review "
        "(Source: Policy.pdf, Pages: 1, 2) [#doc-policy_1; #doc-policy_2]. "
        "See [current guidance](https://example.com/guidance?view=current). "
        "An unknown token [#doc-missing_9] is ignored."
    )

    tracked = build_cited_source_subsets(
        content,
        hybrid_citations=hybrid_sources,
        web_search_citations=web_sources,
    )

    assert tracked["citation_tracking_version"] == CITATION_TRACKING_VERSION
    assert [
        citation["citation_id"]
        for citation in tracked["cited_hybrid_citations"]
    ] == ["doc-policy_1", "doc-policy_2"]
    assert [
        citation["title"]
        for citation in tracked["cited_web_search_citations"]
    ] == ["Cited web page"]
    assert hybrid_sources == original_hybrid_sources
    assert web_sources == original_web_sources

    tracked["cited_hybrid_citations"][0]["file_name"] = "Changed.pdf"
    assert hybrid_sources[0]["file_name"] == "Policy.pdf"


def test_explicit_source_location_matches_without_hidden_id():
    """Match the visible citation format required by the model prompt."""
    tracked = build_cited_source_subsets(
        "Does the second page control (Source: Policy.pdf, Page: 2)?",
        hybrid_citations=_hybrid_sources(),
        web_search_citations=[],
    )

    assert [
        citation["citation_id"]
        for citation in tracked["cited_hybrid_citations"]
    ] == ["doc-policy_2"]


def test_hidden_id_prevents_same_page_source_overmatching():
    """An exact ID should win over other returned chunks from the same page."""
    same_page_source = {
        **_hybrid_sources()[0],
        "citation_id": "doc-policy_1_other",
        "chunk_id": "1-other",
    }
    tracked = build_cited_source_subsets(
        (
            "The first page controls "
            "(Source: Policy.pdf, Page: 1) [#doc-policy_1]"
        ),
        hybrid_citations=[_hybrid_sources()[0], same_page_source],
        web_search_citations=[],
    )

    assert [
        citation["citation_id"]
        for citation in tracked["cited_hybrid_citations"]
    ] == ["doc-policy_1"]


def test_visible_source_matching_handles_sheet_and_filename_commas():
    """Visible references should support sheet locations and original filenames."""
    tracked = build_cited_source_subsets(
        (
            "The Q1 sheet controls. "
            "(Source: Budget, 2026.xlsx, Sheet: Q1, Final (Approved))"
        ),
        hybrid_citations=[{
            "file_name": "Budget, 2026.xlsx",
            "document_id": "budget-doc",
            "citation_id": "budget-doc_Q1",
            "page_number": "Q1, Final (Approved)",
            "sheet_name": "Q1, Final (Approved)",
            "location_label": "Sheet",
            "location_value": "Q1, Final (Approved)",
        }],
        web_search_citations=[],
    )

    assert [
        citation["citation_id"]
        for citation in tracked["cited_hybrid_citations"]
    ] == ["budget-doc_Q1"]


def test_schema_aware_citation_location_is_shared():
    """Workflow and chat citations should label workbook schemas consistently."""
    assert resolve_citation_location(
        page_number=1,
        chunk_text="Tabular workbook: Budget.xlsx",
        is_tabular=True,
    ) == ("Location", "Workbook Schema")
    assert resolve_citation_location(
        page_number=4,
        chunk_text="Narrative page",
        is_tabular=False,
    ) == ("Page", "4")


def test_citation_patterns_resist_adversarial_input():
    """Bounded citation patterns must not degrade on hostile model output."""
    adversarial_inputs = (
        "[#" + ("[#\\" * 20000),
        "(Source:" + (" " * 40000),
        "(Source: a, Page:" + (" " * 40000),
        "(Source: a, Page: " + ("0" * 40000) + "-1)",
        "[#" + ("0" * 40000),
    )

    hybrid_citations = _hybrid_sources()
    started_at = time.monotonic()
    for adversarial_input in adversarial_inputs:
        tracked = build_cited_source_subsets(
            adversarial_input,
            hybrid_citations=hybrid_citations,
            web_search_citations=_web_sources(),
        )
        assert tracked["cited_hybrid_citations"] == []
        assert tracked["cited_web_search_citations"] == []
    elapsed_seconds = time.monotonic() - started_at

    assert elapsed_seconds < 5, (
        f"Citation matching took {elapsed_seconds:.2f}s on adversarial input"
    )


def test_used_documents_collapse_cited_chunks_only():
    """Collapse multiple cited chunks while excluding retrieved-only documents."""
    source_tags = [
        {
            "category": "document",
            "document_id": "doc-policy",
            "title": "Policy Handbook",
            "file_name": "Policy.pdf",
            "classification": "Internal",
            "chunk_ids": ["doc-policy_1", "doc-policy_2", "doc-policy_3"],
            "scope": {
                "type": "group",
                "id": "group-1",
                "name": "Policy Team",
            },
        },
    ]

    used_documents = build_used_documents(
        _hybrid_sources()[:2],
        source_document_tags=source_tags,
    )

    assert len(used_documents) == 1
    used_document = used_documents[0]
    assert used_document["document_id"] == "doc-policy"
    assert used_document["title"] == "Policy Handbook"
    assert used_document["chunk_ids"] == ["doc-policy_1", "doc-policy_2"]
    assert used_document["citation_ids"] == ["doc-policy_1", "doc-policy_2"]
    assert used_document["page_numbers"] == [1, 2]
    assert used_document["scope"]["name"] == "Policy Team"


def test_reference_buckets_use_strict_empty_values_and_legacy_fallback():
    """Tracked messages must not fall back when exact cited subsets are empty."""
    source_message = {
        "citations": [{"title": "Legacy"}],
        "hybrid_citations": _hybrid_sources(),
        "web_search_citations": _web_sources(),
        "agent_citations": [
            {"tool_name": "Calculator", "function_name": "calculate"},
            {
                "tool_name": "Used web reference",
                "function_name": "azure_ai_foundry_web_search",
            },
        ],
    }

    legacy_buckets = get_message_reference_citation_buckets(source_message)
    assert len(legacy_buckets["hybrid"]) == 3
    assert len(legacy_buckets["web"]) == 2
    assert len(legacy_buckets["agent"]) == 2

    tracked_message = {
        **source_message,
        "citation_tracking_version": CITATION_TRACKING_VERSION,
        "cited_hybrid_citations": [],
        "cited_web_search_citations": [],
    }
    tracked_buckets = get_message_reference_citation_buckets(tracked_message)
    assert tracked_buckets["hybrid"] == []
    assert tracked_buckets["web"] == []
    assert tracked_buckets["agent"] == [{
        "tool_name": "Calculator",
        "function_name": "calculate",
    }]
    assert tracked_buckets["legacy"] == [{"title": "Legacy"}]


def test_conversation_tracking_preserves_legacy_and_merges_exact_usage():
    """Snapshot pre-tracking tags and keep new exact documents separate."""
    conversation = {
        "tags": [
            {
                "category": "document",
                "document_id": "doc-legacy",
                "title": "Historical Source",
                "chunk_ids": ["doc-legacy_1"],
            },
            {
                "category": "participant",
                "user_id": "user-1",
            },
        ],
    }

    initialized = initialize_conversation_used_document_tracking(conversation)
    assert initialized is True
    assert (
        conversation["used_documents_tracking_version"]
        == USED_DOCUMENTS_TRACKING_VERSION
    )
    assert [
        document["document_id"]
        for document in conversation["legacy_used_documents"]
    ] == ["doc-legacy"]
    assert conversation["used_documents"] == []

    conversation["tags"].append({
        "category": "document",
        "document_id": "doc-policy",
        "title": "Policy Handbook",
        "file_name": "Policy.pdf",
        "chunk_ids": ["doc-policy_1", "doc-policy_2", "doc-policy_7"],
        "scope": {
            "type": "group",
            "id": "group-1",
            "name": "Policy Team",
        },
    })
    merged = merge_cited_documents_into_conversation(
        conversation,
        _hybrid_sources()[:2],
    )

    assert [document["document_id"] for document in merged] == ["doc-policy"]
    assert merged[0]["chunk_ids"] == ["doc-policy_1", "doc-policy_2"]
    assert [
        document["document_id"]
        for document in conversation["legacy_used_documents"]
    ] == ["doc-legacy"]


def test_rebuild_uses_active_non_deleted_tracked_assistant_messages():
    """Retry and deletion rebuilds must follow the active visible response set."""
    conversation = {
        "tags": [
            {
                "category": "document",
                "document_id": "doc-policy",
                "title": "Policy Handbook",
                "chunk_ids": ["doc-policy_1", "doc-policy_2"],
            },
            {
                "category": "document",
                "document_id": "doc-unused",
                "title": "Unused Source",
                "chunk_ids": ["doc-unused_7"],
            },
        ],
        "used_documents_tracking_version": USED_DOCUMENTS_TRACKING_VERSION,
        "legacy_used_documents": [],
        "used_documents": [],
    }
    messages = [
        {
            "role": "assistant",
            "citation_tracking_version": CITATION_TRACKING_VERSION,
            "cited_hybrid_citations": [_hybrid_sources()[0]],
            "metadata": {
                "thread_info": {
                    "active_thread": True,
                },
            },
        },
        {
            "role": "assistant",
            "citation_tracking_version": CITATION_TRACKING_VERSION,
            "cited_hybrid_citations": [_hybrid_sources()[1]],
            "metadata": {
                "thread_info": {
                    "active_thread": False,
                },
            },
        },
        {
            "role": "assistant",
            "citation_tracking_version": CITATION_TRACKING_VERSION,
            "cited_hybrid_citations": [_hybrid_sources()[2]],
            "metadata": {
                "is_deleted": True,
                "thread_info": {
                    "active_thread": True,
                },
            },
        },
        {
            "role": "assistant",
            "hybrid_citations": [_hybrid_sources()[2]],
            "metadata": {},
        },
    ]

    rebuilt = rebuild_conversation_used_documents(conversation, messages)

    assert [document["document_id"] for document in rebuilt] == ["doc-policy"]
    assert rebuilt[0]["chunk_ids"] == ["doc-policy_1"]


def test_fork_rebuilds_legacy_fallback_from_copied_messages():
    """Fork legacy fallback must exclude documents introduced after the fork point."""
    conversation = {
        "tags": [
            {
                "category": "document",
                "document_id": "doc-policy",
                "title": "Policy Handbook",
                "chunk_ids": ["doc-policy_1"],
            },
            {
                "category": "document",
                "document_id": "doc-unused",
                "title": "Later Source",
                "chunk_ids": ["doc-unused_7"],
            },
        ],
    }
    copied_messages = [
        {
            "role": "assistant",
            "hybrid_citations": [_hybrid_sources()[0]],
            "metadata": {
                "thread_info": {
                    "active_thread": True,
                },
            },
        },
    ]

    rebuild_conversation_used_documents(
        conversation,
        copied_messages,
        rebuild_legacy=True,
    )

    assert conversation["used_documents"] == []
    assert [
        document["document_id"]
        for document in conversation["legacy_used_documents"]
    ] == ["doc-policy"]


def test_chat_publication_paths_persist_tracking_and_aggregates():
    """Verify each chat publication path stores exact subsets and aggregates."""
    route_source = CHAT_ROUTE.read_text(encoding="utf-8")

    required_snippets = [
        "document_action_citation_tracking = build_cited_source_subsets(",
        "citation_tracking = build_cited_source_subsets(",
        "stream_citation_tracking = build_cited_source_subsets(",
        "partial_citation_tracking = build_cited_source_subsets(",
        "interrupted_citation_tracking = build_cited_source_subsets(",
        "**document_action_citation_tracking,",
        "**citation_tracking,",
        "**stream_citation_tracking,",
        "initialize_conversation_used_document_tracking(conversation_item)",
        "merge_cited_documents_into_conversation(",
        "'hybrid_citations': hybrid_citations_list",
        "'web_search_citations': web_search_citations_list",
    ]
    missing = [
        snippet
        for snippet in required_snippets
        if snippet not in route_source
    ]
    assert not missing, f"Missing chat citation tracking wiring: {missing}"
    assert route_source.count("merge_cited_documents_into_conversation(") >= 4
    assert "Copy the exact bracketed citation ID shown after the supporting excerpt." in route_source
    assert 'reason="chat_stream_interrupted"' in route_source
    assert route_source.count("collect_stream_response_conversation_metadata()") >= 4
    assert '"sheet_name": source_doc.get("sheet_name")' in route_source
    assert '"sheet_name": sheet_name' in route_source


def test_lifecycle_mutations_and_forks_rebuild_exact_usage():
    """Verify retry/edit/switch/delete/fork paths invoke the shared rebuild."""
    route_source = CONVERSATIONS_ROUTE.read_text(encoding="utf-8")
    operations_source = SIMPLECHAT_OPERATIONS.read_text(encoding="utf-8")

    assert (
        route_source.count(
            "_rebuild_authorized_personal_conversation_used_documents("
        )
        >= 5
    )
    for reason in (
        "message_deleted",
        "message_retry_created",
        "message_edit_created",
        "message_attempt_switched",
    ):
        assert reason in route_source
    assert '"used_documents_tracking_version"' in operations_source
    assert '"legacy_used_documents"' in operations_source
    assert "rebuild_legacy=True" in operations_source
    assert '"used_documents_tracking_version": conversation_item.get(' in route_source
    assert '"legacy_used_documents": conversation_item.get(' in route_source
    assert '"used_documents": conversation_item.get(' in route_source
    assert "except Exception as rebuild_error:" in route_source
    assert "used_documents_rebuild_required" in route_source


def test_collaboration_and_workflow_propagate_tracking_contract():
    """Verify shared and workflow messages retain exact cited subsets."""
    legacy_message = {
        "id": "assistant-source-1",
        "role": "assistant",
        "content": "Tracked response",
        "timestamp": "2026-08-14T12:00:00Z",
        "citation_tracking_version": CITATION_TRACKING_VERSION,
        "cited_hybrid_citations": [_hybrid_sources()[0]],
        "cited_web_search_citations": [_web_sources()[0]],
    }
    converted = build_collaboration_message_doc_from_legacy(
        conversation_id="collaboration-1",
        legacy_message=legacy_message,
        default_sender_user={
            "user_id": "user-1",
            "display_name": "Test User",
            "email": "test@example.com",
        },
    )
    assert converted["citation_tracking_version"] == CITATION_TRACKING_VERSION
    assert converted["cited_hybrid_citations"][0]["citation_id"] == "doc-policy_1"
    assert converted["cited_web_search_citations"][0]["title"] == "Cited web page"

    collaboration_source = COLLABORATION_FUNCTIONS.read_text(encoding="utf-8")
    collaboration_route_source = COLLABORATION_ROUTE.read_text(encoding="utf-8")
    workflow_source = WORKFLOW_RUNNER.read_text(encoding="utf-8")

    for field_name in (
        "citation_tracking_version",
        "cited_hybrid_citations",
        "cited_web_search_citations",
        "used_documents_tracking_version",
        "legacy_used_documents",
        "used_documents",
    ):
        assert field_name in collaboration_source
    assert "rebuild_conversation_used_documents(conversation_doc, remaining_messages)" in collaboration_source
    assert "'cited_hybrid_citations': serialized_assistant_message.get(" in collaboration_route_source
    assert "stream_payload['done'] = True" in collaboration_route_source
    assert "'conversation_kind': serialized_final_conversation.get(" in collaboration_route_source
    assert "citation_tracking = build_cited_source_subsets(" in workflow_source
    assert "merge_cited_documents_into_conversation(" in workflow_source
    assert "(Source: {file_name}, {location_label}: {location_value}) [#{citation_id}]" in workflow_source
    assert "'sheet_name': sheet_name" in workflow_source
    assert "resolve_citation_location(" in workflow_source


def test_ui_and_exports_select_cited_subsets_without_losing_sources():
    """Verify downstream consumers separate source inventory from references."""
    details_source = CONVERSATION_DETAILS_JS.read_text(encoding="utf-8")
    contents_source = CONVERSATION_CONTENTS_JS.read_text(encoding="utf-8")
    export_source = CONVERSATION_EXPORT_ROUTE.read_text(encoding="utf-8")

    assert "export function getConversationDocumentTags(metadata = {})" in details_source
    assert "export function getConversationUsedDocuments(metadata = {})" in details_source
    assert "getConversationExactUsedDocuments(metadata)" in details_source
    assert "getConversationLegacyUsedDocuments(metadata)" in details_source
    assert "conversation-document-cited-badge" in details_source
    assert "Source documents" in details_source
    assert "getConversationUsedDocuments," in contents_source
    assert "const documents = getConversationUsedDocuments(metadata);" in contents_source
    assert "Documents cited in active responses" in contents_source
    assert "exactDocuments.length > 0" in contents_source

    streaming_source = CHAT_STREAMING_JS.read_text(encoding="utf-8")
    assert "function hasCitedWorkspaceDocuments(payload)" in streaming_source
    assert "hasCitedWorkspaceDocuments(finalData)" in streaming_source
    assert (
        "notifyConversationDocumentsMayHaveChanged("
        in streaming_source
    )
    assert "data.message_persisted" in streaming_source
    assert "&& data.message_id" in streaming_source
    assert "&& data.conversation_id" in streaming_source
    assert "void loadMessages(data.conversation_id).catch" in streaming_source
    assert "data.conversation_kind === 'collaborative'" in streaming_source
    assert ".loadConversationMessages(data.conversation_id)" in streaming_source

    collaboration_ui_source = CHAT_COLLABORATION_JS.read_text(encoding="utf-8")
    assert "'chat:conversation-documents-refresh'" in collaboration_ui_source
    assert "String(payload.message.role || '').trim().toLowerCase() === 'assistant'" in collaboration_ui_source
    assert "conversationKind: 'collaborative'" in collaboration_ui_source
    assert "loadConversationMessages," in collaboration_ui_source

    for mutation_source_path in (
        CHAT_MESSAGES_JS,
        CHAT_RETRY_JS,
        CHAT_EDIT_JS,
    ):
        mutation_source = mutation_source_path.read_text(encoding="utf-8")
        assert "'chat:conversation-documents-refresh'" in mutation_source

    assert "return get_message_reference_citation_buckets(message)" in export_source
    assert "return get_message_source_citation_buckets(message)" in export_source
    assert "source_citation_buckets = _collect_source_citation_buckets(message)" in export_source
    assert "'cited_hybrid_citations': (" in export_source
    assert "'cited_web_search_citations': (" in export_source
    assert "Document References" in export_source
    assert "Web References" in export_source


def test_inline_media_galleries_render_cited_subsets_only():
    """Verify inline image and video galleries consume cited subsets, not sources."""
    tracking_source = CHAT_CITATION_TRACKING_JS.read_text(encoding="utf-8")
    messages_source = CHAT_MESSAGES_JS.read_text(encoding="utf-8")
    images_source = INLINE_IMAGES_JS.read_text(encoding="utf-8")
    videos_source = INLINE_VIDEOS_JS.read_text(encoding="utf-8")

    assert "export function messageHasCitationTracking(message)" in tracking_source
    assert "export function getCitedHybridCitations(message, sourceCitations = [])" in tracking_source
    assert "export function getCitedWebCitations(message, sourceCitations = [])" in tracking_source
    assert '"cited_hybrid_citations" in message || "cited_web_search_citations" in message' in tracking_source

    assert (
        "import { getCitedHybridCitations, getCitedWebCitations } from './chat-citation-tracking.js';"
        in messages_source
    )
    assert (
        "const citedHybridCitations = getCitedHybridCitations(fullMessageObject, hybridCitations);"
        in messages_source
    )
    assert (
        "const citedWebCitations = getCitedWebCitations(fullMessageObject, webCitations);"
        in messages_source
    )

    # Sources keeps the complete retrieved inventory; only the galleries narrow.
    citations_call = messages_source.split(
        "const citationsButtonsHtml = createCitationsHtml("
    )[1].split(");")[0]
    assert "hybridCitations," in citations_call
    assert "webCitations," in citations_call
    assert "citedHybridCitations" not in citations_call
    assert "citedWebCitations" not in citations_call

    for gallery_source in (images_source, videos_source):
        assert "citedHybridCitations = []," in gallery_source
        assert "citedWebCitations = []," in gallery_source
        assert "agentCitations = []," in gallery_source


def test_version_is_available():
    """Verify the application includes the cited-source tracking version."""
    assert_app_version_at_least("0.250.215")


if __name__ == "__main__":
    tests = [
        test_exact_document_and_web_references_preserve_sources,
        test_explicit_source_location_matches_without_hidden_id,
        test_hidden_id_prevents_same_page_source_overmatching,
        test_visible_source_matching_handles_sheet_and_filename_commas,
        test_schema_aware_citation_location_is_shared,
        test_citation_patterns_resist_adversarial_input,
        test_used_documents_collapse_cited_chunks_only,
        test_reference_buckets_use_strict_empty_values_and_legacy_fallback,
        test_conversation_tracking_preserves_legacy_and_merges_exact_usage,
        test_rebuild_uses_active_non_deleted_tracked_assistant_messages,
        test_fork_rebuilds_legacy_fallback_from_copied_messages,
        test_chat_publication_paths_persist_tracking_and_aggregates,
        test_lifecycle_mutations_and_forks_rebuild_exact_usage,
        test_collaboration_and_workflow_propagate_tracking_contract,
        test_ui_and_exports_select_cited_subsets_without_losing_sources,
        test_inline_media_galleries_render_cited_subsets_only,
        test_version_is_available,
    ]
    for test in tests:
        test()
    print(f"Cited-source tracking tests passed: {len(tests)}/{len(tests)}")

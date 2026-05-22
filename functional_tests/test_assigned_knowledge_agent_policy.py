# test_assigned_knowledge_agent_policy.py
"""
Functional test for Assigned Knowledge agent policy.
Version: 0.241.087
Implemented in: 0.241.068

This test ensures that Assigned Knowledge is normalized, constrained by
agent scope, converted into trusted runtime search filters, and keeps
user workspace context and assigned web sources governed by agent policy.
"""

import os
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
APP_PATH = ROOT / "application" / "single_app"
if str(APP_PATH) not in sys.path:
    sys.path.insert(0, str(APP_PATH))

import functions_assigned_knowledge as assigned_knowledge
import functions_search
import functions_source_review


TEST_USER_ID = "assigned-knowledge-user"


def _document_record_side_effect(user_id, document_id, **kwargs):
    if document_id == "personal-doc" and not kwargs:
        return {"id": document_id, "user_id": user_id}
    if document_id == "group-doc" and kwargs.get("group_id") == "group-1":
        return {"id": document_id, "group_id": "group-1"}
    if document_id == "public-doc" and kwargs.get("public_workspace_id") == "public-1":
        return {"id": document_id, "public_workspace_id": "public-1"}
    return None


def _public_workspace_side_effect(workspace_id):
    if workspace_id == "public-1":
        return {"id": workspace_id, "name": "Public One"}
    return None


def _group_side_effect(group_id):
    if group_id == "group-1":
        return {"id": group_id, "name": "Group One"}
    return None


def _mock_policy_dependencies():
    return patch.multiple(
        assigned_knowledge,
        get_user_visible_public_workspace_ids_from_settings=lambda user_id: ["public-1"],
        find_public_workspace_by_id=_public_workspace_side_effect,
        find_group_by_id=_group_side_effect,
        get_user_role_in_group=lambda group_doc, user_id: "Owner",
        get_document_record=_document_record_side_effect,
    )


def test_personal_agent_policy_allows_personal_and_public_sources():
    """Validate personal agents can use personal and visible public knowledge."""
    raw_config = {
        "enabled": True,
        "scopes": {
            "personal": True,
            "public_workspace_ids": ["public-1"],
        },
        "document_ids": ["personal-doc", "public-doc"],
        "tags": ["Finance", "finance", "Operations"],
    }

    with _mock_policy_dependencies():
        normalized = assigned_knowledge.validate_assigned_knowledge_for_agent(
            raw_config,
            user_id=TEST_USER_ID,
            agent_scope="personal",
        )

    assert normalized["enabled"] is True
    assert normalized["scopes"]["personal"] is True
    assert normalized["scopes"]["group_ids"] == []
    assert normalized["scopes"]["public_workspace_ids"] == ["public-1"]
    assert normalized["document_ids"] == ["personal-doc", "public-doc"]
    assert normalized["tags"] == ["finance", "operations"]


def test_group_agent_policy_forces_current_group_scope():
    """Validate group agents cannot persist arbitrary group source IDs."""
    raw_config = {
        "enabled": True,
        "scopes": {
            "personal": True,
            "group_ids": ["other-group"],
            "public_workspace_ids": ["public-1"],
        },
        "document_ids": ["group-doc"],
        "tags": ["Projects"],
    }

    with _mock_policy_dependencies():
        normalized = assigned_knowledge.validate_assigned_knowledge_for_agent(
            raw_config,
            user_id=TEST_USER_ID,
            agent_scope="group",
            group_id="group-1",
        )

    assert normalized["scopes"] == {
        "personal": False,
        "group_ids": ["group-1"],
        "public_workspace_ids": [],
    }
    assert normalized["document_ids"] == ["group-doc"]


def test_global_agent_policy_rejects_non_public_knowledge():
    """Validate global agents must have at least one public source when enabled."""
    raw_config = {
        "enabled": True,
        "scopes": {
            "personal": True,
        },
        "document_ids": [],
        "tags": [],
    }

    with _mock_policy_dependencies():
        try:
            assigned_knowledge.validate_assigned_knowledge_for_agent(
                raw_config,
                user_id=TEST_USER_ID,
                agent_scope="global",
                is_admin=True,
            )
        except assigned_knowledge.AssignedKnowledgeError as error:
            assert "Choose at least one knowledge source" in str(error)
        else:
            raise AssertionError("Global Assigned Knowledge accepted a non-public source")


def test_runtime_filters_use_agent_assigned_knowledge_only():
    """Validate chat runtime filters are built from stored agent metadata."""
    agent_payload = {
        "name": "PolicyAgent",
        "other_settings": {
            "assigned_knowledge": {
                "enabled": True,
                "scopes": {
                    "personal": True,
                    "public_workspace_ids": ["public-1"],
                },
                "document_ids": ["personal-doc", "public-doc"],
                "tags": ["Finance"],
            }
        },
    }

    filters = assigned_knowledge.build_assigned_knowledge_runtime_filters(agent_payload)

    assert filters["enabled"] is True
    assert filters["doc_scope"] == "all"
    assert filters["document_ids"] == ["personal-doc", "public-doc"]
    assert filters["tags_filter"] == ["finance"]
    assert filters["active_group_ids"] == []
    assert filters["active_public_workspace_ids"] == ["public-1"]
    assert filters["document_filter_mode"] == "union"
    assert filters["allow_user_workspace_context"] is False
    assert filters["allowed_user_workspace_actions"] == ["search", "analyze", "compare"]


def test_user_workspace_context_policy_is_normalized_for_runtime():
    """Validate optional user workspace context policy is stored and exposed safely."""
    raw_config = {
        "enabled": True,
        "scopes": {
            "personal": True,
        },
        "document_ids": ["personal-doc"],
        "allow_user_workspace_context": True,
        "allowed_user_context_actions": ["search", "comparison", "invalid", "search"],
    }

    with _mock_policy_dependencies():
        normalized = assigned_knowledge.validate_assigned_knowledge_for_agent(
            raw_config,
            user_id=TEST_USER_ID,
            agent_scope="personal",
        )

    assert normalized["allow_user_workspace_context"] is True
    assert normalized["allowed_user_workspace_actions"] == ["search", "compare"]

    filters = assigned_knowledge.build_assigned_knowledge_runtime_filters({
        "name": "PolicyAgent",
        "other_settings": {"assigned_knowledge": normalized},
    })
    assert filters["allow_user_workspace_context"] is True
    assert filters["allowed_user_workspace_actions"] == ["search", "compare"]


def test_assigned_web_sources_are_normalized_for_runtime():
    """Validate Assigned Knowledge can include trusted URL and Deep Research sources."""
    raw_config = {
        "enabled": True,
        "web_sources": [
            {"url": "https://Example.com/path#fragment", "mode": "url_access"},
            {"url": "https://example.com/path", "mode": "deep_research"},
            {"url": "javascript:alert(1)", "mode": "deep_research"},
        ],
    }

    with _mock_policy_dependencies():
        normalized = assigned_knowledge.validate_assigned_knowledge_for_agent(
            raw_config,
            user_id=TEST_USER_ID,
            agent_scope="personal",
        )

    assert normalized["web_sources"] == [{
        "url": "https://example.com/path",
        "mode": "deep_research",
    }]

    filters = assigned_knowledge.build_assigned_knowledge_runtime_filters({
        "name": "WebPolicyAgent",
        "other_settings": {"assigned_knowledge": normalized},
    })
    assert filters["enabled"] is True
    assert filters["doc_scope"] is None
    assert filters["has_workspace_knowledge"] is False
    assert filters["has_web_sources"] is True
    assert filters["web_sources"] == normalized["web_sources"]


def test_source_review_collects_assigned_seed_urls():
    """Validate assigned URL seeds are additive with user-pasted and citation URLs."""
    seed_urls = functions_source_review.collect_source_review_seed_urls(
        "Please review https://example.com/user",
        [{"url": "https://example.com/citation"}],
        direct_url_limit=10,
        additional_seed_urls=[
            "https://example.com/assigned#section",
            "https://example.com/user",
        ],
    )

    assert seed_urls == [
        "https://example.com/user",
        "https://example.com/assigned",
        "https://example.com/citation",
    ]


def test_assigned_knowledge_search_filter_uses_additive_document_semantics():
    """Validate explicit documents are OR'd with dynamic tag matches for Assigned Knowledge."""
    document_filter = "document_id eq 'doc-explicit'"
    tags_filter = "document_tags/any(t: t eq 'finance') and document_tags/any(t: t eq 'planning')"

    union_filter = functions_search._build_document_content_filter(
        document_filter,
        tags_filter,
        document_filter_mode="union",
    )
    intersection_filter = functions_search._build_document_content_filter(
        document_filter,
        tags_filter,
    )

    assert union_filter == (
        "(document_id eq 'doc-explicit' or "
        "(document_tags/any(t: t eq 'finance') and document_tags/any(t: t eq 'planning')))"
    )
    assert intersection_filter == (
        "document_id eq 'doc-explicit' and "
        "document_tags/any(t: t eq 'finance') and document_tags/any(t: t eq 'planning')"
    )


def test_apply_assigned_knowledge_writes_canonical_other_settings():
    """Validate agent save payloads persist canonical Assigned Knowledge config."""
    agent_payload = {
        "name": "AssignedKnowledgeAgent",
        "other_settings": {
            "assigned_knowledge": {
                "enabled": True,
                "sources": [
                    {"scope": "personal"},
                    {"scope": "public", "id": "public-1"},
                ],
                "selected_document_ids": ["personal-doc", "public-doc"],
                "tags": ["Finance"],
                "web_sources": [
                    {"url": "https://example.com/guide", "mode": "deep_research"},
                ],
                "allow_user_workspace_context": True,
                "allowed_user_workspace_actions": ["analyze"],
            },
            "temperature": 0.2,
        },
    }

    with _mock_policy_dependencies():
        cleaned = assigned_knowledge.apply_assigned_knowledge_to_agent_payload(
            agent_payload,
            user_id=TEST_USER_ID,
            agent_scope="personal",
        )

    stored_config = cleaned["other_settings"]["assigned_knowledge"]
    assert cleaned["other_settings"]["temperature"] == 0.2
    assert stored_config["enabled"] is True
    assert stored_config["scopes"]["personal"] is True
    assert stored_config["scopes"]["public_workspace_ids"] == ["public-1"]
    assert stored_config["document_ids"] == ["personal-doc", "public-doc"]
    assert stored_config["web_sources"] == [{
        "url": "https://example.com/guide",
        "mode": "deep_research",
    }]
    assert stored_config["allow_user_workspace_context"] is True
    assert stored_config["allowed_user_workspace_actions"] == ["analyze"]


def test_public_workspace_search_filter_respects_user_visibility():
    """Validate list-valued public workspace filters stay user-visible."""
    with patch.object(
        functions_search,
        "get_user_visible_public_workspace_ids_from_settings",
        return_value=["public-1", "public-3"],
    ):
        assert functions_search._resolve_public_workspace_ids_for_search(
            TEST_USER_ID,
            ["public-2", "public-1", "public-1"],
        ) == ["public-1"]
        assert functions_search._resolve_public_workspace_ids_for_search(
            TEST_USER_ID,
            None,
        ) == ["public-1", "public-3"]


def run_all_tests():
    """Run all tests in this file without requiring pytest."""
    tests = [
        test_personal_agent_policy_allows_personal_and_public_sources,
        test_group_agent_policy_forces_current_group_scope,
        test_global_agent_policy_rejects_non_public_knowledge,
        test_runtime_filters_use_agent_assigned_knowledge_only,
        test_user_workspace_context_policy_is_normalized_for_runtime,
        test_assigned_web_sources_are_normalized_for_runtime,
        test_source_review_collects_assigned_seed_urls,
        test_assigned_knowledge_search_filter_uses_additive_document_semantics,
        test_apply_assigned_knowledge_writes_canonical_other_settings,
        test_public_workspace_search_filter_respects_user_visibility,
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

    passed = sum(1 for result in results if result)
    print(f"Results: {passed}/{len(results)} tests passed")
    return all(results)


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)

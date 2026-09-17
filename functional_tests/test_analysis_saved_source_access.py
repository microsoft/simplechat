# test_analysis_saved_source_access.py
"""
Functional tests for current source access on saved Analyze results.
Version: 0.261.107
Implemented in: 0.261.107

Saved results require access to every contributor; large selections are resolved
without dropping sources, and historical explanation differs from checkpoint reuse.
"""

from copy import deepcopy

import pytest

from test_support.app_stubs import import_app_module


access = import_app_module("functions_analysis_access")


def source(document_id="doc-1", scope="personal", scope_id="user-1"):
    return {
        "document_id": document_id,
        "scope": scope,
        "scope_id": scope_id,
        "source_version": "1",
        "source_revision": "etag-1",
        "authorization_status": "authorized",
    }


def resolver_for(sources, calls=None):
    by_id = {item["document_id"]: item for item in sources}

    def resolve(document_ids, **context):
        if calls is not None:
            calls.append((list(document_ids), context))
        return [deepcopy(by_id[document_id]) for document_id in document_ids]

    return resolve


@pytest.mark.parametrize("count", [1, 10, 100, 300, 500])
def test_source_resolution_reads_every_source_in_bounded_batches(count):
    sources = [source(f"doc-{index}") for index in range(count)]
    calls = []
    result = access.authorize_analysis_sources(
        "user-1", sources, resolver=resolver_for(sources, calls)
    )
    assert result == {"source_count": count, "source_snapshot_changed": False}
    assert [document_id for batch, _ in calls for document_id in batch] == [
        item["document_id"] for item in sources
    ]
    assert all(len(batch) <= access.SOURCE_MANIFEST_MAX_SOURCES for batch, _ in calls)


def test_one_revoked_contributor_blocks_the_entire_mixed_result():
    original = [
        source("personal"),
        source("group", "group", "group-1"),
        source("public", "public", "public-1"),
    ]
    fresh = deepcopy(original)
    fresh[1]["authorization_status"] = "unresolved"
    with pytest.raises(access.AnalysisResultUnavailable):
        access.authorize_analysis_sources("user-1", original, resolver=resolver_for(fresh))


@pytest.mark.parametrize("field,value", [("scope", "public"), ("scope_id", "another-user")])
def test_a_different_authorized_scope_cannot_substitute_for_the_original(field, value):
    original = [source()]
    fresh = deepcopy(original)
    fresh[0][field] = value
    with pytest.raises(access.AnalysisResultUnavailable):
        access.authorize_analysis_sources("user-1", original, resolver=resolver_for(fresh))


@pytest.mark.parametrize("field", ["source_version", "source_revision"])
def test_history_can_be_explained_but_changed_sources_cannot_resume(field):
    original = [source()]
    fresh = deepcopy(original)
    fresh[0][field] = "changed"
    result = access.authorize_analysis_sources("user-1", original, resolver=resolver_for(fresh))
    assert result["source_snapshot_changed"] is True
    with pytest.raises(access.AnalysisResultUnavailable) as failure:
        access.authorize_analysis_sources(
            "user-1", original, require_snapshot=True, resolver=resolver_for(fresh)
        )
    assert failure.value.code == "analysis_source_snapshot_changed"


def test_chat_source_uses_its_own_conversation_access_boundary():
    original = [source("upload-1", "chat", "source-conversation")]
    calls = []
    access.authorize_analysis_sources("user-1", original, resolver=resolver_for(original, calls))
    assert calls[0][1] == {
        "user_id": "user-1",
        "doc_scope": "all",
        "active_group_ids": [],
        "active_public_workspace_ids": [],
        "conversation_id": "source-conversation",
    }


def test_incomplete_or_reordered_resolution_is_not_success():
    original = [source("first"), source("second")]
    for returned in ([], original[:1], list(reversed(original))):
        with pytest.raises(access.AnalysisResultUnavailable):
            access.authorize_analysis_sources(
                "user-1", original, resolver=lambda *args, **kwargs: returned
            )


def test_resolution_failure_never_reuses_cached_permissions():
    def failed_resolver(*args, **kwargs):
        raise ConnectionError("storage unavailable")

    with pytest.raises(ConnectionError):
        access.authorize_analysis_sources("user-1", [source()], resolver=failed_resolver)


@pytest.mark.parametrize("sources", [None, [], [{}], [{"document_id": "doc-1"}]])
def test_missing_source_lineage_is_not_treated_as_authorized(sources):
    with pytest.raises(access.AnalysisResultUnavailable):
        access.authorize_analysis_sources("user-1", sources)


def test_snapshot_drops_storage_paths_and_removes_identical_replay():
    original = source()
    original["storage_locator"] = {"container": "private", "blob_path": "not-public"}
    snapshot = access.analysis_source_snapshot([original, deepcopy(original)])
    assert len(snapshot) == 1
    assert set(snapshot[0]) == {
        "document_id", "scope", "scope_id", "source_version", "source_revision",
    }


@pytest.mark.parametrize("field,value", [
    ("scope", []),
    ("source_version", float("nan")),
    ("source_version", True),
    ("source_revision", {"invalid": "revision"}),
])
def test_invalid_source_identity_is_rejected(field, value):
    original = source()
    original[field] = value
    with pytest.raises(access.AnalysisResultUnavailable):
        access.analysis_source_snapshot([original])


def test_unversioned_sources_are_not_reusable_checkpoints():
    original = [{**source(), "source_version": None, "source_revision": None}]
    access.authorize_analysis_sources("user-1", original, resolver=resolver_for(original))
    with pytest.raises(access.AnalysisResultUnavailable):
        access.authorize_analysis_sources(
            "user-1", original, require_snapshot=True, resolver=resolver_for(original)
        )


def test_reference_contributors_merge_with_existing_analysis_policy():
    reference = {
        "document_id": "shared-reference", "scope_type": "group", "scope_id": "group-1",
        "source_version": "2", "content_sha256": "A" * 64,
    }
    inherited = access.build_analysis_access([source()])
    policy = access.build_analysis_access([reference, reference], inherited=[inherited])
    assert policy["version"] == access.ANALYSIS_SOURCE_ACCESS_VERSION
    assert [item["document_id"] for item in policy["sources"]] == ["shared-reference", "doc-1"]
    assert policy["sources"][0]["scope"] == "group"
    assert policy["sources"][0]["content_sha256"] == "a" * 64
    assert "scope_type" not in policy["sources"][0]
    assert "scope" not in reference
    fresh = [{**policy["sources"][0], "authorization_status": "unresolved"}, source()]
    with pytest.raises(access.AnalysisResultUnavailable):
        access.authorize_analysis_sources("user-1", policy["sources"], resolver=resolver_for(fresh))


def test_no_contributors_does_not_create_an_empty_access_policy():
    assert access.build_analysis_access() is None


@pytest.mark.parametrize("sources,inherited", [
    ([{**source(), "scope_type": "group"}], []),
    ([{**source(), "content_sha256": "not-a-digest"}], []),
    ([], [{"version": "future", "sources": [source()]}]),
    ([], [{"version": access.ANALYSIS_SOURCE_ACCESS_VERSION, "sources": []}]),
])
def test_malformed_contributor_merge_fails_explicitly(sources, inherited):
    with pytest.raises(access.AnalysisResultUnavailable):
        access.build_analysis_access(sources, inherited=inherited)

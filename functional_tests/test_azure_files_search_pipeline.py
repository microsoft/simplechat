#!/usr/bin/env python3
# test_azure_files_search_pipeline.py
"""
Functional test for the Azure Files Search action's search and permission pipeline.
Version: 0.261.294
Implemented in: 0.261.294

This test ensures that the Azure Files Search action validates its configuration, refuses
SimpleChat's own indexes, parses indexed Azure Files paths, and returns only results from files
the signed-in user is proven able to open. Denied and unverifiable files are withheld from the
model without being mentioned, and recorded for administrators with reason codes. It also covers
the Graph and ARM identity helpers and the global-only action rule, without calling Azure.
"""

import dataclasses
import sys
import threading
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"
FUNCTIONAL_TESTS_ROOT = REPO_ROOT / "functional_tests"
for _path in (str(APP_ROOT), str(FUNCTIONAL_TESTS_ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import functions_azure_files_access as access  # noqa: E402
import functions_azure_files_acl as acl  # noqa: E402
import functions_azure_files_search as afs  # noqa: E402
from functions_action_manifest import GlobalOnlyActionTypeError, is_global_only_action_type  # noqa: E402
from functions_azure_endpoint_validation import validate_azure_file_endpoint, validate_azure_search_endpoint  # noqa: E402
from functions_legacy_action_management import prepare_scoped_action  # noqa: E402
from test_support.versioning import assert_app_version_at_least  # noqa: E402

SUBSCRIPTION = "11111111-2222-3333-4444-555555555555"
ACCOUNT_ID = f"/subscriptions/{SUBSCRIPTION}/resourceGroups/rg-files/providers/Microsoft.Storage/storageAccounts/finfiles"
USER_ID = "73d664e4-0886-4a73-b745-c694da45ddb4"
USER_SID = "S-1-12-1-1943430372-1249052806-2496021943-3034400218"
OTHER_GROUP_SID = "S-1-12-1-1000000001-1000000002-1000000003-1000000004"
UNKNOWN_SID = "S-1-5-21-1111111111-2222222222-3333333333-1105"


def _manifest(**fields):
    additional = {
        "index_name": "finance-files",
        "storage_shares": [{"storage_account_resource_id": ACCOUNT_ID, "share_name": "docs"}],
    }
    additional.update(fields)
    return {
        "id": "action-1",
        "name": "finance_files",
        "displayName": "Finance files",
        "type": "azure_files_index",
        "endpoint": "https://contoso-search.search.windows.net",
        "auth": {"type": "identity", "identity": "managed_identity"},
        "additionalFields": additional,
    }


def _url(path):
    return f"https://finfiles.file.core.windows.net/docs/{path}"


def _hit(path, content="Quarterly budget forecast", score=1.0, **extra):
    hit = {
        "metadata_storage_path": _url(path),
        "metadata_storage_name": path.rsplit("/", 1)[-1],
        "content": content,
        "@search.score": score,
    }
    hit.update(extra)
    return hit


SDDL_BY_PATH = {
    "allowed/budget.txt": f"O:BAG:SYD:P(A;;FA;;;SY)(A;;FR;;;{USER_SID})",
    "denied/salaries.txt": f"O:BAG:SYD:P(A;;FA;;;SY)(A;;FR;;;{OTHER_GROUP_SID})",
    "unknown/merger.txt": f"O:BAG:SYD:P(A;;FA;;;SY)(A;;FR;;;{UNKNOWN_SID})",
    "deny/incident.txt": f"O:BAG:SYD:P(D;;FA;;;{USER_SID})(A;;FR;;;WD)",
}


def _membership():
    return acl.build_membership(
        [USER_SID],
        resolve_unknown_sid=lambda sid: acl.NOT_MEMBER if sid == OTHER_GROUP_SID else acl.UNKNOWN,
    )


def _dependencies(hits, *, membership=None, identity_reason="", share=(acl.MEMBER, "share_role_assignment"), reader=None):
    def read_file_sddl(path):
        return SDDL_BY_PATH[path.relative_path]

    return afs.SearchDependencies(
        run_search=lambda request: [dict(hit) for hit in hits],
        read_file_sddl=reader or read_file_sddl,
        check_share_access=lambda entry: share,
        membership=membership,
        evaluate_sddl=acl.evaluate_sddl_read_access,
        identity_error_reason=identity_reason,
    )


def test_version():
    assert_app_version_at_least("0.261.294")


def test_endpoint_validators():
    assert validate_azure_search_endpoint("contoso-search.search.windows.net") == "https://contoso-search.search.windows.net"
    assert validate_azure_search_endpoint("https://gov-search.search.azure.us/") == "https://gov-search.search.azure.us"
    for hostile in (
        "https://attacker.invalid",
        "https://a.b.search.windows.net",
        "http://contoso.search.windows.net",
        "https://contoso.search.windows.net.evil.com",
        "https://contoso.search.windows.net:8443",
        "https://127.0.0.1",
    ):
        with pytest.raises(ValueError):
            validate_azure_search_endpoint(hostile)
    assert validate_azure_file_endpoint("https://finfiles.file.core.windows.net") == "https://finfiles.file.core.windows.net"
    with pytest.raises(ValueError):
        validate_azure_file_endpoint("https://finfiles.blob.core.windows.net")


def test_config_defaults_by_layout():
    whole_file = afs.normalize_azure_files_search_config(_manifest())
    assert (whole_file.content_field, whole_file.path_field, whole_file.select_content) == ("content", "metadata_storage_path", False)
    assert whole_file.permission_mode == afs.PERMISSION_MODE_LIVE_ACL
    assert whole_file.storage_shares[0].account.account_name == "finfiles"
    chunked = afs.normalize_azure_files_search_config(_manifest(index_layout="chunked", query_mode="hybrid"))
    assert (chunked.content_field, chunked.vector_field, chunked.select_content) == ("chunk", "text_vector", True)
    custom = afs.normalize_azure_files_search_config(_manifest(index_layout="custom", content_field="body", path_field="file_url"))
    assert (custom.content_field, custom.path_field) == ("body", "file_url")
    bounded = afs.normalize_azure_files_search_config(_manifest(default_top_n=500, max_candidates=1, time_budget_seconds=999))
    assert (bounded.default_top_n, bounded.max_candidates, bounded.time_budget_seconds) == (afs.MAX_TOP_N, afs.MIN_CANDIDATES, afs.MAX_TIME_BUDGET_SECONDS)
    assert "auth_key" not in repr(afs.normalize_azure_files_search_config({
        **_manifest(), "auth": {"type": "key", "key": "super-secret-query-key"},
    }))


def test_config_rejections():
    invalid = [
        {**_manifest(), "endpoint": "https://attacker.invalid"},
        _manifest(index_name="Bad Index"),
        {**_manifest(), "auth": {"type": "key"}},
        {**_manifest(), "auth": {"type": "servicePrincipal"}},
        _manifest(index_layout="spreadsheet"),
        _manifest(query_mode="vector_only"),
        _manifest(index_layout="custom", vector_field="", query_mode="hybrid"),
        _manifest(content_field="bad field"),
        _manifest(storage_shares=[]),
        _manifest(storage_shares=[{"storage_account_resource_id": "/subscriptions/x/storageAccounts/y", "share_name": "docs"}]),
        _manifest(storage_shares=[{"storage_account_resource_id": ACCOUNT_ID, "share_name": "Bad_Share"}]),
        _manifest(permission_mode="none"),
    ]
    for manifest in invalid:
        with pytest.raises(afs.AzureFilesSearchConfigError):
            afs.normalize_azure_files_search_config(manifest)
    acknowledged = afs.normalize_azure_files_search_config(
        _manifest(permission_mode="none", permission_mode_none_acknowledged=True, storage_shares=[]),
    )
    assert acknowledged.permission_mode == afs.PERMISSION_MODE_NONE


def test_internal_index_guard():
    settings = {"azure_ai_search_endpoint": "https://contoso-search.search.windows.net/"}
    for index_name in afs.INTERNAL_SEARCH_INDEX_NAMES:
        with pytest.raises(afs.AzureFilesSearchConfigError):
            afs.validate_azure_files_index_action(_manifest(index_name=index_name), settings)
    assert afs.validate_azure_files_index_action(_manifest(), settings).index_name == "finance-files"
    other_service = {"azure_ai_search_endpoint": "https://simplechat-search.search.windows.net"}
    assert afs.validate_azure_files_index_action(_manifest(index_name="simplechat-user-index"), other_service)
    config = afs.normalize_azure_files_search_config(_manifest())
    with pytest.raises(afs.AzureFilesSearchConfigError):
        afs.assert_not_internal_index(config, settings, alias_exists=lambda name: True)
    with pytest.raises(afs.AzureFilesSearchConfigError):
        afs.assert_not_internal_index(config, settings, alias_exists=lambda name: None)
    afs.assert_not_internal_index(config, settings, alias_exists=lambda name: False)


def test_parse_azure_file_path():
    parsed = afs.parse_azure_file_path(_url("Finance%20Team/Q1/budget.txt"))
    assert parsed.account_name == "finfiles" and parsed.share_name == "docs"
    assert parsed.relative_path == "Finance Team/Q1/budget.txt"
    assert parsed.unc_path == "\\\\finfiles.file.core.windows.net\\docs\\Finance Team\\Q1\\budget.txt"
    assert parsed.folder == "Finance Team\\Q1"
    import base64
    encoded = base64.urlsafe_b64encode(_url("a/b.txt").encode()).decode().rstrip("=") + "1"
    assert afs.parse_azure_file_path(encoded).relative_path == "a/b.txt"
    for invalid in (
        "",
        "not a url",
        "https://finfiles.blob.core.windows.net/docs/a.txt",
        "https://finfiles.file.core.windows.net/docs",
        "https://finfiles.file.core.windows.net/docs/../secret.txt",
        "https://finfiles.file.core.windows.net/docs/a.txt?sv=token",
        "http://finfiles.file.core.windows.net/docs/a.txt",
    ):
        assert afs.parse_azure_file_path(invalid) is None, invalid


def test_search_request_shapes():
    keyword = afs.build_search_request(afs.normalize_azure_files_search_config(_manifest()), "budget", None)
    assert keyword["select"] == ["metadata_storage_path", "metadata_storage_name", "metadata_storage_last_modified"]
    assert keyword["highlight_fields"] == "content" and "query_type" not in keyword
    semantic = afs.build_search_request(
        afs.normalize_azure_files_search_config(_manifest(query_mode="semantic", semantic_configuration="default")), "budget", None,
    )
    assert semantic["query_type"] == "semantic" and semantic["query_caption"] == "extractive"
    assert semantic["semantic_configuration_name"] == "default"
    captured = {}
    hybrid = afs.build_search_request(
        afs.normalize_azure_files_search_config(_manifest(index_layout="chunked", query_mode="hybrid")),
        "budget",
        lambda **kwargs: captured.update(kwargs) or "vector-query",
    )
    assert hybrid["vector_queries"] == ["vector-query"] and captured["fields"] == "text_vector"
    assert "chunk" in hybrid["select"] and "highlight_fields" not in hybrid and "query_type" not in hybrid


def test_only_allowed_files_reach_the_model():
    config = afs.normalize_azure_files_search_config(_manifest(select_content=True))
    hits = [
        _hit("allowed/budget.txt", "Budget forecast for Q1"),
        _hit("denied/salaries.txt", "Salary bands"),
        _hit("unknown/merger.txt", "Merger terms"),
        _hit("deny/incident.txt", "Incident review"),
        {**_hit("x.txt", "Other share"), "metadata_storage_path": "https://other.file.core.windows.net/docs/x.txt"},
        {**_hit("y.txt", "No path"), "metadata_storage_path": ""},
        _hit("allowed/budget.txt", "Budget forecast for Q2", score=0.5),
    ]
    outcome = afs.run_azure_files_search(config, "budget", None, _dependencies(hits, membership=_membership()))
    assert [result["file_name"] for result in outcome.results] == ["budget.txt", "budget.txt"]
    assert outcome.results[0]["unc_path"].endswith("\\docs\\allowed\\budget.txt")
    assert (outcome.allowed_files, outcome.denied_files, outcome.unverified_files) == (1, 2, 3)
    assert outcome.reasons == {
        acl.REASON_ACL_NO_ALLOW: 1,
        acl.REASON_SID_UNRESOLVED: 1,
        acl.REASON_ACL_EXPLICIT_DENY: 1,
        afs.REASON_STORAGE_NOT_ALLOWLISTED: 1,
        afs.REASON_PATH_MISSING: 1,
    }
    unresolved = [entry for entry in outcome.withheld_files if entry["reason"] == acl.REASON_SID_UNRESOLVED]
    assert unresolved[0]["unresolved_sids"] == [UNKNOWN_SID]

    model_response = afs.build_model_response(config, outcome)
    serialized = str(model_response)
    for withheld_text in ("salaries", "merger", "incident", "Salary bands", "withheld", "denied", "unverified"):
        assert withheld_text not in serialized, withheld_text
    assert model_response["result_count"] == 2

    review = afs.build_review_record(config, outcome)
    assert review["status"] == "unverified"
    assert review["counts"]["denied_files"] == 2 and review["counts"]["unverified_files"] == 3
    serialized_review = str(review)
    assert "budget" not in serialized_review.lower().replace("budget.txt", "")
    assert "Salary bands" not in serialized_review and "Merger terms" not in serialized_review


def test_identity_unavailable_withholds_everything():
    config = afs.normalize_azure_files_search_config(_manifest())
    outcome = afs.run_azure_files_search(
        config, "budget", None,
        _dependencies([_hit("allowed/budget.txt")], membership=None, identity_reason="identity_unavailable"),
    )
    assert outcome.results == [] and outcome.reasons == {"identity_unavailable": 1}


def test_permission_mode_none_returns_every_match():
    config = afs.normalize_azure_files_search_config(
        _manifest(permission_mode="none", permission_mode_none_acknowledged=True, storage_shares=[]),
    )
    outcome = afs.run_azure_files_search(
        config, "budget", None,
        _dependencies([_hit("denied/salaries.txt"), _hit("unknown/merger.txt")], membership=None),
    )
    assert len(outcome.results) == 2 and outcome.withheld_count == 0


def test_share_level_and_read_failures():
    config = afs.normalize_azure_files_search_config(_manifest())
    hits = [_hit("allowed/budget.txt")]
    denied = afs.run_azure_files_search(
        config, "q", None, _dependencies(hits, membership=_membership(), share=(acl.NOT_MEMBER, "share_access_denied")),
    )
    assert denied.results == [] and denied.reasons == {"share_access_denied": 1} and denied.denied_files == 1
    unknown = afs.run_azure_files_search(
        config, "q", None, _dependencies(hits, membership=_membership(), share=(acl.UNKNOWN, "share_access_unknown")),
    )
    assert unknown.unverified_files == 1
    skipped = afs.run_azure_files_search(
        dataclasses.replace(config, share_access_check=afs.SHARE_ACCESS_CHECK_SKIP), "q", None,
        _dependencies(hits, membership=_membership(), share=(acl.NOT_MEMBER, "share_access_denied")),
    )
    assert len(skipped.results) == 1

    def missing(path):
        raise afs.AzureFileNotFound("gone")

    def failing(path):
        raise RuntimeError("403")

    assert afs.run_azure_files_search(config, "q", None, _dependencies(hits, membership=_membership(), reader=missing)).reasons == {
        afs.REASON_FILE_NOT_FOUND: 1,
    }
    assert afs.run_azure_files_search(config, "q", None, _dependencies(hits, membership=_membership(), reader=failing)).reasons == {
        afs.REASON_ACL_READ_FAILED: 1,
    }


def test_time_budget_withholds_files_not_checked_in_time():
    config = dataclasses.replace(afs.normalize_azure_files_search_config(_manifest()), time_budget_seconds=0)
    release = threading.Event()

    def blocked(path):
        release.wait(5)
        return SDDL_BY_PATH["allowed/budget.txt"]

    try:
        outcome = afs.run_azure_files_search(
            config, "q", None, _dependencies([_hit("allowed/budget.txt")], membership=_membership(), reader=blocked),
        )
    finally:
        release.set()
    assert outcome.results == [] and outcome.reasons == {afs.REASON_TIME_BUDGET_EXCEEDED: 1}


def test_result_limits_and_snippets():
    config = afs.normalize_azure_files_search_config(_manifest(select_content=True, max_snippet_chars=200))
    hits = [_hit("allowed/budget.txt", f"Chunk {index} " + "word " * 100) for index in range(5)]
    outcome = afs.run_azure_files_search(config, "q", 10, _dependencies(hits, membership=_membership()))
    assert len(outcome.results) == afs.MAX_RESULTS_PER_FILE
    assert all(len(result["snippet"]) <= 200 for result in outcome.results)
    limited = afs.run_azure_files_search(config, "q", 1, _dependencies(hits, membership=_membership()))
    assert len(limited.results) == 1

    whole_file = afs.normalize_azure_files_search_config(_manifest())
    assert afs.build_snippet({"@search.captions": [{"text": "Caption text"}]}, whole_file) == "Caption text"
    assert afs.build_snippet({"@search.highlights": {"content": ["first", "second"]}}, whole_file) == "first \u2026 second"
    assert afs.build_snippet({"content": "should not be used"}, whole_file) == ""
    empty = afs.run_azure_files_search(whole_file, "   ", None, _dependencies([], membership=_membership()))
    assert empty.error and empty.results == []


class _Response:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


def _fake_http(routes):
    calls = []

    def http_get(url, headers=None, timeout=None):
        calls.append(url)
        for prefix, response in routes:
            if url.startswith(prefix):
                return response(url) if callable(response) else response
        return _Response(404)

    return http_get, calls


def test_entra_sid_conversion():
    assert access.entra_object_id_to_sid(USER_ID) == USER_SID
    assert access.entra_sid_to_object_id(USER_SID) == USER_ID
    assert access.entra_sid_to_object_id(UNKNOWN_SID) == ""


def test_user_principals_from_graph():
    access.clear_azure_files_access_caches()
    group_id = "0b1f6c2e-1111-2222-3333-444455556666"
    http_get, _calls = _fake_http([
        ("https://graph/me?", _Response(200, {"id": USER_ID, "securityIdentifier": USER_SID, "onPremisesSecurityIdentifier": "S-1-5-21-9-9-9-1201"})),
        ("https://graph/me/transitiveMemberOf", _Response(200, {"value": [{"id": group_id, "securityIdentifier": None}]})),
    ])
    principals = access.get_user_principals(USER_ID, "token", "https://graph", http_get=http_get)
    assert USER_SID in principals.sids and "S-1-5-21-9-9-9-1201" in principals.sids
    assert access.entra_object_id_to_sid(group_id) in principals.sids

    access.clear_azure_files_access_caches()
    mismatch, _ = _fake_http([("https://graph/me?", _Response(200, {"id": "someone-else"}))])
    with pytest.raises(access.AzureFilesIdentityError):
        access.get_user_principals(USER_ID, "token", "https://graph", http_get=mismatch)

    access.clear_azure_files_access_caches()
    endless, _ = _fake_http([
        ("https://graph/me?", _Response(200, {"id": USER_ID})),
        ("https://graph/", lambda url: _Response(200, {"value": [], "@odata.nextLink": "https://graph/next"})),
    ])
    with pytest.raises(access.AzureFilesIdentityError):
        access.get_user_principals(USER_ID, "token", "https://graph", http_get=endless)


def test_foreign_sid_classification():
    access.clear_azure_files_access_caches()
    other_group_id = access.entra_sid_to_object_id(OTHER_GROUP_SID)
    http_get, calls = _fake_http([(f"https://graph/groups/{other_group_id}", _Response(200, {"id": other_group_id}))])
    assert access.classify_foreign_sid(OTHER_GROUP_SID, "token", "https://graph", http_get=http_get) == acl.NOT_MEMBER
    assert access.classify_foreign_sid(OTHER_GROUP_SID, "token", "https://graph", http_get=http_get) == acl.NOT_MEMBER
    assert len(calls) == 1

    onprem, _ = _fake_http([("https://graph/users?$filter=onPremisesSecurityIdentifier", _Response(200, {"value": [{"id": "x"}]}))])
    assert access.classify_foreign_sid("S-1-5-21-1-2-3-4000", "token", "https://graph", http_get=onprem) == acl.NOT_MEMBER

    access.clear_azure_files_access_caches()
    failing_calls = []

    def flaky(url, headers=None, timeout=None):
        failing_calls.append(url)
        return _Response(503)

    assert access.classify_foreign_sid(UNKNOWN_SID, "token", "https://graph", http_get=flaky) == acl.UNKNOWN
    assert access.classify_foreign_sid(UNKNOWN_SID, "token", "https://graph", http_get=flaky) == acl.UNKNOWN
    assert len(failing_calls) == 6, "a transient Graph failure must not be cached as unknown"


def test_share_level_access():
    account = access.parse_storage_account_resource_id(ACCOUNT_ID)
    reader_role = "/providers/Microsoft.Authorization/roleDefinitions/aba4ae5f-2193-4029-9191-0cb91df5e314"
    reader_definition = {"properties": {"permissions": [{"dataActions": [
        "Microsoft.Storage/storageAccounts/fileServices/fileshares/files/read",
    ]}]}}

    def run(routes):
        access.clear_azure_files_access_caches()
        http_get, _ = _fake_http(routes)
        return access.check_share_level_access(USER_ID, account, "docs", "https://arm", lambda: "token", http_get=http_get)

    account_route = f"https://arm{ACCOUNT_ID}?"
    assignments_route = f"https://arm{ACCOUNT_ID}/fileServices/default/fileshares/docs/providers/Microsoft.Authorization/roleAssignments"
    default_reader = {"properties": {"azureFilesIdentityBasedAuthentication": {"defaultSharePermission": "StorageFileDataSmbShareReader"}}}
    assert run([(account_route, _Response(200, default_reader))]) == (acl.MEMBER, "share_default_permission")
    assert run([
        (account_route, _Response(200, {})),
        (assignments_route, _Response(200, {"value": [{"properties": {"roleDefinitionId": reader_role}}]})),
        (f"https://arm{reader_role}", _Response(200, reader_definition)),
    ]) == (acl.MEMBER, "share_role_assignment")
    assert run([(account_route, _Response(200, {})), (assignments_route, _Response(200, {"value": []}))]) == (
        acl.NOT_MEMBER, "share_access_denied",
    )
    assert run([
        (account_route, _Response(200, {})),
        (assignments_route, _Response(200, {"value": [{"properties": {"roleDefinitionId": reader_role, "condition": "@x"}}]})),
        (f"https://arm{reader_role}", _Response(200, reader_definition)),
    ]) == (acl.UNKNOWN, "share_access_unknown")
    assert run([(account_route, _Response(403))]) == (acl.UNKNOWN, "share_access_unknown")


def test_role_definition_wildcards():
    grants = access.role_definition_grants_file_read
    assert grants({"properties": {"permissions": [{"dataActions": ["Microsoft.Storage/storageAccounts/fileServices/*"]}]}})
    assert not grants({"properties": {"permissions": [{
        "dataActions": ["Microsoft.Storage/storageAccounts/fileServices/*"],
        "notDataActions": ["Microsoft.Storage/storageAccounts/fileServices/fileshares/files/read"],
    }]}})
    assert not grants({"properties": {"permissions": [{"dataActions": ["Microsoft.Storage/storageAccounts/blobServices/*"]}]}})


def test_storage_resource_id_validation():
    reference = access.parse_storage_account_resource_id(ACCOUNT_ID.upper().replace("STORAGEACCOUNTS/FINFILES", "storageAccounts/FinFiles"))
    assert reference.account_name == "finfiles"
    for invalid in ("", "finfiles", f"{ACCOUNT_ID}/fileServices/default", ACCOUNT_ID.replace("Microsoft.Storage", "Microsoft.Search")):
        with pytest.raises(ValueError):
            access.parse_storage_account_resource_id(invalid)


def test_global_only_action_type():
    assert is_global_only_action_type("azure_files_index")
    assert not is_global_only_action_type("document_search")
    # The plugin loaders match normalized type substrings, so aliases must be refused too.
    for alias in (
        "AzureFilesIndex", "azure-files-index", " azure_files_index ", "AzureFilesIndexPlugin",
        "azure_files_index_plugin", "files_index", "files", "plugin",
    ):
        assert is_global_only_action_type(alias), alias
    for other in ("search", "document_search", "blob_storage", "mcp", "openapi", "sql_query", "", None):
        assert not is_global_only_action_type(other), other
    action = {"name": "files", "type": "azure_files_index"}
    for scope_type, scope_id in (("personal", "user-1"), ("group", "group-1")):
        with pytest.raises(GlobalOnlyActionTypeError):
            prepare_scoped_action(action, scope_type, scope_id)
        with pytest.raises(GlobalOnlyActionTypeError):
            prepare_scoped_action({**action, "type": "AzureFilesIndex"}, scope_type, scope_id)
    assert prepare_scoped_action(action, "global", "global")["type"] == "azure_files_index"


def test_global_only_check_never_flags_a_discoverable_action_type():
    plugin_root = Path(__file__).resolve().parents[1] / "application" / "single_app" / "semantic_kernel_plugins"
    discovered = {
        path.stem.removesuffix("_plugin") for path in plugin_root.glob("*_plugin.py") if path.stem != "base_plugin"
    }
    assert {kind for kind in discovered if is_global_only_action_type(kind)} == {"azure_files_index"}


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))

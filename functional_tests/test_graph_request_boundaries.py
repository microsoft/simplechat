# test_graph_request_boundaries.py
"""
Functional tests for the selected Graph request-boundary remediation.
Version: 0.261.456
Implemented in: 0.261.456

These tests prepare real Requests URLs and exercise its redirect handling through
an in-memory transport. They cover identifiers, OneDrive metadata pagination,
profile relationships, workspace membership, and content-download redirects for
CodeQL alerts 1090, 1091, 1093, and 1094, without Graph or Azure network access.
"""

import json
import logging
import sys
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Iterable
from unittest.mock import Mock
from urllib.parse import parse_qs, quote, urlparse

import pytest
import requests

from test_file_sync_azure_blob_storage import load_functions
from test_file_sync_ssrf_validation import onedrive_functions
from test_public_workspace_membership_writer_safety import (
    WS_ID,
    _as_actor,
    _environment,
    _exec_nested_handlers,
    _set_body,
    _workspace,
)
from test_support.group_directory_harness import group_directory_environment
from test_user_profile_idor_authorization import prepare_context


GRAPH_BASES = (
    "https://graph.microsoft.com/v1.0",
    "https://graph.microsoft.us/v1.0",
    "https://graph.custom.example:8443/proxy/v1.0",
)
LOOKUPS = {
    "group": (
        "functions_simplechat_operations.py",
        "_get_directory_user_by_id",
        {"_normalize_directory_user"},
    ),
    "public": ("route_backend_public_workspaces.py", "get_user_details_from_graph", set()),
    "profile": ("route_backend_users.py", "_get_graph_user_info_by_id", {"_build_user_info_response"}),
}
GRAPH_USER = {
    "id": "resolved-object-id",
    "displayName": "Directory User",
    "mail": "directory@example.test",
    "userPrincipalName": "directory@tenant.example.test",
}


class GraphAdapter(requests.adapters.BaseAdapter):
    """Record real prepared requests and return queued responses without sockets."""

    def __init__(self, replies):
        super().__init__()
        self.replies = list(replies)
        self.prepared = []
        self.options = []

    def send(self, request, **kwargs):
        self.prepared.append(request)
        self.options.append(kwargs)
        if not self.replies:
            raise AssertionError("Unexpected additional Graph request")
        status, payload, headers = self.replies.pop(0)
        response = requests.Response()
        response.status_code = status
        response.url = request.url
        response.request = request
        response.headers.update(headers)
        response._content = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
        response._content_consumed = True
        return response

    def close(self):
        pass


@contextmanager
def graph_transport(replies):
    adapter = GraphAdapter(replies)
    with requests.Session() as session:
        session.trust_env = False
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        yield SimpleNamespace(
            requests=SimpleNamespace(get=session.get, exceptions=requests.exceptions),
            adapter=adapter,
        )


def graph_endpoint(graph_base):
    functions = load_functions(
        "functions_authentication.py",
        {"get_graph_endpoint"},
        {"get_graph_base_url": lambda: graph_base},
    )
    return functions["get_graph_endpoint"]


def directory_lookup(kind, graph_base, transport):
    filename, name, dependencies = LOOKUPS[kind]
    functions = load_functions(
        filename,
        {name, *dependencies},
        {
            "get_graph_endpoint": graph_endpoint(graph_base),
            "get_valid_access_token": Mock(return_value="test-graph-token"),
            "requests": transport.requests,
            "logging": logging,
            "log_event": Mock(),
        },
    )
    return functions, functions[name]


def file_sync_graph(graph_base, transport):
    functions, _ = onedrive_functions(graph_base)
    functions["requests"] = transport.requests
    functions["_onedrive_headers"] = Mock(return_value={"Authorization": "Bearer test-graph-token"})
    return functions


@pytest.mark.parametrize("environment, custom_url, graph_base", (
    ("public", "", GRAPH_BASES[0]),
    ("usgovernment", "", GRAPH_BASES[1]),
    ("public", "https://graph.custom.example:8443/proxy", GRAPH_BASES[2]),
    ("usgovernment", f"{GRAPH_BASES[2]}/users/", GRAPH_BASES[2]),
))
def test_graph_base_resolution_preserves_cloud_and_legacy_custom_configuration(environment, custom_url, graph_base):
    functions = load_functions(
        "functions_authentication.py",
        {"get_graph_base_url", "get_graph_endpoint"},
        {"AZURE_ENVIRONMENT": environment, "CUSTOM_GRAPH_URL_VALUE": custom_url},
    )
    resolved_base = functions["get_graph_base_url"]()
    endpoint = functions["get_graph_endpoint"]("/me/photo/$value")

    assert resolved_base == graph_base
    assert endpoint == f"{graph_base}/me/photo/$value"


@pytest.mark.parametrize("path", (
    "/users?$filter=displayName%20eq%20%27Alice%27&$select=id,displayName",
    "/users/actor-user/drive/root:/literal%23%25name:/children?$skiptoken=abc%252F%23%2B%3D",
))
def test_graph_uri_structure_keeps_encoded_data_and_odata_queries(path):
    endpoint = graph_endpoint(GRAPH_BASES[0])(path)
    prepared = requests.Request("GET", endpoint).prepare()

    assert prepared.url == f"{GRAPH_BASES[0]}{path}"
    assert not urlparse(prepared.url).fragment


def test_custom_graph_origin_uses_the_same_idna_host_as_requests():
    configured_host = "gr\u00e1ph.example"
    prepared_host = configured_host.encode("idna").decode("ascii")
    next_link = f"https://{prepared_host}/v1.0/drives/drive-id/items/folder-id/children?$skiptoken=next"
    endpoint = graph_endpoint(f"https://{configured_host}/v1.0")(next_link, allow_absolute=True)
    prepared = requests.Request("GET", endpoint).prepare()

    assert prepared.url == next_link


def test_directory_odata_filters_stay_in_query_parameters():
    with graph_transport([(200, {"value": [GRAPH_USER]}, {})]) as transport:
        functions = load_functions(
            "functions_simplechat_operations.py",
            {"_find_directory_users_by_email", "_graph_get_json", "_escape_odata_value",
             "_normalize_directory_users", "_normalize_directory_user"},
            {
                "Iterable": Iterable,
                "get_graph_endpoint": graph_endpoint(GRAPH_BASES[2]),
                "get_valid_access_token": lambda: "test-graph-token",
                "requests": transport.requests,
            },
        )
        result = functions["_find_directory_users_by_email"]("o'connor_example.test#EXT#@tenant.example.test")

    [prepared] = transport.adapter.prepared
    query = parse_qs(urlparse(prepared.url).query)
    assert prepared.url.split("?")[0] == f"{GRAPH_BASES[2]}/users"
    assert query["$filter"] == [
        "mail eq 'o''connor_example.test#EXT#@tenant.example.test' or "
        "userPrincipalName eq 'o''connor_example.test#EXT#@tenant.example.test'"
    ]
    assert result[0]["id"] == GRAPH_USER["id"]


@pytest.mark.parametrize("kind", LOOKUPS)
@pytest.mark.parametrize("graph_base", GRAPH_BASES)
@pytest.mark.parametrize("user_id", (
    "c31f66ca-f292-42a5-9739-f1ed96ec94e9",
    "alice@tenant.example.test",
    "alice_example.test#EXT#@tenant.example.test",
    "alice.o'connor@tenant.example.test",
    "alice+sync@tenant.example.test",
    "directory?query=value#fragment",
    "user/drive",
    "user\\drive",
    "%2e%2e",
    "jos\u00e9@tenant.example.test",
))
def test_directory_identifiers_remain_one_encoded_component(kind, graph_base, user_id):
    with graph_transport([(200, GRAPH_USER, {})]) as transport:
        _, lookup = directory_lookup(kind, graph_base, transport)
        result = lookup(f" {user_id} ")

    [prepared] = transport.adapter.prepared
    assert prepared.url.split("?")[0] == f"{graph_base}/users/{quote(user_id, safe='')}"
    assert not urlparse(prepared.url).fragment
    assert prepared.headers["Authorization"] == "Bearer test-graph-token"
    assert result["displayName"] == GRAPH_USER["displayName"]


@pytest.mark.parametrize("kind", LOOKUPS)
@pytest.mark.parametrize("user_id", (
    ".", "..", "../me", "user/../drive", "user\\..\\drive", "user\rname",
    "user\nname", "user\tname", "user\x00name", "user\x7fname",
))
def test_invalid_directory_components_are_refused_before_http(kind, user_id):
    with graph_transport([(200, GRAPH_USER, {})]) as transport:
        functions, lookup = directory_lookup(kind, GRAPH_BASES[0], transport)
        if kind == "group":
            with pytest.raises(ValueError):
                lookup(user_id)
        else:
            result = lookup(user_id)
            assert result == (None if kind == "profile" else {"displayName": "", "email": ""})
            functions["log_event"].assert_called_once()

    assert transport.adapter.prepared == []


@pytest.mark.parametrize("kind", LOOKUPS)
@pytest.mark.parametrize("status", (301, 302, 303, 307, 308))
def test_directory_metadata_does_not_follow_redirects(kind, status):
    replies = [
        (status, GRAPH_USER, {"Location": "https://attacker.example/user"}),
        (200, GRAPH_USER, {}),
    ]
    with graph_transport(replies) as transport:
        functions, lookup = directory_lookup(kind, GRAPH_BASES[0], transport)
        if kind == "public":
            result = lookup("target-user")
            assert result == {"displayName": "", "email": ""}
            functions["log_event"].assert_called_once()
        else:
            with pytest.raises(requests.exceptions.HTTPError):
                lookup("target-user")

    assert len(transport.adapter.prepared) == 1
    assert transport.adapter.prepared[0].url.startswith(f"{GRAPH_BASES[0]}/users/target-user?")


@pytest.mark.parametrize("kind", LOOKUPS)
def test_missing_token_preserves_the_lookup_failure_contract(kind):
    with graph_transport([]) as transport:
        functions, lookup = directory_lookup(kind, GRAPH_BASES[0], transport)
        functions["get_valid_access_token"].return_value = None
        if kind == "group":
            with pytest.raises(PermissionError, match="access token"):
                lookup("target-user")
        else:
            result = lookup("target-user")
            assert result == (None if kind == "profile" else {"displayName": "", "email": ""})

    assert transport.adapter.prepared == []


@pytest.mark.parametrize("graph_base", GRAPH_BASES + (
    "http://127.0.0.1:8080/graph/v1.0",
    "https://[::1]:8443/graph/v1.0",
))
def test_pagination_retains_the_configured_origin_and_opaque_query(graph_base):
    next_link = f"{graph_base}/drives/drive-id/items/folder-id/children?$skiptoken=abc%2Fdef%2B%3D"
    replies = [
        (200, {"value": [{"id": "first"}], "@odata.nextLink": next_link}, {}),
        (200, {"value": [{"id": "second"}]}, {}),
    ]
    with graph_transport(replies) as transport:
        functions = file_sync_graph(graph_base, transport)
        result = functions["_iter_onedrive_children"]({
            "scope_type": "personal", "user_id": "alice_example.test#EXT#@tenant.example.test",
        })

    assert result == [{"id": "first"}, {"id": "second"}]
    first, second = transport.adapter.prepared
    assert first.url.split("?")[0] == (
        f"{graph_base}/users/alice_example.test%23EXT%23%40tenant.example.test/drive/root/children"
    )
    assert second.url == next_link
    assert "$top" not in urlparse(second.url).query
    assert second.headers["Authorization"] == "Bearer test-graph-token"


@pytest.mark.parametrize("next_link", (
    "https://attacker.example/v1.0/users/user/drive/root/children",
    "http://graph.microsoft.com/v1.0/users/user/drive/root/children",
    "https://graph.microsoft.us/v1.0/users/user/drive/root/children",
    "https://graph.microsoft.com.evil.example/v1.0/users",
    "https://graph.microsoft.com./v1.0/users",
    "https://graph.microsoft.com:8443/v1.0/users",
    "https://graph.microsoft.com:0/v1.0/users",
    "https://graph.microsoft.com:invalid/v1.0/users",
    "https://graph.microsoft.com:99999/v1.0/users",
    "https://name:password@graph.microsoft.com/v1.0/users",
    "//attacker.example/v1.0/users",
    "https://graph.microsoft.com/beta/users",
    "https://graph.microsoft.com/v1.0.evil/users",
    "https://graph.microsoft.com/v1.0/../beta/users",
    "https://graph.microsoft.com/v1.0/%2e%2E/beta/users",
    "https://graph.microsoft.com/v1.0/users/user%2F..%2Fdrive/children",
    "https://graph.microsoft.com/v1.0/users/user%5C..%5Cdrive/children",
    "https://graph.microsoft.com/v1.0/users/user%00/children",
    "https://graph.microsoft.com/v1.0/users#fragment",
    "https://graph.microsoft.com/v1.0/users\r\n",
    "https://graph.microsoft.com/v1.0/users/%invalid",
    "https://[invalid/v1.0/users",
    {"url": "https://attacker.example"},
))
def test_pagination_refuses_invalid_destinations_before_the_next_http_call(next_link):
    replies = [
        (200, {"value": [], "@odata.nextLink": next_link}, {}),
        (200, {"value": []}, {}),
    ]
    with graph_transport(replies) as transport:
        functions = file_sync_graph(GRAPH_BASES[0], transport)
        with pytest.raises(ValueError):
            functions["_iter_onedrive_children"]({"scope_type": "personal", "user_id": "actor-user"})

    assert len(transport.adapter.prepared) == 1
    assert functions["_onedrive_headers"].call_count == 1


@pytest.mark.parametrize("next_link", (
    "https://GRAPH.MICROSOFT.COM:443/v1.0/users/actor-user/drive/root/children?$skiptoken=next",
    "/users/actor-user/drive/root/children?$skiptoken=next",
))
def test_pagination_handles_equivalent_origins_and_relative_continuations(next_link):
    replies = [
        (200, {"value": [], "@odata.nextLink": next_link}, {}),
        (200, {"value": [{"id": "second"}]}, {}),
    ]
    with graph_transport(replies) as transport:
        functions = file_sync_graph(GRAPH_BASES[0], transport)
        result = functions["_iter_onedrive_children"]({"scope_type": "personal", "user_id": "actor-user"})

    assert result == [{"id": "second"}]
    assert transport.adapter.prepared[1].url == (
        f"{GRAPH_BASES[0]}/users/actor-user/drive/root/children?$skiptoken=next"
    )


@pytest.mark.parametrize("status", (301, 302, 303, 307, 308))
def test_onedrive_metadata_redirects_are_failures_not_partial_success(status):
    replies = [
        (status, {"value": [{"id": "redirect-body"}]}, {"Location": "https://attacker.example/metadata"}),
        (200, {"value": [{"id": "attacker-body"}]}, {}),
    ]
    with graph_transport(replies) as transport:
        functions = file_sync_graph(GRAPH_BASES[0], transport)
        with pytest.raises(ValueError, match="redirect"):
            functions["_graph_get_json"]("/users/actor-user/drive/root/children")

    assert len(transport.adapter.prepared) == 1


@pytest.mark.parametrize("status, error_type", ((400, ValueError), (401, PermissionError), (403, PermissionError), (500, ValueError)))
def test_onedrive_metadata_keeps_existing_graph_error_handling(status, error_type):
    with graph_transport([(status, {"error": {"message": "Test Graph failure"}}, {})]) as transport:
        functions = file_sync_graph(GRAPH_BASES[0], transport)
        with pytest.raises(error_type, match=str(status)):
            functions["_graph_get_json"]("/users/actor-user/drive/root/children")

    assert len(transport.adapter.prepared) == 1


def test_group_membership_authorization_still_precedes_the_real_directory_request(monkeypatch):
    with group_directory_environment() as env, graph_transport([(200, GRAPH_USER, {})]) as transport:
        _, lookup = directory_lookup("group", GRAPH_BASES[0], transport)
        monkeypatch.setattr(env.modules.membership, "_get_directory_user_by_id", lookup)
        env.seed_group("graph-group")
        env.as_user("member-1")
        refused = env.add_member("graph-group", {"userId": "newcomer-1", "role": "User"})
        assert refused.status_code == 403
        assert transport.adapter.prepared == []
        env.as_user("owner-1")
        added = env.add_member("graph-group", {"userId": "newcomer-1", "role": "User"})
        payload = added.get_json()

    assert added.status_code == 201
    assert payload["member"]["userId"] == GRAPH_USER["id"]
    assert len(transport.adapter.prepared) == 1


def test_public_workspace_membership_still_precedes_the_real_directory_request():
    env = _environment()
    env.container.seed(_workspace(documentManagers=["target-user"]))
    _set_body(env, {"role": "Admin"})
    with graph_transport([(200, GRAPH_USER, {})]) as transport:
        _, lookup = directory_lookup("public", GRAPH_BASES[0], transport)
        env.namespace["get_user_details_from_graph"] = lookup
        _as_actor(env, "outsider")
        _, refused_status = env.handlers["api_update_public_member_role"](WS_ID, "target-user")
        assert refused_status == 403
        assert transport.adapter.prepared == []
        _as_actor(env, "owner")
        _, allowed_status = env.handlers["api_update_public_member_role"](WS_ID, "target-user")

    assert allowed_status == 200
    assert len(transport.adapter.prepared) == 1


def test_profile_relationship_still_precedes_graph_fallback():
    context, module = prepare_context()
    context.user_settings_container.documents.clear()
    with graph_transport([(200, GRAPH_USER, {})]) as transport:
        functions, _ = directory_lookup("profile", GRAPH_BASES[0], transport)
        for name in ("get_graph_endpoint", "get_valid_access_token", "requests"):
            module.__dict__[name] = functions[name]
        handler = _exec_nested_handlers(
            "route_backend_users.py", "register_route_backend_users", {"api_get_user_info"}, module.__dict__,
        )["api_get_user_info"]
        _, refused_status = handler("target-user")
        assert refused_status == 404
        assert context.user_settings_container.read_calls == []
        assert transport.adapter.prepared == []
        context.groups = [{"roles": {"target-user": "User"}}]
        result, allowed_status = handler("target-user")

    assert allowed_status == 200
    assert result["id"] == GRAPH_USER["id"]
    assert len(transport.adapter.prepared) == 1


@pytest.mark.parametrize("status", (302, 307))
def test_onedrive_content_download_redirects_are_preserved(status, tmp_path):
    content = b"downloaded file contents"
    replies = [
        (status, b"", {"Location": "https://tenant.sharepoint.example/download/file"}),
        (200, content, {}),
    ]
    download_file = tmp_path / "downloaded.txt"
    with graph_transport(replies) as transport:
        functions = file_sync_graph(GRAPH_BASES[0], transport)
        functions.update(load_functions(
            "functions_file_sync.py",
            {"_stage_onedrive_file"},
            {
                "get_graph_endpoint": graph_endpoint(GRAPH_BASES[0]),
                "_onedrive_user_path": functions["_onedrive_user_path"],
                "_get_graph_app_token": lambda: "test-graph-token",
                "requests": transport.requests,
                "tempfile": SimpleNamespace(NamedTemporaryFile=lambda **kwargs: download_file.open("wb")),
            },
        ))
        path, digest = functions["_stage_onedrive_file"](
            {"scope_type": "personal", "user_id": "actor-user"},
            {"onedrive_item_id": "file-id", "file_name": "file.txt"},
        )
        downloaded = download_file.read_bytes()
        expected_digest = functions["hashlib"].sha256(content).hexdigest()

    assert path == str(download_file)
    assert downloaded == content
    assert digest == expected_digest
    assert len(transport.adapter.prepared) == 2
    assert transport.adapter.prepared[0].url == f"{GRAPH_BASES[0]}/users/actor-user/drive/items/file-id/content"
    assert "Authorization" not in transport.adapter.prepared[1].headers


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))

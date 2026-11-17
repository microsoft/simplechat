# test_bitbucket_action_plugin.py
"""
Functional tests for read-only Bitbucket repository review.
Version: 0.261.450
Implemented in: 0.261.450

Validates provider wire contracts, branch/allowlist enforcement, immutable
source attribution, bounded output, comparison direction, and bootstrap safety.
"""

import copy
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "application" / "single_app"
sys.path.insert(0, str(APP))

from functions_bitbucket_operations import BitbucketClient, BitbucketError, bounded_response, normalize_bitbucket_manifest, policy_fingerprint


BASE = "a" * 40
TARGET = "b" * 40
MERGE = "c" * 40


def manifest(cloud=False, method="bearer_token"):
    return {
        "id": "review", "name": "review", "type": "bitbucket",
        "endpoint": "https://api.bitbucket.org" if cloud else "https://bitbucket.example.test/context",
        "auth": {"type": "key", "identity": "", "key": "private-token"},
        "additionalFields": {
            "edition": "cloud" if cloud else "data_center", "auth_method": method,
            "repositories": [{"id": "{repo-uuid}" if cloud else "1", "project": "team", "slug": "repo",
                              "name": "Repository", "branch_mode": "any", "default_branch": "main"}],
        },
    }


class Response:
    def __init__(self, value, status=200):
        self.content = value if isinstance(value, bytes) else json.dumps(value).encode()
        self.status_code = status
        self.closed = False

    def iter_content(self, chunk_size):
        for offset in range(0, len(self.content), chunk_size):
            yield self.content[offset:offset + chunk_size]

    def close(self):
        self.closed = True


class Transport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        value = self.responses.pop(0)
        return value if isinstance(value, Response) else Response(value)


def client(responses, cloud=False):
    transport = Transport(responses)
    instance = BitbucketClient(manifest(cloud), {"method": "bearer_token", "secret": "private-token"},
                               session_factory=lambda: transport)
    return instance, transport


def test_allowlist_fixed_branches_and_input_rejections_before_source_reads():
    instance, transport = client([{"id": 1}, {
        "values": [{"id": "refs/heads/main", "latestCommit": BASE}], "isLastPage": True,
    }])
    with pytest.raises(BitbucketError, match="permitted repository"):
        instance.read_file("unlisted", path="secret.py")
    assert not transport.calls
    instance.fields["repositories"][0].update(branch_mode="fixed")
    with pytest.raises(BitbucketError) as error:
        instance.compare("", "main", "feature")
    assert error.value.code == "branch_denied"
    assert not any("/raw/" in url for url, _ in transport.calls)
    for branch in ("main~1", "main..other", "refs/tags/main", "main\n", "../other"):
        candidate = manifest()
        candidate["additionalFields"]["repositories"][0]["default_branch"] = branch
        with pytest.raises(BitbucketError):
            normalize_bitbucket_manifest(candidate)


@pytest.mark.parametrize("cloud", [False, True])
def test_read_file_pins_commit_and_bounds_lines(cloud):
    repo = {"uuid": "{repo-uuid}"} if cloud else {"id": 1}
    branch = {"target": {"hash": TARGET}} if cloud else {
        "values": [{"id": "refs/heads/main", "latestCommit": TARGET}], "isLastPage": True,
    }
    instance, transport = client([repo, branch, b"one\ntwo\nthree\n"], cloud)
    result = instance.read_file("", "", "src/review.py", 2, 1)
    assert result["content"] == "two"
    assert result["commit"] == TARGET
    assert result["start_line"] == result["end_line"] == 2
    assert result["truncated"] and result["next_line"] == 3
    source_url, options = transport.calls[-1]
    assert TARGET in source_url if cloud else options["params"]["at"] == TARGET
    assert all(call["allow_redirects"] is False and call["stream"] for _, call in transport.calls)
    assert all(call["headers"]["Authorization"] == "Bearer private-token" for _, call in transport.calls)


def test_data_center_exact_branch_lookup_continues_pages_and_never_falls_back():
    instance, transport = client([
        {"values": [{"id": "refs/heads/main-long", "latestCommit": TARGET}], "isLastPage": False, "nextPageStart": 1},
        {"values": [{"id": "refs/heads/main", "latestCommit": BASE}], "isLastPage": True},
    ])
    name, commit = instance.resolve(instance.fields["repositories"][0])
    assert (name, commit) == ("main", BASE)
    assert transport.calls[-1][1]["params"]["start"] == 1
    instance, transport = client([{"values": [], "isLastPage": True}])
    with pytest.raises(BitbucketError) as error:
        instance.resolve(instance.fields["repositories"][0])
    assert error.value.code == "branch_not_found"
    assert len(transport.calls) == 1


@pytest.mark.parametrize("cloud", [False, True])
def test_comparison_merge_base_direction_add_delete_and_rename(cloud):
    repo = {"uuid": "{repo-uuid}"} if cloud else {"id": 1}
    branches = ([{"target": {"hash": value}} for value in (BASE, TARGET)] if cloud else [
        {"values": [{"id": f"refs/heads/{name}", "latestCommit": value}], "isLastPage": True}
        for name, value in (("main", BASE), ("feature", TARGET))
    ])
    changes = [
        {"old": None, "new": {"path": "added.py"}},
        {"old": {"path": "deleted.py"}, "new": None},
        {"old": {"path": "old.py"}, "new": {"path": "renamed.py"}},
    ] if cloud else [
        {"type": "ADD", "path": {"toString": "added.py"}},
        {"type": "DELETE", "path": {"toString": "deleted.py"}},
        {"type": "MOVE", "srcPath": {"toString": "old.py"}, "path": {"toString": "renamed.py"}},
    ]
    page = {"values": changes, **({} if cloud else {"isLastPage": True})}
    instance, transport = client([repo, *branches, {"hash" if cloud else "id": MERGE},
                                  page, b"added\n", b"deleted\n", b"old\n", b"new\n"], cloud)
    result = instance.compare("", "main", "feature")
    assert result["comparison_mode"] == "merge_base_to_target"
    assert result["merge_base"] == MERGE and not result["truncated"]
    assert "+added" in result["files"][0]["patch"]
    assert "-deleted" in result["files"][1]["patch"]
    assert "-old" in result["files"][2]["patch"] and "+new" in result["files"][2]["patch"]
    url, options = transport.calls[4]
    if cloud:
        assert url.endswith(f"/diffstat/{TARGET}..{MERGE}")
        assert options["params"]["topic"] == "false"
    else:
        assert options["params"]["since"] == MERGE and options["params"]["until"] == TARGET


@pytest.mark.parametrize("response,code", [
    (Response(b"binary\x00"), "binary_file"), (Response(b"\xff"), "response_invalid"),
    (Response([]), "response_invalid"), (Response({"error": "secret"}, 302), "provider_failed"),
    (Response(b"x" * 21), "result_too_large"),
])
def test_bounded_provider_failures_are_safe_and_responses_closed(response, code):
    with pytest.raises(BitbucketError) as error:
        bounded_response(response, as_json=code not in {"binary_file", "result_too_large"}, limit=20)
    assert error.value.code == code
    assert "secret" not in str(error.value)
    assert response.closed


def test_cloud_basic_token_auth_and_no_credentials_or_missing_repo_fails_closed():
    transport = Transport([{"values": [], "next": "https://api.bitbucket.org/2.0/repositories/team?page=opaque-token&pagelen=50"}])
    instance = BitbucketClient(manifest(True, "username_password"), {
        "method": "username_password", "username": "email@example.test", "secret": "api-token",
    }, session_factory=lambda: transport)
    result = instance.discover("team")
    assert result["next_cursor"] == "opaque-token"
    assert len(transport.calls) == 1
    assert transport.calls[0][1]["auth"] == ("email@example.test", "api-token")
    assert "Authorization" not in transport.calls[0][1]["headers"]
    instance.auth = {}
    with pytest.raises(BitbucketError) as error:
        instance.get("/test")
    assert error.value.code == "credentials_required"
    staged = manifest()
    staged["additionalFields"]["repositories"] = []
    saved = normalize_bitbucket_manifest(staged, allow_empty=True)
    with pytest.raises(BitbucketError):
        normalize_bitbucket_manifest(saved)


def test_token_identity_hydration_does_not_change_policy_fingerprint():
    record = manifest(True, "username_password")
    record["identity_id"] = "saved-id"
    record["auth"] = {"type": "identity", "identity": "saved-id"}
    hydrated = copy.deepcopy(record)
    hydrated["auth"] = {"type": "username_password", "identity": "email@example.test", "key": "private"}
    assert policy_fingerprint(record) == policy_fingerprint(hydrated)


@pytest.mark.parametrize("next_url", [
    "https://untrusted.invalid/2.0/repositories/team?page=2",
    "https://api.bitbucket.org/2.0/repositories/other?page=2",
    "https://api.bitbucket.org/2.0/repositories/team?page=1",
    "https://api.bitbucket.org/2.0/repositories/team?page=2&pagelen=1000",
])
def test_pagination_never_changes_destination_operation_or_budget(next_url):
    instance, transport = client([{"values": [], "next": next_url}], cloud=True)
    with pytest.raises(BitbucketError) as error:
        instance.discover("team")
    assert error.value.code == "response_invalid"
    assert len(transport.calls) == 1


def test_comparison_serialized_budget_and_continuation_are_truthful():
    instance, _transport = client([], cloud=True)
    instance.repository = lambda repository: instance.fields["repositories"][0]
    instance.resolve = lambda repo, branch: (branch, BASE if branch == "main" else TARGET)
    instance.get = lambda *args, **kwargs: {"hash": MERGE}
    instance.page = lambda *args, **kwargs: ([
        {"old": None, "new": {"path": "one.py"}}, {"old": None, "new": {"path": "two.py"}},
    ], "opaque-next")
    instance.source = lambda *args, **kwargs: "\u00e9" * 100000
    result = instance.compare("", "main", "feature")
    assert len(json.dumps(result).encode()) <= 1000000
    assert result["truncated"] and result["next_cursor"] == "opaque-next"
    assert any(file.get("omitted") == "comparison_byte_limit" for file in result["files"])
    reviewed = next(file for file in result["files"] if "patch" in file)
    assert "\\ No newline at end of file\n" in reviewed["patch"]


@pytest.mark.parametrize("optimized", [False, True])
def test_bitbucket_modules_and_real_web_bootstrap_import_network_free(optimized):
    probe = """
import importlib
from test_support.offline_bootstrap import offline_app_imports
with offline_app_imports() as environment:
    import functions_bitbucket_operations
    import functions_bitbucket_connections
    from semantic_kernel_plugins.bitbucket_plugin import BitbucketPlugin
    import app
    import functions_orchestration_bootstrap
    from semantic_kernel_plugins.plugin_loader import discover_plugins
    discovered = discover_plugins()
    if discovered.get("BitbucketPlugin") is not BitbucketPlugin:
        raise AssertionError("Canonical Bitbucket discovery failed")
    from test_bitbucket_action_plugin import manifest
    from functions_action_manifest import bind_action_origin
    from semantic_kernel import Kernel
    from semantic_kernel_plugins.plugin_health_checker import PluginHealthChecker
    from semantic_kernel_plugins.logged_plugin_loader import LoggedPluginLoader
    from semantic_kernel_loader import load_plugins_for_kernel
    candidate = bind_action_origin({**manifest(), "description": "Review repository source."}, "personal", "actor")
    valid, errors = PluginHealthChecker.validate_plugin_manifest(candidate, "bitbucket")
    if not valid:
        raise AssertionError(errors)
    kernel = Kernel()
    loaded = LoggedPluginLoader(kernel).load_plugin_from_manifest(candidate, "actor")
    if not loaded or set(kernel.plugins["review"].functions) != {
        "list_repositories", "list_branches", "list_tree", "read_file", "compare_branches",
    }:
        raise AssertionError("Logged loader did not register the read-only tool contract")
    kernel = Kernel()
    settings = {key: False for key in (
        "enable_time_plugin", "enable_http_plugin", "enable_wait_plugin", "enable_math_plugin",
        "enable_text_plugin", "enable_default_embedding_model_plugin",
    )}
    load_plugins_for_kernel(kernel, [candidate], settings)
    if "review" not in kernel.plugins or "compare_branches" not in kernel.plugins["review"].functions:
        raise AssertionError("Runtime kernel loader did not register Bitbucket")
    if environment.network_attempts:
        raise AssertionError("Unexpected startup network request")
"""
    environment = {**os.environ, "PYTHONPATH": os.pathsep.join((str(APP), str(ROOT / "functional_tests")))}
    command = [sys.executable, *(["-O"] if optimized else []), "-c", probe]
    result = subprocess.run(command, cwd=ROOT, env=environment, capture_output=True, text=True, timeout=180)
    assert result.returncode == 0, result.stdout + result.stderr

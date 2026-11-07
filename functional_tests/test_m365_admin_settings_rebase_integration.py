# test_m365_admin_settings_rebase_integration.py
"""
Native Microsoft 365 transport setting parity after Development integration.
Version: 0.261.122
Implemented in: 0.261.122

Exercise real schema declarations and transport validation without Azure clients.
Partial edits must not rewrite companion settings or truncate trusted host names.
"""

import copy

import pytest

from test_support.app_stubs import import_app_module


PROVIDER = "m365_retrieval_provider"
HOSTS = "m365_trusted_download_hosts"


@pytest.fixture
def fields():
    return import_app_module("admin_settings_fields")


def test_transport_fields_are_declared_with_the_classic_defaults(fields):
    provider = fields.get_field_definition(PROVIDER)
    hosts = fields.get_field_definition(HOSTS)
    assert provider["default"] == "auto"
    assert {option["value"] for option in provider["options"]} == {"auto", "graph"}
    assert hosts["default"] == []
    assert hosts["type"] == "textarea"


@pytest.mark.parametrize("provider", ["auto", "graph"])
def test_provider_edits_do_not_rewrite_download_hosts(fields, provider):
    current = {PROVIDER: "auto", HOSTS: ["keep.example"], "unrelated": True}
    original = copy.deepcopy(current)
    normalized, errors, warnings = fields.normalize_admin_settings_updates({PROVIDER: provider}, current)
    assert normalized == {PROVIDER: provider}
    assert errors == {} and warnings == {}
    assert current == original


@pytest.mark.parametrize("provider", ["copilot", "", None, [], {}, False])
def test_invalid_provider_choices_are_reported(fields, provider):
    normalized, errors, _ = fields.normalize_admin_settings_updates({PROVIDER: provider})
    assert PROVIDER in errors and PROVIDER not in normalized


@pytest.mark.parametrize("value,expected", [
    ("*.FILES.EXAMPLE.\nfiles.example; second.example", ["files.example", "second.example"]),
    (["*.FILES.EXAMPLE.", "files.example", "second.example"], ["files.example", "second.example"]),
    ("", []),
    ([], []),
    (["a" * 60 + "." + "b" * 60 + ".example"], ["a" * 60 + "." + "b" * 60 + ".example"]),
])
def test_host_edits_use_transport_normalization_and_leave_provider_untouched(fields, value, expected):
    current = {PROVIDER: "graph", HOSTS: ["previous.example"]}
    normalized, errors, warnings = fields.normalize_admin_settings_updates({HOSTS: value}, current)
    assert normalized == {HOSTS: expected}
    assert errors == {} and warnings == {}
    assert current == {PROVIDER: "graph", HOSTS: ["previous.example"]}


@pytest.mark.parametrize("hosts", [
    "https://files.example", "127.0.0.1", "*.127.0.0.1", "localhost",
    "files.example/path", "*", None, {},
    [f"host{index}.example" for index in range(31)],
])
def test_invalid_download_hosts_have_field_errors_instead_of_persistence(fields, hosts):
    normalized, errors, _ = fields.normalize_admin_settings_updates({HOSTS: hosts})
    assert HOSTS in errors and HOSTS not in normalized

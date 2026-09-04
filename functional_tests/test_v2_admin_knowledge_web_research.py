#!/usr/bin/env python3
# test_v2_admin_knowledge_web_research.py
"""
Functional test for the Knowledge group's Web & Research tab in the V2 admin UI.
Version: 0.261.084
Implemented in: 0.261.084

Web Search, URL Access and Deep Research are the first Knowledge sections
described in ``admin_settings_fields.py``. Before that they existed in the V2
surface only as bare switches discovered by the ``enable_*`` scan, with every
endpoint, credential, budget and domain list invisible.

The checks here cover what a generic renderer cannot get right on its own:

parity
    Every field the V1 pane submits is claimed, and the schema invents nothing
    the application does not read.

storage shape
    The Foundry connection is assembled into a nested ``web_search_agent``
    object rather than stored as top-level keys, and the URL Access domain lists
    are stored twice. A field that writes the wrong place saves successfully and
    changes nothing, which is the worst kind of failure to diagnose.

consent
    Web Search moves customer data outside the Azure compliance boundary. The
    toggle is gated on accepting the Grounding with Bing terms, and a save that
    turns it on without the acknowledgement has to be refused.
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
    / "web-research.html"
)

WEB_RESEARCH_SECTIONS = (
    "web-search-section",
    "url-access-section",
    "source-review-section",
)

fields_module = import_app_module("admin_settings_fields")
normalize = fields_module.normalize_admin_settings_updates

FIELD_NAME_RE = re.compile(r'\sname="([^"]+)"')
JINJA_RE = re.compile(r"\{\{|\{%")


def pane_field_names():
    """Literal form field names the server-rendered pane submits."""
    markup = PANE.read_text(encoding="utf-8")
    return {name for name in FIELD_NAME_RE.findall(markup) if not JINJA_RE.search(name)}


def section_fields(section_id):
    return [
        field
        for declared_section, field in fields_module.iter_fields()
        if declared_section == section_id
    ]


def test_the_tab_sections_match_navigation():
    """A field filed under an unknown section id would never render."""
    print("Testing Web & Research sections against ADMIN_NAV...")

    assert_app_version_at_least("0.261.084")

    nav_sections = {
        section["id"]
        for group in ADMIN_NAV
        if group["id"] == "knowledge"
        for tab in group["tabs"]
        if tab["id"] == "web-research"
        for section in tab["sections"]
    }

    assert set(WEB_RESEARCH_SECTIONS) == nav_sections, (
        "The Web & Research tab's sections changed. Update the schema and this "
        f"test together.\n  ADMIN_NAV: {sorted(nav_sections)}\n  test: "
        f"{sorted(WEB_RESEARCH_SECTIONS)}"
    )

    for section_id in WEB_RESEARCH_SECTIONS:
        assert section_fields(section_id), f"{section_id} declares no fields."

    print(f"  All {len(nav_sections)} section(s) exist in ADMIN_NAV and are described.")
    return True


def test_every_v1_field_is_claimed():
    """A V1 field with no V2 equivalent is invisible in the new UI."""
    print("\nTesting that every V1 field is claimed by the schema...")

    claimed = fields_module.get_legacy_field_names()
    documented = set(fields_module.LEGACY_FIELDS_WITHOUT_V2_EQUIVALENT)

    names = pane_field_names()
    missing = sorted(names - claimed - documented)

    assert not missing, (
        "These fields exist in the server-rendered Web & Research pane but are "
        "not described in admin_settings_fields.py, so they cannot appear in the "
        "V2 admin UI. Add a field definition, record the name in "
        "LEGACY_FIELD_NAMES if the shapes differ, or document the omission in "
        "LEGACY_FIELDS_WITHOUT_V2_EQUIVALENT:\n  " + "\n  ".join(missing)
    )

    print(f"  All {len(names)} V1 field(s) are claimed.")
    return True


def test_the_schema_invents_nothing():
    """A schema key with no V1 counterpart would save a setting nothing reads."""
    print("\nTesting that the schema invents no fields...")

    v1_names = pane_field_names()

    invented = []
    for section_id in WEB_RESEARCH_SECTIONS:
        for field in section_fields(section_id):
            key = field.get("key")
            if not key:
                continue
            legacy = fields_module.LEGACY_FIELD_NAMES.get(key, [key])
            if not any(name in v1_names for name in legacy):
                invented.append(f"{section_id}.{key}")

    assert not invented, (
        "These schema fields have no matching field in the V1 pane, so V2 would "
        "write settings the rest of the application never reads:\n  "
        + "\n  ".join(invented)
    )

    print("  Every declared field maps back to a V1 field.")
    return True


def test_the_foundry_connection_is_stored_where_the_runtime_reads_it():
    """The connection is assembled into web_search_agent, not top-level keys."""
    print("\nTesting Foundry connection storage...")

    current = {
        "web_search_agent": {
            "agent_type": "aifoundry",
            "other_settings": {
                "azure_ai_foundry": {
                    "agent_id": "asst_existing",
                    "endpoint": "https://old.invalid/api/projects/p",
                    "client_secret": "stored-secret",
                }
            },
        }
    }

    normalized, errors, _ = normalize(
        {"web_search_foundry_endpoint": "https://new.invalid/api/projects/p"}, current
    )
    assert not errors, errors

    assert "web_search_foundry_endpoint" not in normalized, (
        "The flat form-field name was written as a top-level key. Nothing reads "
        "it, so the save would appear to succeed and change nothing."
    )

    agent = normalized.get("web_search_agent")
    assert isinstance(agent, dict), f"Expected web_search_agent to be rebuilt: {normalized}"

    foundry = agent["other_settings"]["azure_ai_foundry"]
    assert foundry["endpoint"] == "https://new.invalid/api/projects/p", foundry

    # update_settings merges at the top level only, so the whole object is
    # replaced. Anything not rewritten from the stored copy is lost.
    assert foundry["agent_id"] == "asst_existing", (
        "Editing the endpoint dropped the agent id. The containing object must "
        "be rebuilt from the stored one, not written from the changed leaf alone."
    )
    assert foundry["client_secret"] == "stored-secret", (
        "Editing the endpoint dropped the stored client secret."
    )
    assert agent["agent_type"] == "aifoundry", "A sibling key outside other_settings was lost."

    # The runtime still reads the legacy flat endpoint, so both are written.
    assert agent["azure_openai_gpt_endpoint"] == "https://new.invalid/api/projects/p", (
        "The legacy endpoint key was not updated alongside the nested one."
    )

    print("  The connection writes into web_search_agent and preserves siblings.")
    return True


def test_domain_lists_are_stored_for_both_readers():
    """Deep Research reads the source_review copy of the same lists."""
    print("\nTesting URL Access domain list storage...")

    normalized, errors, _ = normalize(
        {"url_access_allowed_domains": ["example.com", " *.contoso.com ", "EXAMPLE.com"]},
        {},
    )
    assert not errors, errors

    assert normalized["url_access_allowed_domains"] == ["example.com", "*.contoso.com"], (
        f"Entries should be trimmed and deduplicated: {normalized}"
    )
    assert normalized.get("source_review_allowed_domains") == [
        "example.com",
        "*.contoso.com",
    ], (
        "Deep Research reads source_review_allowed_domains. Writing only the "
        "url_access copy leaves it reading a stale list, so a domain removed "
        "from the allow list would still be reachable through Deep Research."
    )

    blocked, errors, _ = normalize({"url_access_blocked_domains": ["bad.example"]}, {})
    assert not errors, errors
    assert blocked.get("source_review_blocked_domains") == ["bad.example"], blocked

    rejected, errors, _ = normalize(
        {"url_access_allowed_domains": ["not a domain"]}, {}
    )
    assert "url_access_allowed_domains" in errors, (
        "A value that is not a domain should be refused rather than stored as a "
        f"rule that can never match: {rejected}"
    )

    print("  Domain lists write both copies and reject malformed entries.")
    return True


def test_web_search_requires_consent_before_it_can_be_enabled():
    """The Grounding with Bing terms are a legal gate, not advice."""
    print("\nTesting the web search consent gate...")

    field = fields_module.get_field_definition("enable_web_search")
    assert field, "enable_web_search is not declared."

    acknowledgement = field.get("requires_acknowledgement")
    assert acknowledgement, (
        "enable_web_search must declare requires_acknowledgement. Turning web "
        "search on moves customer data outside the Azure compliance boundary, "
        "and the server-rendered page will not let it be enabled without the "
        "administrator accepting that."
    )
    assert acknowledgement["key"] == "web_search_consent_accepted", acknowledgement

    _, errors, _ = normalize({"enable_web_search": True}, {"enable_web_search": False})
    assert "enable_web_search" in errors, (
        "Enabling web search without the consent flag was accepted."
    )

    accepted, errors, _ = normalize(
        {"enable_web_search": True, "web_search_consent_accepted": True},
        {"enable_web_search": False},
    )
    assert not errors, errors
    assert accepted["enable_web_search"] is True, accepted
    assert "web_search_consent_accepted" not in accepted, (
        "The acknowledgement gates the save; it is not itself a stored setting."
    )

    # Turning it off again needs no consent.
    disabled, errors, _ = normalize({"enable_web_search": False}, {"enable_web_search": True})
    assert not errors, errors
    assert disabled["enable_web_search"] is False, disabled

    print("  Web search cannot be enabled without the consent acknowledgement.")
    return True


def test_each_section_leads_with_its_capability():
    """The switch that governs a section belongs in its header, not its body."""
    print("\nTesting capability roles...")

    for section_id in WEB_RESEARCH_SECTIONS:
        capabilities = [
            field for field in section_fields(section_id) if field.get("role") == "capability"
        ]
        assert len(capabilities) == 1, (
            f"{section_id} declares {len(capabilities)} capability fields; each "
            "section should name exactly one, so the shell knows which switch to "
            "lift into the header."
        )
        assert capabilities[0]["type"] == "switch", capabilities[0]

    print("  Each section names exactly one capability switch.")
    return True


def test_auth_branches_are_mutually_exclusive():
    """Showing both auth paths at once is what makes the V1 pane confusing."""
    print("\nTesting Foundry authentication branching...")

    evaluate = fields_module.evaluate_dependency
    by_key = {
        field["key"]: field
        for field in section_fields("web-search-section")
        if field.get("key")
    }

    service_principal = {
        "enable_web_search": True,
        "web_search_foundry_auth_type": "service_principal",
        "web_search_foundry_cloud": "",
    }
    managed_identity = {
        "enable_web_search": True,
        "web_search_foundry_auth_type": "managed_identity",
        "web_search_foundry_managed_identity_type": "system_assigned",
    }

    def visible(key, state):
        return evaluate(by_key[key].get("depends_on"), state.get)

    for key in ("web_search_foundry_tenant_id", "web_search_foundry_client_id",
                "web_search_foundry_client_secret"):
        assert visible(key, service_principal), f"{key} should show for a service principal"
        assert not visible(key, managed_identity), f"{key} should hide for a managed identity"

    assert visible("web_search_foundry_managed_identity_type", managed_identity)
    assert not visible("web_search_foundry_managed_identity_type", service_principal)

    # The user-assigned client id only matters for a user-assigned identity.
    assert not visible("web_search_foundry_managed_identity_client_id", managed_identity)
    user_assigned = {
        **managed_identity,
        "web_search_foundry_managed_identity_type": "user_assigned",
    }
    assert visible("web_search_foundry_managed_identity_client_id", user_assigned)

    # The authority endpoint only matters for a custom cloud.
    assert not visible("web_search_foundry_authority", service_principal)
    custom_cloud = {**service_principal, "web_search_foundry_cloud": "custom"}
    assert visible("web_search_foundry_authority", custom_cloud)

    # Nothing in the connection shows while the capability is off.
    off = {"enable_web_search": False, "web_search_foundry_auth_type": "service_principal"}
    assert not visible("web_search_foundry_endpoint", off)

    print("  Only the authentication path in use is shown.")
    return True


def test_the_dead_activation_mode_control_is_not_reproduced():
    """V1 renders a disabled select with one option shadowed by a hidden input."""
    print("\nTesting that the activation mode control is documented, not copied...")

    assert "source_review_default_mode" in fields_module.LEGACY_FIELDS_WITHOUT_V2_EQUIVALENT, (
        "source_review_default_mode should be recorded as a deliberate omission "
        "with a reason, not silently dropped."
    )
    assert not fields_module.get_field_definition("source_review_default_mode"), (
        "source_review_default_mode is a permanently disabled control offering "
        "one value, which get_source_review_config rewrites on read anyway. "
        "Reproducing it implies a setting that does not exist."
    )

    print("  The dead control is documented rather than reproduced.")
    return True


if __name__ == "__main__":
    tests = [
        test_the_tab_sections_match_navigation,
        test_every_v1_field_is_claimed,
        test_the_schema_invents_nothing,
        test_the_foundry_connection_is_stored_where_the_runtime_reads_it,
        test_domain_lists_are_stored_for_both_readers,
        test_web_search_requires_consent_before_it_can_be_enabled,
        test_each_section_leads_with_its_capability,
        test_auth_branches_are_mutually_exclusive,
        test_the_dead_activation_mode_control_is_not_reproduced,
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

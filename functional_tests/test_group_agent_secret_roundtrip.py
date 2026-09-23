# test_group_agent_secret_roundtrip.py
"""
§2.1 Key Vault scope round trips for group agents.
Version: 0.261.138
Implemented in: 0.261.138

M4C §8 B5. ``test_group_agent_secret_scope.py`` pins the ``_secret_scope`` seam in
isolation; this test proves the two round trips that seam exists to protect, using
the REAL Key Vault naming helpers and the REAL editor staging engine, faking only
the Key Vault client and settings cache (both supplied by the shared authoring
harness, which stores secrets in an in-memory vault).

(a) A V1-created group agent — its key written by the legacy
    ``keyvault_agent_save_helper(scope="group")`` — is edited in V2 on another
    field. The editor engine must recognise the stored ``group`` reference as its
    own and keep it: nothing is minted, and the reference is unchanged. Were the
    agent scope still hardcoded to ``user`` the reference would fail its context
    check and the edit would be refused.

(b) A V2-created group agent key, staged by the editor engine, is deleted through
    the legacy path ``keyvault_agent_delete_helper(scope="group")``. The staged
    reference lives under the ``group`` namespace, so the legacy delete removes it
    and no orphan ``--agent--user--`` secret is ever created.

(c) A V2-created group agent key is then edited through the CLASSIC UI, which
    submits the masked placeholder. ``keyvault_agent_save_helper(scope="group")``
    must recognise the editor group reference as belonging to this scope and keep
    it verbatim, minting nothing. Under the pre-§2.1 ``user`` scope the reference
    would fail its context check and the classic edit would be refused.

Key Vault storage is enabled in the settings each helper actually reads
(``app_settings_cache.get_settings_cache``); with it off the helpers return early,
so the assertions on the fake vault client (the exact set/delete names) are the
positive control proving the round trips execute rather than no-op.
"""

import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parent))

from test_support.versioning import assert_app_version_at_least
from test_workspace_authoring_backend import environment  # noqa: F401  (pytest fixture)

GROUP_ID = "group-a"
MEMBER = "member-user"


def _group_agent_secret_names(vault):
    return [name for name in vault if "--agent--" in name]


def test_version_at_least_implementation():
    assert_app_version_at_least("0.261.138")


def test_v1_group_key_is_kept_by_the_v2_editor_and_nothing_is_minted(environment):
    env = environment
    env.services.settings["enable_key_vault_secret_storage"] = True
    agent_id = "agent-b5a"
    agent_name = "V1 group assistant"

    # (a) V1 create: the legacy helper writes the key under the group namespace.
    v1_agent = {"id": agent_id, "name": agent_name, "azure_openai_gpt_key": "v1-secret-value"}
    saved = env.keyvault.keyvault_agent_save_helper(v1_agent, agent_id, scope="group")
    reference = saved["azure_openai_gpt_key"]
    expected = env.keyvault.build_full_secret_name(agent_name, agent_id, "agent", "group")
    assert reference == expected
    assert "--agent--group--" in reference and "--agent--user--" not in reference
    assert env.services.vault[reference] == "v1-secret-value"

    # (b) V2 edit of another field: the engine re-checks and re-stages secrets.
    stored = {
        "id": agent_id, "name": agent_name,
        "azure_openai_gpt_key": reference, "description": "Edited in V2",
    }
    writes_before = list(env.services.secret_writes)
    # The stored group reference is recognised as this record's own credential.
    env.helper._check_stored_references(stored, "agents", MEMBER, group_id=GROUP_ID)
    staged = []
    env.helper._stage_editor_secrets(
        stored, "agents", MEMBER, env.services.settings, staged, group_id=GROUP_ID,
    )
    # Nothing minted, the reference kept verbatim, no new Key Vault write.
    assert staged == []
    assert stored["azure_openai_gpt_key"] == reference
    assert env.services.secret_writes == writes_before


def test_v1_group_key_would_be_rejected_under_the_old_user_scope(environment):
    """Guard the seam: the same stored reference is refused when resolved as user."""
    env = environment
    env.services.settings["enable_key_vault_secret_storage"] = True
    agent_id = "agent-b5a2"
    agent_name = "V1 scope guard"
    v1_agent = {"id": agent_id, "name": agent_name, "azure_openai_gpt_key": "v1-secret-value"}
    reference = env.keyvault.keyvault_agent_save_helper(
        v1_agent, agent_id, scope="group",
    )["azure_openai_gpt_key"]
    stored = {"id": agent_id, "name": agent_name, "azure_openai_gpt_key": reference}

    # Personal scope (the pre-§2.1 behaviour, group_id omitted) must not accept a
    # group-scoped reference: this is exactly the refusal the fix avoids for V2.
    with pytest.raises(env.helper.WorkspaceAuthoringValidation):
        env.helper._check_stored_references(stored, "agents", MEMBER, group_id=None)


def test_v2_group_key_is_deleted_by_the_legacy_group_path_with_no_user_orphan(environment):
    env = environment
    env.services.settings["enable_key_vault_secret_storage"] = True
    agent_id = "agent-b5b"
    agent_name = "V2 group assistant"

    # (a) V2 create: the editor engine stages the plaintext key under group scope.
    record = {"id": agent_id, "name": agent_name, "azure_openai_gpt_key": "v2-secret-value"}
    staged = []
    env.helper._stage_editor_secrets(
        record, "agents", MEMBER, env.services.settings, staged, group_id=GROUP_ID,
    )
    v2_reference = record["azure_openai_gpt_key"]
    assert staged == [v2_reference]
    assert "--agent--group--" in v2_reference and "--agent--user--" not in v2_reference
    assert env.services.vault[v2_reference] == "v2-secret-value"
    # The §2.1 promise: no personal-namespace orphan is ever minted.
    assert all("--agent--user--" not in name for name in _group_agent_secret_names(env.services.vault))

    # (b) Legacy delete through the group path removes the staged group reference.
    env.keyvault.keyvault_agent_delete_helper(record, agent_id, scope="group")
    assert v2_reference in env.services.secret_deletes
    assert v2_reference not in env.services.vault
    assert _group_agent_secret_names(env.services.vault) == []


def test_v2_group_key_is_preserved_by_a_classic_placeholder_edit(environment):
    """(c) V2 creates, classic edits: the placeholder keeps the editor group reference."""
    env = environment
    env.services.settings["enable_key_vault_secret_storage"] = True
    agent_id = "agent-b5c"
    agent_name = "V2 then classic"

    # V2 create: the editor engine stages the plaintext key under the group scope.
    record = {"id": agent_id, "name": agent_name, "azure_openai_gpt_key": "v2-secret-value"}
    staged = []
    env.helper._stage_editor_secrets(
        record, "agents", MEMBER, env.services.settings, staged, group_id=GROUP_ID,
    )
    v2_reference = record["azure_openai_gpt_key"]
    assert staged == [v2_reference]
    assert "--agent--group--" in v2_reference

    writes_before = list(env.services.secret_writes)
    # Classic edit: the classic UI submits the masked placeholder and the stored
    # record as ``existing``. The legacy group save must recognise the editor
    # reference as belonging to this group scope and keep it verbatim.
    updated = {"id": agent_id, "name": agent_name, "azure_openai_gpt_key": env.keyvault.ui_trigger_word}
    existing = {"id": agent_id, "name": agent_name, "azure_openai_gpt_key": v2_reference}
    result = env.keyvault.keyvault_agent_save_helper(
        updated, agent_id, scope="group", existing_agent=existing,
    )
    # The editor-staged group reference is preserved and nothing new is minted.
    assert result["azure_openai_gpt_key"] == v2_reference
    assert env.services.secret_writes == writes_before
    assert env.services.vault[v2_reference] == "v2-secret-value"
    assert "--agent--user--" not in v2_reference


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))

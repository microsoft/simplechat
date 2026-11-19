# test_agent_credential_security.py
"""Agent credential authorization regressions.

Version: 0.261.428
Implemented in: 0.261.428

Real Key Vault owner helpers use the existing isolated owner fixture. No cloud
credentials or external connections are used.
"""

from copy import deepcopy
import sys
from pathlib import Path
import os
import subprocess

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "application" / "single_app"))

from agent_credential_contracts import (
    AGENT_CREDENTIAL_BINDINGS, AGENT_SECRET_LABELS, AgentCredentialReentryRequired,
    agent_credential_is_ready, agent_credential_scope, agent_credential_status,
    bind_agent_credential,
)
from test_workspace_authoring_backend import environment
from test_support.versioning import assert_app_version_at_least


def agent(value="new-literal"):
    return {"id": "same-id", "name": "same-name", "azure_openai_gpt_key": value}


def test_implementation_version():
    assert_app_version_at_least("0.261.428")


def test_binding_does_not_truncate_long_owner_ids():
    first = agent_credential_scope("user", "a" * 200 + "1", "same-id", ("azure_openai_gpt_key",))
    second = agent_credential_scope("user", "a" * 200 + "2", "same-id", ("azure_openai_gpt_key",))
    assert first != second
    assert len(first) == 64


@pytest.mark.parametrize("scope", ["user", "group", "global"])
def test_binding_includes_owner_agent_and_slot(scope):
    record = agent()
    bind_agent_credential(record, ("azure_openai_gpt_key",), scope, "owner-a")
    assert agent_credential_is_ready(record, ("azure_openai_gpt_key",), scope, "owner-a")
    assert not agent_credential_is_ready(record, ("azure_openai_gpt_key",), scope, "owner-b")
    other = {**record, "id": "different-id"}
    assert not agent_credential_is_ready(other, ("azure_openai_gpt_key",), scope, "owner-a")
    assert agent_credential_scope(scope, "owner-a", "same-id", ("azure_openai_gpt_key",)) != (
        agent_credential_scope(scope, "owner-a", "same-id", ("azure_agent_apim_gpt_subscription_key",))
    )


def test_legacy_and_tampered_credentials_require_reentry():
    record = agent("old-literal")
    assert agent_credential_status(record, "user", "owner-a")
    bind_agent_credential(record, ("azure_openai_gpt_key",), "user", "owner-a")
    record["azure_openai_gpt_key"] = "changed-without-binding"
    assert agent_credential_status(record, "user", "owner-a")
    record[AGENT_CREDENTIAL_BINDINGS] = {"/azure_openai_gpt_key": "\u00e9" * 64}
    assert agent_credential_status(record, "user", "owner-a")


@pytest.mark.parametrize("vault_enabled", [False, True])
@pytest.mark.parametrize("path", list(AGENT_SECRET_LABELS))
def test_all_fields_reject_foreign_references_even_when_inactive(environment, vault_enabled, path):
    env = environment
    env.services.settings["enable_key_vault_secret_storage"] = vault_enabled
    record = agent("")
    env.keyvault._set_nested_dict_value(record, path, "victim--action--user--sample")
    record["enable_agent_gpt_apim"] = True
    before = dict(env.services.vault)
    with pytest.raises(ValueError):
        env.keyvault.keyvault_agent_save_helper(record, record["id"], scope="user", owner_id="owner-a")
    assert env.services.vault == before


@pytest.mark.parametrize("scope", ["user", "group"])
def test_same_id_cannot_share_overwrite_or_delete_another_owners_secret(environment, scope):
    env = environment
    env.services.settings["enable_key_vault_secret_storage"] = True
    first = env.keyvault.keyvault_agent_save_helper(agent(), "same-id", scope=scope, owner_id="owner-a")
    second = env.keyvault.keyvault_agent_save_helper(agent(), "same-id", scope=scope, owner_id="owner-b")
    assert first["azure_openai_gpt_key"] != second["azure_openai_gpt_key"]
    borrowed = {**second, "azure_openai_gpt_key": first["azure_openai_gpt_key"]}
    with pytest.raises(AgentCredentialReentryRequired):
        env.keyvault.keyvault_agent_get_helper(
            borrowed, "same-id", scope=scope, owner_id="owner-b",
            return_type=env.keyvault.SecretReturnType.VALUE,
        )
    env.keyvault.keyvault_agent_delete_helper(borrowed, "same-id", scope=scope, owner_id="owner-b")
    assert first["azure_openai_gpt_key"] not in env.services.secret_deletes


def test_masked_legacy_save_never_reads_or_upgrades_the_old_value(environment):
    env = environment
    env.services.settings["enable_key_vault_secret_storage"] = True
    old = agent("same-id--agent--user--legacy")
    before = dict(env.services.vault)
    saved = env.keyvault.keyvault_agent_save_helper(
        agent("Stored_In_KeyVault"), "same-id", scope="user", owner_id="owner-a", existing_agent=old,
    )
    assert saved["azure_openai_gpt_key"] == old["azure_openai_gpt_key"]
    assert not saved.get(AGENT_CREDENTIAL_BINDINGS)
    assert env.services.vault == before
    with pytest.raises(AgentCredentialReentryRequired):
        env.keyvault.keyvault_agent_get_helper(
            saved, "same-id", scope="user", owner_id="owner-a",
            return_type=env.keyvault.SecretReturnType.VALUE,
        )


def test_reentry_restores_execution_and_nested_fields_are_masked(environment):
    env = environment
    env.services.settings["enable_key_vault_secret_storage"] = True
    record = agent()
    record["other_settings"] = {"new_foundry": {"client_secret": "fresh-client-secret"}}
    saved = env.keyvault.keyvault_agent_save_helper(record, "same-id", scope="user", owner_id="owner-a")
    hydrated = env.keyvault.keyvault_agent_get_helper(
        saved, "same-id", scope="user", owner_id="owner-a",
        return_type=env.keyvault.SecretReturnType.VALUE,
    )
    assert hydrated["azure_openai_gpt_key"] == "new-literal"
    assert hydrated["other_settings"]["new_foundry"]["client_secret"] == "fresh-client-secret"
    ui = env.keyvault.keyvault_agent_get_helper(saved, "same-id", scope="user", owner_id="owner-a")
    assert AGENT_CREDENTIAL_BINDINGS not in ui
    assert ui["other_settings"]["new_foundry"]["client_secret"] == "Stored_In_KeyVault"
    assert "fresh-client-secret" not in repr(ui)


def test_canonical_apim_reentry_retires_unusable_legacy_alias(environment):
    env = environment
    old = agent("")
    old["azure_apim_gpt_subscription_key"] = "foreign--agent--group--legacy"
    proposed = {
        **old, "azure_agent_apim_gpt_subscription_key": "fresh-apim-key",
        "enable_agent_gpt_apim": True,
    }
    saved = env.keyvault.keyvault_agent_save_helper(
        proposed, "same-id", scope="user", owner_id="owner-a", existing_agent=old,
    )
    assert "azure_apim_gpt_subscription_key" not in saved
    assert agent_credential_is_ready(saved, ("azure_agent_apim_gpt_subscription_key",), "user", "owner-a")
    assert env.services.secret_reads == []


@pytest.mark.parametrize("vault_enabled", [False, True])
def test_masked_credential_cannot_follow_a_changed_destination(environment, vault_enabled):
    env = environment
    env.services.settings["enable_key_vault_secret_storage"] = vault_enabled
    original = {**agent(), "azure_openai_gpt_endpoint": "https://approved.example.test"}
    saved = env.keyvault.keyvault_agent_save_helper(original, "same-id", scope="user", owner_id="owner-a")
    proposed = {
        **saved, "azure_openai_gpt_endpoint": "https://different.example.test",
        "azure_openai_gpt_key": "Stored_In_KeyVault",
    }
    changed = env.keyvault.keyvault_agent_save_helper(
        proposed, "same-id", scope="user", owner_id="owner-a", existing_agent=saved,
    )
    assert not agent_credential_is_ready(changed, ("azure_openai_gpt_key",), "user", "owner-a")
    with pytest.raises(AgentCredentialReentryRequired):
        env.keyvault.keyvault_agent_get_helper(
            changed, "same-id", scope="user", owner_id="owner-a", return_type=env.keyvault.SecretReturnType.VALUE,
        )
    assert env.services.secret_reads == []


def test_foundry_secret_cannot_follow_a_changed_authority(environment):
    env = environment
    original = agent("")
    original["other_settings"] = {"new_foundry": {
        "client_secret": "fresh-client-secret", "authority": "https://login.microsoftonline.com",
        "tenant_id": "tenant", "client_id": "client",
    }}
    saved = env.keyvault.keyvault_agent_save_helper(original, "same-id", scope="user", owner_id="owner-a")
    proposed = deepcopy(saved)
    proposed["other_settings"]["new_foundry"].update({
        "client_secret": "Stored_In_KeyVault", "authority": "https://different.example.test",
    })
    changed = env.keyvault.keyvault_agent_save_helper(
        proposed, "same-id", scope="user", owner_id="owner-a", existing_agent=saved,
    )
    assert not agent_credential_is_ready(changed, ("other_settings", "new_foundry", "client_secret"), "user", "owner-a")


@pytest.mark.parametrize("order", [
    "import agent_credential_contracts; import functions_agent_payload",
    "import functions_agent_payload; import agent_credential_contracts",
])
def test_credential_contract_cold_imports_remain_bootstrap_free(order):
    probe = (
        "import socket, sys\n"
        "def blocked(*args, **kwargs): raise RuntimeError('Unexpected network')\n"
        "socket.socket.connect = blocked\nsocket.getaddrinfo = blocked\n"
        f"{order}\n"
        "if 'config' in sys.modules: raise RuntimeError('Unexpected application bootstrap')\n"
        "from agent_credential_contracts import AgentCredentialReentryRequired\n"
        "from functions_model_endpoint_validation import ModelEndpointValidationError\n"
        "if not isinstance(AgentCredentialReentryRequired(), ModelEndpointValidationError): "
        "raise RuntimeError('User-safe error boundary missing')\n"
    )
    result = subprocess.run([sys.executable, "-O", "-c", probe], env=os.environ.copy(), capture_output=True, text=True)
    assert result.returncode == 0, result.stderr

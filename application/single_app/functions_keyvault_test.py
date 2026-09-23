# functions_keyvault_test.py
"""Bounded, isolated Key Vault permission probes shared by both admin interfaces."""

from datetime import datetime, timedelta, timezone
import logging
import re
import secrets
import uuid

from azure.core.exceptions import AzureError, ResourceNotFoundError
from azure.keyvault.secrets import SecretClient

from functions_appinsights import log_event
from functions_keyvault_errors import key_vault_operation_error


PROBE_OPTIONS = {"connection_timeout": 5, "read_timeout": 10, "retry_total": 0}
PROBE_CREDENTIAL_OPTIONS = {**PROBE_OPTIONS, "process_timeout": 10}
PROBE_CLEANUP_TIMEOUT = 10
VAULT_NAME_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9-]{1,22}[A-Za-z0-9]")
CLIENT_ID_PATTERN = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
PROBE_ERRORS = (AzureError, OSError, ValueError)


def _log_probe_failure(stage, error):
    log_event(
        "[AKV_TEST] Key Vault permission probe failed.",
        extra={
            "stage": stage,
            "error_type": type(error).__name__,
            "status_code": getattr(error, "status_code", None),
        },
        level=logging.WARNING,
    )


def run_key_vault_connection_test(payload, *, vault_domain, credential_factory):
    """Write/read/delete only a unique synthetic secret; never touch stored credentials."""
    payload = payload if isinstance(payload, dict) else {}
    vault_name = payload.get("vault_name", "")
    client_id = payload.get("client_id", "")
    if client_id is None:
        client_id = ""
    if (
        not isinstance(vault_name, str)
        or not VAULT_NAME_PATTERN.fullmatch(vault_name.strip())
        or "--" in vault_name
        or not isinstance(client_id, str)
        or (client_id.strip() and not CLIENT_ID_PATTERN.fullmatch(client_id.strip()))
    ):
        log_event("[AKV_TEST] Invalid vault name or managed identity client ID.", level=logging.WARNING)
        return {
            "success": False,
            "code": "key_vault_invalid_configuration",
            "error": "Enter a valid Key Vault name and, if supplied, a managed identity client ID.",
        }, 400

    probe_name = f"simplechat-connection-test-{uuid.uuid4().hex}"
    probe_value = secrets.token_urlsafe(32)
    checks = {stage: "not_run" for stage in ("list", "write", "read", "cleanup")}
    failure = None
    cleanup_failure = None
    stage = "authentication"
    write_attempted = False
    try:
        with credential_factory(
            settings={"key_vault_identity": client_id.strip() or None},
            **PROBE_CREDENTIAL_OPTIONS,
        ) as credential:
            with SecretClient(
                vault_url=f"https://{vault_name.strip()}{vault_domain}",
                credential=credential,
                **PROBE_OPTIONS,
            ) as client:
                try:
                    stage = "list"
                    next(iter(client.list_properties_of_secrets(**PROBE_OPTIONS)), None)
                    checks[stage] = "passed"
                    stage = "write"
                    # A timed-out write may still have created the secret; always attempt cleanup.
                    write_attempted = True
                    client.set_secret(
                        probe_name,
                        probe_value,
                        expires_on=datetime.now(timezone.utc) + timedelta(minutes=10),
                        tags={"purpose": "simplechat-connection-test"},
                        **PROBE_OPTIONS,
                    )
                    checks[stage] = "passed"
                    stage = "read"
                    retrieved = client.get_secret(probe_name, **PROBE_OPTIONS)
                    if retrieved.value != probe_value:
                        raise ValueError("Key Vault probe read-back did not match.")
                    checks[stage] = "passed"
                except PROBE_ERRORS as error:
                    checks[stage] = "failed"
                    _log_probe_failure(stage, error)
                    failure = (stage, *key_vault_operation_error(stage, error))
                finally:
                    if write_attempted:
                        try:
                            deletion = client.begin_delete_secret(
                                probe_name, polling_interval=1, **PROBE_OPTIONS,
                            )
                            deletion.wait(timeout=PROBE_CLEANUP_TIMEOUT)
                            if not deletion.done():
                                raise TimeoutError("Key Vault probe cleanup is not confirmed.")
                            checks["cleanup"] = "passed"
                        except ResourceNotFoundError:
                            checks["cleanup"] = "passed"
                        except PROBE_ERRORS as error:
                            checks["cleanup"] = "failed"
                            _log_probe_failure("cleanup", error)
                            cleanup_failure = key_vault_operation_error("cleanup", error)
    except PROBE_ERRORS as error:
        _log_probe_failure(stage, error)
        if failure is None:
            failure = (stage, *key_vault_operation_error(stage, error))

    if failure or cleanup_failure:
        failed_stage, code, message = failure or ("cleanup", *cleanup_failure)
        result = {
            "success": False,
            "code": code,
            "failed_stage": failed_stage,
            "error": message,
            "checks": checks,
        }
        if cleanup_failure:
            result["cleanup_secret_name"] = probe_name
            result["error"] += (
                f" Cleanup of temporary test secret '{probe_name}' could not be confirmed. "
                "An administrator should remove it if it still exists."
            )
        return result, 400

    log_event("[AKV_TEST] Key Vault permission probe completed.", extra={"checks": checks}, level=logging.INFO)
    return {
        "success": True,
        "message": "Key Vault list, write, read-back, and temporary-secret cleanup succeeded.",
        "checks": checks,
    }, 200

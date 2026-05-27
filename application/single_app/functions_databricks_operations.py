# functions_databricks_operations.py
"""Shared configuration helpers for Databricks actions."""

from typing import Any, Dict


DATABRICKS_PLUGIN_TYPE = "databricks"
DATABRICKS_LEGACY_TABLE_PLUGIN_TYPE = "databricks_table"
DATABRICKS_CLOUD_AZURE_COMMERCIAL = "azure_commercial"
DATABRICKS_DEFAULT_CLOUD = DATABRICKS_CLOUD_AZURE_COMMERCIAL
DATABRICKS_SQL_STATEMENTS_PATH = "/api/2.0/sql/statements"
DATABRICKS_AZURE_COMMERCIAL_TOKEN_SCOPE = "2ff814a6-3304-4ab8-85cb-cd0e6f879c1d/.default"
DATABRICKS_SUPPORTED_CLOUDS = {DATABRICKS_CLOUD_AZURE_COMMERCIAL}
DATABRICKS_AUTH_METHODS = {
    "pat",
    "bearer",
    "service_principal",
    "managed_identity",
}
DATABRICKS_ALLOWED_READ_STATEMENTS = {
    "SELECT",
    "SHOW",
    "DESCRIBE",
    "EXPLAIN",
    "WITH",
}


def _as_bool(value: Any, default_value: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default_value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _as_int(value: Any, default_value: int, minimum: int, maximum: int) -> int:
    try:
        parsed_value = int(value)
    except (TypeError, ValueError):
        parsed_value = default_value
    return min(max(parsed_value, minimum), maximum)


def normalize_databricks_auth_method(raw_auth_method: Any = None, auth_type: str = "") -> str:
    normalized = str(raw_auth_method or "").strip().lower()
    normalized = normalized.replace("-", "_")
    aliases = {
        "api_key": "pat",
        "key": "pat",
        "personal_access_token": "pat",
        "token": "pat",
        "aad_bearer": "bearer",
        "client_secret": "service_principal",
        "serviceprincipal": "service_principal",
        "identity": "managed_identity",
        "managedidentity": "managed_identity",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized in DATABRICKS_AUTH_METHODS:
        return normalized

    normalized_auth_type = str(auth_type or "").strip()
    if normalized_auth_type == "servicePrincipal":
        return "service_principal"
    if normalized_auth_type == "identity":
        return "managed_identity"
    return "pat"


def normalize_databricks_additional_fields(raw_fields: Any = None, auth_type: str = "") -> Dict[str, Any]:
    fields = dict(raw_fields or {}) if isinstance(raw_fields, dict) else {}
    normalized = dict(fields)
    normalized["cloud"] = str(fields.get("cloud") or DATABRICKS_DEFAULT_CLOUD).strip().lower()
    normalized["auth_method"] = normalize_databricks_auth_method(fields.get("auth_method"), auth_type=auth_type)
    normalized["warehouse_id"] = str(fields.get("warehouse_id") or fields.get("warehouseId") or "").strip()
    normalized["catalog"] = str(fields.get("catalog") or "").strip()
    normalized["schema"] = str(fields.get("schema") or fields.get("database") or "").strip()
    normalized["read_only"] = _as_bool(fields.get("read_only"), default_value=True)
    normalized["max_rows"] = _as_int(fields.get("max_rows"), default_value=1000, minimum=1, maximum=10000)
    normalized["timeout"] = _as_int(fields.get("timeout"), default_value=30, minimum=1, maximum=300)
    normalized["wait_timeout"] = _as_int(fields.get("wait_timeout"), default_value=30, minimum=1, maximum=50)
    normalized["byte_limit"] = _as_int(fields.get("byte_limit"), default_value=250000, minimum=1000, maximum=2000000)
    return normalized
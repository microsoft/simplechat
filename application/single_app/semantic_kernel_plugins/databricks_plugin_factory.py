# databricks_plugin_factory.py
"""Factory for creating Databricks Semantic Kernel plugins from action manifests."""

from typing import Any, Dict

from functions_databricks_operations import (
    DATABRICKS_CLOUD_AZURE_COMMERCIAL,
    DATABRICKS_LEGACY_TABLE_PLUGIN_TYPE,
    DATABRICKS_PLUGIN_TYPE,
    DATABRICKS_SQL_STATEMENTS_PATH,
    normalize_databricks_additional_fields,
)
from semantic_kernel_plugins.databricks_plugin import DatabricksPlugin


class DatabricksPluginFactory:
    """Create Databricks plugin instances from stored action manifests."""

    @classmethod
    def create_from_config(cls, config: Dict[str, Any]) -> DatabricksPlugin:
        manifest = cls.normalize_manifest(config)
        cloud = manifest.get("additionalFields", {}).get("cloud")
        if cloud != DATABRICKS_CLOUD_AZURE_COMMERCIAL:
            raise ValueError("Only Azure Commercial Databricks is supported by this action version.")
        return DatabricksPlugin(manifest)

    @classmethod
    def normalize_manifest(cls, config: Dict[str, Any]) -> Dict[str, Any]:
        manifest = dict(config or {})
        auth = manifest.get("auth") if isinstance(manifest.get("auth"), dict) else {}
        auth = dict(auth)
        additional_fields = manifest.get("additionalFields") if isinstance(manifest.get("additionalFields"), dict) else {}
        additional_fields = dict(additional_fields)

        if manifest.get("type") == DATABRICKS_LEGACY_TABLE_PLUGIN_TYPE:
            manifest["type"] = DATABRICKS_PLUGIN_TYPE
            if additional_fields.get("table") and not additional_fields.get("default_table"):
                additional_fields["default_table"] = additional_fields.get("table")

        endpoint = cls._normalize_endpoint(
            manifest.get("endpoint")
            or additional_fields.get("workspace_url")
            or additional_fields.get("workspaceUrl")
            or ""
        )
        if endpoint:
            manifest["endpoint"] = endpoint
            additional_fields["workspace_url"] = endpoint

        auth_type = str(auth.get("type") or "key").strip() or "key"
        auth["type"] = auth_type
        additional_fields = normalize_databricks_additional_fields(additional_fields, auth_type=auth_type)
        if auth_type == "servicePrincipal":
            additional_fields["auth_method"] = "service_principal"
        elif auth_type == "identity" and auth.get("identity") == "managed_identity":
            additional_fields["auth_method"] = "managed_identity"

        manifest["type"] = DATABRICKS_PLUGIN_TYPE
        manifest["auth"] = auth
        manifest["additionalFields"] = additional_fields
        manifest.setdefault("metadata", {})
        return manifest

    @staticmethod
    def _normalize_endpoint(endpoint: Any) -> str:
        value = str(endpoint or "").strip().rstrip("/")
        if value.endswith(DATABRICKS_SQL_STATEMENTS_PATH):
            value = value[: -len(DATABRICKS_SQL_STATEMENTS_PATH)].rstrip("/")
        return value
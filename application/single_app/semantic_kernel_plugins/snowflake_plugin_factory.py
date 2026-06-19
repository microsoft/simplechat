# snowflake_plugin_factory.py
"""Factory for creating Snowflake Semantic Kernel plugins from action manifests."""

from typing import Any, Dict

from functions_snowflake_operations import (
    SNOWFLAKE_DEFAULT_ENDPOINT,
    SNOWFLAKE_PLUGIN_TYPE,
    normalize_snowflake_additional_fields,
)
from semantic_kernel_plugins.snowflake_plugin import SnowflakePlugin


class SnowflakePluginFactory:
    """Create Snowflake plugin instances from stored action manifests."""

    @classmethod
    def create_from_config(cls, config: Dict[str, Any]) -> SnowflakePlugin:
        manifest = cls.normalize_manifest(config)
        return SnowflakePlugin(manifest)

    @classmethod
    def normalize_manifest(cls, config: Dict[str, Any]) -> Dict[str, Any]:
        manifest = dict(config or {})
        auth = manifest.get("auth") if isinstance(manifest.get("auth"), dict) else {}
        auth = dict(auth)
        additional_fields = manifest.get("additionalFields") if isinstance(manifest.get("additionalFields"), dict) else {}
        additional_fields = dict(additional_fields)

        endpoint = str(manifest.get("endpoint") or "").strip()
        if not endpoint:
            endpoint = SNOWFLAKE_DEFAULT_ENDPOINT
        manifest["endpoint"] = endpoint

        auth_type = str(auth.get("type") or "username_password").strip() or "username_password"
        auth["type"] = auth_type
        additional_fields = normalize_snowflake_additional_fields(additional_fields, auth_type=auth_type)

        if auth_type == "username_password":
            additional_fields["auth_method"] = "password"
        elif auth_type == "identity" and additional_fields.get("identity_auth_type") == "username_password":
            additional_fields["auth_method"] = "password"

        manifest["type"] = SNOWFLAKE_PLUGIN_TYPE
        manifest["auth"] = auth
        manifest["additionalFields"] = additional_fields
        manifest.setdefault("metadata", {})
        return manifest
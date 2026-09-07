# yamcs_plugin_factory.py
"""Factory for creating Yamcs Semantic Kernel plugins from action manifests."""

from typing import Any, Dict

from functions_yamcs_operations import (
    YAMCS_AUTH_METHOD_API_KEY,
    YAMCS_AUTH_METHOD_NONE,
    YAMCS_AUTH_METHOD_USERNAME_PASSWORD,
    YAMCS_PLUGIN_TYPE,
    normalize_yamcs_additional_fields,
    normalize_yamcs_server_url,
)
from semantic_kernel_plugins.yamcs_plugin import YamcsPlugin


class YamcsPluginFactory:
    """Create Yamcs plugin instances from stored action manifests."""

    @classmethod
    def create_from_config(cls, config: Dict[str, Any]) -> YamcsPlugin:
        manifest = cls.normalize_manifest(config)
        return YamcsPlugin(manifest)

    @classmethod
    def normalize_manifest(cls, config: Dict[str, Any]) -> Dict[str, Any]:
        manifest = dict(config or {})
        auth = manifest.get("auth") if isinstance(manifest.get("auth"), dict) else {}
        auth = dict(auth)
        additional_fields = manifest.get("additionalFields") if isinstance(manifest.get("additionalFields"), dict) else {}
        additional_fields = dict(additional_fields)

        auth_type = str(auth.get("type") or "username_password").strip() or "username_password"
        auth["type"] = auth_type
        additional_fields = normalize_yamcs_additional_fields(additional_fields, auth_type=auth_type)

        if auth_type == "username_password":
            additional_fields["auth_method"] = YAMCS_AUTH_METHOD_USERNAME_PASSWORD
        elif auth_type == "NoAuth":
            additional_fields["auth_method"] = YAMCS_AUTH_METHOD_NONE
        elif auth_type == "key" and additional_fields.get("auth_method") == YAMCS_AUTH_METHOD_NONE:
            additional_fields["auth_method"] = YAMCS_AUTH_METHOD_API_KEY

        endpoint = normalize_yamcs_server_url(manifest.get("endpoint") or additional_fields.get("server_url") or "")
        if endpoint:
            manifest["endpoint"] = endpoint
            additional_fields["server_url"] = endpoint

        manifest["type"] = YAMCS_PLUGIN_TYPE
        manifest["auth"] = auth
        manifest["additionalFields"] = additional_fields
        manifest.setdefault("metadata", {})
        return manifest

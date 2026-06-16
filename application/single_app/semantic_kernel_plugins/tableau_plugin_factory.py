# tableau_plugin_factory.py
"""Factory for creating Tableau Semantic Kernel plugins from action manifests."""

from typing import Any, Dict

from functions_tableau_operations import (
    TABLEAU_AUTH_METHOD_PAT,
    TABLEAU_AUTH_METHOD_USERNAME_PASSWORD,
    TABLEAU_PLUGIN_TYPE,
    normalize_tableau_additional_fields,
    normalize_tableau_server_url,
)
from semantic_kernel_plugins.tableau_plugin import TableauPlugin


class TableauPluginFactory:
    """Create Tableau plugin instances from stored action manifests."""

    @classmethod
    def create_from_config(cls, config: Dict[str, Any]) -> TableauPlugin:
        manifest = cls.normalize_manifest(config)
        return TableauPlugin(manifest)

    @classmethod
    def normalize_manifest(cls, config: Dict[str, Any]) -> Dict[str, Any]:
        manifest = dict(config or {})
        auth = manifest.get("auth") if isinstance(manifest.get("auth"), dict) else {}
        auth = dict(auth)
        additional_fields = manifest.get("additionalFields") if isinstance(manifest.get("additionalFields"), dict) else {}
        additional_fields = dict(additional_fields)

        endpoint = normalize_tableau_server_url(
            manifest.get("endpoint")
            or additional_fields.get("server_url")
            or additional_fields.get("serverUrl")
            or ""
        )
        if endpoint:
            manifest["endpoint"] = endpoint
            additional_fields["server_url"] = endpoint

        auth_type = str(auth.get("type") or "key").strip() or "key"
        additional_fields = normalize_tableau_additional_fields(additional_fields, auth_type=auth_type)
        auth_method = additional_fields.get("auth_method") or TABLEAU_AUTH_METHOD_PAT

        if auth_type == "identity":
            identity_auth_type = str(additional_fields.get("identity_auth_type") or "").strip().lower()
            if identity_auth_type == "username_password":
                additional_fields["auth_method"] = TABLEAU_AUTH_METHOD_USERNAME_PASSWORD
            elif identity_auth_type == "api_key":
                additional_fields["auth_method"] = TABLEAU_AUTH_METHOD_PAT
        elif auth_method == TABLEAU_AUTH_METHOD_USERNAME_PASSWORD:
            auth["type"] = "username_password"
        else:
            auth["type"] = "key"
            if additional_fields.get("pat_name") and not auth.get("identity"):
                auth["identity"] = additional_fields.get("pat_name")

        manifest["type"] = TABLEAU_PLUGIN_TYPE
        manifest["auth"] = auth
        manifest["additionalFields"] = additional_fields
        manifest.setdefault("metadata", {})
        return manifest
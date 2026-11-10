# microsoft_decision_plugin_factory.py
"""Factory for Microsoft Decision-1 Semantic Kernel actions."""

from typing import Any, Dict

from functions_microsoft_decision_operations import (
    MICROSOFT_DECISION_PLUGIN_TYPE,
    normalize_microsoft_decision_additional_fields,
)
from semantic_kernel_plugins.microsoft_decision_plugin import MicrosoftDecisionPlugin


class MicrosoftDecisionPluginFactory:
    """Create Microsoft Decision-1 actions from stored manifests."""

    @classmethod
    def create_from_config(cls, config: Dict[str, Any]) -> MicrosoftDecisionPlugin:
        return MicrosoftDecisionPlugin(cls.normalize_manifest(config))

    @classmethod
    def normalize_manifest(cls, config: Dict[str, Any]) -> Dict[str, Any]:
        manifest = dict(config or {})
        auth = dict(manifest.get("auth") or {})
        additional_fields = normalize_microsoft_decision_additional_fields(
            manifest.get("additionalFields")
        )
        manifest["type"] = MICROSOFT_DECISION_PLUGIN_TYPE
        manifest["auth"] = auth
        manifest["additionalFields"] = additional_fields
        manifest.setdefault("metadata", {})
        return manifest

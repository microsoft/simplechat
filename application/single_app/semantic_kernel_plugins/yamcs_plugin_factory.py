# yamcs_plugin_factory.py
"""Factory for creating Yamcs Semantic Kernel plugins from action manifests."""

from typing import Any, Dict

from functions_yamcs_operations import (
    normalize_yamcs_manifest,
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
        return normalize_yamcs_manifest(config)

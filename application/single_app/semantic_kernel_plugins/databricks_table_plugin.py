# databricks_table_plugin.py
"""Backward-compatible Databricks table plugin wrapper."""

from typing import Any, Dict, Optional

from functions_databricks_operations import DATABRICKS_PLUGIN_TYPE
from semantic_kernel_plugins.databricks_plugin import DatabricksPlugin


class DatabricksTablePlugin(DatabricksPlugin):
    """Compatibility wrapper for legacy databricks_table manifests."""

    def __init__(self, manifest: Optional[Dict[str, Any]] = None):
        manifest_copy = dict(manifest or {})
        manifest_copy["type"] = DATABRICKS_PLUGIN_TYPE
        super().__init__(manifest_copy)

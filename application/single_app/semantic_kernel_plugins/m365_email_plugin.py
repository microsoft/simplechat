# m365_email_plugin.py
"""Source-bounded Email facade over the established Graph business operations."""

import semantic_kernel_plugins.msgraph_plugin as msgraph


class M365EmailPlugin(msgraph.MSGraphPlugin):
    ACTION_TYPE = "m365_email"

    def get_kernel_plugin(self, plugin_name=None):
        return super().get_kernel_plugin(plugin_name or self.manifest.get("name") or self.ACTION_TYPE)

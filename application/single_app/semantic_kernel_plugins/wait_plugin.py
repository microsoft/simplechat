# wait_plugin.py
"""Logged wrapper for the Semantic Kernel WaitPlugin."""

from semantic_kernel.core_plugins.wait_plugin import WaitPlugin as SKWaitPlugin

from semantic_kernel_plugins.plugin_invocation_logger import auto_wrap_plugin_functions


class WaitPlugin(SKWaitPlugin):
    """Wait plugin with invocation logging for all kernel functions."""

    def __init__(self, **data):
        super().__init__(**data)
        auto_wrap_plugin_functions(self, self.__class__.__name__)
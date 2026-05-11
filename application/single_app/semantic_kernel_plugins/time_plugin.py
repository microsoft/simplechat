# time_plugin.py
"""Logged wrapper for the Semantic Kernel TimePlugin."""

from semantic_kernel.core_plugins.time_plugin import TimePlugin as SKTimePlugin

from semantic_kernel_plugins.plugin_invocation_logger import auto_wrap_plugin_functions


class TimePlugin(SKTimePlugin):
    """Time plugin with invocation logging for all kernel functions."""

    def __init__(self, **data):
        super().__init__(**data)
        auto_wrap_plugin_functions(self, self.__class__.__name__)
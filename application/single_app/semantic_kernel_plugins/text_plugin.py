# text_plugin.py

from semantic_kernel.core_plugins.text_plugin import TextPlugin as SKTextPlugin

from semantic_kernel_plugins.plugin_invocation_logger import auto_wrap_plugin_functions


class TextPlugin(SKTextPlugin):
    """Text plugin with invocation logging for all kernel functions."""

    def __init__(self, **data):
        super().__init__(**data)
        auto_wrap_plugin_functions(self, self.__class__.__name__)
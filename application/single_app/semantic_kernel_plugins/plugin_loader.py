# plugin_loader.py
"""Discover installed plugins without duplicating their runtime class identities."""

import importlib
import inspect
import logging
import os
from typing import Dict, Type, List

from functions_appinsights import log_event
from semantic_kernel_plugins.base_plugin import BasePlugin


PLUGIN_DIR = os.path.dirname(__file__)


def discover_plugins() -> Dict[str, Type[BasePlugin]]:
    """
    Dynamically discover all BasePlugin subclasses in the semantic_kernel_plugins directory.
    Returns a dict of {plugin_name: plugin_class}.
    Gracefully handles import errors for individual plugins.
    """
    plugins = {}
    for filename in os.listdir(PLUGIN_DIR):
        if filename.endswith('.py') and not filename.startswith('__') and filename != 'base_plugin.py' and filename != 'plugin_loader.py':
            module_name = filename[:-3]

            try:
                # Runtime guards and other loaders must see the same imported classes.
                module = importlib.import_module(f"semantic_kernel_plugins.{module_name}")

                for name, obj in inspect.getmembers(module, inspect.isclass):
                    if issubclass(obj, BasePlugin) and obj is not BasePlugin:
                        plugins[name] = obj

            except Exception as exc:
                log_event(
                    "[PLUGIN_LOADER] Plugin module could not be loaded.",
                    level=logging.WARNING,
                    extra={"plugin_name": module_name, "error_type": type(exc).__name__},
                )
                continue

    return plugins


def get_all_plugin_metadata() -> List[dict]:
    """
    Instantiate each discovered plugin and return a list of their metadata dicts.
    """
    plugins = discover_plugins()
    metadata_list = []
    for plugin_class in plugins.values():
        try:
            plugin_instance = plugin_class()
            metadata_list.append(plugin_instance.metadata)
        except Exception as e:
            continue
    return metadata_list

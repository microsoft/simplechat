import os
import importlib.util
import inspect
import logging
from typing import Dict, Type, List
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
            module_path = os.path.join(PLUGIN_DIR, filename)
            
            try:
                spec = importlib.util.spec_from_file_location(f"semantic_kernel_plugins.{module_name}", module_path)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                
                for name, obj in inspect.getmembers(module, inspect.isclass):
                    if issubclass(obj, BasePlugin) and obj is not BasePlugin:
                        plugins[name] = obj
                        
            except Exception as e:
                # Log the error but continue with other plugins
                logging.warning(f"Failed to load plugin module {module_name}: {str(e)}")
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

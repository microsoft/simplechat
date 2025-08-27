from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional

class BasePlugin(ABC):
    @property
    @abstractmethod
    def metadata(self) -> Dict[str, Any]:
        """
        Returns plugin metadata in a standard schema:
        {
            "name": str,
            "type": str,  # e.g., "function", "tool", "agent"
            "description": str,
            "methods": [
                {
                    "name": str,
                    "description": str,
                    "parameters": [
                        {"name": str, "type": str, "description": str, "required": bool}
                    ],
                    "returns": {"type": str, "description": str}
                }
            ]
        }
        """
        pass
    
    @property
    def display_name(self) -> str:
        """
        Returns the human-readable display name for this plugin.
        Override this method to provide a custom display name.
        Default implementation formats the class name.
        """
        class_name = self.__class__.__name__
        # Remove 'Plugin' suffix and format nicely
        name = class_name.replace('Plugin', '')
        
        # Handle common acronyms by keeping them together
        import re
        # Split on word boundaries while preserving acronyms
        parts = re.findall(r'[A-Z]+(?=[A-Z][a-z]|$)|[A-Z][a-z]*', name)
        
        # Join with spaces and handle underscores
        formatted = ' '.join(parts).replace('_', ' ').strip()
        return formatted if formatted else name
    
    @abstractmethod
    def __init__(self, manifest: Optional[Dict[str, Any]] = None):
        self.manifest = manifest or {}
        self._enable_logging = True  # Enable plugin invocation logging by default

    def enable_invocation_logging(self, enabled: bool = True):
        """Enable or disable plugin invocation logging for this plugin."""
        self._enable_logging = enabled

    def is_logging_enabled(self) -> bool:
        """Check if plugin invocation logging is enabled."""
        return getattr(self, '_enable_logging', True)

    def get_functions(self) -> List[str]:
        """
        Returns a list of function names this plugin exposes for registration with SK.
        Default implementation returns an empty list.
        Override this method if you want to explicitly declare exposed functions.
        """
        return []

    

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
            "displayName": str,  # Human-readable display name
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
    
    @abstractmethod
    def __init__(self, manifest: Optional[Dict[str, Any]] = None):
        self.manifest = manifest or {}

    @abstractmethod
    def get_functions(self) -> List[str]:
        """
        Returns a list of function names this plugin exposes for registration with SK.
        """
        pass

    def get_display_name(self) -> str:
        """
        Returns the display name for this plugin.
        Falls back to name if displayName is not provided.
        """
        return self.manifest.get('displayName') or self.manifest.get('name', 'Unnamed Plugin')

    def get_name(self) -> str:
        """
        Returns the internal name for this plugin.
        """
        return self.manifest.get('name', 'unnamed_plugin')

    def get_description(self) -> str:
        """
        Returns the description for this plugin.
        """
        return self.manifest.get('description', 'No description provided.')

    

from abc import ABC, abstractmethod
from typing import Dict, Any, List

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

    @abstractmethod
    def get_functions(self) -> List[str]:
        """
        Returns a list of function names this plugin exposes for registration with SK.
        """
        pass

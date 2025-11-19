from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
import re
import inspect

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
        
        # Split on word boundaries while preserving acronyms
        parts = re.findall(r'[A-Z]+(?=[A-Z][a-z]|$)|[A-Z][a-z]*', name)
        
        # Join with spaces and handle underscores
        formatted = ' '.join(parts).replace('_', ' ').strip()
        return formatted if formatted else name
    
    """
    This class provides common functionality and enforces a standard interface.
    All plugins should inherit from this base class.
    All plugins should call super().__init__(manifest) in their init constructor.
    """
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
        functions = []
        # First check unbound functions on the class where decorator attributes are set
        for name, fn in inspect.getmembers(self.__class__, predicate=inspect.isfunction):
            if getattr(fn, "is_kernel_function", False):
                functions.append(name)

        # Fallback: check bound methods on the instance (older decorators may attach to the bound method)
        if not functions:
            for name, method in inspect.getmembers(self, predicate=inspect.ismethod):
                if getattr(method, "is_kernel_function", False):
                    functions.append(name)

        # Debug print for visibility during registration
        for f in functions:
            print(f"Registering function: {f}")

        return functions

    def _collect_kernel_methods_for_metadata(self) -> List[Dict[str, str]]:
        """
        Collect methods decorated with @kernel_function by parsing the class source code.
        Falls back to gathering function names and the first line of their docstring when decorator metadata isn't available.
        """
        methods: List[Dict[str, str]] = []
        try:
            src = inspect.getsource(self.__class__)
        except Exception:
            src = None
        if src:
            # Try to find @kernel_function(...description="...") followed by the def
            regex = re.compile(r"@kernel_function\s*\(\s*[^)]*?description\s*=\s*(['\"])(.*?)\1[^)]*?\)\s*(?:\n\s*@[^\"]*?)*\n\s*def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", re.S)
            for m in regex.finditer(src):
                desc = m.group(2).strip()
                name = m.group(3).strip()
                methods.append({"name": name, "description": desc})
        # If parsing didn't find anything, fall back to introspection of methods and docstrings
        if not methods:
            for name, fn in inspect.getmembers(self.__class__, predicate=inspect.isfunction):
                # skip private/internal functions
                if name.startswith("_"):
                    continue
                doc = (fn.__doc__ or "").strip().splitlines()
                desc = doc[0] if doc else ""
                methods.append({"name": name, "description": desc})
        return methods

    

# custom_page_extension.py
"""
Trusted custom page extension contract for deployment-time SimpleChat customizations.
"""

from typing import Any, Dict, Optional


def custom_page(**metadata):
    """Attach SimpleChat custom page metadata to an extension class or factory."""
    def decorator(extension_object):
        extension_object.__simplechat_custom_page__ = metadata
        return extension_object

    return decorator


class CustomPageExtension:
    """Base class for trusted Python-backed custom pages."""

    metadata: Dict[str, Any] = {}

    def __init__(self, metadata_override: Optional[Dict[str, Any]] = None):
        if metadata_override:
            merged_metadata = dict(self.metadata or {})
            merged_metadata.update(metadata_override)
            self.metadata = merged_metadata

    def render(self, context: Dict[str, Any]):
        """Render the custom page response."""
        raise NotImplementedError("Custom page extensions must implement render(context).")

    def handle_api(self, operation: str, context: Dict[str, Any]):
        """Handle a custom page API operation."""
        raise NotImplementedError("This custom page does not expose API operations.")

    def health_check(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Return optional health details for the extension."""
        return {"healthy": True}
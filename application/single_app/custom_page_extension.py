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

    # Opt in to being shown inside the V2 interface. V2 embeds a chrome-less copy of the page in
    # a frame so its navigation rail stays visible. The host asks for that copy with
    # ``context["embed"] is True``, and the extension must then render a page without the
    # classic navigation (``{% extends "custom_page_embed_base.html" %}`` does that). An
    # extension that leaves this False is never asked, and V2 offers "Open in a new tab".
    supports_embed: bool = False

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
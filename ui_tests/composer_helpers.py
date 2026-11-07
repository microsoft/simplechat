# composer_helpers.py
"""Shared production composer disclosure helpers (version 0.261.327)."""


def open_composer_tools(page):
    """Reach the mobile tools before exercising a nested picker."""
    tools = page.get_by_role("button", name="Chat tools", exact=True)
    if tools.is_visible() and tools.get_attribute("aria-expanded") == "false":
        tools.click()

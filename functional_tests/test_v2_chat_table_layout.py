# test_v2_chat_table_layout.py
"""
Functional contracts for responsive V2 assistant tables.
Version: 0.261.425
Implemented in: 0.261.425

Pin shared rendering and scoped saved/streaming layout wiring. Real browser
geometry, content preservation and keyboard scrolling are covered in ui_tests.
"""

from pathlib import Path
import re

import pytest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "application" / "v2_ui" / "src"


def test_saved_and_streaming_bubbles_share_table_layout_without_changing_user_widths():
    source = (SOURCE / "components" / "chat" / "MessageList.tsx").read_text("utf-8")
    saved, streaming = source.split("function StreamingBubble()", 1)
    assert "!isUser && 'chat-assistant-bubble min-w-0'" in saved
    assert "'chat-assistant-bubble min-w-0'" in streaming
    assert "bubbleWidthClass(chatWidth)" in saved
    assert "bubbleWidthClass(chatWidth)" in streaming
    widths = (SOURCE / "lib" / "chatWidth.ts").read_text("utf-8")
    assert "'max-w-[min(64rem,90%)]' : 'max-w-[min(46rem,85%)]'" in widths
    assert "'max-w-none' : 'max-w-4xl'" in widths


def test_table_expansion_is_scoped_to_rendered_tables_and_cells_can_wrap():
    css = (SOURCE / "styles" / "theme.css").read_text("utf-8")
    bubble = re.search(r"\.chat-assistant-bubble:has\(\.chat-markdown-table\)\s*\{([^}]+)\}", css)
    assert bubble is not None
    assert "width: 100%;" in bubble.group(1)
    assert "max-width: 100%;" in bubble.group(1)
    cells = re.search(r"\.chat-markdown-table :is\(th, td\)\s*\{([^}]+)\}", css)
    assert cells is not None
    assert "min-width: clamp(3.5rem, 8vw, 8rem);" in cells.group(1)
    assert "overflow-wrap: anywhere;" in cells.group(1)
    assert "white-space: normal;" in cells.group(1)
    assert "table-layout: fixed" not in cells.group(1)


def test_shared_markdown_table_wrapper_preserves_safe_semantic_rendering():
    source = (SOURCE / "components" / "chat" / "AssistantMarkdown.tsx").read_text("utf-8")
    wrapper = source.split("table: ({ node: _node, ...props }) => (", 1)[1].split("td:", 1)[0]
    assert "chat-markdown-table min-w-0 max-w-full overflow-x-auto" in wrapper
    assert 'role="region"' in wrapper
    assert 'aria-label="Table"' in wrapper
    assert "tabIndex={0}" in wrapper
    assert "<table {...props} />" in wrapper
    assert "focus-visible:outline-accent" in wrapper
    assert "dangerouslySetInnerHTML" not in source
    assert "rehype-raw" not in source.split("const components =", 1)[1]
    assert "td: ({ children }) => <td>{renderTokens(children)}</td>" in source
    assert "th: ({ children }) => <th>{renderTokens(children)}</th>" in source


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))

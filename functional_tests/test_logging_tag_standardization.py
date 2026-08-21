#!/usr/bin/env python3
# test_logging_tag_standardization.py
"""
Functional test for logging tag standardization.
Version: 0.250.125
Implemented in: 0.250.125

This test ensures Python logging prefixes use `[UPPERCASE_WITH_UNDERSCORES]`
and that the logging tag reference document stays synchronized with source.
"""

import ast
import re
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"
LOGGING_TAG_DOC = REPO_ROOT / "docs" / "reference" / "logging-tags.md"

TAG_RE = re.compile(r"^\s*\[([^\]\n]{1,100})\]")
STANDARD_TAG_RE = re.compile(r"^[A-Z0-9]+(?:_[A-Z0-9]+)*$")
DOC_TAG_RE = re.compile(r"^- `\[([A-Z0-9]+(?:_[A-Z0-9]+)*)\]`$", re.MULTILINE)

LOG_FUNCTION_NAMES = {"log_event", "debug_print", "print"}
LOG_ATTRIBUTE_NAMES = {"debug", "info", "warning", "warn", "error", "exception", "critical", "log"}


class LoggingTagScanner(ast.NodeVisitor):
    """Extract bracketed tags from logging-style calls."""

    def __init__(self):
        self.assignments = {}
        self.tags = []

    def _string_value(self, node):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.JoinedStr):
            parts = []
            for value in node.values:
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    parts.append(value.value)
                elif isinstance(value, ast.FormattedValue):
                    parts.append("{}")
            return "".join(parts)
        if isinstance(node, ast.Name):
            return self.assignments.get(node.id)
        return None

    def visit_Assign(self, node):
        value = self._string_value(node.value)
        if value is not None:
            for target in node.targets:
                if isinstance(target, ast.Name):
                    self.assignments[target.id] = value
        self.generic_visit(node)

    def visit_Call(self, node):
        message_node = self._get_logging_message_node(node)
        if message_node is not None:
            message = self._string_value(message_node)
            if message is not None:
                match = TAG_RE.match(message)
                if match:
                    self.tags.append((match.group(1).strip(), node.lineno))
        self.generic_visit(node)

    def _get_logging_message_node(self, node):
        func = node.func
        if isinstance(func, ast.Name) and func.id in LOG_FUNCTION_NAMES and node.args:
            return node.args[0]
        if isinstance(func, ast.Attribute) and func.attr in LOG_ATTRIBUTE_NAMES:
            if func.attr == "log" and len(node.args) > 1:
                return node.args[1]
            if func.attr != "log" and node.args:
                return node.args[0]
        return None


def _collect_source_tags():
    source_tags = {}
    for path in APP_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        scanner = LoggingTagScanner()
        scanner.visit(tree)
        for tag, line_number in scanner.tags:
            source_tags.setdefault(tag, []).append(f"{path.relative_to(REPO_ROOT)}:{line_number}")
    return source_tags


def test_logging_tags_are_normalized_and_documented():
    """Validate source logging tags and docs inventory use the same standard tags."""
    print("Testing logging tag standardization...")

    source_tags = _collect_source_tags()
    nonstandard_tags = {
        tag: locations
        for tag, locations in source_tags.items()
        if not STANDARD_TAG_RE.fullmatch(tag)
    }
    assert not nonstandard_tags, f"Nonstandard logging tags found: {nonstandard_tags}"

    doc_source = LOGGING_TAG_DOC.read_text(encoding="utf-8")
    documented_tags = set(DOC_TAG_RE.findall(doc_source))
    actual_tags = set(source_tags)

    missing_from_docs = actual_tags - documented_tags
    stale_docs = documented_tags - actual_tags
    assert not missing_from_docs, f"Logging tags missing from docs: {sorted(missing_from_docs)}"
    assert not stale_docs, f"Stale logging tags in docs: {sorted(stale_docs)}"

    print(f"Validated {len(actual_tags)} normalized logging tags.")
    return True


if __name__ == "__main__":
    try:
        test_logging_tags_are_normalized_and_documented()
    except Exception as ex:
        print(f"Test failed: {ex}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    sys.exit(0)

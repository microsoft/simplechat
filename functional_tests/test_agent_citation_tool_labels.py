#!/usr/bin/env python3
# test_agent_citation_tool_labels.py
"""
Functional test for user-facing agent citation tool labels.
Version: 0.241.053
Implemented in: 0.241.053

This test ensures that operational agent citations use concise, human-readable
labels for maps, Simple Chat artifacts, and Teams meetings instead of raw
plugin.function names.
"""

import os
import sys
import traceback


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_ROOT = os.path.join(REPO_ROOT, "application", "single_app")
if APP_ROOT not in sys.path:
    sys.path.insert(0, APP_ROOT)

from functions_message_artifacts import build_agent_citation_tool_label


def test_agent_citation_tool_labels_are_human_readable():
    """Operational citations should expose user-facing labels."""
    print("Testing agent citation tool label formatting...")

    cases = [
        {
            "label": build_agent_citation_tool_label(
                "AzureMapsOpenLayersPlugin",
                "create_map_visualization",
                {"title": "eGuardian Map - Corridor"},
                {},
            ),
            "expected": "Map: eGuardian Map - Corridor",
        },
        {
            "label": build_agent_citation_tool_label(
                "SimpleChatPlugin",
                "create_group_conversation",
                {"title": "eGuardian Alert - Atlanta to Pittsburgh"},
                {"conversation": {"title": "ignored"}},
            ),
            "expected": "Group conversation: eGuardian Alert - Atlanta to Pittsburgh",
        },
        {
            "label": build_agent_citation_tool_label(
                "SimpleChatPlugin",
                "upload_markdown_document",
                {"file_name": "eguardian-potential-suspect-2026-04-20.md"},
                {},
            ),
            "expected": "Markdown file: eguardian-potential-suspect-2026-04-20.md",
        },
        {
            "label": build_agent_citation_tool_label(
                "MSGraphPlugin",
                "create_calendar_invite",
                {"subject": "eGuardian Briefing: Potential Suspect", "make_teams_meeting": True},
                {"teams_meeting_requested": True, "join_url": "https://teams.microsoft.com/l/meetup-join/..."},
            ),
            "expected": "Teams meeting: eGuardian Briefing: Potential Suspect",
        },
        {
            "label": build_agent_citation_tool_label(
                "UnknownPlugin",
                "run_operation",
                {},
                {},
            ),
            "expected": "UnknownPlugin.run_operation",
        },
    ]

    failures = []
    for case in cases:
        if case["label"] != case["expected"]:
            failures.append(f"Expected '{case['expected']}', got '{case['label']}'")

    if failures:
        for failure in failures:
            print(f"  FAIL: {failure}")
        raise AssertionError("Agent citation tool label formatting failed.")

    print("  Agent citation tool label formatting passed.")


if __name__ == "__main__":
    tests = [
        test_agent_citation_tool_labels_are_human_readable,
    ]
    results = []

    for test in tests:
        print(f"\n{'=' * 60}")
        print(f"Running {test.__name__}...")
        print('=' * 60)
        try:
            test()
            results.append(True)
        except Exception as exc:
            print(f"ERROR: {exc}")
            traceback.print_exc()
            results.append(False)

    passed = sum(1 for result in results if result)
    total = len(results)
    print(f"\n{'=' * 60}")
    print(f"Results: {passed}/{total} tests passed")
    print('=' * 60)
    sys.exit(0 if all(results) else 1)
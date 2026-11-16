#!/usr/bin/env python3
"""
Grep and server-parity pin for the V2 public workspace label sweep (M9A commit 5).
Version: 0.261.175
Implemented in: 0.261.175

Two guarantees keep the renameable Public Workspace surface honest:

1. Every V2 surface that shows the label routes it through the single selector
   ``lib/publicWorkspaceLabels.ts``. A re-introduced hard-coded "public workspace"
   literal in any swept file would render an admin's custom name inconsistently, so
   the code (comments excluded) of each swept file must be free of the phrase, and
   each file must import the selector.

2. The module default the selector ships (pinned literally by the companion Node
   test ``test_v2_public_workspace_labels_logic.mjs``) must equal what the real
   server ``get_public_workspace_label_context`` produces. This test executes that
   server function unchanged from ``functions_settings.py`` via the source harness,
   with no application import, and compares it to the TypeScript default parsed from
   the selector source, so the two interfaces cannot drift.
"""

import os
import re
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from test_support.app_source import run_definitions

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V2_SRC = os.path.join(REPO_ROOT, "application", "v2_ui", "src")
SELECTOR = os.path.join(V2_SRC, "lib", "publicWorkspaceLabels.ts")

# Exactly the files the commit 5 sweep routed through the selector. "Public directory" and
# "public chat" are distinct feature nouns, not label forms, so they are intentionally excluded.
SWEPT_FILES = [
    os.path.join(V2_SRC, "pages", "PublicDirectoryPage.tsx"),
    os.path.join(V2_SRC, "pages", "PublicWorkspacePage.tsx"),
    os.path.join(V2_SRC, "components", "workspace", "PublicWorkspacePicker.tsx"),
    os.path.join(V2_SRC, "components", "layout", "Sidebar.tsx"),
    os.path.join(V2_SRC, "lib", "publicWorkspaceNavigation.ts"),
    os.path.join(V2_SRC, "lib", "chatContext.ts"),
    os.path.join(V2_SRC, "lib", "chatContextHandoff.ts"),
]

LABEL_PHRASE = re.compile(r"public\s+workspace", re.IGNORECASE)


def strip_comments(source):
    """Remove block and line comments so only executable code remains for the scan."""
    without_blocks = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
    lines = []
    for line in without_blocks.splitlines():
        # Drop a trailing line comment while leaving URL schemes such as https:// intact.
        lines.append(re.sub(r"(?<!:)//.*$", "", line))
    return "\n".join(lines)


def test_swept_files_have_no_hardcoded_label_in_code():
    """No swept file carries the label phrase outside comments, and each imports the selector."""
    print("Testing that every swept file routes the label through the selector...")
    for path in SWEPT_FILES:
        assert os.path.exists(path), f"Swept file is missing: {path}"
        source = open(path, encoding="utf-8").read()

        code = strip_comments(source)
        leaked = LABEL_PHRASE.search(code)
        assert leaked is None, (
            f"{os.path.relpath(path, REPO_ROOT)} contains a hard-coded public workspace label "
            f"in code; route it through publicWorkspaceLabels instead"
        )

        assert "publicWorkspaceLabels" in source, (
            f"{os.path.relpath(path, REPO_ROOT)} must import from publicWorkspaceLabels"
        )
    print("Test passed!")
    return True


def _parse_ts_default():
    """Parse DEFAULT_PUBLIC_WORKSPACE_LABELS out of the selector source into a dict."""
    source = open(SELECTOR, encoding="utf-8").read()
    match = re.search(
        r"DEFAULT_PUBLIC_WORKSPACE_LABELS[^=]*=\s*\{(?P<body>.*?)\};",
        source,
        re.DOTALL,
    )
    assert match, "Could not locate DEFAULT_PUBLIC_WORKSPACE_LABELS in the selector source"
    body = match.group("body")

    def string_field(key):
        found = re.search(rf"{key}:\s*'([^']*)'", body)
        assert found, f"Selector default is missing a string value for {key}"
        return found.group(1)

    is_custom = re.search(r"is_custom:\s*(true|false)", body)
    max_length = re.search(r"max_length:\s*(\d+)", body)
    assert is_custom and max_length, "Selector default is missing is_custom or max_length"
    return {
        "singular": string_field("singular"),
        "plural": string_field("plural"),
        "lower_singular": string_field("lower_singular"),
        "lower_plural": string_field("lower_plural"),
        "short": string_field("short"),
        "is_custom": is_custom.group(1) == "true",
        "max_length": int(max_length.group(1)),
    }


def test_selector_default_matches_server_label_context():
    """The TS default equals the real server get_public_workspace_label_context output."""
    print("Testing selector default parity with the server label context...")
    namespace = {}
    run_definitions(
        "functions_settings.py",
        {
            "get_public_workspace_label_context",
            "normalize_public_workspace_display_name",
            "PUBLIC_WORKSPACE_DISPLAY_NAME_DEFAULT",
            "PUBLIC_WORKSPACE_DISPLAY_NAME_PLURAL_DEFAULT",
            "PUBLIC_WORKSPACE_DISPLAY_NAME_MAX_LENGTH",
        },
        namespace,
    )
    label_context = namespace["get_public_workspace_label_context"]

    server_default = label_context({})
    ts_default = _parse_ts_default()
    assert server_default == ts_default, (
        f"Selector default {ts_default} drifted from server default {server_default}"
    )

    # The block the selector round-trips when an admin renames the surface.
    custom = label_context({"public_workspace_display_name": "Community Hub"})
    assert custom == {
        "singular": "Community Hub",
        "plural": "Community Hub",
        "lower_singular": "Community Hub",
        "lower_plural": "Community Hub",
        "short": "Community Hub",
        "is_custom": True,
        "max_length": 32,
    }, f"Server custom label context changed shape: {custom}"
    print("Test passed!")
    return True


if __name__ == "__main__":
    tests = [
        test_swept_files_have_no_hardcoded_label_in_code,
        test_selector_default_matches_server_label_context,
    ]
    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            results.append(test())
        except Exception as error:
            print(f"Test failed: {error}")
            import traceback

            traceback.print_exc()
            results.append(False)
    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)

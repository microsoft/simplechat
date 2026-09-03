#!/usr/bin/env python3
"""
Functional test for web search documentation accuracy.
Version: 0.261.003
Implemented in: 0.261.003

The web search documentation described a direct Bing Web Search API
integration that was removed in v0.229.001. The implemented path is an Azure
AI Foundry agent carrying the Grounding with Bing Search tool.

The documentation also understated the egress boundary that v0.241.022
deliberately hardened: only the user's current chat message is sent to the
external search service. That is a privacy claim readers act on, so this test
ties it to the implementation. If build_web_search_query_text ever starts
folding in conversation history again, this test fails and forces the
documentation to be corrected with it, rather than leaving a false assurance
published.

This test ensures that:

  - The web search guide states the egress boundary explicitly.
  - The guide and its companion summaries describe the Foundry agent path.
  - No documentation page still claims web search calls Bing directly.
  - The query builder in the application still sends only the current message.
"""

import io
import os
import re
import sys
from pathlib import Path

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from test_support.versioning import assert_app_version_at_least

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCS_ROOT = REPO_ROOT / "docs"
GUIDE = DOCS_ROOT / "guides" / "use-web-search.md"
CHAT_ROUTES = REPO_ROOT / "application" / "single_app" / "route_backend_chats.py"

COMPANION_PAGES = (
    DOCS_ROOT / "guides" / "index.md",
    DOCS_ROOT / "features.md",
    DOCS_ROOT / "reference" / "chat-controls.md",
    DOCS_ROOT / "admin" / "knowledge.md",
)

# Wording that describes the retired direct-API integration rather than the
# Foundry agent that actually runs the search.
STALE_PHRASES = (
    "turns on Bing web search",
    "Bing Web Search API",
    "Bing-backed web search",
    "sent to Bing web search",
)

# Names that would indicate history leaking back into the outbound query.
HISTORY_IDENTIFIERS = (
    "conversation",
    "history",
    "messages",
    "summary",
    "summarize",
    "context",
    "previous",
    "prior",
)


def read_text(path):
    """Read a documentation or source file."""
    return io.open(path, encoding="utf-8", errors="ignore").read()


def test_guide_documents_egress_boundary():
    """The guide must state what does and does not leave the application."""
    print("Checking the web search guide documents the egress boundary...")

    text = read_text(GUIDE)
    problems = []

    if "## What leaves SimpleChat" not in text:
        problems.append("no 'What leaves SimpleChat' section")

    if not re.search(r"only the (current )?message you just typed|current user message alone",
                     text, re.IGNORECASE):
        problems.append("does not state that only the current message is sent")

    # The value of the section is the explicit exclusion list, not the summary.
    for excluded in ("Earlier messages", "workspaces", "attached", "System prompts"):
        if excluded.lower() not in text.lower():
            problems.append(f"exclusion list does not mention {excluded!r}")

    if "compliance boundary" not in text.lower():
        problems.append("does not carry the Grounding with Bing Search compliance notice")

    if "Deep Research" not in text:
        problems.append("does not explain the Deep Research multi-query nuance")

    if problems:
        print(f"  {GUIDE.relative_to(REPO_ROOT).as_posix()} has {len(problems)} problem(s):")
        for problem in problems:
            print(f"    {problem}")
        return False

    print("  The guide documents the egress boundary, exclusions, and compliance notice.")
    return True


def test_documentation_describes_foundry_agent_path():
    """Documentation must describe the Foundry agent rather than a direct Bing call."""
    print("Checking documentation describes the Foundry agent path...")

    guide_text = read_text(GUIDE)
    problems = []

    if "Azure AI Foundry" not in guide_text:
        problems.append(f"{GUIDE.name}: does not name Azure AI Foundry")
    if "Grounding with Bing Search" not in guide_text:
        problems.append(f"{GUIDE.name}: does not name Grounding with Bing Search")

    for page in (GUIDE,) + COMPANION_PAGES:
        if not page.exists():
            continue
        text = read_text(page)
        for phrase in STALE_PHRASES:
            if phrase.lower() in text.lower():
                relative = page.relative_to(REPO_ROOT).as_posix()
                problems.append(f"{relative}: still says {phrase!r}")

    if problems:
        print(f"  {len(problems)} problem(s):")
        for problem in problems:
            print(f"    {problem}")
        print("  The direct Bing Web Search API was removed in v0.229.001. Web "
              "search runs through a configured Azure AI Foundry agent.")
        return False

    print("  Guide and companion pages describe the Foundry agent path.")
    return True


def test_query_builder_sends_only_current_message():
    """The outbound query must still be derived from the current message alone."""
    print("Checking the web search query builder still sends only the current message...")

    source = read_text(CHAT_ROUTES)
    match = re.search(
        r"^def build_web_search_query_text\(([^)]*)\):\n(.*?)(?=^\S)",
        source,
        re.MULTILINE | re.DOTALL,
    )

    if not match:
        print("  Could not find build_web_search_query_text in route_backend_chats.py.")
        print("  The documented egress boundary can no longer be verified.")
        return False

    parameters = [item.strip() for item in match.group(1).split(",") if item.strip()]
    body = match.group(2)
    # The docstring describes the boundary in prose; only executable lines matter.
    code = re.sub(r'""".*?"""', "", body, flags=re.DOTALL)

    problems = []

    if parameters != ["user_message"]:
        problems.append(
            f"takes {parameters} instead of only 'user_message', so it can now "
            "see more than the current message"
        )

    for identifier in HISTORY_IDENTIFIERS:
        if re.search(rf"\b{identifier}\w*", code, re.IGNORECASE):
            problems.append(f"body references {identifier!r}")

    if problems:
        print(f"  {len(problems)} problem(s) in build_web_search_query_text:")
        for problem in problems:
            print(f"    {problem}")
        print("  docs/guides/use-web-search.md promises readers that only the "
              "current message leaves the application. Either restore that "
              "behavior or update the guide, the chat control reference, and "
              "the admin notice copy together.")
        return False

    print("  build_web_search_query_text still derives the query from the current message alone.")
    return True


if __name__ == "__main__":
    assert_app_version_at_least("0.261.003")

    tests = [
        test_guide_documents_egress_boundary,
        test_documentation_describes_foundry_agent_path,
        test_query_builder_sends_only_current_message,
    ]

    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            results.append(test())
        except Exception as error:  # noqa: BLE001 - report and continue
            print(f"Test raised an exception: {error}")
            import traceback
            traceback.print_exc()
            results.append(False)

    print(f"\nResults: {sum(1 for r in results if r)}/{len(results)} checks passed")
    sys.exit(0 if all(results) else 1)

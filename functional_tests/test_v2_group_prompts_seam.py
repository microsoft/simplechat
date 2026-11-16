# test_v2_group_prompts_seam.py
"""
Functional test for the scope-aware V2 group prompts seam.
Version: 0.261.136
Implemented in: 0.261.136

The behavioural coverage lives in the browser suite ``ui_tests/test_v2_group_prompts.py``.
This file pins the parts that are only observable in the source, so a refactor that quietly
re-routes a scope cannot pass unnoticed:

**Scope lives in one seam.** Group behaviour is confined to ``lib/promptWorkbench.ts``. If that
module ever names the personal ``/api/prompts`` route as a string literal, the fork this
programme spent M9B avoiding has crept back in. The personal adapter must delegate to
``workspaceApi`` rather than re-implement the personal routes.

**The group routes are the immutable family.** Every group URL the adapter builds must be an
``/api/groups/<id>/prompts`` path, with ``encodeURIComponent`` applied to both ids so a crafted
group or prompt id cannot escape the path.

**Saving from chat stays personal.** The chat composer and the message action both offer
"Save as prompt". Both must call ``workspaceApi.createPrompt`` so a prompt saved while a group
workspace is active is still written to the member's own prompts, never the shared group.

**No client-side authorization fallback.** The group gate must refuse when the ``prompt_management``
hint is absent or malformed, exactly as the documents seam does, rather than enabling writes.
"""

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
V2_SRC = REPO_ROOT / "application" / "v2_ui" / "src"
WORKBENCH = V2_SRC / "lib" / "promptWorkbench.ts"
COMPOSER = V2_SRC / "components" / "chat" / "Composer.tsx"
MESSAGE_ACTIONS = V2_SRC / "components" / "chat" / "MessageActions.tsx"

sys.path.insert(0, str(REPO_ROOT / "functional_tests"))

from test_support.versioning import assert_app_version_at_least  # noqa: E402


def read(path):
    return path.read_text(encoding="utf-8")


def strip_comments(source):
    """Remove block and line comments so a route named only in prose does not count."""
    without_block = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
    return re.sub(r"//[^\n]*", "", without_block)


def test_version_is_at_least_the_implementing_release():
    assert_app_version_at_least("0.261.136")


def test_seam_never_names_the_personal_prompts_route():
    source = strip_comments(read(WORKBENCH))
    assert "/api/prompts" not in source, (
        "promptWorkbench.ts must delegate personal writes to workspaceApi, not name /api/prompts."
    )


def test_personal_adapter_delegates_to_workspace_api():
    source = read(WORKBENCH)
    assert "from './workspaceApi'" in source, (
        "The personal adapter must delegate to the existing workspaceApi personal functions."
    )
    for delegate in (
        "fetchPersonalPrompts", "createPersonalPrompt", "updatePersonalPrompt", "deletePersonalPrompt",
    ):
        assert delegate in source, f"Personal adapter must delegate through {delegate}."


def test_group_urls_are_the_immutable_family_and_are_encoded():
    source = read(WORKBENCH)
    assert "`/api/groups/${encodeURIComponent(requireWorkspaceId(groupId))}/prompts`" in source, (
        "Group prompt URLs must build the /api/groups/<id>/prompts family with an encoded id."
    )
    assert "encodeURIComponent(requireWorkspaceId(promptId))" in source, (
        "The prompt id segment must also be percent-encoded."
    )


def test_conditional_writes_send_expected_etag():
    source = read(WORKBENCH)
    assert "expected_etag" in source, "Group PATCH and DELETE must carry expected_etag."
    assert "PromptConflictError" in source, "A 409 must become a conflict the workbench can keep the draft for."


def test_no_client_side_authorization_fallback():
    source = read(WORKBENCH)
    # The gate refuses on a missing or malformed hint by returning the empty set, exactly like
    # the documents seam. A change that defaulted to the full set would be an authz bypass.
    assert "return new Set();" in source, (
        "advertisedPromptOperations must yield the empty set for an unrecognised hint."
    )


def test_saving_from_chat_stays_personal():
    for path in (COMPOSER, MESSAGE_ACTIONS):
        source = read(path)
        assert "import { createPrompt } from '../../lib/workspaceApi';" in source, (
            f"{path.name} must import createPrompt from workspaceApi so chat saves stay personal."
        )
        assert "createGroupPromptWorkbench" not in source, (
            f"{path.name} must not route a chat save through the group workbench."
        )
    composer = read(COMPOSER)
    # The save-as-prompt draft is stamped personal, never group.
    assert re.search(r"scope_type:\s*'personal'", composer), (
        "The composer's saved prompt must be stamped as a personal prompt."
    )


if __name__ == "__main__":
    failures = 0
    for name, function in sorted(globals().items()):
        if name.startswith("test_") and callable(function):
            try:
                function()
                print(f"PASS {name}")
            except Exception as error:  # noqa: BLE001
                failures += 1
                print(f"FAIL {name}: {error}")
    sys.exit(1 if failures else 0)

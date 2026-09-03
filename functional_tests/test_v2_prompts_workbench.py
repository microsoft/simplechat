#!/usr/bin/env python3
"""
Functional test for the V2 prompts workbench.

Version: 0.261.050
Implemented in: 0.261.050

The behavioural half of the front end lives in ``test_v2_prompts_workbench_logic.ts``, run from
here. This file covers the parts that are only observable in the source, plus the new
server-side helpers, which are executed directly rather than asserted about.

What it pins:

**One validator, three blueprints.** The personal, group and public prompt routes each had
their own copy of the same name/content checks. Adding ``description`` and ``is_favorite`` to
one copy and not the others would produce a field that saves on a personal prompt and is
silently dropped on a group one, which reads to a user as a save that did not work. All three
must call ``build_prompt_updates``.

**Writes must return the same shape.** The client applies a create and an update optimistically
to the same list. A create that omits a field the update returns would make a newly created
prompt render differently from the same prompt one edit later.

**The search parameter must be the one the route reads.** ``fetchPrompts`` sent ``search_term``
while ``list_prompts`` reads ``search``, so server-side search had never once run.

**Picking a prompt must not replace the composer.** ``setText(prompt.content)`` discarded
whatever had been typed. The composer must insert instead.

**Nothing may be pre-filled in a shared conversation.** A value remembered from a private chat,
auto-filled into a collaborative conversation, becomes visible to every participant on send.

**Variable values must not reach the server.** The memory module is deliberately localStorage
only; an import of the API client or a user-settings key would defeat that.

**The section must be registered as full-bleed.** A three-pane layout inside the page's centred
prose container gets a second scrollbar and a squeezed list.
"""

import ast
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = REPO_ROOT / "application" / "single_app"
V2_DIR = REPO_ROOT / "application" / "v2_ui"
V2_SRC = V2_DIR / "src"

sys.path.insert(0, str(REPO_ROOT / "functional_tests"))

from test_support.versioning import assert_app_version_at_least  # noqa: E402

PROMPTS_FUNCTIONS = APP_DIR / "functions_prompts.py"
PERSONAL_ROUTE = APP_DIR / "route_backend_prompts.py"
GROUP_ROUTE = APP_DIR / "route_backend_group_prompts.py"
PUBLIC_ROUTE = APP_DIR / "route_backend_public_prompts.py"
CHATS_FRONTEND = APP_DIR / "route_frontend_chats.py"

WORKSPACE_API_TS = V2_SRC / "lib" / "workspaceApi.ts"
PROMPT_VARIABLES_TS = V2_SRC / "lib" / "promptVariables.ts"
PROMPT_MEMORY_TS = V2_SRC / "lib" / "promptVariableMemory.ts"
PROMPT_SLASH_TS = V2_SRC / "lib" / "promptSlash.ts"
PROMPT_LIBRARY_TS = V2_SRC / "lib" / "promptLibrary.ts"
TYPES_TS = V2_SRC / "lib" / "types.ts"
SECTIONS_TSX = V2_SRC / "pages" / "workspace" / "sections.tsx"
PROMPTS_SECTION_TSX = V2_SRC / "pages" / "workspace" / "PromptsSection.tsx"
WORKBENCH_TSX = V2_SRC / "components" / "prompts" / "PromptWorkbench.tsx"
LIST_TSX = V2_SRC / "components" / "prompts" / "PromptList.tsx"
DETAILS_TSX = V2_SRC / "components" / "prompts" / "PromptDetailsPane.tsx"
EDITOR_TSX = V2_SRC / "components" / "prompts" / "PromptEditorDialog.tsx"
VARIABLES_TSX = V2_SRC / "components" / "prompts" / "PromptVariablesDialog.tsx"
PRESENTATION_TSX = V2_SRC / "components" / "prompts" / "promptPresentation.tsx"
SLASH_MENU_TSX = V2_SRC / "components" / "chat" / "PromptSlashMenu.tsx"
COMPOSER_TSX = V2_SRC / "components" / "chat" / "Composer.tsx"
MESSAGE_ACTIONS_TSX = V2_SRC / "components" / "chat" / "MessageActions.tsx"
BOOTSTRAP_STORE_TS = V2_SRC / "stores" / "bootstrapStore.ts"
MODAL_TSX = V2_SRC / "components" / "ui" / "Modal.tsx"
PLAIN_MARKDOWN_TSX = V2_SRC / "components" / "ui" / "PlainMarkdown.tsx"

LOGIC_CHECK_TS = REPO_ROOT / "functional_tests" / "test_v2_prompts_workbench_logic.ts"

# Every prompt route that writes, with the flag it is gated on. The guards are what a new
# field must not be allowed to quietly skip past.
PROMPT_WRITE_ROUTES = [
    (PERSONAL_ROUTE, "/api/prompts", "POST", "enable_user_workspace"),
    (PERSONAL_ROUTE, "/api/prompts/<prompt_id>", "PATCH", "enable_user_workspace"),
    (GROUP_ROUTE, "/api/group_prompts", "POST", "enable_group_workspaces"),
    (GROUP_ROUTE, "/api/group_prompts/<prompt_id>", "PATCH", "enable_group_workspaces"),
    (PUBLIC_ROUTE, "/api/public_prompts", "POST", "enable_public_workspaces"),
    (PUBLIC_ROUTE, "/api/public_prompts/<prompt_id>", "PATCH", "enable_public_workspaces"),
]

NEW_PROMPT_FIELDS = ["description", "is_favorite"]


def _read(path):
    return path.read_text(encoding="utf-8")


def _load_module_functions(path, names):
    """Execute selected top-level functions from a module without importing it.

    ``functions_prompts`` imports ``config``, which builds Azure clients at import time and
    cannot run without credentials. The helpers under test depend on nothing but the standard
    library, so the module is parsed and only those definitions -- plus the module-level
    constants they close over -- are executed.
    """
    tree = ast.parse(_read(path))
    wanted = set(names)

    def is_constant_assignment(node):
        return isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id.isupper()
            for target in node.targets
        )

    namespace = {
        "datetime": datetime,
        "timedelta": timedelta,
        "timezone": timezone,
    }

    # Constants are executed one at a time and failures skipped: the module also defines
    # constants built from imports this extraction deliberately does not provide.
    for node in tree.body:
        if not is_constant_assignment(node):
            continue
        try:
            exec(
                compile(ast.Module(body=[node], type_ignores=[]), str(path), "exec"),
                namespace,
            )
        except Exception:  # noqa: BLE001
            continue

    definitions = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in wanted
    ]
    try:
        exec(
            compile(ast.Module(body=definitions, type_ignores=[]), str(path), "exec"),
            namespace,
        )
    except Exception as error:  # noqa: BLE001
        raise AssertionError(
            f"Could not execute the extracted helpers from {path.name}: {error}"
        ) from error

    missing = wanted - set(namespace)
    assert not missing, f"Could not extract {missing} from {path.name}"
    return namespace


def test_version_is_at_least_the_implementing_release():
    print("Testing version...")
    assert_app_version_at_least("0.261.050")
    print("  ok  version is at or beyond the implementing release")
    return True


def test_prompt_update_validation_is_shared_by_every_blueprint():
    """Three copies of the same checks is how the three scopes drift apart."""
    print("Testing shared prompt validation...")

    for route in (PERSONAL_ROUTE, GROUP_ROUTE, PUBLIC_ROUTE):
        source = _read(route)
        assert "build_prompt_updates(data)" in source, (
            f"{route.name} must validate through build_prompt_updates, or a field accepted on "
            "one scope will be silently dropped on another"
        )
        assert "build_prompt_create_options(data)" in source, (
            f"{route.name} must read the optional create fields through the shared helper"
        )
        # The hand-rolled checks these replaced must be gone, not merely bypassed.
        assert "Invalid 'name' provided" not in source, (
            f"{route.name} still carries its own name validation"
        )
        assert "updates['content'] = data['content']" not in source
        assert 'updates["content"] = data["content"]' not in source, (
            f"{route.name} still carries its own content validation"
        )

    print("  ok  all three prompt blueprints share one validator")
    return True


def test_prompt_validation_behaviour():
    """Execute the validator rather than asserting about its source."""
    print("Testing prompt validation behaviour...")

    helpers = _load_module_functions(
        PROMPTS_FUNCTIONS,
        [
            "normalize_prompt_description",
            "serialize_prompt_summary",
            "build_prompt_updates",
            "build_prompt_create_options",
        ],
    )
    build_updates = helpers["build_prompt_updates"]
    build_create = helpers["build_prompt_create_options"]
    normalize = helpers["normalize_prompt_description"]
    summarize = helpers["serialize_prompt_summary"]

    updates, error = build_updates({"name": "  Weekly  ", "description": "  note  "})
    assert error is None, error
    assert updates == {"name": "Weekly", "description": "note"}, updates

    assert build_updates({})[1] == "No fields provided for update"
    assert build_updates({"name": "   "})[1] == "Invalid 'name' provided"
    assert build_updates({"name": 5})[1] == "Invalid 'name' provided"
    assert build_updates({"content": 5})[1] == "Invalid 'content' provided"
    assert build_updates({"description": 5})[1] == "Invalid 'description' provided"

    # A bool is required rather than anything truthy: "false" and 0 are both things a client
    # sends by accident, and both would otherwise be stored as-is and read back as truthy.
    assert build_updates({"is_favorite": "yes"})[1] == "Invalid 'is_favorite' provided"
    assert build_updates({"is_favorite": 1})[1] == "Invalid 'is_favorite' provided"
    assert build_updates({"is_favorite": False}) == ({"is_favorite": False}, None)

    # None clears the description, which is what the editor sends for an emptied field.
    assert build_updates({"description": None}) == ({"description": ""}, None)

    # An empty content string is a legitimate update, and must not be mistaken for "no fields".
    assert build_updates({"content": ""}) == ({"content": ""}, None)

    assert len(normalize("x" * 500)) == 200, "the description must be capped"
    assert normalize(None) == ""

    assert build_create({}) == ({"description": "", "is_favorite": False}, None)
    assert build_create({"description": 5})[1] == "Invalid 'description' provided"
    assert build_create({"name": "ignored"}) == (
        {"description": "", "is_favorite": False},
        None,
    ), "the create helper must consider only the optional fields"

    # Old documents carry neither new field, and neither does one last saved by the classic
    # interface. Reading them must not raise or report None.
    legacy = summarize({"id": "1", "name": "Old", "updated_at": "t"})
    assert legacy["description"] == ""
    assert legacy["is_favorite"] is False
    assert legacy["created_at"] is None

    print("  ok  the validator accepts, rejects and normalises correctly")
    return True


def test_creates_and_updates_return_the_same_shape():
    """The client applies both optimistically to one list."""
    print("Testing write response shape...")

    source = _read(PROMPTS_FUNCTIONS)
    for function in ("create_prompt_doc", "update_prompt_doc"):
        body = re.search(rf"def {function}\(.*?(?=\ndef |\Z)", source, re.DOTALL)
        assert body, f"Could not find {function}"
        assert "serialize_prompt_summary(" in body.group(0), (
            f"{function} must return serialize_prompt_summary(...), so a create and an edit "
            "cannot report different fields for the same prompt"
        )

    assert "def create_prompt_doc(" in source
    signature = re.search(r"def create_prompt_doc\((.*?)\):", source, re.DOTALL)
    assert signature, "Could not read the create_prompt_doc signature"
    for field in NEW_PROMPT_FIELDS:
        assert field in signature.group(1), (
            f"create_prompt_doc must accept {field}, or a prompt created with one loses it"
        )

    print("  ok  creates and updates report the same fields")
    return True


def test_prompt_write_routes_carry_their_guards():
    """A new field must not arrive alongside a weakened route."""
    print("Testing route guards...")

    for path, url, method, flag in PROMPT_WRITE_ROUTES:
        source = _read(path)
        pattern = re.compile(
            r"@bp\.route\(\s*'" + re.escape(url) + r"'\s*,\s*methods=\['" + method + r"'\]\s*\)"
            r"(?P<decorators>(?:\s*@[^\n]+\n)+)\s*def\s+(?P<name>\w+)",
        )
        match = pattern.search(source)
        assert match, f"Could not find the {method} {url} route in {path.name}"

        decorators = match.group("decorators")
        assert "@swagger_route(security=get_auth_security())" in decorators, (
            f"{method} {url} must carry @swagger_route"
        )
        assert "@login_required" in decorators, f"{method} {url} must carry @login_required"
        assert "@user_required" in decorators, f"{method} {url} must carry @user_required"
        assert f'@enabled_required("{flag}")' in decorators or (
            f"@enabled_required('{flag}')" in decorators
        ), f"{method} {url} must be gated on {flag}"

        # Ordering matters: swagger_route documents the route and must wrap the auth
        # decorators rather than sit inside them.
        lines = [line.strip() for line in decorators.strip().splitlines() if line.strip()]
        assert lines[0].startswith("@swagger_route"), (
            f"{method} {url} must place @swagger_route first, before the auth decorators"
        )

    print(f"  ok  all {len(PROMPT_WRITE_ROUTES)} prompt write routes carry their guards")
    return True


def test_the_chat_catalog_carries_the_new_fields():
    """The composer picker and the slash menu sort and label from these."""
    print("Testing chat prompt catalog...")

    source = _read(CHATS_FRONTEND)
    block = re.search(
        r"def _serialize_chat_prompt_option\(.*?\n    \}",
        source,
        re.DOTALL,
    )
    assert block, "Could not find _serialize_chat_prompt_option"
    for field in NEW_PROMPT_FIELDS:
        assert f"'{field}'" in block.group(0), (
            f"{field} must reach the chat catalog, or the composer cannot show or sort by it"
        )
    assert "prompt.get('description', '') or ''" in block.group(0), (
        "the description must be read defensively; prompts predating the field have none"
    )

    print("  ok  the chat catalog carries description and is_favorite")
    return True


def test_the_search_parameter_matches_what_the_route_reads():
    """It did not, so server-side prompt search had never once run."""
    print("Testing search parameter...")

    api = _read(WORKSPACE_API_TS)
    assert "params.set('search'," in api, (
        "fetchPrompts must send `search`, which is what list_prompts reads"
    )
    assert "params.set('search_term'" not in api, (
        "`search_term` is not a parameter any prompt route looks for"
    )

    functions = _read(PROMPTS_FUNCTIONS)
    assert "args.get('search')" in functions, (
        "list_prompts is expected to read `search`; if that changed, fetchPrompts must follow"
    )

    print("  ok  the client and the route agree on the search parameter")
    return True


def test_the_section_is_registered_full_bleed():
    """A two-pane layout inside the prose container gets a second scrollbar."""
    print("Testing section registration...")

    sections = _read(SECTIONS_TSX)
    prompts_entry = re.search(r"\{\s*id: 'prompts',.*?\n    \},", sections, re.DOTALL)
    assert prompts_entry, "Could not find the prompts section entry"
    assert "layout: 'full'" in prompts_entry.group(0), (
        "the prompts section must claim the full page, like the documents explorer"
    )

    section = _read(PROMPTS_SECTION_TSX)
    assert "PromptWorkbench" in section, "the section must render the workbench"
    # The inline editor this replaced is the whole point of the change.
    assert "<textarea" not in section, (
        "the section must not render its own editor above the list again"
    )

    print("  ok  prompts is registered as a full-bleed section")
    return True


def test_picking_a_prompt_does_not_replace_the_composer():
    """setText(prompt.content) discarded whatever had already been written."""
    print("Testing composer insertion...")

    composer = _read(COMPOSER_TSX)
    assert "setText(String(prompt.content))" not in composer, (
        "picking a prompt must not replace the composer's contents"
    )
    assert "insertPromptText(" in composer, "insertion must go through insertPromptText"
    assert "promptNeedsFilling(" in composer, (
        "a prompt with variables must open the fill-in dialog rather than inserting raw braces"
    )
    assert "readSlashQuery(" in composer, "the `/` menu must be wired to the composer"
    assert "PromptSlashMenu" in composer
    assert "saveWrittenTextAsPrompt" in composer, (
        "drafted composer text must be saveable as a prompt"
    )
    assert "readPromptParam(" in composer, (
        "the /chat?prompt=<id> handoff from the workbench must be consumed"
    )

    print("  ok  the composer inserts rather than replaces")
    return True


def test_nothing_is_prefilled_in_a_shared_conversation():
    """A remembered value would become visible to every participant on send."""
    print("Testing shared-conversation pre-fill...")

    composer = _read(COMPOSER_TSX)
    assert "shared={shared}" in composer, (
        "the fill-in dialog must be told whether this is a shared conversation"
    )

    dialog = _read(VARIABLES_TSX)
    assert "shared = false" in dialog, "the dialog must default to the safe case"
    assert "if (!shared)" in dialog, (
        "remembered values must be applied only when the conversation is not shared"
    )
    # The pre-filled badge is what keeps an auto-filled value from reading as typed.
    assert "Reused" in dialog and "From this chat" in dialog, (
        "an auto-filled value must be visibly distinct from one the reader typed"
    )
    assert "onSubmit(content)" in dialog, (
        "a prompt with nothing to ask must not present an empty dialog"
    )

    print("  ok  nothing is pre-filled in a shared conversation")
    return True


def test_variable_values_never_reach_the_server():
    """Free-text values are kept in the browser deliberately."""
    print("Testing variable value storage...")

    memory = _read(PROMPT_MEMORY_TS)
    assert "localStorage" in memory
    for forbidden in ("apiClient", "workspaceApi", "userSettings", "fetch("):
        assert forbidden not in memory, (
            f"promptVariableMemory must not reference {forbidden}: remembered values are "
            "deliberately client-only, because people paste secrets and personal data into them"
        )
    assert "looksLikeSecret" in memory, "obvious secret shapes must not be persisted"
    assert "forgetPromptValues" in memory and "forgetAllPromptValues" in memory, (
        "the reader must be able to remove what was remembered"
    )

    details = _read(DETAILS_TSX)
    assert "Forget saved values" in details, (
        "the workbench must surface a way to forget remembered values"
    )

    # And the key must not have crept into the settings whitelist.
    settings = _read(V2_SRC / "lib" / "userSettings.ts")
    assert "prompt-vars" not in settings and "promptVariable" not in settings, (
        "remembered variable values must not be a synced user setting"
    )

    print("  ok  remembered values stay in the browser")
    return True


def test_the_message_action_says_what_it_does():
    """"Use as prompt" only ever copied text into the composer."""
    print("Testing message actions...")

    actions = _read(MESSAGE_ACTIONS_TSX)
    assert "'Use as prompt'" not in actions, (
        "the entry that fills the composer must not claim to make a prompt"
    )
    assert "'Copy to composer'" in actions, "the copy entry must say what it does"
    assert "'Save as prompt'" in actions, "saving a message as a prompt must be offered"
    assert "PromptEditorDialog" in actions, (
        "saving must open the editor prefilled, so the name and any variables can be set"
    )
    assert "suggestPromptName(" in actions, "a name should be suggested from the message"

    print("  ok  the message actions are named for what they do")
    return True


def test_a_prompt_saved_from_chat_is_immediately_usable():
    """The picker reads a server-built catalog that is cached."""
    print("Testing catalog freshness...")

    store = _read(BOOTSTRAP_STORE_TS)
    assert "upsertPromptInCatalog" in store, (
        "the catalog needs a local upsert, or a prompt saved from chat is not selectable "
        "until the bootstrap refetch lands"
    )

    for path in (COMPOSER_TSX, MESSAGE_ACTIONS_TSX):
        source = _read(path)
        assert "upsertPromptInCatalog(" in source, f"{path.name} must apply the new prompt locally"
        assert "refreshBootstrap()" in source, (
            f"{path.name} must also refetch, so the local guess is replaced by the server's record"
        )

    functions = _read(PROMPTS_FUNCTIONS)
    assert "_invalidate_prompt_chat_bootstrap_cache" in functions, (
        "the server-side catalog cache must still be invalidated on every prompt write"
    )

    print("  ok  a prompt saved from chat is immediately selectable")
    return True


def test_shared_ui_is_not_duplicated():
    """A second copy of a dialog shell is how two dialogs behave differently."""
    print("Testing shared UI promotion...")

    assert MODAL_TSX.exists(), "the dialog shell must live in components/ui"
    assert PLAIN_MARKDOWN_TSX.exists(), "the plain markdown renderer must live in components/ui"

    dialogs = _read(V2_SRC / "components" / "documents" / "DocumentDialogs.tsx")
    assert "from '../ui/Modal'" in dialogs, (
        "the documents dialogs must use the shared shell rather than their own copy"
    )
    assert "export function Modal(" not in dialogs, "the old copy must be gone"

    admin_markdown = _read(V2_SRC / "components" / "admin" / "AdminMarkdown.tsx")
    assert "from '../ui/PlainMarkdown'" in admin_markdown

    # The preview must go through the renderer that does not enable raw HTML.
    for path in (DETAILS_TSX, EDITOR_TSX):
        source = _read(path)
        assert "PlainMarkdown" in source, f"{path.name} must render through PlainMarkdown"
        assert "AssistantMarkdown" not in source, (
            f"{path.name} must not use the assistant renderer, which parses citations and "
            "masking that do not apply to a prompt"
        )

    plain = _read(PLAIN_MARKDOWN_TSX)
    assert "from 'rehype-raw'" not in plain and "rehypeRaw]" not in plain, (
        "raw HTML must stay disabled, so authored markdown cannot inject script"
    )

    print("  ok  the dialog shell and markdown renderer are shared, not copied")
    return True


def test_a_classic_save_does_not_wipe_the_new_fields():
    """The classic prompt modal PATCHes only name and content."""
    print("Testing classic interface compatibility...")

    source = _read(PROMPTS_FUNCTIONS)
    merge = re.search(
        r"def update_prompt_doc\(.*?for k, v in updates\.items\(\):\s*\n\s*item\[k\] = v",
        source,
        re.DOTALL,
    )
    assert merge, (
        "update_prompt_doc must merge the validated updates into the stored item. Replacing "
        "the document wholesale would drop description and is_favorite every time the classic "
        "interface saved a prompt, because its modal sends only name and content"
    )

    # And prove the composition: a classic-shaped PATCH over a document that already carries
    # the new fields must leave them intact.
    helpers = _load_module_functions(
        PROMPTS_FUNCTIONS,
        ["normalize_prompt_description", "serialize_prompt_summary", "build_prompt_updates"],
    )
    stored = {
        "id": "p1",
        "name": "Old name",
        "content": "old body",
        "description": "kept",
        "is_favorite": True,
        "updated_at": "t0",
    }
    updates, error = helpers["build_prompt_updates"]({"name": "New", "content": "new body"})
    assert error is None, error
    for key, value in updates.items():
        stored[key] = value

    summary = helpers["serialize_prompt_summary"](stored)
    assert summary["description"] == "kept", "a classic save must not clear the description"
    assert summary["is_favorite"] is True, "a classic save must not clear the favourite flag"
    assert summary["name"] == "New"

    print("  ok  a classic save preserves description and is_favorite")
    return True


def test_the_prompt_handoff_has_a_single_url_writer():
    """Two writers means the parameter one removes, the other restores."""
    print("Testing prompt handoff URL ownership...")

    composer = _strip_comments(_read(COMPOSER_TSX))
    assert "setSearchParams" not in composer, (
        "the composer must not write the chat query string. ChatPage owns it, and "
        "setSearchParams replaces the whole query from the caller's render snapshot, so a "
        "parameter deleted here is restored by ChatPage's effect in the same commit -- leaving "
        "a URL that re-inserts the prompt on every reload"
    )
    assert "useState(() => readPromptParam(searchParams))" in composer, (
        "the id must be captured during the first render, before the sync effect strips it"
    )

    conversation_url = _strip_comments(_read(V2_SRC / "lib" / "conversationUrl.ts"))
    assert "next.delete(PROMPT_PARAM)" in conversation_url, (
        "the single URL writer must strip the prompt parameter"
    )
    assert "hasPrompt" in conversation_url, (
        "a lone prompt parameter must count as a difference, or it is never stripped"
    )

    print("  ok  one writer owns the chat query string")
    return True


def test_the_dialog_escapes_the_hover_reveal_wrapper():
    """A message's action row sits at opacity-0 until hovered or focused."""
    print("Testing modal portalling...")

    modal = _read(MODAL_TSX)
    assert "createPortal(" in modal, (
        "the dialog must portal to the body. `position: fixed` escapes layout but not inherited "
        "opacity, and MessageActions renders inside a reveal-on-hover wrapper that sits at "
        "opacity-0 -- a dialog left as a descendant fades to invisible the moment focus falls "
        "back to the body, while still covering the page and swallowing clicks"
    )
    assert "document.body" in modal

    print("  ok  dialogs portal out of the hover wrapper")
    return True


def test_a_created_prompt_stays_selected():
    """refresh() renders with the old list before the fetch resolves."""
    print("Testing selection after create...")

    workbench = _read(WORKBENCH_TSX)
    create_block = re.search(
        r"const created = await createPrompt\(.*?syncCatalog\(\);",
        workbench,
        re.DOTALL,
    )
    assert create_block, "Could not find the create branch of onSave"
    body = create_block.group(0)

    refresh_at = body.find("await refresh()")
    select_at = body.find("setSelectedId(created.id)")
    assert refresh_at != -1 and select_at != -1, "Could not find both calls in the create branch"
    assert refresh_at < select_at, (
        "the selection must be applied after the refetch. `refresh` sets loading and then "
        "awaits the network, so a selection made first is applied against the stale list and "
        "the guard effect -- seeing an id the list does not contain -- clears it again, landing "
        "the pane on 'Nothing selected' instead of the prompt just written"
    )

    print("  ok  a newly created prompt stays selected")
    return True


def _strip_comments(source):
    """Remove line and block comments from TypeScript source.

    The remote-asset check would otherwise fire on a URL written in prose -- these files
    explain, for instance, why a slash inside ``https://`` must not open the prompt menu. A
    comment cannot load anything, so scanning the code alone is both accurate and stricter:
    it stops an exclusion list from growing until it hides a real reference.
    """
    without_blocks = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
    return re.sub(r"(?m)^\s*//.*$", "", without_blocks)


def test_no_remote_asset_references():
    """Browser assets are local-only; a CDN reference must not creep in."""
    print("Testing for remote asset references...")

    offenders = []
    for path in [
        PROMPT_VARIABLES_TS,
        PROMPT_MEMORY_TS,
        PROMPT_SLASH_TS,
        PROMPT_LIBRARY_TS,
        WORKBENCH_TSX,
        LIST_TSX,
        DETAILS_TSX,
        EDITOR_TSX,
        VARIABLES_TSX,
        PRESENTATION_TSX,
        SLASH_MENU_TSX,
        MODAL_TSX,
        PLAIN_MARKDOWN_TSX,
    ]:
        source = _strip_comments(_read(path))
        for match in re.finditer(r"https?://[^\s'\"`)]+", source):
            url = match.group(0)
            if "schemas" in url or "w3.org" in url:
                continue
            offenders.append(f"{path.name}: {url}")

    assert not offenders, f"Remote asset references are not allowed: {offenders}"
    print("  ok  no remote asset references")
    return True


def test_the_typescript_logic_checks_pass():
    """Execute the behavioural half, skipping when the front-end toolchain is absent."""
    print("Testing prompt logic (TypeScript)...")

    if not (V2_DIR / "node_modules").exists():
        print("  skip  application/v2_ui/node_modules is absent; run npm install to include")
        return True

    assert LOGIC_CHECK_TS.exists(), "The TypeScript logic checks are missing"

    # functional_tests/ has no node_modules of its own, so the bundle is written where node
    # can resolve bare imports from.
    bundle = V2_DIR / "node_modules" / ".cache-prompts-workbench-check.mjs"
    try:
        subprocess.run(
            [
                "npx",
                "esbuild",
                str(LOGIC_CHECK_TS),
                "--bundle",
                "--platform=node",
                "--format=esm",
                "--packages=external",
                # promptLibrary reaches documentExplorer for its date formatting, which sits in
                # a module tree that reads Vite's `import.meta.env`. Node has no such object.
                "--define:import.meta.env={}",
                f"--outfile={bundle}",
                "--log-level=error",
            ],
            cwd=str(V2_DIR),
            check=True,
            shell=(sys.platform == "win32"),
        )
        result = subprocess.run(
            ["node", str(bundle)],
            cwd=str(V2_DIR),
            capture_output=True,
            text=True,
            shell=(sys.platform == "win32"),
        )
    finally:
        if bundle.exists():
            bundle.unlink()

    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr)
        raise AssertionError("the TypeScript logic checks failed")

    passed = result.stdout.count("  ok  ")
    print(f"  ok  {passed} TypeScript logic checks passed")
    return True


if __name__ == "__main__":
    tests = [
        test_version_is_at_least_the_implementing_release,
        test_prompt_update_validation_is_shared_by_every_blueprint,
        test_prompt_validation_behaviour,
        test_creates_and_updates_return_the_same_shape,
        test_prompt_write_routes_carry_their_guards,
        test_the_chat_catalog_carries_the_new_fields,
        test_the_search_parameter_matches_what_the_route_reads,
        test_the_section_is_registered_full_bleed,
        test_picking_a_prompt_does_not_replace_the_composer,
        test_nothing_is_prefilled_in_a_shared_conversation,
        test_variable_values_never_reach_the_server,
        test_the_message_action_says_what_it_does,
        test_a_prompt_saved_from_chat_is_immediately_usable,
        test_a_classic_save_does_not_wipe_the_new_fields,
        test_the_prompt_handoff_has_a_single_url_writer,
        test_the_dialog_escapes_the_hover_reveal_wrapper,
        test_a_created_prompt_stays_selected,
        test_shared_ui_is_not_duplicated,
        test_no_remote_asset_references,
        test_the_typescript_logic_checks_pass,
    ]

    results = []
    for test in tests:
        try:
            results.append(bool(test()))
        except Exception as error:  # noqa: BLE001
            print(f"  FAIL  {test.__name__}: {error}")
            import traceback

            traceback.print_exc()
            results.append(False)

    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)

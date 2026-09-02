#!/usr/bin/env python3
"""
Functional test for V2 inline image generation proposals.

Version: 0.261.029
Implemented in: 0.261.029

A model can propose a generated image inside an ordinary reply by emitting a fenced
`simpleimage` JSON block. The classic client turns each block into an approval card, because
generating an image costs money and time and should never happen without the user asking. The
V2 chat had no renderer for that fence, so the raw JSON payload was shown to the user as a
code block and the proposal could not be acted on at all.

This test ensures the V2 card agrees with the two things it has to agree with, since a
disagreement in either direction produces a card that looks fine and then fails on approval:

  - the classic client (static/js/chat/chat-inline-image-proposals.js), so the same stored
    message renders the same way in both interfaces, and
  - the server (functions_image_generation.py and the route in route_backend_chats.py), which
    re-normalises and re-authorises everything the card sends.

It also ensures the properties that make rendering untrusted model output safe are still in
place -- no HTML sink, no third-party asset -- and that an approved image is reunited with the
card that proposed it rather than left as a loose bubble at the end of the thread.
"""

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = REPO_ROOT / "application" / "single_app"
V2_SRC = REPO_ROOT / "application" / "v2_ui" / "src"

sys.path.insert(0, str(REPO_ROOT / "functional_tests"))

from test_support.versioning import assert_app_version_at_least  # noqa: E402

IMPLEMENTED_IN = "0.261.029"

SPEC_MODULE = V2_SRC / "lib" / "imageProposalSpec.ts"
QUEUE_MODULE = V2_SRC / "lib" / "imageProposalQueue.ts"
RICH_BLOCKS_MODULE = V2_SRC / "lib" / "richBlocks.ts"
ENDPOINTS_MODULE = V2_SRC / "lib" / "endpoints.ts"
CARD_COMPONENT = V2_SRC / "components" / "chat" / "InlineImageProposal.tsx"
SCOPE_COMPONENT = V2_SRC / "components" / "chat" / "ImageProposalContext.tsx"
MARKDOWN_COMPONENT = V2_SRC / "components" / "chat" / "AssistantMarkdown.tsx"
MESSAGE_LIST_COMPONENT = V2_SRC / "components" / "chat" / "MessageList.tsx"
CHAT_STORE = V2_SRC / "stores" / "chatStore.ts"

CLASSIC_MODULE = APP_DIR / "static" / "js" / "chat" / "chat-inline-image-proposals.js"
SERVER_MODULE = APP_DIR / "functions_image_generation.py"
CHAT_ROUTES = APP_DIR / "route_backend_chats.py"

LOGIC_TEST = REPO_ROOT / "functional_tests" / "test_v2_inline_image_proposal_logic.mjs"

V2_FILES = (
    SPEC_MODULE,
    QUEUE_MODULE,
    RICH_BLOCKS_MODULE,
    ENDPOINTS_MODULE,
    CARD_COMPONENT,
    SCOPE_COMPONENT,
    MARKDOWN_COMPONENT,
    MESSAGE_LIST_COMPONENT,
    CHAT_STORE,
)


def _read(path):
    if not path.exists():
        raise AssertionError(f"Expected file is missing: {path}")
    return path.read_text(encoding="utf-8", errors="ignore")


def test_proposal_modules_exist():
    """Every piece of the V2 proposal pipeline is present."""
    print("Testing that the proposal modules exist...")
    for path in (SPEC_MODULE, QUEUE_MODULE, CARD_COMPONENT, SCOPE_COMPONENT):
        if not path.exists():
            raise AssertionError(f"Missing V2 image proposal module: {path}")
        print(f"  {path.relative_to(REPO_ROOT)} is present.")

    print("Module test passed!")
    return True


def test_fence_language_matches_the_classic_client_and_the_server():
    """All three readers of the fence agree on what it is called."""
    print("Testing the fence language...")
    spec_source = _read(SPEC_MODULE)
    classic_source = _read(CLASSIC_MODULE)
    server_source = _read(SERVER_MODULE)

    v2_language = re.search(
        r"IMAGE_PROPOSAL_LANGUAGE\s*=\s*'([^']+)'", spec_source
    )
    if not v2_language:
        raise AssertionError("IMAGE_PROPOSAL_LANGUAGE is not defined in imageProposalSpec.ts")

    classic_language = re.search(
        r"INLINE_IMAGE_PROPOSAL_LANGUAGE\s*=\s*'([^']+)'", classic_source
    )
    if not classic_language:
        raise AssertionError("Could not read the classic fence language.")

    server_language = re.search(
        r"INLINE_IMAGE_PROPOSAL_BLOCK_LANGUAGE\s*=\s*['\"]([^'\"]+)['\"]", server_source
    )
    if not server_language:
        raise AssertionError("Could not read the server fence language.")

    languages = {
        "V2": v2_language.group(1),
        "classic": classic_language.group(1),
        "server": server_language.group(1),
    }
    if len(set(languages.values())) != 1:
        raise AssertionError(f"Fence language disagreement: {languages}")

    print(f"  All three use ```{v2_language.group(1)}.")
    print("Fence language test passed!")
    return True


def test_sanitisation_caps_match_the_server():
    """A card cannot display or send more than the server will accept."""
    print("Testing sanitisation caps...")
    spec_source = _read(SPEC_MODULE)
    server_source = _read(SERVER_MODULE)

    expected_caps = {
        "PROMPT_MAX_LENGTH": "IMAGE_PROPOSAL_PROMPT_MAX_LENGTH",
        "TEXT_MAX_LENGTH": "IMAGE_PROPOSAL_TEXT_MAX_LENGTH",
        "VISUAL_ID_MAX_LENGTH": "IMAGE_PROPOSAL_ID_MAX_LENGTH",
    }

    for client_name, server_name in expected_caps.items():
        client_value = re.search(rf"\b{client_name}\s*=\s*(\d+)", spec_source)
        server_value = re.search(rf"^{server_name}\s*=\s*(\d+)", server_source, re.MULTILINE)
        if not client_value:
            raise AssertionError(f"{client_name} is not defined in imageProposalSpec.ts")
        if not server_value:
            raise AssertionError(f"{server_name} is not defined in functions_image_generation.py")
        if client_value.group(1) != server_value.group(1):
            raise AssertionError(
                f"{client_name} is {client_value.group(1)} but the server's "
                f"{server_name} is {server_value.group(1)}."
            )
        print(f"  {client_name} == {server_name} == {client_value.group(1)}.")

    # The visual id character set is what the server reduces the value to, so a card that
    # allowed more would show an id the stored proposal will never match on.
    if "[^a-zA-Z0-9_.-]+" not in spec_source:
        raise AssertionError("The client visual id character set does not match the server.")
    print("  Visual id character set matches _normalize_visual_id.")

    # The server requires a prompt and nothing else, so that is the one field whose absence
    # makes a payload not a proposal.
    if "Image proposal prompt is required" not in server_source:
        raise AssertionError("The server no longer requires a prompt; the client check is stale.")
    if not re.search(r"const prompt = normalizePrompt\(source\.prompt\);\s*\n\s*if \(!prompt\)", spec_source):
        raise AssertionError("The client does not reject a proposal with no prompt.")
    print("  A proposal with no prompt is rejected client-side too.")

    # The card posts the normalised spec verbatim on approval, so any placeholder the client
    # invents is stored by the server as though the model had written it. A default title in
    # particular would give every untitled proposal in a message the same one, and the matcher
    # that reunites an approved image with its card would then have a value it must not trust.
    if "|| 'Generate image'" in spec_source:
        raise AssertionError(
            "The spec injects a placeholder title, which is posted and stored on approval. "
            "Apply display fallbacks in the card, not in the normalised spec."
        )
    if "title: trimText(source.title, TITLE_MAX_LENGTH)," not in spec_source:
        raise AssertionError("The title is not normalised the way the server stores it.")
    print("  The spec carries only what the model wrote, so nothing invented is stored.")

    print("Sanitisation test passed!")
    return True


def test_approval_posts_to_the_registered_route():
    """The path the card posts to is a route the application actually registers."""
    print("Testing the approval endpoint...")
    endpoints_source = _read(ENDPOINTS_MODULE)
    routes_source = _read(CHAT_ROUTES)

    posted_path = re.search(
        r"generateImageFromProposal\s*=\s*\([^)]*\)\s*=>\s*\n?\s*api\.post<[^>]+>\(\s*'([^']+)'",
        endpoints_source,
    )
    if not posted_path:
        raise AssertionError("generateImageFromProposal does not post to a literal path.")

    path = posted_path.group(1)
    if f"@bp.route('{path}', methods=['POST'])" not in routes_source:
        raise AssertionError(f"{path} is not registered as a POST route in route_backend_chats.py")
    print(f"  POST {path} is registered.")

    # The route reads these three keys; sending anything else would silently lose the edit.
    for key in ("conversation_id", "assistant_message_id", "proposal"):
        if key not in endpoints_source:
            raise AssertionError(f"The request body does not carry {key}.")
    print("  conversation_id, assistant_message_id and proposal are all sent.")

    # Going through api.post is what applies the shared credentials and CSRF behaviour.
    if "api.post<ImageProposalResult>" not in endpoints_source:
        raise AssertionError("Approval does not go through the shared api client.")
    print("  Approval goes through the shared api client.")

    print("Endpoint test passed!")
    return True


def test_generation_is_opt_in_and_serialised():
    """Nothing generates without a click, and approvals do not run in parallel."""
    print("Testing approval behaviour...")
    card_source = _read(CARD_COMPONENT)
    queue_source = _read(QUEUE_MODULE)

    # An effect that approved on mount would make the card generate by itself, which is the
    # single thing this whole feature exists to prevent.
    if re.search(r"useEffect\(\s*\(\)\s*=>\s*\{\s*void approve\(\)", card_source):
        raise AssertionError("The card approves itself on mount.")
    if "onClick={() => void approve()}" not in card_source:
        raise AssertionError("Approve is not driven by a click.")
    print("  Generation only starts from a click.")

    # "Approve all" is broadcast as a counter that belongs to the message and outlives any one
    # card. Testing it against zero rather than against the value seen at mount would make a
    # card that remounts after the button was pressed generate an image nobody asked for.
    if "approveAllToken > seenApproveAllToken.current" not in card_source:
        raise AssertionError(
            "The approve-all effect does not compare against the token seen at mount, so a "
            "remounted card can generate an image without a click."
        )
    print("  A remounted card does not act on an old approve-all.")

    if "enqueueImageApproval" not in card_source:
        raise AssertionError("Approval does not go through the serial queue.")
    if "let running = false" not in queue_source or "waiting.shift()" not in queue_source:
        raise AssertionError("The approval queue is not a serial FIFO.")
    print("  Approvals run one at a time through a FIFO queue.")

    print("Approval behaviour test passed!")
    return True


def test_approval_stays_bound_to_its_own_conversation():
    """A queued approval cannot generate its image into whichever thread is open later."""
    print("Testing conversation binding...")
    card_source = _read(CARD_COMPONENT)
    store_source = _read(CHAT_STORE)

    # Approvals are queued, so a bulk approval can still be draining after the user has
    # switched threads. Resolving the conversation inside the queued call would post the new
    # conversation's id -- which the server accepts, because the same user owns it -- and bill
    # an image into the wrong conversation.
    action = re.search(
        r"approveImageProposal:\s*async\s*\(\s*conversationId\s*,\s*assistantMessageId\s*,"
        r"\s*proposal\s*\)\s*=>\s*\{(.*?)\n    \},",
        store_source,
        re.S,
    )
    if not action:
        raise AssertionError(
            "approveImageProposal does not take the conversation id, so it resolves one when "
            "the queued approval eventually runs."
        )
    if "activeConversationId" in action.group(1).split("const result =")[0]:
        raise AssertionError(
            "approveImageProposal still resolves the conversation itself before posting."
        )
    if "conversation_id: conversationId" not in action.group(1):
        raise AssertionError("approveImageProposal does not post the conversation it was given.")
    print("  The store posts the conversation it was given, not the active one.")

    if "useChatStore.getState().activeConversationId" not in card_source:
        raise AssertionError("The card does not capture the conversation before queueing.")
    captured = card_source.index("useChatStore.getState().activeConversationId")
    enqueued = card_source.index("await enqueueImageApproval(")
    if captured > enqueued:
        raise AssertionError(
            "The card reads the conversation after queueing rather than before."
        )
    print("  The card captures it at click time, before the approval is queued.")

    print("Conversation binding test passed!")
    return True


def test_approve_all_threshold_matches_the_classic_client():
    """The bulk control appears at the same point in both interfaces."""
    print("Testing the approve-all threshold...")
    scope_source = _read(SCOPE_COMPONENT)
    classic_source = _read(CLASSIC_MODULE)

    v2_threshold = re.search(r"APPROVE_ALL_THRESHOLD\s*=\s*(\d+)", scope_source)
    if not v2_threshold:
        raise AssertionError("APPROVE_ALL_THRESHOLD is not defined.")

    classic_threshold = re.search(r"pendingContainers\.length <= (\d+)", classic_source)
    if not classic_threshold:
        raise AssertionError("Could not read the classic approve-all threshold.")

    if v2_threshold.group(1) != classic_threshold.group(1):
        raise AssertionError(
            f"V2 shows the bulk control above {v2_threshold.group(1)} pending cards but the "
            f"classic client uses {classic_threshold.group(1)}."
        )
    if "pendingCount > APPROVE_ALL_THRESHOLD" not in scope_source:
        raise AssertionError("The bulk control is not gated on the threshold.")
    print(f"  Both show it above {v2_threshold.group(1)} pending cards.")

    print("Approve-all test passed!")
    return True


def test_approved_images_are_folded_into_their_card():
    """An approved image is shown in its proposal card, not twice in the thread."""
    print("Testing result folding...")
    spec_source = _read(SPEC_MODULE)
    list_source = _read(MESSAGE_LIST_COMPONENT)
    server_source = _read(SERVER_MODULE)

    # The metadata key the fold is built on has to be the one the server writes.
    if "metadata['source_assistant_message_id'] = str(source_assistant_message_id)" not in server_source:
        raise AssertionError(
            "The server no longer records source_assistant_message_id on a generated image."
        )
    if "source_assistant_message_id" not in spec_source:
        raise AssertionError("The client does not read source_assistant_message_id.")
    print("  Folding keys on the metadata the server writes.")

    if "groupProposalImages" not in list_source or "ImageProposalScope" not in list_source:
        raise AssertionError("MessageList does not route proposal images into their cards.")

    # Filtering the folded image out of the thread is what stops it appearing twice.
    if "!claimed.has(message.id)" not in list_source:
        raise AssertionError("Folded proposal images are not hidden from the thread.")
    print("  A folded image is hidden from the top-level thread.")

    # An image is only hidden once a card has been shown to claim it. Hiding on the metadata
    # alone would make an image that no card can match visible nowhere at all.
    if "extractProposalSpecs" not in list_source or "findResultForSpec" not in list_source:
        raise AssertionError(
            "The fold hides images without checking that a card can actually show them."
        )
    if "export function extractProposalSpecs" not in spec_source:
        raise AssertionError("extractProposalSpecs is not implemented.")
    print("  An image no card can claim stays visible in the thread.")

    print("Folding test passed!")
    return True


def test_fence_is_wired_into_the_renderer_with_a_streaming_guard():
    """The fence renders as a card, and a half-arrived fence does not."""
    print("Testing renderer wiring...")
    markdown_source = _read(MARKDOWN_COMPONENT)
    rich_blocks_source = _read(RICH_BLOCKS_MODULE)

    if "IMAGE_PROPOSAL_LANGUAGE" not in markdown_source:
        raise AssertionError("AssistantMarkdown does not know the proposal fence.")
    if "<InlineImageProposal source={fenceText(children)} />" not in markdown_source:
        raise AssertionError("The fence does not render the proposal card.")
    if not re.search(
        r"RICH_FENCE_LANGUAGES = new Set<string>\(\[[^\]]*IMAGE_PROPOSAL_LANGUAGE",
        markdown_source,
        re.S,
    ):
        raise AssertionError(
            "The proposal fence is not a rich fence, so it keeps its <pre> code-block wrapper."
        )
    print("  The fence renders as a card without a code-block wrapper.")

    # Without this, markdown hands the card half its own JSON on every streamed token.
    pending_block = re.search(
        r"PENDING_LANGUAGES[^=]*=\s*\{(.*?)\n\};", rich_blocks_source, re.S
    )
    if not pending_block:
        raise AssertionError("PENDING_LANGUAGES could not be read from richBlocks.ts")
    if "IMAGE_PROPOSAL_LANGUAGE" not in pending_block.group(1):
        raise AssertionError("The proposal fence has no streaming pending state.")
    print("  A still-arriving fence shows a placeholder instead of being parsed.")

    print("Renderer wiring test passed!")
    return True


def test_untrusted_payload_is_never_rendered_as_html():
    """A proposal is model output, so none of it reaches an HTML sink."""
    print("Testing rendering safety...")
    for path in V2_FILES:
        source = _read(path)
        for sink in ("dangerouslySetInnerHTML", "innerHTML", "outerHTML", "insertAdjacentHTML"):
            if sink in source:
                raise AssertionError(f"{path.relative_to(REPO_ROOT)} uses {sink}.")
    print("  No HTML sink in any of the touched files.")

    card_source = _read(CARD_COMPONENT)
    # A failed parse must report a reason, never echo the payload back at the reader.
    if "{parsed.reason}" not in card_source:
        raise AssertionError("A malformed proposal does not report why it was rejected.")
    # The fence payload is only ever an argument to the parser, never a rendered child.
    if re.search(r">\s*\{\s*source\s*\}\s*<", card_source):
        raise AssertionError("The raw fence payload is rendered.")
    if "parseImageProposal(source)" not in card_source:
        raise AssertionError("The fence payload is not routed through the parser.")
    print("  A malformed payload shows a reason, not the payload.")

    print("Rendering safety test passed!")
    return True


def test_no_third_party_browser_assets_were_added():
    """The V2 UI still loads nothing from a CDN and gained no new dependency."""
    print("Testing browser assets...")
    remote_pattern = re.compile(r"https?://(?!localhost)[^\s'\"`)]+", re.I)
    for path in V2_FILES:
        source = _read(path)
        for match in remote_pattern.finditer(source):
            url = match.group(0)
            # A URL inside the source is only a problem when the browser would fetch it. The
            # image source matcher and its comments name http(s) forms without fetching them.
            if url.startswith("https://...") or "rollupjs.org" in url:
                continue
            raise AssertionError(
                f"{path.relative_to(REPO_ROOT)} references a remote URL: {url}"
            )
    print("  No remote URL in any of the touched files.")

    package_json = json.loads(
        _read(REPO_ROOT / "application" / "v2_ui" / "package.json")
    )
    dependencies = set(package_json.get("dependencies", {}))
    expected = {
        "clsx",
        "hast-util-to-text",
        "highlight.js",
        "lowlight",
        "lucide-react",
        "react",
        "react-dom",
        "react-markdown",
        "react-router-dom",
        "remark-breaks",
        "remark-gfm",
        "unist-util-visit",
        "zustand",
    }
    if dependencies != expected:
        raise AssertionError(
            f"Dependencies changed. Added: {sorted(dependencies - expected)}, "
            f"removed: {sorted(expected - dependencies)}"
        )
    print("  No npm dependency was added.")

    print("Browser asset test passed!")
    return True


def test_version_was_incremented():
    """The application version records when this shipped."""
    print("Testing version...")
    version = assert_app_version_at_least(
        IMPLEMENTED_IN,
        reason="V2 inline image generation proposals.",
    )
    print(f"  config.py VERSION is {version}.")
    print("Version test passed!")
    return True


def test_proposal_logic_behaves():
    """Run the companion runtime test, which executes the parsing, matching and queue logic.

    The assertions above prove the pieces are wired together correctly. They cannot prove that
    an approved image is reunited with the right card, or that approvals do not run in
    parallel, because those are behaviours rather than shapes. The Node test does that, and is
    run from here so it cannot quietly rot next to a suite that never invokes it.

    Node is not otherwise required to work on this repository, so its absence is reported
    rather than failed. A Node that is present and reports a failure is a failure.
    """
    print("Testing proposal logic behaviour...")
    if not LOGIC_TEST.exists():
        raise AssertionError(f"The runtime logic test is missing: {LOGIC_TEST}")

    node = shutil.which("node")
    if not node:
        print("  Node is not installed; skipping the runtime logic test.")
        print(f"  Run it with: node {LOGIC_TEST.relative_to(REPO_ROOT)}")
        return True

    completed = subprocess.run(
        [node, str(LOGIC_TEST)],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    output = (completed.stdout or "") + (completed.stderr or "")

    # Node below 22.6 cannot import TypeScript directly. That is a limitation of the
    # environment, not a defect in the code under test.
    if completed.returncode != 0 and "Unknown file extension" in output:
        print("  This Node cannot import TypeScript directly (needs 22.6 or newer); skipping.")
        return True

    for line in output.splitlines():
        if line.strip():
            print(f"  {line}")

    if completed.returncode != 0:
        raise AssertionError("The runtime logic test failed; see the output above.")

    print("Proposal logic test passed!")
    return True


if __name__ == "__main__":
    tests = [
        test_proposal_modules_exist,
        test_fence_language_matches_the_classic_client_and_the_server,
        test_sanitisation_caps_match_the_server,
        test_approval_posts_to_the_registered_route,
        test_generation_is_opt_in_and_serialised,
        test_approval_stays_bound_to_its_own_conversation,
        test_approve_all_threshold_matches_the_classic_client,
        test_approved_images_are_folded_into_their_card,
        test_fence_is_wired_into_the_renderer_with_a_streaming_guard,
        test_untrusted_payload_is_never_rendered_as_html,
        test_no_third_party_browser_assets_were_added,
        test_proposal_logic_behaves,
        test_version_was_incremented,
    ]

    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            results.append(bool(test()))
        except Exception as exc:  # noqa: BLE001 - surface any failure with a traceback
            print(f"Test failed: {exc}")
            import traceback

            traceback.print_exc()
            results.append(False)

    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)

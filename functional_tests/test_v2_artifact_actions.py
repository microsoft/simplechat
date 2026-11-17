#!/usr/bin/env python3
# test_v2_artifact_actions.py
"""
Functional test for "Add to workspace" and "Create PowerPoint" on V2 generated-artifact cards.
Version: 0.261.445
Implemented in: 0.261.445

Classic's generated-artifact card offers both actions; the V2 card offered only Download and View
(``V2_TABULAR_ANALYSIS.md`` recorded them as not carried over). The V2 actions call the same two
routes classic does.

These checks pin what the actions rely on, derived from the route source rather than from memory
of it:

- ``POST /api/chat_artifacts/promote``: its decorators, the body fields it reads, that it requires
  an explicit destination, its fixed default ``request_id`` (which is why V2 sends none), and the
  409/202/200 answers V2 reads;
- ``POST /api/message/export-powerpoint``: the ``artifact_message_id`` it takes, that the reply's
  own text override is ignored for a file export, that only Markdown files qualify, and that the
  reply is read from the caller's own conversation (why V2 does not offer it in shared ones);
- what classic's card does, so the V2 rules are a faithful port rather than a guess: which files
  get which button, and the request bodies it builds;
- that the card draws the actions only outside an orchestration file card, and that the reply's
  id reaches it;
- the TypeScript rules (destination resolution, request bodies, answer handling, eligibility).
"""

import re
import subprocess
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))

from test_support.versioning import assert_app_version_at_least


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"
V2_DIR = REPO_ROOT / "application" / "v2_ui"
V2_SRC = V2_DIR / "src"
CITATIONS_ROUTE = APP_ROOT / "route_enhanced_citations.py"
EXPORT_ROUTE = APP_ROOT / "route_backend_conversation_export.py"
CLASSIC_MESSAGES = APP_ROOT / "static" / "js" / "chat" / "chat-messages.js"
CLASSIC_EXPORT = APP_ROOT / "static" / "js" / "chat" / "chat-message-export.js"
LOGIC_CHECK_TS = Path(__file__).resolve().parent / "test_v2_artifact_actions_logic.ts"

NEW_SOURCES = [
    V2_SRC / "lib" / "generatedArtifactActions.ts",
    V2_SRC / "stores" / "generatedArtifactActionStore.ts",
    V2_SRC / "components" / "chat" / "GeneratedArtifactActions.tsx",
    V2_SRC / "components" / "chat" / "ArtifactPromotionDialog.tsx",
]


def _read(path):
    assert Path(path).is_file(), f"Missing expected file: {path}"
    return Path(path).read_text(encoding="utf-8")


def _normalize(source):
    return re.sub(r"\s+", " ", source)


def _function_source(source, name):
    """The text of one top-level or nested Python function, up to the next route or definition."""
    match = re.search(rf"def {name}\(.*?(?=\n    @bp\.route|\ndef |\Z)", source, re.S)
    assert match, f"Could not find {name}"
    return match.group(0)


def test_version_is_at_least_the_implementing_release():
    """The application carries at least the version the artifact actions arrived in."""
    print("Testing the application version...")
    assert_app_version_at_least("0.261.445")


def test_the_promote_route_is_what_the_client_calls():
    """Decorators, body fields, explicit destination, fixed default request id, status codes."""
    print("Testing the promote route...")

    source = _read(CITATIONS_ROUTE)
    route = re.search(
        r'@bp\.route\("/api/chat_artifacts/promote", methods=\["POST"\]\)(?P<decorators>(?:\s*@[^\n]+\n)+)',
        source,
    )
    assert route, "Could not find POST /api/chat_artifacts/promote"
    for decorator in ("@swagger_route(security=get_auth_security())", "@login_required", "@user_required"):
        assert decorator in route.group("decorators"), f"The promote route should carry {decorator}"

    body = _function_source(source, "promote_chat_artifact_to_workspace")
    for field in ("conversation_id", "message_id", "workspace_scope", "group_id", "public_workspace_id"):
        assert f'payload.get("{field}")' in body, f"The route reads {field}, so the client must send it"
    assert 'raise ValueError("Choose an explicit destination for this analysis artifact.")' in body, (
        "The route requires `workspace_scope`, so the client always names a destination"
    )
    assert 'request_id=payload.get("request_id") or "manual"' in body, (
        "Without a request_id the route uses one fixed id, which makes a repeat request return the "
        "existing publication instead of creating a second copy. V2 relies on that and sends none."
    )
    assert 'if result["publication"]["state"] in {"uncertain", "approval_failed"}:' in body
    assert "return jsonify(result), 409" in body, "An unconfirmed publication answers 409 with the usual result"
    assert 'return jsonify(result), 202 if result["approval_required"] else 200' in body

    print("  ok  the promote route is what the V2 client calls")


def test_the_powerpoint_route_takes_a_stored_markdown_file():
    """artifact_message_id replaces the reply's text; only Markdown qualifies; the owner reads it."""
    print("Testing the PowerPoint route...")

    source = _read(EXPORT_ROUTE)
    route = _function_source(source, "api_export_message_powerpoint")
    assert "artifact_message_id = str(data.get('artifact_message_id', '') or '').strip()" in route
    assert "if not artifact_message_id:" in route and "_get_message_export_content_override(data)" in route, (
        "The reply's own text override applies only when no file is named, so V2 sends none"
    )
    assert "message_id and conversation_id are required" in route, "The reply's id is required beside the file"

    loader = _function_source(source, "_load_generated_markdown_artifact_for_user")
    assert "Only generated Markdown artifacts can be exported as PowerPoint" in loader, (
        "Only Markdown files qualify, which is why V2 offers the action for Markdown only"
    )
    assert "artifact_metadata.get('is_generated_chat_artifact')" in loader

    reply_loader = _function_source(source, "_load_export_message_for_user")
    assert "if conversation.get('user_id') != user_id:" in reply_loader and "raise PermissionError('Access denied')" in reply_loader, (
        "The reply is read from the personal conversation container and only its owner may export it, "
        "so a shared conversation cannot succeed and V2 does not offer the action there"
    )

    print("  ok  the PowerPoint route builds a deck from a stored Markdown file")


def test_the_v2_rules_are_the_classic_cards_rules():
    """What classic does, so the port is faithful: which files, which bodies."""
    print("Testing parity with the classic card...")

    classic = _read(CLASSIC_MESSAGES)

    # "Add to Workspace": any finished file on its own message, after the early returns for an
    # approval-blocked file and for a background export.
    promote_button = re.search(
        r"const normalizedArtifactMessageId = String\(outputMetadata\?\.artifact_message_id \|\| ''\)\.trim\(\);\s*"
        r"const normalizedConversationId = String\(outputMetadata\?\.conversation_id \|\| window\.currentConversationId \|\| ''\)\.trim\(\);\s*"
        r"if \(normalizedArtifactMessageId && normalizedConversationId\) \{\s*"
        r"const promoteButton = document\.createElement\('button'\);",
        classic,
    )
    assert promote_button, "Classic offers Add to Workspace for a file with an artifact message id and a conversation"
    assert "if (generatedFileApprovalBlocksDownload(outputMetadata)) {\n      return card;" in classic
    assert "if (outputMetadata?.background_export) {" in classic

    # "Create PowerPoint": Markdown files that are not row-level exports.
    assert "if (isGeneratedMarkdownArtifact(outputMetadata, outputFormat) && !isCompletedTabularArtifact) {" in classic, (
        "Classic offers Create PowerPoint for Markdown files that are not completed tabular exports"
    )

    promote_body = re.search(r"const requestPayload = \{(?P<body>.*?)\};", classic, re.S)
    assert promote_body, "Could not find classic's promote request body"
    for field in ("conversation_id:", "message_id:", "workspace_scope:"):
        assert field in promote_body.group("body")
    assert "requestPayload.group_id = target.group_id;" in classic
    assert "requestPayload.public_workspace_id = target.public_workspace_id;" in classic
    assert "request_id" not in classic[classic.index("const requestPayload"):classic.index("fetch('/api/chat_artifacts/promote'")], (
        "Classic sends no request_id either"
    )

    export = _read(CLASSIC_EXPORT)
    assert "requestBody.artifact_message_id = preferredArtifactSource.artifactMessageId;" in export
    assert "delete requestBody.message_content_override;" in export, (
        "Classic drops the reply's text override when it builds a deck from a file"
    )

    # And the V2 rules say the same things in the same words.
    rules = _read(V2_SRC / "lib" / "generatedArtifactActions.ts")
    assert "isMarkdownArtifact(artifact)" in rules and "!isCompletedTabularArtifact(artifact)" in rules
    assert "approvalBlocksDownload(artifact)" in rules and "artifact.background_export" in rules
    assert "'Add to Personal'" in rules and "'Submit to Group'" in rules and "'Submit to Public'" in rules, (
        "The confirm wording is classic's"
    )
    assert "Private to you" in rules and "Group workspace approval request" in rules and "Public workspace approval request" in rules

    print("  ok  the V2 rules match what the classic card does")


def test_the_client_sends_what_the_routes_read():
    """Paths, methods and the artifact id on the PowerPoint request."""
    print("Testing the client requests...")

    endpoints = _normalize(_read(V2_SRC / "lib" / "endpoints.ts"))
    assert (
        "export const promoteGeneratedArtifact = (body: PromotionRequestBody) => "
        "api.post<ArtifactPromotionResponse>('/api/chat_artifacts/promote', body);"
    ) in endpoints
    assert "powerpoint: '/api/message/export-powerpoint'," in endpoints
    assert "artifact_message_id?: string;" in endpoints, "The export request type carries the file's id"

    rules = _read(V2_SRC / "lib" / "generatedArtifactActions.ts")
    body = re.search(r"export function promotionRequestBody\(.*?\n\}\n", rules, re.S).group(0)
    assert "request_id" not in body, "V2 sends no request_id, like classic"
    assert "workspace_scope: target.scope" in body

    actions = _read(V2_SRC / "components" / "chat" / "GeneratedArtifactActions.tsx")
    assert "downloadMessageExport('powerpoint', body)" in actions, "The deck uses the existing export path"
    assert "toast.pending(POWERPOINT_PENDING_MESSAGE)" in actions and "toast.settle(" in actions, (
        "A PowerPoint takes about a minute, so it reports progress and settles in place"
    )
    assert "buildMessageVisualAssets(messageId)" in actions, "Diagrams already drawn are sent, as classic does"

    print("  ok  the client sends what the routes read")


def test_the_card_draws_the_actions_and_gets_the_replys_id():
    """Only the standalone card carries them; MessageList passes the reply's id."""
    print("Testing wiring...")

    card = _read(V2_SRC / "components" / "chat" / "GeneratedArtifactCard.tsx")
    assert re.search(r"\{!embedded && \(\s*<GeneratedArtifactActions\s+artifact=\{artifact\}\s+conversationId=\{conversationId\}\s+messageId=\{messageId\}", card), (
        "The actions are drawn inside the file controls and not in an orchestration file card"
    )
    assert card.count("messageId={messageId}") >= 3, "The reply's id reaches finished run members and the wrapper too"

    messages = _read(V2_SRC / "components" / "chat" / "MessageList.tsx")
    assert re.search(
        r"<GeneratedArtifactCard\s+key=\{.*?\}\s+artifact=\{artifact\}\s+conversationId=\{message\.conversation_id\}\s+messageId=\{message\.id\}",
        messages,
        re.S,
    ), (
        "The reply carrying the file is what a deck is built beside"
    )

    actions = _read(V2_SRC / "components" / "chat" / "GeneratedArtifactActions.tsx")
    assert "metadata?.conversation_id === activeConversationId" in actions, (
        "The destination is not offered until the conversation's own metadata has loaded"
    )
    assert "activeConversationKind === 'collaborative'" in actions, "Shared conversations are told apart"

    dialog = _read(V2_SRC / "components" / "chat" / "ArtifactPromotionDialog.tsx")
    assert 'role="alert"' in dialog and "<legend" in dialog and 'type="radio"' in dialog, (
        "The dialog reports a refusal, and a chooser is a labelled group of radios"
    )

    print("  ok  the card, the list and the dialog are wired")


def test_nothing_unsafe_or_remote_is_added():
    """Text from the server is React text, and no remote asset or inline display rule appears."""
    print("Testing markup and assets...")

    offenders = []
    for path in NEW_SOURCES:
        source = _read(path)
        for pattern, why in (
            (r"dangerouslySetInnerHTML", "raw HTML"),
            (r"innerHTML", "raw HTML"),
            (r"https?://", "a remote URL"),
            (r"display\s*:\s*none", "an inline display rule"),
            (r"\balert\(", "alert()"),
        ):
            if re.search(pattern, source):
                offenders.append(f"{path.name}: {why}")
    assert not offenders, offenders

    print("  ok  no raw HTML, remote URLs, inline display rules or alert()")


def test_the_typescript_logic_checks_pass():
    """Execute the behavioural half, skipping when the front-end toolchain is absent."""
    print("Testing artifact action logic (TypeScript)...")

    if not (V2_DIR / "node_modules").exists():
        print("  skip  application/v2_ui/node_modules is absent; run npm install to include")
        return

    assert LOGIC_CHECK_TS.exists(), "The TypeScript logic checks are missing"

    # functional_tests/ has no node_modules of its own, so the bundle is written where node can
    # resolve bare imports from.
    bundle = V2_DIR / "node_modules" / ".cache-artifact-actions-check.mjs"
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
    assert passed >= 10, result.stdout
    print(f"  ok  {passed} TypeScript logic checks passed")


if __name__ == "__main__":
    tests = [
        test_version_is_at_least_the_implementing_release,
        test_the_promote_route_is_what_the_client_calls,
        test_the_powerpoint_route_takes_a_stored_markdown_file,
        test_the_v2_rules_are_the_classic_cards_rules,
        test_the_client_sends_what_the_routes_read,
        test_the_card_draws_the_actions_and_gets_the_replys_id,
        test_nothing_unsafe_or_remote_is_added,
        test_the_typescript_logic_checks_pass,
    ]
    results = []
    for test in tests:
        try:
            test()
            results.append(True)
        except Exception as exc:  # noqa: BLE001
            print(f"FAIL  {test.__name__}: {exc}")
            import traceback

            traceback.print_exc()
            results.append(False)

    print(f"\n{sum(1 for result in results if result)}/{len(results)} test(s) passed")
    sys.exit(0 if all(results) else 1)

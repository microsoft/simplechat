#!/usr/bin/env python3
# test_collaboration_multi_user_reload_and_stream_fix.py
"""
Functional test for shared (multi-user) conversation reload and AI streaming.
Version: 0.250.225
Implemented in: 0.250.224

This test ensures that:

1. The collaboration stream bridge resolves the internal chat streaming view function
   even though route modules are registered through Blueprints, so shared conversations
   no longer fail with "Chat streaming endpoint is unavailable" (issue #1281).
2. selectConversation() no longer calls the personal-only /conversation/<id>/messages
   endpoint for collaborative conversations, which always returned 404 because shared
   conversations live in the collaboration container under a different id.
3. loadConversationMessages() performs the search-highlight, task-document, and
   comparison-catalog side effects that the personal loader used to provide, so shared
   conversations keep parity instead of silently losing them.
4. Every shared stream error is tagged with conversation_kind, so the browser recovery
   path can never fall back to the personal messages endpoint (added in 0.250.225).
"""

import ast
import os
import sys

from flask import Blueprint, Flask, current_app

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from test_support.versioning import assert_app_version_at_least

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMPLEMENTED_IN_VERSION = "0.250.224"
RESOLVER_FUNCTION_NAME = "_resolve_internal_view_function"


def read_repo_file(*parts):
    file_path = os.path.join(ROOT_DIR, *parts)
    with open(file_path, "r", encoding="utf-8") as file_handle:
        return file_handle.read()


def load_resolver():
    """Load the collaboration route module's internal view resolver in isolation.

    route_backend_collaboration imports the full application config graph, which needs live
    Azure credentials. Compile just the resolver definition so its real behavior can be
    exercised without standing up Cosmos, Search, and OpenAI clients.
    """
    route_source = read_repo_file("application", "single_app", "route_backend_collaboration.py")
    module_ast = ast.parse(route_source)
    resolver_nodes = [
        node for node in module_ast.body
        if isinstance(node, ast.FunctionDef) and node.name == RESOLVER_FUNCTION_NAME
    ]

    assert len(resolver_nodes) == 1, (
        f"Expected exactly one module-level {RESOLVER_FUNCTION_NAME} definition, "
        f"found {len(resolver_nodes)}."
    )

    resolver_module = ast.Module(body=resolver_nodes, type_ignores=[])
    resolver_namespace = {"current_app": current_app}
    exec(compile(resolver_module, "route_backend_collaboration.py", "exec"), resolver_namespace)
    return resolver_namespace[RESOLVER_FUNCTION_NAME]


def build_blueprint_registered_app():
    """Build an app whose chat stream view is registered exactly like production."""
    app = Flask(__name__)
    app.config["TESTING"] = True

    chats_blueprint = Blueprint("backend_chats", __name__)

    @chats_blueprint.route("/api/chat/stream", methods=["POST"])
    def chat_stream_api():
        return "streamed"

    app.register_blueprint(chats_blueprint)
    return app


def build_app_registered_app():
    """Build an app whose chat stream view is registered directly on the app."""
    app = Flask(__name__)
    app.config["TESTING"] = True

    @app.route("/api/chat/stream", methods=["POST"])
    def chat_stream_api():
        return "streamed"

    return app


def test_stream_view_resolves_through_blueprint_endpoint():
    """Blueprint-registered chat streaming views must resolve for the collaboration bridge."""
    print("Testing blueprint-prefixed chat stream endpoint resolution...")

    resolve_internal_view_function = load_resolver()
    app = build_blueprint_registered_app()

    assert "chat_stream_api" not in app.view_functions, (
        "Expected the Blueprint-registered view to be keyed as backend_chats.chat_stream_api."
    )
    assert "backend_chats.chat_stream_api" in app.view_functions, (
        "Expected the test app to mirror the production Blueprint endpoint name."
    )

    with app.test_request_context("/api/chat/stream", method="POST"):
        resolved_view = resolve_internal_view_function("chat_stream_api")

    assert callable(resolved_view), (
        "Expected the collaboration bridge to resolve backend_chats.chat_stream_api."
    )
    assert resolved_view is app.view_functions["backend_chats.chat_stream_api"], (
        "Expected the resolver to return the registered Blueprint view function."
    )

    print("Blueprint endpoint resolution passed!")
    return True


def test_stream_view_resolves_unprefixed_and_rejects_unknown():
    """Directly registered views still resolve, and unknown endpoints return None."""
    print("Testing unprefixed resolution and unknown endpoint handling...")

    resolve_internal_view_function = load_resolver()
    app = build_app_registered_app()

    with app.test_request_context("/api/chat/stream", method="POST"):
        resolved_view = resolve_internal_view_function("chat_stream_api")
        unknown_view = resolve_internal_view_function("definitely_not_registered_api")

    assert resolved_view is app.view_functions["chat_stream_api"], (
        "Expected an app-registered view function to resolve by its bare endpoint name."
    )
    assert unknown_view is None, (
        "Expected an unregistered endpoint name to resolve to None."
    )

    print("Unprefixed and unknown endpoint handling passed!")
    return True


def test_collaboration_route_uses_resolver_and_logs_failures():
    """The collaboration stream route must use the resolver and log resolution failures."""
    print("Testing collaboration stream route wiring...")

    route_source = read_repo_file("application", "single_app", "route_backend_collaboration.py")

    assert "def _resolve_internal_view_function(endpoint_name):" in route_source, (
        "Expected the Blueprint-tolerant view resolver helper to exist."
    )
    assert "internal_stream_view = _resolve_internal_view_function('chat_stream_api')" in route_source, (
        "Expected the collaboration stream bridge to use the Blueprint-tolerant resolver."
    )
    assert "current_app.view_functions.get('chat_stream_api')" not in route_source, (
        "Expected the Blueprint-unaware view lookup to be removed."
    )
    assert (
        "'[COLLABORATION] Chat streaming view function could not be resolved for the collaboration stream bridge'"
        in route_source
    ), "Expected a tagged log event when the chat streaming view cannot be resolved."

    print("Collaboration stream route wiring passed!")
    return True


def test_select_conversation_skips_personal_messages_endpoint():
    """Collaborative conversations must not call the personal messages endpoint."""
    print("Testing collaborative conversation selection wiring...")

    conversations_source = read_repo_file(
        "application", "single_app", "static", "js", "chat", "chat-conversations.js"
    )

    collaborative_branch_marker = (
        "if (isCollaborativeConversation && window.chatCollaboration?.activateConversation) {"
    )
    branch_start = conversations_source.find(collaborative_branch_marker)
    assert branch_start != -1, "Expected the collaborative branch in selectConversation()."

    branch_end = conversations_source.find("} else {", branch_start)
    assert branch_end != -1, "Expected an else branch after the collaborative branch."

    collaborative_branch = conversations_source[branch_start:branch_end]
    assert "loadMessages(" not in collaborative_branch, (
        "Collaborative conversations must not call the personal /conversation/<id>/messages endpoint."
    )
    assert "window.chatCollaboration.activateConversation(conversationId, metadata)" in collaborative_branch, (
        "Expected collaborative conversations to load through activateConversation()."
    )

    # The personal branch must keep using the personal loader.
    personal_branch = conversations_source[branch_end:branch_end + 1200]
    assert "await loadMessages(conversationId);" in personal_branch, (
        "Expected non-collaborative conversations to keep using loadMessages()."
    )

    print("Collaborative conversation selection wiring passed!")
    return True


def test_collaboration_loader_keeps_personal_loader_side_effects():
    """loadConversationMessages() must retain the side effects loadMessages() provided."""
    print("Testing collaboration message loader side effects...")

    collaboration_source = read_repo_file(
        "application", "single_app", "static", "js", "chat", "chat-collaboration.js"
    )
    messages_source = read_repo_file(
        "application", "single_app", "static", "js", "chat", "chat-messages.js"
    )

    assert "export function updateComparisonChatUploadCatalog(" in messages_source, (
        "Expected updateComparisonChatUploadCatalog to be exported for collaboration reuse."
    )

    assert "import { updateConversationTaskDocumentsFromMessages } from './chat-documents.js';" in collaboration_source, (
        "Expected the collaboration module to import the task document hydrator."
    )

    loader_start = collaboration_source.find("async function loadConversationMessages(conversationId) {")
    assert loader_start != -1, "Expected loadConversationMessages() in chat-collaboration.js."

    loader_end = collaboration_source.find("\n}", loader_start)
    assert loader_end != -1, "Expected loadConversationMessages() to be a closed function block."

    loader_body = collaboration_source[loader_start:loader_end]
    assert "clearSearchHighlight();" in loader_body, (
        "Expected loadConversationMessages() to clear stale search highlights."
    )
    assert "updateConversationTaskDocumentsFromMessages(messages, conversationId);" in loader_body, (
        "Expected loadConversationMessages() to rehydrate conversation task documents."
    )
    assert "updateComparisonChatUploadCatalog(messages);" in loader_body, (
        "Expected loadConversationMessages() to refresh the comparison chat upload catalog."
    )
    assert "reapplyPendingSearchHighlight();" in loader_body, (
        "Expected loadConversationMessages() to reapply a pending search highlight."
    )

    assert "function reapplyPendingSearchHighlight() {" in collaboration_source, (
        "Expected a search highlight reapplication helper in chat-collaboration.js."
    )
    assert "SEARCH_HIGHLIGHT_MAX_AGE_MS" in collaboration_source, (
        "Expected the shared 30 second search highlight freshness window."
    )

    print("Collaboration message loader side effects passed!")
    return True


def test_collaboration_stream_errors_always_carry_conversation_kind():
    """Every shared stream error must be tagged as collaborative for browser recovery."""
    print("Testing collaboration stream error attribution...")

    route_source = read_repo_file("application", "single_app", "route_backend_collaboration.py")
    module_ast = ast.parse(route_source)

    stream_route_nodes = [
        node for node in ast.walk(module_ast)
        if isinstance(node, ast.FunctionDef) and node.name == "stream_collaboration_message_api"
    ]
    assert len(stream_route_nodes) == 1, "Expected exactly one stream_collaboration_message_api definition."
    stream_route_node = stream_route_nodes[0]

    raw_error_calls = [
        node for node in ast.walk(stream_route_node)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_serialize_stream_error"
    ]
    assert len(raw_error_calls) == 1, (
        "Shared stream errors must funnel through a single serializer so conversation_kind "
        f"can never be omitted, found {len(raw_error_calls)} raw _serialize_stream_error calls."
    )

    raw_error_call = raw_error_calls[0]
    keyword_names = {keyword.arg for keyword in raw_error_call.keywords if keyword.arg}
    assert "conversation_kind" in keyword_names, (
        "The shared stream error serializer must set conversation_kind."
    )
    assert "conversation_id" in keyword_names, (
        "The shared stream error serializer must set conversation_id."
    )

    conversation_kind_value = next(
        keyword.value for keyword in raw_error_call.keywords if keyword.arg == "conversation_kind"
    )
    assert isinstance(conversation_kind_value, ast.Name) and conversation_kind_value.id == "COLLABORATION_KIND", (
        "conversation_kind must use the shared COLLABORATION_KIND constant."
    )

    helper_nodes = [
        node for node in ast.walk(stream_route_node)
        if isinstance(node, ast.FunctionDef) and node.name == "collaboration_stream_error"
    ]
    assert len(helper_nodes) == 1, "Expected a single collaboration_stream_error helper."

    helper_call_count = sum(
        1 for node in ast.walk(stream_route_node)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "collaboration_stream_error"
    )
    assert helper_call_count >= 7, (
        f"Expected every shared stream failure path to use the helper, found {helper_call_count}."
    )

    assert "from collaboration_models import COLLABORATION_KIND" in route_source, (
        "Expected COLLABORATION_KIND to be imported from collaboration_models."
    )

    print("Collaboration stream error attribution passed!")
    return True


def test_version_supports_fix():
    """The application version must be at least the fix implementation version."""
    print("Testing application version...")
    assert_app_version_at_least(
        IMPLEMENTED_IN_VERSION,
        reason="Shared conversation reload and streaming fix requires this version or later.",
    )
    print("Application version check passed!")
    return True


if __name__ == "__main__":
    tests = [
        test_stream_view_resolves_through_blueprint_endpoint,
        test_stream_view_resolves_unprefixed_and_rejects_unknown,
        test_collaboration_route_uses_resolver_and_logs_failures,
        test_collaboration_stream_errors_always_carry_conversation_kind,
        test_select_conversation_skips_personal_messages_endpoint,
        test_collaboration_loader_keeps_personal_loader_side_effects,
        test_version_supports_fix,
    ]

    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            results.append(bool(test()))
        except Exception as error:
            print(f"Test failed: {error}")
            import traceback

            traceback.print_exc()
            results.append(False)

    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)

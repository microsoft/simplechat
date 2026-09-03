#!/usr/bin/env python3
"""
Functional test for V2 model identity and document search scope.
Version: 0.261.016
Implemented in: 0.261.016

Document search failed in the V2 chat page with "Something went wrong while streaming the
response" while working in the classic UI. Two request-shape defects were behind it, both of
the same kind as the earlier V2 payload bugs: the client sent a field the server could not
act on, and the server carried on rather than complaining.

1. A model is identified by FOUR fields together -- `model_endpoint_id`, `model_id`,
   `model_provider` and `model_deployment`. V2 sent only the deployment name, taken from the
   catalog's `option_value`. With `enable_multi_model_endpoints` on,
   `resolve_streaming_multi_endpoint_gpt_config` returns None when the endpoint id is
   missing, so every V2 request silently fell back to the legacy single-endpoint client --
   a different endpoint from the one shown in the picker.

2. The document scope was hardcoded to `'all'` and no workspace ids were ever sent. The
   server filters requested scope ids down to what the caller may see, so `'all'` with no
   ids covers only personal documents; and a deployment whose search path depends on the
   resolved scope gets an inconsistent request.

This test ensures the full model identity travels with every chat request, and that the
document scope is computed from the workspaces actually in play.
"""

import os
import re
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from test_support.versioning import assert_app_version_at_least

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V2_SRC = os.path.join(REPO_ROOT, "application", "v2_ui", "src")
APP = os.path.join(REPO_ROOT, "application", "single_app")


def read(*parts):
    with open(os.path.join(*parts), "r", encoding="utf-8") as handle:
        return handle.read()


def test_model_needs_more_than_a_deployment_name():
    """Establish the server's requirement rather than assuming it."""
    print("Testing the server's model resolution contract...")
    try:
        route = read(APP, "route_backend_chats.py")

        assert "def resolve_streaming_multi_endpoint_gpt_config" in route
        # All four fields are read from the request.
        for field in (
            "data.get('model_endpoint_id')",
            "data.get('model_id')",
            "data.get('model_provider')",
            "data.get('model_deployment')",
        ):
            assert field in route, f"Expected the route to read {field}"

        # And the combination is validated.
        assert (
            "raise ValueError('Selected model endpoint is missing for the streaming request.')"
            in route
        ), "model_id without model_endpoint_id is rejected, so they must be sent together"

        print("Model resolution contract test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_client_sends_the_whole_model_identity():
    """Sending only the deployment name drops silently to the legacy endpoint."""
    print("Testing model identity construction...")
    try:
        models = read(V2_SRC, "lib", "models.ts")
        for field in (
            "model_deployment",
            "model_id",
            "model_endpoint_id",
            "model_provider",
        ):
            assert field in models, f"Expected {field} in the model identity"

        # The pairing rule the server enforces.
        assert "identity.model_endpoint_id = endpointId" in models
        assert "if (modelId)" in models, (
            "model_id must only be sent alongside an endpoint id"
        )

        store = read(V2_SRC, "stores", "chatStore.ts")
        # The resolved identity now reaches the request through the shared selection rule,
        # which is also what suppresses it when an agent is selected. Following the
        # indirection keeps this assertion about the guarantee rather than about a call site.
        assert "buildSelectionFields" in store, (
            "The chat request must carry the resolved identity"
        )
        selection = read(V2_SRC, "lib", "chatRequestSelection.ts")
        assert "modelIdentityForSelection" in selection, (
            "The selection rule must resolve the full identity from the catalog"
        )

        # The original defect: only the deployment name was sent.
        assert "requestBody.model_deployment = options.modelDeployment" not in store, (
            "The deployment name alone does not identify a model"
        )

        print("Model identity test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_model_picker_keys_on_selection_key():
    """A deployment name can repeat across endpoints; selection_key cannot."""
    print("Testing model picker keying...")
    try:
        catalog = read(APP, "route_frontend_chats.py")
        # selection_key is scope:scopeId:endpointId:modelId.
        assert (
            "selection_key = f\"{scope_type}:{scope_id or ''}:{endpoint_id}:{model_id or deployment_name}\""
            in catalog
        ), "selection_key is what makes a catalog entry unique"

        models = read(V2_SRC, "lib", "models.ts")
        assert "modelSelectionKey" in models
        assert "model.selection_key" in models

        composer = read(V2_SRC, "components", "chat", "Composer.tsx")
        assert "modelSelectionKey(model as ModelCatalogEntry)" in composer, (
            "The picker must key on selection_key so the identity can be resolved back"
        )
        # The original defect: keyed on option_value, which is just the deployment name.
        assert "model.option_value as string) ??" not in composer, (
            "option_value is the deployment name and does not identify an endpoint"
        )

        print("Model picker keying test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_document_scope_is_computed_not_hardcoded():
    """The scope follows the workspaces in play, as the classic client does."""
    print("Testing document scope resolution...")
    try:
        classic = read(APP, "static", "js", "chat", "chat-messages.js")
        # The classic rules this mirrors.
        assert "let effectiveDocScope = 'all';" in classic
        assert "effectiveDocScope = 'personal';" in classic

        scope = read(V2_SRC, "lib", "documentScope.ts")
        assert "resolveDocumentScope" in scope
        assert "'personal'" in scope and "'all'" in scope

        store = read(V2_SRC, "stores", "chatStore.ts")
        assert "resolveDocumentScope" in store
        # The original defect: a constant carried on the composer options.
        assert "doc_scope: options.docScope" not in store, (
            "The scope must be computed, not carried as a fixed option"
        )

        print("Document scope test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_scope_ids_travel_with_the_scope():
    """The server filters requested ids, so a scope without them covers nothing."""
    print("Testing scope id transmission...")
    try:
        route = read(APP, "route_backend_chats.py")
        assert "def _get_authorized_chat_scope_context" in route, (
            "The server filters requested scope ids down to the caller's access"
        )
        assert "data.get('active_group_ids')" in route
        assert "data.get('active_public_workspace_ids')" in route

        scope = read(V2_SRC, "lib", "documentScope.ts")
        for field in (
            "active_group_ids",
            "active_group_id",
            "active_public_workspace_ids",
            "active_public_workspace_id",
        ):
            assert field in scope, f"Expected {field} to be sent with the scope"

        print("Scope id test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_retry_resolves_the_model_the_same_way():
    """A retry must not reintroduce the raw selection key as a deployment name."""
    print("Testing retry model handling...")
    try:
        store = read(V2_SRC, "stores", "chatStore.ts")
        retry = store[store.index("retryMessage: async") :]
        retry = retry[: retry.index("\n    },")]

        assert "buildSelectionFields" in retry, (
            "Retry must resolve the deployment name from the catalog, since the option "
            "value is a selection key rather than a model name"
        )
        assert "model: selection.model_deployment" in retry, (
            "The retry endpoint takes a flat deployment name, which the selection rule "
            "has already resolved"
        )
        assert "model: options?.modelDeployment" not in retry, (
            "Sending the selection key as the model name would not resolve"
        )

        print("Retry model test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_chat_type_stays_user_so_fact_memory_is_not_re_scoped():
    """A personal conversation must not write its extracted facts into a group scope.

    `chat_stream_api` turns `chat_type` into `scope_id`/`scope_type`, and those feed the
    fact-memory read and autosave. Sending 'group' because the user happens to have an
    active group selected would publish a personal conversation's facts to that group.

    The classic client looks like it sends 'group' in that situation, but its guard reads
    `window.activeChatTabType`, which is never assigned anywhere in the application -- so
    the branch is unreachable and V1 always sends 'user'.
    """
    print("Testing chat_type scoping...")
    try:
        route = read(APP, "route_backend_chats.py")

        # The server contract that makes this matter, read from the route.
        assert "if chat_type not in ('user', 'group'):" in route
        assert "scope_id = active_group_id if chat_type == 'group' else user_id" in route, (
            "chat_type no longer selects the scope id; this test's premise needs rechecking"
        )

        # V1's group branch is dead code: it is read but never assigned.
        legacy_dir = os.path.join(APP, "static", "js")
        assignment = re.compile(r"activeChatTabType\s*=(?!=)")
        comparison = re.compile(r"activeChatTabType\s*===")
        assignments = 0
        reads = 0
        for root, _dirs, files in os.walk(legacy_dir):
            for name in files:
                if not name.endswith(".js"):
                    continue
                text = read(root, name)
                assignments += len(assignment.findall(text))
                reads += len(comparison.findall(text))
        assert reads > 0, "Expected the classic client to still read activeChatTabType"
        assert assignments == 0, (
            "activeChatTabType is now assigned somewhere, so V1 can send chat_type='group'. "
            "Re-evaluate whether V2 should follow, keeping in mind that chat_type re-scopes "
            "fact memory writes to the group."
        )

        store = read(V2_SRC, "stores", "chatStore.ts")
        assert "chat_type: 'user'," in store, (
            "chat_type must stay 'user'; deriving it from the active group would move "
            "personal conversations' fact memory into a shared group scope"
        )

        # Document search is still widened to the group -- via the scope, not chat_type.
        scope = read(V2_SRC, "lib", "documentScope.ts")
        assert "chat_type" not in scope, (
            "Document scope must not set chat_type; widening the search and re-scoping the "
            "request are different things"
        )
        assert "active_group_ids: groupIds," in scope

        print("chat_type scoping test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_web_search_flag_matches_what_the_route_reads():
    """The web search toggle has to use the field name the streaming route reads."""
    print("Testing web search request contract...")
    try:
        route = read(APP, "route_backend_chats.py")

        # The streaming route reads the flag and gates the search on it directly, with no
        # enclosing condition, so the flag alone decides whether a web search happens.
        assert "web_search_enabled = data.get('web_search_enabled')" in route, (
            "The streaming route no longer reads web_search_enabled from the request"
        )
        assert "if web_search_enabled:" in route, (
            "The route no longer gates the web search on the request flag"
        )
        # A string 'true' is accepted too, but a real boolean is what the client sends.
        assert "if isinstance(web_search_enabled, str):" in route

        store = read(V2_SRC, "stores", "chatStore.ts")
        assert "web_search_enabled: options.webSearch," in store, (
            "The composer's Web toggle must be sent as web_search_enabled"
        )

        # The button is only offered when the capability is actually on; `enabled` is a
        # strict identity check so a missing flag hides the control rather than showing a
        # button that silently does nothing server-side.
        gating = read(V2_SRC, "lib", "composerGating.ts")
        assert "return features?.[key] === true;" in gating, (
            "Capability gating must be strict, or the Web button appears for deployments "
            "where enable_web_search is off and the server discards the request"
        )
        assert "showWeb: enabled(features, 'enable_web_search')" in gating

        print("Web search request contract test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_version_is_at_least_implementation_version():
    """The fix must be present in at least the version that introduced it."""
    print("Testing application version...")
    try:
        assert_app_version_at_least("0.261.016")
        print("Application version test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


if __name__ == "__main__":
    tests = [
        test_model_needs_more_than_a_deployment_name,
        test_client_sends_the_whole_model_identity,
        test_model_picker_keys_on_selection_key,
        test_document_scope_is_computed_not_hardcoded,
        test_scope_ids_travel_with_the_scope,
        test_retry_resolves_the_model_the_same_way,
        test_chat_type_stays_user_so_fact_memory_is_not_re_scoped,
        test_web_search_flag_matches_what_the_route_reads,
        test_version_is_at_least_implementation_version,
    ]

    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        results.append(test())

    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)

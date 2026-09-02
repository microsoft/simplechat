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
        assert "modelIdentityForSelection" in store, (
            "The chat request must carry the resolved identity"
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

        assert "modelIdentityForSelection" in retry, (
            "Retry must resolve the deployment name from the catalog, since the option "
            "value is a selection key rather than a model name"
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
        test_version_is_at_least_implementation_version,
    ]

    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        results.append(test())

    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)

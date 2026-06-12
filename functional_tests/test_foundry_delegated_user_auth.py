# test_foundry_delegated_user_auth.py
#!/usr/bin/env python3
"""
Functional test for Foundry delegated user authentication.
Version: 0.241.196
Implemented in: 0.241.185

This test ensures that Foundry agents and workflows default to signed-in user
Foundry access, preserve delegated auth through payload sanitization, and do
not inherit saved model endpoint managed identity, service principal, or API-key
secrets unless an agent explicitly opts into supported Entra service modes.

The Foundry auth-required stream rendering regression was added in 0.241.186.
Foundry workflow agent-reference support was added in 0.241.192.
Foundry agent/workflow API-key invocation was restricted to Entra/RBAC in 0.241.196.
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_FILE = ROOT / "application" / "single_app" / "foundry_agent_runtime.py"
LOADER_FILE = ROOT / "application" / "single_app" / "semantic_kernel_loader.py"
MODELS_ROUTE_FILE = ROOT / "application" / "single_app" / "route_backend_models.py"
MODEL_ENDPOINT_CLIENTS_FILE = ROOT / "application" / "single_app" / "model_endpoint_clients.py"
CHAT_ROUTE_FILE = ROOT / "application" / "single_app" / "route_backend_chats.py"
CHAT_STREAMING_JS_FILE = ROOT / "application" / "single_app" / "static" / "js" / "chat" / "chat-streaming.js"
MODAL_JS_FILE = ROOT / "application" / "single_app" / "static" / "js" / "agent_modal_stepper.js"
MODAL_HTML_FILE = ROOT / "application" / "single_app" / "templates" / "_agent_modal.html"
KEYVAULT_FILE = ROOT / "application" / "single_app" / "functions_keyvault.py"
AGENT_PAYLOAD_FILE = ROOT / "application" / "single_app" / "functions_agent_payload.py"
CONFIG_FILE = ROOT / "application" / "single_app" / "config.py"
FIX_DOC_FILE = ROOT / "docs" / "explanation" / "fixes" / "FOUNDRY_AUTH_REQUIRED_STREAM_MESSAGE_FIX.md"
API_KEY_FIX_DOC_FILE = ROOT / "docs" / "explanation" / "fixes" / "FOUNDRY_AGENT_WORKFLOW_API_KEY_AUTH_FIX.md"
WORKFLOW_API_KEY_FIX_DOC_FILE = ROOT / "docs" / "explanation" / "fixes" / "FOUNDRY_WORKFLOW_API_KEY_APPLICATION_PROTOCOL_FIX.md"
ENTRA_BOUNDARY_FIX_DOC_FILE = ROOT / "docs" / "explanation" / "fixes" / "FOUNDRY_AGENT_WORKFLOW_ENTRA_AUTH_BOUNDARY_FIX.md"


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def assert_contains(path: Path, expected: str) -> None:
    content = read_text(path)
    if expected not in content:
        raise AssertionError(f"Expected to find {expected!r} in {path}")


def assert_not_contains(path: Path, unexpected: str) -> None:
    content = read_text(path)
    if unexpected in content:
        raise AssertionError(f"Did not expect to find {unexpected!r} in {path}")


def test_runtime_defaults_to_delegated_user_auth() -> None:
    """Validate runtime auth defaults and delegated token behavior."""
    print("Testing Foundry runtime delegated user auth defaults...")

    runtime_content = read_text(RUNTIME_FILE)
    expected_snippets = [
        "class FoundryAgentUserAuthenticationRequired(FoundryAgentInvocationError)",
        "class DelegatedUserAccessTokenCredential",
        "def _resolve_jwt_expires_on(token: str) -> int:",
        "return int(time.time()) + 300",
        "def _resolve_foundry_authentication_type(",
        "auth_type = str(auth_type or \"delegated_user\").strip().lower()",
        "if auth_type in {\"user\", \"delegated\", \"user_delegated\", \"signed_in_user\"}:",
        "return \"delegated_user\"",
        "if auth_type in {\"key\", \"api_key\", \"apikey\"}:",
        "return \"api_key\"",
        "Foundry agent and workflow invocation requires Microsoft Entra ID/RBAC.",
        "if auth_type in {\"managed_identity\", \"service_principal\"}:",
        "FOUNDRY_DELEGATED_AUTH_REQUIRED_MESSAGE = (",
        "async def _build_foundry_rest_headers(",
        "headers[\"Authorization\"] = f\"Bearer {token.token}\"",
        "token_result = get_valid_access_token_for_plugins(scopes=[scope])",
        "error_message = FOUNDRY_DELEGATED_AUTH_REQUIRED_MESSAGE",
        "auth_response[\"message\"] = error_message",
        "raise FoundryAgentUserAuthenticationRequired(error_message, auth_response=auth_response)",
    ]
    for snippet in expected_snippets:
        assert_contains(RUNTIME_FILE, snippet)

    forbidden_snippets = [
        "class FoundryApiKeyCredential",
        "def _resolve_foundry_api_key(",
        "headers[\"api-key\"] = credential.api_key",
        "Invoking API-key workflow",
    ]
    for snippet in forbidden_snippets:
        if snippet in runtime_content:
            raise AssertionError(f"Foundry agent runtime still contains stale API-key support: {snippet}")

    delegated_branch_start = runtime_content.index('if auth_type == "delegated_user":')
    managed_branch_start = runtime_content.index('managed_identity_type =')
    delegated_branch = runtime_content[delegated_branch_start:managed_branch_start]
    if "client_secret" in delegated_branch or "AsyncClientSecretCredential" in delegated_branch:
        raise AssertionError("Delegated Foundry auth must not use saved service principal secrets.")
    if 'if client_secret and auth_type != "managed_identity":' in runtime_content:
        raise AssertionError("Foundry delegated auth must not fall back to service principal secrets.")

    print("Runtime delegated user auth defaults verified.")


def test_endpoint_enrichment_keeps_model_auth_separate() -> None:
    """Validate saved model endpoint auth does not become Foundry runtime auth."""
    print("Testing Foundry endpoint enrichment auth separation...")

    loader_content = read_text(LOADER_FILE)
    expected_snippets = [
        'saved_agent_auth_type = str(',
        'or "delegated_user"',
        'foundry_settings["authentication_type"] = "delegated_user"',
        'foundry_settings.pop("api_key", None)',
        'foundry_settings.pop("key", None)',
        'if foundry_settings.get("authentication_type") in {"managed_identity", "service_principal"}:',
        'foundry_settings.pop("managed_identity_type", None)',
        'foundry_settings.pop("managed_identity_client_id", None)',
        'foundry_settings.pop("tenant_id", None)',
        'foundry_settings.pop("client_id", None)',
        'foundry_settings.pop("client_secret", None)',
        'foundry_settings["foundry_scope"] = foundry_settings.get("foundry_scope") or auth.get("foundry_scope") or ""',
    ]
    for snippet in expected_snippets:
        assert_contains(LOADER_FILE, snippet)

    forbidden_snippets = [
        'supports_foundry_api_key = agent_type in {"new_foundry", "foundry_workflow"}',
        'foundry_settings["api_key"] = auth.get("api_key")',
        'foundry_settings["authentication_type"] = "api_key"',
    ]
    for snippet in forbidden_snippets:
        if snippet in loader_content:
            raise AssertionError(f"Endpoint enrichment still promotes API-key Foundry auth: {snippet}")

    advanced_auth_branch_start = loader_content.index('if foundry_settings.get("authentication_type") in {"managed_identity", "service_principal"}:')
    delegated_auth_branch_start = loader_content.index('else:', advanced_auth_branch_start)
    advanced_auth_branch = loader_content[advanced_auth_branch_start:delegated_auth_branch_start]
    if 'foundry_settings["client_secret"] = auth.get("client_secret")' not in advanced_auth_branch:
        raise AssertionError("Explicit service principal Foundry auth should still copy the secret reference.")

    print("Endpoint auth separation verified.")


def test_api_key_model_endpoints_do_not_back_foundry_agent_invocation() -> None:
    """Validate API keys remain model-endpoint-only and do not back Foundry agents."""
    print("Testing API-key boundary between model endpoints and Foundry agents...")

    assert_contains(MODEL_ENDPOINT_CLIENTS_FILE, 'headers["api-key"] = self.api_key')
    assert_contains(RUNTIME_FILE, "API keys are only supported for model endpoint inference.")
    assert_contains(MODELS_ROUTE_FILE, '"authentication_type": "delegated_user",')
    assert_contains(MODAL_JS_FILE, "const foundryAuthenticationType = 'delegated_user';")

    route_forbidden = [
        'supports_api_key = provider in {"new_foundry", "foundry_workflow"}',
        'authentication_type = "api_key" if supports_api_key and endpoint_auth_type in {"api_key", "key"} else "delegated_user"',
        '"api_key": auth.get("api_key") or "",',
    ]
    for snippet in route_forbidden:
        assert_not_contains(MODELS_ROUTE_FILE, snippet)

    modal_forbidden = [
        "supportsFoundryApiKey",
        "manualFoundryApiKey",
        "agent-foundry-api-key",
        "project API key",
    ]
    for snippet in modal_forbidden:
        assert_not_contains(MODAL_JS_FILE, snippet)
        assert_not_contains(MODAL_HTML_FILE, snippet)

    print("API-key model endpoint boundary verified.")


def test_manual_api_key_modal_and_agent_secret_storage_removed() -> None:
    """Validate Foundry app/workflow API keys are not accepted or stored."""
    print("Testing removal of Foundry application/workflow API-key configuration...")

    keyvault_forbidden = [
        '("other_settings", "new_foundry", "api_key")',
        '("other_settings", "foundry_workflow", "api_key")',
    ]
    for snippet in keyvault_forbidden:
        assert_not_contains(KEYVAULT_FILE, snippet)

    payload_snippets = [
        "def _normalize_foundry_entra_auth_settings(foundry_settings: Dict[str, Any]) -> None:",
        'foundry_settings["authentication_type"] = "delegated_user"',
        'foundry_settings.pop("api_key", None)',
        'foundry_settings.pop("key", None)',
        'sanitized["other_settings"]["new_foundry"] = _strip_empty_values(new_foundry_settings)',
        'sanitized["other_settings"]["foundry_workflow"] = _strip_empty_values(workflow_settings)',
    ]
    for snippet in payload_snippets:
        assert_contains(AGENT_PAYLOAD_FILE, snippet)

    assert_not_contains(AGENT_PAYLOAD_FILE, '"api_key": 2048,')
    print("Foundry application/workflow API-key configuration removal verified.")


def test_discovery_and_streaming_return_auth_required_contract() -> None:
    """Validate backend routes expose actionable delegated auth failures."""
    print("Testing delegated auth-required API contract...")

    model_route_snippets = [
        '"authentication_type": "delegated_user",',
        "except FoundryAgentUserAuthenticationRequired as exc:",
        '"auth_required": True',
        '"scopes": auth_response.get("scopes") or []',
        'payload["consent_url"] = auth_response.get("consent_url") or auth_response.get("auth_url")',
        'payload["auth_url"] = auth_response.get("auth_url") or auth_response.get("consent_url")',
    ]
    for snippet in model_route_snippets:
        assert_contains(MODELS_ROUTE_FILE, snippet)

    chat_route_snippets = [
        "FoundryAgentUserAuthenticationRequired",
        "if isinstance(stream_error, FoundryAgentUserAuthenticationRequired):",
        "'auth_required': True",
        "'scopes': auth_response.get('scopes') or []",
        "error_payload['consent_url'] = auth_response.get('consent_url') or auth_response.get('auth_url')",
        "error_payload['auth_url'] = auth_response.get('auth_url') or auth_response.get('consent_url')",
    ]
    for snippet in chat_route_snippets:
        assert_contains(CHAT_ROUTE_FILE, snippet)

    print("Auth-required backend contract verified.")


def test_streaming_client_renders_foundry_auth_required_link_safely() -> None:
    """Validate chat streaming renders Foundry delegated auth failures safely."""
    print("Testing Foundry auth-required stream rendering...")

    streaming_js_content = read_text(CHAT_STREAMING_JS_FILE)
    expected_snippets = [
        "function normalizeStreamHttpUrl(value) {",
        "function buildStreamingRequestError(errorData, status) {",
        "streamError.streamErrorData = streamErrorData;",
        "throw buildStreamingRequestError(errData, response.status);",
        "handleStreamError(tempAiMessageId, data.partial_content || accumulatedContent, data.error, data);",
        "handleStreamError(tempAiMessageId, accumulatedContent, error.message, error);",
        "title.textContent = authRequired ? 'Foundry access required:' : 'Stream interrupted:';",
        "errorBanner.appendChild(document.createTextNode(` ${displayMessage}`));",
        "authLink.textContent = 'Sign in or grant Foundry access';",
        "detailText.textContent = authRequired",
    ]
    for snippet in expected_snippets:
        assert_contains(CHAT_STREAMING_JS_FILE, snippet)

    if "errorBanner.innerHTML" in streaming_js_content:
        raise AssertionError("Stream error banner must not inject server-provided error text with innerHTML.")
    if "Microsoft 365 resources like Outlook email" in read_text(RUNTIME_FILE):
        raise AssertionError("Foundry runtime must not surface the generic Microsoft 365 consent message.")

    print("Foundry auth-required stream rendering verified.")


def test_modal_uses_delegated_user_auth_and_safe_consent_link() -> None:
    """Validate the modal stores delegated auth and renders auth links safely."""
    print("Testing modal delegated auth payload and consent link handling...")

    modal_js_snippets = [
        "function normalizeHttpUrl(value) {",
        "fetchError.authRequired = payload.auth_required === true;",
        "fetchError.authUrl = payload.auth_url || payload.consent_url || '';",
        "const authUrl = normalizeHttpUrl(error.authUrl);",
        "authLink.textContent = 'Sign in or grant Foundry access';",
        "statusEl.appendChild(document.createTextNode('Foundry access requires sign-in or consent. '));",
        "authentication_type: 'delegated_user'",
        "Classic Foundry agents use the signed-in user\\'s Foundry access. Actions are disabled.",
        "New Foundry applications use the signed-in user\\'s Foundry access. Actions are disabled.",
        "Foundry workflows use the signed-in user\\'s Foundry access. Actions are disabled.",
    ]
    for snippet in modal_js_snippets:
        assert_contains(MODAL_JS_FILE, snippet)

    modal_html_snippets = [
        "Foundry agents and workflows run as the signed-in user",
        "Fetch and runtime access use the signed-in user's Foundry permissions.",
    ]
    for snippet in modal_html_snippets:
        assert_contains(MODAL_HTML_FILE, snippet)

    print("Modal delegated auth behavior verified.")


def test_version_bumped_for_delegated_foundry_auth() -> None:
    """Validate version traceability for this auth model change."""
    assert_contains(CONFIG_FILE, 'VERSION = "0.241.196"')
    assert_contains(FIX_DOC_FILE, "Fixed/Implemented in version: **0.241.186**")
    assert_contains(API_KEY_FIX_DOC_FILE, "Superseded in version: **0.241.196**")
    assert_contains(WORKFLOW_API_KEY_FIX_DOC_FILE, "Superseded in version: **0.241.196**")
    assert_contains(ENTRA_BOUNDARY_FIX_DOC_FILE, "Fixed/Implemented in version: **0.241.196**")


def run_tests() -> bool:
    tests = [
        test_runtime_defaults_to_delegated_user_auth,
        test_endpoint_enrichment_keeps_model_auth_separate,
        test_api_key_model_endpoints_do_not_back_foundry_agent_invocation,
        test_manual_api_key_modal_and_agent_secret_storage_removed,
        test_discovery_and_streaming_return_auth_required_contract,
        test_streaming_client_renders_foundry_auth_required_link_safely,
        test_modal_uses_delegated_user_auth_and_safe_consent_link,
        test_version_bumped_for_delegated_foundry_auth,
    ]
    results = []

    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            test()
            print("Test passed")
            results.append(True)
        except Exception as exc:
            print(f"Test failed: {exc}")
            import traceback

            traceback.print_exc()
            results.append(False)

    success = all(results)
    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    return success


if __name__ == "__main__":
    import sys

    sys.exit(0 if run_tests() else 1)

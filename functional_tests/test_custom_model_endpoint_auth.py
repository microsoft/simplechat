#!/usr/bin/env python3
"""
Functional test for Custom model endpoint authentication schemes.
Version: 0.261.020
Implemented in: 0.261.020

Custom endpoints supported one authentication scheme: an API key sent in whichever
header the built-in providers happened to use. That covers OpenAI and Anthropic
and nothing else. A gateway expecting "x-goog-api-key", a corporate gateway
issuing short-lived OAuth2 tokens, and an appliance requiring a client
certificate were all unreachable.

These tests ensure that:
  * the API key header name and value prefix are configurable, so one scheme
    covers OpenAI, Anthropic, Google, and bespoke gateway headers,
  * static bearer tokens work,
  * OAuth2 client credentials are fetched, cached, and refreshed before expiry,
  * an OAuth2 token endpoint is validated against the same outbound policy as the
    inference endpoint, so it cannot become an unchecked request target,
  * mTLS client certificates are referenced by path, never stored in settings,
  * unsupported and incomplete auth configurations are still rejected.
"""

import os
import socket
import sys
from unittest.mock import patch

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "application",
        "single_app",
    )
)

from test_support.versioning import assert_app_version_at_least

from functions_model_endpoint_auth import (
    build_api_key_headers,
    clear_oauth2_token_cache,
    fetch_oauth2_client_credentials_token,
    normalize_custom_endpoint_auth_type,
    resolve_client_certificate,
    resolve_custom_endpoint_credentials,
)
from functions_model_endpoint_providers import (
    MODEL_ENDPOINT_API_TYPE_ANTHROPIC,
    MODEL_ENDPOINT_API_TYPE_OPENAI,
    get_model_endpoint_provider,
)
from functions_model_endpoint_validation import (
    ModelEndpointValidationError,
    validate_custom_model_endpoint,
)


class _FakeResponse:
    def __init__(self, payload, status_code=200, text=""):
        self._payload = payload
        self.status_code = status_code
        self.text = text

    def json(self):
        return self._payload


class _FakeTokenClient:
    """Stand-in for the pinned HTTP client that records token requests."""

    instances = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.requests = []
        self.response = _FakeResponse({"access_token": "issued-token", "expires_in": 3600})
        _FakeTokenClient.instances.append(self)

    def post(self, url, data=None):
        self.requests.append((url, data))
        return self.response

    def close(self):
        pass


# The token endpoint is now revalidated at request time, which resolves the
# hostname. These tests use documentation hostnames that do not resolve, so DNS is
# stubbed to a public address; the policy checks themselves still run for real.
PUBLIC_ADDRESS_INFO = [
    (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.216.34", 443))
]


def _patch_public_dns():
    return patch(
        "functions_model_endpoint_validation.socket.getaddrinfo",
        return_value=PUBLIC_ADDRESS_INFO,
    )


def test_api_key_header_is_configurable():
    """One API key scheme must cover every provider's header convention."""
    print("Testing API key header customization...")
    try:
        cases = [
            ("Anthropic default", {"api_key": "sk-ant"}, "x-api-key", "", {"x-api-key": "sk-ant"}),
            (
                "OpenAI default",
                {"api_key": "sk-abc"},
                "Authorization",
                "Bearer",
                {"Authorization": "Bearer sk-abc"},
            ),
            (
                "Google override",
                {"api_key": "AIza", "api_key_header": "x-goog-api-key"},
                "Authorization",
                "Bearer",
                {"x-goog-api-key": "AIza"},
            ),
            (
                "Gateway with prefix",
                {"api_key": "k", "api_key_header": "X-Corp-Key", "api_key_prefix": "Token"},
                "Authorization",
                "Bearer",
                {"X-Corp-Key": "Token k"},
            ),
        ]
        for label, auth, default_header, default_prefix, expected in cases:
            headers = build_api_key_headers(auth, default_header, default_prefix)
            assert headers == expected, f"{label}: got {headers}, expected {expected}"

        # The registry supplies the per-provider defaults.
        anthropic = get_model_endpoint_provider(MODEL_ENDPOINT_API_TYPE_ANTHROPIC)
        assert anthropic.default_api_key_header == "x-api-key"
        assert anthropic.default_api_key_prefix == ""
        openai = get_model_endpoint_provider(MODEL_ENDPOINT_API_TYPE_OPENAI)
        assert openai.default_api_key_header == "Authorization"
        assert openai.default_api_key_prefix == "Bearer"

        print(f"API key header customization correct for {len(cases)} conventions")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_bearer_and_api_key_credentials_resolve():
    """Bearer tokens and API keys must resolve to the right SDK inputs."""
    print("Testing credential resolution...")
    try:
        credential, headers = resolve_custom_endpoint_credentials(
            {"type": "bearer", "bearer_token": "tok-123"}
        )
        assert credential == "tok-123" and headers == {}

        # An Authorization-header key rides on the SDK's own credential argument.
        credential, headers = resolve_custom_endpoint_credentials(
            {"type": "api_key", "api_key": "sk-abc"},
            default_api_key_header="Authorization",
            default_api_key_prefix="Bearer",
        )
        assert credential == "sk-abc" and headers == {}

        # A non-Authorization header must be sent explicitly.
        credential, headers = resolve_custom_endpoint_credentials(
            {"type": "api_key", "api_key": "sk-ant"},
            default_api_key_header="x-api-key",
        )
        assert credential == "sk-ant"
        assert headers == {"x-api-key": "sk-ant"}

        assert normalize_custom_endpoint_auth_type("key") == "api_key"
        assert normalize_custom_endpoint_auth_type("managed_identity") == ""

        print("Credential resolution passed")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_oauth2_tokens_are_fetched_and_cached():
    """OAuth2 tokens must be fetched once and reused until near expiry."""
    print("Testing OAuth2 client credentials...")
    try:
        clear_oauth2_token_cache()
        _FakeTokenClient.instances = []

        auth = {
            "type": "oauth2_client_credentials",
            "token_url": "https://auth.example.com/oauth2/token",
            "client_id": "client-1",
            "client_secret": "secret-1",
            "scope": "inference.read",
        }

        with _patch_public_dns():
            token = fetch_oauth2_client_credentials_token(
                auth, http_client_factory=_FakeTokenClient
            )
            assert token == "issued-token"
            assert len(_FakeTokenClient.instances) == 1

            request_url, payload = _FakeTokenClient.instances[0].requests[0]
            assert request_url == auth["token_url"]
            assert payload["grant_type"] == "client_credentials"
            assert payload["scope"] == "inference.read"

            # A second call is served from the cache, so no new request is made.
            cached_token = fetch_oauth2_client_credentials_token(
                auth, http_client_factory=_FakeTokenClient
            )
            assert cached_token == "issued-token"
            assert len(_FakeTokenClient.instances) == 1, "Token must be cached."

            # Clearing the cache forces a new request.
            clear_oauth2_token_cache()
            fetch_oauth2_client_credentials_token(
                auth, http_client_factory=_FakeTokenClient
            )
            assert len(_FakeTokenClient.instances) == 2
        clear_oauth2_token_cache()
        print("OAuth2 fetch, cache, and refresh passed")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_oauth2_failures_are_sanitized():
    """A failing token endpoint must not leak its response to the caller."""
    print("Testing OAuth2 failure sanitization...")
    try:
        clear_oauth2_token_cache()

        class FailingTokenClient(_FakeTokenClient):
            def __init__(self, **kwargs):
                super().__init__(**kwargs)
                self.response = _FakeResponse(
                    {}, status_code=401, text='{"error":"invalid_client","secret":"leak-me"}'
                )

        auth = {
            "type": "oauth2_client_credentials",
            "token_url": "https://auth.example.com/oauth2/token",
            "client_id": "client-1",
            "client_secret": "secret-1",
        }
        try:
            with _patch_public_dns():
                fetch_oauth2_client_credentials_token(
                    auth, http_client_factory=FailingTokenClient
                )
        except RuntimeError as exc:
            assert "leak-me" not in str(exc)
            assert "invalid_client" not in str(exc)
            assert "reference" in str(exc), "A correlation id should be offered."
        else:
            raise AssertionError("A failing token endpoint must raise.")

        clear_oauth2_token_cache()
        print("OAuth2 failures sanitized")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_token_endpoint_is_revalidated_at_request_time():
    """A blocked token URL must be refused when the token is fetched, not only when saved.

    Validating only at save time leaves the request itself unguarded: settings can
    be written by another path, restored from backup, or changed after validation.
    CodeQL flagged this as a server-side request forgery, correctly.
    """
    print("Testing request-time token endpoint validation...")
    try:
        clear_oauth2_token_cache()

        for blocked_url in (
            "https://169.254.169.254/token",
            "https://127.0.0.1/token",
            "https://metadata.google.internal/token",
            "http://auth.example.com/token",
        ):
            auth = {
                "type": "oauth2_client_credentials",
                "token_url": blocked_url,
                "client_id": "client-1",
                "client_secret": "secret-1",
            }
            _FakeTokenClient.instances = []
            try:
                fetch_oauth2_client_credentials_token(
                    auth, http_client_factory=_FakeTokenClient
                )
            except Exception:
                # The request must be refused before any client is constructed.
                assert not _FakeTokenClient.instances, (
                    f"{blocked_url} reached the network before being refused."
                )
                continue
            raise AssertionError(f"{blocked_url} must be refused at request time.")

        clear_oauth2_token_cache()
        print("Token endpoint revalidated at request time")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_oauth2_token_endpoint_is_policy_checked():
    """The token endpoint is a separate host and must satisfy the same policy."""
    print("Testing OAuth2 token endpoint policy...")
    try:
        endpoint = {
            "name": "Gateway",
            "provider": "custom",
            "api_type": "openai",
            "connection": {"endpoint": "https://api.example.com/v1"},
            "auth": {
                "type": "oauth2_client_credentials",
                # A token endpoint pointing at cloud metadata must be refused.
                "token_url": "https://169.254.169.254/token",
                "client_id": "c",
                "client_secret": "s",
            },
            "models": [{"modelName": "gpt-4o"}],
        }
        try:
            validate_custom_model_endpoint(endpoint, {})
        except ModelEndpointValidationError:
            pass
        else:
            raise AssertionError("A metadata-address token endpoint must be refused.")

        print("Token endpoint is policy checked")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_incomplete_and_unsupported_auth_is_rejected():
    """Missing credentials and unsupported schemes must still be refused."""
    print("Testing auth rejection...")
    try:
        for auth in (
            {"type": "managed_identity"},
            {"type": "api_key"},
            {"type": "bearer"},
        ):
            try:
                resolve_custom_endpoint_credentials(auth)
            except ValueError:
                continue
            raise AssertionError(f"{auth} must be rejected.")

        base_endpoint = {
            "name": "Gateway",
            "provider": "custom",
            "api_type": "openai",
            "connection": {"endpoint": "https://api.example.com/v1"},
            "models": [{"modelName": "gpt-4o"}],
        }

        # Managed identity is not a Custom endpoint scheme.
        try:
            validate_custom_model_endpoint(
                {**base_endpoint, "auth": {"type": "managed_identity"}}, {}
            )
        except ModelEndpointValidationError:
            pass
        else:
            raise AssertionError("Managed identity must be refused for Custom endpoints.")

        # OAuth2 without its required fields is incomplete.
        try:
            validate_custom_model_endpoint(
                {**base_endpoint, "auth": {"type": "oauth2_client_credentials"}}, {}
            )
        except ModelEndpointValidationError:
            pass
        else:
            raise AssertionError("Incomplete OAuth2 configuration must be refused.")

        print("Unsupported and incomplete auth rejected")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_mtls_certificates_are_referenced_by_path():
    """A client private key must never be stored in settings."""
    print("Testing mTLS certificate handling...")
    try:
        assert resolve_client_certificate({}) is None
        assert resolve_client_certificate({"client_cert_path": "/etc/ssl/client.pem"}) == (
            "/etc/ssl/client.pem"
        )
        assert resolve_client_certificate(
            {"client_cert_path": "/c.pem", "client_key_path": "/k.pem"}
        ) == ("/c.pem", "/k.pem")

        # The module must not offer any way to supply key material inline, so a
        # private key cannot end up written to the configuration database.
        auth_module_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "application",
            "single_app",
            "functions_model_endpoint_auth.py",
        )
        with open(auth_module_path, encoding="utf-8") as source_file:
            source = source_file.read()
        assert "client_key_pem" not in source
        assert "private_key" not in source

        print("mTLS certificates referenced by path only")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_version_bumped():
    """Authentication schemes ship at or after their implementation version."""
    print("Testing config version...")
    try:
        assert_app_version_at_least("0.261.020")
        print("Config version check passed")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


if __name__ == "__main__":
    tests = [
        test_api_key_header_is_configurable,
        test_bearer_and_api_key_credentials_resolve,
        test_oauth2_tokens_are_fetched_and_cached,
        test_oauth2_failures_are_sanitized,
        test_token_endpoint_is_revalidated_at_request_time,
        test_oauth2_token_endpoint_is_policy_checked,
        test_incomplete_and_unsupported_auth_is_rejected,
        test_mtls_certificates_are_referenced_by_path,
        test_version_bumped,
    ]

    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        results.append(test())

    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)

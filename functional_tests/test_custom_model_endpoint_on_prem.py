#!/usr/bin/env python3
"""
Functional test for on-premises Custom model endpoint support.
Version: 0.261.016
Implemented in: 0.261.016

On-premises inference was effectively unreachable. The administrator gate named
"allow private Custom endpoint hosts" did not permit the two most common
on-premises address forms -- an IP literal and a short single-label host name --
and rejected both with a message claiming the URL was an IP address even when it
was not. Plaintext HTTP had no gate at all.

Separately, the outbound transport pinned trust to certifi's public roots and
deliberately ignored ambient environment variables, so an on-premises gateway
with an internally issued certificate could never be trusted.

These tests ensure that:
  * with the gate off nothing changes, so the secure default is preserved,
  * with the gate on, IP literals, short host names, private ranges, and -- with
    a second explicit gate -- plaintext HTTP are accepted,
  * loopback and cloud metadata addresses stay rejected even with the gate on,
  * an administrator can name a CA bundle, a missing bundle fails loudly rather
    than silently weakening trust, and ambient environment variables still cannot
    widen what is trusted,
  * saving configuration tolerates a name that does not resolve yet, while a
    policy violation is never tolerated.
"""

import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "application",
        "single_app",
    )
)

from test_support.versioning import assert_app_version_at_least

from functions_model_endpoint_validation import (
    ModelEndpointUnresolvableError,
    ModelEndpointValidationError,
    validate_custom_model_endpoint_url,
)
from model_endpoint_clients import build_custom_endpoint_ssl_context


ON_PREM_URLS = [
    "https://10.20.30.40/v1",
    "https://10.20.30.40:8443/v1",
    "https://llm-gateway/v1",
    "https://llm.corp.internal/v1",
]

ALWAYS_BLOCKED_URLS = [
    "https://127.0.0.1/v1",
    "https://169.254.169.254/v1",
    "https://metadata.google.internal/v1",
    "https://localhost/v1",
]


def _validate(url, *, private=False, insecure=False):
    return validate_custom_model_endpoint_url(
        url,
        allow_private=private,
        allow_insecure=insecure,
        require_resolvable=False,
    )


def test_gate_off_preserves_the_secure_default():
    """With the gate off, every on-premises address form stays rejected."""
    print("Testing default-deny behaviour...")
    try:
        for url in ON_PREM_URLS + ["http://llm.corp.example.com/v1"]:
            try:
                _validate(url)
            except ModelEndpointValidationError:
                continue
            raise AssertionError(f"{url} must be rejected when the gate is off.")

        # A public HTTPS endpoint is unaffected.
        assert _validate("https://api.openai.com/v1") == "https://api.openai.com/v1"

        print(f"Default-deny held for {len(ON_PREM_URLS) + 1} address forms")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_gate_on_enables_on_prem_addresses():
    """With the gate on, on-premises address forms are accepted."""
    print("Testing on-premises address acceptance...")
    try:
        for url in ON_PREM_URLS:
            resolved = _validate(url, private=True)
            assert resolved, f"{url} must be accepted when the gate is on."

        # Plaintext HTTP needs its own second gate, not just the private gate.
        plaintext = "http://llm.corp.example.com/v1"
        try:
            _validate(plaintext, private=True)
        except ModelEndpointValidationError:
            pass
        else:
            raise AssertionError("Plaintext HTTP must require its own explicit gate.")

        assert _validate(plaintext, private=True, insecure=True) == plaintext

        print(f"On-premises addresses accepted for {len(ON_PREM_URLS)} forms")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_dangerous_targets_stay_blocked_with_the_gate_on():
    """Loopback and cloud metadata must be rejected even with the gate on."""
    print("Testing that dangerous targets stay blocked...")
    try:
        for url in ALWAYS_BLOCKED_URLS:
            try:
                _validate(url, private=True, insecure=True)
            except ModelEndpointValidationError:
                continue
            raise AssertionError(
                f"{url} must stay blocked even with every gate enabled."
            )

        print(f"All {len(ALWAYS_BLOCKED_URLS)} dangerous targets stay blocked")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_rejection_messages_are_accurate():
    """A short host name must not be described as an IP address."""
    print("Testing rejection message accuracy...")
    try:
        try:
            _validate("https://llm-gateway/v1")
        except ModelEndpointValidationError as exc:
            message = str(exc)
            assert "not an IP address" not in message, (
                f"A short host name must not be called an IP address: {message!r}"
            )
            assert "short host name" in message, (
                f"The message should say what to enable: {message!r}"
            )
        else:
            raise AssertionError("Expected a rejection for a short host name.")

        print("Rejection messages are accurate")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_custom_ca_bundle_is_honoured_and_fails_loudly():
    """An internal CA can be trusted explicitly, but never silently."""
    print("Testing CA bundle handling...")
    try:
        import certifi

        # The default context ignores ambient environment variables, so nothing
        # outside SimpleChat's configuration can widen what is trusted.
        original_cert_file = os.environ.get("SSL_CERT_FILE")
        os.environ["SSL_CERT_FILE"] = os.path.join("C:" + os.sep, "nonexistent", "evil.pem")
        try:
            default_context = build_custom_endpoint_ssl_context("")
            assert default_context.get_ca_certs(), "The default context must trust public roots."
        finally:
            if original_cert_file is None:
                os.environ.pop("SSL_CERT_FILE", None)
            else:
                os.environ["SSL_CERT_FILE"] = original_cert_file

        # An explicitly named bundle is loaded.
        explicit_context = build_custom_endpoint_ssl_context(certifi.where())
        assert explicit_context.get_ca_certs()

        # A missing bundle must not silently fall back to a weaker context.
        try:
            build_custom_endpoint_ssl_context(
                os.path.join("C:" + os.sep, "nonexistent", "missing-ca.pem")
            )
        except ModelEndpointValidationError:
            pass
        else:
            raise AssertionError(
                "A missing CA bundle must fail rather than silently fall back."
            )

        print("CA bundle honoured explicitly and fails loudly when missing")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_saving_tolerates_unresolvable_names_but_not_policy_violations():
    """Configuration may be saved before the host resolves; policy still applies."""
    print("Testing save-time resolution behaviour...")
    try:
        unresolvable = "https://not-a-real-host.invalid/v1"

        # Saving tolerates a name that does not resolve yet.
        assert _validate(unresolvable, private=True) == unresolvable

        # Requiring resolution surfaces the failure with a distinct exception.
        try:
            validate_custom_model_endpoint_url(
                unresolvable,
                allow_private=True,
                require_resolvable=True,
            )
        except ModelEndpointUnresolvableError:
            pass
        else:
            raise AssertionError("Expected an unresolvable-hostname error.")

        # A policy violation is never tolerated, regardless of resolvability.
        try:
            validate_custom_model_endpoint_url(
                "https://127.0.0.1/v1",
                allow_private=True,
                require_resolvable=False,
            )
        except ModelEndpointValidationError as exc:
            assert not isinstance(exc, ModelEndpointUnresolvableError), (
                "A blocked address must be a policy violation, not a resolution failure."
            )
        else:
            raise AssertionError("A loopback address must always be rejected.")

        print("Save tolerates unresolvable names while policy still applies")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_version_bumped():
    """On-premises support ships at or after its implementation version."""
    print("Testing config version...")
    try:
        assert_app_version_at_least("0.261.016")
        print("Config version check passed")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


if __name__ == "__main__":
    tests = [
        test_gate_off_preserves_the_secure_default,
        test_gate_on_enables_on_prem_addresses,
        test_dangerous_targets_stay_blocked_with_the_gate_on,
        test_rejection_messages_are_accurate,
        test_custom_ca_bundle_is_honoured_and_fails_loudly,
        test_saving_tolerates_unresolvable_names_but_not_policy_violations,
        test_version_bumped,
    ]

    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        results.append(test())

    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)

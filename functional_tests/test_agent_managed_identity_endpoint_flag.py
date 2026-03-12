#!/usr/bin/env python3
# test_agent_managed_identity_endpoint_flag.py
"""
Functional test for managed identity endpoint_is_user_supplied flag and
use_managed_identity guard logic in semantic_kernel_loader.py.

Version: 0.239.002
Implemented in: 0.238.025

This test ensures that:
1. resolve_agent_config() sets endpoint_is_user_supplied=False for Cases 5 and 6
   (system-controlled endpoints) and True for Cases 1, 3, and 4 (user/agent-supplied).
2. use_managed_identity evaluates to True only when all five guards hold:
   auth_type == 'managed_identity', no APIM, no key, DefaultAzureCredential
   available, and endpoint_is_user_supplied == False.
3. The AzureChatCompletion gate condition admits MI auth when appropriate and
   blocks it when endpoint_is_user_supplied=True (which forces use_managed_identity=False).

These tests mirror the decision tree in resolve_agent_config() and the
use_managed_identity expression in load_single_agent_for_kernel() from
application/single_app/semantic_kernel_loader.py.
"""

import sys


# ---------------------------------------------------------------------------
# Inline mirror of the resolve_agent_config() decision tree.
# Only the endpoint_is_user_supplied assignment is exercised here.
# Logic must stay in sync with semantic_kernel_loader.py.
# ---------------------------------------------------------------------------

def _resolve_endpoint_is_user_supplied(agent, settings):
    """
    Mirror of the 'PATCHED DECISION TREE' in resolve_agent_config().
    Returns (endpoint_is_user_supplied, case_number).
    """
    def any_filled(*fields):
        return any(bool(f) for f in fields)

    def all_filled(*fields):
        return all(bool(f) for f in fields)

    user_apim_enabled = agent.get("enable_agent_gpt_apim") in [True, 1, "true", "True"]
    global_apim_enabled = settings.get("enable_gpt_apim", False)
    allow_user_custom = settings.get("allow_user_custom_agent_endpoints", False)
    allow_group_custom = settings.get("allow_group_custom_agent_endpoints", False)
    is_group_agent = agent.get("is_group", False)
    is_global_agent = agent.get("is_global", False)

    if is_group_agent:
        can_use_agent_endpoints = allow_group_custom
    elif is_global_agent:
        can_use_agent_endpoints = False
    else:
        can_use_agent_endpoints = allow_user_custom

    user_apim_allowed = user_apim_enabled and can_use_agent_endpoints

    u_apim = (
        agent.get("azure_apim_gpt_endpoint"),
        agent.get("azure_apim_gpt_subscription_key"),
        agent.get("azure_apim_gpt_deployment"),
        agent.get("azure_apim_gpt_api_version"),
    )
    g_apim = (
        settings.get("azure_apim_gpt_endpoint"),
        settings.get("azure_apim_gpt_subscription_key"),
        settings.get("azure_apim_gpt_deployment"),
        settings.get("azure_apim_gpt_api_version"),
    )
    u_gpt = (
        agent.get("azure_openai_gpt_endpoint"),
        agent.get("azure_openai_gpt_key"),
        agent.get("azure_openai_gpt_deployment"),
        agent.get("azure_openai_gpt_api_version"),
    )
    g_gpt = (
        settings.get("azure_openai_gpt_endpoint"),
        settings.get("azure_openai_gpt_key"),
        settings.get("azure_openai_gpt_deployment"),
        settings.get("azure_openai_gpt_api_version"),
    )

    # Case 1 – user APIM values present and allowed
    if user_apim_allowed and any_filled(*u_apim):
        return True, 1
    # Case 2 – user APIM enabled but no user values; fall to global APIM
    elif user_apim_enabled and global_apim_enabled and any_filled(*g_apim):
        return False, 2
    # Case 3 – agent GPT config fully filled and allowed
    elif all_filled(*u_gpt) and can_use_agent_endpoints:
        return True, 3
    # Case 4 – agent GPT config partially filled, no global APIM
    elif any_filled(*u_gpt) and not global_apim_enabled and can_use_agent_endpoints:
        return True, 4
    # Case 5 – global APIM enabled and present
    elif global_apim_enabled and any_filled(*g_apim):
        return False, 5
    # Case 6 – global GPT fallback
    else:
        return False, 6


# ---------------------------------------------------------------------------
# Mirror of the use_managed_identity expression in load_single_agent_for_kernel
# ---------------------------------------------------------------------------

def _compute_use_managed_identity(auth_type, apim_enabled, agent_key,
                                   credential_available, endpoint_is_user_supplied):
    """Mirror of the inline use_managed_identity expression."""
    DefaultAzureCredential = object() if credential_available else None
    return (
        auth_type == "managed_identity"
        and not apim_enabled
        and not agent_key
        and bool(DefaultAzureCredential)
        and not endpoint_is_user_supplied
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

GLOBAL_ENDPOINT   = "https://global.openai.azure.com"
GLOBAL_KEY        = "global-key-abc"
GLOBAL_DEPLOYMENT = "gpt-4.1"
GLOBAL_API_VER    = "2024-08-01"

AGENT_ENDPOINT    = "https://agent.openai.azure.com"
AGENT_KEY         = "agent-key-xyz"
AGENT_DEPLOYMENT  = "gpt-4o"
AGENT_API_VER     = "2024-05-13"

APIM_ENDPOINT = "https://apim.azure-api.net"
APIM_KEY      = "apim-sub-key"
APIM_DEPL     = "gpt-4.1"
APIM_VER      = "2024-08-01"


def _settings(**overrides):
    s = {
        "azure_openai_gpt_endpoint": GLOBAL_ENDPOINT,
        "azure_openai_gpt_key": GLOBAL_KEY,
        "azure_openai_gpt_deployment": GLOBAL_DEPLOYMENT,
        "azure_openai_gpt_api_version": GLOBAL_API_VER,
        "enable_gpt_apim": False,
        "per_user_semantic_kernel": True,
        "allow_user_custom_agent_endpoints": False,
        "allow_group_custom_agent_endpoints": False,
    }
    s.update(overrides)
    return s


def _agent(**overrides):
    a = {
        "name": "test-agent",
        "agent_type": "local",
        "enable_agent_gpt_apim": False,
        "is_global": False,
        "is_group": False,
    }
    a.update(overrides)
    return a


# ---------------------------------------------------------------------------
# Test 1 – endpoint_is_user_supplied across all 6 decision-tree cases
# ---------------------------------------------------------------------------

def test_endpoint_is_user_supplied_all_cases():
    """endpoint_is_user_supplied must be False for Cases 2, 5, 6 and True for 1, 3, 4."""
    print("Testing endpoint_is_user_supplied flag for all 6 cases...")
    errors = []

    # Case 1 – user APIM with values present, can_use=True  →  True
    val, case = _resolve_endpoint_is_user_supplied(
        _agent(
            enable_agent_gpt_apim=True,
            azure_apim_gpt_endpoint=APIM_ENDPOINT,
            azure_apim_gpt_subscription_key=APIM_KEY,
            azure_apim_gpt_deployment=APIM_DEPL,
            azure_apim_gpt_api_version=APIM_VER,
        ),
        _settings(allow_user_custom_agent_endpoints=True),
    )
    _check(errors, "Case 1 (user APIM)", expected=True, got=val, case=case)

    # Case 2 – user APIM on but no user values, global APIM present  →  False
    val, case = _resolve_endpoint_is_user_supplied(
        _agent(enable_agent_gpt_apim=True),
        _settings(
            allow_user_custom_agent_endpoints=True,
            enable_gpt_apim=True,
            azure_apim_gpt_endpoint=APIM_ENDPOINT,
            azure_apim_gpt_subscription_key=APIM_KEY,
            azure_apim_gpt_deployment=APIM_DEPL,
            azure_apim_gpt_api_version=APIM_VER,
        ),
    )
    _check(errors, "Case 2 (global APIM fallback)", expected=False, got=val, case=case)

    # Case 3 – agent GPT fully filled, can_use=True  →  True
    val, case = _resolve_endpoint_is_user_supplied(
        _agent(
            azure_openai_gpt_endpoint=AGENT_ENDPOINT,
            azure_openai_gpt_key=AGENT_KEY,
            azure_openai_gpt_deployment=AGENT_DEPLOYMENT,
            azure_openai_gpt_api_version=AGENT_API_VER,
        ),
        _settings(allow_user_custom_agent_endpoints=True),
    )
    _check(errors, "Case 3 (full agent GPT)", expected=True, got=val, case=case)

    # Case 4 – agent GPT partially filled, no global APIM, can_use=True  →  True
    val, case = _resolve_endpoint_is_user_supplied(
        _agent(azure_openai_gpt_deployment=AGENT_DEPLOYMENT),  # only deployment
        _settings(allow_user_custom_agent_endpoints=True, enable_gpt_apim=False),
    )
    _check(errors, "Case 4 (partial agent GPT, merged)", expected=True, got=val, case=case)

    # Case 5 – global APIM enabled and present, no agent override  →  False
    val, case = _resolve_endpoint_is_user_supplied(
        _agent(),
        _settings(
            enable_gpt_apim=True,
            azure_apim_gpt_endpoint=APIM_ENDPOINT,
            azure_apim_gpt_subscription_key=APIM_KEY,
            azure_apim_gpt_deployment=APIM_DEPL,
            azure_apim_gpt_api_version=APIM_VER,
        ),
    )
    _check(errors, "Case 5 (global APIM)", expected=False, got=val, case=case)

    # Case 6 – pure global GPT fallback (most common MI scenario)  →  False
    val, case = _resolve_endpoint_is_user_supplied(_agent(), _settings())
    _check(errors, "Case 6 (global GPT fallback)", expected=False, got=val, case=case)

    # --- Group-agent scenarios matching: Allow Group Custom Agent Endpoints=ON ---
    # Group agent with NO custom fields + allow_group_custom=True
    # → no u_gpt/u_apim fields filled → falls to Case 6 → endpoint_is_user_supplied=False
    # → MI is permitted (this is the user's deployment scenario)
    val, case = _resolve_endpoint_is_user_supplied(
        _agent(is_group=True),
        _settings(allow_group_custom_agent_endpoints=True),
    )
    _check(errors, "Group agent, no custom fields, allow_group_custom=True (MI permitted)",
           expected=False, got=val, case=case)

    # Group agent WITH a custom endpoint + allow_group_custom=True
    # → hits Case 3 (fully filled u_gpt) → endpoint_is_user_supplied=True
    # → MI is BLOCKED (group admin could point at attacker endpoint)
    val, case = _resolve_endpoint_is_user_supplied(
        _agent(
            is_group=True,
            azure_openai_gpt_endpoint=AGENT_ENDPOINT,
            azure_openai_gpt_key=AGENT_KEY,
            azure_openai_gpt_deployment=AGENT_DEPLOYMENT,
            azure_openai_gpt_api_version=AGENT_API_VER,
        ),
        _settings(allow_group_custom_agent_endpoints=True),
    )
    _check(errors, "Group agent, custom endpoint set, allow_group_custom=True (MI blocked)",
           expected=True, got=val, case=case)

    return _summarise(errors, "endpoint_is_user_supplied")


def _check(errors, label, expected, got, case=None):
    status = "PASS" if got == expected else "FAIL"
    suffix = f" (case #{case})" if case else ""
    print(f"  [{status}] {label}{suffix}: endpoint_is_user_supplied={got}")
    if got != expected:
        errors.append(f"{label}: expected {expected}, got {got}")


# ---------------------------------------------------------------------------
# Test 2 – use_managed_identity guard logic
# ---------------------------------------------------------------------------

def test_use_managed_identity_logic():
    """use_managed_identity must be True only when every guard passes."""
    print("\nTesting use_managed_identity boolean logic...")

    cases = [
        # (description, auth_type, apim, key, cred_avail, user_supplied, expected)
        ("all guards pass → True",
         "managed_identity", False, None,     True,  False, True),
        ("wrong auth_type → False",
         "api_key",          False, None,     True,  False, False),
        ("APIM enabled → False",
         "managed_identity", True,  None,     True,  False, False),
        ("key present → False",
         "managed_identity", False, "abc123", True,  False, False),
        ("no DefaultAzureCredential → False",
         "managed_identity", False, None,     False, False, False),
        ("endpoint_is_user_supplied=True → False",
         "managed_identity", False, None,     True,  True,  False),
    ]

    errors = []
    for desc, auth, apim, key, cred, user_sup, expected in cases:
        result = _compute_use_managed_identity(auth, apim, key, cred, user_sup)
        status = "PASS" if result == expected else "FAIL"
        print(f"  [{status}] {desc}: {result}")
        if result != expected:
            errors.append(f"{desc}: expected {expected}, got {result}")

    return _summarise(errors, "use_managed_identity")


# ---------------------------------------------------------------------------
# Test 3 – AzureChatCompletion gate condition
# ---------------------------------------------------------------------------

def test_gate_condition():
    """Gate must admit MI auth and block it when endpoint_is_user_supplied=True
    (which sets use_mi=False) and no key is present."""
    print("\nTesting AzureChatCompletion gate condition...")

    def gate(endpoint, key, deployment, use_mi):
        """Mirrors: if AzureChatCompletion and endpoint and (key or use_mi) and deployment"""
        return bool(endpoint) and bool(key or use_mi) and bool(deployment)

    cases = [
        # (desc, endpoint, key, deployment, use_mi, expected)
        ("MI auth, no key, user_supplied=False → admitted",
         GLOBAL_ENDPOINT, None,       GLOBAL_DEPLOYMENT, True,  True),
        ("key auth, no MI → admitted",
         GLOBAL_ENDPOINT, GLOBAL_KEY, GLOBAL_DEPLOYMENT, False, True),
        ("user_supplied=True → use_mi=False, no key → blocked",
         AGENT_ENDPOINT,  None,       AGENT_DEPLOYMENT,  False, False),
        ("no endpoint → blocked",
         None,            None,       GLOBAL_DEPLOYMENT, True,  False),
        ("no deployment → blocked",
         GLOBAL_ENDPOINT, None,       None,              True,  False),
    ]

    errors = []
    for desc, ep, key, depl, use_mi, expected in cases:
        result = gate(ep, key, depl, use_mi)
        status = "PASS" if result == expected else "FAIL"
        print(f"  [{status}] {desc}: {result}")
        if result != expected:
            errors.append(f"{desc}: expected {expected}, got {result}")

    return _summarise(errors, "gate condition")


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _summarise(errors, label):
    if errors:
        for e in errors:
            print(f"  FAIL: {e}")
        return False
    print(f"All {label} cases passed!")
    return True


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        test_endpoint_is_user_supplied_all_cases,
        test_use_managed_identity_logic,
        test_gate_condition,
    ]
    results = []
    for t in tests:
        print(f"\n{'='*60}")
        print(f"Running {t.__name__}...")
        print("="*60)
        try:
            results.append(t())
        except Exception as exc:
            import traceback
            print(f"ERROR: {exc}")
            traceback.print_exc()
            results.append(False)

    passed = sum(1 for r in results if r)
    total = len(results)
    print(f"\n{'='*60}")
    print(f"Results: {passed}/{total} tests passed")
    print("="*60)
    sys.exit(0 if all(results) else 1)

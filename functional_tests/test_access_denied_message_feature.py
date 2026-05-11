#!/usr/bin/env python3
# test_access_denied_message_feature.py
"""
Functional regression test for admin-configurable access denied message.

Version: 0.239.002
Implemented in: 0.239.002

This test ensures that:
1. The Admin Settings template exposes a textarea with name="access_denied_message".
2. route_frontend_admin_settings.py reads the field from form_data and falls back
   to the existing stored value (not '') when the field is absent -- preventing
   silent data loss from cached/older form submissions.
3. index.html renders app_settings.access_denied_message through the nl2br filter
   without a redundant hardcoded fallback string.
4. functions_settings.py defines a non-empty default for access_denied_message so
   the field is always present after get_settings() deep-merges defaults.
"""

import sys
import os
import re

# Resolve paths relative to repo root
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ADMIN_TEMPLATE    = os.path.join(REPO_ROOT, "application", "single_app", "templates", "admin_settings.html")
INDEX_TEMPLATE    = os.path.join(REPO_ROOT, "application", "single_app", "templates", "index.html")
ROUTE_FILE        = os.path.join(REPO_ROOT, "application", "single_app", "route_frontend_admin_settings.py")
SETTINGS_FILE     = os.path.join(REPO_ROOT, "application", "single_app", "functions_settings.py")


# ---------------------------------------------------------------------------
# Test 1 – Admin Settings template has the access_denied_message field
# ---------------------------------------------------------------------------

def test_admin_template_has_field():
    """Admin Settings template must expose a textarea named access_denied_message."""
    print("Testing admin_settings.html contains access_denied_message field...")
    errors = []

    with open(ADMIN_TEMPLATE, encoding="utf-8") as f:
        content = f.read()

    # textarea with correct name attribute
    if 'name="access_denied_message"' not in content:
        errors.append("No <textarea name=\"access_denied_message\"> found in admin_settings.html")

    # label pointing to the field
    if 'for="access_denied_message"' not in content:
        errors.append("No <label for=\"access_denied_message\"> found in admin_settings.html")

    # renders the current stored value
    if 'settings.access_denied_message' not in content:
        errors.append("Textarea does not render {{ settings.access_denied_message }}")

    return _summarise(errors, "admin template field")


# ---------------------------------------------------------------------------
# Test 2 – Route persists access_denied_message with safe fallback
# ---------------------------------------------------------------------------

def test_route_persists_with_safe_fallback():
    """route_frontend_admin_settings must fall back to existing stored value, not ''."""
    print("\nTesting route_frontend_admin_settings.py persistence logic...")
    errors = []

    with open(ROUTE_FILE, encoding="utf-8") as f:
        content = f.read()

    # Key must be written into the settings dict
    if "'access_denied_message'" not in content:
        errors.append("'access_denied_message' key not found in route file")
        return _summarise(errors, "route persistence")

    # Must use form_data.get('access_denied_message', ...) - not a hard '' fallback
    # Correct pattern: form_data.get('access_denied_message', settings.get(...))
    safe_fallback_pattern = re.compile(
        r"'access_denied_message'\s*:\s*form_data\.get\(\s*'access_denied_message'\s*,"
        r"\s*settings\.get\("
    )
    if not safe_fallback_pattern.search(content):
        errors.append(
            "access_denied_message does not use settings.get() as fallback -- "
            "form_data.get('access_denied_message', settings.get(...)) pattern not found"
        )

    # Must NOT be: form_data.get('access_denied_message', '')  (bare empty-string fallback)
    bare_empty_pattern = re.compile(
        r"'access_denied_message'\s*:\s*form_data\.get\(\s*'access_denied_message'\s*,\s*''\s*\)"
    )
    if bare_empty_pattern.search(content):
        errors.append(
            "access_denied_message still has bare '' fallback -- would wipe stored value "
            "if field is absent from form submission"
        )

    return _summarise(errors, "route persistence")


# ---------------------------------------------------------------------------
# Test 3 – index.html renders via nl2br without a hardcoded fallback
# ---------------------------------------------------------------------------

def test_index_renders_via_nl2br_no_hardcoded_fallback():
    """index.html must render access_denied_message | nl2br with no inline fallback."""
    print("\nTesting index.html nl2br rendering...")
    errors = []

    with open(INDEX_TEMPLATE, encoding="utf-8") as f:
        content = f.read()

    # Must use the nl2br filter
    if 'access_denied_message | nl2br' not in content:
        errors.append("index.html does not render access_denied_message through nl2br filter")

    # Must NOT contain a hardcoded fallback string inline
    hardcoded_pattern = re.compile(
        r"access_denied_message\s+or\s+'You are logged in"
    )
    if hardcoded_pattern.search(content):
        errors.append(
            "index.html still has a hardcoded fallback string -- "
            "default should live only in functions_settings.py"
        )

    return _summarise(errors, "index nl2br rendering")


# ---------------------------------------------------------------------------
# Test 4 – functions_settings.py defines a non-empty default
# ---------------------------------------------------------------------------

def test_settings_default_is_defined():
    """functions_settings.py must define a non-empty default for access_denied_message."""
    print("\nTesting functions_settings.py default value...")
    errors = []

    with open(SETTINGS_FILE, encoding="utf-8") as f:
        content = f.read()

    pattern = re.compile(
        r"'access_denied_message'\s*:\s*'(.+?)'"
    )
    match = pattern.search(content)
    if not match:
        errors.append("No non-empty default for 'access_denied_message' found in functions_settings.py")
    else:
        print(f"  Default value: \"{match.group(1)[:60]}...\"")

    return _summarise(errors, "settings default")


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _summarise(errors, label):
    if errors:
        for e in errors:
            print(f"  FAIL: {e}")
        return False
    print(f"  All {label} checks passed!")
    return True


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        test_admin_template_has_field,
        test_route_persists_with_safe_fallback,
        test_index_renders_via_nl2br_no_hardcoded_fallback,
        test_settings_default_is_defined,
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

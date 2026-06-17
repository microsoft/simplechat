# test_chat_local_openlayers_assets.py
#!/usr/bin/env python3
"""
Functional test for local chat OpenLayers assets.
Version: 0.242.053
Implemented in: 0.241.116
CSP allowlist regression fixed in: 0.242.053

This test ensures the chat page loads OpenLayers from SimpleChat static files,
the CSP no longer allows jsDelivr for scripts or styles, and SimpleMDE editor
instances do not trigger CDN-backed spell checker downloads.
"""

import os
import re
import sys
import traceback


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHAT_TEMPLATE = os.path.join(REPO_ROOT, "application", "single_app", "templates", "chats.html")
ADMIN_SETTINGS_TEMPLATE = os.path.join(REPO_ROOT, "application", "single_app", "templates", "admin_settings.html")
CONFIG_FILE = os.path.join(REPO_ROOT, "application", "single_app", "config.py")
OPENLAYERS_JS = os.path.join(REPO_ROOT, "application", "single_app", "static", "js", "openlayers", "ol.js")
OPENLAYERS_CSS = os.path.join(REPO_ROOT, "application", "single_app", "static", "css", "openlayers", "ol.css")
SIMPLEMDE_JS = os.path.join(REPO_ROOT, "application", "single_app", "static", "js", "simplemde", "simplemde.js")
SIMPLEMDE_MIN_JS = os.path.join(REPO_ROOT, "application", "single_app", "static", "js", "simplemde", "simplemde.min.js")


def _read(path):
    with open(path, encoding="utf-8") as file_handle:
        return file_handle.read()


def _strip_html_comments(content):
    return re.sub(r"<!--.*?-->", "", content, flags=re.DOTALL)


def _get_current_version():
    for line in _read(CONFIG_FILE).splitlines():
        if line.strip().startswith("VERSION = "):
            return line.split("=", 1)[1].strip().strip('"')
    raise AssertionError("Unable to find VERSION in config.py.")


def test_openlayers_assets_are_local():
    """Validate that chat references the local OpenLayers runtime assets."""
    print("Testing chat OpenLayers asset paths...")
    content = _strip_html_comments(_read(CHAT_TEMPLATE))
    errors = []

    required_fragments = [
        "css/openlayers/ol.css",
        "js/openlayers/ol.js",
    ]
    for fragment in required_fragments:
        if fragment not in content:
            errors.append(f"Missing local asset reference: {fragment}")

    forbidden_fragments = [
        "https://cdn.jsdelivr.net/npm/ol@10.6.1/ol.css",
        "https://cdn.jsdelivr.net/npm/ol@10.6.1/dist/ol.js",
    ]
    for fragment in forbidden_fragments:
        if fragment in content:
            errors.append(f"Found CDN OpenLayers reference: {fragment}")

    for path in (OPENLAYERS_JS, OPENLAYERS_CSS):
        if not os.path.exists(path):
            errors.append(f"Missing vendored OpenLayers file: {path}")
        elif os.path.getsize(path) == 0:
            errors.append(f"Vendored OpenLayers file is empty: {path}")

    if errors:
        for error in errors:
            print(f"  FAIL: {error}")
        raise AssertionError("OpenLayers local asset checks failed.")

    print("  OpenLayers local asset checks passed.")


def test_csp_keeps_scripts_and_styles_local():
    """Validate the browser cannot load script/style assets from jsDelivr."""
    print("Testing CSP script/style sources...")
    content = _read(CONFIG_FILE)
    errors = []

    if _get_current_version() != "0.242.053":
        errors.append("config.py VERSION must match the test header version 0.242.053.")

    for csp_fragment in [
        "script-src 'self' 'unsafe-inline' 'unsafe-eval';",
        "style-src 'self' 'unsafe-inline';",
    ]:
        if csp_fragment not in content:
            errors.append(f"Missing CSP fragment: {csp_fragment}")

    active_csp = content.split("'Content-Security-Policy':", 1)[1].split(")", 1)[0]
    for forbidden_fragment in [
        "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.jsdelivr.net",
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net",
    ]:
        if forbidden_fragment in active_csp:
            errors.append(f"Found CDN allowance in active CSP: {forbidden_fragment}")

    if errors:
        for error in errors:
            print(f"  FAIL: {error}")
        raise AssertionError("CSP local asset checks failed.")

    print("  CSP local asset checks passed.")


def test_simplemde_spell_checker_is_disabled_for_admin_editor():
    """Validate SimpleMDE admin editor setup does not request CDN spell dictionaries."""
    print("Testing admin SimpleMDE CDN-prevention options...")
    content = _read(ADMIN_SETTINGS_TEMPLATE)
    editor_fragment_match = re.search(
        r"new\s+SimpleMDE\s*\(\s*\{(?P<options>.*?)\}\s*\)",
        content,
        flags=re.DOTALL,
    )

    if not editor_fragment_match:
        raise AssertionError("Unable to find admin SimpleMDE initialization.")

    options = editor_fragment_match.group("options")
    errors = []
    for required_option in ["spellChecker: false", "autoDownloadFontAwesome: false"]:
        if required_option not in options:
            errors.append(f"Missing admin SimpleMDE option: {required_option}")

    if errors:
        for error in errors:
            print(f"  FAIL: {error}")
        raise AssertionError("Admin SimpleMDE CDN-prevention checks failed.")

    print("  Admin SimpleMDE CDN-prevention checks passed.")


def test_simplemde_vendor_defaults_do_not_reference_cdns():
    """Validate the local SimpleMDE vendor files cannot auto-load CDN assets by default."""
    print("Testing SimpleMDE vendor CDN defaults...")
    errors = []
    for path in [SIMPLEMDE_JS, SIMPLEMDE_MIN_JS]:
        content = _read(path)
        for forbidden_fragment in [
            "https://cdn.jsdelivr.net/codemirror.spell-checker",
            "https://maxcdn.bootstrapcdn.com/font-awesome",
        ]:
            if forbidden_fragment in content:
                errors.append(f"Found external vendor URL in {path}: {forbidden_fragment}")

    simplemde_source = _read(SIMPLEMDE_JS)
    if "if(options.spellChecker === true)" not in simplemde_source:
        errors.append("SimpleMDE source should require explicit spellChecker: true.")
    if "var autoDownloadFA = false;" not in simplemde_source:
        errors.append("SimpleMDE source should keep FontAwesome auto-download disabled.")

    simplemde_minified = _read(SIMPLEMDE_MIN_JS)
    if "spellChecker===!0" not in simplemde_minified:
        errors.append("SimpleMDE minified file should require explicit spellChecker: true.")

    if errors:
        for error in errors:
            print(f"  FAIL: {error}")
        raise AssertionError("SimpleMDE vendor CDN default checks failed.")

    print("  SimpleMDE vendor CDN default checks passed.")


if __name__ == "__main__":
    tests = [
        test_openlayers_assets_are_local,
        test_csp_keeps_scripts_and_styles_local,
        test_simplemde_spell_checker_is_disabled_for_admin_editor,
        test_simplemde_vendor_defaults_do_not_reference_cdns,
    ]
    results = []

    for test in tests:
        print(f"\n{'=' * 60}")
        print(f"Running {test.__name__}...")
        print("=" * 60)
        try:
            test()
            results.append(True)
        except Exception as exc:
            print(f"ERROR: {exc}")
            traceback.print_exc()
            results.append(False)

    success = all(results)
    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if success else 1)
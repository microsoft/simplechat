# test_browser_alert_replacement.py
"""
Functional test for replacing native browser alerts with shared toast notifications.
Version: 0.250.102
Implemented in: 0.250.102

This test ensures first-party browser code uses the shared, XSS-safe showToast
utility while pinned third-party DataTables bundles remain unchanged.
"""

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
APPLICATION_ROOT = ROOT / "application" / "single_app"
ALERT_CALL_PATTERN = re.compile(r"\b(?:window\.)?alert\s*\(")
VENDOR_EXCLUSIONS = {
    Path("static/js/chat/jquery.dataTables.min.js"),
    Path("static/js/datatables/datatables.js"),
    Path("static/js/datatables/datatables.min.js"),
}


def iter_first_party_browser_files():
    """Yield first-party JavaScript and template files covered by the alert policy."""
    for relative_root, pattern in (
        (Path("static/js"), "*.js"),
        (Path("templates"), "*.html"),
    ):
        source_root = APPLICATION_ROOT / relative_root
        for source_path in source_root.rglob(pattern):
            relative_path = source_path.relative_to(APPLICATION_ROOT)
            if relative_path in VENDOR_EXCLUSIONS:
                continue
            yield source_path


def test_first_party_browser_code_has_no_native_alert_calls():
    """Prevent blocking browser alert calls from returning to first-party code."""
    violations = []

    for source_path in iter_first_party_browser_files():
        source = source_path.read_text(encoding="utf-8")
        if ALERT_CALL_PATTERN.search(source):
            violations.append(str(source_path.relative_to(ROOT)))

    assert violations == [], (
        "Replace native alert() calls with showToast() in: "
        + ", ".join(violations)
    )


def test_shared_toast_utility_is_safe_and_globally_available():
    """Verify the shared toast contract used by classic, inline, and module scripts."""
    toast_source = (
        APPLICATION_ROOT / "static" / "js" / "toast.js"
    ).read_text(encoding="utf-8")
    chat_toast_source = (
        APPLICATION_ROOT / "static" / "js" / "chat" / "chat-toast.js"
    ).read_text(encoding="utf-8")
    base_template = (
        APPLICATION_ROOT / "templates" / "base.html"
    ).read_text(encoding="utf-8")

    assert "window.showToast = showToast;" in toast_source
    assert "bodyEl.textContent =" in toast_source
    assert "bodyEl.innerHTML" not in toast_source
    assert "pendingToastStorageKey" in toast_source
    assert "options.persist === true" in toast_source
    assert "variantAliases = new Map([['error', 'danger']])" in toast_source
    assert "window.showToast(message, variant, options);" in chat_toast_source
    assert "js/toast.js" in base_template
    assert base_template.index("js/toast.js") < base_template.index("{% block scripts %}")


if __name__ == "__main__":
    test_first_party_browser_code_has_no_native_alert_calls()
    test_shared_toast_utility_is_safe_and_globally_available()
    print("Browser alert replacement checks passed.")

# test_msg_file_upload_support.py
#!/usr/bin/env python3
"""
Functional test for Outlook MSG file upload support.
Version: 0.242.066
Implemented in: 0.242.063

This test ensures Outlook .msg files are accepted for workspace and chat uploads,
processed through a plain-text extractor, and covered by existing route security
decorators and XSS-safe extraction boundaries.
"""

import importlib.util
import os
import re
import sys
import types
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
SINGLE_APP_DIR = ROOT_DIR / "application" / "single_app"
CONFIG_PATH = SINGLE_APP_DIR / "config.py"
FUNCTIONS_CONTENT_PATH = SINGLE_APP_DIR / "functions_content.py"
FUNCTIONS_DOCUMENTS_PATH = SINGLE_APP_DIR / "functions_documents.py"
FUNCTIONS_SETTINGS_PATH = SINGLE_APP_DIR / "functions_settings.py"
CHAT_ROUTE_PATH = SINGLE_APP_DIR / "route_frontend_chats.py"
GROUP_ROUTE_PATH = SINGLE_APP_DIR / "route_frontend_group_workspaces.py"
CHAT_TEMPLATE_PATH = SINGLE_APP_DIR / "templates" / "chats.html"
FEATURE_DOC_PATH = ROOT_DIR / "docs" / "explanation" / "features" / "v0.242.063" / "MSG_FILE_INGESTION.md"
EXPECTED_CONFIG_VERSION = "0.242.066"
EXPECTED_FEATURE_VERSION = "0.242.063"


def read_text(path):
    """Read a UTF-8 file from the repository."""
    return path.read_text(encoding="utf-8")


def assert_contains(source, snippets, label):
    """Assert every snippet is present in source."""
    missing = [snippet for snippet in snippets if snippet not in source]
    assert not missing, f"Missing {label} snippets: {missing}"


def assert_not_contains(source, snippets, label):
    """Assert no snippets are present in source."""
    present = [snippet for snippet in snippets if snippet in source]
    assert not present, f"Unexpected {label} snippets: {present}"


def assert_order(source, snippets, label):
    """Assert snippets appear in source order."""
    previous_index = -1
    for snippet in snippets:
        current_index = source.find(snippet)
        assert current_index != -1, f"Missing {label} snippet: {snippet}"
        assert current_index > previous_index, f"Out-of-order {label} snippet: {snippet}"
        previous_index = current_index


def load_functions_content_for_msg_tests():
    """Load functions_content with lightweight app-module stubs."""
    fake_config = types.ModuleType("config")
    fake_config.os = os
    fake_config.re = re
    fake_config.WORD_CHUNK_SIZE = 400

    fake_functions_settings = types.ModuleType("functions_settings")
    fake_functions_settings.get_settings = lambda *args, **kwargs: {}

    fake_functions_logging = types.ModuleType("functions_logging")

    fake_functions_debug = types.ModuleType("functions_debug")
    fake_functions_debug.debug_print = lambda *args, **kwargs: None

    module_names = [
        "config",
        "functions_settings",
        "functions_logging",
        "functions_debug",
    ]
    original_modules = {module_name: sys.modules.get(module_name) for module_name in module_names}
    sys.modules.update({
        "config": fake_config,
        "functions_settings": fake_functions_settings,
        "functions_logging": fake_functions_logging,
        "functions_debug": fake_functions_debug,
    })

    try:
        spec = importlib.util.spec_from_file_location("functions_content_msg_test", FUNCTIONS_CONTENT_PATH)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        for module_name, original_module in original_modules.items():
            if original_module is None:
                sys.modules.pop(module_name, None)
            else:
                sys.modules[module_name] = original_module


class FakeOleStream:
    """Small read-only stream stand-in for OLE property streams."""

    def __init__(self, payload):
        self.payload = payload

    def read(self):
        """Return stream bytes."""
        return self.payload


class FakeMsgOle:
    """Small OLE stand-in with top-level MSG streams."""

    def __init__(self, streams):
        self.streams = streams
        self.closed = False

    def listdir(self, streams=True, storages=False):
        """Return fake stream entries."""
        if not streams:
            return []
        return [[stream_name] for stream_name in self.streams]

    def openstream(self, stream_entry):
        """Open a fake stream by path."""
        stream_name = stream_entry[-1] if isinstance(stream_entry, list) else stream_entry
        return FakeOleStream(self.streams[stream_name])

    def close(self):
        """Record close calls."""
        self.closed = True


class FakeOleFileModule:
    """Small olefile module stand-in."""

    def __init__(self, fake_ole):
        self.fake_ole = fake_ole

    def isOleFile(self, file_path):
        """Treat the test path as a valid OLE file."""
        return True

    def OleFileIO(self, file_path):
        """Return the fake OLE object."""
        return self.fake_ole


def utf16_msg_value(value):
    """Encode a fake Unicode MAPI property value."""
    return str(value).encode("utf-16le")


def test_msg_extension_is_centrally_allowed():
    """Validate .msg is part of the shared upload allowlist and version."""
    print("Testing central .msg upload allowlist...")

    config_source = read_text(CONFIG_PATH)
    settings_source = read_text(FUNCTIONS_SETTINGS_PATH)

    assert f'VERSION = "{EXPECTED_CONFIG_VERSION}"' in config_source
    assert_contains(
        config_source,
        [
            "mimetypes.add_type('application/vnd.ms-outlook', '.msg')",
            "EMAIL_EXTENSIONS = {'msg'}",
            "extensions.update(EMAIL_EXTENSIONS)",
        ],
        "central .msg allowlist",
    )
    assert settings_source.count("'msg': {'value': 400, 'unit': 'words'}") >= 2


def test_msg_processor_and_chat_paths_are_wired():
    """Validate workspace and chat upload paths dispatch .msg files safely."""
    print("Testing .msg processor and chat upload wiring...")

    documents_source = read_text(FUNCTIONS_DOCUMENTS_PATH)
    chat_route_source = read_text(CHAT_ROUTE_PATH)
    group_route_source = read_text(GROUP_ROUTE_PATH)
    chat_template_source = read_text(CHAT_TEMPLATE_PATH)

    assert_contains(
        documents_source,
        [
            "def process_msg(",
            "extract_outlook_msg_text(temp_file_path)",
            "target_words_per_chunk = max(1, int(chunk_config.get('msg', {}).get('value', 400)))",
            "email_extensions = tuple('.' + ext for ext in EMAIL_EXTENSIONS)",
            "elif file_ext in email_extensions:",
            "result = process_msg(",
        ],
        ".msg processor dispatch",
    )
    assert_contains(
        chat_route_source,
        [
            "| EMAIL_EXTENSIONS",
            "elif file_ext_nodot == 'msg':",
            "extracted_content = extract_outlook_msg_text(temp_file_path)",
        ],
        "chat .msg handling",
    )
    assert_contains(chat_template_source, [".docx,.msg", "docx, msg"], "chat picker .msg support")
    assert_contains(
        group_route_source,
        [
            "allowed_extensions = sorted(get_allowed_extensions(",
            "allowed_extensions_str = \"Allowed: \" + \", \".join(allowed_extensions)",
        ],
        "central group workspace extension label",
    )
    assert_not_contains(
        group_route_source,
        [
            '"txt", "pdf", "doc", "docm", "docx", "xlsx"',
            'allowed_extensions += ["mp4", "mov", "avi", "wmv", "mkv", "webm"]',
        ],
        "stale hard-coded group workspace extension labels",
    )


def test_chat_upload_route_keeps_required_decorators():
    """Validate the existing chat upload route keeps required decorators."""
    print("Testing chat upload route decorators...")

    route_source = read_text(CHAT_ROUTE_PATH)
    route_start = route_source.index("@app.route('/upload', methods=['POST'])")
    function_start = route_source.index("def upload_file():", route_start)
    route_header = route_source[route_start:function_start]

    assert_order(
        route_header,
        [
            "@app.route('/upload', methods=['POST'])",
            "@swagger_route(security=get_auth_security())",
            "@login_required",
            "@user_required",
            "@file_upload_required",
        ],
        "chat upload route decorators",
    )


def test_outlook_msg_extractor_returns_plain_text_payload():
    """Validate the .msg extractor reads standard MAPI streams as plain text."""
    print("Testing Outlook .msg text extraction...")

    functions_content = load_functions_content_for_msg_tests()
    fake_ole = FakeMsgOle({
        "__substg1.0_0037001F": utf16_msg_value("Quarterly Review"),
        "__substg1.0_0C1A001F": utf16_msg_value("Ada Lovelace"),
        "__substg1.0_0C1F001F": utf16_msg_value("ada@example.com"),
        "__substg1.0_0E04001F": utf16_msg_value("Team Example"),
        "__substg1.0_1000001F": utf16_msg_value("Please review the attached plan before Friday."),
    })
    functions_content.olefile = FakeOleFileModule(fake_ole)

    extracted_text = functions_content.extract_outlook_msg_text("sample.msg")

    assert "Subject: Quarterly Review" in extracted_text
    assert "From: Ada Lovelace <ada@example.com>" in extracted_text
    assert "To: Team Example" in extracted_text
    assert "Body:" in extracted_text
    assert "Please review the attached plan before Friday." in extracted_text
    assert fake_ole.closed is True


def test_outlook_msg_html_body_is_stripped_before_indexing():
    """Validate HTML-only .msg bodies are stripped to inert plain text."""
    print("Testing Outlook .msg HTML body stripping...")

    functions_content = load_functions_content_for_msg_tests()
    fake_ole = FakeMsgOle({
        "__substg1.0_0037001F": utf16_msg_value("HTML Notice"),
        "__substg1.0_10130102": (
            b"<html><body><p>Hello team</p>"
            b"<script>window.__msgXss = true</script>"
            b"<img src=x onerror=\"window.__msgXss = true\"></body></html>"
        ),
    })
    functions_content.olefile = FakeOleFileModule(fake_ole)

    extracted_text = functions_content.extract_outlook_msg_text("html-only.msg")

    assert "Subject: HTML Notice" in extracted_text
    assert "Hello team" in extracted_text
    assert "<script" not in extracted_text
    assert "onerror" not in extracted_text
    assert "window.__msgXss" not in extracted_text


def test_feature_documentation_exists():
    """Validate feature documentation tracks the .msg ingestion version."""
    print("Testing .msg feature documentation...")

    assert FEATURE_DOC_PATH.exists(), f"Expected feature documentation at {FEATURE_DOC_PATH}"
    feature_doc = read_text(FEATURE_DOC_PATH)
    assert_contains(
        feature_doc,
        [
            f"Implemented in version: **{EXPECTED_FEATURE_VERSION}**",
            f"Fixed/Implemented in version: **{EXPECTED_FEATURE_VERSION}**",
            "Outlook `.msg`",
        ],
        ".msg feature documentation",
    )


def main():
    """Run focused .msg upload support tests."""
    tests = [
        test_msg_extension_is_centrally_allowed,
        test_msg_processor_and_chat_paths_are_wired,
        test_chat_upload_route_keeps_required_decorators,
        test_outlook_msg_extractor_returns_plain_text_payload,
        test_outlook_msg_html_body_is_stripped_before_indexing,
        test_feature_documentation_exists,
    ]

    failures = []
    for test in tests:
        try:
            test()
            print(f"PASS: {test.__name__}")
        except Exception as exc:
            failures.append((test.__name__, exc))
            print(f"FAIL: {test.__name__}: {exc}")

    if failures:
        return 1

    print(f"Results: {len(tests)}/{len(tests)} tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
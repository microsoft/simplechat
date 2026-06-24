# test_unit_model_endpoint_helpers.py
"""
Unit tests for SimpleChat model endpoint helper functions.
Version: 0.250.024
Implemented in: 0.250.024

These tests validate small, deterministic helper functions in isolation. They
do not use Playwright, Flask, authentication, network calls, or cross-component
application workflows.
"""

import sys
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1] / "application" / "single_app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from model_endpoint_clients import (  # noqa: E402
    get_endpoint_path,
    is_anthropic_model,
    normalize_endpoint_text,
)


def test_normalize_endpoint_text_strips_whitespace_and_trailing_slash():
    """Validate endpoint text normalization as a small isolated function."""
    assert normalize_endpoint_text("  https://example.services.ai.azure.com/openai/v1/  ") == (
        "https://example.services.ai.azure.com/openai/v1"
    )
    assert normalize_endpoint_text(None) == ""
    print("normalize_endpoint_text trims whitespace and trailing slashes.")


def test_get_endpoint_path_extracts_lowercase_path():
    """Validate path extraction without needing a configured model endpoint."""
    assert get_endpoint_path("https://example.services.ai.azure.com/OpenAI/V1/Chat/Completions") == (
        "/openai/v1/chat/completions"
    )
    assert get_endpoint_path("not a url/openai/v1") == "not a url/openai/v1"
    print("get_endpoint_path extracts lower-case URL paths.")


def test_is_anthropic_model_detects_claude_names_only():
    """Validate Claude model-name detection in isolation."""
    assert is_anthropic_model("Claude-3-7-Sonnet") is True
    assert is_anthropic_model("azure-claude-demo") is True
    assert is_anthropic_model("gpt-5.4") is False
    assert is_anthropic_model("") is False
    print("is_anthropic_model detects Claude model names only.")
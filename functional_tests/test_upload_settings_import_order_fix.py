# test_upload_settings_import_order_fix.py
"""
Functional test for upload settings helper binding during full app startup.
Version: 0.241.101
Implemented in: 0.241.101

This test ensures upload logging and background embedding generation keep
resolving runtime settings after the full Flask app import path, preventing
valid uploads from failing in either the request path or the background worker.
"""

from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"

if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

import app as _simplechat_app_module
import functions_content
import functions_logging


def test_file_processing_log_resolves_settings_after_full_app_import():
    """Verify upload logging still resolves settings after importing the full app."""
    created_items = []

    original_get_settings = functions_logging.functions_settings.get_settings
    original_create_item = functions_logging.cosmos_file_processing_container.create_item

    functions_logging.functions_settings.get_settings = lambda: {
        "enable_file_processing_logs": True,
    }
    functions_logging.cosmos_file_processing_container.create_item = lambda item: created_items.append(item)

    try:
        functions_logging.add_file_task_to_file_processing_log(
            document_id="doc-123",
            user_id="user-123",
            content="Queued upload",
        )
    finally:
        functions_logging.functions_settings.get_settings = original_get_settings
        functions_logging.cosmos_file_processing_container.create_item = original_create_item

    assert len(created_items) == 1, "Expected upload logging to persist a file-processing log entry."
    assert created_items[0]["document_id"] == "doc-123", "Expected the queued upload log to keep the document id."
    assert created_items[0]["user_id"] == "user-123", "Expected the queued upload log to keep the user id."


def test_generate_embedding_resolves_settings_after_full_app_import():
    """Verify background embedding generation still resolves settings after importing the full app."""
    fake_requests = []

    class FakeEmbeddingsClient:
        def create(self, *, model, input):
            fake_requests.append({
                "model": model,
                "input": input,
            })

            class FakeUsage:
                prompt_tokens = 4
                total_tokens = 4

            class FakeEmbeddingItem:
                embedding = [0.1, 0.2, 0.3]

            class FakeResponse:
                data = [FakeEmbeddingItem()]
                usage = FakeUsage()

            return FakeResponse()

    class FakeAzureOpenAI:
        def __init__(self, *args, **kwargs):
            self.embeddings = FakeEmbeddingsClient()

    fake_settings = {
        "enable_embedding_apim": False,
        "azure_openai_embedding_authentication_type": "key",
        "azure_openai_embedding_api_version": "2024-12-01-preview",
        "azure_openai_embedding_endpoint": "https://example.invalid",
        "azure_openai_embedding_key": "fake-key",
        "embedding_model": {
            "selected": [
                {"deploymentName": "text-embedding-3-small"}
            ]
        },
    }

    original_get_settings = functions_content.functions_settings.get_settings
    original_azure_openai = functions_content.AzureOpenAI
    original_sleep = functions_content.time.sleep
    original_uniform = functions_content.random.uniform

    functions_content.functions_settings.get_settings = lambda: fake_settings
    functions_content.AzureOpenAI = FakeAzureOpenAI
    functions_content.time.sleep = lambda _seconds: None
    functions_content.random.uniform = lambda _start, _end: 0.0

    try:
        embedding, token_usage = functions_content.generate_embedding("hello world")
    finally:
        functions_content.functions_settings.get_settings = original_get_settings
        functions_content.AzureOpenAI = original_azure_openai
        functions_content.time.sleep = original_sleep
        functions_content.random.uniform = original_uniform

    assert embedding == [0.1, 0.2, 0.3], "Expected background embedding generation to return the mocked embedding payload."
    assert token_usage == {
        "prompt_tokens": 4,
        "total_tokens": 4,
        "model_deployment_name": "text-embedding-3-small",
    }, "Expected background embedding generation to preserve token usage metadata."
    assert fake_requests == [{
        "model": "text-embedding-3-small",
        "input": "hello world",
    }], "Expected background embedding generation to call the embedding client with the selected deployment."


if __name__ == "__main__":
    test_file_processing_log_resolves_settings_after_full_app_import()
    test_generate_embedding_resolves_settings_after_full_app_import()
    print("✅ Upload settings helper import-order fix verified.")
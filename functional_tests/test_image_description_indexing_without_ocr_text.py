#!/usr/bin/env python3
# test_image_description_indexing_without_ocr_text.py
"""
Functional test for indexing image descriptions when OCR finds no text.
Version: 0.261.210
Implemented in: 0.261.047 (Development); 0.261.210 (React V2)

Issue #1583: two nearly identical photos of an empty lab floor had no real text. Document
Intelligence Layout returned only a bogus page-number comment for one and nothing for the other,
so the second image was never indexed and its AI vision description was unreachable from chat.
Content Understanding's image analyzer described both photos, but its description was ignored,
and the vision model was always called on the legacy GPT connection even when it was hosted on a
different AI connection.

This test ensures that:
  - the vision block keeps its existing format and is empty for failed or empty analyses,
  - save_chunks and save_chunks_batch embed the same text they store, including the vision block,
    and never write a chunk with nothing to index,
  - an image whose OCR output is empty, or only Document Intelligence page-number annotations, is
    indexed from its vision description, while images with real OCR text, including header and
    footer text, are unchanged,
  - the Content Understanding image analyzer's Summary field is read, and extraction falls back
    to it for standalone images before Document Intelligence Layout, both for workspace uploads
    and for images uploaded straight into a chat,
  - the stored vision model name resolves to the enabled AI connection that hosts it, falling
    back to the legacy GPT connection otherwise, and the admin test uses the same connection,
  - metadata extraction builds its client exactly as before, with the same error messages.

The model-name lookup and the chat upload call-site check run in-process. Checks that need the
real application modules run in fresh normal and optimized processes with external I/O blocked,
stubbing only the Azure-facing calls.
"""

import ast
import copy
from contextlib import ExitStack
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

import pytest


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / "application" / "single_app"
TEST_ROOT = ROOT / "functional_tests"
IMPLEMENTED_IN_VERSION = "0.261.047"

for _path in (str(TEST_ROOT), str(APP_ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from test_support.versioning import assert_app_version_at_least  # noqa: E402


# A 1x1 PNG, enough for code that only reads and base64-encodes the file.
TEST_PNG_BYTES = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c63f8cfc0f01f0005000201e1c5a8e1"
    "0000000049454e44ae426082"
)

# Layout output for the less-exposed photo: a strip of floor tape read as the page number "J".
LESS_EXPOSED_DI_PAGES = [{"page_number": 1, "content": '<!-- PageNumber="J" -->'}]
# Layout output for the overexposed photo: one page with no content.
OVEREXPOSED_DI_PAGES = [{"page_number": 1, "content": ""}]

CU_IMAGE_SUMMARY = (
    "The image shows a mostly empty indoor space with a tiled floor. In the background, there are "
    "several checkerboard calibration patterns placed against the wall."
)
CU_IMAGE_SEARCH_RESULT = {
    "analyzerId": "prebuilt-imageSearch",
    "apiVersion": "2025-11-01",
    "contents": [
        {
            "kind": "document",
            "markdown": "![image](pages/1)\n",
            "fields": {
                "Summary": {"type": "string", "valueString": CU_IMAGE_SUMMARY},
            },
        }
    ],
}

VISION_ANALYSIS = {
    "description": "A grayscale photo of an empty laboratory floor with checkerboard calibration targets on the far wall.",
    "objects": ["tiled floor", "checkerboard calibration target", "wall"],
    "text": "",
    "analysis": "The room looks like a camera calibration area in a robotics lab.",
    "model": "gpt-5.4",
}
VISION_RESPONSE_JSON = {
    "description": VISION_ANALYSIS["description"],
    "objects": VISION_ANALYSIS["objects"],
    "text": "",
    "analysis": VISION_ANALYSIS["analysis"],
}

CU_SETTINGS = {
    "azure_content_understanding_endpoint": "https://content-understanding.invalid",
    "azure_content_understanding_key": "content-understanding-test-key",
    "azure_content_understanding_authentication_type": "key",
}

PRIMARY_ENDPOINT_SECRET = "primary-endpoint-secret-must-not-be-logged"
GLOBAL_ENDPOINT_SECRET = "global-endpoint-secret-must-not-be-logged"


def _require(condition, message):
    """Raise explicitly so checks survive python -O."""
    if not condition:
        raise AssertionError(message)


def build_model_endpoints():
    """Two AI connections: the primary one, and 'Global', which alone hosts gpt-5.6-luna."""
    return [
        {
            "id": "primary-endpoint",
            "name": "Primary",
            "provider": "aoai",
            "enabled": True,
            "connection": {
                "endpoint": "https://simplechat-openai.invalid",
                "openai_api_version": "2024-12-01-preview",
            },
            "auth": {"type": "api_key", "api_key": PRIMARY_ENDPOINT_SECRET},
            "models": [
                {"id": "gpt-4o-model", "deploymentName": "gpt-4o", "modelName": "gpt-4o", "enabled": True},
            ],
        },
        {
            "id": "global-endpoint",
            "name": "Global",
            "provider": "aoai",
            "enabled": True,
            "connection": {
                "endpoint": "https://aoai-global-team.invalid",
                "openai_api_version": "2025-04-01-preview",
            },
            "auth": {"type": "api_key", "api_key": GLOBAL_ENDPOINT_SECRET},
            "models": [
                {
                    "id": "luna-model",
                    "deploymentName": "luna-prod",
                    "modelName": "gpt-5.6-luna",
                    "displayName": "GPT-5.6 Luna",
                    "enabled": True,
                },
            ],
        },
    ]


def legacy_vision_block(vision_analysis):
    """The inline formatting save_chunks used before this fix, kept here for format parity."""
    vision_text_parts = []
    vision_text_parts.append("\n\n=== AI Vision Analysis ===")
    vision_text_parts.append(f"Model: {vision_analysis.get('model', 'unknown')}")
    if vision_analysis.get('description'):
        vision_text_parts.append(f"\nDescription: {vision_analysis['description']}")
    if vision_analysis.get('objects'):
        objects_list = vision_analysis['objects']
        if isinstance(objects_list, list):
            vision_text_parts.append(f"\nObjects Detected: {', '.join(objects_list)}")
        else:
            vision_text_parts.append(f"\nObjects Detected: {objects_list}")
    if vision_analysis.get('text'):
        vision_text_parts.append(f"\nVisible Text: {vision_analysis['text']}")
    if vision_analysis.get('analysis'):
        vision_text_parts.append(f"\nContextual Analysis: {vision_analysis['analysis']}")
    return "\n".join(vision_text_parts)


class FakeChatClient:
    """Records chat completion requests and answers with a canned vision analysis."""

    def __init__(self, content):
        self.requests = []
        self._content = content
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **params):
        self.requests.append(params)
        return SimpleNamespace(
            id="chatcmpl-test",
            model=params.get("model"),
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=20, total_tokens=30),
            choices=[
                SimpleNamespace(
                    finish_reason="stop",
                    message=SimpleNamespace(content=self._content, refusal=None),
                )
            ],
        )


def make_recording_azure_openai(records):
    """Return an AzureOpenAI stand-in that records its constructor arguments."""

    class RecordingAzureOpenAI(FakeChatClient):
        def __init__(self, **kwargs):
            super().__init__(json.dumps(VISION_RESPONSE_JSON))
            self.init_kwargs = kwargs
            records.append(self)

    return RecordingAzureOpenAI


def make_recording_client_builder(records, client=None):
    """Return a build_model_endpoint_sync_chat_client stand-in that records its arguments."""

    def fake_build(*args, **kwargs):
        built_client = client or FakeChatClient(json.dumps(VISION_RESPONSE_JSON))
        records.append({"args": args, "kwargs": kwargs, "client": built_client})
        return built_client, "azure_openai"

    return fake_build


def write_test_image(directory, file_name="lab-floor.png"):
    image_path = os.path.join(directory, file_name)
    with open(image_path, "wb") as image_file:
        image_file.write(TEST_PNG_BYTES)
    return image_path


# ---------------------------------------------------------------------------
# In-process checks of the pure model-name lookup
# ---------------------------------------------------------------------------

def _load_model_endpoint_types():
    import functions_model_endpoint_types  # noqa: PLC0415 - loaded after sys.path is prepared

    return functions_model_endpoint_types


def test_model_name_lookup_matches_deployment_model_name_and_id():
    """A stored name matches a deployment, the request model, a model name, or a model id."""
    find = _load_model_endpoint_types().find_enabled_model_endpoint_for_model_name
    endpoints = build_model_endpoints()

    for stored_name in ("luna-prod", "gpt-5.6-luna", "luna-model", "  gpt-5.6-luna  "):
        endpoint, model = find(endpoints, stored_name)
        assert endpoint is endpoints[1], f"{stored_name!r} should resolve to the Global connection"
        assert model is endpoints[1]["models"][0], f"{stored_name!r} should resolve to the Luna model"

    endpoint, model = find(endpoints, "gpt-4o")
    assert endpoint is endpoints[0] and model["id"] == "gpt-4o-model"

    # OpenAI-style Custom connections send the model name, so it is their request model.
    custom_endpoints = [{
        "id": "custom-endpoint",
        "provider": "custom",
        "api_type": "openai",
        "enabled": True,
        "models": [{"id": "llama-model", "modelName": "llama-3.2-vision", "enabled": True}],
    }]
    endpoint, model = find(custom_endpoints, "llama-3.2-vision")
    assert endpoint is custom_endpoints[0] and model["id"] == "llama-model"


def test_model_name_lookup_prefers_deployments_then_first_endpoint():
    """Deployment and request-model matches beat model names; ties go to the first endpoint."""
    find = _load_model_endpoint_types().find_enabled_model_endpoint_for_model_name
    endpoints = [
        {
            "id": "family-endpoint",
            "enabled": True,
            "models": [{"id": "family-model", "deploymentName": "gpt-4o-prod", "modelName": "gpt-4o", "enabled": True}],
        },
        {
            "id": "deployment-endpoint",
            "enabled": True,
            "models": [{"id": "deployment-model", "deploymentName": "gpt-4o", "enabled": True}],
        },
        {
            "id": "second-deployment-endpoint",
            "enabled": True,
            "models": [{"id": "second-deployment-model", "deploymentName": "gpt-4o", "enabled": True}],
        },
    ]

    endpoint, model = find(endpoints, "gpt-4o")
    assert endpoint["id"] == "deployment-endpoint", "A deployment match must beat an earlier model-name match."
    assert model["id"] == "deployment-model", "The first deployment match in endpoint order must win."

    endpoints_by_name = [
        {"id": "first", "enabled": True, "models": [{"id": "a", "deploymentName": "a-prod", "modelName": "shared", "enabled": True}]},
        {"id": "second", "enabled": True, "models": [{"id": "b", "deploymentName": "b-prod", "modelName": "shared", "enabled": True}]},
    ]
    endpoint, _ = find(endpoints_by_name, "shared")
    assert endpoint["id"] == "first", "Equal model-name matches must resolve to the first endpoint."

    endpoints_by_id = [
        {"id": "first", "enabled": True, "models": [{"id": "shared-id", "deploymentName": "x-prod", "enabled": True}]},
        {"id": "second", "enabled": True, "models": [
            {"id": "other", "deploymentName": "other-prod", "modelName": "shared-id", "enabled": True},
        ]},
    ]
    endpoint, _ = find(endpoints_by_id, "shared-id")
    assert endpoint["id"] == "second", "A model-name match must beat an earlier model-id match."

    endpoints_only_id = [
        {"id": "first", "enabled": True, "models": [{"id": "shared-id", "deploymentName": "x-prod", "enabled": True}]},
        {"id": "second", "enabled": True, "models": [{"id": "shared-id", "deploymentName": "y-prod", "enabled": True}]},
    ]
    endpoint, _ = find(endpoints_only_id, "shared-id")
    assert endpoint["id"] == "first", "Equal model-id matches must resolve to the first endpoint."


def test_model_name_lookup_ignores_disabled_endpoints_and_models():
    """Disabled endpoints and disabled models never match."""
    find = _load_model_endpoint_types().find_enabled_model_endpoint_for_model_name

    disabled_endpoint = build_model_endpoints()
    disabled_endpoint[1]["enabled"] = False
    assert find(disabled_endpoint, "gpt-5.6-luna") == (None, None)

    disabled_model = build_model_endpoints()
    disabled_model[1]["models"][0]["enabled"] = False
    assert find(disabled_model, "luna-prod") == (None, None)

    fallback = [
        {"id": "off", "enabled": False, "models": [{"id": "m1", "deploymentName": "vision", "enabled": True}]},
        {"id": "on", "enabled": True, "models": [
            {"id": "m2", "deploymentName": "vision", "enabled": False},
            {"id": "m3", "deploymentName": "vision", "enabled": True},
        ]},
    ]
    endpoint, model = find(fallback, "vision")
    assert endpoint["id"] == "on" and model["id"] == "m3"


def test_model_name_lookup_handles_blank_and_malformed_input():
    """Blank names and malformed endpoint data return (None, None) instead of raising."""
    find = _load_model_endpoint_types().find_enabled_model_endpoint_for_model_name
    endpoints = build_model_endpoints()

    for model_name in (None, "", "   "):
        assert find(endpoints, model_name) == (None, None)
    for malformed in (None, {}, "gpt-4o", 42):
        assert find(malformed, "gpt-4o") == (None, None)
    assert find([None, "text", {"id": "no-models", "enabled": True}, {"models": "gpt-4o"}], "gpt-4o") == (None, None)
    assert find([{"id": "e", "models": [None, "gpt-4o", {"deploymentName": "gpt-4o"}]}], "gpt-4o")[1] == {"deploymentName": "gpt-4o"}
    assert find(endpoints, "not-configured") == (None, None)

    before = copy.deepcopy(endpoints)
    find(endpoints, "gpt-5.6-luna")
    assert endpoints == before, "The lookup must not mutate the endpoint records."


def test_version_is_at_least_implementation_version():
    """The app version must be at or beyond the version this fix shipped in."""
    assert_app_version_at_least(IMPLEMENTED_IN_VERSION)


def _call_name(call_node):
    if isinstance(call_node.func, ast.Name):
        return call_node.func.id
    if isinstance(call_node.func, ast.Attribute):
        return call_node.func.attr
    return ""


def test_chat_uploads_request_the_image_analyzer_fallback():
    """Images uploaded straight into a chat must get the same image-analyzer fallback."""
    tree = ast.parse((APP_ROOT / "route_frontend_chats.py").read_text(encoding="utf-8-sig"))
    calls = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call) and _call_name(node) == "extract_content_with_extraction_engine"
    ]
    assert len(calls) == 1, f"Expected one chat upload extraction call site, found {len(calls)}."

    keywords = {keyword.arg: keyword.value for keyword in calls[0].keywords}
    assert isinstance(keywords.get("is_image"), ast.Name) and keywords["is_image"].id == "is_image_file", (
        "The chat upload route must pass is_image=is_image_file to extract_content_with_extraction_engine()."
    )

    enclosing_function = min(
        (
            node for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.lineno <= calls[0].lineno <= node.end_lineno
        ),
        key=lambda node: node.end_lineno - node.lineno,
    )
    assert any(
        isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "is_image_file" for target in node.targets)
        for node in ast.walk(enclosing_function)
    ), "is_image_file must be computed in the same chat upload function."


# ---------------------------------------------------------------------------
# Real-module checks, run by the offline probe in a fresh process
# ---------------------------------------------------------------------------

def check_vision_block_formatting(documents):
    print("Checking vision block formatting...")
    block = documents._format_vision_analysis_block(VISION_ANALYSIS)
    _require(block == legacy_vision_block(VISION_ANALYSIS), "A valid analysis must keep the existing vision block format.")
    _require(block.startswith("\n\n=== AI Vision Analysis ==="), "The block must still start with the section header.")

    string_objects = {**VISION_ANALYSIS, "objects": "tiled floor, wall"}
    _require(
        documents._format_vision_analysis_block(string_objects) == legacy_vision_block(string_objects),
        "A non-list objects value must keep the existing format.",
    )

    # json.loads fallback analyses carry the raw response as a description and no error key.
    parse_failed = {"description": "Raw model text", "raw_response": "Raw model text", "parse_failed": True, "model": "gpt-5.4"}
    _require("Description: Raw model text" in documents._format_vision_analysis_block(parse_failed),
             "An analysis whose JSON could not be parsed still has a usable description.")

    unusable = [
        None,
        "not a dict",
        {},
        {"model": "gpt-5.4"},
        {"description": "   ", "objects": [], "text": "", "analysis": None, "model": "gpt-5.4"},
        {"description": "Model returned empty content with no refusal message",
         "error": "Model returned empty content with no refusal message", "model": "gpt-5.4", "parse_failed": True},
        {"error": ""},
    ]
    for analysis in unusable:
        _require(documents._format_vision_analysis_block(analysis) == "",
                 f"Unusable analysis must format to an empty string: {analysis!r}")
        _require(not documents._is_usable_vision_analysis(analysis), f"Analysis must be unusable: {analysis!r}")
    _require(documents._is_usable_vision_analysis({"objects": ["floor"]}), "Objects alone make an analysis usable.")

    append = documents._append_vision_block_to_chunk_text
    _require(append("EXIT 12", block) == "EXIT 12" + block, "OCR text must be followed by the unchanged block.")
    _require(append("", block) == block.lstrip(), "Without OCR text the block must not keep leading blank lines.")
    _require(append(" \n", block).startswith("=== AI Vision Analysis ==="), "Whitespace-only text counts as no text.")
    _require(append(None, "") == "" and append("EXIT 12", "") == "EXIT 12", "No block leaves the text unchanged.")


def check_comment_only_ocr_is_not_text(documents):
    print("Checking Document Intelligence page-number-only OCR detection...")
    has_text = documents._has_indexable_ocr_text
    for content in (
        '<!-- PageNumber="J" -->',
        '<!-- PageNumber="1" -->\n\n<!-- PageBreak -->\n<!-- PageNumber="2" -->',
        "<!--PageNumber=\"12\"-->",
        "",
        None,
        " \n ",
    ):
        _require(not has_text(content), f"Content must count as no text: {content!r}")
    for content in (
        '<!-- PageNumber="1" -->\nEXIT 12',
        # Header and footer comments carry recognized text, so they must keep the image indexed.
        '<!-- PageHeader="Lab 3 - Calibration Area" -->',
        '<!-- PageFooter="Contoso Confidential" -->\n<!-- PageNumber="1" -->',
        "Selection marks detected:\n- Door closed: checked",
        "J",
    ):
        _require(has_text(content), f"Content must count as real text: {content!r}")


def _run_save_chunks(documents, page_text, vision_analysis, max_characters=100000, legacy_embedding=True):
    embedded_inputs = []
    uploaded_documents = []
    metadata = {"id": "doc-1583", "version": 1, "title": "", "tags": [], "shared_user_ids": []}
    if vision_analysis is not None:
        metadata["vision_analysis"] = vision_analysis

    def fake_generate_embedding(text):
        embedded_inputs.append(text)
        return [0.25, 0.5], {"total_tokens": 42, "prompt_tokens": 42, "model_deployment_name": "text-embedding-3-small"}

    def fake_search_write(search_client, operation_name, *args, **kwargs):
        uploaded_documents.extend(kwargs.get("documents") or [])
        return [{"succeeded": True}]

    with ExitStack() as stack:
        stack.enter_context(patch.object(documents, "get_document_metadata", lambda **_: copy.deepcopy(metadata)))
        stack.enter_context(patch.object(documents, "generate_embedding", fake_generate_embedding))
        stack.enter_context(patch.object(documents, "get_embedding_safe_chunk_characters", lambda *a, **k: max_characters))
        # React V2 refuses an oversized chunk for a non-legacy embedding profile instead of
        # clamping it; the profile is supplied here rather than read from settings.
        stack.enter_context(patch.object(
            documents, "active_embedding_profile", lambda *a, **k: SimpleNamespace(legacy=legacy_embedding),
        ))
        stack.enter_context(patch.object(documents, "_execute_document_search_write", fake_search_write))
        stack.enter_context(patch.object(documents, "add_file_task_to_file_processing_log", lambda **_: None))
        stack.enter_context(patch.object(documents, "log_event", lambda *a, **k: None))
        stack.enter_context(patch.dict(documents.CLIENTS, {"search_client_user": object()}))
        token_usage = documents.save_chunks(
            page_text_content=page_text,
            page_number=1,
            file_name="lab-floor.png",
            user_id="user-1",
            document_id="doc-1583",
        )
    return token_usage, embedded_inputs, uploaded_documents


def check_save_chunks_embeds_the_stored_text(documents):
    print("Checking save_chunks embeds and stores the vision description...")
    block = legacy_vision_block(VISION_ANALYSIS)

    token_usage, embedded, uploaded = _run_save_chunks(documents, "", VISION_ANALYSIS)
    _require(len(uploaded) == 1, "A description-only image chunk must be written.")
    chunk_text = uploaded[0]["chunk_text"]
    _require(chunk_text == block.lstrip(), "The description-only chunk must hold exactly the vision block.")
    _require(chunk_text.startswith("=== AI Vision Analysis ==="), "The chunk must not start with blank lines.")
    _require(VISION_ANALYSIS["description"] in chunk_text, "The chunk must contain the vision description.")
    _require(embedded == [chunk_text], "The embedding must be generated from the stored chunk text.")
    _require(uploaded[0]["id"] == "doc-1583_1" and uploaded[0]["page_number"] == 1, "The chunk must be page 1.")
    _require(token_usage and token_usage["total_tokens"] == 42, "Token usage must still be returned.")

    _, embedded, uploaded = _run_save_chunks(documents, "EXIT 12", VISION_ANALYSIS)
    _require(uploaded[0]["chunk_text"] == "EXIT 12" + block, "OCR chunks must keep text followed by the vision block.")
    _require(embedded == ["EXIT 12" + block], "The vector must reflect the description, not only the OCR text.")

    _, embedded, uploaded = _run_save_chunks(documents, "Quarterly report text.", None)
    _require(uploaded[0]["chunk_text"] == "Quarterly report text.", "Chunks without vision analysis are unchanged.")
    _require(embedded == ["Quarterly report text."], "Embeddings without vision analysis are unchanged.")

    error_analysis = {"description": "Model refused to respond", "error": "Model refused to respond", "model": "gpt-5.4"}
    for page_text, analysis in (("", error_analysis), ("", None), ("  \n", {"model": "gpt-5.4"})):
        token_usage, embedded, uploaded = _run_save_chunks(documents, page_text, analysis)
        _require(token_usage is None and not embedded and not uploaded,
                 f"A chunk with nothing to index must not be embedded or written: {page_text!r}, {analysis!r}")

    _, embedded, uploaded = _run_save_chunks(documents, "", error_analysis.copy() | {"description": ""}, max_characters=100000)
    _require(not uploaded, "A failed vision analysis must never be indexed.")

    long_text = "OCR " * 40
    _, embedded, uploaded = _run_save_chunks(documents, long_text, VISION_ANALYSIS, max_characters=60)
    _require(len(embedded[0]) == 60 and embedded[0] == (long_text + block)[:60],
             "The last-resort guard must still clamp only the embedding input.")
    _require(uploaded[0]["chunk_text"] == long_text + block, "The stored chunk text must never be clamped.")

    # React V2: a non-legacy embedding profile refuses an oversized chunk. Appending the vision
    # block must not turn a page that fits into a refused one, so that page embeds its OCR text.
    _, embedded, uploaded = _run_save_chunks(
        documents, "EXIT 12", VISION_ANALYSIS, max_characters=60, legacy_embedding=False,
    )
    _require(embedded == ["EXIT 12"], "A page that fits must embed its OCR text when the vision block does not.")
    _require(uploaded[0]["chunk_text"] == "EXIT 12" + block, "The stored text must still carry the vision block.")

    refused = False
    try:
        _run_save_chunks(documents, long_text, VISION_ANALYSIS, max_characters=60, legacy_embedding=False)
    except Exception as error:  # noqa: BLE001 - the V2 guard raises AIConnectionError.
        refused = "too large" in str(error)
    _require(refused, "An OCR page that is itself too large is still refused, as before.")


def check_save_chunks_batch_matches_save_chunks(documents, content):
    print("Checking save_chunks_batch embeds the same text it stores...")
    block = legacy_vision_block(VISION_ANALYSIS)
    batched_inputs = []
    uploaded_documents = []

    def fake_batch(texts):
        batched_inputs.append(list(texts))
        return [([0.1, 0.2], {"total_tokens": 5, "prompt_tokens": 5, "model_deployment_name": "text-embedding-3-small"}) for _ in texts]

    def fake_search_write(search_client, operation_name, *args, **kwargs):
        uploaded_documents.extend(kwargs.get("documents") or [])
        return [{"succeeded": True}]

    def run(metadata, chunks):
        batched_inputs.clear()
        uploaded_documents.clear()
        with ExitStack() as stack:
            stack.enter_context(patch.object(documents, "get_document_metadata", lambda **_: copy.deepcopy(metadata)))
            stack.enter_context(patch.object(content, "generate_embeddings_batch", fake_batch))
            stack.enter_context(patch.object(documents, "_execute_document_search_write", fake_search_write))
            stack.enter_context(patch.object(documents, "log_event", lambda *a, **k: None))
            stack.enter_context(patch.dict(documents.CLIENTS, {"search_client_user": object()}))
            return documents.save_chunks_batch(chunks, "user-1", "doc-1583")

    chunks = [
        {"page_text_content": "Page one", "page_number": 1, "file_name": "lab-floor.png"},
        {"page_text_content": "", "page_number": 2, "file_name": "lab-floor.png"},
    ]
    usage = run({"version": 1, "vision_analysis": VISION_ANALYSIS}, chunks)
    stored = [document["chunk_text"] for document in uploaded_documents]
    _require(stored == ["Page one" + block, block.lstrip()], "Batch chunks must use the shared vision formatting.")
    _require(batched_inputs == [stored], "Batch embeddings must be generated from the stored chunk text.")
    _require(usage["total_tokens"] == 10, "Batch token usage must still be accumulated.")

    usage = run({"version": 1}, chunks)
    stored = [document["chunk_text"] for document in uploaded_documents]
    _require(stored == ["Page one"] and batched_inputs == [["Page one"]],
             "Without a vision analysis, empty batch chunks are skipped and others are unchanged.")

    usage = run({"version": 1}, [{"page_text_content": " ", "page_number": 1, "file_name": "x.md"}])
    _require(not batched_inputs and not uploaded_documents and usage["total_tokens"] == 0,
             "A batch with nothing to index must not call the embedding endpoint.")


def _run_image_ingestion(documents, image_path, di_pages, vision_result, enable_vision=True):
    saved_chunks = []
    extraction_calls = []
    status_updates = []
    vision_calls = []
    settings = {
        "enable_multimodal_vision": enable_vision,
        "enable_extract_meta_data": False,
        "enable_enhanced_extraction": True,
        "document_intelligence_pdf_image_extraction_mode": "layout",
    }

    def fake_extract(file_path, extraction_mode, extraction_engine, settings=None, pages=None, is_image=False):
        extraction_calls.append({"extraction_mode": extraction_mode, "extraction_engine": extraction_engine, "is_image": is_image})
        return copy.deepcopy(di_pages), "document_intelligence", "Content Understanding returned no content, so Document Intelligence Layout was used"

    def fake_vision(*args, **kwargs):
        vision_calls.append(args)
        return copy.deepcopy(vision_result)

    def fake_save_chunks(**kwargs):
        saved_chunks.append(kwargs)
        return {"total_tokens": 7, "prompt_tokens": 7, "model_deployment_name": "text-embedding-3-small"}

    with ExitStack() as stack:
        stack.enter_context(patch.object(documents, "get_settings", lambda: dict(settings)))
        stack.enter_context(patch.object(documents, "get_chunk_size_config", lambda *a, **k: {}))
        stack.enter_context(patch.object(documents, "is_enhanced_extraction_enabled", lambda *a, **k: True))
        stack.enter_context(patch.object(documents, "get_effective_document_intelligence_pdf_image_extraction_mode", lambda *a, **k: "layout"))
        stack.enter_context(patch.object(documents, "get_document_intelligence_auto_sample_pages", lambda *a, **k: 3))
        stack.enter_context(patch.object(documents, "_resolve_extraction_engine_for_mode", lambda *a, **k: ("content_understanding", "")))
        stack.enter_context(patch.object(documents, "upload_to_blob", lambda **_: None))
        stack.enter_context(patch.object(documents, "_extract_pages_with_extraction_engine", fake_extract))
        stack.enter_context(patch.object(documents, "analyze_image_with_vision_model", fake_vision))
        stack.enter_context(patch.object(documents, "get_document_metadata", lambda **_: {"number_of_pages": 1}))
        stack.enter_context(patch.object(documents, "save_chunks", fake_save_chunks))
        stack.enter_context(patch.object(documents, "log_event", lambda *a, **k: None))
        result = documents.process_di_document(
            document_id="doc-1583",
            user_id="user-1",
            temp_file_path=image_path,
            original_filename="lab-floor.png",
            file_ext=".png",
            enable_enhanced_citations=True,
            update_callback=lambda **kwargs: status_updates.append(kwargs),
            auto_extract_metadata=False,
        )
    return result, saved_chunks, extraction_calls, status_updates, vision_calls


def check_text_free_images_are_indexed_from_vision(documents, work_dir):
    print("Checking text-free images are indexed from their vision description...")
    image_path = write_test_image(work_dir)
    description_only_chunk = {
        "page_text_content": "",
        "page_number": 1,
        "file_name": "lab-floor.png",
        "user_id": "user-1",
        "document_id": "doc-1583",
    }

    for label, di_pages in (
        ("less-exposed photo (comment-only Layout output)", LESS_EXPOSED_DI_PAGES),
        ("overexposed photo (empty Layout page)", OVEREXPOSED_DI_PAGES),
        ("no pages at all", []),
    ):
        result, saved, extraction_calls, statuses, _ = _run_image_ingestion(documents, image_path, di_pages, VISION_ANALYSIS)
        _require(result[0] == 1, f"{label}: exactly one chunk must be saved, got {result[0]}.")
        _require(saved == [description_only_chunk], f"{label}: expected one description-only page-1 chunk, got {saved}.")
        _require(result[1] == 7 and result[2] == "text-embedding-3-small", f"{label}: token usage must be accumulated.")
        _require(extraction_calls and extraction_calls[0]["is_image"] is True, f"{label}: is_image must reach extraction.")
        _require(any("indexing its AI vision description" in str(update.get("status")) for update in statuses),
                 f"{label}: the status must say the vision description was indexed.")

    result, saved, _, _, _ = _run_image_ingestion(
        documents, image_path, [{"page_number": 1, "content": "EXIT 12"}], VISION_ANALYSIS
    )
    _require(result[0] == 1 and saved[0]["page_text_content"] == "EXIT 12",
             "Images with real OCR text must keep their OCR chunk unchanged.")

    header_only_pages = [{"page_number": 1, "content": '<!-- PageHeader="Lab 3 - Calibration Area" -->'}]
    for vision_result in (VISION_ANALYSIS, None):
        result, saved, _, _, _ = _run_image_ingestion(documents, image_path, header_only_pages, vision_result)
        _require(result[0] == 1 and saved[0]["page_text_content"] == header_only_pages[0]["content"],
                 "Text Layout reports as a page header is real OCR text and must stay indexed.")

    result, saved, _, _, _ = _run_image_ingestion(
        documents,
        image_path,
        [{"page_number": 1, "content": '<!-- PageNumber="1" -->'}, {"page_number": 2, "content": "Second page text"}],
        VISION_ANALYSIS,
    )
    _require(result[0] == 1 and [(c["page_number"], c["page_text_content"]) for c in saved] == [(2, "Second page text")],
             "Only OCR pages with real text may be saved.")

    failed_analysis = {"description": "Model returned empty content with no refusal message",
                       "error": "Model returned empty content with no refusal message", "model": "gpt-5.4", "parse_failed": True}
    for label, vision_result, enable_vision in (
        ("failed vision analysis", failed_analysis, True),
        ("empty vision analysis", {"description": "", "objects": [], "text": "", "analysis": "", "model": "gpt-5.4"}, True),
        ("no vision analysis", None, True),
        ("vision disabled", VISION_ANALYSIS, False),
    ):
        result, saved, _, _, vision_calls = _run_image_ingestion(
            documents, image_path, LESS_EXPOSED_DI_PAGES, vision_result, enable_vision=enable_vision
        )
        _require(result[0] == 0 and not saved, f"{label}: a text-free image with no usable description must save nothing.")
        if not enable_vision:
            _require(not vision_calls, "Vision analysis must not run when it is disabled.")


def check_content_understanding_image_analyzer(content_understanding, work_dir):
    print("Checking the Content Understanding image analyzer parsing...")
    image_path = write_test_image(work_dir, "cu-image.png")
    analyzer_calls = []

    def analyze(result):
        analyzer_calls.clear()

        def fake_analyze_file(file_path, analyzer_id=None, page_range=None, settings=None, config_override=None, max_wait_seconds=None):
            analyzer_calls.append(analyzer_id)
            return copy.deepcopy(result)

        with patch.object(content_understanding, "analyze_file_with_content_understanding", fake_analyze_file):
            return content_understanding.analyze_image_with_content_understanding(image_path, settings=dict(CU_SETTINGS))

    text = analyze(CU_IMAGE_SEARCH_RESULT)
    _require(text == CU_IMAGE_SUMMARY, f"The Summary field must be returned as plain text, got {text!r}.")
    _require(analyzer_calls == ["prebuilt-imageSearch"], f"The configured image analyzer must be used: {analyzer_calls}.")

    with_fields = copy.deepcopy(CU_IMAGE_SEARCH_RESULT)
    with_fields["contents"][0]["fields"].update({
        "Setting": {"type": "string", "valueString": "Robotics calibration lab"},
        "ObjectCount": {"type": "number", "valueNumber": 4},
        "Caption": {"type": "string", "valueString": "   "},
        "Tags": {"type": "array", "valueArray": [{"type": "string", "valueString": "floor"}]},
    })
    text = analyze(with_fields)
    _require(text == f"{CU_IMAGE_SUMMARY}\n\nSetting: Robotics calibration lab",
             f"Other string fields must be emitted as 'Name: value' after the summary, got {text!r}.")

    only_placeholder = {"contents": [{"kind": "document", "markdown": "![image](pages/1)\n![image](pages/2)"}]}
    _require(analyze(only_placeholder) == "", "Placeholder-only markdown must not count as a description.")

    with_markdown = copy.deepcopy(CU_IMAGE_SEARCH_RESULT)
    with_markdown["contents"][0]["markdown"] = "EXIT 12\n\n![image](pages/1)"
    text = analyze(with_markdown)
    _require(text == f"EXIT 12\n\n![image](pages/1)\n\n{CU_IMAGE_SUMMARY}", f"Real markdown must be kept, got {text!r}.")

    with_figures = {
        "contents": [{
            "kind": "document",
            "markdown": "![image](pages/1)",
            "fields": {"Summary": {"type": "string", "valueString": CU_IMAGE_SUMMARY}},
            "figures": [
                {"id": "fig-1", "description": "A checkerboard calibration target.", "span": {"offset": 0, "length": 5}},
                {"id": "fig-2", "description": CU_IMAGE_SUMMARY, "span": {"offset": 0, "length": 5}},
            ],
        }]
    }
    text = analyze(with_figures)
    _require("Figure (fig-1):\nA checkerboard calibration target." in text, "Figure descriptions must still be appended.")
    _require(text.count(CU_IMAGE_SUMMARY) == 1, "A figure description already in the summary must not be repeated.")

    _require(analyze({"contents": []}) == "" and analyze({}) == "", "An empty result must return an empty string.")


def check_extraction_engine_image_fallback(content, content_understanding, work_dir):
    print("Checking the extraction engine image analyzer fallback...")
    image_path = write_test_image(work_dir, "engine-image.png")
    di_calls = []
    image_analyzer_calls = []
    warnings = []
    di_pages = [{"page_number": 1, "content": '<!-- PageNumber="J" -->'}]
    no_content_reason = "Content Understanding returned no content, so Document Intelligence Layout was used"

    def run(document_pages, image_result, is_image=True, extraction_mode="layout", document_error=None):
        di_calls.clear()
        image_analyzer_calls.clear()
        warnings.clear()

        def fake_document_analyzer(file_path, pages=None, settings=None):
            if document_error:
                raise document_error
            return copy.deepcopy(document_pages)

        def fake_image_analyzer(file_path, settings=None):
            image_analyzer_calls.append(file_path)
            if isinstance(image_result, Exception):
                raise image_result
            return image_result

        def fake_azure_di(file_path, extraction_mode="read", pages=None):
            di_calls.append(extraction_mode)
            return copy.deepcopy(di_pages)

        def capture_log(message, *args, **kwargs):
            warnings.append(str(message))

        with ExitStack() as stack:
            stack.enter_context(patch.object(content_understanding, "extract_content_with_content_understanding", fake_document_analyzer))
            stack.enter_context(patch.object(content_understanding, "analyze_image_with_content_understanding", fake_image_analyzer))
            stack.enter_context(patch.object(content, "extract_content_with_azure_di", fake_azure_di))
            stack.enter_context(patch.object(content, "log_event", capture_log))
            return content.extract_content_with_extraction_engine(
                image_path,
                extraction_mode=extraction_mode,
                extraction_engine="content_understanding",
                settings=dict(CU_SETTINGS),
                is_image=is_image,
            )

    pages, engine, reason = run([], CU_IMAGE_SUMMARY)
    _require(pages == [{"page_number": 1, "content": CU_IMAGE_SUMMARY}], f"The description must become page 1, got {pages}.")
    _require(engine == "content_understanding", "The image analyzer result must be attributed to Content Understanding.")
    _require(reason == content.CONTENT_UNDERSTANDING_IMAGE_ANALYZER_REASON and len(reason) < 120,
             "The persisted reason must name the image analyzer and stay short.")
    _require(not di_calls, "Document Intelligence must not run when the image analyzer described the image.")

    for label, image_result in (("analyzer failure", RuntimeError("image analyzer unavailable")), ("empty description", "  ")):
        pages, engine, reason = run([], image_result)
        _require(pages == di_pages and engine == "document_intelligence" and reason == no_content_reason,
                 f"{label}: must fall back to Document Intelligence Layout exactly as before.")
        _require(di_calls == ["layout"], f"{label}: the fallback must use Layout.")
        _require(any("image analyzer" in warning for warning in warnings), f"{label}: a warning must be logged.")

    pages, engine, reason = run([], CU_IMAGE_SUMMARY, is_image=False)
    _require(not image_analyzer_calls and di_calls == ["layout"] and reason == no_content_reason,
             "PDFs and other non-image files must keep their existing fallback.")

    cu_pages = [{"page_number": 1, "content": "# Floor plan\n\nRoom 101"}]
    pages, engine, reason = run(cu_pages, CU_IMAGE_SUMMARY)
    _require(pages == cu_pages and engine == "content_understanding" and reason == "" and not image_analyzer_calls,
             "Document analyzer content must be used as-is without calling the image analyzer.")

    pages, engine, reason = run([], CU_IMAGE_SUMMARY, document_error=RuntimeError("service unavailable"))
    _require(not image_analyzer_calls and engine == "document_intelligence" and reason.startswith("Content Understanding failed"),
             "A document analyzer failure must keep the existing failure fallback.")

    pages, engine, reason = run([], CU_IMAGE_SUMMARY, extraction_mode="read")
    _require(not image_analyzer_calls and di_calls == ["read"] and engine == "document_intelligence",
             "Standard extraction must stay on Document Intelligence Read.")


def _analyze_with_vision(documents, image_path, settings):
    client_builds = []
    legacy_clients = []
    key_vault_lookups = []
    logs = []

    def fake_key_vault(endpoint_cfg, scope_value, scope="global", return_type=None):
        key_vault_lookups.append({"scope_value": scope_value, "scope": scope, "return_type": return_type})
        return endpoint_cfg

    def capture_log(message, extra=None, level=None, **kwargs):
        logs.append({"message": str(message), "extra": extra or {}, "level": level})

    with ExitStack() as stack:
        stack.enter_context(patch.object(documents, "build_model_endpoint_sync_chat_client", make_recording_client_builder(client_builds)))
        stack.enter_context(patch.object(documents, "keyvault_model_endpoint_get_helper", fake_key_vault))
        stack.enter_context(patch.object(documents, "AzureOpenAI", make_recording_azure_openai(legacy_clients)))
        stack.enter_context(patch.object(documents, "log_event", capture_log))
        analysis = documents.analyze_image_with_vision_model(image_path, "user-1", "doc-1583", settings)
    return analysis, client_builds, legacy_clients, key_vault_lookups, logs


def _vision_settings(**overrides):
    settings = {
        "enable_multimodal_vision": True,
        "multimodal_vision_model": "gpt-5.6-luna",
        "enable_multi_model_endpoints": True,
        "model_endpoints": build_model_endpoints(),
        "enable_gpt_apim": False,
        "azure_openai_gpt_endpoint": "https://simplechat-openai.invalid",
        "azure_openai_gpt_api_version": "2024-12-01-preview",
        "azure_openai_gpt_key": "legacy-gpt-key",
        "azure_openai_gpt_authentication_type": "key",
    }
    settings.update(overrides)
    return settings


def check_vision_model_routes_through_its_connection(documents, work_dir):
    print("Checking the vision model is routed through the AI connection that hosts it...")
    image_path = write_test_image(work_dir, "vision-image.png")

    endpoint_cfg, model_cfg = documents.resolve_vision_model_endpoint(_vision_settings(), "gpt-5.6-luna")
    _require(endpoint_cfg is not None and model_cfg is not None
             and endpoint_cfg["id"] == "global-endpoint" and model_cfg["id"] == "luna-model",
             "The stored model name must resolve to the Global connection.")
    _require(documents.resolve_vision_model_endpoint(_vision_settings(enable_multi_model_endpoints=False), "gpt-5.6-luna") == (None, None),
             "Without multi-endpoint models the legacy connection must be used.")
    _require(documents.resolve_vision_model_endpoint(_vision_settings(), "") == (None, None), "A blank name must not match.")

    for stored_name in ("gpt-5.6-luna", "luna-prod"):
        analysis, builds, legacy_clients, key_vault_lookups, logs = _analyze_with_vision(
            documents, image_path, _vision_settings(multimodal_vision_model=stored_name)
        )
        _require(analysis and analysis.get("description") == VISION_ANALYSIS["description"],
                 f"{stored_name}: the routed call must return the parsed analysis.")
        _require(analysis.get("model") == stored_name, f"{stored_name}: the analysis must record the configured model name.")
        _require(len(builds) == 1 and not legacy_clients, f"{stored_name}: only the Global connection client may be built.")
        build_args = builds[0]["args"]
        _require(build_args[1:4] == ("aoai", "https://aoai-global-team.invalid", "2025-04-01-preview"),
                 f"{stored_name}: wrong connection details {build_args[1:4]}.")
        _require(build_args[0].get("api_key") == GLOBAL_ENDPOINT_SECRET, "The connection's own credentials must be used.")
        _require(builds[0]["kwargs"].get("deployment_name") == "luna-prod", "The client must target the deployment.")
        _require(builds[0]["kwargs"].get("identity_context") == {"user_id": "user-1"}, "The caller identity must be passed.")
        requests = builds[0]["client"].requests
        _require(len(requests) == 1 and requests[0]["model"] == "luna-prod",
                 f"{stored_name}: the request must send the resolved request model.")
        _require(key_vault_lookups and key_vault_lookups[0]["scope_value"] == "global-endpoint",
                 "Key Vault-backed secrets must be resolved for the matched connection.")
        routing_logs = [log for log in logs if "Using the AI connection" in log["message"]]
        _require(routing_logs and routing_logs[0]["extra"].get("endpoint_id") == "global-endpoint"
                 and routing_logs[0]["extra"].get("endpoint_name") == "Global",
                 "The connection used must be logged by name and id.")
        _require(GLOBAL_ENDPOINT_SECRET not in json.dumps(logs, default=str), "Connection secrets must never be logged.")

    disabled_endpoint = build_model_endpoints()
    disabled_endpoint[1]["enabled"] = False
    disabled_model = build_model_endpoints()
    disabled_model[1]["models"][0]["enabled"] = False
    for label, settings in (
        ("multi-endpoint models disabled", _vision_settings(enable_multi_model_endpoints=False)),
        ("no matching model", _vision_settings(multimodal_vision_model="gpt-4.1-vision")),
        ("matching endpoint disabled", _vision_settings(model_endpoints=disabled_endpoint)),
        ("matching model disabled", _vision_settings(model_endpoints=disabled_model)),
    ):
        analysis, builds, legacy_clients, _, logs = _analyze_with_vision(documents, image_path, settings)
        _require(not builds and len(legacy_clients) == 1, f"{label}: the legacy GPT connection must be used.")
        legacy = legacy_clients[0]
        _require(legacy.init_kwargs == {
            "api_version": "2024-12-01-preview",
            "azure_endpoint": "https://simplechat-openai.invalid",
            "api_key": "legacy-gpt-key",
        }, f"{label}: the legacy client must be built exactly as before: {legacy.init_kwargs}.")
        _require(legacy.requests[0]["model"] == settings["multimodal_vision_model"],
                 f"{label}: the legacy request must send the stored model name.")
        _require(analysis and analysis.get("description") == VISION_ANALYSIS["description"], f"{label}: analysis expected.")
        _require(any("legacy GPT connection" in log["message"] for log in logs), f"{label}: the legacy connection must be logged.")

    analysis, builds, legacy_clients, _, _ = _analyze_with_vision(
        documents,
        image_path,
        _vision_settings(
            enable_multi_model_endpoints=False,
            enable_gpt_apim=True,
            azure_apim_gpt_endpoint="https://apim.invalid",
            azure_apim_gpt_api_version="2024-10-21",
            azure_apim_gpt_subscription_key="apim-subscription-key",
        ),
    )
    _require(len(legacy_clients) == 1 and legacy_clients[0].init_kwargs == {
        "api_version": "2024-10-21",
        "azure_endpoint": "https://apim.invalid",
        "api_key": "apim-subscription-key",
    }, "The legacy APIM client must be built exactly as before.")

    incomplete = build_model_endpoints()
    incomplete[1]["connection"]["endpoint"] = ""
    analysis, builds, legacy_clients, _, logs = _analyze_with_vision(documents, image_path, _vision_settings(model_endpoints=incomplete))
    _require(analysis is None and not builds and not legacy_clients, "Errors on the matched connection must return None.")
    _require(any("Vision analysis failed" in log["message"] for log in logs), "The failure must be logged.")


def _resolve_metadata_client(documents, settings):
    client_builds = []
    legacy_clients = []
    key_vault_lookups = []

    def fake_key_vault(endpoint_cfg, scope_value, scope="global", return_type=None):
        key_vault_lookups.append({"scope_value": scope_value, "scope": scope, "return_type": return_type})
        return endpoint_cfg

    sentinel_client = object()
    with ExitStack() as stack:
        stack.enter_context(patch.object(documents, "build_model_endpoint_sync_chat_client", make_recording_client_builder(client_builds, sentinel_client)))
        stack.enter_context(patch.object(documents, "keyvault_model_endpoint_get_helper", fake_key_vault))
        stack.enter_context(patch.object(documents, "AzureOpenAI", make_recording_azure_openai(legacy_clients)))
        try:
            result = documents._resolve_metadata_extraction_client(settings, identity_context={"user_id": "user-1"})
            error = None
        except Exception as resolution_error:  # noqa: BLE001 - the check compares the exact error
            result = None
            error = resolution_error
    return result, error, client_builds, legacy_clients, key_vault_lookups, sentinel_client


def check_metadata_extraction_client_is_unchanged(documents):
    print("Checking the metadata extraction client is built exactly as before...")

    def settings_with(selection=None, endpoints=None, **overrides):
        settings = {
            "enable_multi_model_endpoints": True,
            "model_endpoints": endpoints if endpoints is not None else build_model_endpoints(),
            "metadata_extraction_model_selection": selection or {
                "endpoint_id": "global-endpoint",
                "model_id": "luna-model",
                "provider": "aoai",
            },
            "metadata_extraction_model": "gpt-4o",
            "enable_gpt_apim": False,
            "azure_openai_gpt_endpoint": "https://simplechat-openai.invalid",
            "azure_openai_gpt_api_version": "2024-12-01-preview",
            "azure_openai_gpt_key": "legacy-gpt-key",
            "azure_openai_gpt_authentication_type": "key",
        }
        settings.update(overrides)
        return settings

    settings = settings_with()
    result, error, builds, legacy_clients, key_vault_lookups, sentinel = _resolve_metadata_client(documents, settings)
    _require(error is None, f"The selected metadata model must resolve, got {error!r}.")
    _require(result == (sentinel, "luna-prod"), f"Expected (client, deployment), got {result!r}.")
    _require(not legacy_clients and len(builds) == 1, "Only the selected connection client may be built.")
    args, kwargs = builds[0]["args"], builds[0]["kwargs"]
    _require(args[1:4] == ("aoai", "https://aoai-global-team.invalid", "2025-04-01-preview"),
             f"Unexpected connection details: {args[1:4]}.")
    _require(args[0].get("type") == "api_key" and args[0].get("api_key") == GLOBAL_ENDPOINT_SECRET,
             "The endpoint auth must be passed through.")
    _require(kwargs.get("deployment_name") == "luna-prod" and kwargs.get("api_type") == "" and kwargs.get("anthropic_version") == "",
             f"Unexpected client arguments: {kwargs}.")
    _require(kwargs.get("allow_private_custom_endpoints") is False and kwargs.get("settings") is settings,
             "The private endpoint flag and settings must be passed through.")
    _require(kwargs.get("endpoint_config", {}).get("id") == "global-endpoint", "The resolved endpoint config must be passed.")
    _require(kwargs.get("identity_context") == {"user_id": "user-1"}, "The identity context must be passed through.")
    _require(key_vault_lookups == [{"scope_value": "global-endpoint", "scope": "global", "return_type": documents.SecretReturnType.VALUE}],
             f"Key Vault secrets must be resolved exactly once for the endpoint: {key_vault_lookups}.")

    disabled_endpoint = build_model_endpoints()
    disabled_endpoint[1]["enabled"] = False
    disabled_model = build_model_endpoints()
    disabled_model[1]["models"][0]["enabled"] = False
    unsupported = build_model_endpoints()
    unsupported[1]["provider"] = "Bogus"
    incomplete = build_model_endpoints()
    incomplete[1]["connection"]["endpoint"] = ""
    no_api_version = build_model_endpoints()
    no_api_version[1]["connection"].pop("openai_api_version")

    # React V2 looks the model up and re-checks its chat capability before resolving any Key
    # Vault secret, so a missing or disabled model is refused without a secret lookup, and a
    # disabled model is refused by the shared capability check.
    from functions_ai_connections import AIConnectionError  # noqa: PLC0415 - offline bootstrap

    for label, settings, expected_type, expected_message, expects_key_vault in (
        ("missing endpoint", settings_with({"endpoint_id": "missing", "model_id": "luna-model"}),
         LookupError, "Selected metadata extraction endpoint could not be found.", False),
        ("disabled endpoint", settings_with(endpoints=disabled_endpoint),
         ValueError, "Selected metadata extraction endpoint is disabled.", False),
        ("missing model", settings_with({"endpoint_id": "global-endpoint", "model_id": "missing"}),
         LookupError, "Selected metadata extraction model could not be found on the endpoint.", False),
        ("disabled model", settings_with(endpoints=disabled_model),
         AIConnectionError, "The selected model is not available for chat. Choose a compatible model.", False),
        ("unsupported provider", settings_with(endpoints=unsupported),
         ValueError, "Selected metadata extraction provider 'bogus' is not supported.", True),
        ("incomplete endpoint", settings_with(endpoints=incomplete),
         ValueError, "Selected metadata extraction endpoint is incomplete.", True),
        ("missing API version", settings_with(endpoints=no_api_version),
         ValueError, "Selected metadata extraction endpoint is incomplete.", True),
    ):
        result, error, builds, _, key_vault_lookups, _ = _resolve_metadata_client(documents, settings)
        _require(type(error) is expected_type and str(error) == expected_message,
                 f"{label}: expected {expected_type.__name__}({expected_message!r}), got {error!r}.")
        _require(not builds, f"{label}: no client may be built.")
        _require(bool(key_vault_lookups) == expects_key_vault, f"{label}: Key Vault lookup order changed.")

    result, error, builds, legacy_clients, _, _ = _resolve_metadata_client(
        documents, settings_with(enable_multi_model_endpoints=False)
    )
    _require(error is None and not builds and len(legacy_clients) == 1 and result == (legacy_clients[0], "gpt-4o"),
             "Without multi-endpoint models the legacy metadata extraction client must be used.")
    _require(legacy_clients[0].init_kwargs.get("azure_endpoint") == "https://simplechat-openai.invalid"
             and legacy_clients[0].init_kwargs.get("api_key") == "legacy-gpt-key",
             "The legacy metadata extraction client must be built from the GPT settings.")

    result, error, _, _, _, _ = _resolve_metadata_client(
        documents, settings_with(enable_multi_model_endpoints=False, metadata_extraction_model="")
    )
    _require(type(error) is ValueError and str(error) == "No metadata extraction model is selected.",
             "A missing legacy metadata model must keep its error.")


def check_vision_test_uses_the_ingestion_connection(route_settings, keyvault):
    print("Checking the admin vision test uses the same connection as ingestion...")
    from flask import Flask  # noqa: PLC0415 - imported inside the offline bootstrap

    web = Flask("image-description-vision-test")

    def run(saved_settings, payload):
        client_builds = []
        legacy_clients = []
        with ExitStack() as stack:
            stack.enter_context(patch.object(route_settings, "get_settings", lambda *a, **k: copy.deepcopy(saved_settings)))
            stack.enter_context(patch.object(route_settings, "get_current_user_id", lambda: "admin-user"))
            stack.enter_context(patch.object(route_settings, "build_model_endpoint_sync_chat_client",
                                             make_recording_client_builder(client_builds)))
            stack.enter_context(patch.object(route_settings, "AzureOpenAI", make_recording_azure_openai(legacy_clients)))
            stack.enter_context(patch.object(keyvault, "keyvault_model_endpoint_get_helper",
                                             lambda endpoint_cfg, *a, **k: endpoint_cfg))
            with web.app_context():
                response, status_code = route_settings._test_multimodal_vision_connection(copy.deepcopy(payload))
        return response.get_json(), status_code, client_builds, legacy_clients

    apim_payload = {
        "test_type": "multimodal_vision",
        "enable_apim": True,
        "vision_model": "gpt-5.6-luna",
        "apim": {
            "endpoint": "https://apim.invalid",
            "subscription_key": "apim-subscription-key",
            "api_version": "2024-10-21",
            "deployment": "gpt-5.6-luna",
        },
    }
    saved_settings = _vision_settings(enable_gpt_apim=True)

    body, status_code, builds, legacy_clients = run(saved_settings, apim_payload)
    _require(status_code == 200, f"The vision test must succeed, got {status_code}: {body}.")
    _require(len(builds) == 1 and not legacy_clients,
             "With the model hosted on an AI connection, the test must not use APIM, matching ingestion.")
    _require(builds[0]["args"][2] == "https://aoai-global-team.invalid" and builds[0]["kwargs"].get("deployment_name") == "luna-prod",
             "The test must call the same connection and deployment that ingestion uses.")

    direct_payload = {
        "test_type": "multimodal_vision",
        "enable_apim": False,
        "vision_model": "gpt-5.6-luna",
        "multi_endpoint": {
            "endpoint_id": "global-endpoint",
            "model_id": "luna-model",
            "provider": "aoai",
            "model_name": "gpt-5.6-luna",
            "deployment_name": "gpt-5.6-luna",
        },
        "direct": {"endpoint": "https://simplechat-openai.invalid", "auth_type": "key", "key": "legacy-gpt-key",
                   "api_version": "2024-12-01-preview", "deployment": "gpt-5.6-luna"},
    }
    body, status_code, builds, legacy_clients = run(_vision_settings(), direct_payload)
    _require(status_code == 200 and len(builds) == 1 and not legacy_clients
             and builds[0]["args"][2] == "https://aoai-global-team.invalid",
             "The classic multi-endpoint payload must keep resolving the Global connection.")

    body, status_code, builds, legacy_clients = run(_vision_settings(enable_multi_model_endpoints=False, enable_gpt_apim=True), apim_payload)
    _require(status_code == 200 and not builds and len(legacy_clients) == 1
             and legacy_clients[0].init_kwargs.get("azure_endpoint") == "https://apim.invalid",
             "Without multi-endpoint models the APIM test path must be unchanged.")


def _run_offline_probe():
    # Real application imports must occur inside the external-I/O bootstrap seam.
    from test_support.offline_bootstrap import offline_app_imports  # noqa: PLC0415

    with offline_app_imports() as offline, tempfile.TemporaryDirectory() as work_dir:
        import functions_content as content  # noqa: PLC0415
        import functions_content_understanding as content_understanding  # noqa: PLC0415
        import functions_documents as documents  # noqa: PLC0415
        import functions_keyvault as keyvault  # noqa: PLC0415
        import route_backend_settings as route_settings  # noqa: PLC0415
        _require(not offline.network_attempts, "Application imports attempted network access.")

        check_vision_block_formatting(documents)
        check_comment_only_ocr_is_not_text(documents)
        check_save_chunks_embeds_the_stored_text(documents)
        check_save_chunks_batch_matches_save_chunks(documents, content)
        check_text_free_images_are_indexed_from_vision(documents, work_dir)
        check_content_understanding_image_analyzer(content_understanding, work_dir)
        check_extraction_engine_image_fallback(content, content_understanding, work_dir)
        check_vision_model_routes_through_its_connection(documents, work_dir)
        check_metadata_extraction_client_is_unchanged(documents)
        check_vision_test_uses_the_ingestion_connection(route_settings, keyvault)
        _require(not offline.network_attempts, "The checks attempted network access.")

    print("All offline image description indexing checks passed.")


@pytest.mark.parametrize("optimized", (False, True))
def test_image_description_indexing_real_modules(optimized):
    """Run the real-module checks in a fresh process with external I/O blocked."""
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join((str(ROOT), str(APP_ROOT), str(TEST_ROOT)))
    env["PYTHONIOENCODING"] = "utf-8"
    command = [sys.executable]
    if optimized:
        command.append("-O")
    command.extend((str(Path(__file__).resolve()), "--offline-probe"))
    result = subprocess.run(
        command, cwd=ROOT, env=env, capture_output=True,
        text=True, encoding="utf-8", errors="replace", timeout=300,
    )
    assert result.returncode == 0, result.stdout + result.stderr


if __name__ == "__main__":
    if "--offline-probe" in sys.argv:
        _run_offline_probe()
    else:
        raise SystemExit(pytest.main([__file__, "-q"]))

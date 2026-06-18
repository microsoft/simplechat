# test_upload_dlp_ingestion_integration.py
#!/usr/bin/env python3
"""
Functional test for upload DLP ingestion integration.
Version: 0.242.070
Implemented in: 0.242.070

This test ensures upload DLP blocks stop before embeddings/search indexing and
redacted text is the only text passed into embedding/index payload construction.
"""

import ast
import os
import sys
import types
from datetime import datetime, timezone
from pathlib import Path
from typing import List


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_DIR = os.path.join(ROOT_DIR, "application", "single_app")
FUNCTIONS_DOCUMENTS_FILE = os.path.join(APP_DIR, "functions_documents.py")
FUNCTIONS_AUTHENTICATION_FILE = os.path.join(APP_DIR, "functions_authentication.py")
FUNCTIONS_DOCUMENTS = Path(FUNCTIONS_DOCUMENTS_FILE)
FUNCTIONS_AUTHENTICATION = Path(FUNCTIONS_AUTHENTICATION_FILE)
sys.path.insert(0, APP_DIR)


RAW_VALUE = "123-45-6789"


def read_file_text(path):
    with open(path, "r", encoding="utf-8") as file_handle:
        return file_handle.read()


def extract_function_source(source_text, function_name):
    parsed = ast.parse(source_text, filename=FUNCTIONS_DOCUMENTS_FILE)
    for node in ast.walk(parsed):
        if isinstance(node, ast.FunctionDef) and node.name == function_name:
            return ast.get_source_segment(source_text, node)
    raise AssertionError(f"Function {function_name} not found")


def import_functions_documents_for_helper_tests():
    """Import functions_documents with lightweight stubs for optional app dependencies."""
    stub_modules = {
        "config": types.ModuleType("config"),
        "functions_content": types.ModuleType("functions_content"),
        "functions_settings": types.ModuleType("functions_settings"),
        "functions_search": types.ModuleType("functions_search"),
        "functions_logging": types.ModuleType("functions_logging"),
        "functions_authentication": types.ModuleType("functions_authentication"),
        "functions_debug": types.ModuleType("functions_debug"),
        "functions_keyvault": types.ModuleType("functions_keyvault"),
        "azure": types.ModuleType("azure"),
        "azure.cognitiveservices": types.ModuleType("azure.cognitiveservices"),
        "azure.cognitiveservices.speech": types.ModuleType("azure.cognitiveservices.speech"),
    }
    stub_modules["config"].List = List
    stub_modules["config"].datetime = datetime
    stub_modules["config"].timezone = timezone
    stub_modules["functions_settings"].get_settings = lambda: {}
    stub_modules["functions_logging"].add_file_task_to_file_processing_log = lambda **kwargs: None
    stub_modules["functions_logging"].log_event = lambda *args, **kwargs: None
    stub_modules["functions_keyvault"].SecretReturnType = types.SimpleNamespace(VALUE="value")
    stub_modules["functions_keyvault"].keyvault_model_endpoint_get_helper = lambda endpoint, return_type=None: endpoint

    original_modules = {module_name: sys.modules.get(module_name) for module_name in stub_modules}
    try:
        sys.modules.pop("functions_documents", None)
        for module_name, module_stub in stub_modules.items():
            sys.modules[module_name] = module_stub
        import functions_documents
    finally:
        for module_name, original_module in original_modules.items():
            if original_module is None:
                sys.modules.pop(module_name, None)
            else:
                sys.modules[module_name] = original_module

    return functions_documents


def import_functions_authentication_for_helper_tests():
    """Import functions_authentication with lightweight stubs for optional app dependencies."""
    config_stub = types.ModuleType("config")
    config_stub.AZURE_ENVIRONMENT = "public"
    config_stub.CUSTOM_RESOURCE_MANAGER_URL_VALUE = ""
    config_stub.DEFAULT_VIDEO_INDEXER_ARM_API_VERSION = "2024-01-01"
    config_stub.OIDC_METADATA_URL = "https://login.example/.well-known/openid-configuration"
    config_stub.AUDIENCE = "audience"
    config_stub.ISSUER = "issuer"
    config_stub.requests = types.SimpleNamespace()
    config_stub.requests.exceptions = types.SimpleNamespace(RequestException=Exception)
    config_stub.jwt = types.SimpleNamespace()
    config_stub.DefaultAzureCredential = lambda: None

    stub_modules = {
        "config": config_stub,
        "functions_settings": types.ModuleType("functions_settings"),
        "functions_debug": types.ModuleType("functions_debug"),
    }
    stub_modules["functions_debug"].debug_print = lambda *args, **kwargs: None

    original_modules = {module_name: sys.modules.get(module_name) for module_name in stub_modules}
    try:
        sys.modules.pop("functions_authentication", None)
        for module_name, module_stub in stub_modules.items():
            sys.modules[module_name] = module_stub
        import functions_authentication
    finally:
        for module_name, original_module in original_modules.items():
            if original_module is None:
                sys.modules.pop(module_name, None)
            else:
                sys.modules[module_name] = original_module

    return functions_authentication


def test_upload_helper_blocks_before_returning_to_ingestion_paths():
    """The shared upload DLP evaluator should raise before callers can embed blocked text."""
    print("Testing upload DLP block gate...")
    source = read_file_text(FUNCTIONS_DOCUMENTS_FILE)
    helper_source = extract_function_source(source, "_evaluate_upload_dlp_text")

    record_index = helper_source.find("_record_upload_dlp_result(")
    block_index = helper_source.find('if not result.get("upload_allowed", True):')
    raise_index = helper_source.find('raise ValueError("Upload content blocked by DLP policy.")')
    return_index = helper_source.find("return result")

    assert record_index != -1, "DLP result should be recorded before block handling"
    assert block_index > record_index, "Block gate should run after safe metadata is recorded"
    assert raise_index > block_index, "Blocked upload should raise a policy error"
    assert return_index > raise_index, "Allowed result should return only after the block gate"


def test_single_chunk_uses_sanitized_text_for_embedding_and_indexing():
    """save_chunks should generate embeddings and search documents from sanitized text."""
    print("Testing single chunk sanitized text flow...")
    source = read_file_text(FUNCTIONS_DOCUMENTS_FILE)
    save_chunks_source = extract_function_source(source, "save_chunks")

    dlp_index = save_chunks_source.find("_evaluate_upload_dlp_text(")
    sanitized_index = save_chunks_source.find('sanitized_chunk_text = upload_dlp_result.get("sanitized_text", enhanced_chunk_text)')
    embedding_index = save_chunks_source.find("generate_embedding(sanitized_chunk_text)")
    index_payload_index = save_chunks_source.find('"chunk_text": sanitized_chunk_text')

    assert dlp_index != -1
    assert sanitized_index > dlp_index
    assert embedding_index > sanitized_index
    assert index_payload_index > embedding_index
    assert "generate_embedding(page_text_content)" not in save_chunks_source
    assert RAW_VALUE not in save_chunks_source


def test_batch_chunks_use_sanitized_text_for_batch_embeddings_and_indexing():
    """save_chunks_batch should batch only sanitized chunk text."""
    print("Testing batch chunk sanitized text flow...")
    source = read_file_text(FUNCTIONS_DOCUMENTS_FILE)
    batch_source = extract_function_source(source, "save_chunks_batch")

    dlp_index = batch_source.find("_evaluate_upload_dlp_text(")
    metadata_sanitize_index = batch_source.find("metadata, _metadata_dlp_summary = _sanitize_upload_metadata_for_dlp(")
    author_index = batch_source.find("author = ensure_list(metadata.get('authors'))")
    title_index = batch_source.find("title = metadata.get('title', '')")
    sanitized_index = batch_source.find("sanitized_chunk_info['page_text_content']")
    texts_index = batch_source.find("texts = [c['page_text_content'] for c in sanitized_chunks_data]")
    embedding_index = batch_source.find("generate_embeddings_batch(texts)")
    payload_index = batch_source.find('"chunk_text": enhanced_chunk_text')

    assert dlp_index != -1
    assert metadata_sanitize_index != -1
    assert author_index > metadata_sanitize_index
    assert title_index > metadata_sanitize_index
    assert sanitized_index > dlp_index
    assert texts_index > sanitized_index
    assert embedding_index > texts_index
    assert payload_index > embedding_index
    assert '"author": author' in batch_source
    assert '"title": title' in batch_source
    assert "texts = [c['page_text_content'] for c in chunks_data]" not in batch_source
    assert "dlp_metadata" in batch_source


def test_batch_chunk_vision_text_is_not_reappended_after_dlp_redaction():
    """save_chunks_batch should index sanitized chunk text without raw vision text."""
    print("Testing batch chunk vision text DLP redaction before indexing...")
    functions_documents = import_functions_documents_for_helper_tests()

    uploaded_batches = []
    embedded_texts = []

    class FakeSearchClient:
        def upload_documents(self, documents):
            uploaded_batches.append(documents)

    original_get_settings = functions_documents.get_settings
    original_get_document_metadata = functions_documents.get_document_metadata
    original_update_document = getattr(functions_documents, "update_document", None)
    original_clients = getattr(functions_documents, "CLIENTS", None)
    original_functions_content = sys.modules.get("functions_content")

    functions_documents.get_settings = lambda: {
        "enable_dlp_control_plane": True,
        "enable_upload_dlp": True,
        "upload_dlp_mode": "redact",
        "dlp_default_engine": "regex",
        "dlp_max_scan_chars": 200000,
    }
    functions_documents.get_document_metadata = lambda **kwargs: {
        "version": 1,
        "authors": ["Author"],
        "title": "Document",
        "document_classification": "None",
        "tags": [],
        "shared_user_ids": [],
        "vision_analysis": {
            "model": "vision-model",
            "text": f"badge SSN {RAW_VALUE}",
        },
    }
    functions_documents.update_document = lambda **kwargs: None
    functions_documents.CLIENTS = {"search_client_user": FakeSearchClient()}

    def fake_generate_embeddings_batch(texts):
        embedded_texts.extend(texts)
        return [([0.1, 0.2, 0.3], {"total_tokens": 1, "prompt_tokens": 1}) for _ in texts]

    functions_content_stub = types.ModuleType("functions_content")
    functions_content_stub.generate_embeddings_batch = fake_generate_embeddings_batch
    sys.modules["functions_content"] = functions_content_stub

    try:
        functions_documents.save_chunks_batch(
            [
                {
                    "page_text_content": "Safe page content.",
                    "page_number": 1,
                    "file_name": "vision.pdf",
                }
            ],
            user_id="user-1",
            document_id="doc-vision",
        )
    finally:
        functions_documents.get_settings = original_get_settings
        functions_documents.get_document_metadata = original_get_document_metadata
        if original_functions_content is None:
            sys.modules.pop("functions_content", None)
        else:
            sys.modules["functions_content"] = original_functions_content
        if original_update_document is None:
            delattr(functions_documents, "update_document")
        else:
            functions_documents.update_document = original_update_document
        if original_clients is None:
            delattr(functions_documents, "CLIENTS")
        else:
            functions_documents.CLIENTS = original_clients

    assert uploaded_batches
    indexed_chunk_text = uploaded_batches[0][0]["chunk_text"]
    assert RAW_VALUE not in indexed_chunk_text
    assert RAW_VALUE not in repr(embedded_texts)
    assert indexed_chunk_text == embedded_texts[0]
    assert "badge SSN [REDACTED_US_SSN]" in indexed_chunk_text


def test_video_chunks_use_sanitized_transcript_and_ocr_text():
    """save_video_chunk should sanitize transcript and OCR text before embedding/search."""
    print("Testing video chunk sanitized text flow...")
    source = read_file_text(FUNCTIONS_DOCUMENTS_FILE)
    video_source = extract_function_source(source, "save_video_chunk")

    transcript_dlp_index = video_source.find("transcript_dlp_result = _evaluate_upload_dlp_text(")
    transcript_sanitized_index = video_source.find(
        'sanitized_transcript_text = transcript_dlp_result.get("sanitized_text", page_text_content)'
    )
    ocr_dlp_index = video_source.find("ocr_dlp_result = _evaluate_upload_dlp_text(")
    ocr_sanitized_index = video_source.find(
        'sanitized_ocr_text = ocr_dlp_result.get("sanitized_text", ocr_chunk_text)'
    )
    embedding_index = video_source.find("generate_embedding(sanitized_transcript_text)")
    transcript_payload_index = video_source.find('"chunk_text":           sanitized_transcript_text')
    ocr_payload_index = video_source.find('"video_ocr_chunk_text": sanitized_ocr_text')

    assert transcript_dlp_index != -1
    assert transcript_sanitized_index > transcript_dlp_index
    assert ocr_dlp_index > transcript_sanitized_index
    assert ocr_sanitized_index > ocr_dlp_index
    assert embedding_index > ocr_sanitized_index
    assert transcript_payload_index > embedding_index
    assert ocr_payload_index > embedding_index


def test_video_chunks_preserve_public_workspace_scope():
    """Video chunks should use the public workspace metadata/search path when supplied."""
    print("Testing video chunk public workspace scope...")
    source = read_file_text(FUNCTIONS_DOCUMENTS_FILE)
    video_source = extract_function_source(source, "save_video_chunk")
    process_video_source = extract_function_source(source, "process_video_document")

    assert "public_workspace_id=None" in video_source
    assert "is_public_workspace = public_workspace_id is not None" in video_source
    assert "public_workspace_id=public_workspace_id" in video_source
    assert 'chunk["public_workspace_id"] = public_workspace_id' in video_source
    assert 'CLIENTS["search_client_public"]' in video_source
    assert "save_video_chunk(" in process_video_source
    assert "public_workspace_id=public_workspace_id" in process_video_source


def test_video_dlp_block_errors_abort_processing():
    """Video processing should not swallow upload DLP block decisions."""
    print("Testing video DLP block propagation...")
    source = read_file_text(FUNCTIONS_DOCUMENTS_FILE)
    video_source = extract_function_source(source, "save_video_chunk")
    process_video_source = extract_function_source(source, "process_video_document")

    save_chunk_call_index = process_video_source.find("save_video_chunk(")
    catch_index = process_video_source.find("except Exception as e:", save_chunk_call_index)
    dlp_guard_index = process_video_source.find('if str(e) == "Upload content blocked by DLP policy.":', catch_index)
    raise_index = process_video_source.find("raise", dlp_guard_index)
    log_index = process_video_source.find("Failed to save chunk", catch_index)

    assert 'if str(e) == "Upload content blocked by DLP policy.":' in video_source
    assert save_chunk_call_index != -1
    assert catch_index > save_chunk_call_index
    assert dlp_guard_index > catch_index
    assert raise_index > dlp_guard_index
    assert log_index > raise_index


def test_audio_chunks_preserve_public_workspace_scope():
    """Audio transcript chunks should pass public workspace scope through save_chunks."""
    print("Testing audio chunk public workspace scope...")
    source = read_file_text(FUNCTIONS_DOCUMENTS_FILE)
    audio_source = extract_function_source(source, "process_audio_document")

    save_chunks_index = audio_source.find("save_chunks(")
    public_scope_index = audio_source.find("public_workspace_id=public_workspace_id", save_chunks_index)

    assert save_chunks_index != -1
    assert public_scope_index > save_chunks_index


def test_media_processing_logs_do_not_emit_raw_detector_text():
    """Media processors should log counts and lengths, not raw transcript/insight bodies."""
    print("Testing media processing log safety...")
    source = read_file_text(FUNCTIONS_DOCUMENTS_FILE)
    video_source = extract_function_source(source, "process_video_document")
    audio_source = extract_function_source(source, "process_audio_document")

    forbidden_video = [
        "RAW INSIGHTS",
        "insights_json",
        "json.dumps(insights",
        "TRANSCRIPT sample",
        "OCR sample",
        "KEYWORDS sample",
        "sample:",
        "First speech item: {speech_context[0]}",
        "using insights as text: {chunk_text[:100]}",
        "chunk_text[:100]",
    ]
    forbidden_audio = [
        "Recognized: {evt.result.text}",
        "Recognized: {result.text}",
    ]

    for snippet in forbidden_video:
        assert snippet not in video_source, f"Unsafe video log remains: {snippet}"
    for snippet in forbidden_audio:
        assert snippet not in audio_source, f"Unsafe audio log remains: {snippet}"


def test_upload_dlp_metadata_is_counts_only():
    """Upload DLP metadata should store summaries, not raw detector matches."""
    print("Testing upload DLP metadata safety...")
    from functions_dlp import evaluate_upload_content

    result = evaluate_upload_content(
        f"employee ssn {RAW_VALUE}",
        settings={
            "enable_dlp_control_plane": True,
            "enable_upload_dlp": True,
            "upload_dlp_mode": "redact",
        },
        context={"document_id": "doc-1", "workspace_scope": "personal"},
    )

    metadata = result["dlp_metadata"]
    assert metadata["entity_counts"] == {"US_SSN": 1}
    assert metadata["total_replacements"] == 1
    assert RAW_VALUE not in repr(metadata)
    assert "matches" not in metadata
    assert "raw_matches" not in metadata


def test_upload_dlp_enforcement_disables_enhanced_citation_blob_upload():
    """Enforced upload DLP should disable raw enhanced-citation blob upload."""
    print("Testing upload DLP enhanced-citation enforcement...")
    source = FUNCTIONS_DOCUMENTS.read_text(encoding="utf-8")
    assert "_should_disable_enhanced_citations_for_upload_dlp" in source
    assert "enable_enhanced_citations = False" in source
    assert "upload_dlp_mode" in source
    assert 'settings.get("upload_dlp_fail_upload_on_match", False)' in source
    assert 'settings.get("dlp_fail_closed_on_scanner_error", True)' in source

    upload_source = extract_function_source(source, "process_document_upload_background")
    helper_source = extract_function_source(source, "_should_disable_enhanced_citations_for_upload_dlp")
    conditional = "disabled_enhanced_citations_for_upload_dlp = ("
    conditional_index = upload_source.find(conditional)
    disable_index = upload_source.find("enable_enhanced_citations = False", conditional_index)
    status_index = upload_source.find("Enhanced citations disabled because upload DLP enforcement is active")
    dispatch_args_index = upload_source.find("args = {")
    process_handler_indices = [
        index
        for index in (
            upload_source.find("process_txt("),
            upload_source.find("process_xml("),
            upload_source.find("process_yaml("),
            upload_source.find("process_log("),
            upload_source.find("process_doc("),
            upload_source.find("process_html("),
            upload_source.find("process_md("),
            upload_source.find("process_json("),
            upload_source.find("process_tabular("),
            upload_source.find("process_video_document("),
            upload_source.find("process_audio_document("),
            upload_source.find("process_di_document("),
        )
        if index != -1
    ]

    assert conditional_index != -1
    assert 'settings.get("dlp_fail_closed_on_scanner_error", True)' in helper_source
    assert 'settings.get("upload_dlp_fail_upload_on_match", False)' in helper_source
    assert "return True" in helper_source
    assert disable_index > conditional_index
    assert status_index > disable_index
    assert dispatch_args_index > disable_index
    assert '"enable_enhanced_citations": enable_enhanced_citations' in upload_source
    assert process_handler_indices
    assert disable_index < min(process_handler_indices)
    assert "enable_enhanced_citations=enable_enhanced_citations" in upload_source

    video_source = extract_function_source(source, "process_video_document")
    audio_source = extract_function_source(source, "process_audio_document")
    assert "enable_enhanced_citations=False" in video_source
    assert "enable_enhanced_citations=False" in audio_source
    assert 'if enable_enhanced_citations:' in video_source
    assert 'if enable_enhanced_citations:' in audio_source
    assert 'settings.get("enable_enhanced_citations", False)' not in video_source
    assert 'settings.get("enable_enhanced_citations", False)' not in audio_source


def test_upload_metadata_sanitizer_redacts_counts_only_metadata():
    """Upload metadata sanitizer should redact raw values and return counts only."""
    print("Testing upload metadata DLP sanitizer...")
    functions_documents = import_functions_documents_for_helper_tests()

    original_get_settings = functions_documents.get_settings
    functions_documents.get_settings = lambda: {
        "enable_dlp_control_plane": True,
        "enable_upload_dlp": True,
        "upload_dlp_mode": "redact",
        "dlp_default_engine": "regex",
        "dlp_max_scan_chars": 200000,
    }

    try:
        metadata = {
            "title": "Roadmap 123-45-6789",
            "authors": ["Alice 123-45-6789"],
            "organization": "Org",
            "publication_date": "06/2026",
            "keywords": ["SSN 123-45-6789"],
            "abstract": "Contains 123-45-6789",
        }

        sanitized, summary = functions_documents._sanitize_upload_metadata_for_dlp(
            metadata,
            user_id="user-1",
            document_id="doc-1",
        )
    finally:
        functions_documents.get_settings = original_get_settings

    assert "123-45-6789" not in repr(sanitized)
    assert summary["entity_counts"]["US_SSN"] >= 1
    assert "raw_matches" not in repr(summary)


def test_upload_metadata_logs_use_safe_counts_and_lengths():
    """Metadata retrieval and extraction logs should not write raw metadata bodies."""
    print("Testing upload metadata log safety...")
    source = FUNCTIONS_DOCUMENTS.read_text(encoding="utf-8")
    get_metadata_source = extract_function_source(source, "get_document_metadata")
    summary_source = extract_function_source(source, "_upload_metadata_log_summary")

    assert "Document metadata retrieved: {document_items}" not in get_metadata_source
    assert "item_count: {len(document_items)}" in get_metadata_source
    assert '"field_lengths"' in summary_source
    assert "Final metadata for document {document_id}: {meta_data}" not in source
    assert "Decoded JSON from GPT response for document {document_id}: {gpt_output}" not in source


def test_initial_di_metadata_is_sanitized_before_update_callback():
    """DI file properties should be sanitized before first metadata persistence."""
    print("Testing initial DI metadata sanitization...")
    source = FUNCTIONS_DOCUMENTS.read_text(encoding="utf-8")
    di_source = extract_function_source(source, "process_di_document")

    metadata_fields_index = di_source.find("metadata_update_fields = {")
    sanitize_index = di_source.find("_sanitize_upload_metadata_for_dlp(")
    update_index = di_source.find("update_callback(**update_fields)")
    dlp_reraise_index = di_source.find('if str(e) == "Upload content blocked by DLP policy.":')
    warning_index = di_source.find("Warning: Failed to extract initial metadata")

    assert metadata_fields_index != -1
    assert sanitize_index > metadata_fields_index
    assert update_index > sanitize_index
    assert dlp_reraise_index > update_index
    assert warning_index > dlp_reraise_index


def test_video_indexer_upload_params_do_not_log_access_token():
    """Video Indexer upload logging should not include raw account tokens."""
    print("Testing Video Indexer upload parameter log safety...")
    source = FUNCTIONS_DOCUMENTS.read_text(encoding="utf-8")
    video_source = extract_function_source(source, "process_video_document")

    assert '"accessToken": token' in video_source
    assert 'debug_print(f"[VIDEO INDEXER] Upload params: {params}")' not in video_source
    assert 'debug_print(f"[VIDEO INDEXER] Index polling URL: {index_url}")' not in video_source
    assert "accessToken_present={bool(token)}" in video_source
    assert "name_length={len(original_filename or '')}" in video_source
    assert "Upload params keys" in video_source
    assert "Index polling request prepared" in video_source
    assert "video_id_length={len(str(vid or ''))}" in video_source


def test_video_indexer_request_errors_redact_access_token():
    """Video Indexer request exceptions should redact token-bearing URLs before logging."""
    print("Testing Video Indexer request error redaction...")
    functions_documents = import_functions_documents_for_helper_tests()
    source = FUNCTIONS_DOCUMENTS.read_text(encoding="utf-8")
    video_source = extract_function_source(source, "process_video_document")

    query_error = (
        "403 Client Error: Forbidden for url: "
        "https://video.example/Index?accessToken=opaque-token&other=value"
    )
    dict_error = "{'accessToken': 'opaque-token', 'name': 'example.mp4'}"

    redacted_query = functions_documents._sanitize_video_indexer_log_value(query_error)
    redacted_dict = functions_documents._sanitize_video_indexer_log_value(dict_error)

    assert "opaque-token" not in redacted_query
    assert "accessToken=[REDACTED]" in redacted_query
    assert "other=value" in redacted_query
    assert "opaque-token" not in redacted_dict
    assert "[REDACTED]" in redacted_dict
    assert "Authentication failed: {str(e)}" not in video_source
    assert "AUTH ERROR: {e}" not in video_source
    assert "auth failed → {e}" not in video_source
    assert "Upload request failed: {str(e)}" not in video_source
    assert "Poll request failed: {str(e)}" not in video_source
    assert "Upload response text: {resp.text}" not in video_source
    assert "No video ID in response: {response_data}" not in video_source
    assert "_sanitize_video_indexer_log_value(e)" in video_source
    assert "_sanitize_video_indexer_log_value(resp.text)" in video_source
    assert "_sanitize_video_indexer_log_value(e.response.text)" in video_source


def test_video_indexer_auth_errors_redact_access_token():
    """Video Indexer auth response logging should redact token-bearing bodies."""
    print("Testing Video Indexer auth response redaction...")
    functions_authentication = import_functions_authentication_for_helper_tests()
    source = FUNCTIONS_AUTHENTICATION.read_text(encoding="utf-8")
    auth_source = extract_function_source(source, "get_video_indexer_managed_identity_token")

    response_body = '{"accessToken":"opaque-token","expiresIn":"3600"}'
    query_error = (
        "400 Client Error: Bad Request for url: "
        "https://management.example/generateAccessToken?accessToken=opaque-token"
    )

    redacted_body = functions_authentication._sanitize_video_indexer_auth_log_value(response_body)
    redacted_query = functions_authentication._sanitize_video_indexer_auth_log_value(query_error)

    assert "opaque-token" not in redacted_body
    assert "opaque-token" not in redacted_query
    assert "[REDACTED]" in redacted_body
    assert "accessToken=[REDACTED]" in redacted_query
    assert "ARM API response text: {resp.text}" not in auth_source
    assert "ERROR: No accessToken in response: {response_data}" not in auth_source
    assert "ERROR in ARM API request: {str(e)}" not in auth_source
    assert "Error response text: {e.response.text}" not in auth_source
    assert "_sanitize_video_indexer_auth_log_value(resp.text)" in auth_source
    assert "_sanitize_video_indexer_auth_log_value(e.response.text)" in auth_source


def test_upload_dlp_document_status_aggregates_worst_result():
    """Document DLP summary should preserve the worst observed status."""
    print("Testing upload DLP document status aggregation...")
    functions_documents = import_functions_documents_for_helper_tests()

    aggregate = functions_documents._merge_upload_dlp_document_summary(
        existing={
            "status": "accepted_with_redactions",
            "entity_counts": {"US_SSN": 1},
            "total_replacements": 1,
        },
        incoming={
            "status": "accepted",
            "entity_counts": {},
            "total_replacements": 0,
        },
    )

    assert aggregate["status"] == "accepted_with_redactions"
    assert aggregate["entity_counts"]["US_SSN"] == 1


def test_upload_dlp_record_merges_with_existing_document_status():
    """Recording a clean field should not downgrade an earlier redacted document status."""
    print("Testing upload DLP record persistence aggregation...")
    functions_documents = import_functions_documents_for_helper_tests()

    updates = []
    original_get_settings = functions_documents.get_settings
    original_get_document_metadata = functions_documents.get_document_metadata
    original_update_document = functions_documents.update_document
    functions_documents.get_settings = lambda: {
        "enable_dlp_control_plane": True,
        "enable_upload_dlp": True,
        "upload_dlp_mode": "redact",
    }
    functions_documents.get_document_metadata = lambda **kwargs: {
        "dlp_status": "accepted_with_redactions",
        "dlp_metadata": {
            "status": "accepted_with_redactions",
            "entity_counts": {"US_SSN": 1},
            "total_replacements": 1,
            "scanner_status": "ok",
        },
    }
    functions_documents.update_document = lambda **kwargs: updates.append(kwargs)

    try:
        functions_documents._record_upload_dlp_result(
            {
                "status": "accepted",
                "sanitized_text": "clean",
                "dlp_metadata": {
                    "status": "accepted",
                    "entity_counts": {},
                    "total_replacements": 0,
                    "scanner_status": "ok",
                },
            },
            user_id="user-1",
            document_id="doc-1",
        )
    finally:
        functions_documents.get_settings = original_get_settings
        functions_documents.get_document_metadata = original_get_document_metadata
        functions_documents.update_document = original_update_document

    assert updates
    assert updates[0]["dlp_status"] == "accepted_with_redactions"
    assert updates[0]["dlp_metadata"]["entity_counts"]["US_SSN"] == 1


if __name__ == "__main__":
    tests = [
        test_upload_helper_blocks_before_returning_to_ingestion_paths,
        test_single_chunk_uses_sanitized_text_for_embedding_and_indexing,
        test_batch_chunks_use_sanitized_text_for_batch_embeddings_and_indexing,
        test_batch_chunk_vision_text_is_not_reappended_after_dlp_redaction,
        test_video_chunks_use_sanitized_transcript_and_ocr_text,
        test_video_chunks_preserve_public_workspace_scope,
        test_video_dlp_block_errors_abort_processing,
        test_audio_chunks_preserve_public_workspace_scope,
        test_media_processing_logs_do_not_emit_raw_detector_text,
        test_upload_dlp_metadata_is_counts_only,
        test_upload_dlp_enforcement_disables_enhanced_citation_blob_upload,
        test_upload_metadata_sanitizer_redacts_counts_only_metadata,
        test_upload_metadata_logs_use_safe_counts_and_lengths,
        test_initial_di_metadata_is_sanitized_before_update_callback,
        test_video_indexer_upload_params_do_not_log_access_token,
        test_video_indexer_request_errors_redact_access_token,
        test_video_indexer_auth_errors_redact_access_token,
        test_upload_dlp_document_status_aggregates_worst_result,
        test_upload_dlp_record_merges_with_existing_document_status,
    ]

    failures = []
    for test in tests:
        try:
            test()
        except Exception as exc:
            failures.append((test.__name__, exc))
            print(f"Test failed: {test.__name__}: {exc}")
            import traceback

            traceback.print_exc()

    if failures:
        print(f"{len(failures)} of {len(tests)} upload DLP ingestion integration tests failed.")
        sys.exit(1)

    print(f"All {len(tests)} upload DLP ingestion integration tests passed.")
    sys.exit(0)

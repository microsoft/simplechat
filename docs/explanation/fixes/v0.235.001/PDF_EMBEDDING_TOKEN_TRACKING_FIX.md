# PDF Embedding Token Tracking Fix

## Issue
**Version:** 0.233.299  
**Date:** December 19, 2025  
**Related Feature:** Embedding Token Tracking (0.233.298)

## Problem Description
After implementing embedding token tracking in version 0.233.298, PDF document uploads were showing **0 embedding tokens** even though embeddings were being generated for all chunks.

### Error Observed
```
Document c3076b27-e867-4081-a092-8ca1b2b46a1b (test.pdf) processed successfully with 7 chunks saved and 0 embedding tokens used.
```

### Root Cause
The initial implementation only updated `process_txt()` to accumulate and return embedding token data. PDF files are processed through `process_di_document()` (Document Intelligence pathway), which was not updated to:
1. Capture token_usage from `save_chunks()` calls
2. Accumulate tokens across all chunks
3. Return token data as a tuple

## Solution

### Files Modified

#### `functions_documents.py`

**1. Added token tracking initialization in `process_di_document()`**
```python
def process_di_document(...):
    # --- Token tracking initialization ---
    total_embedding_tokens = 0
    embedding_model_name = None
```

**2. Updated `save_chunks()` call to capture token usage**
```python
# Before
save_chunks(**args)
total_final_chunks_processed += 1

# After
token_usage = save_chunks(**args)

# Accumulate embedding tokens
if token_usage:
    total_embedding_tokens += token_usage.get('total_tokens', 0)
    if not embedding_model_name:
        embedding_model_name = token_usage.get('model_deployment_name')

total_final_chunks_processed += 1
```

**3. Updated return statement to include token data**
```python
# Before
return total_final_chunks_processed

# After
return total_final_chunks_processed, total_embedding_tokens, embedding_model_name
```

**4. Updated `process_document_upload_background()` to handle tuple return**
```python
elif file_ext in di_supported_extensions:
    result = process_di_document(**args)
    # Handle tuple return (chunks, tokens, model_name)
    if isinstance(result, tuple) and len(result) == 3:
        total_chunks_saved, total_embedding_tokens, embedding_model_name = result
    else:
        total_chunks_saved = result
```

#### `config.py`
- Version incremented to `0.233.299`

#### `test_embedding_token_tracking.py`
- Updated version to `0.233.299`

## Impact

### Document Types Now Tracking Tokens
- ✅ **PDF** files (via Document Intelligence)
- ✅ **DOCX** files (via Document Intelligence)
- ✅ **PPTX** files (via Document Intelligence)
- ✅ **Images** (JPG, PNG, etc. via Document Intelligence)
- ✅ **TXT** files (direct processing)

### Expected Behavior
When a PDF or other Document Intelligence-processed file is uploaded:
```
Document abc123 (test.pdf) processed successfully with 7 chunks saved and 1847 embedding tokens used.
```

The document metadata in Cosmos DB will now contain:
```json
{
  "embedding_tokens": 1847,
  "embedding_model_deployment_name": "text-embedding-3-small"
}
```

## Testing

### Manual Testing
Upload a PDF file and verify:
1. Document processes successfully
2. Console shows non-zero embedding tokens
3. Cosmos DB document metadata contains `embedding_tokens` > 0
4. Cosmos DB document metadata contains `embedding_model_deployment_name`

### Automated Testing
Run existing functional test:
```bash
python functional_tests\test_embedding_token_tracking.py
```

## Related Issues

### VectorizedQuery Serialization Warning
During testing, this warning may appear:
```
Error processing Hybrid search for document xxx: Unable to serialize value: [<azure.search.documents._generated.models._models_py3.VectorizedQuery object at 0x...>] as type: '[VectorQuery]'.
```

**Status:** This is a non-blocking warning in the metadata extraction phase. The document processing continues successfully, and this error is caught and handled gracefully. This is a separate issue related to the hybrid search functionality used for metadata extraction, not related to embedding token tracking.

## Remaining Work

### Other File Types to Update
The following process functions still need to be updated to track embedding tokens:
- `process_xml()`
- `process_yaml()`
- `process_log()`
- `process_doc()` (legacy .doc files)
- `process_html()`
- `process_md()`
- `process_json()`
- `process_tabular()` (CSV, XLSX, etc.)
- `process_video_document()`
- `process_audio_document()`

### Group and Public Workspaces
Token tracking still needs to be implemented for:
- Group workspace documents
- Public workspace documents

## Verification

After this fix, PDF uploads in personal workspaces should correctly track embedding tokens:

**Before Fix:**
```
embedding_tokens: 0
embedding_model_deployment_name: None
```

**After Fix:**
```
embedding_tokens: 1847
embedding_model_deployment_name: "text-embedding-3-small"
```

## Related Documentation
- [Embedding Token Tracking Feature](../features/EMBEDDING_TOKEN_TRACKING.md)
- Main implementation: `application/single_app/functions_documents.py`
- Test: `functional_tests/test_embedding_token_tracking.py`

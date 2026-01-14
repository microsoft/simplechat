# All File Types Embedding Token Tracking Fix

**Version: 0.233.300**  
**Fixed in version: 0.233.300**  
**Date: December 19, 2024**

## Overview

Extended embedding token tracking to **all supported file types** in personal workspaces. Previously, only TXT files (v0.233.298) and Document Intelligence files like PDF, DOCX, PPTX, Images (v0.233.299) tracked embedding tokens. This update ensures comprehensive token tracking across the entire document upload system.

## Problem Statement

After implementing embedding token tracking for TXT and PDF files, the system needed to track tokens for all remaining supported file types to provide complete usage analytics:

- XML files (.xml)
- YAML files (.yaml, .yml)
- Log files (.log)
- Legacy Word files (.doc, .docm)
- HTML files (.html)
- Markdown files (.md)
- JSON files (.json)
- Tabular files (.csv, .xlsx, .xls, .xlsm)

Without this tracking, embedding token usage data would be incomplete and inconsistent across different document types.

## Files Modified

### 1. `functions_documents.py`

#### Updated Functions:
All document processor functions now implement the complete token tracking pattern:

1. **`process_xml()`** (Lines ~3385-3480)
   - Initialize token tracking variables
   - Capture token_usage from save_chunks() calls
   - Accumulate tokens across chunks
   - Return tuple: (chunks, tokens, model_name)

2. **`process_yaml()`** (Lines ~3482-3575)
   - Same pattern as process_xml
   - Handles both .yaml and .yml extensions

3. **`process_log()`** (Lines ~3575-3672)
   - Tracks tokens for log file chunks
   - Returns tuple with token data

4. **`process_doc()`** (Lines ~3672-3764)
   - Handles legacy .doc and .docm files
   - Uses docx2txt library for extraction
   - Tracks embedding tokens

5. **`process_html()`** (Lines ~3764-3894)
   - Processes HTML files
   - Includes metadata extraction if enabled
   - Tracks embedding tokens for all chunks

6. **`process_md()`** (Lines ~3894-4030)
   - Processes Markdown files
   - Metadata extraction support
   - Complete token tracking

7. **`process_json()`** (Lines ~4030-4168)
   - JSON file processing
   - Metadata extraction enabled
   - Token tracking implemented

8. **`process_tabular()`** (Lines ~4255-4395)
   - Handles CSV, XLSX, XLS, XLSM files
   - Processes multiple Excel sheets
   - Aggregates tokens across all sheets
   - Already had tuple handling from `process_single_tabular_sheet()`

9. **`process_document_upload_background()`** (Lines ~4855-5100)
   - **DISPATCHER UPDATE**: Modified to handle tuple returns from all processors
   - Added `isinstance(result, tuple)` checks for:
     - .xml files
     - .yaml/.yml files
     - .log files
     - .doc/.docm files
     - .html files
     - .md files
     - .json files
     - Tabular extensions (.csv, .xlsx, .xls, .xlsm)
   - Unpacks tuples into: `total_chunks_saved, total_embedding_tokens, embedding_model_name`
   - Includes token data in final update callback

### 2. `config.py`

```python
VERSION = "0.233.300"  # Incremented from 0.233.299
```

## Technical Implementation

### Token Tracking Pattern

Each processor follows this consistent pattern:

```python
def process_[file_type](...):
    # 1. Initialize tracking variables
    total_chunks_saved = 0
    total_embedding_tokens = 0
    embedding_model_name = None
    
    # 2. Process chunks and capture token usage
    for chunk in chunks:
        token_usage = save_chunks(
            page_text_content=chunk_content,
            page_number=total_chunks_saved + 1,
            file_name=original_filename,
            user_id=user_id,
            document_id=document_id
        )
        total_chunks_saved += 1
        
        # 3. Accumulate tokens
        if token_usage:
            total_embedding_tokens += token_usage.get('total_tokens', 0)
            if not embedding_model_name:
                embedding_model_name = token_usage.get('model_deployment_name')
    
    # 4. Return tuple
    return total_chunks_saved, total_embedding_tokens, embedding_model_name
```

### Dispatcher Pattern

The dispatcher handles both old (integer) and new (tuple) return formats:

```python
if file_ext == '.xml':
    result = process_xml(**args)
    if isinstance(result, tuple) and len(result) == 3:
        total_chunks_saved, total_embedding_tokens, embedding_model_name = result
    else:
        total_chunks_saved = result  # Backward compatibility
```

### Final Update with Token Data

```python
final_update_args = {
    "number_of_pages": total_chunks_saved,
    "status": final_status,
    "percentage_complete": 100,
    "current_file_chunk": None
}

# Add embedding token data if available
if total_embedding_tokens > 0:
    final_update_args["embedding_tokens"] = total_embedding_tokens
if embedding_model_name:
    final_update_args["embedding_model_deployment_name"] = embedding_model_name
    
update_doc_callback(**final_update_args)
```

## Supported File Types

### Now Tracking Embedding Tokens (Complete List):

| File Type | Extensions | Processor Function | Status |
|-----------|-----------|-------------------|---------|
| Text | .txt | `process_txt()` | ✅ v0.233.298 |
| PDF | .pdf | `process_di_document()` | ✅ v0.233.299 |
| Word (Modern) | .docx | `process_di_document()` | ✅ v0.233.299 |
| PowerPoint | .pptx, .ppt | `process_di_document()` | ✅ v0.233.299 |
| Images | .jpg, .jpeg, .png, .bmp, .tiff, .tif, .heif | `process_di_document()` | ✅ v0.233.299 |
| XML | .xml | `process_xml()` | ✅ v0.233.300 |
| YAML | .yaml, .yml | `process_yaml()` | ✅ v0.233.300 |
| Log | .log | `process_log()` | ✅ v0.233.300 |
| Word (Legacy) | .doc, .docm | `process_doc()` | ✅ v0.233.300 |
| HTML | .html | `process_html()` | ✅ v0.233.300 |
| Markdown | .md | `process_md()` | ✅ v0.233.300 |
| JSON | .json | `process_json()` | ✅ v0.233.300 |
| CSV | .csv | `process_tabular()` | ✅ v0.233.300 |
| Excel | .xlsx, .xls, .xlsm | `process_tabular()` | ✅ v0.233.300 |

### Not Yet Implemented:
- Video files (.mp4, .avi, .mov, .mkv, .webm) - `process_video_document()`
- Audio files (.mp3, .wav, .m4a, .flac, .ogg, .aac) - `process_audio_document()`

## Data Structure

### Token Usage Dictionary (from generate_embedding)

```python
{
    'prompt_tokens': 12,
    'total_tokens': 12,
    'model_deployment_name': 'text-embedding-3-small'
}
```

### Document Metadata (in Cosmos DB)

```python
{
    "id": "doc-xyz",
    "user_id": "user-123",
    "file_name": "document.xml",
    "number_of_pages": 5,  # chunks saved
    "embedding_tokens": 1250,  # NEW: total tokens used
    "embedding_model_deployment_name": "text-embedding-3-small",  # NEW: model name
    "status": "Processing complete",
    # ... other fields
}
```

## Testing

All existing functional tests continue to pass:

```bash
python functional_tests/test_embedding_token_tracking.py
```

**Results: 6/6 tests passed**

Tests verify:
1. ✅ Config version updated (0.233.300)
2. ✅ `generate_embedding()` returns token usage
3. ✅ `save_chunks()` signature verified
4. ✅ `create_document()` initializes embedding fields
5. ✅ `process_txt()` returns tuple
6. ✅ `update_document()` accepts token fields

## Validation Steps

To validate the fix:

1. **Upload different file types** to a personal workspace:
   - XML file
   - YAML file
   - Log file
   - .doc file
   - HTML file
   - Markdown file
   - JSON file
   - CSV file
   - Excel file

2. **Check application logs** for token usage:
   ```
   Document doc-xyz (filename.xml) processed successfully with 5 chunks saved and 1250 embedding tokens used.
   ```

3. **Verify Cosmos DB document** contains:
   ```json
   {
     "embedding_tokens": 1250,
     "embedding_model_deployment_name": "text-embedding-3-small"
   }
   ```

4. **Confirm non-zero values** for each file type

## Impact

### Positive Changes
- ✅ **Complete token tracking** across all supported file types
- ✅ **Consistent implementation** using standard pattern
- ✅ **Backward compatible** with old integer returns
- ✅ **Accurate usage analytics** for Azure OpenAI embedding API
- ✅ **Foundation for cost analysis** across document types
- ✅ **Prepared for group/public workspace extension**

### No Breaking Changes
- Dispatcher handles both old and new return formats
- Existing functionality preserved
- All tests continue to pass

## Next Steps

1. **Video & Audio Processors**
   - Extend token tracking to `process_video_document()`
   - Extend token tracking to `process_audio_document()`

2. **Group Workspaces**
   - Extend embedding token tracking to group workspace document uploads
   - Update group container queries to include token fields

3. **Public Workspaces**
   - Extend embedding token tracking to public workspace document uploads
   - Update public container queries to include token fields

4. **UI Integration**
   - Display embedding token usage in document details
   - Show aggregated token usage per workspace
   - Create analytics dashboard for token consumption

5. **Cost Analysis**
   - Calculate embedding costs based on token usage
   - Provide per-user and per-workspace cost reports
   - Track trends over time

## Related Documentation

- [EMBEDDING_TOKEN_TRACKING.md](EMBEDDING_TOKEN_TRACKING.md) - Original feature documentation (v0.233.298)
- [PDF_EMBEDDING_TOKEN_TRACKING_FIX.md](PDF_EMBEDDING_TOKEN_TRACKING_FIX.md) - PDF fix documentation (v0.233.299)
- [Functional Test: test_embedding_token_tracking.py](../../functional_tests/test_embedding_token_tracking.py)

## Conclusion

Version 0.233.300 completes the comprehensive embedding token tracking implementation for personal workspace document uploads. All 14 supported file types now track and report embedding token usage, providing complete visibility into Azure OpenAI API consumption for document processing.

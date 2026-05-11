# Embedding Token Tracking for Document Uploads

## Overview
Implemented comprehensive token tracking for document embedding generation in personal workspaces. When documents are uploaded and processed, the system now captures and stores embedding token usage alongside the document metadata in Cosmos DB.

## Version
**Implemented in:** 0.233.298  
**Date:** December 19, 2025

## Feature Description
When users upload documents to their personal workspace, the system:
1. Generates embeddings for each document chunk using Azure OpenAI
2. Captures token usage from the embedding API for each chunk
3. Accumulates total tokens across all chunks
4. Stores the total embedding tokens and model deployment name in the document metadata

This enables tracking of embedding costs and usage patterns at the document level, similar to how we track tokens for chat messages.

## Technical Implementation

### Modified Files

#### 1. `functions_content.py`
**Function:** `generate_embedding()`
- **Change:** Modified to return both the embedding vector and token usage information
- **Return Value:** Tuple of `(embedding, token_usage)` where `token_usage` is a dict containing:
  - `prompt_tokens`: Number of tokens in the input text
  - `total_tokens`: Total tokens used (same as prompt_tokens for embeddings)
  - `model_deployment_name`: Name of the embedding model deployment

```python
# Before
return embedding

# After
return embedding, token_usage
```

#### 2. `functions_documents.py`

##### `save_chunks()`
- **Change:** Now captures token_usage from `generate_embedding()` and returns it to caller
- **Return Value:** Returns `token_usage` dict for accumulation by parent functions

```python
embedding, token_usage = generate_embedding(page_text_content)
# ... process chunk ...
return token_usage
```

##### `create_document()`
- **Change:** Added two new fields to document metadata initialization for personal workspaces:
  - `embedding_tokens`: 0 (initialized to 0)
  - `embedding_model_deployment_name`: None (initialized to null)

##### `process_txt()`
- **Change:** Accumulates embedding tokens across all chunks during processing
- **Return Value:** Returns tuple of `(total_chunks_saved, total_embedding_tokens, embedding_model_name)`

```python
total_embedding_tokens = 0
embedding_model_name = None

for chunk in chunks:
    token_usage = save_chunks(**args)
    total_chunks_saved += 1
    
    if token_usage:
        total_embedding_tokens += token_usage.get('total_tokens', 0)
        if not embedding_model_name:
            embedding_model_name = token_usage.get('model_deployment_name')

return total_chunks_saved, total_embedding_tokens, embedding_model_name
```

##### `process_document_upload_background()`
- **Change:** Captures embedding token data from process functions and updates document metadata
- **Implementation:** 
  - Extracts token data from tuple return values
  - Adds `embedding_tokens` and `embedding_model_deployment_name` to final document update
  - Enhanced logging to include token counts

```python
# Capture token data from processor
result = process_txt(**args)
if isinstance(result, tuple) and len(result) == 3:
    total_chunks_saved, total_embedding_tokens, embedding_model_name = result

# Update document with token data
if total_embedding_tokens > 0:
    final_update_args["embedding_tokens"] = total_embedding_tokens
if embedding_model_name:
    final_update_args["embedding_model_deployment_name"] = embedding_model_name
```

#### 3. `config.py`
- **Change:** Incremented version to `0.233.298`

### Cosmos DB Schema Updates

#### Personal Workspace Documents Container
New fields added to document metadata:

```json
{
  "id": "document-id",
  "file_name": "example.txt",
  "num_chunks": 15,
  "embedding_tokens": 1847,
  "embedding_model_deployment_name": "text-embedding-3-small",
  "status": "Processing complete",
  "percentage_complete": 100,
  ...
}
```

### Token Usage Tracking Pattern

This implementation follows the same pattern used for chat message token tracking:

**Chat Message Example:**
```json
{
  "metadata": {
    "token_usage": {
      "prompt_tokens": 5423,
      "completion_tokens": 1513,
      "total_tokens": 6936,
      "captured_at": "2025-12-19T04:24:15.122492"
    }
  }
}
```

**Document Embedding Example:**
```json
{
  "embedding_tokens": 1847,
  "embedding_model_deployment_name": "text-embedding-3-small"
}
```

## Current Implementation Status

### ✅ Completed (Personal Workspaces)
- ✅ Embedding token capture from Azure OpenAI API
- ✅ Token accumulation across document chunks
- ✅ Storage in personal workspace document metadata
- ✅ Model deployment name tracking
- ✅ Functional testing and validation

### 🔄 Future Work (Group & Public Workspaces)
The current implementation is scoped to **personal workspaces only**. The following remain to be implemented:

#### Group Workspaces
- Add `embedding_tokens` and `embedding_model_deployment_name` fields to group workspace document metadata
- Update all group workspace process_* functions to return token data
- Handle group-specific token accumulation

#### Public Workspaces  
- Add `embedding_tokens` and `embedding_model_deployment_name` fields to public workspace document metadata
- Update all public workspace process_* functions to return token data
- Handle public workspace token accumulation

## Testing

### Functional Test
**File:** `functional_tests/test_embedding_token_tracking.py`

**Test Coverage:**
1. ✅ `generate_embedding()` returns token usage tuple
2. ✅ `save_chunks()` returns token usage information
3. ✅ `create_document()` initializes embedding token fields
4. ✅ `process_txt()` returns token data alongside chunks
5. ✅ `update_document()` accepts embedding token fields
6. ✅ Config version incremented

**Test Results:** All 6 tests passed ✅

### Example Test Output
```
🔍 Testing generate_embedding token usage return...
✅ Embedding vector has 1536 dimensions
✅ Token usage structure correct:
   - Prompt tokens: 12
   - Total tokens: 12
   - Model: text-embedding-3-small

🔍 Testing create_document embedding fields...
✅ Document has embedding_tokens: 0
✅ Document has embedding_model_deployment_name: None
```

## Usage and Benefits

### Cost Tracking
- Track embedding costs at the document level
- Understand which documents consume the most embedding tokens
- Optimize chunking strategies based on token usage

### Usage Analytics
- Monitor embedding token consumption trends
- Compare token usage across different document types
- Identify opportunities for cost optimization

### Model Versioning
- Track which embedding model was used for each document
- Support for model migration and comparison
- Historical record of embedding model deployments

## Integration Points

### Backend Only (Current)
Token data is collected and stored in Cosmos DB but not exposed in the UI. This is intentional for the initial implementation.

### Future UI Integration
When UI integration is added, embedding token data can be displayed in:
- Document details pages
- Workspace metrics dashboards
- Control center analytics
- Cost reporting views

## Error Handling

### Missing Token Usage
If the Azure OpenAI API doesn't return token usage (older API versions or different providers), the system gracefully handles this by:
- Defaulting to `None` for `token_usage`
- Checking for `None` before accumulation
- Only updating document metadata if tokens > 0

### Backward Compatibility
- Existing documents without embedding token fields will continue to work
- New documents will have the fields initialized
- No migration required for existing documents

## Dependencies

### Azure OpenAI API
- Requires `response.usage` to be available from embedding API calls
- Works with Azure OpenAI Embedding API v2023-05-15 and later

### Cosmos DB
- No schema changes required (dynamic schema)
- New fields added automatically on document creation
- Existing documents remain unchanged

## Next Steps

1. **Monitor production usage** - Validate token tracking accuracy in production
2. **Extend to other file types** - Update remaining process_* functions (XML, JSON, PDF, etc.)
3. **Add group workspace support** - Implement for group documents
4. **Add public workspace support** - Implement for public documents
5. **UI integration** - Display token usage in user-facing dashboards
6. **Cost reporting** - Build reports and analytics on embedding costs

## Related Documentation

- [Tabular Data CSV Storage Fix](../fixes/TABULAR_DATA_CSV_STORAGE_FIX.md)
- [Agent Model Display Fixes](../fixes/AGENT_MODEL_DISPLAY_FIXES.md)
- Main codebase: `application/single_app/`

## Implementation Notes

### Why Start with Personal Workspaces?
Personal workspaces were chosen as the initial implementation target because:
1. Lower complexity (single user partition)
2. Easier testing and validation
3. Pattern can be replicated for group/public workspaces
4. Most common use case for document uploads

### Token Accumulation Strategy
Tokens are accumulated during chunk processing rather than calculated afterward because:
1. Token usage is only available at generation time
2. Avoids need for re-calling the API
3. Real-time tracking as processing occurs
4. No additional cost or latency

### Model Deployment Name
The model deployment name is captured alongside tokens to:
1. Support multiple embedding models
2. Track which model was used for each document
3. Enable cost analysis by model type
4. Support future model migration scenarios

# Metadata-Enhanced Citations Feature

**Version**: 0.229.086  
**Implemented**: November 21, 2025

## Overview

This feature enhances the RAG (Retrieval-Augmented Generation) experience by automatically including document metadata (keywords and abstracts) as additional citation sources when AI Search returns relevant documents. This provides the model with richer context and allows users to see more comprehensive information about the sources used in responses.

## Problem Statement

Previously, when AI Search returned up to 12 document chunks as citations, only the chunk content was included in the context sent to the model. However, documents often contain valuable metadata extracted during upload (keywords and abstracts) that provide additional context about the document's content, purpose, and key topics.

This metadata was stored in Cosmos DB but not being utilized during chat interactions, representing a missed opportunity to:
- Provide better context to the model
- Give users visibility into document keywords and summaries
- Improve the quality of AI responses by including structured metadata

## Solution

### Architecture

The solution adds a metadata extraction pipeline that runs after AI Search results are retrieved but before sending context to the model:

```
1. AI Search returns up to 12 chunks from documents
2. For each unique document:
   a. Determine workspace type (personal/group/public)
   b. Query appropriate Cosmos DB container
   c. Extract keywords and abstract fields
   d. Create additional citation objects if content exists
3. Append metadata to context sent to model
4. Include metadata citations in response
```

### Key Components

#### 1. New Helper Function: `get_document_metadata_for_citations()`

**Location**: `functions_documents.py`

```python
def get_document_metadata_for_citations(document_id, user_id=None, group_id=None, public_workspace_id=None):
    """
    Retrieve keywords and abstract from a document for creating metadata citations.
    Returns dict with 'keywords', 'abstract', and 'file_name' or None if no metadata found.
    """
```

**Purpose**: Efficiently queries the appropriate Cosmos DB container (personal, group, or public) to retrieve document metadata.

**Features**:
- Automatically determines correct container based on workspace type
- Returns None if document not found (graceful failure)
- Only returns data if keywords or abstract have actual content
- Lightweight - only retrieves needed fields

#### 2. Enhanced Citation Processing in `route_backend_chats.py`

**Location**: After hybrid citations are populated, before sending to model

**Process Flow**:

1. **Check if enabled**: Only runs if `enable_extract_meta_data` setting is `True`
2. **Track processed documents**: Maintains set to avoid duplicate processing
3. **Extract document IDs**: Parses chunk IDs to identify parent documents
4. **Determine workspace**: Uses `user_id`, `group_id`, or `public_workspace_id` fields from search results
5. **Query metadata**: Calls `get_document_metadata_for_citations()` for each unique document
6. **Create citations**: If metadata exists:
   - Creates separate citation for keywords (if present)
   - Creates separate citation for abstract (if present)
   - Adds metadata content to retrieved texts sent to model
7. **Update system prompt**: Refreshes the augmentation prompt with enhanced content

### Citation Format

#### Keywords Citation
```python
{
    "file_name": "PolicyDocument.pdf",
    "citation_id": "doc-uuid_keywords",
    "page_number": "Metadata",  # Special identifier
    "chunk_id": "doc-uuid_keywords",
    "chunk_sequence": 9999,  # Sorts to end
    "score": 0.0,
    "metadata_type": "keywords",
    "metadata_content": "policy, compliance, regulations, federal funding"
}
```

#### Abstract Citation
```python
{
    "file_name": "PolicyDocument.pdf",
    "citation_id": "doc-uuid_abstract",
    "page_number": "Metadata",  # Special identifier
    "chunk_id": "doc-uuid_abstract",
    "chunk_sequence": 9998,  # Sorts to end
    "score": 0.0,
    "metadata_type": "abstract",
    "metadata_content": "This document outlines federal funding policies..."
}
```

## Configuration

### Required Setting

**Setting**: `enable_extract_meta_data`  
**Type**: Boolean  
**Location**: Admin Settings → Document Management  
**Default**: `False`

When enabled, the system will:
1. Extract metadata during document upload (existing functionality)
2. Query and include metadata in chat citations (new functionality)

## User Experience

### Before Enhancement
- User receives up to 12 citations from document chunks
- Citations show: file name, page number, chunk content
- No visibility into document metadata

### After Enhancement
- User receives up to 12 chunk citations + up to 12 metadata citations (keywords/abstract)
- Metadata citations clearly marked with "Metadata" as page number
- Model has access to:
  - Original chunk content
  - Document keywords for context
  - Document abstracts for summaries
- Total possible citations: Up to 24 (12 chunks + up to 12 metadata pairs)

### Example User Interaction

**User**: "What documents do we have about compliance?"

**AI Response** (with metadata citations):
"Based on the available documents, we have several resources about compliance:

1. **PolicyDocument.pdf** - Keywords include: compliance, regulations, federal funding (Source: PolicyDocument.pdf, Metadata)
2. **ComplianceGuide.pdf** - This document provides comprehensive guidance on compliance requirements... (Source: ComplianceGuide.pdf, Metadata)

[Additional details from specific page chunks...]"

## Technical Details

### Workspace Detection

The system automatically detects workspace type from AI Search results:

```python
# Personal workspace: has user_id field
doc_user_id = doc.get('user_id')

# Group workspace: has group_id field  
doc_group_id = doc.get('group_id')

# Public workspace: has public_workspace_id field
doc_public_workspace_id = doc.get('public_workspace_id')
```

### Cosmos DB Container Selection

```python
if public_workspace_id:
    cosmos_container = cosmos_public_documents_container
elif group_id:
    cosmos_container = cosmos_group_documents_container
else:
    cosmos_container = cosmos_user_documents_container
```

### Deduplication

Documents are tracked by ID to ensure each document's metadata is only processed once:

```python
processed_doc_ids = set()

for doc in search_results:
    doc_id = doc.get('id', '').split('_')[0]
    if doc_id in processed_doc_ids:
        continue
    processed_doc_ids.add(doc_id)
    # Process metadata...
```

## Performance Considerations

### Efficiency
- **Minimal overhead**: Only queries Cosmos DB for unique documents
- **Graceful failures**: Returns None if document not found, doesn't break chat flow
- **Conditional execution**: Only runs when metadata extraction is enabled
- **Direct reads**: Uses item read by ID (not queries) for optimal performance

### Scalability
- **Bounded growth**: Maximum 12 additional metadata citation pairs (keywords + abstract)
- **Efficient queries**: Direct document reads by partition key
- **Deduplication**: Prevents redundant Cosmos queries

## Limitations

1. **Metadata Dependency**: Requires documents to have been processed with metadata extraction
2. **Setting Dependent**: Only works when `enable_extract_meta_data` is enabled
3. **Content Quality**: Quality of keywords/abstracts depends on:
   - Original document metadata (PDF/DOCX properties)
   - GPT extraction quality during upload
   - User manual edits
4. **Language Support**: Metadata language depends on source document
5. **No Scoring**: Metadata citations have score=0.0 (not ranked by relevance)

## Benefits

### For Users
- **Better Context**: See document keywords and summaries alongside chunk citations
- **Improved Discovery**: Keywords help identify relevant documents quickly
- **Enhanced Understanding**: Abstracts provide document overviews without reading full content
- **Comprehensive Citations**: Up to 24 citations instead of 12

### For AI Model
- **Richer Context**: Access to structured metadata alongside unstructured content
- **Better Responses**: Can reference document themes, topics, and summaries
- **Improved Accuracy**: Keywords help model understand document scope and purpose

### For Administrators
- **Configurable**: Can be toggled via admin settings
- **No Breaking Changes**: Existing functionality unchanged when disabled
- **Audit Trail**: Metadata citations tracked like regular citations

## Testing

### Test Scenarios

1. **Basic Functionality**
   - Upload document with keywords/abstract
   - Enable `enable_extract_meta_data`
   - Search for content in document
   - Verify metadata citations appear

2. **Workspace Types**
   - Test with personal workspace documents
   - Test with group workspace documents
   - Test with public workspace documents

3. **Edge Cases**
   - Documents without metadata
   - Documents with only keywords
   - Documents with only abstract
   - Empty keywords/abstract fields

4. **Performance**
   - Multiple documents in search results
   - Same document appearing multiple times in chunks
   - Verify deduplication works

### Validation

Check that:
- [ ] Metadata citations have `metadata_type` field
- [ ] Page number shows "Metadata" not a number
- [ ] Chunk sequence is high (9998/9999) for sorting
- [ ] Citation IDs are unique (`doc-id_keywords`, `doc-id_abstract`)
- [ ] Content includes in retrieved texts for model
- [ ] System prompt updated with enhanced content

## Future Enhancements

### Potential Improvements
1. **Custom Metadata Fields**: Support for additional metadata beyond keywords/abstract
2. **Metadata Scoring**: Relevance scoring for metadata based on query
3. **Selective Inclusion**: User preference for which metadata types to include
4. **Metadata Highlighting**: Special UI treatment for metadata citations
5. **Metadata-Only Search**: Option to search just document metadata
6. **Aggregation**: Combine metadata across multiple versions of same document

## Related Features

- **Document Metadata Extraction** (v0.228.x): Extracts and stores metadata during upload
- **Enhanced Citations** (v0.229.x): Server-side citation rendering
- **Hybrid Search** (v0.228.x): AI Search integration with multiple workspace types
- **Document Classification** (v0.229.x): Classification metadata also available

## Troubleshooting

### Metadata Citations Not Appearing

**Check**:
1. Is `enable_extract_meta_data` enabled in admin settings?
2. Does the document have keywords or abstract in Cosmos DB?
3. Are search results actually returning documents?
4. Check browser console for errors

### Duplicate Metadata

**Check**:
1. Verify deduplication logic is working
2. Check document IDs in search results
3. Look for multiple versions of same document

### Missing Context in Model Response

**Check**:
1. Verify metadata content is added to `retrieved_texts`
2. Check system prompt includes enhanced content
3. Verify model token limits not exceeded

## Code Locations

### Modified Files
- `application/single_app/functions_documents.py` - Added `get_document_metadata_for_citations()`
- `application/single_app/route_backend_chats.py` - Added metadata extraction logic
- `application/single_app/config.py` - Version updated to 0.229.086

### Key Functions
- `get_document_metadata_for_citations()` - Queries Cosmos for metadata
- `chat_api()` - Main chat endpoint with metadata enhancement logic

## Version History

**0.229.086** - Initial implementation of metadata-enhanced citations
- Added Cosmos DB metadata query function
- Integrated metadata extraction into chat flow
- Created separate citations for keywords and abstracts
- Updated system prompts with metadata content

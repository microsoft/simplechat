# Multi-Modal Vision Analysis Feature

**Version**: 0.229.088 (Initial), 0.229.089 (Expanded model support)  
**Implemented**: November 21, 2025

## Overview

This feature adds AI-powered vision analysis capabilities to Simple Chat, enabling semantic understanding of images beyond traditional OCR text extraction. When enabled alongside Document Intelligence, images receive both text extraction (OCR) and contextual semantic analysis (vision AI), providing richer insights and improved search/citation capabilities.

## Problem Statement

Previously, image processing relied solely on Azure Document Intelligence for OCR (Optical Character Recognition), which extracts text from images but doesn't provide:
- Semantic understanding of image content
- Object detection and identification
- Contextual analysis and insights
- Scene description and interpretation

This limited the AI's ability to answer questions about visual content that wasn't explicitly written as text in the image.

## Solution

### Architecture

The solution integrates GPT-4 Vision (or similar multi-modal models) into the document processing pipeline:

```
1. User uploads image to chat OR workspace
2. Document Intelligence performs OCR (text extraction)
3. Multi-Modal Vision model analyzes image semantically
   a. Generates detailed description
   b. Identifies objects, people, elements
   c. Extracts visible text (secondary OCR)
   d. Provides contextual analysis
4. Both analyses combined and stored
5. Results available in citations and search context
```

### Key Components

#### 1. Admin Configuration (`admin_settings.html`)

**Location**: Admin Settings → Search and Extract Tab → Multi-Modal Vision Analysis

**Configuration Options**:
- **Enable Toggle**: `enable_multimodal_vision`
- **Model Selection**: Dropdown populated with vision-capable models (gpt-4o, gpt-4-vision)
- **Test Connection**: Button to validate vision API connectivity

**UI Features**:
- Automatic filtering of vision-capable models
- Support for both direct Azure OpenAI and APIM configurations
- Informational alerts explaining how it works with Document Intelligence
- Test button with detailed response feedback

#### 2. Settings Database Schema (`functions_settings.py`)

**New Settings**:
```python
'enable_multimodal_vision': False,
'multimodal_vision_model': '',  # Selected deployment name
```

**Integration**:
- Reuses existing GPT authentication settings (APIM or direct)
- Reuses existing managed identity or API key authentication
- No additional endpoints required

#### 3. Core Vision Analysis Function (`functions_documents.py`)

**Function**: `analyze_image_with_vision_model()`

**Parameters**:
- `image_path`: Path to image file
- `user_id`: User ID for logging
- `document_id`: Document ID for tracking
- `settings`: Application settings

**Returns**:
```python
{
    'description': 'AI-generated image description',
    'objects': ['list', 'of', 'detected', 'objects'],
    'text': 'any text visible in image',
    'analysis': 'detailed analysis'
}
```

**Features**:
- Converts image to base64 for API transmission
- Determines correct mime type automatically
- Uses structured JSON prompt for consistent responses
- Handles authentication (managed identity or API key)
- Supports both APIM and direct Azure OpenAI endpoints
- Graceful error handling with detailed logging

#### 4. Document Processing Integration

**Workspace Upload Flow** (`process_di_document()`):
1. Document Intelligence extracts text via OCR
2. If image AND enhanced citations enabled:
   - Vision analysis performed
   - Results stored in document metadata:
     - `vision_analysis`: Full JSON object
     - `vision_description`: Indexed field for search
     - `vision_objects`: Indexed field for filtering
     - `vision_extracted_text`: Additional text content
   - Vision analysis JSON saved to blob storage
3. Document updated with all results

**Chat Upload Flow** (`route_frontend_chats.py`):
1. Document Intelligence extracts text via OCR
2. If vision enabled:
   - Vision analysis performed in-memory
   - Combined with DI results in file message
   - Formatted output added to chat context:
     ```
     === AI Vision Analysis ===
     Description: [semantic description]
     Objects detected: [object list]
     Text visible in image: [additional OCR]
     ```
3. Vision analysis stored in file message metadata

#### 5. Enhanced Citations

**Citation Format** (in `route_backend_chats.py`):

```python
{
    "file_name": "image.jpg",
    "citation_id": "doc-uuid_vision",
    "page_number": "AI Vision",  # Special identifier
    "chunk_id": "doc-uuid_vision",
    "chunk_sequence": 9997,  # Sorts before keywords/abstract
    "score": 0.0,
    "metadata_type": "vision",
    "metadata_content": "AI Vision Analysis:\n..."
}
```

**Content Format**:
```
AI Vision Analysis:
Description: [Full semantic description of the image]
Objects: [Comma-separated list of detected objects]
Text in Image: [Any visible text found]
```

**Integration**:
- Vision citations appear alongside document chunks
- Sorted to appear near metadata citations
- Included in context sent to GPT for answering questions
- Available in citation panel for user reference

#### 6. Test Connection Endpoint (`route_backend_settings.py`)

**Function**: `_test_multimodal_vision_connection()`

**Test Method**:
- Creates 1x1 pixel red PNG (base64 encoded)
- Sends to vision model with simple prompt: "What color is this image?"
- Validates model responds correctly
- Returns success with model response

**Features**:
- Supports both APIM and direct endpoints
- Handles managed identity and API key authentication
- Provides detailed error messages
- Shows model response for verification

## Configuration Flow

### Step 1: Configure GPT Models
1. Admin → AI Models → GPT Configuration
2. Configure endpoint, authentication, API version
3. Fetch models and select vision-capable models (gpt-4o, gpt-4-vision)
4. Save settings

### Step 2: Enable Multi-Modal Vision
1. Admin → Search and Extract → Multi-Modal Vision Analysis
2. Toggle "Enable Multi-Modal Vision Analysis" ON
3. Select vision model from dropdown (only shows vision-capable models)
4. Click "Test Vision Analysis" to validate
5. Save settings

### Step 3: Enable Enhanced Citations (Required for Workspace)
1. Admin → Citation → Enhanced Citations
2. Toggle "Enable Enhanced Citations" ON
3. Configure blob storage settings
4. Save settings

**Note**: For chat uploads, enhanced citations are not required. Vision analysis works in-memory and enhances the chat context directly.

## Usage Scenarios

### Scenario 1: Chat Upload with Image

**User Action**: Upload image to chat conversation

**Processing**:
1. Document Intelligence extracts any text (OCR)
2. Vision model analyzes image semantically
3. Combined results added to conversation context
4. AI can answer questions about:
   - What objects are in the image
   - What's happening in the scene
   - Colors, composition, layout
   - Any visible text
   - Context and meaning

**Example Interaction**:
```
User: [uploads photo of a conference room]
User: How many people are in this meeting?

AI: Based on the AI vision analysis, there are 8 people visible 
in the conference room. The image shows a professional meeting 
setting with participants seated around a table.
```

### Scenario 2: Workspace Document Upload

**User Action**: Upload image to Your Workspace or Group Workspace

**Processing**:
1. Background processing extracts text via Document Intelligence
2. Vision analysis generates semantic description
3. Both stored in Cosmos DB document metadata
4. Vision analysis JSON saved to blob storage
5. Content indexed in AI Search
6. Available for RAG-enhanced conversations

**Citations Available**:
- Document chunks (OCR text)
- Vision analysis (semantic description)
- Keywords metadata (if enabled)
- Abstract metadata (if enabled)

**Example Interaction**:
```
User: What equipment is visible in the office photos?

AI: Based on the AI Vision Analysis of office_photo.jpg, the 
following equipment is visible: laptops, external monitors, 
wireless keyboards, ergonomic chairs, standing desks, and a 
whiteboard with markers (Source: office_photo.jpg, Page: AI Vision)
```

### Scenario 3: Mixed Content Document Search

**User Action**: Ask question about documents with images

**Processing**:
1. AI Search retrieves relevant documents
2. Enhanced citations include:
   - Text chunks from OCR
   - Vision analysis descriptions
   - Metadata (keywords, abstract)
3. GPT has full context from all sources
4. Can answer questions combining text and visual content

## Data Storage

### Cosmos DB Document Structure

```python
{
    "id": "document_id",
    "file_name": "image.jpg",
    "file_type": ".jpg",
    "di_ocr_text": "...",  # From Document Intelligence
    
    # NEW: Vision Analysis Fields
    "vision_analysis": {
        "description": "A modern office space...",
        "objects": ["laptop", "desk", "chair", "monitor"],
        "text": "Welcome to our office",
        "analysis": "Professional workspace..."
    },
    "vision_description": "A modern office space...",  # Indexed
    "vision_objects": ["laptop", "desk", "chair"],      # Indexed
    "vision_extracted_text": "Welcome to our office",   # Indexed
    
    "keywords": ["office", "workspace"],
    "abstract": "Office environment photo",
    "status": "AI vision analysis completed",
    ...
}
```

### Blob Storage Structure

```
user-documents/
  ├── {user_id}/
  │   ├── {document_id}.jpg                    # Original image
  │   ├── {document_id}_vision_analysis.json   # Vision analysis
  │   └── ...

group-documents/
  ├── {group_id}/
  │   ├── {document_id}.jpg
  │   ├── {document_id}_vision_analysis.json
  │   └── ...
```

**Vision Analysis JSON** (`_vision_analysis.json`):
```json
{
  "description": "A modern office workspace with natural lighting...",
  "objects": [
    "desk",
    "laptop",
    "monitor",
    "chair",
    "plant"
  ],
  "text": "Welcome to our office",
  "analysis": "Professional environment designed for productivity..."
}
```

## Model Requirements

### Supported Models

**Vision-Capable Models** (per Azure OpenAI documentation):

**Recommended Models**:
- `gpt-4o` - Latest multi-modal model with vision (recommended)
- `gpt-4o-mini` - Smaller, faster vision-capable model

**O-Series Reasoning Models**:
- `o1` - Reasoning model with vision capabilities
- `o1-preview` - Preview version with vision
- `o1-mini` - Smaller reasoning model with vision
- `o3` - Next-generation reasoning model (if available)
- `o3-mini` - Compact version (if available)

**GPT-5 Series**:
- All GPT-5 models support vision (when available in your region)

**GPT-4.5 & GPT-4.1 Series**:
- `gpt-4.5` - Mid-generation update with vision
- `gpt-4.1` - All variants support vision

**Legacy Vision Models**:
- `gpt-4-vision-preview` - Original vision model
- `gpt-4-turbo-vision` - Turbo variant with vision
- `gpt-4-vision` - Standard vision variant

**Model Detection**:
The admin UI automatically filters and displays only vision-capable models based on naming patterns. If your deployed model includes "vision", "gpt-4o", "gpt-4.1", "gpt-4.5", "gpt-5", or matches o-series patterns (o1, o3, etc.), it will appear in the dropdown.

**API Requirements**:
- Azure OpenAI API version 2024-02-15-preview or later
- Vision API capabilities enabled on deployment
- Model must be deployed in a region that supports vision features

### Token Usage

**Per Image Analysis**:
- Base image encoding: ~1000 tokens (varies by image size)
- Prompt: ~100 tokens
- Response: up to 1000 tokens (configurable via `max_tokens`)
- **Total**: ~2100 tokens per image

**Cost Considerations**:
- Vision models typically cost more per token than text-only models
- Consider limiting to important images or user-requested analysis
- Can be disabled/enabled per environment

## Benefits

### Enhanced Search & Retrieval
- **Semantic Search**: Find images by describing what's in them
- **Object-Based Search**: "Find all images with laptops"
- **Scene Search**: "Show me meeting room photos"
- **Combined Context**: Text + visual understanding

### Improved AI Responses
- **Visual Question Answering**: AI can answer about image content
- **Richer Citations**: Visual context included in sources
- **Better Accuracy**: Multiple analysis methods increase confidence
- **Context Awareness**: Understanding beyond just text

### User Experience
- **Natural Queries**: Ask about visual content naturally
- **Comprehensive Results**: Get both text and visual insights
- **Citation Transparency**: See all analysis sources
- **Flexibility**: Works in both chat and workspace contexts

## Technical Specifications

### Performance
- **Latency**: +2-5 seconds per image (vision analysis)
- **Concurrent Processing**: Handled by background executor
- **Caching**: Vision results cached in Cosmos DB
- **Scalability**: Uses existing Azure OpenAI quotas

### Error Handling
- **Vision Failure**: Falls back to OCR-only processing
- **Model Unavailable**: Logs warning, continues without vision
- **Invalid Response**: Captures raw text as fallback
- **Network Issues**: Retries with exponential backoff

### Logging
- **Debug Logging**: Detailed vision analysis flow
- **Error Tracking**: All exceptions logged with stack traces
- **Performance Metrics**: Analysis duration tracked
- **Results Logging**: Confirmation of successful analysis

## Configuration Requirements

### Prerequisites
1. **Azure OpenAI Service** with vision-capable model deployed
2. **Enhanced Citations** enabled (for workspace uploads)
3. **Document Intelligence** configured (for OCR)
4. **Blob Storage** configured (for workspace uploads)

### Optional Enhancements
- **Metadata Extraction**: Combines with keywords/abstract
- **AI Search**: Vision content indexed for semantic search
- **Content Safety**: Can be applied to vision analysis results

## Limitations

### Current Limitations
1. **Image Types Only**: Only processes image files (not video frames)
2. **Single Image**: Analyzes one image at a time
3. **Token Costs**: Higher cost per analysis than text-only
4. **Model Availability**: Requires vision-capable model deployment

### Future Enhancements
- Video frame extraction and analysis
- Batch image processing for efficiency
- Custom vision prompts per use case
- Vision fine-tuning with domain-specific models
- Integration with Azure Computer Vision for specialized tasks

## Security & Privacy

### Data Handling
- **In-Transit**: Images base64 encoded for API transmission
- **At-Rest**: Original images stored in blob storage (if enhanced citations enabled)
- **Access Control**: Inherits workspace permissions
- **Retention**: Follows blob storage retention policies

### Compliance
- **GDPR**: Vision analysis subject to same data protection
- **HIPAA**: Vision models process healthcare images per compliance needs
- **Enterprise**: All processing via Azure OpenAI (no external APIs)

## Troubleshooting

### Vision Analysis Not Working

**Check**:
1. Is `enable_multimodal_vision` set to `True`?
2. Is a vision model selected in settings?
3. Does the model deployment support vision?
4. Are GPT authentication settings correct?
5. Is API version 2024-02-15-preview or later?

**Test**:
```bash
# Use test button in admin settings
Admin Settings → Search and Extract → Multi-Modal Vision Analysis → Test Vision Analysis
```

### Vision Citations Not Appearing

**Check**:
1. Is `enable_enhanced_citations` enabled? (required for workspace)
2. Was the document processed AFTER enabling vision?
3. Is the file actually an image? (check file extension)
4. Check Cosmos DB document for `vision_analysis` field

**Debug**:
```python
# Check document metadata
doc = cosmos_user_documents_container.read_item(
    item=document_id,
    partition_key=document_id
)
print(doc.get('vision_analysis'))
```

### Model Not Showing in Dropdown

**Check**:
1. Is model name vision-capable? Must match one of:
   - Contains "vision" (gpt-4-vision, gpt-4-turbo-vision)
   - Contains "gpt-4o" (gpt-4o, gpt-4o-mini)
   - Contains "gpt-4.1" (any GPT-4.1 variant)
   - Contains "gpt-4.5" (any GPT-4.5 variant)
   - Contains "gpt-5" (any GPT-5 variant)
   - Matches o-series pattern (o1, o1-preview, o1-mini, o3, o3-mini)
2. Was model fetched and selected in GPT configuration?
3. For APIM: Is deployment name listed in comma-separated list?

**Supported Model Families**:
- **GPT-4o series**: gpt-4o, gpt-4o-mini
- **O-series**: o1, o1-preview, o1-mini, o3, o3-mini
- **GPT-5 series**: All variants (when available)
- **GPT-4.5 & GPT-4.1**: All variants
- **Legacy vision**: gpt-4-vision, gpt-4-turbo-vision

**Solution**:
```
1. Go to Admin Settings → AI Models → GPT Configuration
2. Fetch GPT Models
3. Select a vision-capable model from the list above
4. Save settings
5. Return to Multi-Modal Vision section
6. Model should now appear in dropdown
```

**Note**: If your model supports vision but doesn't appear, check that the deployment name follows Azure OpenAI naming conventions. Custom deployment names may not be detected automatically if they don't include the model family identifiers.

## Related Features

- **Document Intelligence**: Provides OCR for text extraction
- **Enhanced Citations**: Required for workspace document storage
- **Metadata Extraction**: Combines with vision for rich metadata
- **AI Search**: Indexes vision content for semantic search

## Version History

- **0.229.088**: Initial implementation of multi-modal vision analysis
  - Core vision analysis function with base64 encoding
  - Integration into document processing and chat upload flows
  - Enhanced citations with "AI Vision" page type
  - Admin UI with model selection and test connection
  - Initial model filtering (gpt-4o, vision models)
  
- **0.229.089**: Expanded vision model support
  - Added support for o-series reasoning models (o1, o3, etc.)
  - Added support for GPT-5 series models
  - Added support for GPT-4.1 and GPT-4.5 series
  - Improved model detection with comprehensive regex patterns
  - Updated documentation with complete model list per Azure OpenAI specs

- **0.229.090**: Fixed settings persistence issue
  - **Critical Bug Fix**: Settings now save correctly to database
  - Added missing form field processing in backend
  - Toggle and model selection now persist across page reloads
  - Resolved issue where settings appeared to save but reverted

## References

- [Azure OpenAI Vision Documentation](https://learn.microsoft.com/azure/ai-services/openai/how-to/gpt-with-vision)
- [GPT-4 Vision API Reference](https://learn.microsoft.com/azure/ai-services/openai/reference)
- [Document Intelligence OCR](https://learn.microsoft.com/azure/ai-services/document-intelligence/)

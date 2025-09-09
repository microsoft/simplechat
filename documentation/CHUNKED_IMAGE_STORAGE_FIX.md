# Chunked Image Storage for Large Base64 Images

## Issue Description
Large base64 images from gpt-image-1 model (4.3MB) were causing "RequestEntityTooLarge" errors when storing in Cosmos DB, which has a 2MB document size limit.

## Root Cause
- Cosmos DB document size limit: 2MB
- gpt-image-1 base64 images: Can be 4MB+ 
- Single document storage: Exceeded size limit
- Error: `(RequestEntityTooLarge) Message: {"Errors":["Request size is too large"]}`

## Solution: Chunked Storage Across Multiple Documents

### 1. Automatic Size Detection
- **Size Threshold**: 1.5MB (safe margin under 2MB limit)
- **Accounts for JSON Overhead**: Leaves room for metadata
- **Smart Detection**: Checks content size before storage

```python
max_content_size = 1500000  # 1.5MB in bytes
if len(generated_image_url) > max_content_size:
    # Split into chunks
```

### 2. Intelligent Chunking (`route_backend_chats.py`)
- **Data URL Handling**: Preserves `data:image/png;base64,` prefix
- **Optimal Chunk Size**: Calculated based on safe limits
- **Multiple Documents**: Main document + chunk documents

```python
# Main document (contains first chunk + metadata)
main_image_doc = {
    'id': image_message_id,
    'role': 'image',
    'content': f"{data_url_prefix}{chunks[0]}",
    'metadata': {
        'is_chunked': True,
        'total_chunks': total_chunks,
        'chunk_index': 0
    }
}

# Additional chunk documents
chunk_doc = {
    'id': f"{image_message_id}_chunk_{i}",
    'role': 'image_chunk',
    'content': chunks[i],
    'parent_message_id': image_message_id,
    'metadata': {
        'chunk_index': i,
        'total_chunks': total_chunks
    }
}
```

### 3. Transparent Reassembly (`route_backend_conversations.py`)
- **Automatic Detection**: Identifies chunked images during message loading
- **Proper Ordering**: Reassembles chunks in correct sequence
- **Complete Reconstruction**: Returns full image to frontend

```python
# Collect all chunks by parent message ID
for item in all_items:
    if item.get('role') == 'image_chunk':
        parent_id = item.get('parent_message_id')
        chunk_index = item.get('metadata', {}).get('chunk_index', 0)
        chunked_images[parent_id][chunk_index] = item.get('content', '')

# Reassemble complete content
complete_content = message.get('content', '')  # First chunk
for chunk_index in range(1, total_chunks):
    complete_content += chunks[chunk_index]
```

## Benefits

### ✅ **Size Compliance**
- Respects Cosmos DB 2MB document limit
- Safe 1.5MB threshold with overhead margin
- No storage failures for large images

### ✅ **Transparent Operation**
- Automatic chunking detection
- Seamless reassembly during loading
- No frontend changes required

### ✅ **Data Integrity**
- Proper chunk ordering with metadata
- Parent-child relationships maintained
- Original size tracking for verification

### ✅ **Performance Optimized**
- Small images stored normally (no chunking overhead)
- Large images split only when necessary
- Efficient chunk size calculation

## Storage Pattern Examples

### Small Image (< 1.5MB)
```
Documents: 1
├── message_id: 'conv_image_123456_7890'
    ├── role: 'image'
    ├── content: 'data:image/png;base64,iVBORw0...'
    └── metadata: { is_chunked: false }
```

### Large Image (> 1.5MB, e.g., 4.3MB)
```
Documents: 3
├── message_id: 'conv_image_123456_7890' (Main)
│   ├── role: 'image'
│   ├── content: 'data:image/png;base64,{chunk_0}'
│   └── metadata: { is_chunked: true, total_chunks: 3, chunk_index: 0 }
├── message_id: 'conv_image_123456_7890_chunk_1'
│   ├── role: 'image_chunk'
│   ├── content: '{chunk_1_data}'
│   └── metadata: { chunk_index: 1, parent_message_id: 'conv_image_123456_7890' }
└── message_id: 'conv_image_123456_7890_chunk_2'
    ├── role: 'image_chunk'
    ├── content: '{chunk_2_data}'
    └── metadata: { chunk_index: 2, parent_message_id: 'conv_image_123456_7890' }
```

## Testing
Run the functional test to verify chunked storage:
```bash
python functional_tests/test_chunked_image_storage.py
```

## Performance Characteristics
- **Small Images**: No performance impact (single document)
- **Large Images**: Minimal overhead for chunking/reassembly
- **Storage Efficiency**: Optimal use of Cosmos DB limits
- **Retrieval Speed**: Sequential chunk reassembly

## Version
Implemented in version 0.226.107

## Related Files
- `route_backend_chats.py` - Image storage and chunking logic
- `route_backend_conversations.py` - Message loading and reassembly
- `test_chunked_image_storage.py` - Functional tests

## Future Enhancements
- **Compression**: Could add image compression before chunking
- **Caching**: Could cache reassembled images for repeat loads
- **Cleanup**: Could add cleanup job for orphaned chunks

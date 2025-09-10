# Enhanced Citations Implementation

## Overview
This implementation provides an improved citation experience for documents stored in Azure blob storage. When users click on citations, instead of showing plain text, the system now displays appropriate media viewers based on file type.

## Features

### Supported File Types
- **Images** (jpg, jpeg, png, bmp, tiff, tif, heif): Display in a modal viewer
- **PDFs**: Show page context (±1 page) in a modal
- **Videos** (mp4, mov, avi, mkv, flv, webm, wmv): Play with timestamp navigation
- **Audio** (mp3, wav, ogg, aac, flac, m4a): Play with timestamp navigation

### How It Works

#### Frontend Components
1. **chat-enhanced-citations.js**: New module handling different media types
   - File type detection based on extensions
   - Modal creation for each media type
   - Timestamp parsing and seeking for video/audio
   - Integration with existing citation system

2. **Updated chat-citations.js**: Modified to use enhanced system
   - Checks if enhanced citations are enabled
   - Falls back to text citations when needed
   - Passes citation data to enhanced modal system

#### Backend Components
1. **route_enhanced_citations.py**: New API endpoints
   - `/api/enhanced_citations/image`: Serves images with SAS URLs
   - `/api/enhanced_citations/video`: Serves videos with SAS URLs  
   - `/api/enhanced_citations/audio`: Serves audio with SAS URLs
   - Workspace-aware blob storage access

2. **Updated app.py**: Registers enhanced citation routes

### Citation Data Flow

#### For Images
1. User clicks citation → Enhanced modal detects image file type
2. Fetches image SAS URL from `/api/enhanced_citations/image`
3. Displays image in a modal viewer

#### For PDFs
1. User clicks citation → Enhanced modal detects PDF file type
2. Reuses existing PDF viewer but called through enhanced system
3. Shows page ±1 context as before

#### For Video/Audio
1. User clicks citation → Enhanced modal detects video/audio file type
2. Citation ID contains chunk_sequence (timestamp offset in seconds)
3. Fetches media SAS URL from appropriate endpoint
4. Creates video/audio player in modal
5. Seeks to timestamp when media loads

### Timestamp Handling

#### Video Citations
- Video processing creates 30-second chunks with `start_time` and `chunk_sequence`
- Citation IDs format: `{document_id}_{chunk_sequence}`
- `chunk_sequence` represents the offset in seconds from the start
- Enhanced modal seeks to this timestamp when video loads

#### Audio Citations  
- Audio processing creates chunks with similar timestamp structure
- Citation IDs format: `{document_id}_{chunk_sequence}`
- `chunk_sequence` represents the offset in seconds from the start
- Enhanced modal seeks to this timestamp when audio loads

### Configuration
- Enhanced citations are controlled by `enable_enhanced_citations` setting
- Requires blob storage configuration for serving media files
- Works with personal, group, and public workspaces

### Fallback Behavior
- If enhanced citations are disabled globally → Use text citations
- If document metadata indicates enhanced_citations=false → Use text citations
- If file type is not supported → Use text citations
- If enhanced citation fails → Automatically falls back to text citation

## Files Modified

### New Files
- `static/js/chat/chat-enhanced-citations.js`: Main enhanced citations module
- `route_enhanced_citations.py`: Backend API endpoints
- `test_enhanced_citations.py`: Test suite for validation

### Modified Files
- `static/js/chat/chat-citations.js`: Updated to integrate enhanced system
- `app.py`: Added route registration for enhanced citations

## Testing

Run the test suite:
```bash
python test_enhanced_citations.py
```

### Manual Testing Steps
1. Enable enhanced citations in admin settings
2. Upload test files of different types (images, PDFs, videos, audio)
3. Ask questions that generate citations referencing these files
4. Click on citations to verify:
   - Images open in modal viewer
   - PDFs show page context
   - Videos play at correct timestamp
   - Audio plays at correct timestamp

### Debugging
- Check browser console for timestamp conversion logs
- Verify SAS URL generation in backend logs
- Ensure blob storage containers are properly configured
- Test fallback to text citations when enhanced fails

## Architecture Benefits
- Modular design with clear separation of concerns
- Graceful fallback ensures system reliability
- Workspace-aware blob storage access
- Consistent user experience across file types
- Extensible for future media types

## Future Enhancements
- Support for additional file types (PowerPoint, Excel, etc.)
- Thumbnail previews in citation text
- Batch media loading for performance
- Advanced video/audio controls (playback speed, chapters)
- Offline media caching

# Uploading and Managing Documents

Documents are the foundation of Simple Chat's Retrieval-Augmented Generation (RAG) capabilities. This tutorial will teach you everything you need to know about uploading, organizing, and managing your documents effectively.

## What You'll Learn

By the end of this tutorial, you'll:
- Upload documents to different workspace types
- Understand document processing and status indicators
- Organize documents effectively
- Handle different file types and formats
- Troubleshoot common upload issues
- Manage document versions and updates

## Prerequisites

- Simple Chat deployed and configured
- Basic workspace setup completed
- Admin permissions for workspace configuration

## Understanding Workspaces

Simple Chat organizes documents into different workspace types:

### Your Workspace (Personal)
- **Private to you**: Only you can see and use these documents
- **Perfect for**: Personal notes, drafts, confidential documents
- **Access**: Always available to you in chat

### Group Workspaces (Shared)
- **Shared with team members**: Multiple users can access
- **Perfect for**: Team documentation, shared knowledge bases, collaborative projects
- **Access**: Available to group members in chat

### Ephemeral Documents (Session-only)
- **Temporary**: Available only during current chat session
- **Perfect for**: One-time analysis, temporary files, quick questions
- **Access**: Disappears when session ends

## Step 1: Prepare Your Documents

### Supported File Types

**Text Documents**:
- `.txt` - Plain text files
- `.md` - Markdown files  
- `.html` - Web pages
- `.json` - Structured data files

**Office Documents**:
- `.pdf` - PDF documents
- `.docx` - Word documents
- `.pptx` - PowerPoint presentations  
- `.xlsx, .xlsm, .xls` - Excel spreadsheets
- `.csv` - Comma-separated values

**Images** (with OCR):
- `.jpg, .jpeg` - JPEG images
- `.png` - PNG images
- `.bmp, .tiff, .tif` - Other image formats
- `.heif` - High efficiency image format

**Multimedia** (requires additional configuration):
- `.mp4, .mov, .avi, .wmv, .mkv, .webm` - Video files
- `.mp3, .wav, .ogg, .aac, .flac, .m4a` - Audio files

### Document Preparation Tips

**For best results**:
- Use clear, descriptive filenames
- Ensure text is readable (not blurry scans)
- Organize related documents logically
- Keep file sizes reasonable (check admin settings for limits)

## Step 2: Upload to Your Workspace

Let's start with personal document uploads:

### Access Your Workspace
1. **Navigate to "Your Workspace"** from the main menu
2. **Click "Add Documents"** or the upload button
3. **Select files** using the file picker or drag-and-drop

### Upload Process
1. **Choose your files**: Select one or multiple files
2. **Start upload**: Click "Upload" or confirm selection
3. **Monitor progress**: Watch the upload progress indicators
4. **Wait for processing**: Documents need to be processed before use

### Processing Status Indicators

You'll see different status indicators during processing:

- **📤 Uploading**: File transfer in progress
- **⚙️ Processing**: Document being analyzed and chunked
- **✅ Ready**: Available for chat and search
- **❌ Error**: Processing failed (see error message)
- **⏳ Queued**: Waiting for processing resources

## Step 3: Upload to Group Workspaces

Group workspaces require additional setup:

### Create or Join a Group
1. **Navigate to "My Groups"**
2. **Create new group** (if you have permissions) or **join existing**
3. **Access group workspace** once membership is confirmed

### Group Upload Process
1. **Select the group workspace** you want to add documents to
2. **Follow same upload process** as personal workspace
3. **Consider team needs**: Upload documents relevant to group members

### Group Management Considerations
- **Permissions**: Ensure you have upload rights
- **Relevance**: Only upload documents useful to the group
- **Organization**: Use consistent naming and organization
- **Updates**: Coordinate with team members about document changes

## Step 4: Document Classification (Optional)

If document classification is enabled, you can organize uploads:

### Classification Benefits
- **Organization**: Group related documents
- **Discovery**: Help others find relevant content
- **Workflow**: Support business processes
- **Compliance**: Track document sensitivity levels

### How to Classify
1. **Select classification type** during or after upload
2. **Choose appropriate category** from predefined list
3. **Add classification colors** for visual organization

Example classifications:
- 📊 **Financial Reports** (Blue)
- 📋 **Technical Documentation** (Green)  
- 🏢 **HR Policies** (Purple)
- 📈 **Marketing Materials** (Orange)

## Step 5: Manage Your Documents

### View and Organize
- **Document list**: See all uploaded documents
- **Search functionality**: Find documents by name or content
- **Filters**: Filter by classification, date, or status
- **Sorting**: Order by name, date, or relevance

### Document Actions
- **View details**: See processing information and metadata
- **Download**: Get original file back
- **Delete**: Remove from workspace (careful - this affects chat!)
- **Re-process**: Retry failed processing

### Version Management
When uploading a document with the same name:
- **New version**: Replaces old content
- **Keep both**: Rename one to keep separate versions
- **Overwrite**: Replace completely (recommended for updates)

## Step 6: Using Documents in Chat

### Select Workspace in Chat
1. **Go to Chat** interface
2. **Choose workspace** from dropdown
3. **Verify document availability** in workspace selector

### Document Context in Conversations
- Simple Chat automatically searches relevant documents
- Citations show which documents provided information
- You can ask about specific documents by name

### Example Chat Interactions

**General questions**:
- "What are the main topics covered in my documents?"
- "Summarize the key findings from the financial reports"

**Document-specific questions**:
- "What does the Q3 report say about revenue growth?"
- "Find information about security policies in the HR documents"

**Cross-document analysis**:
- "Compare the budget projections across all quarterly reports"
- "What trends do you see across all marketing documents?"

## Best Practices

### Organization
- ✅ Use descriptive filenames
- ✅ Group related documents in appropriate workspaces
- ✅ Apply consistent classification schemes
- ✅ Remove outdated documents regularly

### File Management
- ✅ Check file quality before upload
- ✅ Keep reasonable file sizes
- ✅ Upload updated versions when content changes
- ✅ Test document searchability after upload

### Collaboration
- ✅ Coordinate with team members on group uploads
- ✅ Use consistent naming conventions
- ✅ Document any special handling requirements
- ✅ Share knowledge about document organization

## Troubleshooting Common Issues

### Upload Failures
**Large file size**:
- Check admin settings for file size limits
- Compress large files or split into smaller pieces
- Contact admin to increase limits if needed

**Unsupported file type**:
- Convert to supported format
- Check if additional features need to be enabled
- Use alternative file format

**Processing errors**:
- Verify file isn't corrupted
- Check if file requires specific software to open
- Try re-uploading or use different format

### Content Not Found in Chat
**Document not processed**:
- Wait for processing to complete
- Check for error status and resolve issues
- Re-upload if processing failed

**Content not matching queries**:
- Try different search terms or phrases
- Verify document content is searchable text (not just images)
- Check if document needs OCR processing

### Performance Issues
**Slow uploads**:
- Check internet connection
- Try uploading smaller batches
- Upload during off-peak times

**Slow processing**:
- Large documents take time to process
- Multiple simultaneous uploads can cause delays
- Check system resource availability

## What You've Accomplished

Congratulations! You've successfully:
✅ Uploaded documents to different workspace types  
✅ Understood document processing workflow  
✅ Organized documents with classifications  
✅ Learned document management best practices  
✅ Troubleshot common upload issues

## Next Steps

Now that you're comfortable with document management:
- [Classify your documents](classifying_documents) for better organization
- [Create agents](first_agent) that work with specific document sets
- Explore [advanced document management](../how-to/add_documents) techniques
- Learn about [enhanced citations](../how-to/enhanced_citations) for better document linking

---

*Next: [Classifying Documents](classifying_documents) →*

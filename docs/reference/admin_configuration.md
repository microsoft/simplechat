# Admin Configuration Reference

This reference provides complete details about all administrative configuration options available in Simple Chat. The Admin Settings page provides a centralized location to configure application features and service connections.

## Accessing Admin Settings

Once deployed and running, users with the **Admin** role can access the Admin Settings page through the application interface.

![Admin Settings Page](../images/admin_settings_page.png)

## Configuration Sections

### 1. General Settings

Controls basic application appearance and branding.

**Application Title**
- Set custom title displayed in browser and interface
- Default: "Simple Chat"
- Format: Plain text string

**Custom Logo Upload**  
- Upload organization logo to replace default branding
- Supported formats: PNG, JPG, GIF
- Recommended size: 200x50 pixels
- Maximum file size: 1MB

**Landing Page Markdown Text**
- Customize welcome message on landing page
- Supports full Markdown formatting
- Can include links, images, and styling
- Useful for announcements or instructions

### 2. GPT Configuration

Configure Azure OpenAI endpoints for chat models.

**Endpoint Configuration**
- **Direct Endpoint**: Connect directly to Azure OpenAI resource
- **APIM Endpoint**: Connect through Azure API Management

**Authentication Methods**
- **API Key**: Traditional key-based authentication
- **Managed Identity**: Azure Managed Identity (recommended)

**Connection Testing**
- **Test Connection**: Verify endpoint accessibility and authentication
- **Connection Status**: Real-time connection validation

**Model Deployment Selection**
- **Active Deployment(s)**: Choose which GPT model deployments are available
- **Multi-model Support**: Allow users to select from multiple models
- **Default Model**: Set default model for new conversations

**Multi-Model Selection Setup**
1. Configure multiple model deployments in Azure OpenAI
2. Add each deployment endpoint in Admin Settings
3. Test connections for all deployments
4. Enable multi-model selection for users
5. Set appropriate default model

### 3. Embeddings Configuration

Configure Azure OpenAI endpoints for embedding models used in RAG.

**Endpoint Options**
- **Direct Endpoint**: Direct connection to Azure OpenAI
- **APIM Endpoint**: API Management routing

**Authentication**
- **API Key**: Key-based authentication
- **Managed Identity**: Recommended for production

**Deployment Selection**
- **Active Deployment**: Choose embedding model deployment
- **Connection Testing**: Verify embedding service availability

**Supported Embedding Models**
- text-embedding-ada-002
- text-embedding-3-small  
- text-embedding-3-large

### 4. Image Generation (Optional)

Configure DALL-E image generation capabilities.

**Feature Control**
- **Enable/Disable**: Toggle image generation feature
- **User Access**: Control which users can generate images

**Azure OpenAI DALL-E Configuration**
- **Endpoint**: DALL-E deployment endpoint
- **Authentication**: Key or Managed Identity
- **Model Selection**: Choose DALL-E model version
- **Connection Testing**: Verify DALL-E accessibility

### 5. Workspaces Configuration

Control document workspace features and capabilities.

#### Your Workspace (Personal Documents)
- **Enable/Disable**: Control personal document uploads
- **Storage Limit**: Set per-user storage limits (if applicable)
- **File Type Restrictions**: Limit allowed file types

#### My Groups (Group Workspaces)  
- **Enable/Disable**: Control group workspace functionality
- **Group Creation**: Require `CreateGroups` RBAC role for new group creation
- **Member Management**: Control who can add/remove group members
- **Document Permissions**: Set group document access policies

#### Multimedia Support
**Video Processing (Azure Video Indexer)**
- **Enable/Disable**: Toggle video file support
- **Account ID**: Video Indexer account identifier
- **Location**: Geographic location of Video Indexer account
- **API Key**: Authentication key for Video Indexer
- **API Endpoint**: Video Indexer service endpoint
- **Timeout Settings**: Processing timeout limits

**Audio Processing (Azure Speech Service)**
- **Enable/Disable**: Toggle audio file support
- **Endpoint**: Speech service endpoint URL
- **Region**: Azure region for Speech service
- **API Key**: Authentication key for Speech service

#### Metadata Extraction
- **Enable/Disable**: Toggle AI-powered metadata extraction
- **GPT Model Selection**: Choose model for metadata generation
- **Extraction Types**: Keywords, summaries, author/date inference
- **Manual Override**: Allow users to edit extracted metadata

#### Document Classification
- **Enable/Disable**: Toggle document classification features
- **Classification Labels**: Define category names and descriptions
- **Color Coding**: Assign colors for visual organization
- **Required Classification**: Make classification mandatory for uploads
- **Default Categories**: Set default classification options

**Sample Classification Configuration:**
```
Financial Reports (Blue)
HR Policies (Purple)  
Technical Documentation (Green)
Marketing Materials (Orange)
Legal Documents (Red)
Meeting Notes (Yellow)
```

### 6. Citations Configuration

Control how document citations are displayed and linked.

#### Standard Citations
- **Always Enabled**: Basic text-based citation references
- **Format**: "Document: filename, Chunk: number"
- **Clickable Links**: Link to document source when available

#### Enhanced Citations
- **Enable/Disable**: Toggle rich citation features
- **Azure Storage Connection**: Storage account for processed files
- **Authentication**: Connection string or Managed Identity
- **File Organization**: User and document-scoped folder structure
- **Preview Integration**: Direct links to document pages/timestamps

**Enhanced Citations Setup:**
1. Configure Azure Storage Account connection
2. Choose authentication method (Managed Identity recommended)
3. Test storage connectivity  
4. Enable enhanced citations feature
5. Verify citation links in chat interface

### 7. Safety Configuration

Configure content moderation and user feedback systems.

#### Content Safety (Azure AI Content Safety)
- **Enable/Disable**: Toggle content moderation
- **Endpoint Configuration**: Direct or APIM endpoint
- **Authentication**: Key or Managed Identity authentication
- **Connection Testing**: Verify Content Safety service access

**Content Filtering Categories:**
- **Hate Speech**: Detect and filter hate content
- **Sexual Content**: Moderate sexual material
- **Violence**: Filter violent content
- **Self-Harm**: Detect self-harm content
- **Severity Thresholds**: Set filtering sensitivity levels

**Custom Blocklists:**
- **Custom Terms**: Add organization-specific blocked terms
- **Regex Patterns**: Use pattern matching for complex filtering
- **Allowlists**: Define permitted terms that override filters

#### User Feedback System
- **Enable/Disable**: Toggle user rating and feedback collection
- **Rating Types**: Thumbs up/down, star ratings, custom scales
- **Comment Collection**: Allow detailed feedback comments
- **Admin Dashboard**: Interface for reviewing user feedback

#### RBAC Access Control
**Safety Violation Admin (`SafetyViolationAdmin` role)**
- **Requirement**: Require specific role for safety violation access
- **Violation Dashboard**: Interface for reviewing flagged content
- **User Management**: Actions for users with safety violations

**Feedback Admin (`FeedbackAdmin` role)**
- **Requirement**: Require specific role for feedback access
- **Feedback Dashboard**: Interface for reviewing user feedback  
- **Response Management**: Tools for responding to user feedback

#### Conversation Archiving
- **Enable/Disable**: Toggle conversation archiving for compliance
- **Archive Location**: Cosmos DB container for archived conversations
- **Retention Policy**: How long to retain archived conversations
- **Access Control**: Who can access archived conversations
- **Export Options**: Tools for exporting archived data

### 8. Search & Extract Configuration

Configure document processing and search capabilities.

#### Azure AI Search
- **Endpoint**: AI Search service endpoint URL
- **Authentication**: Key or Managed Identity
- **Connection Testing**: Verify search service connectivity
- **Index Management**: Configuration for search indexes
- **Query Configuration**: Search behavior and relevance tuning

**Search Performance Options:**
- **Semantic Search**: Enable semantic ranking for better relevance
- **Hybrid Search**: Combine vector and keyword search
- **Query Expansion**: Expand queries for better recall
- **Result Ranking**: Configure search result ordering

#### Document Intelligence
- **Endpoint**: Document Intelligence service endpoint
- **Authentication**: Key or Managed Identity  
- **Connection Testing**: Verify document processing service
- **Processing Options**: Configure document analysis features

**Supported Document Intelligence Features:**
- **OCR**: Optical character recognition for images/PDFs
- **Layout Analysis**: Extract document structure and formatting
- **Table Extraction**: Identify and extract table data
- **Form Recognition**: Process structured forms and documents

### 9. Other Settings

Additional configuration options for application behavior.

#### File Management
**Maximum File Size**
- **Setting**: Maximum upload size in MB
- **Default**: 50MB
- **Range**: 1MB - 500MB (depending on App Service plan)
- **Impact**: Affects upload performance and storage costs

**Supported File Types**
- **Text Files**: .txt, .md, .html, .json
- **Documents**: .pdf, .docx, .pptx, .xlsx, .xlsm, .xls, .csv
- **Images**: .jpg, .jpeg, .png, .bmp, .tiff, .tif, .heif
- **Video**: .mp4, .mov, .avi, .wmv, .mkv, .webm (requires Video Indexer)
- **Audio**: .mp3, .wav, .ogg, .aac, .flac, .m4a (requires Speech Service)

#### Chat Behavior  
**Conversation History Limit**
- **Setting**: Maximum number of past conversations displayed
- **Default**: 50 conversations
- **Range**: 10 - 1000 conversations
- **Impact**: Affects UI performance and user experience

**Default System Prompt**
- **Configuration**: Base instructions for AI model behavior
- **Customization**: Tailor AI personality and response style
- **Best Practices**: Clear, specific instructions work best
- **Template Variables**: Support for dynamic prompt elements

**Example System Prompt:**
```
You are a helpful AI assistant for [Organization Name]. 
You provide accurate, professional responses based on the 
documents and context provided. Always cite your sources 
and indicate when you're uncertain about information.

Guidelines:
- Be concise but thorough
- Use professional tone
- Cite document sources
- Ask for clarification when needed
- Follow company policies and guidelines
```

#### Logging and Monitoring
**File Processing Logs**
- **Enable/Disable**: Toggle verbose logging for document ingestion
- **Log Level**: Control detail level of processing logs
- **Retention**: How long to keep processing logs
- **Access**: Who can view processing logs

**Application Insights Integration**
- **Performance Monitoring**: Track application performance metrics
- **Error Tracking**: Monitor and alert on application errors
- **User Analytics**: Track user behavior and feature usage
- **Custom Events**: Log business-specific events and metrics

## Configuration Best Practices

### Security
- ✅ Use Managed Identity authentication whenever possible
- ✅ Regularly rotate API keys if used
- ✅ Enable Content Safety for production deployments
- ✅ Implement proper RBAC role assignments
- ✅ Monitor access to admin settings

### Performance
- ✅ Test all service connections after configuration
- ✅ Configure appropriate timeouts for external services
- ✅ Monitor service quotas and rate limits
- ✅ Use autoscaling for variable workloads
- ✅ Implement caching where appropriate

### Operational
- ✅ Document configuration decisions and changes
- ✅ Create configuration backup/restore procedures
- ✅ Test disaster recovery scenarios
- ✅ Monitor service health and dependencies
- ✅ Plan for service maintenance windows

### Cost Management
- ✅ Monitor usage and costs across all services
- ✅ Set appropriate service tiers for usage patterns
- ✅ Use consumption-based pricing where available
- ✅ Implement cost alerts and budgets
- ✅ Regular cost optimization reviews

## Troubleshooting Configuration Issues

### Service Connection Failures

**Azure OpenAI Connection Issues:**
```
Common Problems:
- Incorrect endpoint URL format
- Invalid API key or expired key
- Managed Identity not properly configured
- Model deployment not found
- Rate limiting or quota exceeded

Solutions:
- Verify endpoint URL includes proper prefix/suffix
- Generate new API key in Azure Portal
- Check Managed Identity role assignments
- Confirm model deployment name and availability
- Monitor quota usage in Azure OpenAI Studio
```

**Cosmos DB Connection Issues:**
```
Common Problems:
- Firewall blocking App Service
- Invalid connection string format
- Managed Identity permissions missing
- Network connectivity issues

Solutions:  
- Add App Service IP to Cosmos DB firewall
- Verify connection string includes AccountEndpoint
- Assign Cosmos DB Data Contributor role
- Check Private Endpoint configuration
```

### Feature Configuration Problems

**Document Processing Issues:**
```
Common Problems:
- File size exceeding limits
- Unsupported file types
- Document Intelligence quota exceeded
- Storage connection issues

Solutions:
- Increase file size limits or compress files
- Check supported file type list
- Monitor Document Intelligence usage
- Verify storage account connectivity
```

**Search and RAG Issues:**
```
Common Problems:
- Documents not appearing in search results
- Poor search relevance
- Slow query performance
- Index synchronization issues

Solutions:
- Verify document processing completed successfully
- Tune search query parameters
- Check AI Search service performance tier
- Monitor indexing status and errors
```

## API Configuration Reference

For programmatic configuration management, Simple Chat exposes REST APIs for admin settings:

### Configuration API Endpoints

**Get Configuration:**
```http
GET /api/admin/config
Authorization: Bearer {token}
```

**Update Configuration:**  
```http
PUT /api/admin/config
Content-Type: application/json
Authorization: Bearer {token}

{
    "general": {...},
    "gpt": {...},
    "embeddings": {...}
}
```

**Test Service Connection:**
```http
POST /api/admin/test-connection
Content-Type: application/json
Authorization: Bearer {token}

{
    "service": "openai",
    "config": {...}
}
```

### Configuration Schema

The configuration follows a structured schema with validation:

```json
{
    "general": {
        "appTitle": "string",
        "customLogo": "base64-string",
        "landingPageText": "markdown-string"
    },
    "gpt": {
        "endpoint": "url",
        "authType": "key|managed-identity",
        "apiKey": "string",
        "deployments": ["string-array"]
    },
    "embeddings": {
        "endpoint": "url", 
        "authType": "key|managed-identity",
        "deployment": "string"
    }
}
```

This reference provides comprehensive details for configuring Simple Chat to meet your organization's specific needs and requirements.

# Simple Chat - Admin Configuration

[Return to Main](../README.md)

Once the application is running and you log in as a user assigned the Admin role, you can access the **Admin Settings** page. This UI provides a centralized location to configure most application features and service connections.

![alt text](./images/admin_settings_page.png)

## Setup Walkthrough

The Admin Settings page includes an interactive **Setup Walkthrough** feature that guides you through the initial configuration process. This is particularly helpful for first-time setup.

### Starting the Walkthrough

- The walkthrough automatically appears on first-time setup when critical settings are missing
- You can manually launch it anytime by clicking the **"Start Setup Walkthrough"** button at the top of the Admin Settings page
- The walkthrough will automatically navigate to the relevant configuration tabs as you progress through each step

### Walkthrough Features

- **Automatic Tab Navigation**: As you move through steps, the walkthrough automatically switches to the relevant admin settings tab and scrolls to the appropriate section
- **Smart Step Skipping**: Steps that aren't applicable based on your configuration choices (e.g., workspace-dependent features) are automatically skipped
- **Real-time Validation**: The "Next" button becomes available only when required fields for the current step are completed
- **Progress Tracking**: Visual progress bar shows your completion status through the setup process
- **Flexible Navigation**: Use "Previous" and "Next" buttons to move between steps, or close the walkthrough at any time to configure settings manually

### Walkthrough Steps Overview

The walkthrough covers these key configuration areas in order:

1. **Application Basics** (Optional) - App title and logo
2. **GPT API Settings** (Required) - Azure OpenAI GPT endpoint and authentication
3. **GPT Model Selection** (Required) - Select available GPT models for users
4. **Workspaces** (Optional) - Enable personal and/or group workspaces
5. **Embedding API** (Required if workspaces enabled) - Configure embedding service
6. **Azure AI Search** (Required if workspaces enabled) - Configure search indexing
7. **Document Intelligence** (Required if workspaces enabled) - Configure document processing
8. **Video Support** (Optional, workspace-dependent) - Configure video file processing
9. **Audio Support** (Optional, workspace-dependent) - Configure audio file processing
10. **Content Safety** (Optional) - Configure content filtering
11. **User Feedback & Archiving** (Optional) - Enable feedback and conversation archiving
12. **Enhanced Features** (Optional) - Enhanced citations and image generation

The walkthrough automatically adjusts which steps are required based on your selections. For example, if you don't enable workspaces, embedding and search configuration steps become optional.

## Configuration Sections

Key configuration sections include:

### 1. General
- **Branding**: Application title, custom logo upload (light and dark mode), favicon
- **Home Page Text**: Landing page markdown content with alignment options and optional editor
- **Appearance**: Default theme (light/dark mode) and navigation layout (top nav or left sidebar)
- **Health Check**: External health check endpoint configuration for monitoring systems
- **API Documentation**: Enable/disable Swagger/OpenAPI documentation endpoint
- **Classification Banner**: Security classification banner for data sensitivity indication
- **External Links**: Custom navigation links to external resources with configurable menu behavior
- **System Settings**: Maximum file size, conversation history limit, default system prompt

### 2. AI Models
- **GPT Configuration**: 
  - Configure Azure OpenAI endpoint(s) for chat models
  - Supports Direct endpoint or APIM (API Management)
  - Allows Key or Managed Identity authentication
  - Test connection button
  - Select multiple active deployment(s) - users can choose from available models
  - Multi-model selection for users
  
- **Embeddings Configuration**:
  - Configure Azure OpenAI endpoint(s) for embedding models
  - Supports Direct/APIM, Key/Managed Identity
  - Test connection
  - Select active deployment
  
- **Image Generation** *(Optional)*:
  - Enable/disable feature
  - Configure Azure OpenAI DALL-E endpoint
  - Supports Direct/APIM, Key/Managed Identity
  - Test connection
  - Select active deployment

### 3. Workspaces
- **Personal Workspaces**: Enable/disable "Your Workspace" (personal docs)
- **Group Workspaces**: 
  - Enable/disable "Groups" (group docs)
  - Option to enforce `CreateGroups` RBAC role for creating new groups
- **Public Workspaces**: 
  - Enable/disable "Public" (public docs)
  - Option to enforce `CreatePublicWorkspaces` RBAC role for creating new public workspaces
- **File Sharing**:
  - Enable/disable file sharing capabilities between users and workspaces.
- **Metadata Extraction**:
  - Enable/disable metadata extraction from documents
  - Select the GPT model used for extraction
- **Multi-Modal Vision Analysis**:
  - Enable vision-capable models for image analysis in addition to document OCR
  - Automatic filtering of compatible GPT models (GPT-4o, GPT-4 Vision, etc.)
- **Document Classification**:
  - Enable/disable classification features
  - Define custom classification labels and colors
  - Dynamic category management with inline editing

### 4. Citations
- **Standard Citations**: Basic text references (always enabled)
- **Enhanced Citations**:
  - Enable/disable enhanced citation features
  - Configure Azure Storage Account Connection String or Service Endpoint with Managed Identity
  - Store original files for direct reference and preview

### 5. Safety
- **Content Safety**:
  - Enable/disable content filtering
  - Configure endpoint (Direct/APIM)
  - Key/Managed Identity authentication
  - Test connection
- **User Feedback**:
  - Enable/disable thumbs up/down feedback on AI responses
- **Admin Access RBAC**:
  - Option to require `SafetyViolationAdmin` role for safety violation admin views
  - Option to require `FeedbackAdmin` role for feedback admin views
- **Conversation Archiving**:
  - Enable/disable conversation archiving instead of permanent deletion

### 6. Search & Extract
- **Azure AI Search**:
  - Configure connection (Endpoint, Key/Managed Identity)
  - Support for Direct or APIM routing
  - Test connection
- **Document Intelligence**:
  - Configure connection (Endpoint, Key/Managed Identity)
  - Support for Direct or APIM routing
  - Test connection
- **Multimedia Support** (Video/Audio uploads):
  - **Video Files**: Configure Azure Video Indexer using Managed Identity authentication
    - Resource Group, Subscription ID, Account Name, Location, Account ID
    - API Endpoint, ARM API Version, Timeout
  - **Audio Files**: Configure Speech Service
    - Endpoint, Location/Region, Locale
    - Key/Managed Identity authentication

### 7. Agents
- **Agents Configuration**:
  - Enable/disable Semantic Kernel-powered agents
  - Configure workspace mode (per-user vs global agents)
  - Agent orchestration settings (single agent vs multi-agent group chat)
  - Manage global agents and select default/orchestrator agent
- **Actions Configuration**:
  - Enable/disable core plugins (Time, HTTP, Wait, Math, Text, Fact Memory, Embedding)
  - Configure user and group plugin permissions
  - Manage custom OpenAPI plugins

### 8. Scale
- **Redis Cache**:
  - Enable distributed session storage for horizontal scaling
  - Configure Redis endpoint and authentication (Key or Managed Identity)
  - Test connection
- **Front Door**:
  - Enable Azure Front Door integration
  - Configure Front Door URL for authentication flows
  - Supports global load balancing and custom domains

### 9. Logging
- **Application Insights Logging**:
  - Enable global logging for agents and orchestration
  - Requires application restart to take effect
- **Debug Logging**:
  - Enable/disable debug print statements
  - Optional time-based auto-disable feature
  - Warning: Collects tokens and keys during debug
- **File Processing Logs**:
  - Enable logging of file processing events
  - Logs stored in Cosmos DB file_processing container
  - Optional time-based auto-disable feature

## Navigation Options

The Admin Settings page supports two navigation layouts:

1. **Tab Navigation** (Default): Horizontal tabs at the top for switching between configuration sections
2. **Left Sidebar Navigation**: Collapsible left sidebar with grouped navigation items
   - Can be set as the default for all users in General → Appearance settings
   - Users can toggle between layouts individually
   - The Setup Walkthrough works seamlessly with both navigation styles

## Tips for Configuration

- **Save Changes**: The floating "Save Settings" button in the bottom-right becomes active (blue) when you make changes
- **Test Connections**: Use the "Test Connection" buttons to verify your service configurations before saving
- **APIM vs Direct**: When using Azure API Management (APIM), you'll need to manually specify model names as automatic model fetching is not available
- **Managed Identity**: When using Managed Identity authentication, ensure your Service Principal has the appropriate roles assigned:
  - **Azure OpenAI**: Cognitive Services OpenAI User role
  - **Speech Service**: Cognitive Services Speech Contributor role (requires custom domain name on endpoint)
  - **Video Indexer**: Appropriate Video Indexer roles for your account
- **Dependencies**: The walkthrough will alert you if required services aren't configured when you enable dependent features (e.g., workspaces require embeddings, AI Search, and Document Intelligence)
- **Required vs Optional**: The walkthrough clearly indicates which settings are required vs optional based on your configuration choices
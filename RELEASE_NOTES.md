<!-- BEGIN RELEASE_NOTES.MD BLOCK -->

# Feature Release

### **(v0.214.001)**

#### New Features

*   **Dark Mode Support**
    *   Added full dark mode theming with support for:
        *   Chat interface (left and right panes)
        *   File metadata panels
        *   Dropdowns, headers, buttons, and classification tables
    *   User preferences persist across sessions.
    *   Dark mode toggle in navbar with text labels and styling fixes (no flash during navigation).
*   **Admin Management Enhancements**
    *   **First-Time Configuration Wizard**: Introduced a guided setup wizard on the Admin Settings page. This wizard simplifies the initial configuration process for application basics (title, logo), GPT API settings, workspace settings, additional services (Embedding, AI Search, Document Intelligence), and optional features. (Ref: `README.md`, `admin_settings.js`, `admin_settings.html`)
    *   Admin Settings UI updated to show application version check status, comparing against the latest GitHub release. (Ref: `route_frontend_admin_settings.py`, `admin_settings.html`)
    *   Added `logout_hint` parameter to resolve multi-identity logout errors.
    *   Updated favicon and admin settings layout for improved clarity and usability.
*   **UI Banner & Visual Updates**
    *   **Enhanced Document Dropdown (Chat Interface)**: The document selection dropdown in the chat interface has been significantly improved:
        *   Increased width and scrollability for better handling of numerous documents.
        *   Client-side search/filter functionality added to quickly find documents.
        *   Improved visual feedback, including a "no matches found" message. (Ref: `chats.css`, `chat-documents.js`, `chats.html`)
    *   New top-of-page banner added (configurable).
    *   Local CSS/JS used across admin, group, and user workspaces for consistency and performance.
    *   Updated `base.html` and `workspace.html` to reflect visual improvements.
*   **Application Setup & Configuration**
    *   **Automatic Storage Container Creation**: The application now attempts to automatically create the `user-documents` and `group-documents` Azure Storage containers during initialization if they are not found, provided "Enhanced Citations" are enabled and a valid storage connection string is configured. Manual creation as per documentation is still the recommended primary approach. (Ref: `config.py`)
    *   Updated documentation for Azure Storage Account setup, including guidance for the new First-Time Configuration Wizard. (Ref: `README.md`)
*   **Security Improvements**
    *   Implemented `X-Content-Type-Options: nosniff` header to mitigate MIME sniffing vulnerabilities.
    *   Enhanced security for loading AI Search index schema JSON files by implementing path validation and using `secure_filename` in backend settings. (Ref: `route_backend_settings.py`)
*   **Build & Deployment**
    *   Added `docker_image_publish_dev.yml` GitHub Action workflow for publishing dev Docker images.
    *   Updated Dockerfile to use Python 3.12.
*   **Version Enforcement**
    *   GitHub workflow `enforce-dev-to-main.yml` added to prevent pull requests to `main` unless from `development`.

#### Bug Fixes

*   **A. Document Processing**
    *   **Document Deletion**: Resolved an issue where documents were not properly deleted from Azure Blob Storage. Now, when a document is deleted from the application, its corresponding blob is also removed from the `user-documents` or `group-documents` container if enhanced citations are enabled. (Ref: `functions_documents.py`)
    *   **Configuration Validation (Enhanced Citations)**: Added validation in Admin Settings to ensure that if "Enhanced Citations" is enabled, the "Office Docs Storage Account Connection String" is also provided. If the connection string is missing, Enhanced Citations will be automatically disabled, and a warning message will be displayed to the admin, preventing silent failures. (Ref: `route_frontend_admin_settings.py`)
*   **C. UI & Usability**
    *   **Local Assets for SimpleMDE**: The SimpleMDE Markdown editor assets (JS/CSS) are now served locally from `/static/js/simplemde/` and `/static/css/simplemde.min.css` instead of a CDN. This improves page load times, reduces external dependencies, and allows for use in offline or air-gapped environments. (Ref: `simplemde.min.js`, `simplemde.min.css` additions, template updates in `group_workspaces.html`, `workspace.html`)
    *   General CSS cleanups across admin and workspace UIs.
*   **D. General Stability**
    *   Merged contributions from multiple devs including UI fixes, backend updates, and config changes.
    *   Removed unused video/audio container declarations for a leaner frontend.

### **(v0.213.001)**

#### New Features

1. **Dark Mode Support**
   - Added full dark mode theming with support for:
     - Chat interface (left and right panes)
     - File metadata panels
     - Dropdowns, headers, buttons, and classification tables
   - User preferences persist across sessions.
   - Dark mode toggle in navbar with text labels and styling fixes (no flash during navigation).
2. **Admin Management Enhancements**
   - Admin Settings UI updated to show version check.
   - Added logout_hint parameter to resolve multi-identity logout errors.
   - Updated favicon and admin settings layout for improved clarity and usability.
3. **UI Banner & Visual Updates**
   - New top-of-page banner added (configurable).
   - Local CSS/JS used across admin, group, and user workspaces for consistency and performance.
   - Updated `base.html` and `workspace.html` to reflect visual improvements.
4. **Security Improvements**
   - Implemented `X-Content-Type-Options: nosniff` header to mitigate MIME sniffing vulnerabilities.
5. **Build & Deployment**
   - Added `docker_image_publish_dev.yml` GitHub Action workflow for publishing dev Docker images.
   - Updated Dockerfile to use **Python 3.12**.
6. **Version Enforcement**
   - GitHub workflow `enforce-dev-to-main.yml` added to prevent pull requests to `main` unless from `development`.

#### Bug Fixes

A. **Document Processing**

- Resolved document deletion error.

C. **UI & Usability**

- Local assets now used for JS/CSS to improve load times and offline compatibility.
- General CSS cleanups across admin and workspace UIs.

D. **General Stability**

- Merged contributions from multiple devs including UI fixes, backend updates, and config changes.
- Removed unused video/audio container declarations for a leaner frontend.

## (v0.212.79)

### New Features

#### 1. Audio & Video Processing

- **Audio processing pipeline**
  - Integrated Azure Speech transcriptions into document ingestion.
  - Splits transcripts into ~400-word chunks for downstream indexing.
- **Video Indexer settings UI**
  - Added input fields in Admin Settings for Video Indexer endpoint, key and locale.

#### 2. Multi-Model Support

- Users may choose from **multiple OpenAI deployments** at runtime.
- Model list is dynamically populated based on Admin settings (including APIM).

#### 3. Advanced Chunking Logic

- **PDF & PPTX**: page-based chunks via Document Intelligence.
- **DOC/DOCX**: ~400-word chunks via Document Intelligence.
- **Images** (jpg/jpeg/png/bmp/tiff/tif/heif): single-chunk OCR.
- **Plain Text (.txt)**: ~400-word chunks.
- **HTML**: hierarchical H1–H5 splits with table rebuilding, 600–1200-word sizing.
- **Markdown (.md)**: header-based splitting, table & code-block integrity, 600–1200-word sizing.
- **JSON**: `RecursiveJsonSplitter` w/ `convert_lists=True`, `max_chunk_size=600`.
- **Tabular (CSV/XLSX/XLS)**: pandas-driven row chunks (≤800 chars + header), sheets as separate files, formulas stripped.

#### 4. Group Workspace Consolidation

- Unified all group document logic into `functions_documents.js`.
- Removed `functions_group_documents.js` duplication.

#### 5. Bulk File Uploads

- Support for uploading **up to 10 files** in a single operation, with parallel ingestion and processing.

#### 6. GPT-Driven Metadata Extraction

- Admins can select a **GPT model** to power metadata parsing.
- All new documents are processed through the chosen model for entity, keyword, and summary extraction.

#### 7. Advanced Document Classification

- Admin-configurable classification fields, each with **custom color-coded labels**.
- Classification metadata persisted per document for filtering and display.

#### 8. Contextual Classification Propagation

- When a classified document is referenced in chat, its tags are **automatically applied to the conversation** as contextual metadata.

#### 9. Chat UI Enhancements

- **Left-docked** conversation menu for persistent navigation.
- **Editable** conversation titles inline (left & right panes stay in sync).
- Streamlined **new chat** flow: click-to-start or type-to-auto-create.
- **User-defined prompts** surfaced inline within the message input.

#### 10. Semantic Reranking & Extractive Answers

* Switched to semantic queries (`query_type="semantic"`) on both user and group indexes. 
* Enabled extractive highlights (`query_caption="extractive"`) to surface the most relevant snippet in each hit.  
* Enabled extractive answers (`query_answer="extractive"`) so the engine returns a concise, context-rich response directly from the index.  
* Automatically falls back to full-text search (`query_type="full"`, `search_mode="all"`) whenever no literal match is found, ensuring precise retrieval of references or other exact phrases.

### Bug Fixes

#### A. AI Search Index Migration

- Automatically add any **missing** fields (e.g. `author`, `chunk_keywords`, `document_classification`, `page_number`, `start_time`, `video_ocr_chunk_text`, etc.) on every Admin page load.
- Fixed SDK usage (`Collection` attribute) to update index schema without full-index replacement.

#### B. User & Group Management

- **User search 401 error** when adding a new user to a group resolved by:
  - Implementing `SerializableTokenCache` in MSAL tied to Flask session.
  - Ensuring `_save_cache()` is called after `acquire_token_by_authorization_code`.
  - Refactoring `get_valid_access_token()` to use `acquire_token_silent()`.
- Restored **metadata extraction** & **classification** buttons in Group Workspace.
- Fixed new role language in Admin settings and published an OpenAPI spec for `/api/`.

#### C. Conversation Flow & UI

- **Auto-create** a new conversation on first user input, prompt selection or file upload.
- **Custom logo persistence** across reboots via Base64 storage in Cosmos (max 100 px height, ≤ 500 KB).
- Prevent uploaded files from **overflowing** the chat window (CSS update).
- Sync conversation title in left pane **without** manual refresh.
- Restore missing `loadConversations()` in `chat-input-actions.js`.
- Fix feedback button behavior and ensure prompt selection sends full content.
- Include original `search_query` & `user_message` in AI Search telemetry.
- Ensure existing documents no longer appear “Not Available” by populating `percent_complete`.
- Support **Unicode** (e.g. Japanese) in text-file chunking.

#### D. Miscellaneous Fixes

- **Error uploading file** (`loadConversations is not defined`) fixed.
- **Classification disabled** no longer displays in documents list or title.
- **Select prompt/upload file** now always creates a conversation if none exists.
- **Fix new categories** error by seeding missing nested settings with defaults on startup.



### Breaking Changes & Migration Notes

- **Index schema** must be re-migrated via Admin Settings (admin initiates in the app settings page).

## (v0.203.15)

The update introduces "Workspaces," allowing users and groups to store both **documents** and **custom prompts** in a shared context. A new **prompt selection** feature enhances the chat workflow for a smoother experience. Additionally, admin configuration has been streamlined, and the landing page editor now supports improved Markdown formatting.

#### 1. Renaming Documents to Workspaces

- **Your Documents** → **Your Workspace**
- **Group Documents** → **Group Workspaces**
- All references, routes, and templates updated (`documents.html` → `workspace.html`, `group_documents.html` → `group_workspaces.html`).
- New admin settings flags: `enable_user_workspace` and `enable_group_workspaces` replaced the old `enable_user_documents` / `enable_group_documents`.

#### 2. Custom Prompt Support

- User Prompts:
  - New backend routes in `route_backend_prompts.py` (CRUD for user-specific prompts).
- Group Prompts:
  - New backend routes in `route_backend_group_prompts.py` (CRUD for group-shared prompts).

#### 3. Chat Page Enhancements

- Prompt Selection Dropdown:
  - New button (“Prompts”) toggles a dropdown for selecting saved user/group prompts.
  - Eliminates copy-paste; helps users insert larger or more complex prompts quickly.
  - Lays groundwork for future workflow automation.
- **Toast Notifications** for errors and status messages (replacing browser alerts).

#### 4. Cosmos Containers

- Added `prompts_container` and `group_prompts_container`.

- **Simplified** or standardized the container creation logic in `config.py`.

## (v0.202.41)

- **Azure Government Support**:

  - Introduced an `AZURE_ENVIRONMENT` variable (e.g. `"public"` or `"usgovernment"`) and logic to handle separate authority hosts, resource managers, and credential scopes.

  ```
  # Azure Cosmos DB
  AZURE_COSMOS_ENDPOINT="<your-cosmosdb-endpoint>"
  AZURE_COSMOS_KEY="<your-cosmosdb-key>"
  AZURE_COSMOS_AUTHENTICATION_TYPE="key" # key or managed_identity
  
  # Azure Bing Search
  BING_SEARCH_ENDPOINT="https://api.bing.microsoft.com/"
  
  # Azure AD Authentication
  CLIENT_ID="<your-client-id>"
  TENANT_ID="<your-tenant-id>"
  AZURE_ENVIRONMENT="public" #public, usgovernment
  SECRET_KEY="32-characters" # Example - "YouSh0uldGener8teYour0wnSecr3tKey!", import secrets; print(secrets.token_urlsafe(32))
  ```

- **Admin Settings Overhaul**:

  - **Route & UI**: Added `route_backend_settings.py` and significantly expanded `admin_settings.html` to configure GPT, Embeddings, Image Gen, Content Safety, Web Search, AI Search, and Document Intelligence—all from a single Admin page.
  - **APIM Toggles**: Each service (GPT, Embeddings, Image Generation, Content Safety, etc.) can now be routed through Azure API Management instead of direct endpoints by switching a toggle.
  - **“Test Connection” Buttons**: Each service (GPT, Embeddings, Image Generation, Content Safety, Bing Web Search, Azure AI Search, and Document Intelligence) now has a dedicated “Test Connection” button that performs a live connectivity check.

- **Improved Safety Features**:

  - New pages/sections for “Admin Safety Violations” vs. “My Safety Violations.”

- **Miscellaneous Frontend & Template Updates**:

  - All templates now reference an `app_settings.app_title` for a dynamic page title.
  - Enhanced navigation and labeling in “My Documents,” “My Groups,” and “Profile” pages.

### Bug Fixes

- **Conversation Pipeline**:
  - Removed the `"image"` role from the allowed conversation roles to streamline message handling.
- **Group Management**:
  - Now correctly passes and references the current user’s ID in various group actions.

## (v0.201.5)

#### 1. **Managed Identity Support**

- Azure Cosmos DB (enabled/disabled via environment variable)
- Azure Document Intelligence (enabled/disabled via app settings)
- Azure AI Search (enabled/disabled via app settings)
- Azure OpenAI (enabled/disabled via app settings)

#### 2. **Conversation Archiving**

- Introduced a new setting 

  ```
  enable_conversation_archiving
  ```

  - When enabled, deleting a conversation will first copy (archive) the conversation document into an `archived_conversations_container` before removing it from the main `conversations` container.
  - Helps preserve conversation history if you want to restore or analyze it later.

#### 3. **Configuration & Environment Variable Updates**

- `example.env` & `example_advance_edit_environment_variables.json`:
  - Added `AZURE_COSMOS_AUTHENTICATION_TYPE` to demonstrate how to switch between `key`-based or `managed_identity`-based authentication.
  - Cleaned up references to Azure AI Search and Azure Document Intelligence environment variables to reduce clutter and reflect the new approach of toggling authentication modes.
- Default Settings Updates
  - `functions_settings.py` has more descriptive defaults covering GPT, Embeddings, and Image Generation for both key-based and managed identity scenarios.
  - New config fields such as `content_safety_authentication_type`, `azure_document_intelligence_authentication_type`, and `enable_conversation_archiving`.

#### 6. **Bug Fixes**

- Fixed bug affecting the ability to manage groups
  - Renamed or refactored `manage_groups.js` to `manage_group.js`, and updated the template (`manage_group.html`) to use the new filename.
  - Injected `groupId` directly via Jinja for improved client-side handling.

#### 7. **Architecture Diagram Updates**

- Updated `architecture.vsdx` and `architecture.png` to align with the new authentication flow and container usage.

------

#### How to Use / Test the New Features

1. **Enable Managed Identity**
   - In your `.env` or Azure App Service settings, set `AZURE_COSMOS_AUTHENTICATION_TYPE="managed_identity"` (and similarly for `azure_document_intelligence_authentication_type`, etc.).
   - Ensure the Azure resource (e.g., App Service, VM) has a system- or user-assigned Managed Identity with the correct roles (e.g., “Cosmos DB Account Contributor”).
   - Deploy, and the application will now connect to Azure resources without storing any keys in configuration.
2. **Test Conversation Archiving**
   - In the Admin Settings, enable `Enable Conversation Archiving`.
   - Delete a conversation.
   - Verify the record is copied to `archived_conversations_container` before being removed from the active container.
3. **Check New Environment Variables**
   - Review `example.env` and `example_advance_edit_environment_variables.json` for the newly added variables.
   - Update your application settings in Azure or your local `.env` accordingly to test various authentication modes (key vs. managed identity).

## (V0.199.3)

We introduced a robust user feedback system, expanded content-safety features for both admins and end users, added new Cosmos DB containers, and refined route-level permission toggles. These changes help administrators collect feedback on AI responses, manage content safety more seamlessly, and give end users clearer ways to manage their documents, groups, and personal logs. Enjoy the new functionality, and let us know if you have any questions or issues!

1. **New “User Feedback” System**
   - **Thumbs Up / Thumbs Down**: Users can now provide feedback on individual AI responses (when enabled in App Settings)
   - **Frontend Feedback Pages**:
     - **/my_feedback** page shows each user’s submitted feedback.
     - **/admin/feedback_review** page allows admins to review, filter, and manage all feedback.
2. **Extended Content Safety Features**
   - **New “Safety Violations” Page**: Admins can manage safety violations.
   - **New “My Safety Violations” Page**: Users can view their violations and add personal notes to each violation.
3. **New or Updated Database Containers**
   - feedback_container for user feedback.
   - archived_conversations_container / archived_feedback_container / archived_safety_container for long-term archival.
4. **Route-Level Feature Toggles**
   - **enabled_required(setting_key) Decorator**:
     - Dynamically block or allow routes based on an admin setting (e.g., enable_user_documents or enable_group_documents).
     - Reduces scattered if checks; you simply annotate the route.
5. **Conversation & Messaging Improvements**
   - **Unique message_id for Each Chat Message**:
     - Every user, assistant, safety, or image message now includes a message_id.
     - Makes it easier to tie user feedback or safety logs to a specific message.
   - **Public vs. Secret Settings**:
     - Frontend references a public_settings = sanitize_settings_for_user(settings) to avoid the potential to expose secrets on the client side.
6. **UI/UX Tweaks**
   - **Chat Layout Updates**:
     - “Start typing to create a new conversation…” message if none selected.
     - Automatic creation of new conversation when user tries to send a message with no active conversation.
   - **Navigation Bar Adjustments**:
     - Consolidated admin links into a dropdown.
     - “My Account” dropdown for quick access to “My Groups,” “My Feedback,” etc., if enabled.

## (v0.196.9)

1. **Content Safety Integration**
   - **New Safety Tab in Admin Settings**: A dedicated “Safety” section now appears under Admin Settings, allowing you to enable Azure Content Safety, configure its endpoint and key, and test connectivity.
   - **Real-Time Message Scanning**: If Content Safety is enabled, user prompts are scanned for potentially disallowed content. Blocked messages are flagged and a “safety” message is added to the conversation log in place of a normal AI reply.
   - **Admin Safety Logs**: Site admins (with “Admin” role) can view a new “Safety Violations” page (at /admin/safety_violations) showing blocked or flagged messages. Admins can update the status, action taken, or notes on each violation.
2. **Expanded APIM Support for GPT, Embeddings, and Image Generation**
   - **Fine-Grained APIM Toggles**: You can now enable or disable APIM usage independently for GPT, embeddings, and image generation. Each service has its own APIM endpoint, version, and subscription key fields in Admin Settings.
   - **UI-Driven Switching**: Check/uncheck “Enable APIM” to toggle between native Azure OpenAI endpoints or APIM-managed endpoints, all without redeploying the app.
3. **Workspaces & Documents Configuration**
   - **User Documents and Group Documents**: A new “Workspaces” tab in Admin Settings (replacing the old “Web Search” tab) lets you enable or disable user-specific documents and group-based documents.
   - **Group Documents Page**: The front-end for Group Documents now checks whether “Enable My Groups” is turned on. If enabled, members can manage shared group files and see group-level search results.
   - **My Groups & Group Management**: Navigation includes “My Groups” (if group features are enabled). This leads to a new set of pages for viewing groups, managing memberships, transferring ownership, and more.
4. **Search & Extract Tab**
   - **Azure AI Search & Document Intelligence**: Moved Bing Web Search, Azure AI Search, and Azure Document Intelligence settings into a new “Search and Extract” tab (replacing the older “Web Search” tab).
   - **Bing Search Toggle**: If you enable web search, the user can optionally include Bing results in chat queries.
   - **Azure Document Intelligence**: Configure endpoints and keys for file ingestion (OCR, form analysis, etc.) in a more structured place within Admin Settings.
5. **Updated UI & Navigation**
   - **Admin Dropdown**: Admin-specific features (App Settings, Safety Violations, etc.) are grouped in an “Admin” dropdown on the main navbar.
   - **Safety**: For Content Safety (as noted above).
   - **Search & Extract**: For Bing Search, Azure AI Search, and Document Intelligence.
   - **Minor Styling Adjustments**: Updated top navbar to show/hide “Groups” or “Documents” links based on new toggles (Enable Your Documents, Enable My Groups).

## (v0.191.0)

1. **Azure API Management (APIM) Support**  
   - **New APIM Toggles**: In the Admin Settings, you can now enable or disable APIM usage separately for GPT, embeddings, and image generation.  
   - **APIM Endpoints & Subscription Keys**: For each AI service (GPT, Embeddings, Image Generation), you can specify an APIM endpoint, version, deployment, and subscription key—allowing a unified API gateway approach (e.g., rate limiting, authentication) without changing your core service code.  
   - **Seamless Switching**: A single checkbox (`Enable APIM`) within each tab (GPT, Embeddings, Image Generation) instantly switches the app between native Azure endpoints and APIM-protected endpoints, with no redeployment required.

2. **Enhanced Admin Settings UI**  
   - **Advanced Fields**: Collapsible “Show Advanced” sections for GPT, Embeddings, and Image Generation let you configure API versions or other fine-tuning details only when needed.  
   - **Test Connectivity**: Each service tab (GPT, Embeddings, Image Gen) now has a dedicated “Test Connection” button, providing immediate feedback on whether your settings and credentials are valid.  
   - **Improved UX for Keys**: Updated show/hide password toggles for all key fields (including APIM subscription keys), making it easier to confirm you’ve entered credentials correctly.

3. **Miscellaneous Improvements**  
   - **UI Polishing**: Minor styling updates and improved tooltips in Admin Settings to guide first-time users.  
   - **Performance Tweaks**: Reduced initial load time for the Admin Settings page when large model lists are returned from the OpenAI endpoints.  
   - **Logging & Error Handling**: More descriptive error messages and client-side alerts for failed fetches (e.g., if the user tries to fetch GPT models but hasn’t set the endpoint properly).

## v0.191.0

1. **Azure API Management (APIM) Support**  
   - **New APIM Toggles**: In the Admin Settings, you can now enable or disable APIM usage separately for GPT, embeddings, and image generation.  
   - **APIM Endpoints & Subscription Keys**: For each AI service (GPT, Embeddings, Image Generation), you can specify an APIM endpoint, version, deployment, and subscription key—allowing a unified API gateway approach (e.g., rate limiting, authentication) without changing your core service code.  
   - **Seamless Switching**: A single checkbox (`Enable APIM`) within each tab (GPT, Embeddings, Image Generation) instantly switches the app between native Azure endpoints and APIM-protected endpoints, with no redeployment required.

2. **Enhanced Admin Settings UI**  
   - **Advanced Fields**: Collapsible “Show Advanced” sections for GPT, Embeddings, and Image Generation let you configure API versions or other fine-tuning details only when needed.  
   - **Test Connectivity**: Each service tab (GPT, Embeddings, Image Gen) now has a dedicated “Test Connection” button, providing immediate feedback on whether your settings and credentials are valid.  
   - **Improved UX for Keys**: Updated show/hide password toggles for all key fields (including APIM subscription keys), making it easier to confirm you’ve entered credentials correctly.

3. **Miscellaneous Improvements**  
   - **UI Polishing**: Minor styling updates and improved tooltips in Admin Settings to guide first-time users.  
   - **Performance Tweaks**: Reduced initial load time for the Admin Settings page when large model lists are returned from the OpenAI endpoints.  
   - **Logging & Error Handling**: More descriptive error messages and client-side alerts for failed fetches (e.g., if the user tries to fetch GPT models but hasn’t set the endpoint properly).

## v0.190.1

1. **Admin Settings UI**  
   - Configure Azure OpenAI GPT, Embeddings, Image Generation, and Bing Search settings directly through an in-app interface (rather than `.env`).  
   - Choose between **key-based** or **managed identity** authentication for GPT, Embeddings, and Image Generation.  
   - Dynamically switch models/deployments without redeploying the app.

2. **Multiple Roles & Group Permissions**  
   - Roles include `Owner`, `Admin`, `DocumentManager`, and `User`.  
   - Group Owners/Admins can invite or remove members, manage documents, and set “active workspace” for group-based search.

3. **One-Click Switching of Active Group**  
   - Users in multiple groups can quickly switch their active group to see group-specific documents and chat references.

4. **Ephemeral Document Upload**  
   - Upload a file for a single conversation. The file is not saved in Azure Cognitive Search; instead, it is only used for the session’s RAG context.

5. **Inline File Previews in Chat**  
   - Files attached to a conversation can be previewed directly from the chat, with text or data displayed in a pop-up.

6. **Optional Bing Web Search**  
   - Administrators can enable or disable web search. When enabled, the user can toggle “Search the Web” while chatting to incorporate Bing results.

7. **Optional Image Generation**  
   - Users can toggle an “Image” button to create images via Azure OpenAI (e.g., DALL·E) when configured in Admin Settings.

8. **App Roles & Enterprise Application**  
   - Provides a robust way to control user access at scale.  
   - Admins can assign roles to new users or entire Azure AD groups.
# Simple Chat - Features

- [Features](#features)
- [Architecture Diagram](#architecture-diagram)
- [Optional Features](#optional-features)
  - [Redis Cache](#redis-cache-azure-cache-for-redis)
  - [Content Safety](#content-safety)
  - [Your Workspaces](#your-workspaces)
  - [My Groups](#my-groups-includes-group-workspaces)
  - [User Feedback](#user-feedback)
  - [Conversation Archiving](#conversation-archiving)
  - [Video Extraction](#video-extraction-video-indexer)
  - [Audio Extraction](#audio-extraction-speech-service)
  - [Document Classification](#document-classification)
  - [Enhanced Citation](#enhanced-citation-storage-account)
  - [Metadata Extraction](#metadata-extraction)
  - [File Processing Logs](#file-processing-logs)
- [Return to Main](../README.md)

## Features

-   **Chat with AI**: Interact with an AI model based on Azure OpenAI’s GPT models.
-   **RAG with Hybrid Search**: Upload documents and perform hybrid searches (vector + keyword), retrieving relevant information from your files to augment AI responses.
-   **Document Management**: Upload, store, and manage multiple versions of documents—personal ("Your Workspace") or group-level ("Group Workspaces").
-   **Group Management**: Create and join groups to share access to group-specific documents, enabling collaboration with Role-Based Access Control (RBAC).
-   **Ephemeral (Single-Convo) Documents**: Upload temporary documents available only during the current chat session, without persistent storage in Azure AI Search.
-   **Conversation Archiving (Optional)**: Retain copies of user conversations—even after deletion from the UI—in a dedicated Cosmos DB container for audit, compliance, or legal requirements.
-   **Content Safety (Optional)**: Integrate Azure AI Content Safety to review every user message *before* it reaches AI models, search indexes, or image generation services. Enforce custom filters and compliance policies, with an optional `SafetyAdmin` role for viewing violations.
-   **Feedback System (Optional)**: Allow users to rate AI responses (thumbs up/down) and provide contextual comments on negative feedback. Includes user and admin dashboards, governed by an optional `FeedbackAdmin` role.
-   **Image Generation (Optional)**: Enable on-demand image creation using Azure OpenAI's DALL-E models, controlled via Admin Settings.
-   **Video Extraction (Optional)**: Utilize Azure Video Indexer to transcribe speech and perform Optical Character Recognition (OCR) on video frames. Segments are timestamp-chunked for precise retrieval and enhanced citations linking back to the video timecode.
-   **Audio Extraction (Optional)**: Leverage Azure Speech Service to transcribe audio files into timestamped text chunks, making audio content searchable and enabling enhanced citations linked to audio timecodes.
-   **Document Classification (Optional)**: Admins define custom classification types and associated colors. Users tag uploaded documents with these labels, which flow through to AI conversations, providing lineage and insight into data sensitivity or type.
-   **Enhanced Citation (Optional)**: Store processed, chunked files in Azure Storage (organized into user- and document-scoped folders). Display interactive citations in the UI—showing page numbers or timestamps—that link directly to the source document preview.
-   **Metadata Extraction (Optional)**: Apply an AI model (configurable GPT model via Admin Settings) to automatically generate keywords, two-sentence summaries, and infer author/date for uploaded documents. Allows manual override for richer search context.
-   **File Processing Logs (Optional)**: Enable verbose logging for all ingestion pipelines (workspaces and ephemeral chat uploads) to aid in debugging, monitoring, and auditing file processing steps.
-   **Redis Cache (Optional)**: Integrate Azure Cache for Redis to provide a distributed, high-performance session store. This enables true horizontal scaling and high availability by decoupling user sessions from individual app instances.
-   **Authentication & RBAC**: Secure access via Azure Active Directory (Entra ID) using MSAL. Supports Managed Identities for Azure service authentication, group-based controls, and custom application roles (`Admin`, `User`, `CreateGroup`, `SafetyAdmin`, `FeedbackAdmin`).
-   **Backend Services**:
    -   **Azure Cosmos DB**: Stores conversations, document metadata, user/group information, settings, and optionally archived chats and feedback.
    -   **Azure AI Search**: Powers efficient hybrid search and retrieval over personal and group documents.
    -   **Azure AI Document Intelligence**: Extracts text, layout, and structured data from PDFs, Office files, images, and more during ingestion.
    -   **Azure Cache for Redis**: (Optional) Provides a distributed cache for session data, enabling seamless scaling and improved reliability.

-   **Supported File Types**:
    -   Text: `txt`, `md`, `html`, `json`
    *   Documents: `pdf`, `docx`, `pptx`, `xlsx`, `xls`, `csv`
    *   Images: `jpg`, `jpeg`, `png`, `bmp`, `tiff`, `tif`, `heif` (processed via Document Intelligence OCR)
    *   Video: `mp4`, `mov`, `avi`, `wmv`, `mkv`, `webm` (requires Video Indexer)
    *   Audio: `mp3`, `wav`, `ogg`, `aac`, `flac`, `m4a` (requires Speech Service)

## Architecture Diagram

> <a href="#simple-chat---features" style="text-decoration: none;">Return to top</a>

![Architecture](./images/architecture.png)

## Optional Features

> <a href="#simple-chat---features" style="text-decoration: none;">Return to top</a>

### **Redis Cache (Azure Cache for Redis)**

Enabling Redis Cache provides a distributed, high-performance session store for the application. This is essential for supporting horizontal scaling (scale out) and high availability in enterprise deployments. By storing user session data in Redis, all app instances can access and update sessions consistently, eliminating issues with session stickiness and enabling seamless load balancing.

-   **Enables true horizontal scaling** by decoupling user sessions from individual app instances.
-   **Improves reliability and availability** by providing a central, resilient cache for session data.
-   **Reduces login issues** (such as infinite login loops) when running multiple app instances behind a load balancer.
-   **Supports high concurrency** and fast session access, critical for large user bases.
-   **Configurable authentication**: Supports Access Keys or Entra ID (Managed Identity) for secure access.

> **When to enable:** Enable Redis Cache if you plan to scale out the application to multiple App Service instances, require high availability, or want to future-proof your deployment for enterprise workloads.

### **Content Safety**

Ensures governance and security by reviewing all user messages before they interact with any service, including AI models, document search, web search, and image generation. This feature allows organizations to enforce custom filters and compliance policies, mitigating risks associated with harmful content or policy violations while maintaining a safe and controlled user experience.

-   **Prevents inappropriate content** from being processed, generated, or retrieved.
-   **Aids compliance** with organizational policies, industry regulations, and responsible AI principles.
-   **Enhances security** by filtering potentially malicious or sensitive queries before they interact with external systems or internal data.
-   **Optional RBAC** (`SafetyAdmin` App Role) restricts access to the Safety Violation Admin View, allowing designated personnel to review flagged content.

| ![Content Safety - Settings](./images/content_safety-settings.png) | ![Content Safety - In Action](./images/content_safety-in_action.png) | ![Content Safety - Cosmos Container](./images/content_safety-cosmos_container.png) |
| ------------------------------------------------------------ | ------------------------------------------------------------ | ------------------------------------------------------------ |
| ![Content Safety - Management](./images/content_safety-management.png) | ![Content Safety - Taking Action](./images/content_safety-taking_action.png) | ![Content Safety - User View](./images/content_safety-user_view.png) |

### **Your Workspaces**

**Your Workspace** enhances individual productivity by allowing users to upload, manage, and utilize their personal documents as context for Azure OpenAI. It centralizes important files and prompts, eliminating repetitive uploads and copy-pasting. When enabled, the AI can reference these documents, leading to more relevant, personalized, and contextually accurate responses for tasks like summarizing reports, drafting emails, or brainstorming.

-   **Centralized hub** for personal documents and frequently used prompts, making them easily accessible.
-   **Improved AI context** by enabling Azure OpenAI to "see" user-specific documents, resulting in tailored and accurate responses.
-   **Time-saving** by storing crucial information once for repeated use across multiple chat sessions.

| ![Admin Settings - Enable Workspace](./images/admin_settings-enable_workspace.png) | ![Workspace - Document List](./images/workspace-doc_list.png) |
| ------------------------------------------------------------ | ------------------------------------------------------------ |
| ![Workspace - Prompt list](./images/workspace-prompt_list.png) | ![Workspace - Edit Prompt](./images/workspace-prompt_edit.png) |

### **My Groups (includes Group Workspaces)**

Facilitates teamwork by enabling users to create or join groups where documents and prompts can be shared securely. This creates a shared knowledge base, ensuring team members are aligned and can leverage the same information for AI-driven tasks. It reduces redundant explanations and email chains, allowing teams to collaborate efficiently and obtain consistent, AI-generated insights based on collective resources.

-   **Shared knowledge base** ensures team alignment with up-to-date, common resources.
-   **Streamlined collaboration** on documents and prompts, reducing repetitive tasks and communication overhead.
-   **Consistent AI responses** across the team by referencing identical data and prompt sets, minimizing misinformation.
-   **Optional RBAC** (`CreateGroup` App Role) can be enforced to control which users have permission to create new groups.

| ![Admin Settings - Enable Groups](./images/admin_settings-enable_groups.png) | ![App Registration - App Role - Create Group](./images/app_reg-app_role-create_group.png) | ![Enterprise App - Add user to Create Group role](./images/enterprise_app-add_user_to_role.png) |
| ------------------------------------------------------------ | ------------------------------------------------------------ | ------------------------------------------------------------ |
| ![My Groups - Group list](./images/my_groups-group_list.png) | ![My Groups - Find group - Request to join](./images/my_groups-find_group-request_to_join.png) | ![Manage Group - Group details as owner](./images/manage_group-group_details_as_owner.png) |
| ![Manage Group - Add member](./images/manage_group-add_member.png) | ![Manage Group - Assign member role](./images/manage_group-update_member_role.png) | ![Group Workspace - Document list](./images/group_workspace-doc_list.png) |

### **User Feedback**

Provides a mechanism for end-users to offer direct feedback on the quality and relevance of AI-generated responses. This feedback loop is crucial for monitoring model performance, identifying areas for improvement, and understanding user satisfaction.

-   **Simple rating system** (Thumbs up/down) for quick assessment of AI replies.
-   **Contextual comments** prompted upon a thumbs-down selection, allowing users to specify issues.
-   **User dashboard** for individuals to review their submitted feedback history.
-   **Admin dashboard** for aggregating, reviewing, and acting upon feedback. Access is controlled by **Optional RBAC** (`FeedbackAdmin` App Role).

| ![Admin Settings - Enable User Feedback](./images/admin_settings-enable_user_feedback.png) | ![Chat - Negative Feedback](./images/chat-feedback-negative.png) | ![Feedback Review - List all](./images/feedback_review-list_all.png) |
| ------------------------------------------------------------ | ------------------------------------------------------------ | ------------------------------------------------------------ |
| ![Feedback Review - Feedback review workflow](./images/feedback_review-workflow.png) | ![My feedback - List all](./images/my_feedback-list_all.png) | ![My feedback - View specific](./images/my_feedback-view_specific.png) |

### **Conversation Archiving**

Addresses compliance and record-keeping needs by automatically retaining a copy of all user conversations in a separate Cosmos DB container, even if users delete them from their chat history interface.

-   **Dedicated archive container** in Cosmos DB ensures separation from live conversation data.
-   **Post-deletion retention** guarantees that chats removed from the user history remain available for audit or legal discovery.
-   **Supports policy compliance** for regulatory, legal, or internal organizational record-keeping requirements.

| ![Admin Settings - Enable Conversation Archiving](./images/admin_settings-enable_conversation_archiving.png) | ![Chat - Delete conversation](./images/chat-delete_conversation.png) |
| ------------------------------------------------------------ | ------------------------------------------------------------ |
| ![Cosmos container - View archived conversation](./images/cosmos_container-view_archived_conversation.png) | ![Cosmos container - View archived messages](./images/cosmos_container-view_archived_messages.png) |

### **Video Extraction (Video Indexer)**

Unlocks the value within video files by using Azure Video Indexer to transcribe spoken words and extract text visible on screen (OCR). This makes video content searchable and citable within the chat application.

-   **Comprehensive text extraction** from both audio tracks (transcription) and visual elements (OCR).
-   **Timestamp-based chunking** segments the extracted text, tagging each chunk with its start time in the video for precise retrieval.
-   **Enhanced citations** in chat responses link directly to the specific time point in the video source.
-   **Integrates seamlessly** with the application's document storage, search, and citation workflow.

| ![Admin settings - Enable Video file support](./images/admin_settings-enable_video_file_support.png) | ![Workspace - Upload and process video file](./images/workflow-upload_video_file.png) |
| ------------------------------------------------------------ | ------------------------------------------------------------ |

### **Audio Extraction (Speech Service)**

Leverages Azure Speech Service to automatically transcribe audio files, converting spoken content into searchable and citable text.

-   **Accurate transcription** of various uploaded audio formats.
-   **Timestamped text chunks** enable precise linking of citations back to the specific moment in the audio file.
-   **Enhanced citation support** allows users to click a citation and potentially jump to (or reference) the relevant audio timestamp.

| ![Admin settings - Enable audio file support](./images/admin_settings-enable_audio_file_support.png) | ![Workspace - Upload and process audio file](./images/workflow-upload_process_audio_file.png) |
| ------------------------------------------------------------ | ------------------------------------------------------------ |

### **Document Classification**

Allows organizations to categorize documents based on sensitivity, type, or other criteria defined by administrators. These classifications persist throughout the application, providing context and aiding governance.

-   **Admin-defined classification types** with customizable labels and visual color-coding.
-   **User-assigned labels** applied during the document upload process.
-   **Classification propagation** ensures that tags associated with referenced documents appear in the chat context, indicating the nature of the source data.
-   **Improved insights** into how different types of documents are being used and referenced in AI interactions.

| ![Admin settings - Enable and configure Document classification](./images/admin_settings-enable_and_configure_doc_classification.png) | ![Workspace - View and update classification](./images/workflow-view_and_update_classification.png) | ![Chat - Classification propagation](./images/chat-classification_propagation.png) |
| ------------------------------------------------------------ | ------------------------------------------------------------ | ------------------------------------------------------------ |

### **Enhanced Citation (Storage Account)**

Provides a richer citation experience by storing processed document chunks in Azure Storage and enabling interactive citations that link directly to the source content (e.g., specific page or timestamp).

-   **Structured Azure Storage**: Organizes processed files into user-specific and document-specific folders.
-   **Metadata linkage**: Connects files in Azure Storage with their corresponding document records in Cosmos DB.
-   **Rich UI citations**: Displays page numbers (for documents) or timestamps (for video/audio) alongside document previews within the chat interface.
-   **Direct navigation**: Allows users to click citations to view the original content source, improving transparency and trust.

### **Metadata Extraction**

Uses AI (a configurable GPT model) to automatically enrich uploaded documents with relevant metadata, improving search relevance and providing better context for AI responses.

-   **Configurable AI model**: Administrators select the GPT model used for extraction via Admin Settings.
-   **Automated generation**: Extracts keywords, creates concise two-sentence summaries, and infers potential author and creation dates.
-   **Improved searchability**: Generated metadata enhances the information available to Azure AI Search, leading to more relevant results.
-   **Manual override**: Users can manually edit or provide their own metadata if the AI-generated content needs correction or refinement.

| ![Admin settings - Enable Enhanced citations](./images/admin_settings-enable_enhanced_citations.png) | ![Workspace - Enhanced citation tag](./images/workspace-enhanced_citation_tag.png) | ![Storage account - View documents for citation retrieval](./images/storage_account-view_doc_for_citation_retrieval.png) |
| ------------------------------------------------------------ | ------------------------------------------------------------ | ------------------------------------------------------------ |

### **File Processing Logs**

Enables detailed logging for the entire file ingestion and processing pipeline, assisting administrators and developers in troubleshooting issues, monitoring performance, and auditing activity.

-   **Granular logging**: Captures step-by-step details of document ingestion, chunking, embedding, and indexing processes.
-   **Error diagnostics**: Helps pinpoint failures or bottlenecks in the ingestion or AI-driven extraction steps.
-   **Admin control**: Verbosity can be toggled on or off via Admin Settings, allowing control over logging volume.

| ![Admin settings - Enable File processing logs](./images/admin_settings-enable_file_processing_logs.png) | ![Cosmos container - View specific document's file processing logs](./images/cosmos_container-view_specific_doc_file_processing_logs.png) |
| ------------------------------------------------------------ | ------------------------------------------------------------ |

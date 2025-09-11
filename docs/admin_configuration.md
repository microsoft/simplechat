# Simple Chat - Admin Configuration

[Return to Main](../README.md)


Once the application is running and you log in as a user assigned the Admin role, you can access the **Admin Settings** page. This UI provides a centralized location to configure most application features and service connections.

![alt text](./images/admin_settings_page.png)

Key configuration sections include:

1. **General**: Application title, custom logo upload, landing page markdown text.
2. **GPT**: Configure Azure OpenAI endpoint(s) for chat models. Supports Direct endpoint or APIM. Allows Key or Managed Identity authentication. Test connection button. Select active deployment(s).
   1. Setting up Multi-model selection for users
3. **Embeddings**: Configure Azure OpenAI endpoint(s) for embedding models. Supports Direct/APIM, Key/Managed Identity. Test connection. Select active deployment.
4. **Image Generation** *(Optional)*: Enable/disable feature. Configure Azure OpenAI DALL-E endpoint. Supports Direct/APIM, Key/Managed Identity. Test connection. Select active deployment.
5. **Workspaces**:
   - Enable/disable **Your Workspace** (personal docs).
   - Enable/disable **My Groups** (group docs). Option to enforce `CreateGroups` RBAC role for creating new groups.
   - Enable/disable **Multimedia Support** (Video/Audio uploads). Configure **Video Indexer** (Account ID, Location, Key, API Endpoint, Timeout) and **Speech Service** (Endpoint, Region, Key).
   - Enable/disable **Metadata Extraction**. Select the GPT model used for extraction.
   - Enable/disable **Document Classification**. Define classification labels and colors.
6. **Citations**:
   - Standard Citations (basic text references) are always on.
   - Enable/disable **Enhanced Citations**. Configure **Azure Storage Account Connection String** (or indicate Managed Identity use if applicable).
7. **Safety**:
   - Enable/disable **Content Safety**. Configure endpoint (Direct/APIM), Key/Managed Identity. Test connection.
   - Enable/disable **User Feedback**.
   - Configure **Admin Access RBAC**: Option to require `SafetyViolationAdmin` or `FeedbackAdmin` roles for respective admin views.
   - Enable/disable **Conversation Archiving**.
8. **Search & Extract**:
   - Configure **Azure AI Search** connection (Endpoint, Key/Managed Identity). Test connection. (Primarily for testing, main indexing uses backend logic).
   - Configure **Document Intelligence** connection (Endpoint, Key/Managed Identity). Test connection.
9. **Other**:
   - Set **Maximum File Size** for uploads (in MB).
   - Set **Conversation History Limit** (max number of past conversations displayed).
   - Define the **Default System Prompt** used for the AI model.
   - Enable/disable **File Processing Logs** (verbose logging for ingestion pipelines).

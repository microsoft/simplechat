# Simple Chat - FAQ's

[Return to Main](../README.md)

## Q: We've put Simple Chat behind a firewall (like Azure Firewall or a WAF), and some features (like search, document upload, or admin settings updates) don't work. What's wrong?

   - **A:** The application consists of a frontend (served to the browser) and a backend API running on the App Service. The frontend makes JavaScript calls to this backend API (e.g., /api/conversation, /api/documents, /api/config). Firewalls or Web Application Firewalls (WAFs) might block these API requests if not configured correctly.

     - **Solution**: Review your firewall/WAF rules. Ensure that HTTP GET, POST, PUT, PATCH, DELETE requests from user browsers to your App Service URL (e.g., https://<your-app-service-name>.azurewebsites.net/api/*) are allowed. Refer to the OpenAPI specification provided in the repository (artifacts/open_api/openapi.yaml) for a detailed list of API endpoints used by the application. You may need to create specific rules to allow traffic to these paths. 

     ```
     📁 SimpleChat
          └── 📁 artifacts
              └── 📁 open_api
                  ├── openapi.yaml
     ```

## Q: Users are getting authentication errors or cannot log in.

   - **A:** Check the following:
     - **App Registration**: Is the Redirect URI (.../.auth/login/aad/callback) correctly configured in the Azure AD App Registration?
     - **App Service Authentication**: Is Authentication turned on in the App Service, linked to the correct App Registration, and set to "Require authentication"? Is the Issuer URL correct?
     - **Enterprise Application**: Are users or groups correctly assigned to the application in **Enterprise Applications > Users and groups**? If "User assignment required" is enabled on the Enterprise App, only assigned users/groups can log in.
     - **API Permissions**: Have the required Microsoft Graph permissions (`User.Read`, `openid`, `profile`, etc., and potentially `People.Read.All` for groups) been added *and* granted admin consent in the App Registration?
     - **Tenant ID/Client ID**: Are the `TENANT_ID` and `CLIENT_ID` values in the App Service Application Settings correct?

## Q: File uploads are failing.

   - **A:** Possible causes:
     - **Permissions**: Does the App Service have permissions to write to Azure AI Search (if indexing), Document Intelligence (for processing), Speech/Video Indexer (if applicable), and Azure Storage (if using Enhanced Citations)? Check IAM roles, especially if using Managed Identity. If using keys, ensure they are correct in Admin Settings/App Settings.
     - **Service Issues**: Check the status of dependent Azure services (Document Intelligence, AI Search, OpenAI Embeddings).
     - **App Service Logs**: Enable and check Application Insights and App Service Logs (Diagnose and solve problems -> Application Logs) for specific error messages from the backend.
     - **File Processing Logs**: Enable verbose File Processing Logs in Admin Settings > Other for detailed ingestion pipeline steps.

## Q: Document search (RAG) isn't returning expected results or any results.

   - **A:** Possible causes:
     - **Indexing Status**: Check if the documents were successfully uploaded and processed. Look at the document status in "Your Workspace" or "Group Workspaces". Check File Processing Logs if enabled.
     - **Azure AI Search**: Go to the Azure AI Search resource in the portal. Check the simplechat-user-index or simplechat-group-index. Do they contain documents? Are the document counts increasing after uploads? Use the Search explorer tool in the portal to test queries directly against the index.
     - **Embedding Model**: Is the Embedding model configured correctly in Admin Settings and reachable? Errors during embedding will prevent indexing.
     - **Search Query**: The quality of the search query matters. Ensure the "Search Documents" toggle is enabled in the chat UI. Try rephrasing your question.

## Q: How do I update the AI models (GPT, Embedding, DALL-E) used by the application?

   - **A:** Go to **Admin Settings**. Navigate to the relevant section (**GPT**, **Embeddings**, **Image Generation**). Use the interface to fetch available deployments from your configured Azure OpenAI endpoint(s) and select the desired deployment name(s). Save the settings. You don't need to redeploy the application code to change models if the endpoint remains the same.

## Q: Can I use Azure OpenAI endpoints secured with Private Endpoints?

   - **A:** Yes, but it requires network integration. The App Service must be integrated with a Virtual Network (VNet) that has connectivity to the private endpoints of your Azure services (OpenAI, Search, Cosmos DB, etc.). This typically involves using App Service VNet Integration and configuring Private DNS Zones or custom DNS. Ensure the App Service's outbound traffic can resolve and reach the private endpoint IPs.

## Q: “Fetch Models” fails if my authentication app registration is in a different Azure AD tenant than my Azure OpenAI resource. What’s happening and how can I work around it?

   - **A:** Because your app registration (the “management-plane” identity) lives in Tenant B but your Azure OpenAI resource is in Tenant A, cross-tenant listing of deployed models is blocked by default. Data-plane calls (completions via managed identity) still work, but management-plane operations (model enumeration) will return a 403.
   - **Workaround:**
     1. In **Admin Settings → GPT**, enable **Use APIM instead of direct to Azure OpenAI endpoint**.
     2. In the APIM fields, enter your **Azure OpenAI endpoint** URL, API version, and deployment name (instead of an actual APIM proxy).
     3. Save and re-fetch models.
         This causes the app to call the AOAI endpoint through the APIM-mode flow, bypassing the cross-tenant management-plane check and allowing model listing to succeed.

   ![Cross-tenant Model Support](./images/cross_tenant-model_support.png)

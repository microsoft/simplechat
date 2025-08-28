![logo](./docs/images/logo-wide.png)

# Overview

The **Simple Chat Application** is a comprehensive, web-based platform designed to facilitate secure and context-aware interactions with generative AI models, specifically leveraging **Azure OpenAI**. Its central feature is **Retrieval-Augmented Generation (RAG)**, which significantly enhances AI interactions by allowing users to ground conversations in their own data. Users can upload personal ("Your Workspace") or shared group ("Group Workspaces") documents, which are processed using **Azure AI Document Intelligence**, chunked intelligently based on content type, vectorized via **Azure OpenAI Embeddings**, and indexed into **Azure AI Search** for efficient hybrid retrieval (semantic + keyword).

Built with modularity in mind, the application offers a suite of powerful **optional features** that can be enabled via administrative settings. These include integrating **Azure AI Content Safety** for governance, enabling **Bing Web Search** for real-time data, providing **Image Generation** capabilities (DALL-E), processing **Video** (via Azure Video Indexer) and **Audio** (via Azure Speech Service) files for RAG, implementing **Document Classification** schemes, collecting **User Feedback**, enabling **Conversation Archiving** for compliance, extracting **AI-driven Metadata**, and offering **Enhanced Citations** linked directly to source documents stored in Azure Storage.

The application utilizes **Azure Cosmos DB** for storing conversations, metadata, and settings, and is secured using **Azure Active Directory (Entra ID)** for authentication and fine-grained Role-Based Access Control (RBAC) via App Roles. Designed for enterprise use, it runs reliably on **Azure App Service** and supports deployment in both **Azure Commercial** and **Azure Government** cloud environments, offering a versatile tool for knowledge discovery, content generation, and collaborative AI-powered tasks within a secure, customizable, and Azure-native framework.

## Table of Contents

- [Features](./docs/features.md)
  - [Application Features](./docs/features.md#features)
  - [Architecture Diagram](./docs/features.md#architecture-diagram)
  - [Optional Features](./docs/features.md#optional-features) 
- [Release Notes](./RELEASE_NOTES.md)
- [Roadmap (as of 8/20/25)](https://github.com/microsoft/simplechat/discussions/133)
- [Application Workflow](./docs/application_workflows.md)
  - [Content Safety](./docs/application_workflows.md#content-safety---workflow)
  - [Add your data (RAG Ingestion)](./docs/application_workflows.md#add-your-data)
- [Demos](./docs/demos.md)
  - [Upload document and review metadata](./docs/demos.md#upload-document-and-review-metadata)
  - [Classify document and chat with content](./docs/demos.md#classify-document-and-chat-with-content)
- [Setup Instructions](./docs/setup_instructions.md)
  - [AzureCLI with Powershell](./docs/setup_instructions.md#option-1-azure-cli-with-powershell)
  - [Bicep](./docs/setup_instructions.md#option-2-bicep)
  - [Terraform](./docs/setup_instructions.md#option-3-hashicorp-terraform)
  - [Special Cases](./docs/setup_instructions_special.md)
    - [Azure Government Configuration](./docs/setup_instructions_special.md#azure-government-configuration)
    - [How to use Managed Identity](./docs/setup_instructions_special.md#how-to-use-managed-identity)
    - [Enterprise Networking](./docs/setup_instructions_special.md#enterprise-networking)
  

- [Admin Configuration](./docs/admin_configuration.md)
- [Application Scaling](./docs/application_scaling.md)
  - [Azure App Service](./docs/application_scaling.md#azure-app-service)
  - [Azure Cosmos DB](./docs/application_scaling.md#azure-cosmos-db)
  - [Azure AI Search](./docs/application_scaling.md#azure-ai-search)
  - [Azure AI / Cognitive Services](./docs/application_scaling.md#azure-ai--cognitive-services-openai-document-intelligence-etc)
- [FAQs](./docs/faqs.md)
- [External Apps Overview](./docs/external_apps_overview.md)
  - [Bulk uploader utility](./docs/external_apps_overview.md#bulk-uploader-utility)
  - [Database seeder utility](./docs/external_apps_overview.md#database-seeder-utility)
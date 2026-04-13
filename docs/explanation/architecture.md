---
layout: showcase-page
title: "Architecture"
permalink: /explanation/architecture/
menubar: docs_menu
accent: slate
eyebrow: "Explanation"
description: "Understand the major platform layers in Simple Chat and how data, AI services, identity, and operations interact."
hero_icons: ["bi-diagram-3", "bi-hdd-network", "bi-cpu"]
hero_pills: ["Application, data, and AI layers", "Security and scale concerns", "Azure-native service composition"]
hero_links: [{ label: "Explanation index", url: "/explanation/", style: "primary" }, { label: "Design principles", url: "/explanation/design_principles/", style: "secondary" }]
order: 110
category: Explanation
---

Architecture matters here because Simple Chat is not just a chat frontend. It is a coordinated application layer over identity, search, storage, retrieval, and optional AI services.

<section class="latest-release-card-grid">
    <article class="latest-release-card">
        <div class="latest-release-card-icon"><i class="bi bi-window-stack"></i></div>
        <h2>Application tier</h2>
        <p>Azure App Service hosts the Flask application, owns the request flow, and orchestrates conversations, uploads, configuration, and service integration.</p>
    </article>
    <article class="latest-release-card">
        <div class="latest-release-card-icon"><i class="bi bi-database"></i></div>
        <h2>Data plane</h2>
        <p>Cosmos DB stores application metadata and history while Azure AI Search stores the retrieval layer that grounded chat depends on.</p>
    </article>
    <article class="latest-release-card">
        <div class="latest-release-card-icon"><i class="bi bi-stars"></i></div>
        <h2>AI services</h2>
        <p>Azure OpenAI, Document Intelligence, Speech, Video Indexer, and Content Safety can be combined based on which feature packs the deployment enables.</p>
    </article>
    <article class="latest-release-card">
        <div class="latest-release-card-icon"><i class="bi bi-shield-check"></i></div>
        <h2>Security and operations</h2>
        <p>Identity, private networking, monitoring, autoscale, and role separation are first-order parts of the design rather than optional polish.</p>
    </article>
</section>

<div class="latest-release-note-panel">
    <h2>How to read this page</h2>
    <p>Start with the high-level diagram, then move into the component and data-flow sections. That order mirrors how most production questions appear: first where a responsibility lives, then how requests and documents move across the system.</p>
</div>


This document explains the overall architecture, design principles, and key concepts behind Simple Chat. Understanding these foundations will help you make informed decisions about deployment, configuration, and usage.

## System Overview

Simple Chat is built as a modern, cloud-native application leveraging Azure's AI and data services to provide Retrieval-Augmented Generation (RAG) capabilities with enterprise-grade security and scalability.

### Core Principles

**Security-First Design**
- Azure Active Directory integration for authentication
- Role-based access control (RBAC) for authorization
- Azure Managed Identity for service-to-service communication
- Private networking support for enterprise deployments

**Scalable Architecture**
- Stateless application design with external session storage
- Horizontal scaling support across multiple App Service instances
- Configurable autoscaling for variable workloads
- Distributed caching with Azure Redis Cache

**Extensible Framework**
- Modular feature architecture with optional components
- Admin-configurable settings for all major features
- Plugin-style integration for additional AI services
- API-first design for custom integrations

## High-Level Architecture

```
┌─────────────┐    ┌──────────────┐    ┌─────────────────┐
│   Users     │───▶│ Azure AD     │───▶│ Simple Chat     │
│ (Browsers)  │    │ (Auth)       │    │ (App Service)   │
└─────────────┘    └──────────────┘    └─────────────────┘
                                                │
                   ┌─────────────────────────────┼─────────────────────────────┐
                   │                             ▼                             │
                   │        ┌─────────────────────────────────────┐           │
                   │        │          Data Layer                 │           │
                   │        │                                     │           │
                   │        │  ┌─────────────┐ ┌──────────────┐  │           │
                   │        │  │ Cosmos DB   │ │ AI Search    │  │           │
                   │        │  │(Metadata)   │ │(Documents)   │  │           │
                   │        │  └─────────────┘ └──────────────┘  │           │
                   │        └─────────────────────────────────────┘           │
                   │                                                          │
                   │        ┌─────────────────────────────────────┐           │
                   │        │           AI Services               │           │
                   │        │                                     │           │
                   │        │ ┌───────────┐ ┌─────────────────┐   │           │
                   │        │ │Azure      │ │ Document        │   │           │
                   │        │ │OpenAI     │ │ Intelligence    │   │           │
                   │        │ └───────────┘ └─────────────────┘   │           │
                   │        │                                     │           │
                   │        │ ┌───────────┐ ┌─────────────────┐   │           │
                   │        │ │Content    │ │ Other AI        │   │           │
                   │        │ │Safety     │ │ Services        │   │           │
                   │        │ └───────────┘ └─────────────────┘   │           │
                   │        └─────────────────────────────────────┘           │
                   └────────────────────────────────────────────────────────────┘
```

## Core Components

### Application Tier

**Azure App Service**
- **Purpose**: Hosts the Python web application
- **Technology**: Flask-based web framework
- **Scaling**: Horizontal scaling with session state externalization
- **Security**: Integrated with Azure AD, supports Managed Identity

**Key Responsibilities:**
- User interface rendering and interaction handling
- Business logic orchestration
- API endpoint management
- Authentication and authorization enforcement
- Integration with Azure AI services

### Data Layer

**Azure Cosmos DB**
- **Purpose**: Primary data store for application metadata
- **Data Model**: Document-based JSON storage
- **Containers**: Conversations, documents, users, groups, settings
- **Scaling**: Request Unit (RU) based autoscaling
- **Consistency**: Session consistency for user interactions

**Stored Data Types:**
- Conversation history and metadata
- Document metadata and processing status
- User preferences and group memberships
- Application configuration settings
- Feedback and audit logs

**Azure AI Search**
- **Purpose**: Document content indexing and retrieval
- **Technology**: Hybrid search (vector + keyword)
- **Indexes**: Separate indexes for personal and group documents
- **Scaling**: Search units (replicas + partitions)
- **Features**: Semantic search, custom ranking, faceted search

**Search Index Structure:**
- Document chunks with embeddings
- Metadata fields for filtering
- User and group access controls
- Classification and tagging information

**Azure Storage Account** (Enhanced Citations)
- **Purpose**: Stores processed document files for direct access
- **Organization**: User-scoped and document-scoped folders
- **Access**: Private with time-limited SAS tokens
- **Integration**: Links citations to original document pages/timestamps

### AI Services Layer

**Azure OpenAI**
- **Chat Models**: GPT-4, GPT-3.5-turbo for conversational AI
- **Embedding Models**: text-embedding-ada-002, text-embedding-3 variants
- **Image Generation**: DALL-E models for image creation
- **Integration**: Both direct endpoints and API Management support

**Azure AI Document Intelligence**
- **Purpose**: Extract text and structure from uploaded documents
- **Capabilities**: OCR, layout analysis, table extraction
- **File Types**: PDF, Office documents, images
- **Integration**: Async processing with status tracking

**Azure AI Content Safety**
- **Purpose**: Content moderation and safety filtering
- **Categories**: Hate, sexual, violence, self-harm detection
- **Custom Lists**: Organization-specific blocked terms
- **Integration**: Pre-processing filter for all user inputs

**Additional AI Services:**
- **Speech Service**: Audio file transcription
- **Video Indexer**: Video content analysis and transcription
- **Custom AI Models**: Integration points for specialized models

## Data Flow and Processing

### Document Ingestion Workflow

```
User Upload ─┐
             ├─▶ Document Intelligence ─┐
File Types   ┘                           ├─▶ Text Extraction
                                         │
Audio Files ─────▶ Speech Service ──────┘
                                         │
Video Files ─────▶ Video Indexer ───────┘
                                         │
                                         ▼
                              ┌─────────────────┐
                              │ Content Chunking │
                              │ & Vectorization │
                              └─────────────────┘
                                         │
                                         ▼
                              ┌─────────────────┐
                              │    Storage      │
                              │ ┌─────────────┐ │
                              │ │ Cosmos DB   │ │ ◄─── Metadata
                              │ │ (Metadata)  │ │
                              │ └─────────────┘ │
                              │ ┌─────────────┐ │
                              │ │ AI Search   │ │ ◄─── Content + Embeddings
                              │ │ (Content)   │ │
                              │ └─────────────┘ │
                              │ ┌─────────────┐ │
                              │ │ Storage     │ │ ◄─── Processed Files
                              │ │ (Files)     │ │      (Enhanced Citations)
                              │ └─────────────┘ │
                              └─────────────────┘
```

### Chat Processing Workflow

```
User Message ─┐
              │
              ▼
    ┌─────────────────┐
    │ Content Safety  │ ◄─── Optional pre-processing filter
    │   Filtering     │
    └─────────────────┘
              │
              ▼
    ┌─────────────────┐
    │   RAG Query     │
    │   Processing    │
    └─────────────────┘
              │
              ├─▶ AI Search ────┐
              │                 │
              ▼                 ▼
    ┌─────────────────┐  ┌─────────────────┐
    │  Document       │  │   Relevant      │
    │  Retrieval      │  │   Context       │
    └─────────────────┘  └─────────────────┘
              │                 │
              └─────────┬───────┘
                        │
                        ▼
              ┌─────────────────┐
              │  Azure OpenAI   │
              │  Generation     │
              └─────────────────┘
                        │
                        ▼
              ┌─────────────────┐
              │   Response      │
              │ + Citations     │
              └─────────────────┘
```

## Security Architecture

### Authentication & Authorization

**Azure Active Directory Integration**
- **Identity Provider**: Centralized identity management
- **Authentication Flow**: OAuth 2.0/OpenID Connect
- **Multi-tenancy**: Support for multiple Azure AD tenants
- **Device Security**: Conditional access policy support

**Role-Based Access Control (RBAC)**
```
Application Roles:
├── Admin
│   └── Full system configuration access
├── User  
│   └── Basic chat and document access
├── CreateGroups
│   └── Permission to create new groups
├── SafetyViolationAdmin
│   └── View and manage content safety violations
└── FeedbackAdmin
    └── Access user feedback and analytics
```

**Data Access Control**
- **Personal Workspaces**: User-scoped document access
- **Group Workspaces**: Role-based group membership
- **Document Permissions**: Fine-grained access controls
- **Search Isolation**: User/group-aware search results

### Network Security

**Private Networking Support**
- **Private Endpoints**: Secure service-to-service communication
- **VNet Integration**: Application subnet isolation  
- **NSG Rules**: Network traffic filtering and control
- **Private DNS**: Internal name resolution

**Service Security**
- **Managed Identity**: Eliminate stored secrets
- **Key Vault Integration**: Secure secret management
- **TLS Encryption**: End-to-end encryption in transit
- **At-Rest Encryption**: Azure service native encryption

## Scalability Architecture

### Horizontal Scaling Design

**Stateless Application**
- **Session Storage**: Externalized to Azure Redis Cache
- **No Local State**: All persistent data in external services
- **Load Balancer**: Azure App Service built-in load balancing
- **Health Checks**: Application health monitoring

**Auto-scaling Configuration**
```
App Service Scaling:
├── CPU-based scaling (70% threshold)
├── Memory-based scaling (80% threshold)
├── Request queue scaling
└── Custom metrics scaling

Database Scaling:
├── Cosmos DB autoscale (RU/s based)
├── AI Search replicas (query performance)
├── AI Search partitions (storage capacity)
└── Cache scaling (memory and connections)
```

### Performance Optimization

**Caching Strategy**
- **Application Cache**: Redis for session and temporary data
- **Search Cache**: AI Search query result caching
- **CDN Integration**: Static asset delivery optimization
- **Browser Caching**: Client-side caching headers

**Database Optimization**
- **Partition Strategy**: Efficient data distribution
- **Index Optimization**: Query-specific indexing
- **Connection Pooling**: Efficient connection management
- **Query Optimization**: Minimized RU consumption

## Integration Architecture

### External Service Integration

**API-First Design**
- **REST APIs**: Standard HTTP/JSON interfaces
- **Authentication**: Bearer token and Managed Identity
- **Rate Limiting**: Built-in throttling and retry logic
- **Error Handling**: Comprehensive error responses

**Extensibility Points**
```
Integration Capabilities:
├── Custom AI Models
│   └── Bring your own model endpoints
├── External Data Sources
│   └── Custom document connectors
├── Workflow Integrations
│   └── Business process automation
└── Reporting & Analytics
    └── Custom dashboard integration
```

### Monitoring and Observability

**Application Insights Integration**
- **Performance Monitoring**: Request/response tracking
- **Error Tracking**: Exception and failure analysis
- **User Analytics**: Usage patterns and behavior
- **Custom Telemetry**: Business-specific metrics

**Azure Monitor Integration**
- **Resource Health**: Service availability monitoring
- **Cost Monitoring**: Resource usage and cost tracking
- **Security Monitoring**: Audit log analysis
- **Alerting**: Proactive issue notification

## Deployment Architectures

### Single-Region Deployment

**Standard Configuration:**
- All services deployed in single Azure region
- VNet integration for private networking
- Backup and disaster recovery within region
- Suitable for most enterprise deployments

**Benefits:**
- Lower latency between components
- Simplified networking configuration
- Reduced cross-region data transfer costs
- Easier compliance with data residency requirements

### Multi-Region Deployment

**Global Distribution:**
- Primary and secondary region deployments
- Cross-region replication for data services
- Traffic manager for intelligent routing
- Disaster recovery and business continuity

**Considerations:**
- Increased complexity and cost
- Data synchronization challenges
- Network latency for cross-region calls
- Compliance with data sovereignty requirements

## Design Patterns and Best Practices

### Microservices Principles

**Service Separation**
- **Document Processing**: Independent processing pipeline
- **Search Service**: Dedicated search and retrieval
- **Chat Service**: Conversation management and AI integration
- **Admin Service**: Configuration and management APIs

**Communication Patterns**
- **Async Processing**: Message queues for long-running operations
- **Event-Driven**: Event-based service communication
- **Circuit Breakers**: Fault tolerance for external dependencies
- **Retry Logic**: Resilient service interactions

### Data Consistency Patterns

**Eventually Consistent**
- Document processing and search indexing
- Cross-service data synchronization
- User preference replication

**Strongly Consistent**
- User authentication and authorization
- Configuration changes
- Critical business operations

## Technology Choices and Rationale

### Azure Services Selection

**Why Azure OpenAI?**
- Enterprise-grade AI with Azure security controls
- Private deployment options for sensitive data
- Integration with Azure ecosystem
- Compliance with enterprise requirements

**Why Cosmos DB?**
- Global distribution capabilities
- Flexible schema for evolving data models
- Built-in scaling and performance
- Strong consistency options when needed

**Why AI Search?**
- Hybrid search capabilities (vector + keyword)
- Built-in semantic search features
- Integration with Azure AI services
- Scalable search infrastructure

### Framework and Language Choices

**Python/Flask**
- Rich AI and ML library ecosystem
- Rapid development and iteration
- Strong Azure SDK support
- Enterprise-ready deployment options

**React/TypeScript Frontend**
- Modern, responsive user interface
- Strong typing for maintainability
- Rich component ecosystem
- Mobile-responsive design capabilities

This architecture provides a solid foundation for understanding how Simple Chat components work together to deliver secure, scalable, and intelligent conversational AI capabilities.

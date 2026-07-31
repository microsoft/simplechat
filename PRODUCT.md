# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

SimpleChat serves authenticated enterprise users who chat with generative AI grounded in personal, group, and public-workspace data. Administrators configure Azure-backed services, govern capabilities, and operate backup and migration workflows for production environments.

## Product Purpose

SimpleChat provides secure, context-aware generative AI using Azure OpenAI and retrieval-augmented generation. It lets organizations manage documents and AI-assisted work across personal, shared-group, and public workspaces while retaining administrative control over models, data, security, and operations.

## Positioning

SimpleChat combines Azure-native identity, Cosmos DB, Azure AI Search, Azure OpenAI, and document-processing services in one deployable application with explicit administrative governance and data-management workflows.

## Operating Context

- Users work with documents, conversations, agents, actions, and governed workspaces.
- Administrators operate the application through authenticated settings and control-center surfaces.
- Data migrations move selected SimpleChat users, groups, public workspaces, documents, Search records, and Enhanced Citation source blobs between SimpleChat environments.
- Migration work may be long-running, destructive, resumable, and operationally sensitive, so administrators need authoritative review, progress, and recovery information.

## Capabilities and Constraints

- Personal, group, and public-workspace document management and retrieval-augmented chat.
- Azure Cosmos DB, Azure AI Search, Azure OpenAI, Azure Storage, and Microsoft Entra integration.
- Admin-only backup, migration, settings, and governance operations.
- Durable migration checkpoints, retries, cancellation, provenance, reconciliation, and optional temporary Cosmos capacity management.
- Browser runtime JavaScript and companion assets are served locally; frontend settings and migration responses must not expose credentials or internal configuration.
- The web interface uses Bootstrap 5, supports light and dark themes, and must remain keyboard accessible and responsive.

## Brand Commitments

- Product name: SimpleChat.
- Preserve the existing SimpleChat logos and the familiar Bootstrap-based application vocabulary.
- Administrative copy is direct, operational, and explicit about risk; it does not use marketing language for destructive or production-impacting actions.

## Evidence on Hand

- Product overview and deployment facts: `README.md`.
- Existing application and admin interface: `application/single_app/`.
- Migration behavior and operational guidance: `docs/explanation/features/DATA_MANAGEMENT_BACKUP_MIGRATION.md` and `docs/explanation/features/DATA_MANAGEMENT_MIGRATION_RESILIENCE.md`.
- Product logos: `application/single_app/static/images/`.
- No customer claims, testimonials, pricing, or benchmark assets are approved for invention.

## Product Principles

- Keep data boundaries and authorization explicit.
- Make high-impact operations reviewable before execution.
- Prefer server-authoritative state and counts over browser inference.
- Preserve durable recovery paths for long-running work.
- Surface operational risk plainly without obscuring the task.

## Accessibility & Inclusion

Admin workflows must preserve semantic structure, visible labels, keyboard navigation, focus feedback, responsive layouts, and accessible loading, validation, progress, and status states.

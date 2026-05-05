# Core Document Search And Summarization

Version implemented: **0.241.007**

## Overview and Purpose

This feature adds a shared backend document-search service, a dedicated authenticated search API, and an always-loaded Semantic Kernel core plugin for search and summarization.

The goal is to give agents and backend callers a common way to:

- Run relevance-ranked hybrid search with a bounded, caller-overridable top-N.
- Retrieve ordered chunks for a specific document instead of relying only on distilled search hits.
- Generate hierarchical summaries across the full document by summarizing chunk windows and then reducing the intermediate summaries.

Dependencies:

- Azure AI Search chunk indexes for personal, group, and public workspaces
- Azure OpenAI chat model configuration for summary generation
- Semantic Kernel core plugin loading in the shared kernel loader

## Technical Specifications

### Architecture Overview

The feature is split into three thin layers over one shared service:

1. `functions_search.py` keeps hybrid search and now exposes shared top-N and scope normalization helpers.
2. `functions_search_service.py` resolves document scope, retrieves ordered chunks, builds chunk windows, and performs hierarchical summarization.
3. Adapters expose the shared service through:
   - `route_backend_search.py` for authenticated backend APIs
   - `semantic_kernel_plugins/document_search_plugin.py` for always-loaded Semantic Kernel access

This keeps the HTTP API and the Semantic Kernel plugin behavior aligned and makes future comparison workflows easier to add.

### API Endpoints

The backend route module adds three authenticated endpoints:

- `POST /api/search/documents`
  - Runs hybrid search.
  - Supports `query`, `doc_scope`, `top_n`, `document_id` or `document_ids`, optional tags, and optional scope hints.
- `POST /api/search/document-chunks`
  - Resolves an accessible document and returns ordered chunks.
  - Supports optional windowing by pages or chunks.
- `POST /api/search/document-summary`
  - Resolves a document, retrieves its ordered chunks, windows the content, summarizes each window, and reduces the intermediate summaries into a final result.
  - Supports optional focus instructions and target-length overrides.

### Semantic Kernel Plugin Functions

The core plugin is loaded for model-only and agent-backed kernel sessions and exposes three functions:

- `search_documents`
- `retrieve_document_chunks`
- `summarize_document`

The plugin resolves the current signed-in user at invocation time and calls the shared service directly rather than going through HTTP.

### Summary Workflow

The summarization workflow is hierarchical:

1. Resolve an accessible document in personal, group, or public scope.
2. Retrieve ordered chunks for the document.
3. Build chunk windows by pages when page numbers are available, otherwise by chunk count.
4. Summarize each window to a configurable intermediate target.
5. Reduce intermediate summaries in batches until a single final summary remains or the configured reduction limit is reached.

Default behavior keeps the first-pass window summaries and final summary at two pages unless the caller overrides those values.

### File Structure

- `application/single_app/functions_search.py`
- `application/single_app/functions_documents.py`
- `application/single_app/functions_search_service.py`
- `application/single_app/route_backend_search.py`
- `application/single_app/semantic_kernel_plugins/document_search_plugin.py`
- `application/single_app/semantic_kernel_loader.py`
- `functional_tests/test_document_search_api_and_plugin.py`

## Usage Instructions

### Backend API Usage

Use the backend endpoints when server-side code or future UI features need direct access to search, chunk retrieval, or summarization without invoking an agent.

Typical request patterns:

- Search a workspace with default distilled behavior and an explicit `top_n`.
- Retrieve all ordered chunks for a document before downstream processing.
- Summarize a document with focus instructions such as risks, deadlines, implementation details, or policy requirements.

### Agent Usage

Agents can use the core plugin to:

- Search for relevant chunks across accessible documents.
- Pull the full ordered chunk stream for one document when distilled search is not enough.
- Generate a hierarchical summary with caller-specified focus and length guidance.

This is intended to improve document-grounded summarization today and to support future document-to-document or version-to-version comparison workflows without changing the core retrieval contract.

## Testing and Validation

### Test Coverage

Functional coverage validates:

- Shared search helper exposure and document-id propagation
- Shared search service entry points for search, retrieval, and summarization
- Backend route registration and authentication decorators
- Core plugin kernel-function contract
- Loader and Flask app registration

Related test:

- `functional_tests/test_document_search_api_and_plugin.py`

### Known Limitations

- Summaries are generated on demand and are not persisted or cached in this implementation.
- Very large documents can require multiple summarization stages and multiple model calls.
- Comparison workflows are not included yet, but the retrieval and scope-resolution shapes are designed to support them.
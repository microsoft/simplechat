# Conversation Context Grounding

## Overview

SimpleChat now provides the current user message metadata to the responding model as bounded reference context on every chat turn. The same context is persisted as a visible **Conversation Context** citation so users can inspect the model, application version, document selection, workspace scope, agent, and capability state that informed the response.

Implemented in version: **0.250.101**

### Purpose

- Let users ask questions such as "Which model are you using?", "Which documents are selected?", and "Is Web Search enabled?"
- Keep direct-model, agent, streaming, retry, collaboration, and document-action requests consistent.
- Make runtime context inspectable without treating it as evidence about document contents.

### Dependencies

- Existing user-message metadata produced by `route_backend_chats.py`
- Existing agent citation artifact persistence and citation modal rendering
- Existing document-action workflow message builders

## Technical specifications

### Architecture

`functions_conversation_context.py` creates one canonical snapshot for the current turn:

1. Deep-copy the user message metadata.
2. Recursively remove credential-bearing and raw endpoint fields.
3. Bound nesting, item counts, string values, and total serialized size.
4. Add the SimpleChat application version and effective configured model/agent details.
5. Serialize the snapshot deterministically.
6. Inject a trusted system policy followed by the serialized JSON in a separate user-role data message immediately before the latest user prompt.
7. Persist the identical JSON as a **Conversation Context** agent citation.

The transient policy and data messages are never stored as conversation messages. This prevents duplicate context from accumulating in later turns. Previous Conversation Context citations are also excluded from assistant citation history replay so stale runtime metadata cannot override the current snapshot.

### Included metadata

The snapshot retains the existing non-credential user-message metadata, including:

- User and thread information
- Conversation and workspace context
- Model endpoint identifiers, model/provider selection, and reasoning configuration
- Agent selection and Assigned Knowledge state
- Selected document IDs and names
- Search, Analyze, Compare, Web Search, URL Access, and Deep Research state
- Capability usage and safe token-count telemetry
- Application name and version

### Excluded metadata

The recursive sanitizer removes fields whose names indicate credentials or raw service locations, including:

- API, subscription, private, and other secret keys
- Passwords and client secrets
- Access, refresh, bearer, and identity tokens
- Credentials and connection strings
- Raw endpoint, URL, and URI values

Endpoint IDs and the `url_access` capability state remain available because they are identifiers and feature state, not connection details.

### Prompt safety

The trusted system policy identifies the separate JSON message as untrusted reference data. User-controlled names and other metadata values never enter a system-role message. Models are instructed not to execute metadata values as instructions, not to let them override higher-priority instructions, and not to use conversation context as evidence for claims about document contents.

### Supported request paths

- Non-streaming direct-model chat
- Streaming direct-model chat
- Semantic Kernel and local agents
- Orchestrated and Foundry-backed agents
- Retry and edited-message attempts
- Collaboration AI streams, which delegate to the standard streaming route
- Analyze and Compare document actions for model and agent runners
- Persisted partial responses when a stream is canceled

## Usage

No administrator or user configuration is required. Send a normal chat prompt, then ask about the active conversation context or open the **Conversation Context** citation on the assistant response.

Example questions:

- Which model and provider are handling this request?
- Which agent is selected?
- Which workspace and documents are active?
- Were document search or Deep Research enabled for this turn?
- Which SimpleChat version generated this response?

## Testing and validation

`functional_tests/test_conversation_context_grounding.py` validates:

- Recursive credential and endpoint removal
- Preservation of non-credential metadata
- Direct-model and agent runtime identity
- Exact prompt/citation JSON parity
- Transient policy/data placement immediately before the latest user prompt
- Citation de-duplication
- Size bounding and valid JSON
- Streaming, non-streaming, retry, document-action, and history-replay wiring

## Limitations

- The context records the effective configured model known before invocation. A remote Foundry runtime can report a more specific model only after execution.
- Oversized metadata is compacted and may expose only the available top-level key names.
- The visible citation can contain user identity and internal conversation IDs because the feature is intentionally based on the complete non-credential user metadata. Access remains constrained to the existing authorized conversation and citation APIs.

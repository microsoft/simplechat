# Enhanced Conversation Metadata

This document describes the enhanced conversation metadata collection system implemented for Simple Chat. The system now captures comprehensive metadata about conversations including context, tags, and detailed tracking information.

## Overview

The conversation documents in Cosmos DB now store much more detailed information about each conversation, including:

- **Context**: Primary and secondary scopes for the conversation
- **Tags**: Detailed categorization of conversation elements
- **Strict Mode**: Controls access to data outside primary context
- **Enhanced Classifications**: Document classifications encountered in the conversation

### Deduplication Logic

The system prevents duplicates across all categories:

- **Participants**: Keyed by `user_id` - no duplicate users
- **Documents**: Keyed by `document_id` - chunk IDs are merged into existing documents
- **Models/Agents**: Keyed by `value` - no duplicate model or agent entries  
- **Semantic Terms**: Keyed by `value` - no duplicate keywords
- **Web Sources**: Keyed by `url` - no duplicate URLs

## Document Structure

### Basic Structure

```json
{
  "id": "conversation-id",
  "user_id": "user-id",
  "last_updated": "2025-01-11T17:25:54.467913",
  "title": "Conversation title",
  "context": [...],
  "tags": [...],
  "strict": false,
  "classification": [...]
}
```

### Context Array

The `context` array defines the scope and access boundaries for the conversation:

- **Primary Context**: The main scope for the conversation (personal, group, or public)
- **Secondary Contexts**: Additional scopes that were accessed during the conversation

```json
"context": [
  {
    "type": "primary",
    "scope": "group",
    "id": "group-id"
  },
  {
    "type": "secondary", 
    "scope": "public",
    "id": "public-workspace"
  }
]
```

### Tags Array

The `tags` array provides detailed categorization of conversation elements:

#### Tag Categories

1. **agent**: AI agents used in the conversation
2. **model**: AI models used (GPT-4o, DALL-E, etc.)
3. **participant**: Users who participated in the conversation with detailed information
4. **semantic**: Keywords extracted from user messages
5. **document**: Documents referenced with scope and classification
6. **web**: External web sources accessed

#### Participant Tags

Participant tags include detailed user information:

```json
{
  "category": "participant",
  "user_id": "07e61033-ea1a-4472-a1e7-6b9ac874984a",
  "name": "Paul Lizer", 
  "email": "paul.lizer@microsoft.com"
}
```

#### Document Tags

Document tags include additional metadata:

```json
{
  "category": "document",
  "value": "doc-id",
  "scope": "group|personal|public",
  "id": "scope-specific-id",
  "classification": "CUI|Public|None|etc"
}
```

#### Web Tags

Web tags capture external sources:

```json
{
  "category": "web",
  "value": "https://example.com/page"
}
```

### Strict Mode

The `strict` field controls context access:

- `true`: Conversation cannot access data outside the primary context without explicit user confirmation
- `false`: Conversation can access data from secondary contexts freely

## Implementation

### Functions

The metadata collection is implemented in `functions_conversation_metadata.py`:

- `collect_conversation_metadata()`: Main function to collect and update metadata
- `update_conversation_with_metadata()`: Update conversation with new metadata
- `get_conversation_metadata()`: Retrieve conversation metadata

### Integration Points

The metadata collection is integrated at several points:

1. **Conversation Creation**: Initialize basic metadata structure
2. **Chat Processing**: Collect metadata during message processing
3. **Final Update**: Update conversation with comprehensive metadata before response

### API Endpoints

- `GET /api/conversations/{id}/metadata`: Retrieve detailed conversation metadata

## Use Cases

This enhanced metadata enables several advanced features:

1. **Scoped Context Control**: Prevent accidental cross-contamination between projects
2. **Audit Trail**: Track what resources were used in each conversation
3. **Analytics**: Understand usage patterns and resource access
4. **Compliance**: Support regulatory requirements for data tracking
5. **Search and Discovery**: Find conversations by detailed criteria

## Examples

See `test_conversation_metadata.py` for comprehensive examples of the metadata structure in different scenarios:

- Personal conversations
- Group conversations with document access
- Multi-scope conversations with web search
- Image generation conversations

## Future Enhancements

Potential future enhancements include:

- UI components to display and manage conversation metadata
- Advanced search and filtering based on metadata
- Automatic context switching based on strict mode settings
- Metadata-based access controls and permissions
- Analytics dashboards showing usage patterns

# Document Metadata Update Activity Logging

## Overview
Document metadata update activity logging provides comprehensive tracking of all document metadata modifications across personal, group, and public workspaces. This feature creates permanent audit trails in the `activity_logs` container for compliance, analytics, and user activity monitoring.

## Version Information
- **Implemented in**: Version 0.234.024
- **Related Features**: Document creation logging, document deletion logging

## Purpose
Track all document metadata changes to:
- Provide audit trails for compliance and governance
- Enable analytics on document metadata modifications
- Monitor user activity patterns
- Support troubleshooting and debugging
- Generate reports on document management activities

## Activity Type
The activity logs use `activity_type: 'document_metadata_update'` to identify metadata update transactions.

## What Gets Logged

### Core Fields
- **User Information**: User ID who performed the update
- **Document Information**: Document ID, file name, file type
- **Workspace Context**: Workspace type (personal/group/public) and workspace IDs
- **Timestamp**: ISO 8601 formatted timestamp of the update
- **Updated Fields**: Dictionary of all metadata fields that were modified with their new values

### Tracked Metadata Fields
The following metadata fields are tracked when updated:
- `title` - Document title
- `abstract` - Document abstract/summary
- `keywords` - Document keywords (array)
- `authors` - Document authors (array)
- `publication_date` - Publication date
- `document_classification` - Classification (e.g., Public, Internal, Confidential)

## Activity Log Structure

### Personal Workspace Example
```json
{
    "id": "uuid-string",
    "user_id": "user-id",
    "activity_type": "document_metadata_update",
    "workspace_type": "personal",
    "timestamp": "2024-12-20T10:30:00.000Z",
    "created_at": "2024-12-20T10:30:00.000Z",
    "document": {
        "document_id": "doc-id",
        "file_name": "research_paper.pdf",
        "file_type": ".pdf"
    },
    "updated_fields": {
        "title": "New Document Title",
        "abstract": "Updated abstract text",
        "keywords": ["research", "updated", "keywords"],
        "authors": ["John Doe", "Jane Smith"]
    },
    "workspace_context": {}
}
```

### Group Workspace Example
```json
{
    "id": "uuid-string",
    "user_id": "user-id",
    "activity_type": "document_metadata_update",
    "workspace_type": "group",
    "timestamp": "2024-12-20T10:30:00.000Z",
    "created_at": "2024-12-20T10:30:00.000Z",
    "document": {
        "document_id": "doc-id",
        "file_name": "team_report.pdf",
        "file_type": ".pdf"
    },
    "updated_fields": {
        "document_classification": "Internal",
        "publication_date": "2024-12-20"
    },
    "workspace_context": {
        "group_id": "group-oid"
    }
}
```

### Public Workspace Example
```json
{
    "id": "uuid-string",
    "user_id": "user-id",
    "activity_type": "document_metadata_update",
    "workspace_type": "public",
    "timestamp": "2024-12-20T10:30:00.000Z",
    "created_at": "2024-12-20T10:30:00.000Z",
    "document": {
        "document_id": "doc-id",
        "file_name": "public_guide.pdf",
        "file_type": ".pdf"
    },
    "updated_fields": {
        "abstract": "Updated public guide description",
        "keywords": ["guide", "public", "help"]
    },
    "workspace_context": {
        "public_workspace_id": "workspace-oid"
    }
}
```

## Implementation Details

### Function: `log_document_metadata_update_transaction`
Location: `functions_activity_logging.py`

**Parameters:**
- `user_id` (str, required): ID of user performing the update
- `document_id` (str, required): ID of the document being updated
- `workspace_type` (str, required): Type of workspace ('personal', 'group', 'public')
- `file_name` (str, required): Name of the document file
- `updated_fields` (dict, required): Dictionary of updated fields with new values
- `file_type` (str, optional): File extension/type
- `group_id` (str, optional): Group ID if group workspace
- `public_workspace_id` (str, optional): Public workspace ID if public workspace
- `additional_metadata` (dict, optional): Any additional metadata to store

### Routes That Log Metadata Updates

#### 1. Personal Workspace
**Route**: `PATCH /api/documents/<document_id>`  
**File**: `route_backend_documents.py`  
**Function**: `api_patch_user_document()`

#### 2. Group Workspace
**Route**: `PATCH /api/group_documents/<document_id>`  
**File**: `route_backend_group_documents.py`  
**Function**: `api_patch_group_document()`

#### 3. Public Workspace (Internal)
**Route**: `PATCH /api/public_documents/<doc_id>`  
**File**: `route_backend_public_documents.py`  
**Function**: `api_patch_public_document()`

#### 4. Public Workspace (External)
**Route**: `PATCH /external/public_documents/<document_id>`  
**File**: `route_external_public_documents.py`  
**Function**: `external_patch_public_document()`

## Querying Activity Logs

### Get All Metadata Updates for a User
```sql
SELECT * FROM c
WHERE c.user_id = 'user-id'
AND c.activity_type = 'document_metadata_update'
ORDER BY c.timestamp DESC
```

### Get Metadata Updates for a Specific Document
```sql
SELECT * FROM c
WHERE c.document.document_id = 'document-id'
AND c.activity_type = 'document_metadata_update'
ORDER BY c.timestamp DESC
```

### Get Metadata Updates by Workspace Type
```sql
SELECT * FROM c
WHERE c.workspace_type = 'group'
AND c.activity_type = 'document_metadata_update'
ORDER BY c.timestamp DESC
```

### Get Recent Metadata Updates Across All Workspaces
```sql
SELECT * FROM c
WHERE c.activity_type = 'document_metadata_update'
ORDER BY c.timestamp DESC
OFFSET 0 LIMIT 50
```

### Get Metadata Updates for a Specific Field
```sql
SELECT * FROM c
WHERE c.activity_type = 'document_metadata_update'
AND IS_DEFINED(c.updated_fields.title)
ORDER BY c.timestamp DESC
```

## Integration with Application Insights

In addition to Cosmos DB storage, metadata update events are logged to Application Insights with:
- Event name: "Document metadata update transaction logged"
- Full activity record as custom properties
- Log level: INFO

This enables:
- Real-time monitoring and alerting
- Performance metrics and tracking
- Cross-system correlation with other logs
- Azure Monitor integration

## Analytics Use Cases

### 1. Document Governance
Track who modifies document metadata and when for compliance requirements.

### 2. User Activity Patterns
Analyze which metadata fields are most frequently updated by users.

### 3. Workspace Activity
Monitor metadata update activity across different workspace types.

### 4. Audit Trails
Maintain permanent records of all metadata changes for auditing purposes.

### 5. Change Tracking
Track the history of metadata changes for specific documents over time.

## Error Handling

The logging function includes comprehensive error handling:
- Errors are logged to Application Insights but don't break the metadata update flow
- Console warnings are printed for debugging
- The document update succeeds even if activity logging fails
- This ensures user experience is not impacted by logging issues

## Testing

Functional test: `test_document_metadata_update_activity_logging.py`

The test validates:
- ✅ Metadata update logging for personal workspaces
- ✅ Metadata update logging for group workspaces  
- ✅ Metadata update logging for public workspaces
- ✅ Proper tracking of all updated fields
- ✅ Correct workspace context logging
- ✅ Activity log structure and data integrity

## Related Documentation

- [Document Creation Activity Logging](./DOCUMENT_CREATION_ACTIVITY_LOGGING.md)
- [Document Deletion Activity Logging](./DOCUMENT_DELETION_ACTIVITY_LOGGING.md)
- [Activity Logging Architecture](./ACTIVITY_LOGGING_ARCHITECTURE.md)

## Performance Considerations

- Activity logging is non-blocking and won't impact document update performance
- Logs are stored with the user_id as partition key for efficient querying
- Cosmos DB throughput may need adjustment based on metadata update volume
- Application Insights logging is asynchronous

## Best Practices

1. **Query Optimization**: Use partition key (user_id) in queries when possible
2. **Data Retention**: Implement retention policies based on compliance requirements
3. **Monitoring**: Set up alerts for unusual metadata update patterns
4. **Privacy**: Ensure updated_fields dictionary doesn't contain sensitive data
5. **Documentation**: Keep this documentation updated as the schema evolves

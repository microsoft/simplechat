# Agent Template Gallery

## Overview

The Agent Template Gallery provides a curated collection of reusable agent configurations that users can use as starting points when creating new agents. This feature includes an admin review workflow to ensure quality control and organizational compliance for user-submitted templates.

**Version Implemented:** 0.236.011

## Key Features

- **Template Gallery**: Browse and select from approved agent templates
- **User Submission**: Users can submit their agents as templates for community use
- **Admin Review Workflow**: Submitted templates require admin approval before publication
- **Rich Metadata**: Templates include titles, descriptions, tags, and instructions
- **Helper Text**: Short descriptions optimized for gallery display
- **Actions Integration**: Templates can include predefined actions/plugins

## Configuration

### Admin Settings

| Setting | Description | Default |
|---------|-------------|---------|
| `enable_agent_template_gallery` | Show template gallery in agent builder | `true` |
| `agent_templates_allow_user_submission` | Allow users to submit templates | `true` |
| `agent_templates_require_approval` | Require admin approval for submissions | `true` |

### Accessing Template Gallery Settings

1. Navigate to **Admin Settings** from the sidebar
2. Select the **Agents** tab
3. Locate the **Agent Template Gallery** section

## Template Workflow

### Template Statuses

| Status | Description |
|--------|-------------|
| `pending` | Submitted, awaiting admin review |
| `approved` | Approved and visible in gallery |
| `rejected` | Rejected by admin |
| `archived` | Removed from gallery but preserved |

### User Submission Flow

1. User creates and configures an agent
2. User selects "Submit as Template" option
3. User provides additional metadata (title, description, tags)
4. Template is saved with `pending` status
5. Template awaits admin review

### Admin Review Flow

1. Admin navigates to template management
2. Admin reviews pending templates
3. Admin can:
   - **Approve**: Template becomes visible in gallery
   - **Reject**: Template is marked rejected with reason
   - **Edit**: Modify template details before approval

## Template Structure

### Required Fields

| Field | Max Length | Description |
|-------|------------|-------------|
| `display_name` / `title` | 200 chars | Template name |
| `description` | 2000 chars | Full description |
| `instructions` | 30000 chars | Agent instructions |

### Optional Fields

| Field | Max Length | Description |
|-------|------------|-------------|
| `helper_text` | 140 chars | Short gallery description |
| `tags` | 64 chars each | Categorization tags |
| `actions_to_load` | 128 chars each | Predefined actions |
| `additional_settings` | JSON | Extra configuration |

### Helper Text Generation

If no explicit helper text is provided, it's automatically generated from the description:
- If description ≤ 140 characters: Use full description
- If description > 140 characters: Truncate to 137 characters + "..."

## Technical Architecture

### Backend Components

| File | Purpose |
|------|---------|
| [functions_agent_templates.py](../../../../application/single_app/functions_agent_templates.py) | CRUD operations for templates |
| [config.py](../../../../application/single_app/config.py) | Cosmos DB container setup |
| [route_frontend_admin_settings.py](../../../../application/single_app/route_frontend_admin_settings.py) | Settings management |

### Cosmos DB Container

```python
cosmos_agent_templates_container_name = "agent_templates"
cosmos_agent_templates_container = cosmos_database.create_container_if_not_exists(
    id=cosmos_agent_templates_container_name,
    partition_key=PartitionKey(path='/id')
)
```

### Key Functions

| Function | Purpose |
|----------|---------|
| `list_agent_templates(status, include_internal)` | List templates with optional filtering |
| `get_agent_template(template_id)` | Get single template by ID |
| `create_agent_template(payload, user_info, auto_approve)` | Create new template |
| `update_agent_template(template_id, updates)` | Update existing template |
| `validate_template_payload(payload)` | Validate template data |

### API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/agent-templates` | GET | List approved templates |
| `/api/agent-templates` | POST | Submit new template |
| `/api/agent-templates/<id>` | GET | Get template details |
| `/api/agent-templates/<id>` | PUT | Update template |

## User Experience

### Browsing Templates

1. Open Agent Builder modal
2. View Template Gallery section
3. Browse by title, description, or tags
4. Click template to view details
5. Select "Use Template" to create agent from template

### Submitting Templates

1. Create and test an agent
2. Click "Submit as Template"
3. Fill in template metadata:
   - Title/display name
   - Description
   - Helper text (optional)
   - Tags
   - Submission notes
4. Submit for review

### Template Card Display

Each template card shows:
- Title
- Helper text (short description)
- Tags
- Action count
- "Use Template" button

## Activity Logging

Template submissions and approvals are logged:
```python
log_event(
    "Agent template submitted",
    extra={
        "template_id": template['id'],
        "status": template['status'],
        "created_by": template.get('created_by'),
    },
)
```

## Security Considerations

1. **Admin Approval**: Templates must be reviewed before publication
2. **User Attribution**: Submissions track creator identity
3. **Content Sanitization**: Template fields are sanitized and length-limited
4. **Permission Control**: Only admins can approve/reject templates
5. **Internal Fields**: Sensitive fields are stripped from public views

## Validation Rules

Templates are validated for:
- Required fields presence (display_name, description, instructions)
- Maximum field lengths
- Valid JSON for additional_settings
- Proper tag formatting

## Known Limitations

- Templates don't include file attachments
- Actions referenced must exist in the system
- Large instruction sets may affect load times

## Related Features

- Agent Builder
- Personal and Group Agents
- Plugin/Action Configuration

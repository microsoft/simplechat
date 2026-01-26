# Web Search via Azure AI Foundry Agents

## Overview

SimpleChat now supports web search capability through Azure AI Foundry agents using the Grounding with Bing Search service. This feature enables AI responses to be augmented with real-time web search results, providing users with up-to-date information beyond the model's training data.

**Version Implemented:** v0.237.001

## Key Features

- **Azure AI Foundry Integration**: Leverages Azure AI Foundry's Grounding with Bing Search capability
- **Admin Consent Flow**: Requires explicit administrator consent before enabling due to data processing considerations
- **Activity Logging**: All consent acceptances are logged for compliance and audit purposes
- **Setup Guide Modal**: Comprehensive in-app configuration guide with step-by-step instructions
- **User Data Notice**: Admin-configurable notification banner informing users when their message will be sent to Bing
- **Graceful Error Handling**: Informs users when web search fails rather than answering from outdated training data
- **Seamless Experience**: Web search results are automatically integrated into AI responses

## Admin Consent Requirement

Before web search can be enabled, administrators must acknowledge important data handling considerations:

### Consent Message

> When you use Grounding with Bing Search, your customer data is transferred outside of the Azure compliance boundary to the Grounding with Bing Search service. Grounding with Bing Search is not subject to the same data processing terms (including location of processing) and does not have the same compliance standards and certifications as the Azure AI Agent Service, as described in the Grounding with Bing Search TOU.

### Why Consent is Required

1. **Data Transfer**: Customer data is transferred outside the Azure compliance boundary
2. **Different Terms**: Grounding with Bing Search has different data processing terms
3. **Compliance Considerations**: Different compliance standards and certifications apply
4. **Organizational Responsibility**: Organizations must assess whether this meets their requirements

## Configuration

### Enabling Web Search

1. Navigate to **Admin Settings** from the sidebar
2. Go to the **Search** or **Agents** section
3. Locate the **Web Search** toggle
4. Read and accept the consent message
5. Enable web search

### Settings Stored

| Setting | Description |
|---------|-------------|
| `enable_web_search` | Master toggle for web search capability |
| `web_search_consent_accepted` | Tracks whether consent has been accepted |
| `enable_web_search_user_notice` | Toggle for showing user notification when web search is activated |
| `web_search_user_notice_text` | Customizable notification message shown to users |

## User Data Notice

Administrators can enable a notification banner that appears when users activate web search, informing them about data being sent to Bing.

### Configuration

1. Navigate to **Admin Settings** > **Search and Extract** tab
2. Locate the **User Data Notice** card in the Web Search section
3. Enable the **Show User Notice** toggle
4. Customize the notification text (optional)

### Default Notice Text

> Your message will be sent to Microsoft Bing for web search. Only your current message is sent, not your conversation history.

### Behavior

- **Appears**: When user clicks the "Web" button to activate web search
- **Dismissible**: Users can dismiss the notice via the X button
- **Session-based**: Dismissal persists for the browser session only
- **Hides automatically**: When web search is deactivated

## Setup Guide Modal

The admin settings include a comprehensive setup guide modal with:

### Pricing Information

| Metric | Value |
|--------|-------|
| **Cost** | $14 per 1,000 transactions |
| **Rate Limit** | 150 transactions/second |
| **Daily Limit** | 1,000,000 transactions/day |

### Step-by-Step Instructions

1. Create an Azure AI Foundry project
2. Navigate to Agents section
3. Create a new agent with Bing grounding tool
4. Configure result count to 10
5. Add recommended agent instructions
6. Copy the agent ID to SimpleChat admin settings
7. Configure Azure AI Foundry connection settings

### Access

Click the **Setup Guide** button in the Web Search admin settings section to open the modal.

## Technical Architecture

### Backend Components

| File | Purpose |
|------|---------|
| [route_frontend_admin_settings.py](../../../../application/single_app/route_frontend_admin_settings.py) | Handles consent flow and settings persistence |
| [route_backend_chats.py](../../../../application/single_app/route_backend_chats.py) | `perform_web_search()` with graceful error handling |
| [functions_activity_logging.py](../../../../application/single_app/functions_activity_logging.py) | `log_web_search_consent_acceptance()` for audit logging |
| [functions_settings.py](../../../../application/single_app/functions_settings.py) | Default settings including user notice configuration |

### Frontend Components

| File | Purpose |
|------|---------|
| [admin_settings.html](../../../../application/single_app/templates/admin_settings.html) | Admin UI for web search configuration |
| [_web_search_foundry_info.html](../../../../application/single_app/templates/_web_search_foundry_info.html) | Setup guide modal with pricing and instructions |
| [chats.html](../../../../application/single_app/templates/chats.html) | User notice container in chat interface |
| [chat-input-actions.js](../../../../application/single_app/static/js/chat-input-actions.js) | Notice show/hide logic with session dismissal |

### Consent Flow Logic

```python
# Simplified flow
web_search_consent_accepted = form_data.get('web_search_consent_accepted') == 'true'
requested_enable_web_search = form_data.get('enable_web_search') == 'on'
enable_web_search = requested_enable_web_search and web_search_consent_accepted

# Log consent if newly accepted
if enable_web_search and web_search_consent_accepted and not settings.get('web_search_consent_accepted'):
    log_web_search_consent_acceptance(
        user_id=user_id,
        admin_email=admin_email,
        consent_text=web_search_consent_message,
        source='admin_settings'
    )
```

### Activity Log Entry

When consent is accepted, the following information is logged:
- Admin user ID
- Admin email address
- Full consent text
- Source of consent (admin_settings)
- Timestamp

## User Experience

### For End Users

- Web search is transparent when enabled
- AI responses automatically incorporate relevant web search results
- Citations from web sources are displayed alongside responses
- Optional notification banner when activating web search (if enabled by admin)
- Graceful error messages when web search fails

### For Administrators

- Clear consent flow before enabling
- One-time consent acceptance (persisted in settings)
- Audit trail of consent acceptance
- Comprehensive setup guide with pricing information
- Configurable user notification for transparency

## Security Considerations

1. **Consent Tracking**: All consent acceptances are logged for compliance
2. **Admin-Only Configuration**: Only administrators can enable web search
3. **Data Awareness**: Clear communication about data handling implications
4. **Revocability**: Web search can be disabled at any time

## Related Features

- [Azure AI Foundry Agent Support](AZURE_AI_FOUNDRY_AGENT_SUPPORT.md)
- Agent-based chat with real-time information

## Dependencies

- Azure AI Foundry account with Grounding with Bing Search enabled
- Proper Azure AI Foundry configuration in SimpleChat

## Known Limitations

- Web search results depend on Bing Search availability
- Results may vary based on Bing's index freshness
- Subject to Bing Search Terms of Use

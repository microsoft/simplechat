# Conversation Deep Linking

## Overview

SimpleChat now supports conversation deep linking through URL query parameters. Users can share direct links to specific conversations, and the application will automatically navigate to and load the referenced conversation when the link is accessed.

**Version Implemented:** v0.237.001

## Key Features

- **Direct Conversation Links**: Share URLs that open a specific conversation
- **URL Parameter Support**: Supports both `conversationId` and `conversation_id` parameters
- **Automatic URL Updates**: Current conversation ID is automatically added to the URL
- **Browser History Integration**: Uses `replaceState` to update URLs without creating new history entries
- **Error Handling**: Graceful handling of invalid or inaccessible conversation IDs

## How It Works

### URL Format

Conversations can be linked using either parameter format:

```
https://your-simplechat.com/?conversationId=<conversation-uuid>
https://your-simplechat.com/?conversation_id=<conversation-uuid>
```

### Automatic URL Updates

When users select a conversation in the sidebar, the URL is automatically updated to include the conversation ID:

```javascript
function updateConversationUrl(conversationId) {
  if (!conversationId) return;

  try {
    const url = new URL(window.location.href);
    url.searchParams.set('conversationId', conversationId);
    window.history.replaceState({}, '', url.toString());
  } catch (error) {
    console.warn('Failed to update conversation URL:', error);
  }
}
```

### Deep Link Loading

On page load, the application checks for a `conversationId` parameter and loads that conversation:

```javascript
// Deep-link: conversationId query param
const conversationId = getUrlParameter("conversationId") || getUrlParameter("conversation_id");
if (conversationId) {
    try {
        await ensureConversationPresent(conversationId);
        await selectConversation(conversationId);
    } catch (err) {
        console.error('Failed to load conversation from URL param:', err);
        showToast('Could not open that conversation.', 'danger');
    }
}
```

## User Experience

### Sharing Conversations

1. Navigate to any conversation
2. Copy the URL from the browser address bar
3. Share the URL with colleagues
4. Recipients with access can open the link to view the conversation

### Receiving Shared Links

1. Click or paste a shared conversation link
2. The application loads and displays the referenced conversation
3. If the conversation doesn't exist or isn't accessible, an error toast is shown

### Error Handling

When a deep link fails to load:
- A toast notification appears: "Could not open that conversation."
- The user remains on the default view
- Console logging captures the error details for debugging

## Technical Architecture

### Frontend Components

| File | Purpose |
|------|---------|
| [chat-onload.js](../../../../application/single_app/static/js/chat/chat-onload.js) | Handles deep link loading on page initialization |
| [chat-conversations.js](../../../../application/single_app/static/js/chat/chat-conversations.js) | `updateConversationUrl()` function for URL management |

### Functions Involved

| Function | Purpose |
|----------|---------|
| `getUrlParameter(name)` | Retrieves query parameter value from current URL |
| `ensureConversationPresent(id)` | Ensures conversation exists in the local list |
| `selectConversation(id)` | Loads and displays the specified conversation |
| `updateConversationUrl(id)` | Updates URL with current conversation ID |

## Use Cases

### Team Collaboration
- Share conversation links in chat or email for review
- Direct colleagues to specific AI interactions for discussion

### Support and Troubleshooting
- Users can share conversation links with support staff
- Administrators can reference specific conversations in reports

### Documentation
- Bookmark important conversations for future reference
- Create documentation links to example interactions

## Security Considerations

1. **Access Control**: Deep links respect existing conversation access permissions
2. **User Ownership**: Only accessible if the user has rights to the conversation
3. **No Authentication Bypass**: Users must still be logged in to access conversations
4. **Workspace Boundaries**: Workspace permissions still apply

## Browser Compatibility

- Uses standard `URL` and `URLSearchParams` APIs
- `history.replaceState()` for seamless URL updates
- Compatible with all modern browsers

## Known Limitations

- Deep links only work for conversations the current user has access to
- Links to deleted conversations will show an error
- Group/public workspace conversations require appropriate membership

## Related Features

- Conversation management and history
- Sidebar conversation navigation
- Chat workspace functionality

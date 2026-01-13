# File Message Metadata Loading Fix

**Fixed in version: 0.233.232**

## Issue Description

When clicking the metadata info button (ℹ️) on file messages in the chat interface, the system was failing to load metadata with a 404 error:

```
GET https://127.0.0.1:5000/api/message/null/metadata 404 (NOT FOUND)
Error loading message metadata: Error: Failed to load metadata
```

The error occurred because the message ID was not being properly passed when loading file messages, resulting in `null` being used in the API endpoint URL.

## Root Cause

In the `loadMessages` function in `chat-messages.js`, file messages were being loaded with only 2 parameters:

```javascript
} else if (msg.role === "file") {
  appendMessage("File", msg);
}
```

This contrasts with other message types (user, assistant, image) which properly pass the message ID as the 4th parameter to `appendMessage`. Without the message ID parameter, the metadata button's event listener couldn't retrieve the correct message ID, causing it to be `null` when constructing the API URL.

## Solution

Updated the file message loading to pass all required parameters, including the message ID:

```javascript
} else if (msg.role === "file") {
  // Pass file message with proper parameters including message ID
  appendMessage("File", msg, null, msg.id, false, [], [], [], null, null, msg);
}
```

### Parameters passed:
1. `"File"` - sender type
2. `msg` - the full message object (contains filename and id)
3. `null` - model name (not applicable for files)
4. `msg.id` - **the message ID** (critical for metadata loading)
5. `false` - augmented flag
6. `[]` - hybrid citations
7. `[]` - web citations
8. `[]` - agent citations
9. `null` - agent display name
10. `null` - agent name
11. `msg` - full message object for additional context

## Files Modified

- **application/single_app/static/js/chat/chat-messages.js** (line ~489)
  - Updated file message loading to include message ID parameter
  
- **application/single_app/config.py**
  - Updated VERSION from "0.233.231" to "0.233.232"

## Testing

To verify the fix:

1. Upload a file to a conversation
2. Click the info button (ℹ️) on the file message
3. Verify that metadata loads successfully showing:
   - Thread Information (thread ID, previous thread, active status, attempt)
   - Message Details (message ID, conversation ID, role, timestamp)
   - File Details (filename, table data status)

## Sample Working Metadata

```json
{
  "id": "bbf4ba02-f75b-4323-bfa2-6e7cea78b95b_file_1765039677_2894",
  "conversation_id": "bbf4ba02-f75b-4323-bfa2-6e7cea78b95b",
  "role": "file",
  "filename": "Connect-2025-05.pdf",
  "is_table": false,
  "timestamp": "2025-12-06T16:47:57.048838",
  "metadata": {
    "thread_info": {
      "thread_id": "8f0c3b8d-6770-4569-aafd-f20cbe7ce3ed",
      "previous_thread_id": "17074c81-ee9a-4a2e-8505-0665252313e1",
      "active_thread": true,
      "thread_attempt": 1
    }
  }
}
```

## Impact

- **User Experience**: Users can now successfully view file message metadata
- **Debugging**: Proper metadata access enables better troubleshooting of file upload and processing issues
- **Consistency**: File messages now behave consistently with other message types (images, user messages, assistant messages)

## Related Features

- File upload system
- Message metadata display system
- Thread tracking and management

# Content Safety Error Handling Improvement

## Issue Description
Image generation requests that violate Azure OpenAI's content safety policies were returning generic 500 errors, providing poor user experience and unclear guidance on how to resolve the issue.

## Example Error Case
User prompt: "phishing → account takeover → silent malicious patch release"
Result: Generic "HTTP error! status: 500" with no clear explanation

## Root Cause
- Content safety violations were treated as generic server errors
- No distinction between technical failures and policy violations
- Users received no guidance on how to modify their requests
- Frontend showed unhelpful generic error messages

## Solution Implemented

### 1. Backend Improvements (`route_backend_chats.py`)
- **Error Type Detection**: Identify content safety vs technical errors
- **Appropriate Status Codes**: 400 for content violations, 500 for technical issues
- **User-Friendly Messages**: Clear explanations with actionable guidance

```python
# Check if this is a content moderation error
if "safety system" in error_message.lower() or "moderation_blocked" in error_message:
    user_friendly_message = "Image generation was blocked by content safety policies. Please try a different prompt that doesn't involve potentially harmful content."
    status_code = 400  # Bad request rather than server error
```

### 2. Frontend Improvements (`chat-messages.js`)
- **Specific Content Safety Detection**: Recognizes safety-related error messages
- **Styled Safety Messages**: Uses 'safety' sender type for appropriate styling
- **Clear User Guidance**: Explains what content to avoid

```javascript
// Handle image generation content safety errors
if (errMsg.includes("safety system") || errMsg.includes("moderation_blocked") || errMsg.includes("content safety")) {
  appendMessage(
    "safety", // Use 'safety' sender type
    `**Image Generation Blocked by Content Safety**\n\n` +
    `Your image generation request was blocked by Azure OpenAI's content safety system. ` +
    `Please try a different prompt that doesn't involve potentially harmful, violent, or illicit content.`
  );
}
```

## User Experience Improvements

### Before
- ❌ Generic "HTTP error! status: 500"
- ❌ No explanation of what went wrong
- ❌ No guidance on how to fix the issue
- ❌ Confusing technical error for policy violation

### After
- ✅ Clear "Image Generation Blocked by Content Safety" message
- ✅ Explanation that Azure OpenAI's safety system blocked the request
- ✅ Specific guidance: "avoid harmful, violent, or illicit content"
- ✅ Proper 400 status code indicating user input issue

## Error Type Differentiation

| Error Type | Status Code | User Message | Guidance |
|------------|-------------|--------------|----------|
| Content Safety | 400 | "Blocked by content safety policies" | "Try a different prompt" |
| Bad Request | 400 | "Request was invalid" | Technical details |
| Technical Error | 500 | "Technical error occurred" | Contact support |

## Benefits
- ✅ Users understand why their request was blocked
- ✅ Clear guidance on how to modify prompts
- ✅ Reduced confusion between technical and policy issues
- ✅ Better debugging with appropriate status codes
- ✅ Consistent with Azure OpenAI content safety practices

## Testing
Run the functional test to verify improvements:
```bash
python functional_tests/test_content_safety_error_handling.py
```

## Version
Implemented in version 0.226.106

## Related Files
- `route_backend_chats.py` - Backend error handling logic
- `static/js/chat/chat-messages.js` - Frontend error display
- `test_content_safety_error_handling.py` - Functional tests

## Example User Flow
1. User submits prompt with potentially harmful content
2. Azure OpenAI blocks request with safety violation
3. Backend detects content safety error and returns 400 with helpful message
4. Frontend displays styled safety message with clear guidance
5. User understands issue and modifies prompt accordingly

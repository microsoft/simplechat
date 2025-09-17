# External Links New Window Fix

**Version:** 0.229.058

## Issue Description
Web links in AI responses and user messages were opening in the same window/tab, replacing the current chat session. This created a poor user experience as users would lose their conversation context when clicking on external links.

## Root Cause Analysis
The issue was in the message rendering pipeline in `chat-messages.js`. When markdown content was parsed using the `marked` library and sanitized with `DOMPurify`, the resulting HTML anchor tags for external links did not include the `target="_blank"` attribute. This caused all external links to open in the current window instead of a new tab/window.

## Technical Details

### Files Modified
- **`static/js/chat/chat-utils.js`**: Added `addTargetBlankToExternalLinks()` utility function
- **`static/js/chat/chat-messages.js`**: Updated message processing to apply the new function
- **`config.py`**: Incremented version from 0.229.019 to 0.229.020

### Solution Implementation
1. **Created utility function**: `addTargetBlankToExternalLinks()` in `chat-utils.js`
   - Identifies external links (HTTP/HTTPS URLs)
   - Adds `target="_blank"` attribute if not present
   - Adds `rel="noopener noreferrer"` for security
   - Preserves existing attributes and enhances them as needed

2. **Updated message processing**: Modified `appendMessage()` function in `chat-messages.js`
   - Applied the function after `DOMPurify.sanitize()` for AI messages
   - Applied the function to user messages
   - Applied the function to safety messages

3. **Security considerations**: 
   - Added `rel="noopener noreferrer"` to prevent potential security issues
   - Maintained DOMPurify sanitization before applying link modifications

### Code Changes Summary
```javascript
// New utility function in chat-utils.js
export function addTargetBlankToExternalLinks(htmlContent) {
  // Parses HTML and adds target="_blank" to external links
}

// Updated message processing in chat-messages.js
const sanitizedHtml = DOMPurify.sanitize(marked.parse(withASCIITables));
const htmlContent = addTargetBlankToExternalLinks(sanitizedHtml);
```

## Testing Approach
- Created functional test: `test_external_links_new_window.py`
- Validates function requirements and integration points
- Ensures proper attributes are added to external links
- Verifies internal links remain unchanged

## User Experience Improvements
- **Before**: External links opened in the same window, losing chat context
- **After**: External links open in new tabs/windows, preserving chat session
- **Security**: Added `rel="noopener noreferrer"` for enhanced security
- **Consistency**: Applied to all message types (AI, user, safety)

## Impact Analysis
- **Scope**: All external HTTP/HTTPS links in chat messages
- **Backward compatibility**: Maintained (no breaking changes)
- **Performance**: Minimal impact (DOM parsing only for messages with links)
- **Security**: Enhanced with proper `rel` attributes

## Version Information
- **Fixed in version**: 0.229.020
- **Implementation date**: September 17, 2025
- **Related functional test**: `test_external_links_new_window.py`

## Validation
✅ External links now open in new windows  
✅ Internal links remain unchanged  
✅ Security attributes properly added  
✅ All message types properly handled  
✅ Functional test passes  
✅ Version updated in config.py
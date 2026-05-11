# Copy Text Message Feature

**Version Implemented:** 0.229.001

## Overview
The Copy Text Message feature provides users with a convenient and intuitive way to copy message content from conversations to their clipboard with a single click, supporting various content types including plain text, formatted content, code blocks, and structured data.

## Purpose
This feature enables users to:
- Quickly copy message content without manual text selection
- Copy formatted content while preserving structure
- Extract code snippets and commands efficiently
- Share conversation content with colleagues and external tools
- Integrate AI responses into other documents and workflows

## Technical Specifications

### Architecture Overview
- **Universal Copy Support**: Copy functionality for all message types (user, assistant, system)
- **Format Preservation**: Maintains formatting when copying to clipboard
- **Smart Content Detection**: Automatically detects and handles different content types
- **Clipboard API Integration**: Uses modern browser clipboard APIs with fallbacks

### JavaScript Implementation
```javascript
class MessageCopyManager {
    constructor() {
        this.copiedMessageId = null;
        this.copyTimeout = null;
        this.initializeEventListeners();
        this.setupClipboardAPI();
    }
    
    initializeEventListeners() {
        // Delegate event listener for copy buttons
        document.addEventListener('click', (event) => {
            const copyButton = event.target.closest('.copy-message-btn');
            if (copyButton) {
                event.preventDefault();
                this.copyMessage(copyButton);
            }
        });
        
        // Keyboard shortcut: Ctrl+C on selected message
        document.addEventListener('keydown', (event) => {
            if (event.ctrlKey && event.key === 'c') {
                const selectedMessage = document.querySelector('.message-selected');
                if (selectedMessage && !window.getSelection().toString()) {
                    event.preventDefault();
                    this.copyMessageContent(selectedMessage);
                }
            }
        });
    }
    
    setupClipboardAPI() {
        // Check for clipboard API support
        this.hasClipboardAPI = navigator.clipboard && navigator.clipboard.writeText;
        this.hasAdvancedClipboard = navigator.clipboard && navigator.clipboard.write;
    }
    
    async copyMessage(buttonElement) {
        const messageElement = buttonElement.closest('.chat-message');
        const messageId = messageElement.dataset.messageId;
        const messageContent = this.extractMessageContent(messageElement);
        
        try {
            await this.copyToClipboard(messageContent);
            this.showCopyFeedback(buttonElement, 'success');
            this.trackCopyEvent(messageId, messageContent.type);
        } catch (error) {
            console.error('Failed to copy message:', error);
            this.showCopyFeedback(buttonElement, 'error');
        }
    }
    
    extractMessageContent(messageElement) {
        const contentElement = messageElement.querySelector('.message-content');
        const messageType = this.detectContentType(contentElement);
        
        switch (messageType) {
            case 'code':
                return this.extractCodeContent(contentElement);
            case 'table':
                return this.extractTableContent(contentElement);
            case 'list':
                return this.extractListContent(contentElement);
            case 'markdown':
                return this.extractMarkdownContent(contentElement);
            default:
                return this.extractPlainContent(contentElement);
        }
    }
    
    detectContentType(contentElement) {
        if (contentElement.querySelector('pre code')) return 'code';
        if (contentElement.querySelector('table')) return 'table';
        if (contentElement.querySelector('ul, ol')) return 'list';
        if (contentElement.querySelector('[data-markdown]')) return 'markdown';
        return 'text';
    }
    
    extractCodeContent(contentElement) {
        const codeBlocks = contentElement.querySelectorAll('pre code');
        let content = '';
        
        if (codeBlocks.length > 0) {
            codeBlocks.forEach((block, index) => {
                const language = block.className.replace('language-', '') || 'text';
                const code = block.textContent;
                
                if (codeBlocks.length > 1) {
                    content += `// Code Block ${index + 1} (${language})\n`;
                }
                content += code;
                if (index < codeBlocks.length - 1) {
                    content += '\n\n';
                }
            });
        } else {
            // Inline code
            const inlineCode = contentElement.querySelectorAll('code');
            content = Array.from(inlineCode).map(code => code.textContent).join('\n');
        }
        
        return {
            type: 'code',
            plainText: content,
            richText: content,
            html: contentElement.innerHTML
        };
    }
    
    extractTableContent(contentElement) {
        const tables = contentElement.querySelectorAll('table');
        let plainText = '';
        let csvText = '';
        
        tables.forEach((table, tableIndex) => {
            const rows = table.querySelectorAll('tr');
            
            if (tableIndex > 0) {
                plainText += '\n\n';
                csvText += '\n\n';
            }
            
            rows.forEach((row, rowIndex) => {
                const cells = row.querySelectorAll('th, td');
                const rowText = Array.from(cells).map(cell => cell.textContent.trim()).join('\t');
                const csvRow = Array.from(cells).map(cell => 
                    `"${cell.textContent.trim().replace(/"/g, '""')}"`
                ).join(',');
                
                plainText += rowText + '\n';
                csvText += csvRow + '\n';
            });
        });
        
        return {
            type: 'table',
            plainText: plainText.trim(),
            csvText: csvText.trim(),
            html: contentElement.innerHTML
        };
    }
    
    extractListContent(contentElement) {
        const lists = contentElement.querySelectorAll('ul, ol');
        let content = '';
        
        lists.forEach((list, index) => {
            if (index > 0) content += '\n\n';
            
            const items = list.querySelectorAll('li');
            const isOrdered = list.tagName.toLowerCase() === 'ol';
            
            items.forEach((item, itemIndex) => {
                const prefix = isOrdered ? `${itemIndex + 1}. ` : '• ';
                content += prefix + item.textContent.trim() + '\n';
            });
        });
        
        return {
            type: 'list',
            plainText: content.trim(),
            richText: content.trim(),
            html: contentElement.innerHTML
        };
    }
    
    extractMarkdownContent(contentElement) {
        // Extract markdown from HTML
        const markdown = this.htmlToMarkdown(contentElement.innerHTML);
        
        return {
            type: 'markdown',
            plainText: contentElement.textContent.trim(),
            markdown: markdown,
            html: contentElement.innerHTML
        };
    }
    
    extractPlainContent(contentElement) {
        return {
            type: 'text',
            plainText: contentElement.textContent.trim(),
            html: contentElement.innerHTML
        };
    }
    
    async copyToClipboard(messageContent) {
        if (this.hasAdvancedClipboard && (messageContent.type === 'table' || messageContent.type === 'code')) {
            // Use advanced clipboard API for rich content
            await this.copyRichContent(messageContent);
        } else if (this.hasClipboardAPI) {
            // Use basic clipboard API
            await navigator.clipboard.writeText(messageContent.plainText);
        } else {
            // Fallback to legacy method
            this.fallbackCopy(messageContent.plainText);
        }
    }
    
    async copyRichContent(messageContent) {
        const clipboardItems = [];
        
        // Add plain text
        clipboardItems.push(new ClipboardItem({
            'text/plain': new Blob([messageContent.plainText], { type: 'text/plain' })
        }));
        
        // Add specific format based on content type
        if (messageContent.type === 'table' && messageContent.csvText) {
            clipboardItems.push(new ClipboardItem({
                'text/csv': new Blob([messageContent.csvText], { type: 'text/csv' })
            }));
        }
        
        if (messageContent.html) {
            clipboardItems.push(new ClipboardItem({
                'text/html': new Blob([messageContent.html], { type: 'text/html' })
            }));
        }
        
        await navigator.clipboard.write(clipboardItems);
    }
    
    fallbackCopy(text) {
        // Legacy clipboard method for older browsers
        const textArea = document.createElement('textarea');
        textArea.value = text;
        textArea.style.position = 'fixed';
        textArea.style.opacity = '0';
        textArea.style.pointerEvents = 'none';
        
        document.body.appendChild(textArea);
        textArea.select();
        textArea.setSelectionRange(0, 99999);
        
        try {
            document.execCommand('copy');
        } finally {
            document.body.removeChild(textArea);
        }
    }
    
    showCopyFeedback(buttonElement, status) {
        const originalContent = buttonElement.innerHTML;
        const originalClass = buttonElement.className;
        
        if (status === 'success') {
            buttonElement.innerHTML = '<i class="fas fa-check"></i>';
            buttonElement.className = buttonElement.className.replace('btn-outline-secondary', 'btn-success');
        } else {
            buttonElement.innerHTML = '<i class="fas fa-times"></i>';
            buttonElement.className = buttonElement.className.replace('btn-outline-secondary', 'btn-danger');
        }
        
        // Reset after 2 seconds
        setTimeout(() => {
            buttonElement.innerHTML = originalContent;
            buttonElement.className = originalClass;
        }, 2000);
    }
    
    trackCopyEvent(messageId, contentType) {
        // Analytics tracking
        fetch('/api/analytics/message-copy', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                messageId,
                contentType,
                timestamp: new Date().toISOString()
            })
        }).catch(error => console.log('Analytics tracking failed:', error));
    }
    
    htmlToMarkdown(html) {
        // Basic HTML to Markdown conversion
        return html
            .replace(/<strong>(.*?)<\/strong>/g, '**$1**')
            .replace(/<em>(.*?)<\/em>/g, '*$1*')
            .replace(/<code>(.*?)<\/code>/g, '`$1`')
            .replace(/<h([1-6])>(.*?)<\/h[1-6]>/g, (match, level, text) => '#'.repeat(level) + ' ' + text)
            .replace(/<p>(.*?)<\/p>/g, '$1\n\n')
            .replace(/<br\s*\/?>/g, '\n')
            .replace(/<[^>]*>/g, ''); // Remove remaining HTML tags
    }
}

// Initialize copy manager
document.addEventListener('DOMContentLoaded', () => {
    window.messageCopyManager = new MessageCopyManager();
});
```

### CSS Styling
```css
.copy-message-btn {
    position: absolute;
    top: 8px;
    right: 8px;
    opacity: 0;
    transition: opacity 0.2s ease, transform 0.2s ease;
    z-index: 10;
    padding: 4px 8px;
    font-size: 12px;
    border-radius: 4px;
    background-color: rgba(255, 255, 255, 0.9);
    border: 1px solid rgba(0, 0, 0, 0.1);
}

.chat-message {
    position: relative;
}

.chat-message:hover .copy-message-btn {
    opacity: 1;
    transform: translateY(0);
}

.copy-message-btn:hover {
    opacity: 1 !important;
    transform: scale(1.05);
    background-color: var(--primary-color);
    color: white;
    border-color: var(--primary-color);
}

.copy-message-btn.copying {
    animation: copyPulse 0.6s ease;
}

@keyframes copyPulse {
    0%, 100% { transform: scale(1); }
    50% { transform: scale(1.1); }
}

/* Code block copy button positioning */
.message-content pre {
    position: relative;
}

.message-content pre .copy-message-btn {
    top: 4px;
    right: 4px;
    background-color: rgba(0, 0, 0, 0.7);
    color: white;
    border: none;
}

/* Table copy button */
.message-content table {
    position: relative;
}

.message-content table .copy-message-btn {
    top: -2px;
    right: -2px;
    background-color: var(--table-header-bg);
}

/* Dark mode support */
[data-bs-theme="dark"] .copy-message-btn {
    background-color: rgba(0, 0, 0, 0.8);
    color: white;
    border-color: rgba(255, 255, 255, 0.2);
}

[data-bs-theme="dark"] .copy-message-btn:hover {
    background-color: var(--primary-color);
    border-color: var(--primary-color);
}

/* Mobile optimizations */
@media (max-width: 768px) {
    .copy-message-btn {
        opacity: 1;
        position: static;
        display: inline-block;
        margin-left: 8px;
        font-size: 11px;
        padding: 2px 6px;
    }
    
    .chat-message .message-actions {
        margin-top: 8px;
        text-align: right;
    }
}

/* Accessibility improvements */
.copy-message-btn:focus {
    opacity: 1;
    outline: 2px solid var(--focus-color);
    outline-offset: 2px;
}

.copy-message-btn[aria-describedby] {
    /* Tooltip support */
}

/* Message selection highlighting */
.message-selected {
    background-color: var(--selection-bg);
    border-left: 3px solid var(--primary-color);
    padding-left: 12px;
}
```

## Configuration Options

### Admin Settings
```html
<div class="copy-message-settings">
    <h6>Message Copy Configuration</h6>
    
    <div class="form-group">
        <div class="form-check">
            <input type="checkbox" id="enable-message-copy" class="form-check-input" checked>
            <label class="form-check-label">Enable Message Copy Functionality</label>
            <small class="form-text text-muted">Allow users to copy message content to clipboard</small>
        </div>
    </div>
    
    <div class="form-group">
        <div class="form-check">
            <input type="checkbox" id="copy-preserve-formatting" class="form-check-input" checked>
            <label class="form-check-label">Preserve Formatting When Copying</label>
            <small class="form-text text-muted">Maintain rich text formatting in copied content</small>
        </div>
    </div>
    
    <div class="form-group">
        <div class="form-check">
            <input type="checkbox" id="copy-include-metadata" class="form-check-input">
            <label class="form-check-label">Include Message Metadata in Copy</label>
            <small class="form-text text-muted">Add timestamp and sender information to copied content</small>
        </div>
    </div>
    
    <div class="form-group">
        <label>Copy Button Position</label>
        <select class="form-control" id="copy-button-position">
            <option value="top-right" selected>Top Right (Hover)</option>
            <option value="bottom-right">Bottom Right (Always Visible)</option>
            <option value="inline">Inline with Message Actions</option>
        </select>
    </div>
    
    <div class="form-group">
        <div class="form-check">
            <input type="checkbox" id="copy-analytics" class="form-check-input" checked>
            <label class="form-check-label">Track Copy Usage Analytics</label>
            <small class="form-text text-muted">Collect anonymous usage statistics for copy functionality</small>
        </div>
    </div>
</div>
```

### Content Type Handling
```javascript
const copyConfiguration = {
    contentTypes: {
        text: {
            enabled: true,
            format: 'plain'
        },
        code: {
            enabled: true,
            format: 'preserveLanguage',
            includeLanguageComment: true
        },
        table: {
            enabled: true,
            format: 'csv',
            alternativeFormats: ['tsv', 'markdown']
        },
        list: {
            enabled: true,
            format: 'markdown',
            preserveNesting: true
        },
        markdown: {
            enabled: true,
            format: 'markdown',
            fallbackToPlain: true
        }
    },
    ui: {
        showCopyButton: 'hover',
        animationDuration: 200,
        feedbackDuration: 2000,
        buttonSize: 'small'
    },
    advanced: {
        enableKeyboardShortcuts: true,
        enableBulkCopy: false,
        maxContentLength: 50000,
        enableClipboardAPI: true
    }
};
```

## Usage Instructions

### For End Users

#### Basic Message Copying
1. **Hover Over Message**: Move your cursor over any message in the conversation
2. **Click Copy Button**: Click the copy icon (📋) that appears in the top-right corner
3. **Visual Confirmation**: The button will briefly change to a checkmark (✓) indicating successful copy
4. **Paste Content**: Use Ctrl+V (or Cmd+V on Mac) to paste the content elsewhere

#### Keyboard Shortcuts
- **Select and Copy**: Click a message to select it, then press Ctrl+C to copy
- **Quick Copy**: Hover over a message and press C to copy without clicking

#### Content-Specific Copying

**Code Blocks:**
- Copies clean code without syntax highlighting
- Preserves indentation and line breaks
- Includes language information as a comment

**Tables:**
- Copies as tab-separated values for easy pasting into spreadsheets
- Maintains column structure
- Headers are preserved

**Lists:**
- Preserves bullet points and numbering
- Maintains nested list structure
- Converts to plain text format

#### Advanced Copy Options
```html
<!-- Context menu for advanced copy options -->
<div class="copy-options-menu">
    <button class="copy-option" data-format="plain">Copy as Plain Text</button>
    <button class="copy-option" data-format="markdown">Copy as Markdown</button>
    <button class="copy-option" data-format="html">Copy as HTML</button>
    <button class="copy-option" data-format="csv" data-visible-for="table">Copy as CSV</button>
</div>
```

### For Administrators

#### Monitoring Copy Usage
```javascript
class CopyAnalytics {
    generateCopyReport(dateRange) {
        return {
            totalCopies: 0,
            contentTypeBreakdown: {
                text: 0,
                code: 0,
                table: 0,
                list: 0
            },
            topCopiedMessages: [],
            userEngagement: {
                activeUsers: 0,
                averageCopiesPerUser: 0
            },
            trends: {
                dailyCopies: [],
                peakUsageHours: []
            }
        };
    }
}
```

#### Content Policy Configuration
```javascript
const copyPolicyConfig = {
    restrictions: {
        maxCopiesPerHour: 100,
        maxContentLength: 10000,
        blockedContentPatterns: [
            /sensitive.*information/i,
            /confidential/i
        ]
    },
    auditLogging: {
        enabled: true,
        includeContent: false,
        retentionDays: 90
    },
    security: {
        watermarkCopiedContent: false,
        trackCopyDestination: false,
        preventBulkCopy: true
    }
};
```

## Integration Points

### Search Integration
```javascript
// Integration with conversation search
document.addEventListener('messageCopied', (event) => {
    const { messageId, content } = event.detail;
    
    // Update search rankings based on copy frequency
    if (window.conversationSearch) {
        window.conversationSearch.updateMessagePopularity(messageId);
    }
});
```

### Export Integration
```javascript
class ConversationExporter {
    includeCopyStatistics(conversation) {
        const messages = conversation.messages.map(message => ({
            ...message,
            copyCount: this.getCopyCount(message.id),
            lastCopied: this.getLastCopyDate(message.id)
        }));
        
        return { ...conversation, messages };
    }
}
```

### Plugin Integration
```javascript
// Allow plugins to customize copy behavior
class CopyPluginManager {
    registerCopyHandler(contentType, handler) {
        this.copyHandlers[contentType] = handler;
    }
    
    processCopyRequest(content, type) {
        const handler = this.copyHandlers[type];
        return handler ? handler(content) : content;
    }
}
```

## Security Considerations

### Content Sanitization
```javascript
class CopySecurityManager {
    sanitizeCopyContent(content) {
        // Remove sensitive patterns
        const sensitivePatterns = [
            /\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b/g, // emails
            /\b\d{4}\s?\d{4}\s?\d{4}\s?\d{4}\b/g, // credit cards
            /\b\d{3}-\d{2}-\d{4}\b/g // SSNs
        ];
        
        let sanitized = content;
        sensitivePatterns.forEach(pattern => {
            sanitized = sanitized.replace(pattern, '[REDACTED]');
        });
        
        return sanitized;
    }
    
    auditCopyEvent(userId, messageId, contentType) {
        fetch('/api/audit/copy-event', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                userId,
                messageId,
                contentType,
                timestamp: new Date().toISOString(),
                userAgent: navigator.userAgent
            })
        });
    }
}
```

### Privacy Protection
```javascript
class CopyPrivacyManager {
    shouldAllowCopy(messageContent, userRole) {
        // Check if content contains sensitive information
        if (this.containsSensitiveData(messageContent)) {
            return userRole === 'Admin';
        }
        
        return true;
    }
    
    containsSensitiveData(content) {
        const sensitiveKeywords = [
            'password', 'secret', 'token', 'api key',
            'confidential', 'internal only'
        ];
        
        return sensitiveKeywords.some(keyword => 
            content.toLowerCase().includes(keyword)
        );
    }
}
```

## Testing and Validation

### Functional Testing
- Verify copy functionality across all message types and browsers
- Test keyboard shortcuts and accessibility features
- Validate content formatting preservation in different applications
- Confirm error handling for clipboard API failures

### Performance Testing
- Measure copy operation performance with large content blocks
- Test memory usage during bulk copy operations
- Validate responsiveness during copy feedback animations
- Check impact on overall application performance

### Security Testing
- Verify content sanitization for sensitive data
- Test copy restrictions and rate limiting
- Validate audit logging functionality
- Confirm privacy protection mechanisms

## Known Limitations
- Clipboard API support varies across browsers and requires HTTPS
- Some applications may not preserve rich formatting when pasting
- Large content blocks may cause performance issues
- Mobile devices may have limited clipboard functionality

## Browser Compatibility
- **Full Support**: Chrome 76+, Firefox 90+, Safari 13.1+, Edge 79+
- **Basic Support**: Earlier browsers with fallback to legacy copy methods
- **Mobile Support**: iOS Safari 13.4+, Android Chrome 84+

## Future Enhancements
- Bulk copy for multiple selected messages
- Copy templates with customizable formatting
- Integration with external clipboard managers
- AI-powered content summarization for large copies
- Copy history and recently copied items
- Advanced content transformation options (e.g., translate while copying)
- Integration with collaboration tools and document editors
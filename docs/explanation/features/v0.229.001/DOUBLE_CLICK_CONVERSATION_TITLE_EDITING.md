# Double-Click Conversation Title Editing Feature

**Version Implemented:** 0.229.001

## Overview
The Double-Click Conversation Title Editing feature provides users with an intuitive and efficient way to rename conversations directly within the chat interface by simply double-clicking on conversation titles, eliminating the need for separate edit dialogs or menu navigation.

## Purpose
This feature enables users to:
- Quickly rename conversations with a natural double-click gesture
- Edit conversation titles without interrupting their workflow
- Organize conversations more efficiently with descriptive names
- Improve conversation management through intuitive interaction patterns
- Maintain focus within the chat interface while organizing content

## Technical Specifications

### Architecture Overview
- **Inline Editing**: Direct text editing within the conversation title element
- **Event Handling**: Double-click detection with debouncing to prevent conflicts
- **Auto-Save**: Automatic saving of changes with validation
- **Keyboard Support**: Enter to save, Escape to cancel editing

### JavaScript Implementation
```javascript
class ConversationTitleEditor {
    constructor() {
        this.isEditing = false;
        this.originalTitle = '';
        this.editTimeout = null;
        this.maxTitleLength = 100;
        this.initializeEventListeners();
    }
    
    initializeEventListeners() {
        document.addEventListener('dblclick', (event) => {
            const titleElement = event.target.closest('.conversation-title');
            if (titleElement && !this.isEditing) {
                this.startEditing(titleElement);
            }
        });
        
        document.addEventListener('keydown', (event) => {
            if (this.isEditing) {
                this.handleKeyPress(event);
            }
        });
        
        document.addEventListener('click', (event) => {
            if (this.isEditing && !event.target.closest('.conversation-title-input')) {
                this.finishEditing(true); // Save changes
            }
        });
    }
    
    startEditing(titleElement) {
        this.isEditing = true;
        this.originalTitle = titleElement.textContent.trim();
        
        // Create input element
        const input = document.createElement('input');
        input.className = 'conversation-title-input form-control form-control-sm';
        input.type = 'text';
        input.value = this.originalTitle;
        input.maxLength = this.maxTitleLength;
        input.style.width = '100%';
        input.style.fontSize = window.getComputedStyle(titleElement).fontSize;
        
        // Replace title with input
        const parent = titleElement.parentNode;
        parent.replaceChild(input, titleElement);
        
        // Focus and select text
        input.focus();
        input.select();
        
        // Store references
        this.currentInput = input;
        this.titleElement = titleElement;
        this.parentElement = parent;
        
        // Add visual indicator
        parent.classList.add('editing-title');
    }
    
    handleKeyPress(event) {
        switch (event.key) {
            case 'Enter':
                event.preventDefault();
                this.finishEditing(true);
                break;
            case 'Escape':
                event.preventDefault();
                this.finishEditing(false);
                break;
        }
    }
    
    async finishEditing(save) {
        if (!this.isEditing) return;
        
        const newTitle = save ? this.currentInput.value.trim() : this.originalTitle;
        
        // Validate title
        if (save && newTitle && newTitle !== this.originalTitle) {
            try {
                await this.saveConversationTitle(
                    this.getConversationId(),
                    newTitle
                );
                this.originalTitle = newTitle;
            } catch (error) {
                console.error('Failed to save conversation title:', error);
                this.showErrorMessage('Failed to save title. Please try again.');
                // Revert to original title
                newTitle = this.originalTitle;
            }
        }
        
        // Restore title element
        this.titleElement.textContent = newTitle || this.originalTitle;
        this.parentElement.replaceChild(this.titleElement, this.currentInput);
        this.parentElement.classList.remove('editing-title');
        
        // Cleanup
        this.isEditing = false;
        this.currentInput = null;
        this.titleElement = null;
        this.parentElement = null;
    }
    
    getConversationId() {
        // Extract conversation ID from current context
        return document.body.dataset.conversationId || 
               this.currentInput.closest('[data-conversation-id]')?.dataset.conversationId;
    }
    
    async saveConversationTitle(conversationId, newTitle) {
        const response = await fetch(`/api/conversations/${conversationId}/title`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json',
                'X-Requested-With': 'XMLHttpRequest'
            },
            body: JSON.stringify({ title: newTitle })
        });
        
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }
        
        // Update title in conversation list if visible
        this.updateConversationListTitle(conversationId, newTitle);
        
        // Trigger event for other components
        document.dispatchEvent(new CustomEvent('conversationTitleUpdated', {
            detail: { conversationId, newTitle }
        }));
    }
    
    updateConversationListTitle(conversationId, newTitle) {
        const conversationListItem = document.querySelector(
            `.conversation-list-item[data-conversation-id="${conversationId}"] .conversation-title`
        );
        
        if (conversationListItem) {
            conversationListItem.textContent = newTitle;
        }
    }
    
    showErrorMessage(message) {
        // Show toast notification or error message
        if (typeof showToast === 'function') {
            showToast(message, 'error');
        } else {
            alert(message); // Fallback
        }
    }
}

// Initialize the title editor
document.addEventListener('DOMContentLoaded', () => {
    window.conversationTitleEditor = new ConversationTitleEditor();
});
```

### CSS Styling
```css
.conversation-title {
    cursor: pointer;
    padding: 4px 8px;
    border-radius: 4px;
    transition: background-color 0.2s ease;
    user-select: none;
    max-width: 300px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.conversation-title:hover {
    background-color: var(--hover-bg-color);
}

.conversation-title-input {
    min-width: 200px;
    max-width: 400px;
    border: 2px solid var(--primary-color);
    border-radius: 4px;
    padding: 4px 8px;
    font-size: inherit;
    font-family: inherit;
    background-color: var(--input-bg);
    color: var(--text-color);
}

.conversation-title-input:focus {
    outline: none;
    border-color: var(--primary-color);
    box-shadow: 0 0 0 0.2rem rgba(var(--primary-color-rgb), 0.25);
}

.editing-title {
    position: relative;
}

.editing-title::after {
    content: '';
    position: absolute;
    top: -2px;
    left: -2px;
    right: -2px;
    bottom: -2px;
    border: 1px dashed var(--primary-color);
    border-radius: 6px;
    pointer-events: none;
    opacity: 0.5;
}

/* Dark mode support */
[data-bs-theme="dark"] .conversation-title:hover {
    background-color: var(--hover-bg-color-dark);
}

[data-bs-theme="dark"] .conversation-title-input {
    background-color: var(--input-bg-dark);
    color: var(--text-color-dark);
    border-color: var(--primary-color-dark);
}

/* Visual feedback for editable titles */
.conversation-title[data-editable="true"]::before {
    content: "✎";
    font-size: 0.8em;
    opacity: 0;
    margin-right: 4px;
    transition: opacity 0.2s ease;
}

.conversation-title[data-editable="true"]:hover::before {
    opacity: 0.6;
}

/* Mobile-specific styles */
@media (max-width: 768px) {
    .conversation-title-input {
        min-width: 150px;
        max-width: 250px;
        font-size: 14px;
    }
    
    .conversation-title {
        max-width: 200px;
    }
}
```

## Configuration Options

### Admin Settings
```html
<div class="conversation-title-editing-settings">
    <h6>Conversation Title Editing</h6>
    
    <div class="form-group">
        <div class="form-check">
            <input type="checkbox" id="enable-title-editing" class="form-check-input" checked>
            <label class="form-check-label">Enable Double-Click Title Editing</label>
            <small class="form-text text-muted">Allow users to edit conversation titles by double-clicking</small>
        </div>
    </div>
    
    <div class="form-group">
        <label>Maximum Title Length</label>
        <input type="number" id="max-title-length" class="form-control" value="100" min="20" max="200">
        <small class="form-text text-muted">Maximum characters allowed in conversation titles</small>
    </div>
    
    <div class="form-group">
        <div class="form-check">
            <input type="checkbox" id="auto-save-titles" class="form-check-input" checked>
            <label class="form-check-label">Auto-save Title Changes</label>
            <small class="form-text text-muted">Automatically save title changes without confirmation</small>
        </div>
    </div>
    
    <div class="form-group">
        <div class="form-check">
            <input type="checkbox" id="show-edit-indicator" class="form-check-input" checked>
            <label class="form-check-label">Show Edit Indicator on Hover</label>
            <small class="form-text text-muted">Display pencil icon when hovering over editable titles</small>
        </div>
    </div>
</div>
```

### JavaScript Configuration
```javascript
const titleEditingConfig = {
    enabled: true,
    maxLength: 100,
    autoSave: true,
    showEditIndicator: true,
    debounceDelay: 300,
    validation: {
        minLength: 1,
        maxLength: 100,
        allowedCharacters: /^[a-zA-Z0-9\s\-_\.,:;!?\(\)\[\]]+$/,
        forbiddenWords: ['untitled', 'new chat', 'conversation']
    },
    ui: {
        showHoverEffect: true,
        animationDuration: 200,
        autoSelectText: true,
        focusOnEdit: true
    }
};
```

## Usage Instructions

### For End Users

#### Editing Conversation Titles
1. **Locate Conversation Title**: Find the conversation title in the chat header or conversation list
2. **Double-Click**: Double-click on the title text to enter edit mode
3. **Edit Text**: Type the new conversation title (up to 100 characters)
4. **Save Changes**:
   - Press **Enter** to save the new title
   - Press **Escape** to cancel editing and revert to original title
   - Click elsewhere to save changes and exit edit mode

#### Best Practices for Conversation Titles
- **Be Descriptive**: Use titles that clearly describe the conversation topic
- **Keep It Concise**: Aim for 20-50 characters for optimal display
- **Use Keywords**: Include important keywords for easier searching
- **Avoid Generic Names**: Replace "New Chat" with specific topics

#### Visual Feedback
- **Hover Effect**: Titles show subtle background change when hovering
- **Edit Indicator**: Small pencil icon appears on hover (if enabled)
- **Active Editing**: Input field with blue border indicates active editing
- **Dashed Border**: Subtle dashed outline shows editing area

### For Administrators

#### Managing Title Editing Settings
1. **Access Admin Settings**: Navigate to Admin Settings → UI Configuration
2. **Configure Options**: Adjust title editing preferences
3. **Set Limits**: Define maximum title length and validation rules
4. **Enable/Disable**: Toggle the feature on/off organization-wide

#### Monitoring Title Changes
```javascript
// Track title editing usage
document.addEventListener('conversationTitleUpdated', (event) => {
    const { conversationId, newTitle } = event.detail;
    
    // Log title change for analytics
    fetch('/api/analytics/title-change', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            conversationId,
            newTitle,
            timestamp: new Date().toISOString(),
            action: 'title_edit'
        })
    });
});
```

## Integration Points

### Conversation Management Integration
```javascript
// Integration with conversation loading
class ConversationManager {
    loadConversation(conversationId) {
        // Load conversation and update title display
        this.fetchConversation(conversationId).then(conversation => {
            this.updateConversationTitle(conversation.title);
            this.markTitleAsEditable(conversation.id);
        });
    }
    
    updateConversationTitle(title) {
        const titleElement = document.querySelector('.current-conversation-title');
        if (titleElement) {
            titleElement.textContent = title;
            titleElement.setAttribute('data-editable', 'true');
        }
    }
    
    markTitleAsEditable(conversationId) {
        const titleElement = document.querySelector('.conversation-title');
        if (titleElement) {
            titleElement.setAttribute('data-conversation-id', conversationId);
            titleElement.setAttribute('data-editable', 'true');
        }
    }
}
```

### Search Integration
```javascript
// Update search when titles change
document.addEventListener('conversationTitleUpdated', (event) => {
    const { conversationId, newTitle } = event.detail;
    
    // Update search index
    if (window.conversationSearch) {
        window.conversationSearch.updateConversationTitle(conversationId, newTitle);
    }
    
    // Update conversation list filter
    if (window.conversationFilter) {
        window.conversationFilter.refresh();
    }
});
```

### Keyboard Accessibility
```javascript
// Enhanced keyboard support
class TitleEditingAccessibility {
    constructor() {
        this.setupKeyboardNavigation();
        this.setupScreenReaderSupport();
    }
    
    setupKeyboardNavigation() {
        document.addEventListener('keydown', (event) => {
            // F2 key to start editing focused title
            if (event.key === 'F2' && !event.ctrlKey && !event.altKey) {
                const focusedTitle = document.activeElement.closest('.conversation-title');
                if (focusedTitle) {
                    event.preventDefault();
                    window.conversationTitleEditor.startEditing(focusedTitle);
                }
            }
        });
    }
    
    setupScreenReaderSupport() {
        // Add ARIA labels and live regions
        document.querySelectorAll('.conversation-title').forEach(title => {
            title.setAttribute('role', 'button');
            title.setAttribute('aria-label', 'Double-click to edit conversation title');
            title.setAttribute('tabindex', '0');
        });
    }
}
```

## User Experience Enhancements

### Animation and Transitions
```css
.conversation-title {
    transition: all 0.2s ease;
}

.conversation-title-input {
    animation: focusIn 0.2s ease;
}

@keyframes focusIn {
    from {
        transform: scale(0.95);
        opacity: 0.7;
    }
    to {
        transform: scale(1);
        opacity: 1;
    }
}

.editing-title {
    animation: editHighlight 0.3s ease;
}

@keyframes editHighlight {
    0%, 100% { background-color: transparent; }
    50% { background-color: var(--highlight-color); }
}
```

### Error Handling and Validation
```javascript
class TitleValidation {
    static validate(title) {
        const errors = [];
        
        if (!title || title.trim().length === 0) {
            errors.push('Title cannot be empty');
        }
        
        if (title.length > titleEditingConfig.maxLength) {
            errors.push(`Title cannot exceed ${titleEditingConfig.maxLength} characters`);
        }
        
        if (title.length < titleEditingConfig.validation.minLength) {
            errors.push(`Title must be at least ${titleEditingConfig.validation.minLength} character`);
        }
        
        if (!titleEditingConfig.validation.allowedCharacters.test(title)) {
            errors.push('Title contains invalid characters');
        }
        
        if (titleEditingConfig.validation.forbiddenWords.some(word => 
            title.toLowerCase().includes(word.toLowerCase()))) {
            errors.push('Please choose a more descriptive title');
        }
        
        return {
            isValid: errors.length === 0,
            errors
        };
    }
}
```

### Auto-Save with Debouncing
```javascript
class AutoSaveTitleManager {
    constructor() {
        this.saveTimeout = null;
        this.saveDelay = 1000; // 1 second delay
    }
    
    scheduleAutoSave(conversationId, title) {
        // Cancel previous auto-save
        if (this.saveTimeout) {
            clearTimeout(this.saveTimeout);
        }
        
        // Schedule new auto-save
        this.saveTimeout = setTimeout(() => {
            this.saveTitle(conversationId, title);
        }, this.saveDelay);
    }
    
    async saveTitle(conversationId, title) {
        try {
            await window.conversationTitleEditor.saveConversationTitle(conversationId, title);
            this.showAutoSaveIndicator();
        } catch (error) {
            this.showAutoSaveError();
        }
    }
    
    showAutoSaveIndicator() {
        // Show brief "saved" indicator
        const indicator = document.createElement('span');
        indicator.className = 'auto-save-indicator';
        indicator.textContent = '✓ Saved';
        indicator.style.cssText = `
            position: absolute;
            top: -20px;
            right: 0;
            font-size: 12px;
            color: var(--success-color);
            opacity: 1;
            transition: opacity 0.5s ease;
        `;
        
        document.body.appendChild(indicator);
        
        setTimeout(() => {
            indicator.style.opacity = '0';
            setTimeout(() => indicator.remove(), 500);
        }, 2000);
    }
}
```

## Testing and Validation

### Functional Testing
- Verify double-click detection works across different browsers
- Test keyboard shortcuts (Enter, Escape, F2) for title editing
- Validate title saving and error handling
- Confirm conversation list updates when titles change

### Accessibility Testing
- Test with screen readers for proper ARIA labeling
- Verify keyboard-only navigation works correctly
- Check focus management during edit mode
- Validate color contrast for edit indicators

### Usability Testing
- Test with various title lengths and special characters
- Verify behavior on mobile devices with touch interfaces
- Check integration with conversation search and filtering
- Validate performance with large numbers of conversations

## Known Limitations
- Double-click detection may interfere with text selection in some browsers
- Mobile devices may require special handling for double-tap gestures
- Very long titles may cause layout issues on smaller screens
- Auto-save may conflict with rapid successive edits

## Browser Compatibility
- **Full Support**: Chrome 90+, Firefox 88+, Safari 14+, Edge 90+
- **Touch Support**: iOS Safari 14+, Android Chrome 90+
- **Keyboard Support**: All modern browsers with full keyboard navigation

## Future Enhancements
- Drag-and-drop title reordering in conversation lists
- Title suggestions based on conversation content
- Bulk title editing for multiple conversations
- Integration with conversation templates and categories
- Advanced title formatting options (bold, italics, emojis)
- Title history and version tracking
- AI-powered automatic title generation based on conversation content
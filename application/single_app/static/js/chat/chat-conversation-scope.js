// chat-conversation-scope.js

function sanitizeScopeId(rawValue) {
    if (!rawValue && rawValue !== 0) {
        return null;
    }

    const normalizedValue = String(rawValue).trim();
    if (!normalizedValue) {
        return null;
    }

    const loweredValue = normalizedValue.toLowerCase();
    if (loweredValue === 'none' || loweredValue === 'null' || loweredValue === 'undefined') {
        return null;
    }

    return normalizedValue;
}

export function getActiveConversationContext() {
    const activeItem = document.querySelector('.conversation-item.active');
    const chatType = activeItem?.getAttribute('data-chat-type') || '';
    const chatState = activeItem?.getAttribute('data-chat-state') || '';
    const groupId = sanitizeScopeId(activeItem?.getAttribute('data-group-id'));
    const publicWorkspaceId = sanitizeScopeId(activeItem?.getAttribute('data-public-workspace-id'));

    return {
        activeItem,
        chatType,
        chatState,
        groupId,
        publicWorkspaceId,
    };
}

export function getActiveConversationScope() {
    const { activeItem, chatType, chatState } = getActiveConversationContext();

    if (!activeItem || chatType === 'new' || chatState === 'new') {
        return null;
    }

    if (chatType.startsWith('group')) {
        return 'group';
    }

    if (chatType.startsWith('public')) {
        return 'public';
    }

    return 'personal';
}

export function isActiveConversationNew() {
    const { activeItem, chatType, chatState } = getActiveConversationContext();
    return !activeItem || chatType === 'new' || chatState === 'new';
}

export function getConversationFilteringContext() {
    const conversationScope = getActiveConversationScope();
    const { activeItem, chatType, chatState, groupId, publicWorkspaceId } = getActiveConversationContext();

    return {
        activeItem,
        chatType,
        chatState,
        groupId,
        publicWorkspaceId,
        conversationScope,
        isNewConversation: isActiveConversationNew(),
    };
}
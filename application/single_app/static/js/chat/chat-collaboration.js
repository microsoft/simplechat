// chat-collaboration.js

import { appendMessage, getCollaborativeTagSuggestions, updateSendButtonVisibility, updateUserMessageId, userInput } from './chat-messages.js';
import { applyConversationMetadataUpdate } from './chat-conversations.js';
import { loadUserSettings, saveUserSetting } from './chat-layout.js';
import { showToast } from './chat-toast.js';
import { sendMessageWithStreaming } from './chat-streaming.js';

const RECENT_COLLABORATORS_KEY = 'recentCollaborators';
const MAX_RECENT_COLLABORATORS = 12;
const DEFAULT_SUGGESTION_LIMIT = 8;

const mentionMenu = document.getElementById('collaboration-mention-menu');
const participantModalEl = document.getElementById('collaboration-participant-modal');
const participantSearchInput = document.getElementById('collaboration-participant-search-input');
const participantResults = document.getElementById('collaboration-participant-results');
const participantConversationIdInput = document.getElementById('collaboration-participant-conversation-id');
const confirmModalEl = document.getElementById('collaboration-confirm-modal');
const confirmMessageEl = document.getElementById('collaboration-confirm-message');
const confirmAddBtn = document.getElementById('collaboration-confirm-add-btn');
const replyPreviewEl = document.getElementById('collaboration-reply-preview');
const replyPreviewLabelEl = document.getElementById('collaboration-reply-preview-label');
const replyPreviewTextEl = document.getElementById('collaboration-reply-preview-text');
const replyCancelBtn = document.getElementById('collaboration-reply-cancel-btn');
const sendBtn = document.getElementById('send-btn');

let cachedUserSettingsPromise = null;
let activeCollaborativeConversationId = null;
let activeCollaborationEventSource = null;
let activeSubscriptionStartedAt = 0;
let activeReplyContext = null;
let typingUsers = new Map();
let lastTypingState = false;
let typingStopHandle = null;
let mentionSearchToken = 0;
let activeMentionState = null;
let pendingParticipantConfirmation = null;
const notifiedPendingInviteConversationIds = new Set();
const promptedPendingInviteConversationIds = new Set();
const seenCollaborationEventKeys = new Set();
const collaborationMessageCache = new Map();
const collaborationConversationCache = new Map();
const collaborationMarkReadRequests = new Map();

function isCollaborationEnabled() {
    return Boolean(window.appSettings?.enable_collaborative_conversations);
}

function getConversationDomItem(conversationId) {
    if (!conversationId) {
        return null;
    }

    return document.querySelector(`.conversation-item[data-conversation-id="${conversationId}"]`)
        || document.querySelector(`.sidebar-conversation-item[data-conversation-id="${conversationId}"]`);
}

function getConversationKind(conversationId) {
    const item = getConversationDomItem(conversationId);
    return item?.dataset?.conversationKind || null;
}

function isCollaborationConversation(conversationId) {
    return getConversationKind(conversationId) === 'collaborative';
}

function getConversationChatType(conversationId) {
    const item = getConversationDomItem(conversationId);
    return item?.getAttribute('data-chat-type') || null;
}

function markCollaborationConversationRead(conversationId, options = {}) {
    const { suppressErrorToast = false } = options;
    if (!conversationId) {
        return Promise.resolve(null);
    }

    if (collaborationMarkReadRequests.has(conversationId)) {
        return collaborationMarkReadRequests.get(conversationId);
    }

    const request = fetch(`/api/collaboration/conversations/${conversationId}/mark-read`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
    })
        .then(async response => {
            const payload = await response.json().catch(() => ({}));
            if (!response.ok || payload.success === false) {
                throw new Error(payload.error || 'Failed to clear shared conversation notifications');
            }
            return payload;
        })
        .catch(error => {
            if (!suppressErrorToast) {
                showToast(`Failed to clear shared conversation notifications: ${error.message}`, 'danger');
            }
            throw error;
        })
        .finally(() => {
            collaborationMarkReadRequests.delete(conversationId);
        });

    collaborationMarkReadRequests.set(conversationId, request);
    return request;
}

function setConversationDataset(conversationId, metadata = {}) {
    const conversationSelectors = [
        `.conversation-item[data-conversation-id="${conversationId}"]`,
        `.sidebar-conversation-item[data-conversation-id="${conversationId}"]`,
    ];

    conversationSelectors.forEach(selector => {
        const element = document.querySelector(selector);
        if (!element) {
            return;
        }

        if (metadata.conversation_kind) {
            element.dataset.conversationKind = metadata.conversation_kind;
        }
        if (metadata.membership_status) {
            element.dataset.membershipStatus = metadata.membership_status;
        }
        if (Object.prototype.hasOwnProperty.call(metadata, 'can_manage_members')) {
            element.dataset.canManageMembers = metadata.can_manage_members ? 'true' : 'false';
        }
        if (Object.prototype.hasOwnProperty.call(metadata, 'can_manage_roles')) {
            element.dataset.canManageRoles = metadata.can_manage_roles ? 'true' : 'false';
        }
        if (Object.prototype.hasOwnProperty.call(metadata, 'can_accept_invite')) {
            element.dataset.canAcceptInvite = metadata.can_accept_invite ? 'true' : 'false';
        }
        if (Object.prototype.hasOwnProperty.call(metadata, 'can_post_messages')) {
            element.dataset.canPostMessages = metadata.can_post_messages ? 'true' : 'false';
        }
        if (Object.prototype.hasOwnProperty.call(metadata, 'can_delete_conversation')) {
            element.dataset.canDeleteConversation = metadata.can_delete_conversation ? 'true' : 'false';
        }
        if (Object.prototype.hasOwnProperty.call(metadata, 'can_leave_conversation')) {
            element.dataset.canLeaveConversation = metadata.can_leave_conversation ? 'true' : 'false';
        }
        if (Object.prototype.hasOwnProperty.call(metadata, 'current_user_role')) {
            element.dataset.currentUserRole = metadata.current_user_role || '';
        }
    });
}

function normalizeCollaborator(rawUser) {
    if (!rawUser || typeof rawUser !== 'object') {
        return null;
    }

    const userId = String(rawUser.user_id || rawUser.userId || rawUser.id || '').trim();
    if (!userId) {
        return null;
    }

    const displayName = String(rawUser.display_name || rawUser.displayName || rawUser.name || rawUser.email || '').trim();
    const email = String(rawUser.email || rawUser.mail || '').trim();
    return {
        user_id: userId,
        display_name: displayName || email || 'Unknown User',
        email,
    };
}

function normalizeCollaborationConversation(rawConversation = {}) {
    const normalizedParticipants = Array.isArray(rawConversation.participants)
        ? rawConversation.participants
            .map(participant => {
                const normalizedParticipant = normalizeCollaborator(participant);
                if (!normalizedParticipant) {
                    return null;
                }

                return {
                    ...participant,
                    ...normalizedParticipant,
                    role: String(participant?.role || '').trim(),
                    status: String(participant?.status || '').trim().toLowerCase(),
                };
            })
            .filter(Boolean)
        : [];

    return {
        ...rawConversation,
        conversation_kind: rawConversation.conversation_kind || 'collaborative',
        last_updated: rawConversation.last_updated || rawConversation.updated_at || rawConversation.last_message_at || rawConversation.created_at || new Date().toISOString(),
        classification: Array.isArray(rawConversation.classification) ? rawConversation.classification : [],
        tags: Array.isArray(rawConversation.tags) ? rawConversation.tags : [],
        context: Array.isArray(rawConversation.context) ? rawConversation.context : [],
        participants: normalizedParticipants,
        is_pinned: Boolean(rawConversation.is_pinned),
        is_hidden: Boolean(rawConversation.is_hidden),
        has_unread_assistant_response: Boolean(rawConversation.has_unread_assistant_response),
    };
}

function cacheCollaborationConversation(rawConversation = {}) {
    const normalizedConversation = normalizeCollaborationConversation(rawConversation);
    if (!normalizedConversation.id) {
        return normalizedConversation;
    }

    collaborationConversationCache.set(normalizedConversation.id, normalizedConversation);
    return normalizedConversation;
}

function getCachedCollaborationConversation(conversationId) {
    if (!conversationId) {
        return null;
    }

    return collaborationConversationCache.get(conversationId) || null;
}

function getConversationParticipants(conversationId, options = {}) {
    const currentUserId = getCurrentUserId();
    const conversation = getCachedCollaborationConversation(conversationId);
    const participants = Array.isArray(conversation?.participants) ? conversation.participants : [];

    return participants.filter(participant => {
        const participantUserId = String(participant?.user_id || '').trim();
        if (!participantUserId) {
            return false;
        }
        if (!options.includeCurrentUser && participantUserId === currentUserId) {
            return false;
        }

        const participantStatus = String(participant?.status || '').trim().toLowerCase();
        return !participantStatus || participantStatus === 'accepted';
    });
}

function escapeRegExp(value) {
    return String(value || '').replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function matchesMentionQuery(collaborator, query = '') {
    const normalizedQuery = String(query || '').trim().toLowerCase();
    if (!normalizedQuery) {
        return true;
    }

    const haystack = `${collaborator?.display_name || ''} ${collaborator?.email || ''}`.trim().toLowerCase();
    return haystack.includes(normalizedQuery);
}

function buildMentionSuggestionsFromParticipants(conversationId, query = '') {
    return getConversationParticipants(conversationId).filter(participant => matchesMentionQuery(participant, query)).map(participant => ({
        ...participant,
        action: 'tag',
        source: 'participant',
    }));
}

async function loadMentionSuggestions(conversationId, query = '') {
    const participantSuggestions = buildMentionSuggestionsFromParticipants(conversationId, query);
    const targetSuggestions = getCollaborativeTagSuggestions(query);
    const seenUserIds = new Set(participantSuggestions.map(participant => participant.user_id));

    if (!canUseParticipantFlow(conversationId)) {
        return [...participantSuggestions, ...targetSuggestions].slice(0, DEFAULT_SUGGESTION_LIMIT);
    }

    const collaboratorSuggestions = await searchLocalCollaborators(query, {
        recentOnly: false,
        limit: DEFAULT_SUGGESTION_LIMIT,
    });
    const inviteSuggestions = collaboratorSuggestions
        .map(collaborator => {
            const normalizedCollaborator = normalizeCollaborator(collaborator);
            if (!normalizedCollaborator) {
                return null;
            }

            return {
                ...normalizedCollaborator,
                source: collaborator.source || 'local',
            };
        })
        .filter(Boolean)
        .filter(collaborator => !seenUserIds.has(collaborator.user_id))
        .map(collaborator => ({
            ...collaborator,
            action: 'invite',
        }));

    return [...participantSuggestions, ...targetSuggestions, ...inviteSuggestions].slice(0, DEFAULT_SUGGESTION_LIMIT);
}

function replaceComposerMention(mentionState, replacementText) {
    if (!userInput || !mentionState) {
        return;
    }

    const beforeMention = userInput.value.slice(0, mentionState.startIndex);
    const afterMention = userInput.value.slice(mentionState.endIndex);
    const trailingSpacer = afterMention.startsWith(' ') || !afterMention ? '' : ' ';
    const nextValue = `${beforeMention}${replacementText} ${trailingSpacer}${afterMention}`.replace(/\s{2,}/g, ' ');
    const nextCaretIndex = beforeMention.length + replacementText.length + 1;

    userInput.value = nextValue;
    userInput.setSelectionRange(nextCaretIndex, nextCaretIndex);
    updateSendButtonVisibility();
    hideMentionMenu();
    userInput.focus();
}

function insertParticipantMention(collaborator, mentionState) {
    const normalizedCollaborator = normalizeCollaborator(collaborator);
    if (!normalizedCollaborator) {
        return;
    }

    replaceComposerMention(mentionState, `@${normalizedCollaborator.display_name}`);
}

function insertInvocationTargetMention(target, mentionState) {
    const mentionText = String(target?.mention_text || `@${target?.display_name || ''}`).trim();
    if (!mentionText) {
        return;
    }

    replaceComposerMention(mentionState, mentionText);
}

function extractMentionedParticipantsFromMessage(messageText, conversationId) {
    const normalizedMessageText = String(messageText || '');
    if (!normalizedMessageText.trim()) {
        return [];
    }

    const participants = getConversationParticipants(conversationId, { includeCurrentUser: true })
        .slice()
        .sort((left, right) => String(right?.display_name || '').length - String(left?.display_name || '').length);

    const mentionedParticipants = [];
    const seenUserIds = new Set();
    participants.forEach(participant => {
        const displayName = String(participant?.display_name || '').trim();
        if (!displayName || seenUserIds.has(participant.user_id)) {
            return;
        }

        const mentionPattern = new RegExp(`(^|\\s)@${escapeRegExp(displayName)}(?=$|\\s|[.,!?;:])`, 'i');
        if (!mentionPattern.test(normalizedMessageText)) {
            return;
        }

        seenUserIds.add(participant.user_id);
        mentionedParticipants.push({
            user_id: participant.user_id,
            display_name: participant.display_name,
            email: participant.email || '',
        });
    });

    return mentionedParticipants;
}

function isCurrentUserMentioned(message = {}) {
    const currentUserId = getCurrentUserId();
    if (!currentUserId) {
        return false;
    }

    const mentionedUserIds = Array.isArray(message?.metadata?.mentioned_user_ids)
        ? message.metadata.mentioned_user_ids.map(userId => String(userId || '').trim())
        : [];
    return mentionedUserIds.includes(currentUserId);
}

function escapeHtml(value) {
    return String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function buildMessagePreview(content, maxLength = 140) {
    const plainText = String(content ?? '').replace(/\s+/g, ' ').trim();
    if (!plainText) {
        return 'No message content';
    }
    if (plainText.length <= maxLength) {
        return plainText;
    }
    return `${plainText.slice(0, maxLength - 3)}...`;
}

function buildReplyContext(message = {}) {
    const sender = normalizeCollaborator(message.sender || message.metadata?.sender || {}) || {};
    return {
        message_id: String(message.id || '').trim(),
        sender_display_name: sender.display_name || 'Participant',
        content_preview: buildMessagePreview(message.content || ''),
    };
}

function renderReplyPreview() {
    if (!replyPreviewEl || !replyPreviewLabelEl || !replyPreviewTextEl) {
        return;
    }

    if (!activeReplyContext) {
        replyPreviewEl.classList.add('d-none');
        replyPreviewLabelEl.textContent = '';
        replyPreviewTextEl.textContent = '';
        return;
    }

    replyPreviewLabelEl.textContent = `Replying to ${activeReplyContext.sender_display_name || 'Participant'}`;
    replyPreviewTextEl.textContent = activeReplyContext.content_preview || 'No message content';
    replyPreviewEl.classList.remove('d-none');
}

function clearReplyTarget(options = {}) {
    activeReplyContext = null;
    renderReplyPreview();
    if (options.focusComposer !== false) {
        userInput?.focus();
    }
}

function replyToMessage(message = {}) {
    const messageId = String(message.id || '').trim();
    if (!messageId) {
        return;
    }

    if (!canPostMessages(window.chatConversations?.getCurrentConversationId?.())) {
        showToast('Accept the invite before replying in this shared conversation.', 'warning');
        return;
    }

    activeReplyContext = buildReplyContext(message);
    renderReplyPreview();
    userInput?.focus();
}

function getPendingMessageContext(options = {}) {
    const conversationId = window.chatConversations?.getCurrentConversationId?.();
    const mentionedParticipants = extractMentionedParticipantsFromMessage(userInput?.value || '', conversationId);
    const invocationTarget = options.invocationTarget && typeof options.invocationTarget === 'object'
        ? options.invocationTarget
        : null;
    if (!activeReplyContext && mentionedParticipants.length === 0 && !invocationTarget) {
        return null;
    }

    const metadata = {};
    if (activeReplyContext) {
        metadata.reply_context = {
            ...activeReplyContext,
        };
    }
    if (mentionedParticipants.length > 0) {
        metadata.mentioned_participants = mentionedParticipants;
        metadata.mentioned_user_ids = mentionedParticipants.map(participant => participant.user_id);
    }
    if (invocationTarget) {
        metadata.ai_invocation_target = { ...invocationTarget };
        metadata.explicit_ai_invocation = true;
    }

    return {
        reply_to_message_id: activeReplyContext?.message_id || null,
        metadata,
    };
}

function cacheCollaborationMessage(message = {}) {
    const messageId = String(message.id || '').trim();
    if (!messageId) {
        return;
    }

    collaborationMessageCache.set(messageId, {
        ...message,
        metadata: message.metadata || {},
        sender: message.sender || {},
    });
}

function removeCollaborationMessage(messageId) {
    const normalizedMessageId = String(messageId || '').trim();
    if (!normalizedMessageId) {
        return;
    }

    collaborationMessageCache.delete(normalizedMessageId);

    const messageElement = document.querySelector(`[data-message-id="${normalizedMessageId}"]`);
    if (messageElement) {
        messageElement.remove();
    }

    if (activeReplyContext?.message_id === normalizedMessageId) {
        clearReplyTarget({ focusComposer: false });
    }
}

function clearMessageCache() {
    collaborationMessageCache.clear();
}

function decorateReplyMessage(message = {}) {
    const replyToMessageId = String(message.reply_to_message_id || '').trim();
    if (!replyToMessageId) {
        return message;
    }

    const replyMessage = collaborationMessageCache.get(replyToMessageId);
    if (!replyMessage) {
        return message;
    }

    return {
        ...message,
        reply_message: replyMessage,
    };
}

function buildEventKey(eventEnvelope = {}) {
    const payload = eventEnvelope.payload || {};
    return [
        eventEnvelope.conversation_id || payload.conversation?.id || '',
        eventEnvelope.event_type || '',
        payload.message?.id || payload.message_id || payload.participant?.user_id || payload.user?.user_id || payload.deleted_by_user_id || '',
        eventEnvelope.occurred_at || '',
    ].join('|');
}

function isReplayEvent(eventEnvelope = {}) {
    if (!activeSubscriptionStartedAt) {
        return false;
    }

    const occurredAt = Date.parse(eventEnvelope.occurred_at || '');
    if (Number.isNaN(occurredAt)) {
        return false;
    }

    return occurredAt < (activeSubscriptionStartedAt - 1000);
}

async function getCachedUserSettings() {
    if (!cachedUserSettingsPromise) {
        cachedUserSettingsPromise = loadUserSettings().then(settings => settings || {});
    }
    return cachedUserSettingsPromise;
}

function setCachedUserSettings(settings = {}) {
    cachedUserSettingsPromise = Promise.resolve(settings || {});
}

async function rememberRecentCollaborator(collaborator) {
    const normalizedCollaborator = normalizeCollaborator(collaborator);
    if (!normalizedCollaborator) {
        return;
    }

    const userSettings = await getCachedUserSettings();
    const existing = Array.isArray(userSettings[RECENT_COLLABORATORS_KEY])
        ? userSettings[RECENT_COLLABORATORS_KEY]
        : [];

    const updatedCollaborators = [
        {
            ...normalizedCollaborator,
            last_used_at: new Date().toISOString(),
        },
        ...existing.filter(item => String(item?.user_id || item?.userId || item?.id || '').trim() !== normalizedCollaborator.user_id),
    ].slice(0, MAX_RECENT_COLLABORATORS);

    const nextSettings = {
        ...userSettings,
        [RECENT_COLLABORATORS_KEY]: updatedCollaborators,
    };
    setCachedUserSettings(nextSettings);
    saveUserSetting({ [RECENT_COLLABORATORS_KEY]: updatedCollaborators });
}

async function fetchJson(url, options = {}) {
    const response = await fetch(url, {
        credentials: 'same-origin',
        ...options,
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
        throw new Error(payload.error || `Request failed (${response.status})`);
    }
    return payload;
}

async function searchLocalCollaborators(query = '', options = {}) {
    const search = new URLSearchParams();
    search.set('query', query);
    search.set('limit', String(options.limit || DEFAULT_SUGGESTION_LIMIT));
    if (options.recentOnly) {
        search.set('recent_only', 'true');
    }

    const payload = await fetchJson(`/api/user/collaboration-suggestions?${search.toString()}`);
    return Array.isArray(payload.results) ? payload.results : [];
}

function ensureTypingIndicator() {
    let typingIndicator = document.getElementById('collaboration-typing-indicator');
    if (typingIndicator) {
        return typingIndicator;
    }

    const chatbox = document.getElementById('chatbox');
    if (!chatbox || !chatbox.parentElement) {
        return null;
    }

    typingIndicator = document.createElement('div');
    typingIndicator.id = 'collaboration-typing-indicator';
    typingIndicator.className = 'collaboration-typing-indicator d-none';
    chatbox.insertAdjacentElement('afterend', typingIndicator);
    return typingIndicator;
}

function renderTypingIndicator() {
    const typingIndicator = ensureTypingIndicator();
    if (!typingIndicator) {
        return;
    }

    const now = Date.now();
    typingUsers.forEach((entry, userId) => {
        const expiresAt = entry?.expiresAt ? Date.parse(entry.expiresAt) : 0;
        if (!expiresAt || expiresAt <= now) {
            typingUsers.delete(userId);
        }
    });

    if (typingUsers.size === 0) {
        typingIndicator.textContent = '';
        typingIndicator.classList.add('d-none');
        return;
    }

    const names = Array.from(typingUsers.values())
        .map(entry => entry.displayName)
        .filter(Boolean);

    if (names.length === 1) {
        typingIndicator.textContent = `${names[0]} is typing...`;
    } else if (names.length === 2) {
        typingIndicator.textContent = `${names[0]} and ${names[1]} are typing...`;
    } else {
        typingIndicator.textContent = `${names[0]} and ${names.length - 1} others are typing...`;
    }

    typingIndicator.classList.remove('d-none');
}

function clearTypingState() {
    typingUsers = new Map();
    renderTypingIndicator();
}

function updateComposerAvailability(metadata = null) {
    if (!userInput || !sendBtn) {
        return;
    }

    if (!metadata || metadata.conversation_kind !== 'collaborative') {
        userInput.disabled = false;
        sendBtn.disabled = false;
        userInput.placeholder = 'Type your message...';
        return;
    }

    const canPostMessages = metadata.can_post_messages !== false;
    userInput.disabled = !canPostMessages;
    sendBtn.disabled = !canPostMessages;

    if (canPostMessages) {
        userInput.placeholder = 'Type a shared message...';
        return;
    }

    if (metadata.membership_status === 'pending') {
        userInput.placeholder = 'Accept the invite before posting messages...';
    } else {
        userInput.placeholder = 'You cannot post messages in this conversation.';
    }
}

function resolveMessageSenderType(message) {
    if (message.role === 'assistant') {
        return 'AI';
    }

    if (message.role === 'image') {
        return 'image';
    }

    if (message.role === 'file') {
        return 'File';
    }

    if (message.role === 'safety') {
        return 'safety';
    }

    const senderUserId = message.sender?.user_id || message.metadata?.sender?.user_id || null;
    if (senderUserId && senderUserId === getCurrentUserId()) {
        return 'You';
    }

    return 'Collaborator';
}

function getCurrentUserId() {
    return String(window.currentUser?.id || window.currentUser?.user_id || '').trim();
}

function getLatestPendingCollaborativeMessageId() {
    const pendingMessages = Array.from(document.querySelectorAll('[data-message-id^="temp_user_"]'));
    if (pendingMessages.length === 0) {
        return null;
    }

    return pendingMessages[pendingMessages.length - 1].getAttribute('data-message-id');
}

function reconcilePendingCollaborativeUserMessage(message, preferredTempId = null) {
    const senderUserId = String(message?.sender?.user_id || message?.metadata?.sender?.user_id || '').trim();
    if (!senderUserId || senderUserId !== getCurrentUserId()) {
        return false;
    }

    const realMessageId = String(message?.id || '').trim();
    if (!realMessageId) {
        return false;
    }

    const pendingMessageId = preferredTempId || getLatestPendingCollaborativeMessageId();
    const existingRealMessage = document.querySelector(`[data-message-id="${realMessageId}"]`);

    if (existingRealMessage && pendingMessageId) {
        const pendingMessage = document.querySelector(`[data-message-id="${pendingMessageId}"]`);
        if (pendingMessage) {
            pendingMessage.remove();
        }
        return true;
    }

    if (pendingMessageId) {
        updateUserMessageId(pendingMessageId, realMessageId);
        return true;
    }

    return Boolean(existingRealMessage);
}

function renderCollaborationMessage(message, options = {}) {
    if (!message || !message.id) {
        return;
    }

    if (document.querySelector(`[data-message-id="${message.id}"]`)) {
        return;
    }

    const senderType = resolveMessageSenderType(message);
    appendMessage(
        senderType,
        message.content || '',
        message.model_deployment_name || null,
        message.id,
        Boolean(message.augmented),
        Array.isArray(message.hybrid_citations) ? message.hybrid_citations : [],
        Array.isArray(message.web_search_citations) ? message.web_search_citations : [],
        Array.isArray(message.agent_citations) ? message.agent_citations : [],
        message.agent_display_name || null,
        message.agent_name || null,
        {
            ...message,
            metadata: message.metadata || {},
            sender: message.sender || {},
        },
        Boolean(options.isNewMessage)
    );
}

async function loadConversationMessages(conversationId) {
    const payload = await fetchJson(`/api/collaboration/conversations/${conversationId}/messages`);
    const chatbox = document.getElementById('chatbox');
    if (!chatbox) {
        return [];
    }

    chatbox.innerHTML = '';
    clearTypingState();
    clearMessageCache();

    const messages = Array.isArray(payload.messages) ? payload.messages : [];
    messages.forEach(message => {
        const decoratedMessage = decorateReplyMessage(message);
        renderCollaborationMessage(decoratedMessage);
        cacheCollaborationMessage(message);
    });
    return messages;
}

function handleTypingEvent(payload = {}) {
    const currentUserId = getCurrentUserId();
    const typingUser = normalizeCollaborator(payload.user);
    if (!typingUser || typingUser.user_id === currentUserId) {
        return;
    }

    if (payload.is_typing === false) {
        typingUsers.delete(typingUser.user_id);
        renderTypingIndicator();
        return;
    }

    typingUsers.set(typingUser.user_id, {
        displayName: typingUser.display_name,
        expiresAt: payload.expires_at,
    });
    renderTypingIndicator();
}

function disconnectConversationEvents() {
    const previousConversationId = activeCollaborativeConversationId;

    if (activeCollaborationEventSource) {
        activeCollaborationEventSource.close();
        activeCollaborationEventSource = null;
    }

    activeSubscriptionStartedAt = 0;

    if (typingStopHandle) {
        window.clearTimeout(typingStopHandle);
        typingStopHandle = null;
    }

    setTypingState(false, {
        force: true,
        conversationId: previousConversationId,
    });

    activeCollaborativeConversationId = null;
    clearTypingState();
    lastTypingState = false;
}

function handleConversationEvent(eventEnvelope = {}) {
    if (!eventEnvelope || !eventEnvelope.event_type) {
        return;
    }

    const eventKey = buildEventKey(eventEnvelope);
    if (eventKey && seenCollaborationEventKeys.has(eventKey)) {
        return;
    }
    if (eventKey) {
        seenCollaborationEventKeys.add(eventKey);
    }

    if (isReplayEvent(eventEnvelope)) {
        return;
    }

    const payload = eventEnvelope.payload || {};
    if (payload.conversation) {
        const normalizedConversation = cacheCollaborationConversation(payload.conversation);
        setConversationDataset(normalizedConversation.id, normalizedConversation);
        applyConversationMetadataUpdate(normalizedConversation.id, normalizedConversation);
        if (!['collaboration.message.created', 'collaboration.typing.updated'].includes(eventEnvelope.event_type)) {
            void fetchConversationMetadata(normalizedConversation.id).catch(() => {});
        }
    }

    if (eventEnvelope.event_type === 'collaboration.message.created' && payload.message) {
        const senderUserId = String(payload.message?.sender?.user_id || payload.message?.metadata?.sender?.user_id || '').trim();
        const shouldClearNotifications = Boolean(senderUserId && senderUserId !== getCurrentUserId());
        if (senderUserId && senderUserId !== getCurrentUserId() && isCurrentUserMentioned(payload.message)) {
            const senderName = normalizeCollaborator(payload.message.sender || payload.message.metadata?.sender || {})?.display_name || 'A participant';
            showToast(`${senderName} tagged you in a shared message.`, 'info');
        }

        const decoratedMessage = decorateReplyMessage(payload.message);
        cacheCollaborationMessage(payload.message);
        if (reconcilePendingCollaborativeUserMessage(payload.message)) {
            if (shouldClearNotifications) {
                void markCollaborationConversationRead(eventEnvelope.conversation_id || payload.message.conversation_id, {
                    suppressErrorToast: true,
                }).catch(() => {});
            }
            return;
        }
        renderCollaborationMessage(decoratedMessage, { isNewMessage: true });
        if (shouldClearNotifications) {
            void markCollaborationConversationRead(eventEnvelope.conversation_id || payload.message.conversation_id, {
                suppressErrorToast: true,
            }).catch(() => {});
        }
        return;
    }

    if (eventEnvelope.event_type === 'collaboration.typing.updated') {
        handleTypingEvent(payload);
        return;
    }

    if (eventEnvelope.event_type === 'collaboration.message.deleted' && payload.message_id) {
        removeCollaborationMessage(payload.message_id);
        if (payload.deleted_by_user_id && payload.deleted_by_user_id !== getCurrentUserId()) {
            showToast('A shared message was deleted.', 'info');
        }
        return;
    }

    if (eventEnvelope.event_type === 'collaboration.member.invited' && Array.isArray(payload.participants)) {
        return;
    }

    if (eventEnvelope.event_type === 'collaboration.member.removed' && payload.participant?.display_name) {
        if (String(payload.participant.user_id || '').trim() === getCurrentUserId()) {
            showToast('You no longer have access to this shared conversation.', 'warning');
            window.chatConversations?.removeConversationFromUi?.(eventEnvelope.conversation_id || payload.conversation?.id, {
                refreshList: true,
                skipToast: true,
            });
            return;
        }
        showToast(`${payload.participant.display_name} was removed from the conversation.`, 'info');
        return;
    }

    if (eventEnvelope.event_type === 'collaboration.member.role_updated' && payload.participant?.display_name) {
        const roleLabel = payload.participant.role === 'admin' ? 'admin' : 'member';
        showToast(`${payload.participant.display_name} is now ${roleLabel}.`, 'success');
        return;
    }

    if (eventEnvelope.event_type === 'collaboration.invite.accepted' && payload.participant?.display_name) {
        showToast(`${payload.participant.display_name} accepted the invite.`, 'success');
        return;
    }

    if (eventEnvelope.event_type === 'collaboration.deleted') {
        showToast('This shared conversation was deleted.', 'warning');
        window.chatConversations?.removeConversationFromUi?.(eventEnvelope.conversation_id || payload.conversation?.id, {
            refreshList: true,
            skipToast: true,
        });
    }
}

function subscribeToConversationEvents(conversationId) {
    if (!isCollaborationEnabled() || !conversationId || typeof EventSource === 'undefined') {
        return;
    }

    disconnectConversationEvents();
    activeCollaborativeConversationId = conversationId;
    activeSubscriptionStartedAt = Date.now();
    activeCollaborationEventSource = new EventSource(`/api/collaboration/conversations/${encodeURIComponent(conversationId)}/events`);
    activeCollaborationEventSource.onmessage = event => {
        if (!event?.data) {
            return;
        }

        try {
            handleConversationEvent(JSON.parse(event.data));
        } catch (error) {
            console.warn('Failed to parse collaboration event:', error);
        }
    };
    activeCollaborationEventSource.onerror = () => {
        console.warn('Collaboration event stream disconnected.');
    };
}

async function fetchConversationMetadata(conversationId) {
    const payload = await fetchJson(`/api/collaboration/conversations/${conversationId}`);
    const normalizedConversation = cacheCollaborationConversation(payload.conversation || {});
    setConversationDataset(conversationId, normalizedConversation);
    applyConversationMetadataUpdate(conversationId, normalizedConversation);
    return normalizedConversation;
}

function showPendingInviteToast(conversation) {
    if (!conversation?.id || !conversation.can_accept_invite) {
        return;
    }

    if (notifiedPendingInviteConversationIds.has(conversation.id)) {
        return;
    }

    notifiedPendingInviteConversationIds.add(conversation.id);
    const actionId = `collaboration-invite-review-${conversation.id}-${Date.now()}`;
    showToast(
        `You were invited to <strong>${escapeHtml(conversation.title || 'a collaborative conversation')}</strong>. <button type="button" id="${actionId}" class="btn btn-sm btn-light ms-2">Review invite</button>`,
        'warning'
    );

    window.setTimeout(() => {
        const actionButton = document.getElementById(actionId);
        if (!actionButton) {
            return;
        }

        actionButton.addEventListener('click', async event => {
            event.preventDefault();
            if (window.chatConversations?.selectConversation) {
                await window.chatConversations.selectConversation(conversation.id);
            }
            if (window.showConversationDetails) {
                window.showConversationDetails(conversation.id);
            }
        }, { once: true });
    }, 0);
}

function notifyPendingInvites(conversations = []) {
    conversations.forEach(conversation => {
        if (conversation?.can_accept_invite) {
            showPendingInviteToast(conversation);
        }
    });
}

async function fetchCollaborationConversationList() {
    if (!isCollaborationEnabled()) {
        return [];
    }

    const payload = await fetchJson('/api/collaboration/conversations?include_pending=true');
    const conversations = Array.isArray(payload.conversations) ? payload.conversations : [];
    const normalizedConversations = conversations.map(conversation => cacheCollaborationConversation(conversation));
    notifyPendingInvites(normalizedConversations);
    return normalizedConversations;
}

async function activateConversation(conversationId, metadata = null) {
    const conversationMetadata = metadata
        ? cacheCollaborationConversation(metadata)
        : await fetchConversationMetadata(conversationId);
    updateComposerAvailability(conversationMetadata);
    clearReplyTarget({ focusComposer: false });
    await loadConversationMessages(conversationId);
    markCollaborationConversationRead(conversationId, { suppressErrorToast: true }).catch(error => {
        console.warn('Failed to clear shared conversation notifications:', error);
    });
    subscribeToConversationEvents(conversationId);

    if (conversationMetadata.can_accept_invite && !promptedPendingInviteConversationIds.has(conversationId)) {
        promptedPendingInviteConversationIds.add(conversationId);
        showPendingInviteToast(conversationMetadata);
        if (window.showConversationDetails) {
            window.setTimeout(() => {
                window.showConversationDetails(conversationId);
            }, 0);
        }
    }

    return conversationMetadata;
}

function deactivateConversation() {
    disconnectConversationEvents();
    updateComposerAvailability(null);
    clearReplyTarget({ focusComposer: false });
    hideMentionMenu();
}

async function sendCollaborativeMessage(messageText, tempMessageId = null) {
    const conversationId = window.chatConversations?.getCurrentConversationId?.();
    if (!conversationId) {
        return null;
    }

    const mentionedParticipants = extractMentionedParticipantsFromMessage(messageText, conversationId);

    const payload = await fetchJson(`/api/collaboration/conversations/${conversationId}/messages`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({
            content: messageText,
            reply_to_message_id: activeReplyContext?.message_id || null,
            mentioned_participants: mentionedParticipants,
        }),
    });

    if (payload.conversation) {
        const normalizedConversation = cacheCollaborationConversation(payload.conversation);
        setConversationDataset(conversationId, normalizedConversation);
        applyConversationMetadataUpdate(conversationId, normalizedConversation);
    }

    if (payload.message) {
        cacheCollaborationMessage(payload.message);
        if (!reconcilePendingCollaborativeUserMessage(payload.message, tempMessageId)) {
            renderCollaborationMessage(decorateReplyMessage(payload.message), { isNewMessage: true });
        }
    }

    setTypingState(false, { force: true });
    clearReplyTarget();
    return payload;
}

async function sendCollaborativeAiMessage(messageText, tempMessageId = null, messageData = {}, pendingContext = null) {
    const conversationId = window.chatConversations?.getCurrentConversationId?.();
    if (!conversationId) {
        throw new Error('No collaborative conversation is active.');
    }

    const mentionedParticipants = extractMentionedParticipantsFromMessage(messageText, conversationId);
    const invocationTarget = pendingContext?.metadata?.ai_invocation_target || null;
    const requestBody = {
        ...messageData,
        content: messageText,
        reply_to_message_id: activeReplyContext?.message_id || null,
        mentioned_participants: mentionedParticipants,
        invocation_target: invocationTarget,
    };

    sendMessageWithStreaming(
        requestBody,
        tempMessageId,
        conversationId,
        {
            endpoint: `/api/collaboration/conversations/${encodeURIComponent(conversationId)}/stream`,
            allowRecovery: false,
            onError: (errorMessage, errorData = null) => {
                if (errorData?.user_message_id && tempMessageId) {
                    updateUserMessageId(tempMessageId, errorData.user_message_id);
                }

                if (errorData?.message_persisted === true) {
                    return;
                }

                const tempMessage = document.querySelector(`[data-message-id="${tempMessageId}"]`);
                if (tempMessage) {
                    tempMessage.remove();
                }
            },
        },
    );

    setTypingState(false, { force: true });
    clearReplyTarget();
    return { started: true };
}

function setTypingState(isTyping, options = {}) {
    const conversationId = options.conversationId || window.chatConversations?.getCurrentConversationId?.();
    if (!conversationId || !isCollaborationConversation(conversationId) || !canPostMessages(conversationId)) {
        return;
    }

    if (!options.force && lastTypingState === isTyping) {
        return;
    }

    lastTypingState = isTyping;
    fetch(`/api/collaboration/conversations/${conversationId}/typing`, {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({ is_typing: isTyping }),
    }).catch(error => {
        console.warn('Failed to update collaboration typing state:', error);
    });
}

function scheduleTypingState() {
    if (!isCollaborationConversation(window.chatConversations?.getCurrentConversationId?.())) {
        return;
    }

    const hasContent = Boolean(userInput?.value?.trim());
    setTypingState(hasContent);

    if (typingStopHandle) {
        window.clearTimeout(typingStopHandle);
    }
    typingStopHandle = window.setTimeout(() => {
        setTypingState(false);
    }, 3000);
}

function getMentionMatch() {
    if (!userInput) {
        return null;
    }

    const selectionStart = typeof userInput.selectionStart === 'number'
        ? userInput.selectionStart
        : userInput.value.length;
    const beforeCursor = userInput.value.slice(0, selectionStart);
    const match = beforeCursor.match(/(^|\s)@([^\s@]*)$/);
    if (!match) {
        return null;
    }

    const startIndex = selectionStart - match[2].length - 1;
    return {
        query: match[2] || '',
        startIndex,
        endIndex: selectionStart,
    };
}

function buildSuggestionItemHtml(suggestion) {
    const subtitle = suggestion.action === 'ai_tag'
        ? `<div class="small text-muted">${escapeHtml(suggestion.subtitle || (suggestion.target_type === 'agent' ? 'AI agent' : 'Model deployment'))}</div>`
        : suggestion.email
        ? `<div class="small text-muted">${escapeHtml(suggestion.email)}</div>`
        : '<div class="small text-muted">No email recorded</div>';
    const sourceLabel = suggestion.action === 'ai_tag'
        ? suggestion.target_type === 'agent'
            ? '<span class="badge bg-warning-subtle text-warning-emphasis ms-2">Agent</span>'
            : '<span class="badge bg-primary-subtle text-primary-emphasis ms-2">Model</span>'
        : suggestion.action === 'tag'
        ? '<span class="badge bg-success-subtle text-success-emphasis ms-2">Tag</span>'
        : suggestion.source === 'recent'
        ? '<span class="badge bg-secondary-subtle text-secondary-emphasis ms-2">Recent</span>'
        : '<span class="badge bg-light text-muted ms-2">Invite</span>';

    return `
        <div class="d-flex justify-content-between align-items-start gap-2">
            <div class="text-start overflow-hidden">
                <div class="fw-semibold text-truncate">${escapeHtml(suggestion.display_name)}</div>
                ${subtitle}
            </div>
            ${sourceLabel}
        </div>
    `;
}

function hideMentionMenu() {
    if (!mentionMenu) {
        return;
    }

    mentionMenu.innerHTML = '';
    mentionMenu.classList.add('d-none');
    activeMentionState = null;
}

function renderMentionMenu(results, mentionState) {
    if (!mentionMenu) {
        return;
    }

    if (!Array.isArray(results) || results.length === 0) {
        mentionMenu.innerHTML = '<div class="list-group-item text-muted small">No matching participants, agents, models, or collaborators found.</div>';
        mentionMenu.classList.remove('d-none');
        activeMentionState = {
            ...mentionState,
            results: [],
            activeIndex: -1,
        };
        return;
    }

    activeMentionState = {
        ...mentionState,
        results,
        activeIndex: 0,
    };

    mentionMenu.innerHTML = '';
    results.forEach((result, index) => {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = `list-group-item list-group-item-action collaboration-mention-item${index === 0 ? ' active' : ''}`;
        button.innerHTML = buildSuggestionItemHtml(result);
        button.setAttribute('data-index', String(index));
        button.addEventListener('mousedown', event => {
            event.preventDefault();
            if (result.action === 'tag') {
                insertParticipantMention(result, mentionState);
                return;
            }

            if (result.action === 'ai_tag') {
                insertInvocationTargetMention(result, mentionState);
                return;
            }

            openParticipantConfirmation(result, {
                conversationId: window.chatConversations?.getCurrentConversationId?.(),
                source: 'mention',
                mentionState,
            });
        });
        mentionMenu.appendChild(button);
    });
    mentionMenu.classList.remove('d-none');
}

function updateMentionMenuActiveItem() {
    if (!mentionMenu || !activeMentionState) {
        return;
    }

    const items = mentionMenu.querySelectorAll('.collaboration-mention-item');
    items.forEach((item, index) => {
        item.classList.toggle('active', index === activeMentionState.activeIndex);
    });
}

async function refreshMentionSuggestions() {
    const conversationId = window.chatConversations?.getCurrentConversationId?.();
    if (!conversationId) {
        hideMentionMenu();
        return;
    }

    const mentionState = getMentionMatch();
    if (!mentionState) {
        hideMentionMenu();
        return;
    }

    const searchToken = ++mentionSearchToken;
    try {
        const results = await loadMentionSuggestions(conversationId, mentionState.query);
        if (searchToken !== mentionSearchToken) {
            return;
        }
        renderMentionMenu(results, mentionState);
    } catch (error) {
        if (searchToken !== mentionSearchToken) {
            return;
        }
        hideMentionMenu();
        console.warn('Failed to load mention suggestions:', error);
    }
}

function removeMentionFromComposer(mentionState) {
    if (!userInput || !mentionState) {
        return;
    }

    const beforeMention = userInput.value.slice(0, mentionState.startIndex);
    const afterMention = userInput.value.slice(mentionState.endIndex);
    const nextValue = `${beforeMention}${afterMention}`.replace(/\s{2,}/g, ' ').trimStart();
    userInput.value = nextValue;
    updateSendButtonVisibility();
    userInput.focus();
}

function renderParticipantResults(results, emptyMessage = 'No collaborators found.') {
    if (!participantResults) {
        return;
    }

    if (!Array.isArray(results) || results.length === 0) {
        participantResults.innerHTML = `<div class="list-group-item text-muted small">${emptyMessage}</div>`;
        return;
    }

    participantResults.innerHTML = '';
    results.forEach(result => {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'list-group-item list-group-item-action';
        button.innerHTML = buildSuggestionItemHtml(result);
        button.addEventListener('click', () => {
            openParticipantConfirmation(result, {
                conversationId: participantConversationIdInput?.value || window.chatConversations?.getCurrentConversationId?.(),
                source: 'picker',
            });
        });
        participantResults.appendChild(button);
    });
}

async function refreshParticipantPickerResults(query = '') {
    try {
        const results = await searchLocalCollaborators(query, { recentOnly: false, limit: 12 });
        renderParticipantResults(results);
    } catch (error) {
        renderParticipantResults([], 'Failed to load collaborators.');
        console.warn('Failed to refresh participant picker results:', error);
    }
}

function openParticipantPicker(options = {}) {
    const conversationId = options.conversationId || window.chatConversations?.getCurrentConversationId?.();
    if (!conversationId) {
        showToast('Select a conversation first.', 'warning');
        return;
    }

    if (!canUseParticipantFlow(conversationId)) {
        showToast('Participants can only be added to eligible personal conversations you manage.', 'warning');
        return;
    }

    if (!participantModalEl || !participantSearchInput || !participantConversationIdInput) {
        return;
    }

    participantConversationIdInput.value = conversationId;
    participantSearchInput.value = '';
    renderParticipantResults([], 'Loading collaborators...');
    bootstrap.Modal.getOrCreateInstance(participantModalEl).show();
    refreshParticipantPickerResults('');
}

function openParticipantConfirmation(userSummary, context = {}) {
    const collaborator = normalizeCollaborator(userSummary);
    if (!collaborator || !confirmModalEl || !confirmMessageEl) {
        return;
    }

    pendingParticipantConfirmation = {
        collaborator,
        context,
    };
    confirmMessageEl.innerHTML = `Are you sure you want to add <strong>${collaborator.display_name}</strong>${collaborator.email ? ` (${collaborator.email})` : ''} to this conversation?`;
    bootstrap.Modal.getOrCreateInstance(confirmModalEl).show();
}

function canUseParticipantFlow(conversationId) {
    const chatType = getConversationChatType(conversationId);
    if (!chatType || !['personal_single_user', 'personal_multi_user'].includes(chatType)) {
        return false;
    }

    if (!isCollaborationConversation(conversationId)) {
        return true;
    }

    const item = getConversationDomItem(conversationId);
    return item?.dataset?.canManageMembers === 'true';
}

function canPostMessages(conversationId) {
    if (!isCollaborationConversation(conversationId)) {
        return true;
    }

    const item = getConversationDomItem(conversationId);
    return item?.dataset?.canPostMessages !== 'false';
}

async function addParticipantToConversation(conversationId, collaborator) {
    const isCollaborative = isCollaborationConversation(conversationId);
    const endpoint = isCollaborative
        ? `/api/collaboration/conversations/${conversationId}/members`
        : `/api/collaboration/conversations/from-personal/${conversationId}/members`;

    const payload = await fetchJson(endpoint, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({
            participants: [collaborator],
        }),
    });

    const normalizedConversation = cacheCollaborationConversation(payload.conversation || {});
    await rememberRecentCollaborator(collaborator);

    if (window.chatConversations?.loadConversations) {
        await window.chatConversations.loadConversations();
    }

    if (normalizedConversation.id && window.chatConversations?.selectConversation) {
        await window.chatConversations.selectConversation(normalizedConversation.id);
    }

    setConversationDataset(normalizedConversation.id, normalizedConversation);
    return {
        ...payload,
        conversation: normalizedConversation,
    };
}

async function confirmPendingParticipant() {
    if (!pendingParticipantConfirmation) {
        return;
    }

    const { collaborator, context } = pendingParticipantConfirmation;
    const conversationId = context.conversationId || window.chatConversations?.getCurrentConversationId?.();
    if (!conversationId) {
        return;
    }

    confirmAddBtn.disabled = true;
    try {
        const payload = await addParticipantToConversation(conversationId, collaborator);
        bootstrap.Modal.getOrCreateInstance(confirmModalEl).hide();
        bootstrap.Modal.getOrCreateInstance(participantModalEl)?.hide();

        if (context.source === 'mention' && context.mentionState) {
            removeMentionFromComposer(context.mentionState);
            hideMentionMenu();
        }

        showToast(
            payload.created
                ? 'Conversation converted to a collaborative chat and participant invited.'
                : 'Participant invited to the conversation.',
            'success'
        );

        const detailsModalVisible = document.getElementById('conversation-details-modal')?.classList.contains('show');
        if (detailsModalVisible && window.showConversationDetails && payload.conversation?.id) {
            window.showConversationDetails(payload.conversation.id);
        }
    } catch (error) {
        showToast(error.message || 'Failed to add participant.', 'danger');
    } finally {
        confirmAddBtn.disabled = false;
        pendingParticipantConfirmation = null;
    }
}

async function respondToInvite(conversationId, action) {
    const payload = await fetchJson(`/api/collaboration/conversations/${conversationId}/invite-response`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({ action }),
    });

    if (window.chatConversations?.loadConversations) {
        await window.chatConversations.loadConversations();
    }

    if (action === 'accept') {
        notifiedPendingInviteConversationIds.delete(conversationId);
        promptedPendingInviteConversationIds.delete(conversationId);
    }

    if (action === 'accept' && payload.conversation?.id && window.chatConversations?.selectConversation) {
        await window.chatConversations.selectConversation(payload.conversation.id);
    }

    window.hideConversationDetails?.();
    showToast(action === 'accept' ? 'Invite accepted.' : 'Invite declined.', 'success');
    return payload;
}

async function removeParticipant(conversationId, memberUserId) {
    const payload = await fetchJson(`/api/collaboration/conversations/${conversationId}/members/${encodeURIComponent(memberUserId)}`, {
        method: 'DELETE',
    });

    if (window.chatConversations?.loadConversations) {
        await window.chatConversations.loadConversations();
    }
    if (window.chatConversations?.selectConversation) {
        await window.chatConversations.selectConversation(conversationId);
    }

    showToast('Participant removed from the conversation.', 'success');
    if (window.showConversationDetails) {
        window.showConversationDetails(conversationId);
    }
    return payload;
}

async function updateParticipantRole(conversationId, memberUserId, role) {
    const payload = await fetchJson(`/api/collaboration/conversations/${conversationId}/members/${encodeURIComponent(memberUserId)}/role`, {
        method: 'PUT',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({ role }),
    });

    if (window.chatConversations?.loadConversations) {
        await window.chatConversations.loadConversations();
    }
    if (window.chatConversations?.selectConversation) {
        await window.chatConversations.selectConversation(conversationId);
    }

    showToast(role === 'admin' ? 'Participant promoted to admin.' : 'Participant admin access removed.', 'success');
    if (window.showConversationDetails) {
        window.showConversationDetails(conversationId);
    }
    return payload;
}

function handleComposerInput() {
    if (!isCollaborationEnabled()) {
        return;
    }

    scheduleTypingState();
    void refreshMentionSuggestions();
}

function handleComposerKeydown(event) {
    if (!activeMentionState || mentionMenu?.classList.contains('d-none')) {
        if (event.key === 'Escape' && activeReplyContext) {
            clearReplyTarget();
            return true;
        }
        return false;
    }

    if (event.key === 'ArrowDown') {
        event.preventDefault();
        activeMentionState.activeIndex = Math.min(activeMentionState.activeIndex + 1, Math.max(activeMentionState.results.length - 1, 0));
        updateMentionMenuActiveItem();
        return true;
    }

    if (event.key === 'ArrowUp') {
        event.preventDefault();
        activeMentionState.activeIndex = Math.max(activeMentionState.activeIndex - 1, 0);
        updateMentionMenuActiveItem();
        return true;
    }

    if (event.key === 'Enter' && activeMentionState.activeIndex >= 0) {
        event.preventDefault();
        const collaborator = activeMentionState.results[activeMentionState.activeIndex];
        if (collaborator) {
            if (collaborator.action === 'tag') {
                insertParticipantMention(collaborator, activeMentionState);
            } else if (collaborator.action === 'ai_tag') {
                insertInvocationTargetMention(collaborator, activeMentionState);
            } else {
                openParticipantConfirmation(collaborator, {
                    conversationId: window.chatConversations?.getCurrentConversationId?.(),
                    source: 'mention',
                    mentionState: activeMentionState,
                });
            }
        }
        return true;
    }

    if (event.key === 'Escape') {
        hideMentionMenu();
        return true;
    }

    return false;
}

function handleComposerBlur() {
    window.setTimeout(() => {
        hideMentionMenu();
    }, 100);
}

function initializeUi() {
    if (!isCollaborationEnabled()) {
        return;
    }

    if (participantSearchInput) {
        participantSearchInput.addEventListener('input', event => {
            void refreshParticipantPickerResults(event.target.value || '');
        });
    }

    if (participantModalEl) {
        participantModalEl.addEventListener('shown.bs.modal', () => {
            participantSearchInput?.focus();
        });
    }

    if (confirmAddBtn) {
        confirmAddBtn.addEventListener('click', () => {
            void confirmPendingParticipant();
        });
    }

    if (replyCancelBtn) {
        replyCancelBtn.addEventListener('click', () => {
            clearReplyTarget();
        });
    }

    document.addEventListener('click', event => {
        if (!mentionMenu || mentionMenu.classList.contains('d-none')) {
            return;
        }

        const withinMentionMenu = mentionMenu.contains(event.target);
        if (!withinMentionMenu && event.target !== userInput) {
            hideMentionMenu();
        }
    });
}

window.chatCollaboration = {
    activateConversation,
    clearReplyTarget,
    deactivateConversation,
    fetchCollaborationConversationList,
    fetchConversationMetadata,
    getPendingMessageContext,
    handleComposerBlur,
    handleComposerInput,
    handleComposerKeydown,
    isCollaborationConversation,
    openParticipantPicker,
    removeParticipant,
    replyToMessage,
    respondToInvite,
    sendCollaborativeAiMessage,
    sendCollaborativeMessage,
    updateParticipantRole,
    canUseParticipantFlow,
    markConversationRead: markCollaborationConversationRead,
};

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initializeUi);
} else {
    initializeUi();
}
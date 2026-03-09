// chat-message-export.js
import { showToast } from "./chat-toast.js";

'use strict';

/**
 * Per-message export module.
 *
 * Provides functions to export a single chat message as Markdown (.md)
 * or Word (.docx) from the three-dots dropdown on each message bubble.
 */

/**
 * Get the markdown content for a message from the DOM.
 * AI messages store their markdown in a hidden textarea; user messages
 * use the visible text content.
 */
function getMessageMarkdown(messageDiv, role) {
    if (role === 'assistant') {
        // AI messages have a hidden textarea with the markdown content
        const hiddenTextarea = messageDiv.querySelector('textarea[id^="copy-md-"]');
        if (hiddenTextarea) {
            return hiddenTextarea.value;
        }
    }
    // For user messages (or fallback), grab the text from the message bubble
    const messageText = messageDiv.querySelector('.message-text');
    if (messageText) {
        return messageText.innerText;
    }
    return '';
}

/**
 * Get the sender label and timestamp from a message div.
 */
function getMessageMeta(messageDiv, role) {
    const senderEl = messageDiv.querySelector('.message-sender');
    const sender = senderEl ? senderEl.innerText.trim() : (role === 'assistant' ? 'Assistant' : 'User');

    const timestampEl = messageDiv.querySelector('.message-timestamp');
    const timestamp = timestampEl ? timestampEl.innerText.trim() : '';

    return { sender, timestamp };
}

/**
 * Trigger a browser file download from a Blob.
 */
function downloadBlob(blob, filename) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
}

/**
 * Build a formatted timestamp string for filenames.
 */
function filenameTimestamp() {
    const now = new Date();
    const pad = (n) => String(n).padStart(2, '0');
    return `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}_${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`;
}

/**
 * Export a single message as a Markdown (.md) file download.
 * This is entirely client-side — no backend call needed.
 */
export function exportMessageAsMarkdown(messageDiv, messageId, role) {
    const content = getMessageMarkdown(messageDiv, role);
    if (!content) {
        showToast('No message content to export.', 'warning');
        return;
    }

    const { sender, timestamp } = getMessageMeta(messageDiv, role);

    const lines = [];
    lines.push(`### ${sender}`);
    if (timestamp) {
        lines.push(`*${timestamp}*`);
    }
    lines.push('');
    lines.push(content);
    lines.push('');

    const markdown = lines.join('\n');
    const blob = new Blob([markdown], { type: 'text/markdown; charset=utf-8' });
    const filename = `message_export_${filenameTimestamp()}.md`;
    downloadBlob(blob, filename);
    showToast('Message exported as Markdown.', 'success');
}

/**
 * Export a single message as a Word (.docx) file by calling the backend
 * endpoint which uses python-docx to generate the document.
 */
export async function exportMessageAsWord(messageDiv, messageId, role) {
    const conversationId = window.currentConversationId;
    if (!conversationId || !messageId) {
        showToast('Cannot export — no active conversation or message.', 'warning');
        return;
    }

    try {
        const response = await fetch('/api/message/export-word', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                message_id: messageId,
                conversation_id: conversationId
            })
        });

        if (!response.ok) {
            const errorData = await response.json().catch(() => null);
            const errorMsg = errorData?.error || `Export failed (${response.status})`;
            showToast(errorMsg, 'danger');
            return;
        }

        const blob = await response.blob();
        const filename = `message_export_${filenameTimestamp()}.docx`;
        downloadBlob(blob, filename);
        showToast('Message exported as Word document.', 'success');
    } catch (err) {
        console.error('Error exporting message to Word:', err);
        showToast('Failed to export message to Word.', 'danger');
    }
}

/**
 * Insert the message content as a formatted prompt directly into the chat
 * input box so the user can review, edit, and send it.
 * For AI messages, wraps with instructions to continue/build on the response.
 * For user messages, inserts the raw content as a reusable prompt.
 */
export function copyAsPrompt(messageDiv, messageId, role) {
    const content = getMessageMarkdown(messageDiv, role);
    if (!content) {
        showToast('No message content to use.', 'warning');
        return;
    }

    const userInput = document.getElementById('user-input');
    if (!userInput) {
        showToast('Chat input not found.', 'warning');
        return;
    }

    userInput.value = content;
    userInput.focus();
    // Trigger input event so auto-resize and send button visibility update
    userInput.dispatchEvent(new Event('input', { bubbles: true }));
    showToast('Prompt inserted into chat input.', 'success');
}

/**
 * Open the user's default email client with the message content
 * pre-filled in the email body via a mailto: link.
 */
export function openInEmail(messageDiv, messageId, role) {
    const content = getMessageMarkdown(messageDiv, role);
    if (!content) {
        showToast('No message content to email.', 'warning');
        return;
    }

    const { sender } = getMessageMeta(messageDiv, role);
    const subject = `Chat message from ${sender}`;

    // mailto: uses the body parameter for content
    const mailtoUrl = `mailto:?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(content)}`;
    window.open(mailtoUrl, '_blank');
}

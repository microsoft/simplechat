// chat-message-export.js
import { showToast } from "./chat-toast.js";

/**
 * Per-message export module.
 *
 * Provides functions to export a single chat message as Markdown (.md)
 * Word (.docx), or PowerPoint (.pptx) from the three-dots dropdown on each
 * message bubble.
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
 * Get the sender label from a message div.
 */
function getMessageMeta(messageDiv, role) {
    const senderEl = messageDiv.querySelector('.message-sender');
    const sender = senderEl ? senderEl.innerText.trim() : (role === 'assistant' ? 'Assistant' : 'User');

    return { sender };
}

function getMessageContentOverride(messageDiv, role) {
    if (role !== 'assistant') {
        return '';
    }

    return String(getMessageMarkdown(messageDiv, role) || '');
}

function buildMessageExportRequestBody(messageDiv, messageId, conversationId, role, extraFields = {}) {
    const requestBody = {
        message_id: messageId,
        conversation_id: conversationId,
        ...extraFields,
    };
    const messageContentOverride = getMessageContentOverride(messageDiv, role);
    if (messageContentOverride) {
        requestBody.message_content_override = messageContentOverride;
    }
    return requestBody;
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

function dataUriToBlob(dataUri, fallbackContentType = 'application/octet-stream') {
    const candidate = String(dataUri || '').trim();
    const commaIndex = candidate.indexOf(',');
    if (commaIndex === -1 || !candidate.startsWith('data:')) {
        return null;
    }

    const metadata = candidate.slice(5, commaIndex);
    const encodedPayload = candidate.slice(commaIndex + 1);
    const contentType = metadata.split(';')[0] || fallbackContentType;
    const isBase64 = metadata.toLowerCase().includes(';base64');
    let binaryString = '';
    try {
        binaryString = isBase64 ? atob(encodedPayload) : decodeURIComponent(encodedPayload);
    } catch (err) {
        console.warn('Unable to decode email draft attachment data URI:', err);
        return null;
    }

    const bytes = new Uint8Array(binaryString.length);
    for (let index = 0; index < binaryString.length; index += 1) {
        bytes[index] = binaryString.charCodeAt(index);
    }
    return new Blob([bytes], { type: contentType || fallbackContentType });
}

function safeDownloadFilename(filename, fallbackFilename) {
    const candidate = String(filename || '').trim() || fallbackFilename;
    return candidate.replace(/[<>:"/\\|?*\x00-\x1F]/g, '_');
}

function downloadEmailDraftAttachments(attachments) {
    if (!Array.isArray(attachments) || attachments.length === 0) {
        return 0;
    }

    let downloadedCount = 0;
    attachments.forEach((attachment, index) => {
        const dataUri = String(attachment?.data_uri || '').trim();
        if (!dataUri.startsWith('data:image/png;base64,')) {
            return;
        }

        const blob = dataUriToBlob(dataUri, attachment?.content_type || 'image/png');
        if (!blob) {
            return;
        }

        const filename = safeDownloadFilename(
            attachment?.filename,
            `message_chart_${index + 1}.png`
        );
        downloadBlob(blob, filename);
        downloadedCount += 1;
    });

    return downloadedCount;
}

function getPreferredMarkdownArtifactExportSource(messageDiv) {
    if (!(messageDiv instanceof HTMLElement)) {
        return null;
    }

    const artifactButton = messageDiv.querySelector('.generated-artifact-export-ppt-btn[data-artifact-message-id]');
    const artifactMessageId = String(artifactButton?.dataset.artifactMessageId || '').trim();
    const conversationId = String(artifactButton?.dataset.conversationId || window.currentConversationId || '').trim();
    if (!artifactMessageId || !conversationId) {
        return null;
    }

    return {
        artifactMessageId,
        conversationId,
    };
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

    const { sender } = getMessageMeta(messageDiv, role);

    const lines = [];
    lines.push(`### ${sender}`);
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
            body: JSON.stringify(buildMessageExportRequestBody(messageDiv, messageId, conversationId, role))
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
 * Export a single message as a PowerPoint (.pptx) presentation by calling
 * the backend endpoint that uses python-pptx to generate slides.
 */
export async function exportMessageAsPowerPoint(messageDiv, messageId, role, options = {}) {
    const preferredArtifactSource = options.artifactMessageId
        ? {
            artifactMessageId: String(options.artifactMessageId || '').trim(),
            conversationId: String(options.conversationId || window.currentConversationId || '').trim(),
        }
        : getPreferredMarkdownArtifactExportSource(messageDiv);
    const conversationId = preferredArtifactSource?.conversationId || window.currentConversationId;
    if (!conversationId || !messageId) {
        showToast('Cannot export - no active conversation or message.', 'warning');
        return;
    }

    try {
        const requestBody = buildMessageExportRequestBody(messageDiv, messageId, conversationId, role);
        if (preferredArtifactSource?.artifactMessageId) {
            requestBody.artifact_message_id = preferredArtifactSource.artifactMessageId;
            delete requestBody.message_content_override;
        }

        const response = await fetch('/api/message/export-powerpoint', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(requestBody)
        });

        if (!response.ok) {
            const errorData = await response.json().catch(() => null);
            const errorMsg = errorData?.error || `Export failed (${response.status})`;
            showToast(errorMsg, 'danger');
            return;
        }

        const blob = await response.blob();
        const filename = `message_export_${filenameTimestamp()}.pptx`;
        downloadBlob(blob, filename);
        showToast(
            preferredArtifactSource?.artifactMessageId
                ? 'Markdown artifact exported as PowerPoint.'
                : 'Message exported as PowerPoint.',
            'success'
        );
    } catch (err) {
        console.error('Error exporting message to PowerPoint:', err);
        showToast('Failed to export message to PowerPoint.', 'danger');
    }
}

/**
 * Insert the message content as a formatted prompt directly into the chat
 * input box so the user can review, edit, and send it.
 * The raw message content is inserted unchanged for both user and AI messages.
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
export async function openInEmail(messageDiv, messageId, role) {
    const conversationId = window.currentConversationId;
    if (!conversationId || !messageId) {
        showToast('Cannot email — no active conversation or message.', 'warning');
        return;
    }

    const content = getMessageMarkdown(messageDiv, role);
    if (!content) {
        showToast('No message content to email.', 'warning');
        return;
    }

    try {
        const response = await fetch('/api/message/export-email-draft', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(buildMessageExportRequestBody(messageDiv, messageId, conversationId, role))
        });

        const data = await response.json().catch(() => null);
        if (!response.ok) {
            const errorMsg = data?.error || `Email export failed (${response.status})`;
            showToast(errorMsg, 'danger');
            return;
        }

        const subject = data?.subject || 'Shared chat message';
        const body = data?.body || content;
        const downloadedAttachmentCount = downloadEmailDraftAttachments(data?.attachments);
        const mailtoUrl = `mailto:?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;
        if (downloadedAttachmentCount > 0) {
            showToast(
                `${downloadedAttachmentCount} visual PNG ${downloadedAttachmentCount === 1 ? 'file' : 'files'} downloaded for the email draft.`,
                'success'
            );
        }
        window.location.href = mailtoUrl;
    } catch (err) {
        console.error('Error exporting message to email:', err);
        showToast('Failed to open email draft.', 'danger');
    }
}

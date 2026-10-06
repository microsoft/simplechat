// conversationMedia.ts
// Every image, video and audio clip in a conversation, for the Media section of the drawer.
//
// Media reaches a thread three ways: an image message (generated or uploaded), an image placed
// in a reply with `![caption](url)`, and a recording or clip linked in a reply, which the thread
// plays in place (see inlineMedia.ts). Replies often carry media an action fetched from a remote
// service as a signed URL, which is exactly what is hard to find again in a long thread.
//
// Only what the thread itself shows is listed: masked text is scanned with its masked spans
// removed, a fully masked message is skipped, and so is a message a workflow reply replaced.

import { resolveImageSource } from './images';
import { inlineMediaKind, inlineMediaTitle, safeMediaUrl } from './inlineMedia';
import { applyMasks, readMaskState } from './masking';
import { isAgentPostedMessage, isSupersededByWorkflowReply } from './sharedMessage';
import type { ChatMessage } from './types';

export interface ConversationMediaItem {
    /** Unique per media file, so one shown in several messages is listed once. */
    key: string;
    kind: 'image' | 'video' | 'audio';
    /** Ready for `src`: an image source as `resolveImageSource` returns it, or an absolute URL. */
    src: string;
    title: string;
    messageId: string;
}

/** Fenced and inline code: a URL shown as code is not media the reply displayed. */
const CODE_PATTERN = /```[\s\S]*?(?:```|$)|`[^`\n]*`/g;
/** `![alt](url "title")` and `[text](url "title")`, with an optional `<url>` form. */
const MARKDOWN_LINK_PATTERN = /(!?)\[([^\]]*)\]\(\s*<?([^\s<>()]+)>?(?:\s+"[^"]*")?\s*\)/g;
const TITLE_MAX_LENGTH = 160;

function shortTitle(value: string, fallback: string): string {
    const title = value.replace(/\s+/g, ' ').trim();
    return (title || fallback).slice(0, TITLE_MAX_LENGTH);
}

function visibleMarkdown(message: ChatMessage): string | null {
    const masks = readMaskState(message);
    if (masks.fullyMasked) {
        return null;
    }
    const content = String(message.content ?? '');
    return masks.ranges.length > 0 ? applyMasks(content, masks.ranges).text : content;
}

function imageMessageTitle(message: ChatMessage): string {
    const metadata = (message.metadata && typeof message.metadata === 'object' && !Array.isArray(message.metadata)
        ? message.metadata
        : {}) as Record<string, unknown>;
    const candidates = [message.filename, metadata.prompt, metadata.revised_prompt, metadata.filename];
    const named = candidates.find((value): value is string => typeof value === 'string' && Boolean(value.trim()));
    return shortTitle(named ?? '', metadata.is_user_upload ? 'Uploaded image' : 'Generated image');
}

/** The media of one message, in the order it appears. */
export function messageMedia(message: ChatMessage): ConversationMediaItem[] {
    if (!message?.id || isSupersededByWorkflowReply(message)) {
        return [];
    }

    if (message.role === 'image') {
        if (readMaskState(message).fullyMasked) {
            return [];
        }
        const source = resolveImageSource(message.content);
        return source
            ? [{ key: `image:${source.src}`, kind: 'image', src: source.src, title: imageMessageTitle(message), messageId: message.id }]
            : [];
    }

    // Replies, and messages an agent posted, are markdown. What people type is plain text.
    if (message.role !== 'assistant' && !isAgentPostedMessage(message)) {
        return [];
    }
    const markdown = visibleMarkdown(message);
    if (!markdown) {
        return [];
    }

    const items: ConversationMediaItem[] = [];
    for (const match of markdown.replace(CODE_PATTERN, ' ').matchAll(MARKDOWN_LINK_PATTERN)) {
        const [, bang, text, url] = match;
        if (bang) {
            const source = resolveImageSource(url);
            if (source) {
                items.push({
                    key: `image:${source.src}`,
                    kind: 'image',
                    src: source.src,
                    title: shortTitle(text, 'Image'),
                    messageId: message.id,
                });
            }
            continue;
        }
        const kind = inlineMediaKind(url);
        const src = safeMediaUrl(url);
        if (kind && src) {
            items.push({
                key: `${kind}:${src}`,
                kind,
                src,
                title: shortTitle(inlineMediaTitle(text, src), kind === 'audio' ? 'Audio' : 'Video'),
                messageId: message.id,
            });
        }
    }
    return items;
}

/** Every media item in the conversation, oldest first, each file once. */
export function collectConversationMedia(messages: readonly ChatMessage[]): ConversationMediaItem[] {
    const seen = new Set<string>();
    const items: ConversationMediaItem[] = [];
    for (const message of messages) {
        for (const item of messageMedia(message)) {
            if (!seen.has(item.key)) {
                seen.add(item.key);
                items.push(item);
            }
        }
    }
    return items;
}

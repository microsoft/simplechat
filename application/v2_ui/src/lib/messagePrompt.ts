// messagePrompt.ts
// Splitting a sent message back into the prompt that shaped it and the words you wrote.
//
// The stored content of such a message is the two concatenated, because that is what was sent
// to the model. Drawing it back as one blob is what made a saved prompt unpleasant to use:
// your actual question ends up as two lines somewhere inside four paragraphs of standing
// instructions, and the reply reads as though it answered something you did not ask.
//
// So the pieces are recovered and drawn apart. Three sources are tried, most trustworthy
// first, and if none of them work the message renders exactly as it does today. That last
// branch is the important one: every message sent before this existed goes through it, and a
// heuristic that guessed would rewrite old conversations rather than leave them alone.

import type { ChatMessage } from './types';

export interface MessagePrompt {
    name: string;
    /** The prompt as it was actually sent, variables filled in. */
    promptText: string;
    /** What was typed under it. Empty when the prompt was the whole message. */
    userText: string;
}

function asRecord(value: unknown): Record<string, unknown> | null {
    return value && typeof value === 'object' && !Array.isArray(value)
        ? (value as Record<string, unknown>)
        : null;
}

function asText(value: unknown): string {
    return typeof value === 'string' ? value : '';
}

/**
 * The prompt behind a sent message, or null to render it unchanged.
 *
 * Null is returned whenever the split cannot be made honestly: no prompt metadata, no prompt
 * text, or a stored content that does not begin with the prompt it claims to have used. A
 * message that has been edited since, or was assembled by a client that pasted rather than
 * attached, falls into that last case and is left alone.
 */
export function readMessagePrompt(message: Pick<ChatMessage, 'content' | 'metadata'>): MessagePrompt | null {
    const selection = asRecord(asRecord(message?.metadata)?.prompt_selection);
    if (!selection) {
        return null;
    }

    const promptText = asText(selection.selected_prompt_text).trim();
    if (!promptText) {
        return null;
    }

    const name = asText(selection.prompt_name).trim() || 'Prompt';
    const content = asText(message?.content);

    // What the composer recorded it had typed underneath. Trusted when the two still add up,
    // which is the check that keeps a later edit to the message from being mis-split.
    const recorded = selection.user_text;
    if (typeof recorded === 'string') {
        const userText = recorded.trim();
        const expected = userText ? `${promptText}\n\n${userText}` : promptText;
        if (content.trim() === expected) {
            return { name, promptText, userText };
        }
    }

    // No record, or it no longer matches: fall back to removing the prompt from the front of
    // the message. Only from the front, because that is the one position the composer puts it
    // in; searching for it anywhere would find and remove a quotation of it.
    const trimmed = content.trim();
    if (trimmed.startsWith(promptText)) {
        return { name, promptText, userText: trimmed.slice(promptText.length).trim() };
    }

    return null;
}

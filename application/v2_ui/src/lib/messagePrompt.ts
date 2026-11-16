// messagePrompt.ts
// Splitting a sent message back into the prompt that shaped it and the words you wrote.
//
// The stored content of such a message is the two concatenated, because that is what was sent
// to the model. Drawing it back as one blob is what made a saved prompt unpleasant to use:
// your actual question ends up as two lines somewhere inside four paragraphs of standing
// instructions, and the reply reads as though it answered something you did not ask.
//
// Recover only a composition the stored message still proves. A stale attachment must not
// rewrite an edited message or reveal text that the message no longer contains.

import { composePromptMessage } from './promptRequest';
import { parsePromptVariables } from './promptVariables';
import type { ChatMessage } from './types';

export interface MessagePrompt {
    name: string;
    /** The prompt as it was actually sent, variables filled in. */
    promptText: string;
    /** What was typed, including text positioned inside the prompt by {{composer}}. */
    userText: string;
    scopeLabel?: string;
    edited: boolean;
    variableCount: number;
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
 * New snapshots must match their complete recorded composition. Older metadata without a
 * recorded tail can use the exact blank-line delimiter, never just a matching prefix.
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

    const content = asText(message?.content).trim();
    const hasSnapshot = ['template_content', 'composer_text', 'composer_embedded'].some(
        (key) => key in selection,
    );
    const template = asText(selection.template_content);
    const fields = hasSnapshot ? parsePromptVariables(template) : [];
    const scopeLabel = asText(selection.scope_name).trim() || asText(selection.scope_type).trim();
    const details = {
        name: asText(selection.prompt_name).trim() || 'Prompt',
        promptText,
        ...(scopeLabel ? { scopeLabel } : {}),
        edited: selection.prompt_edited === true,
        variableCount: hasSnapshot
            ? fields.length
            : Object.values(asRecord(selection.prompt_variables) ?? {}).filter(
                (value) => typeof value === 'string' && value.trim(),
            ).length,
    };

    if (hasSnapshot) {
        if (
            typeof selection.template_content !== 'string'
            || typeof selection.composer_text !== 'string'
            || typeof selection.composer_embedded !== 'boolean'
            || typeof selection.user_text !== 'string'
        ) {
            return null;
        }
        const composerText = selection.composer_text.trim();
        const embedded = selection.composer_embedded;
        const tail = embedded ? '' : composerText;
        if (
            embedded !== fields.some((variable) => variable.key === 'composer')
            || selection.user_text.trim() !== tail
            || composePromptMessage(promptText, tail) !== content
            || (embedded && composerText !== '' && !promptText.includes(composerText))
        ) {
            return null;
        }
        return { ...details, userText: composerText };
    }

    const recorded = selection.user_text;
    if (typeof recorded === 'string') {
        const userText = recorded.trim();
        return composePromptMessage(promptText, userText) === content
            ? { ...details, userText }
            : null;
    }
    if (recorded !== undefined && recorded !== null) {
        return null;
    }
    if (content === promptText) {
        return { ...details, userText: '' };
    }
    if (content.startsWith(`${promptText}\n\n`)) {
        return { ...details, userText: content.slice(promptText.length + 2).trim() };
    }

    return null;
}

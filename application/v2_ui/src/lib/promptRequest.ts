// promptRequest.ts
// Turning an attached prompt into the message that is sent and the `prompt_info` that
// describes it.
//
// One builder, used by the chat request and the orchestration seeds alike. They used to
// disagree in the worst possible way: the orchestration path sent `prompt_info` and the
// ordinary chat path sent nothing at all, so using a saved prompt in a normal turn left no
// record that a prompt had been involved -- no metadata to render it with afterwards, and
// nothing for the planner to read.
//
// The prompt goes first and what you typed goes after it. That is the order the two are
// actually written in: the prompt is the standing instruction and the message underneath is
// the particular thing being asked. Reversing them buries the instruction under its own input.

import { parsePromptVariables } from './promptVariables';
import type { Json } from './types';

/** A saved prompt carried by the turn being written. */
export interface AttachedPrompt {
    id: string;
    name: string;
    scopeType?: string;
    scopeName?: string;
    /** The prompt as saved. Kept so an edit can be reverted and reported as an edit. */
    originalContent: string;
    /** Wording changed for this turn only, or null. Never written back to the saved prompt. */
    editedContent: string | null;
}

/** The wording this turn will use. */
export function attachedPromptContent(attached: AttachedPrompt): string {
    return attached.editedContent ?? attached.originalContent;
}

export function attachedPromptIsEdited(attached: AttachedPrompt): boolean {
    return (
        attached.editedContent !== null && attached.editedContent !== attached.originalContent
    );
}

/**
 * The single message body built from the prompt and what was typed under it.
 *
 * Either side may be empty: a prompt that needs no further input is a complete message on its
 * own, which is why the composer allows sending without typing anything.
 */
export function composePromptMessage(promptText: string, userText: string): string {
    const prompt = String(promptText ?? '').trim();
    const typed = String(userText ?? '').trim();
    if (prompt && typed) {
        return `${prompt}\n\n${typed}`;
    }
    return prompt || typed;
}

/**
 * Whether the prompt places what you typed itself, via `{{composer}}`.
 *
 * Such a prompt has already consumed the message -- "summarise the following: {{composer}}" --
 * so appending it underneath as well would send it twice, once inside the instruction and once
 * after it. A prompt that asks for the text by name is asking to position it.
 */
export function promptConsumesComposer(content: string): boolean {
    return parsePromptVariables(content).some((variable) => variable.key === 'composer');
}

/**
 * The message this turn sends, given a resolved prompt and what was typed.
 *
 * Split from `composePromptMessage` so the composition rule and the `{{composer}}` exception
 * are testable apart from each other.
 */
export function buildOutgoingMessage(
    promptContent: string,
    promptText: string,
    userText: string,
): { message: string; userText: string } {
    if (promptConsumesComposer(promptContent)) {
        return { message: String(promptText ?? '').trim(), userText: '' };
    }
    return {
        message: composePromptMessage(promptText, userText),
        userText: String(userText ?? '').trim(),
    };
}

/**
 * The `prompt_selection` metadata shape the server stores against a message.
 *
 * Mirrored here so the optimistic user message can be drawn the same way the echoed one will
 * be. Without it the bubble renders as one blob until the server replies and then silently
 * rearranges itself, which reads as a glitch rather than as an update.
 */
export function promptSelectionMetadata(promptInfo: Json): Json {
    const info = (promptInfo ?? {}) as Record<string, unknown>;
    return {
        prompt_id: info.id ?? null,
        prompt_name: info.name ?? null,
        selected_prompt_text: info.content ?? '',
        original_prompt_text: info.original_content ?? '',
        prompt_variables: info.variables ?? {},
        prompt_edited: Boolean(info.edited),
        user_text: info.user_text ?? '',
    };
}

/**
 * What the server is told about the prompt behind a message.
 *
 * `content` is the resolved text that actually went to the model, `original_content` is the
 * prompt as saved, and `user_text` is what was typed under it. The last one is what lets the
 * sent message be drawn as a collapsed prompt plus your own words rather than one blob: the
 * stored message content is the two concatenated, and nothing else can tell them apart.
 */
export function buildPromptInfo({
    attached,
    promptText,
    userText,
    values,
}: {
    attached: AttachedPrompt;
    promptText: string;
    userText: string;
    values: Record<string, string>;
}): Json {
    return {
        id: attached.id,
        name: attached.name,
        content: promptText,
        original_content: attached.originalContent,
        // Only what was supplied. Empty entries would read as answered placeholders.
        variables: Object.fromEntries(
            Object.entries(values ?? {}).filter(([, value]) => String(value ?? '').trim()),
        ),
        edited: attachedPromptIsEdited(attached),
        user_text: String(userText ?? '').trim(),
    };
}

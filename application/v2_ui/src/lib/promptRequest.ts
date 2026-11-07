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
    const info = promptInfo && typeof promptInfo === 'object' && !Array.isArray(promptInfo)
        ? promptInfo
        : {};
    const text = (value: unknown) => typeof value === 'string' ? value : null;
    const template = text(info.template_content);
    const activeKeys = template === null
        ? null
        : new Set(parsePromptVariables(template).map((variable) => variable.key));
    const variables = info.variables && typeof info.variables === 'object' && !Array.isArray(info.variables)
        ? info.variables as Record<string, unknown>
        : {};
    return {
        selected_prompt_index: typeof info.index === 'string' || Number.isInteger(info.index)
            ? info.index
            : null,
        prompt_id: text(info.id),
        prompt_name: text(info.name),
        selected_prompt_text: text(info.content),
        original_prompt_text: text(info.original_content),
        prompt_variables: Object.fromEntries(Object.entries(variables).filter(
            ([key, value]) => typeof value === 'string' && value.trim()
                && (activeKeys === null || activeKeys.has(key)),
        )),
        prompt_edited: info.edited === true,
        user_text: text(info.user_text)?.trim() ?? null,
        ...('template_content' in info ? { template_content: info.template_content } : {}),
        ...('composer_text' in info ? {
            composer_text: text(info.composer_text)?.trim() ?? info.composer_text,
        } : {}),
        ...('composer_embedded' in info ? { composer_embedded: info.composer_embedded } : {}),
        ...('scope_type' in info ? { scope_type: text(info.scope_type) } : {}),
        ...('scope_name' in info ? { scope_name: text(info.scope_name) } : {}),
    };
}

/**
 * What the server is told about the prompt behind a message.
 *
 * `content` is the resolved text that actually went to the model, `original_content` is the
 * prompt as saved, and `user_text` is the appended tail. `composer_text` keeps the actual
 * words typed even when `{{composer}}` placed them inside the prompt instead.
 */
export function buildPromptInfo({
    attached,
    promptText,
    userText,
    composerText = userText,
    values,
}: {
    attached: AttachedPrompt;
    promptText: string;
    userText: string;
    composerText?: string;
    values: Record<string, string>;
}): Json {
    const template = attachedPromptContent(attached);
    const activeKeys = new Set(parsePromptVariables(template).map((variable) => variable.key));
    const composerEmbedded = activeKeys.has('composer');
    return {
        id: attached.id,
        name: attached.name,
        content: promptText,
        original_content: attached.originalContent,
        template_content: template,
        composer_text: String(composerText ?? '').trim(),
        composer_embedded: composerEmbedded,
        scope_type: attached.scopeType ?? null,
        scope_name: attached.scopeName ?? null,
        // Removed fields and remembered values for other prompts are not part of this turn.
        variables: Object.fromEntries(
            Object.entries(values ?? {}).filter(
                ([key, value]) => activeKeys.has(key) && typeof value === 'string' && value.trim(),
            ),
        ),
        edited: attachedPromptIsEdited(attached),
        user_text: composerEmbedded ? '' : String(userText ?? '').trim(),
    };
}

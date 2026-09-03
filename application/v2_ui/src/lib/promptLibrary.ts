// promptLibrary.ts
// The workbench's list rules: what a search matches, what order rows come in, and what a
// duplicate is called.
//
// Separate from the components so the rules can be executed in a test rather than inferred
// from a rendered list. The failure modes here are all quiet ones -- a sort that puts a
// favourite in the middle, a search that only looks at the name, a duplicate that collides with
// the name it was copied from -- and none of them throw.

import { formatRelativeDate } from './documentExplorer';
import { countPromptVariables } from './promptVariables';
import type { WorkspacePrompt } from './types';

/** The date a row reports. `updated_at` is what the server orders by. */
export function promptDate(prompt: WorkspacePrompt): Date | null {
    const raw = prompt.updated_at ?? prompt.created_at;
    if (!raw) {
        return null;
    }
    const parsed = new Date(String(raw));
    return Number.isNaN(parsed.getTime()) ? null : parsed;
}

/**
 * The query parameter that hands a prompt from the workbench to the composer.
 *
 * Owned by `conversationUrl.ts`, which owns the vocabulary of the chat URL and is the single
 * writer of its query string. Re-exported here so the prompt surfaces have one import.
 */
export { PROMPT_PARAM, chatHrefForPrompt, readPromptParam } from './conversationUrl';

export function promptUpdatedLabel(prompt: WorkspacePrompt, now: Date = new Date()): string {
    return formatRelativeDate(promptDate(prompt), now);
}

export function promptName(prompt: WorkspacePrompt): string {
    return String(prompt.name ?? '').trim() || 'Untitled prompt';
}

export function isFavoritePrompt(prompt: WorkspacePrompt): boolean {
    return prompt.is_favorite === true;
}

/**
 * Whether a prompt matches a search.
 *
 * Covers the body as well as the name and description. Searching only names is the behaviour
 * the section had, and it fails exactly when it is most needed: looking for the prompt that
 * mentions a particular system when you cannot remember what you called it.
 */
export function promptMatchesQuery(prompt: WorkspacePrompt, query: string): boolean {
    const needle = String(query ?? '')
        .trim()
        .toLowerCase();
    if (!needle) {
        return true;
    }
    return [prompt.name, prompt.description, prompt.content]
        .map((part) => String(part ?? '').toLowerCase())
        .some((part) => part.includes(needle));
}

export type PromptSort = 'recent' | 'name';

/**
 * Order a list for display.
 *
 * Favourites float to the top in both orders, and that is done here rather than in the Cosmos
 * query: `list_prompts` pages with `ORDER BY c.updated_at DESC OFFSET/LIMIT`, so adding a second
 * sort key would need a composite index, and prompts written before `is_favorite` existed have
 * no such property for the index to cover. Sorting a few hundred rows in the client costs
 * nothing and works on every existing document.
 */
export function sortPrompts(
    prompts: WorkspacePrompt[],
    sort: PromptSort = 'recent',
): WorkspacePrompt[] {
    return prompts.slice().sort((left, right) => {
        const leftFavourite = isFavoritePrompt(left);
        const rightFavourite = isFavoritePrompt(right);
        if (leftFavourite !== rightFavourite) {
            return leftFavourite ? -1 : 1;
        }

        if (sort === 'name') {
            return promptName(left).localeCompare(promptName(right));
        }

        const leftTime = promptDate(left)?.getTime() ?? 0;
        const rightTime = promptDate(right)?.getTime() ?? 0;
        if (leftTime !== rightTime) {
            return rightTime - leftTime;
        }
        // A stable tiebreak, so two prompts saved in the same second do not swap places on
        // every refresh.
        return promptName(left).localeCompare(promptName(right));
    });
}

export function visiblePrompts(
    prompts: WorkspacePrompt[],
    query: string,
    sort: PromptSort = 'recent',
): WorkspacePrompt[] {
    return sortPrompts(
        prompts.filter((prompt) => promptMatchesQuery(prompt, query)),
        sort,
    );
}

/** One line of body text for a list row, with markdown noise removed. */
export function promptPreview(prompt: WorkspacePrompt, maxLength = 140): string {
    const text = String(prompt.content ?? '')
        .replace(/```[\s\S]*?```/g, ' ')
        .replace(/[#>*_`]+/g, '')
        .replace(/\s+/g, ' ')
        .trim();
    if (text.length <= maxLength) {
        return text;
    }
    return `${text.slice(0, maxLength).trimEnd()}…`;
}

export function promptVariableCount(prompt: WorkspacePrompt): number {
    return countPromptVariables(String(prompt.content ?? ''));
}

/**
 * A free name for a copy.
 *
 * Counts up rather than appending "copy" repeatedly, so duplicating three times gives
 * "X (copy)", "X (copy 2)", "X (copy 3)" instead of "X (copy) (copy) (copy)". Comparison is
 * case-insensitive because the list is, and two prompts differing only in case read as
 * duplicates to everyone but the database.
 */
export function duplicatePromptName(name: string, existing: string[]): string {
    const base = String(name ?? '').trim() || 'Untitled prompt';
    const taken = new Set(existing.map((item) => String(item ?? '').trim().toLowerCase()));

    const first = `${base} (copy)`;
    if (!taken.has(first.toLowerCase())) {
        return first;
    }

    for (let index = 2; index < 100; index += 1) {
        const candidate = `${base} (copy ${index})`;
        if (!taken.has(candidate.toLowerCase())) {
            return candidate;
        }
    }

    return `${base} (copy ${Date.now()})`;
}

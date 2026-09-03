// promptVariableMemory.ts
// The values you last used for a prompt's variables, remembered so you do not retype them.
//
// This never touches the server. Variable values are free text and people paste customer
// names, case numbers, patient identifiers and API keys into them; a preference that syncs is
// the right call for a colour theme and the wrong one for that. Everything here stays in this
// browser, and `forgetPromptValues` genuinely removes it.
//
// Memory is keyed by prompt **and** variable, never by variable alone. "Name" means a customer
// in one prompt and a product in another, and a store keyed on the bare name would pre-fill one
// into the other -- the specific failure that makes an auto-filled value worse than an empty
// box, because it is plausible enough to send without reading.
//
// Caps are enforced on write rather than trusted on read: this is `localStorage`, it is shared
// with the classic interface, and it is quota-limited for the whole origin.

/** Where the map lives. Namespaced like the other V2 client-only keys in uiStore.ts. */
export const PROMPT_VARIABLE_STORAGE_KEY = 'simplechat.v2.prompt-vars';

/** How many previous values to offer per variable. Enough to pick from, short enough to scan. */
export const MAX_REMEMBERED_VALUES = 5;

/** Caps that exist to bound the stored document rather than to express a product rule. */
export const MAX_REMEMBERED_VARIABLES = 50;
export const MAX_REMEMBERED_PROMPTS = 40;
export const MAX_REMEMBERED_VALUE_LENGTH = 2000;

/** `{ [promptId]: { [variableKey]: string[] } }`, most recent value first. */
export type PromptVariableMemory = Record<string, Record<string, string[]>>;

/**
 * Shapes that should not be written to disk.
 *
 * Not a security control -- someone determined to store a secret in a prompt variable will
 * succeed -- but it removes the common accidents: a pasted bearer token, an Azure or OpenAI
 * key, a private key block. The cost of a false positive is only that a value is not offered
 * back, which is exactly what should happen to anything that looks like this.
 */
const SECRET_PATTERNS: RegExp[] = [
    /-----BEGIN [A-Z ]*PRIVATE KEY-----/,
    /\bBearer\s+[A-Za-z0-9._~+/-]{16,}/i,
    /\bsk-[A-Za-z0-9]{16,}\b/,
    /\bgh[pousr]_[A-Za-z0-9]{20,}\b/,
    /\bxox[abprs]-[A-Za-z0-9-]{10,}\b/,
    /\b(?:api[_-]?key|client[_-]?secret|password|connection[_-]?string)\b\s*[:=]/i,
    /\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\./,
];

export function looksLikeSecret(value: string): boolean {
    const text = String(value ?? '');
    if (!text.trim()) {
        return false;
    }
    return SECRET_PATTERNS.some((pattern) => pattern.test(text));
}

function readRaw(): PromptVariableMemory {
    try {
        const stored = localStorage.getItem(PROMPT_VARIABLE_STORAGE_KEY);
        if (!stored) {
            return {};
        }
        const parsed: unknown = JSON.parse(stored);
        return isMemory(parsed) ? parsed : {};
    } catch {
        // Private browsing, a disabled store, or a value another version wrote in a shape this
        // one cannot read. Starting empty is correct in all three.
        return {};
    }
}

function isMemory(value: unknown): value is PromptVariableMemory {
    if (!value || typeof value !== 'object' || Array.isArray(value)) {
        return false;
    }
    return Object.values(value as Record<string, unknown>).every(
        (entry) =>
            Boolean(entry) &&
            typeof entry === 'object' &&
            !Array.isArray(entry) &&
            Object.values(entry as Record<string, unknown>).every(
                (values) => Array.isArray(values) && values.every((item) => typeof item === 'string'),
            ),
    );
}

function writeRaw(memory: PromptVariableMemory): void {
    try {
        localStorage.setItem(PROMPT_VARIABLE_STORAGE_KEY, JSON.stringify(memory));
    } catch {
        // A full or unavailable store must not break using a prompt. The values were a
        // convenience; the prompt still works without them.
    }
}

/**
 * Trim a memory document to the caps.
 *
 * Exported so the logic test can exercise it directly, and because doing it in one place is
 * what stops `rememberPromptValues` from having to reason about three limits at once. Prompts
 * are dropped from the end, which is insertion order: the least recently written prompt goes
 * first because a fresh write re-inserts its key at the end.
 */
export function pruneMemory(memory: PromptVariableMemory): PromptVariableMemory {
    const pruned: PromptVariableMemory = {};
    const promptIds = Object.keys(memory).slice(-MAX_REMEMBERED_PROMPTS);

    for (const promptId of promptIds) {
        const variables = memory[promptId] ?? {};
        const kept: Record<string, string[]> = {};
        for (const key of Object.keys(variables).slice(-MAX_REMEMBERED_VARIABLES)) {
            const values = (variables[key] ?? [])
                .filter((value) => typeof value === 'string' && value !== '')
                .slice(0, MAX_REMEMBERED_VALUES);
            if (values.length > 0) {
                kept[key] = values;
            }
        }
        if (Object.keys(kept).length > 0) {
            pruned[promptId] = kept;
        }
    }

    return pruned;
}

/** Every remembered value for a prompt, most recent first. */
export function recallPromptValues(promptId: string): Record<string, string[]> {
    if (!promptId) {
        return {};
    }
    return readRaw()[promptId] ?? {};
}

/**
 * The single value to pre-fill per variable.
 *
 * Separate from `recallPromptValues` because the two are used differently and confusing them
 * is how a field ends up pre-filled with an array. The caller decides whether to apply this at
 * all -- it does not in a shared conversation, where a value remembered from a private chat
 * would become visible to everyone the moment the message is sent.
 */
export function suggestedPromptValues(promptId: string): Record<string, string> {
    const recalled = recallPromptValues(promptId);
    const suggested: Record<string, string> = {};
    for (const [key, values] of Object.entries(recalled)) {
        if (values.length > 0) {
            suggested[key] = values[0];
        }
    }
    return suggested;
}

/**
 * Record the values just used.
 *
 * A repeated value moves to the front rather than being appended again, so the list stays a
 * set ordered by recency. Empty values, over-long values and anything matching a secret shape
 * are skipped, which can leave a variable with nothing remembered at all -- the correct
 * outcome for a pasted token.
 */
export function rememberPromptValues(promptId: string, values: Record<string, string>): void {
    if (!promptId) {
        return;
    }

    const memory = readRaw();
    // Re-inserted so this prompt counts as the most recently written for pruning.
    const existing = memory[promptId] ?? {};
    delete memory[promptId];

    const next: Record<string, string[]> = { ...existing };
    let changed = false;

    for (const [key, rawValue] of Object.entries(values)) {
        const value = String(rawValue ?? '').trim();
        if (!value || value.length > MAX_REMEMBERED_VALUE_LENGTH || looksLikeSecret(value)) {
            continue;
        }
        const previous = next[key] ?? [];
        next[key] = [value, ...previous.filter((item) => item !== value)].slice(
            0,
            MAX_REMEMBERED_VALUES,
        );
        changed = true;
    }

    if (!changed && Object.keys(next).length === 0) {
        writeRaw(pruneMemory(memory));
        return;
    }

    memory[promptId] = next;
    writeRaw(pruneMemory(memory));
}

/** Drop everything remembered for one prompt. Surfaced in the details pane. */
export function forgetPromptValues(promptId: string): void {
    if (!promptId) {
        return;
    }
    const memory = readRaw();
    if (!(promptId in memory)) {
        return;
    }
    delete memory[promptId];
    writeRaw(memory);
}

/** Drop everything, for a shared machine. */
export function forgetAllPromptValues(): void {
    try {
        localStorage.removeItem(PROMPT_VARIABLE_STORAGE_KEY);
    } catch {
        // Nothing to do: the values are advisory and the store is unavailable.
    }
}

/** Whether a prompt has anything remembered, so the control can be hidden when it does not. */
export function hasRememberedPromptValues(promptId: string): boolean {
    return Object.keys(recallPromptValues(promptId)).length > 0;
}

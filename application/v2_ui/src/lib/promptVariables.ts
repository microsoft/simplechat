// promptVariables.ts
// Placeholders in a saved prompt, and the context the application can fill in for itself.
//
// A prompt is markdown, and markdown about templating languages is a real thing people write.
// `{{ user.name }}` inside a fenced block is documentation, not a variable, and treating it as
// one would rewrite the very example the prompt exists to explain. So parsing works from a mask
// of the regions markdown says are literal -- fenced blocks and inline code spans -- and only
// looks for variables outside them. A backslash escapes a single occurrence anywhere.
//
// The name pattern is deliberately strict. Anything goes between `{{` and `}}` in the wild, and
// a permissive parser turns `{{ this is prose, honestly }}` into a form field the user has to
// dismiss. Requiring a short, identifier-shaped name means the parser declines far more often
// than it guesses.
//
// Nothing here reads the DOM, the clock or storage: `resolveBuiltInPromptVariables` takes the
// current time as an argument precisely so the tests are not time-dependent.

/** How long a variable name may be, past the first character. */
const MAX_VARIABLE_NAME_TAIL = 39;

/**
 * A name we are willing to treat as a variable.
 *
 * First character is alphanumeric or an underscore, so `{{ 3 + 4 }}` and `{{-}}` are left
 * alone. The remainder additionally allows spaces and hyphens, because `{{customer name}}`
 * is how people actually write them.
 */
const VARIABLE_NAME_RE = new RegExp(`^[A-Za-z0-9_][A-Za-z0-9_ -]{0,${MAX_VARIABLE_NAME_TAIL}}$`);

/**
 * A candidate placeholder.
 *
 * `[^{}]` in the body is what stops `{{{a}}` and nested braces from matching across what a
 * reader would see as two separate constructs. The leading group captures an escaping
 * backslash so an escaped occurrence can be recognised and stripped in the same pass.
 *
 * Built fresh per call rather than shared at module scope: a `g` regex carries `lastIndex`,
 * and one instance driving both an `exec` loop and a `replace` is a stateful trap for whoever
 * adds the third caller.
 */
function placeholderPattern(): RegExp {
    return /(\\?)\{\{([^{}]*)\}\}/g;
}

/** The variables the application resolves without asking. */
export const BUILT_IN_PROMPT_VARIABLES = [
    'today',
    'now',
    'me',
    'conversation_title',
    'selected_documents',
    'last_response',
    'last_message',
    'composer',
] as const;

export type BuiltInPromptVariable = (typeof BUILT_IN_PROMPT_VARIABLES)[number];

/** What each built-in is, for the fill-in dialog's helper text. */
export const BUILT_IN_PROMPT_VARIABLE_LABELS: Record<BuiltInPromptVariable, string> = {
    today: "Today's date",
    now: 'The current date and time',
    me: 'Your display name',
    conversation_title: 'The title of this conversation',
    selected_documents: 'The documents currently in scope',
    last_response: 'The most recent assistant reply',
    last_message: 'The most recent message you sent',
    composer: 'What you have already typed',
};

export interface PromptVariable {
    /** The name as written, for display. */
    name: string;
    /** Normalised name, used for lookup, substitution and remembered values. */
    key: string;
    /** The literal written as `{{name|default}}`, or an empty string. */
    defaultValue: string;
    /** Whether the application resolves this one itself. */
    builtIn: boolean;
}

export interface PromptResolutionContext {
    /** Injected so formatting is deterministic under test. */
    now?: Date;
    userName?: string;
    conversationTitle?: string;
    selectedDocuments?: string[];
    lastAssistantMessage?: string;
    lastUserMessage?: string;
    composerText?: string;
}

/**
 * Normalise a written name to its lookup key.
 *
 * Spaces and hyphens both fold to an underscore, so `{{customer name}}`, `{{customer-name}}`
 * and `{{customer_name}}` are one variable rather than three fields asking the same question.
 */
export function promptVariableKey(name: string): string {
    return String(name ?? '')
        .trim()
        .toLowerCase()
        .replace(/[\s-]+/g, '_');
}

export function isBuiltInPromptVariable(key: string): boolean {
    return (BUILT_IN_PROMPT_VARIABLES as readonly string[]).includes(key);
}

interface Region {
    start: number;
    end: number;
}

function inRegions(index: number, regions: Region[]): boolean {
    return regions.some((region) => index >= region.start && index < region.end);
}

/**
 * The spans of a markdown document that are literal text.
 *
 * Fenced blocks are matched on their own opening run, so a ``` block containing ~~~ stays one
 * block. An unterminated fence runs to the end of the document, which is what a markdown
 * renderer does with it too, and is the safer reading here: it suppresses variables rather
 * than inventing them.
 */
export function literalCodeRegions(content: string): Region[] {
    const text = String(content ?? '');
    const regions: Region[] = [];

    const fenceRe = /^[ \t]{0,3}(`{3,}|~{3,})[^\n]*$/gm;
    let openFence: { marker: string; start: number } | null = null;
    let fenceMatch: RegExpExecArray | null;

    while ((fenceMatch = fenceRe.exec(text)) !== null) {
        const marker = fenceMatch[1];
        if (!openFence) {
            openFence = { marker, start: fenceMatch.index };
            continue;
        }
        // A closing fence must use the same character and be at least as long as the opener.
        if (marker[0] === openFence.marker[0] && marker.length >= openFence.marker.length) {
            regions.push({ start: openFence.start, end: fenceMatch.index + fenceMatch[0].length });
            openFence = null;
        }
    }

    if (openFence) {
        regions.push({ start: openFence.start, end: text.length });
    }

    // Inline spans, outside the fenced regions found above. A run of n backticks is closed by
    // the next run of exactly n, which is how markdown lets a span contain a backtick.
    const tickRe = /`+/g;
    let tickMatch: RegExpExecArray | null;
    let pendingOpen: { length: number; start: number } | null = null;

    while ((tickMatch = tickRe.exec(text)) !== null) {
        if (inRegions(tickMatch.index, regions)) {
            continue;
        }
        if (!pendingOpen) {
            pendingOpen = { length: tickMatch[0].length, start: tickMatch.index };
            continue;
        }
        if (tickMatch[0].length === pendingOpen.length) {
            regions.push({ start: pendingOpen.start, end: tickMatch.index + tickMatch[0].length });
            pendingOpen = null;
        }
    }

    return regions;
}

/**
 * The variables a prompt declares, in the order they first appear.
 *
 * Repeated occurrences collapse to one entry: the fill-in dialog asks once and substitutes
 * everywhere. A later occurrence carrying a default supplies it if the first did not, so
 * `{{tone}} ... {{tone|formal}}` still offers "formal" rather than nothing.
 */
export function parsePromptVariables(content: string): PromptVariable[] {
    const text = String(content ?? '');
    if (!text.includes('{{')) {
        return [];
    }

    const regions = literalCodeRegions(text);
    const found = new Map<string, PromptVariable>();

    const pattern = placeholderPattern();
    let match: RegExpExecArray | null;

    while ((match = pattern.exec(text)) !== null) {
        const [, escape, body] = match;
        if (escape) {
            continue;
        }
        // `match.index` points at the backslash slot, which is empty here, so it is also the
        // index of the opening brace.
        if (inRegions(match.index, regions)) {
            continue;
        }

        const separator = body.indexOf('|');
        const rawName = (separator === -1 ? body : body.slice(0, separator)).trim();
        const defaultValue = separator === -1 ? '' : body.slice(separator + 1).trim();

        if (!VARIABLE_NAME_RE.test(rawName)) {
            continue;
        }

        const key = promptVariableKey(rawName);
        const existing = found.get(key);
        if (existing) {
            if (!existing.defaultValue && defaultValue) {
                existing.defaultValue = defaultValue;
            }
            continue;
        }

        found.set(key, {
            name: rawName,
            key,
            defaultValue,
            builtIn: isBuiltInPromptVariable(key),
        });
    }

    return [...found.values()];
}

/** Whether a prompt has anything to fill in at all. Cheap enough for a list row. */
export function countPromptVariables(content: string): number {
    return parsePromptVariables(content).length;
}

function twoDigits(value: number): string {
    return String(value).padStart(2, '0');
}

/**
 * Format a date as `YYYY-MM-DD`.
 *
 * Built from local components rather than `toISOString`, which would report the previous day
 * for anyone west of UTC in the evening, and rather than `toLocaleDateString`, whose output
 * depends on the runner's locale and could not be asserted.
 */
function formatDate(value: Date): string {
    return `${value.getFullYear()}-${twoDigits(value.getMonth() + 1)}-${twoDigits(value.getDate())}`;
}

function formatDateTime(value: Date): string {
    return `${formatDate(value)} ${twoDigits(value.getHours())}:${twoDigits(value.getMinutes())}`;
}

/**
 * Values the application knows without asking.
 *
 * A built-in that has nothing behind it -- no documents in scope, no assistant reply yet -- is
 * left out rather than resolved to an empty string, so the dialog offers it as something to
 * fill instead of quietly substituting nothing.
 */
export function resolveBuiltInPromptVariables(
    context: PromptResolutionContext = {},
): Partial<Record<BuiltInPromptVariable, string>> {
    const now = context.now ?? new Date();
    const resolved: Partial<Record<BuiltInPromptVariable, string>> = {
        today: formatDate(now),
        now: formatDateTime(now),
    };

    const put = (key: BuiltInPromptVariable, value: string | undefined) => {
        const trimmed = String(value ?? '').trim();
        if (trimmed) {
            resolved[key] = trimmed;
        }
    };

    put('me', context.userName);
    put('conversation_title', context.conversationTitle);
    put('selected_documents', (context.selectedDocuments ?? []).filter(Boolean).join(', '));
    put('last_response', context.lastAssistantMessage);
    put('last_message', context.lastUserMessage);
    put('composer', context.composerText);

    return resolved;
}

/**
 * Substitute values into a prompt.
 *
 * A variable with no value and no default is left exactly as written. Blanking it would hide
 * the omission in the middle of a paragraph, where the visible `{{customer}}` is the thing
 * that makes someone notice before they press send.
 *
 * Code regions are left untouched for the same reason they are not parsed, and `\{{` loses its
 * backslash here -- that is the point of the escape, and the last chance to remove it.
 */
export function applyPromptVariables(content: string, values: Record<string, string>): string {
    const text = String(content ?? '');
    if (!text.includes('{{')) {
        return text;
    }

    const regions = literalCodeRegions(text);

    return text.replace(
        placeholderPattern(),
        (whole, escape: string, body: string, offset: number) => {
            if (escape) {
                return whole.slice(1);
            }
            if (inRegions(offset, regions)) {
                return whole;
            }

            const separator = body.indexOf('|');
            const rawName = (separator === -1 ? body : body.slice(0, separator)).trim();
            const defaultValue = separator === -1 ? '' : body.slice(separator + 1).trim();

            if (!VARIABLE_NAME_RE.test(rawName)) {
                return whole;
            }

            const supplied = values[promptVariableKey(rawName)];
            if (supplied !== undefined && supplied !== '') {
                return supplied;
            }
            return defaultValue || whole;
        },
    );
}

/** The variables still without a value or a default, for the dialog's status line. */
export function describeUnfilledVariables(
    variables: PromptVariable[],
    values: Record<string, string>,
): PromptVariable[] {
    return variables.filter(
        (variable) => !String(values[variable.key] ?? '').trim() && !variable.defaultValue,
    );
}

/** Whether using this prompt needs the fill-in dialog at all. */
export function promptNeedsFilling(content: string): boolean {
    return parsePromptVariables(content).length > 0;
}

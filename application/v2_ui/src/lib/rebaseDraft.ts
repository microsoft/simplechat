// rebaseDraft.ts
// The shared, pure conflict-rebase helper for the group editors, kept out of the renderers so it
// can be tested without a DOM.
//
// Every group editor detects a save conflict honestly -- a PATCH carries a revision or etag, and a
// stale one comes back as a 409 that keeps the draft open. The problem this module fixes is the
// *reload* after that conflict. A draft carries the whole record, so reloading only the write token
// and re-saving re-sends every field with its pre-conflict value, silently overwriting the other
// writer's changes to fields the user never touched -- the lost update the token exists to prevent.
//
// `rebaseDraft` merges the reloaded record into the open draft field by field:
//   - a field the user did not touch (draft equals the baseline) takes the reloaded value, so the
//     other writer's change is adopted and shown;
//   - a field the user edited keeps the user's value;
//   - a field all three disagree on -- the user edited it and the other writer changed it to a
//     different value -- keeps the user's value and is reported as a conflict, by its label.
//
// Secrets are never returned to the browser, so a secret field opens blank and a blank on save
// keeps the stored value. A secret is therefore never compared or copied into a notice: a value the
// user typed is kept, and a blank input adopts the reloaded stored state (the placeholder plus the
// stored/not-stored flags, which are ordinary fields).

/** One editable field the rebase considers, addressed by a dot path into the editable projection. */
export interface RebaseField {
    /** Dot path into the editable projection, for example `credentials.username`. */
    path: string;
    /** Human label used when a field both sides changed is reported. */
    label: string;
    /**
     * A secret input. The user's freshly typed value is kept; a blank input adopts the reloaded
     * stored state. A secret is never compared for equality and never named in a conflict.
     */
    secret?: boolean;
}

export interface RebaseResult<T> {
    /** The draft with untouched fields refreshed from the reloaded record and the user's edits kept. */
    draft: T;
    /** Labels of the fields the user and the other writer both changed to different values. */
    conflicts: string[];
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/** Structural equality over the plain-data shapes the editor drafts use (scalars, arrays, objects). */
export function deepEqual(a: unknown, b: unknown): boolean {
    if (a === b) {
        return true;
    }
    if (Array.isArray(a) && Array.isArray(b)) {
        return a.length === b.length && a.every((item, index) => deepEqual(item, b[index]));
    }
    if (isPlainObject(a) && isPlainObject(b)) {
        const keys = new Set([...Object.keys(a), ...Object.keys(b)]);
        for (const key of keys) {
            if (!deepEqual(a[key], b[key])) {
                return false;
            }
        }
        return true;
    }
    return false;
}

function clone<T>(value: T): T {
    if (Array.isArray(value)) {
        return value.map((item) => clone(item)) as unknown as T;
    }
    if (isPlainObject(value)) {
        const next: Record<string, unknown> = {};
        for (const [key, item] of Object.entries(value)) {
            next[key] = clone(item);
        }
        return next as unknown as T;
    }
    return value;
}

function getPath(source: unknown, path: string): unknown {
    return path.split('.').reduce<unknown>(
        (accumulator, key) => (isPlainObject(accumulator) ? accumulator[key] : undefined),
        source,
    );
}

function setPath(target: Record<string, unknown>, path: string, value: unknown): void {
    const keys = path.split('.');
    let cursor = target;
    for (let index = 0; index < keys.length - 1; index += 1) {
        const key = keys[index];
        if (!isPlainObject(cursor[key])) {
            cursor[key] = {};
        }
        cursor = cursor[key] as Record<string, unknown>;
    }
    cursor[keys[keys.length - 1]] = value;
}

/** A secret counts as "typed" when a non-empty value is present; a blank input keeps the stored one. */
function hasSecretValue(value: unknown): boolean {
    return typeof value === 'string' ? value.trim().length > 0 : value != null;
}

/**
 * Merge a reloaded record into an open draft. `baseline` is the record as the editor loaded it,
 * `fresh` is the reloaded record, and `draft` is the user's current copy -- all three in the same
 * editable projection. `fields` names the editable field paths to consider; any field absent from
 * the list is left as the draft holds it.
 */
export function rebaseDraft<T>(baseline: T, fresh: T, draft: T, fields: RebaseField[]): RebaseResult<T> {
    const rebased = clone(draft) as Record<string, unknown>;
    const conflicts: string[] = [];
    for (const field of fields) {
        const base = getPath(baseline, field.path);
        const incoming = getPath(fresh, field.path);
        const local = getPath(draft, field.path);
        if (field.secret) {
            // A typed secret wins; otherwise adopt the reloaded stored state. Never compared, never
            // reported.
            setPath(rebased, field.path, hasSecretValue(local) ? clone(local) : clone(incoming));
            continue;
        }
        if (deepEqual(local, base)) {
            // The user did not touch this field: take the other writer's value.
            setPath(rebased, field.path, clone(incoming));
            continue;
        }
        // The user changed this field: keep their value. If the other writer also changed it to a
        // different value, all three differ and it is a reportable conflict.
        setPath(rebased, field.path, clone(local));
        if (!deepEqual(incoming, base) && !deepEqual(incoming, local)) {
            conflicts.push(field.label);
        }
    }
    return { draft: rebased as T, conflicts };
}

/** The notice shown after a successful conflict reload, naming any fields both sides changed. */
export const REBASE_NOTICE =
    'Someone else changed this while you were editing. Their changes are loaded; your edits are kept. Review, then save.';

/** The notice shown when the record was deleted out from under an open editor. */
export const REBASE_DELETED_NOTICE = 'This item was deleted. Copy anything you need, then close.';

export function rebaseNotice(conflicts: string[]): string {
    if (conflicts.length === 0) {
        return REBASE_NOTICE;
    }
    return `${REBASE_NOTICE} You and someone else both changed: ${conflicts.join(', ')}. Your values are shown.`;
}

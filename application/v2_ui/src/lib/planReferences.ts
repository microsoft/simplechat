// planReferences.ts
// The `#` documents and tags a plan editor Ask request carries, and how they are shown back.
//
// A reference is a claim, not a permission: the server checks that the acting user can read it
// when the request is used. What this module owns is the request identity. The server holds a
// submission id to the request it first arrived with, and compares the canonical form of its
// references; this is the same canonical form, so the editor reuses an id exactly when the server
// would replay it. A reordered or repeated selection is the same request. A different selection,
// or another label for the same document, is a new one.
//
// Mirrors application/single_app/functions_assist_references.py. The two are pinned to each other
// by functional_tests/fixtures/plan_reference_canonicalization.json; change them together.
//
// Labels are untrusted display text. They are shown as text and named in error messages, and are
// never authorization.

import type { ContextItem } from './chatContext';

export const REFERENCE_LABEL_LIMIT = 200;
export const REFERENCE_IDENTIFIER_LIMIT = 512;
export const REQUEST_REFERENCE_LIMIT = 20;
/** Bounds the work done on a request before duplicates are removed. */
export const REQUEST_REFERENCE_RAW_LIMIT = 100;

export type PlanReferenceKind = 'document' | 'tag';
export type PlanReferenceScopeKind = 'personal' | 'group' | 'public';

/** One reference in canonical form, as the request sends it. */
export interface PlanReference {
    kind: PlanReferenceKind;
    id: string;
    scope: { kind: PlanReferenceScopeKind; id: string | null };
    label?: string;
}

/** A reference as the draft holds it, before it is checked. */
export interface PlanReferenceInput {
    kind: string;
    id: string;
    label?: string;
    scope: { kind: string; id: string | null; name?: string };
}

/** A `#` chip stored with a user turn: the server's label for what it authorized. */
export interface PlanTurnReference {
    kind: PlanReferenceKind;
    id: string;
    label: string;
    scope: { kind: PlanReferenceScopeKind; id: string | null };
}

/** Stored with the planner's turn when a revision first limited what the plan searches. */
export interface PlanScopeNotice {
    kind: 'search_limited';
    documents: string[];
    tags: string[];
    more: number;
}

/** A chip as a thread turn shows it. */
export interface PlanReferenceChip {
    key: string;
    kind: PlanReferenceKind;
    label: string;
}

export type PlanReferenceErrorCode = 'invalid_request' | 'reference_limit';

export class PlanReferenceError extends Error {
    readonly code: PlanReferenceErrorCode;

    constructor(message: string, code: PlanReferenceErrorCode = 'invalid_request') {
        super(message);
        this.name = 'PlanReferenceError';
        this.code = code;
    }
}

const PICKER_MESSAGE = 'Choose documents or tags from the # picker.';
const KIND_MESSAGE = 'Only documents and tags from your workspaces can be attached here.';
const REFERENCE_FIELDS = new Set(['kind', 'id', 'label', 'scope']);
const SCOPE_FIELDS = new Set(['kind', 'id', 'name']);

// Character sets are spelled out rather than left to String.prototype.trim, so this form matches
// the server's exactly whatever each runtime's Unicode tables say. Every member is one UTF-16
// unit, so the ends can be read a unit at a time. Bidirectional controls go with the other
// controls: a label sits inside a sentence and must not reorder the text around it.
const LABEL_CONTROL_CHARACTERS = /[\u0000-\u001f\u007f-\u009f\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069\ufeff]/g;
const LABEL_SPACE: ReadonlySet<string> = new Set([
    ' ', '\u00a0', '\u1680',
    ...Array.from({ length: 0x200b - 0x2000 }, (_, index) => String.fromCharCode(0x2000 + index)),
    '\u2028', '\u2029', '\u202f', '\u205f', '\u3000',
]);
const IDENTIFIER_SPACE: ReadonlySet<string> = new Set(['\t', '\n', '\v', '\f', '\r', ' ']);

function isRecord(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/** The fields a request would carry. JSON leaves out a field whose value is undefined. */
function sentFields(value: Record<string, unknown>): string[] {
    return Object.keys(value).filter((key) => value[key] !== undefined);
}

function stripEnds(value: string, characters: ReadonlySet<string>, leading = true): string {
    let start = 0;
    let end = value.length;
    while (leading && start < end && characters.has(value[start])) {
        start += 1;
    }
    while (end > start && characters.has(value[end - 1])) {
        end -= 1;
    }
    return value.slice(start, end);
}

/** The first `limit` code points of `text`, so a character outside the BMP counts once. */
function codePointPrefix(text: string, limit: number): string {
    let index = 0;
    for (let count = 0; index < text.length && count < limit; count += 1) {
        index += (text.codePointAt(index) ?? 0) > 0xffff ? 2 : 1;
    }
    return text.slice(0, index);
}

/** Compare by code point, the order the server sorts in; `<` compares UTF-16 units. */
function compareCodePoints(left: string, right: string): number {
    let index = 0;
    while (index < left.length && index < right.length) {
        const a = left.codePointAt(index) ?? 0;
        const b = right.codePointAt(index) ?? 0;
        if (a !== b) {
            return a < b ? -1 : 1;
        }
        index += a > 0xffff ? 2 : 1;
    }
    return (index < left.length ? 1 : 0) - (index < right.length ? 1 : 0);
}

/** The label a user picked, as plain display text: no control characters, bounded. */
export function sanitizeReferenceLabel(value: unknown, limit = REFERENCE_LABEL_LIMIT): string {
    if (typeof value !== 'string') {
        return '';
    }
    const text = stripEnds(value.replace(LABEL_CONTROL_CHARACTERS, ''), LABEL_SPACE);
    const kept = codePointPrefix(text, limit);
    return kept.length < text.length ? stripEnds(kept, LABEL_SPACE, false) : text;
}

function identifier(value: unknown): string {
    if (typeof value !== 'string') {
        throw new PlanReferenceError(PICKER_MESSAGE);
    }
    const text = stripEnds(value, IDENTIFIER_SPACE);
    if (!text || codePointPrefix(text, REFERENCE_IDENTIFIER_LIMIT).length < text.length) {
        throw new PlanReferenceError(PICKER_MESSAGE);
    }
    return text;
}

/** One reference in canonical form, or a PlanReferenceError. */
export function canonicalPlanReference(value: unknown): PlanReference {
    if (!isRecord(value) || sentFields(value).some((key) => !REFERENCE_FIELDS.has(key))) {
        throw new PlanReferenceError(PICKER_MESSAGE);
    }
    const kind = value.kind;
    if (kind !== 'document' && kind !== 'tag') {
        throw new PlanReferenceError(KIND_MESSAGE);
    }
    const scope = value.scope;
    if (!isRecord(scope) || sentFields(scope).some((key) => !SCOPE_FIELDS.has(key))) {
        throw new PlanReferenceError(PICKER_MESSAGE);
    }
    const scopeKind = scope.kind;
    if (scopeKind !== 'personal' && scopeKind !== 'group' && scopeKind !== 'public') {
        throw new PlanReferenceError(KIND_MESSAGE);
    }
    let scopeId: string | null;
    if (scope.id === undefined || scope.id === null
        || (typeof scope.id === 'string' && !stripEnds(scope.id, IDENTIFIER_SPACE))) {
        if (scopeKind !== 'personal') {
            throw new PlanReferenceError(PICKER_MESSAGE);
        }
        scopeId = null;
    } else {
        scopeId = identifier(scope.id);
    }
    const reference: PlanReference = {
        kind,
        id: identifier(value.id),
        scope: { kind: scopeKind, id: scopeId },
    };
    const label = sanitizeReferenceLabel(value.label);
    if (label) {
        reference.label = label;
    }
    return reference;
}

/** The dedupe identity of a canonical reference. Never the label. */
function referenceIdentity(reference: PlanReference): string {
    return JSON.stringify([reference.kind, reference.id, reference.scope.kind, reference.scope.id ?? '']);
}

function compareReferences(left: PlanReference, right: PlanReference): number {
    return compareCodePoints(left.kind, right.kind)
        || compareCodePoints(left.scope.kind, right.scope.kind)
        || compareCodePoints(left.scope.id ?? '', right.scope.id ?? '')
        || compareCodePoints(left.id, right.id);
}

/**
 * Canonical references for a request: shape-checked, deduplicated and ordered.
 *
 * Duplicates keep the first label sent. The order is by kind, workspace and identity in code point
 * order, so the same selection always has the same form. Nothing, null and an empty list are all
 * no references.
 */
export function canonicalPlanReferences(value: unknown, limit = REQUEST_REFERENCE_LIMIT): PlanReference[] {
    if (value === undefined || value === null) {
        return [];
    }
    if (!Array.isArray(value)) {
        throw new PlanReferenceError(PICKER_MESSAGE);
    }
    if (value.length > REQUEST_REFERENCE_RAW_LIMIT) {
        throw new PlanReferenceError(`Attach at most ${limit} documents or tags.`, 'reference_limit');
    }
    const unique = new Map<string, PlanReference>();
    for (const item of value) {
        const reference = canonicalPlanReference(item);
        const identity = referenceIdentity(reference);
        if (!unique.has(identity)) {
            unique.set(identity, reference);
        }
    }
    if (unique.size > limit) {
        throw new PlanReferenceError(`Attach at most ${limit} documents or tags.`, 'reference_limit');
    }
    return Array.from(unique.values()).sort(compareReferences);
}

/**
 * Every chip in a draft, as the request would send it.
 *
 * Nothing is dropped here. A chip the plan editor cannot use, such as a whole workspace, is
 * refused with a message when the request is checked, rather than silently left out.
 */
export function planDraftReferences(draft: { contextItems: readonly ContextItem[] }): PlanReferenceInput[] {
    return draft.contextItems.map((item) => ({
        kind: item.kind,
        id: item.id,
        label: item.label,
        scope: { kind: item.scope.kind, id: item.scope.id, name: item.scope.name },
    }));
}

/** The chips a stored user turn shows. Stored data is read defensively and shown as text. */
export function storedTurnReferences(value: unknown): PlanReferenceChip[] {
    if (!Array.isArray(value)) {
        return [];
    }
    const chips: PlanReferenceChip[] = [];
    value.slice(0, REQUEST_REFERENCE_LIMIT).forEach((entry: unknown, index) => {
        const kind = isRecord(entry) ? entry.kind : null;
        if (!isRecord(entry) || (kind !== 'document' && kind !== 'tag')) {
            return;
        }
        const id = typeof entry.id === 'string' ? entry.id : '';
        chips.push({
            key: `${index}:${kind}:${id}`,
            kind,
            label: sanitizeReferenceLabel(entry.label) || (kind === 'tag' ? 'Selected tag' : 'Selected document'),
        });
    });
    return chips;
}

function joinList(items: readonly string[]): string {
    return items.length > 1 ? `${items.slice(0, -1).join(', ')} and ${items[items.length - 1]}` : items.join('');
}

function noticeLabels(value: unknown): string[] {
    return Array.isArray(value)
        ? value.slice(0, REQUEST_REFERENCE_LIMIT).map((item) => sanitizeReferenceLabel(item)).filter(Boolean)
        : [];
}

/**
 * What a planner turn says when its revision first limited what the plan searches.
 *
 * Picked documents replace the plan's default search and picked tags filter it, so a plan that
 * searched everything the user can read now searches only these. The reader should know.
 */
export function scopeNoticeText(value: unknown): string | null {
    if (!isRecord(value) || value.kind !== 'search_limited') {
        return null;
    }
    const documents = noticeLabels(value.documents);
    const tags = noticeLabels(value.tags);
    if (!documents.length && !tags.length) {
        return null;
    }
    const more = typeof value.more === 'number' && Number.isInteger(value.more)
        && value.more > 0 && value.more <= 1000 ? value.more : 0;
    const items = [...documents, ...tags.map((tag) => `tag ${tag}`), ...(more ? [`${more} more`] : [])];
    return `Searches in this plan now look only at what you attached: ${joinList(items)}.`;
}

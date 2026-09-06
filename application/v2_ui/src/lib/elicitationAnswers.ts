// elicitationAnswers.ts

import {
    buildComposerDraftSubmission,
    composerDraftHasPendingUploads,
    composerDraftReferences,
    composerReferenceKey,
    createComposerDraft,
    type ComposerDraft,
    type ComposerReference,
} from './composerDraft';
import type {
    Elicitation,
    ElicitationContext,
    ElicitationFieldSchema,
    ElicitationResponse,
} from './orchestration';
import type { PromptResolutionContext } from './promptVariables';

export type ElicitationFieldKind =
    | 'files'
    | 'radio'
    | 'checkboxes'
    | 'boolean'
    | 'number'
    | 'arrayText'
    | 'text';

export interface ElicitationDraft {
    elicitationId: string;
    revision: number;
    values: Record<string, unknown>;
    editors: Record<string, ComposerDraft>;
    pageIndex: number;
    submitting: boolean;
    error: string | null;
    submissionId: string | null;
    submissionFingerprint: string | null;
}

export function elicitationFieldKind(
    elicitation: Elicitation,
    name: string,
): ElicitationFieldKind {
    const field = elicitation.requested_schema.properties[name];
    if (elicitation.ui_hints.fields?.[name]?.input === 'files'
        && (field.type === 'string' || (field.type === 'array' && field.items?.type === 'string'))) {
        return 'files';
    }
    if (Array.isArray(field.enum)) {
        return 'radio';
    }
    if (field.type === 'array') {
        return Array.isArray(field.items?.enum) ? 'checkboxes' : 'arrayText';
    }
    if (field.type === 'boolean') {
        return 'boolean';
    }
    return field.type === 'number' || field.type === 'integer' ? 'number' : 'text';
}

export function elicitationFieldLabel(name: string, field: ElicitationFieldSchema): string {
    return field.title || name.replace(/[_-]+/g, ' ').replace(/\b\w/g, (value) => value.toUpperCase());
}

export function createElicitationDraft(elicitation: Elicitation): ElicitationDraft {
    const values: Record<string, unknown> = {};
    const editors: Record<string, ComposerDraft> = {};
    for (const [name, field] of Object.entries(elicitation.requested_schema.properties)) {
        const editor = createComposerDraft();
        const kind = elicitationFieldKind(elicitation, name);
        if (field.default !== undefined && kind !== 'files') {
            if (kind === 'text' || (kind === 'arrayText' && field.items?.type === 'string')) {
                editor.text = Array.isArray(field.default)
                    ? field.default.join('\n')
                    : String(field.default);
            } else if (kind === 'number' || kind === 'arrayText') {
                values[name] = Array.isArray(field.default)
                    ? field.default.join('\n')
                    : String(field.default);
            } else {
                values[name] = field.default;
            }
        }
        editors[name] = editor;
    }
    return {
        elicitationId: elicitation.elicitation_id,
        revision: elicitation.revision ?? 0,
        values,
        editors,
        pageIndex: 0,
        submitting: false,
        error: null,
        submissionId: null,
        submissionFingerprint: null,
    };
}

export function elicitationPages(elicitation: Elicitation): string[][] {
    const properties = elicitation.requested_schema.properties;
    const seen = new Set<string>();
    const take = (names: string[]) => names.filter((name) => {
        if (!(name in properties) || seen.has(name)) {
            return false;
        }
        seen.add(name);
        return true;
    });
    const pages = (elicitation.ui_hints.pages ?? [])
        .map(take)
        .filter((page) => page.length > 0);
    const remainder = take([
        ...(elicitation.ui_hints.order ?? []),
        ...Object.keys(properties),
    ]);
    if (pages.length === 0) {
        return [remainder];
    }
    return [...pages, ...remainder.map((name) => [name])];
}

export function isFileReference(reference: ComposerReference): boolean {
    return reference.kind === 'document' || reference.kind === 'chat_attachment';
}

export function selectedFileCandidates(
    elicitation: Elicitation,
    name: string,
    value: unknown,
): ComposerReference[] {
    const selected = Array.isArray(value) ? value : value === undefined ? [] : [value];
    return (elicitation.ui_hints.fields?.[name]?.candidates ?? [])
        .filter((candidate) => isFileReference(candidate) && selected.includes(candidate.id));
}

export function elicitationFieldReferences(
    elicitation: Elicitation,
    name: string,
    draft: ElicitationDraft,
): ComposerReference[] {
    return [...new Map([
        ...selectedFileCandidates(elicitation, name, draft.values[name]),
        ...composerDraftReferences(draft.editors[name] ?? createComposerDraft()),
    ].map((reference) => [composerReferenceKey(reference), reference])).values()];
}

function primitiveValue(value: unknown): value is string | number | boolean {
    return typeof value === 'string' || typeof value === 'boolean'
        || (typeof value === 'number' && Number.isFinite(value));
}

function parseScalar(value: unknown, type: string): string | number | boolean | undefined {
    if (type === 'string') {
        return typeof value === 'string' && value.trim() ? value.trim() : undefined;
    }
    if (type === 'boolean') {
        if (typeof value === 'boolean') {
            return value;
        }
        return value === 'true' ? true : value === 'false' ? false : undefined;
    }
    if ((typeof value !== 'string' && typeof value !== 'number')
        || (typeof value === 'string' && !value.trim())) {
        return undefined;
    }
    const number = Number(value);
    return Number.isFinite(number) && (type !== 'integer' || Number.isInteger(number))
        ? number
        : undefined;
}

export interface BuiltElicitationAnswer {
    response: ElicitationResponse;
    context: ElicitationContext;
    errors: Record<string, string>;
    pendingUploads: boolean;
}

export function buildElicitationAnswer(
    elicitation: Elicitation,
    draft: ElicitationDraft,
    promptContext: PromptResolutionContext,
): BuiltElicitationAnswer {
    const content: Record<string, unknown> = {};
    const context: ElicitationContext = {};
    const errors: Record<string, string> = {};
    let pendingUploads = false;

    for (const [name, field] of Object.entries(elicitation.requested_schema.properties)) {
        const kind = elicitationFieldKind(elicitation, name);
        const editor = draft.editors[name] ?? createComposerDraft();
        const references = elicitationFieldReferences(elicitation, name, draft);
        const submitted = buildComposerDraftSubmission(editor, {
            ...promptContext,
            composerText: editor.text,
            selectedDocuments: references.filter(isFileReference).map((reference) => reference.label || reference.id),
        });
        const files = references.filter(isFileReference);
        const waiting = composerDraftHasPendingUploads(editor);
        pendingUploads ||= waiting;
        if (waiting) {
            errors[name] = 'Wait for the attached files to finish processing.';
        } else if (editor.uploads.some((upload) => upload.state === 'failed')) {
            errors[name] = 'Retry or remove the failed upload before continuing.';
        }

        const extra = {
            ...(submitted.message ? { text: submitted.message } : {}),
            ...(submitted.promptInfo ? { prompt_info: submitted.promptInfo } : {}),
            ...(references.length ? { references } : {}),
        };
        if (Object.keys(extra).length) {
            context[name] = extra;
        }

        const raw = draft.values[name];
        if (kind === 'files') {
            if (field.type !== 'array' && files.length > 1) {
                errors[name] = 'Choose one file, or remove the extra file references.';
            } else if (files.length) {
                content[name] = field.type === 'array' ? files.map((file) => file.id) : files[0].id;
            }
        } else if (kind === 'text') {
            const text = submitted.message || references.map((reference) => reference.label || reference.id).join('\n');
            if (text.trim()) {
                content[name] = text.trim();
            }
        } else if (kind === 'arrayText') {
            const text = field.items?.type === 'string' ? submitted.message : String(raw ?? '');
            const lines = text.split('\n').map((line) => line.trim()).filter(Boolean);
            const values = lines.map((line) => parseScalar(line, field.items?.type ?? 'string'));
            if (values.some((value) => value === undefined)) {
                errors[name] = `Enter one ${field.items?.type ?? 'string'} value per line.`;
            } else if (values.length) {
                content[name] = values;
            } else if (field.items?.type === 'string' && references.length) {
                content[name] = references.map((reference) => reference.id);
            }
        } else if (kind === 'checkboxes') {
            if (Array.isArray(raw) && raw.length) {
                const allowed = field.items?.enum ?? [];
                if (raw.some((value) => !primitiveValue(value) || !allowed.includes(value))) {
                    errors[name] = 'Choose from the offered options.';
                } else {
                    content[name] = [...new Set(raw)];
                }
            }
        } else if (kind === 'radio') {
            if (raw !== undefined && raw !== null) {
                if (!primitiveValue(raw) || !field.enum?.includes(raw)) {
                    errors[name] = 'Choose one of the offered options.';
                } else {
                    content[name] = raw;
                }
            }
        } else if (raw !== undefined && raw !== '') {
            const value = parseScalar(raw, field.type);
            if (value === undefined) {
                errors[name] = `Enter a valid ${field.type}.`;
            } else {
                content[name] = value;
            }
        }

        if (elicitation.requested_schema.required.includes(name) && !(name in content) && !errors[name]) {
            errors[name] = kind === 'files' ? 'Choose, reference, or upload a file.' : 'An answer is required.';
        }
    }
    return { response: { action: 'accept', content }, context, errors, pendingUploads };
}

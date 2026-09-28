// composerDraft.ts

import {
    addContextItem,
    documentContextItem,
    scopeContextItem,
    tagContextItem,
    type ContextItem,
    type ContextScopeRef,
} from './chatContext';
import { reconcileContextItems } from './chatContextTokens';
import { insertPromptText } from './promptSlash';
import {
    attachedPromptContent,
    buildOutgoingMessage,
    buildPromptInfo,
    type AttachedPrompt,
} from './promptRequest';
import {
    applyPromptVariables,
    describeUnfilledVariables,
    parsePromptVariables,
    resolvePromptVariableValues,
    type PromptResolutionContext,
    type PromptVariable,
} from './promptVariables';
import type { ChatUploadTarget } from './endpoints';
import {
    imageReferenceKey,
    isHeifFileName,
    isReferenceImageFileName,
    normalizeImageReferences,
    type ImageReferenceRequest,
} from './imageReferences';
import type { Json, PromptOption } from './types';
import type { PromptAiValue } from './usePromptVariableValues';

export interface ComposerReference {
    kind: 'document' | 'tag' | 'scope' | 'chat_attachment';
    id: string;
    label?: string;
    scope: {
        kind: 'personal' | 'group' | 'public' | 'chat';
        id: string | null;
        name?: string;
    };
}

export interface ComposerUpload {
    id: string;
    fileName: string;
    state: 'uploading' | 'processing' | 'ready' | 'failed';
    reference?: ComposerReference;
    fileMessageId?: string;
    error?: string;
    progress?: number;
    conversationId?: string;
    groupUploadTargets?: ChatUploadTarget[];
    groupUploadTargetId?: string;
    uploadScopeGroupIds?: string[];
    interrupted?: 'uploading' | 'processing';
}

export interface ComposerDraft {
    text: string;
    contextItems: ContextItem[];
    attachedPrompt: AttachedPrompt | null;
    promptValues: Record<string, string>;
    promptAiValues?: Record<string, PromptAiValue>;
    promptInstance?: number;
    uploads: ComposerUpload[];
    imageReferences?: ImageReferenceRequest[];
}

export function createComposerDraft(): ComposerDraft {
    return { text: '', contextItems: [], attachedPrompt: null, promptValues: {}, uploads: [], imageReferences: [] };
}

export function attachPromptToDraft(
    draft: ComposerDraft,
    prompt: PromptOption,
    range?: { start: number; end: number },
): ComposerDraft {
    const content = String(prompt.content ?? '');
    if (!content) {
        return draft;
    }
    const text = range ? insertPromptText(draft.text, range.start, range.end, '').text : draft.text;
    return {
        ...draft,
        text,
        contextItems: reconcileContextItems(text, draft.contextItems),
        attachedPrompt: {
            id: String(prompt.id ?? ''),
            name: String(prompt.name ?? 'Prompt'),
            scopeType: prompt.scope_type ? String(prompt.scope_type) : undefined,
            scopeName: prompt.scope_name ? String(prompt.scope_name) : undefined,
            originalContent: content,
            editedContent: null,
        },
        promptValues: {},
        promptAiValues: {},
        promptInstance: (draft.promptInstance ?? 0) + 1,
    };
}

export function composerDraftHasPendingUploads(draft: ComposerDraft): boolean {
    return draft.uploads.some((upload) =>
        upload.state === 'uploading' || upload.state === 'processing',
    );
}

export function interruptComposerDraftUploads(
    draft: ComposerDraft,
    ownedUploadIds: ReadonlySet<string>,
): ComposerDraft {
    let changed = false;
    const uploads = draft.uploads.map((upload): ComposerUpload => {
        if (!ownedUploadIds.has(upload.id)
            || (upload.state !== 'uploading' && upload.state !== 'processing')) {
            return upload;
        }
        changed = true;
        return {
            ...upload,
            state: 'failed',
            interrupted: upload.state,
            error: upload.state === 'processing' && upload.reference
                ? 'File processing continues. Return to this answer to resume its status check, or remove the file.'
                : 'The transfer was interrupted. Use Retry to choose the file again, or remove it. An uploaded copy may already be in the conversation.',
        };
    });
    return changed ? { ...draft, uploads } : draft;
}

/** Normal chat requests can carry workspace documents, never chat-message ids as documents. */
export function composerDraftContextItems(draft: ComposerDraft): ContextItem[] {
    return draft.uploads.reduce((items, upload) => {
        const reference = upload.reference;
        if (upload.state !== 'ready' || reference?.kind !== 'document'
            || (reference.scope.kind !== 'personal' && reference.scope.kind !== 'group')) {
            return items;
        }
        return addContextItem(items, documentContextItem(
            { id: reference.id, file_name: upload.fileName, title: reference.label },
            { ...reference.scope, kind: reference.scope.kind, name: reference.scope.name ?? 'Workspace' },
            items,
        ));
    }, draft.contextItems);
}

/** Ground variable filling in actual workspace references, not chat-message ids or labels. */
export function composerDraftKnowledgeContext(
    draft: ComposerDraft,
    references: readonly ComposerReference[] = [],
): ContextItem[] {
    return references.reduce((items, reference) => {
        if (reference.kind === 'chat_attachment' || reference.scope.kind === 'chat'
            || (reference.kind !== 'scope' && !reference.id)
            || (reference.scope.kind !== 'personal' && !reference.scope.id)) {
            return items;
        }
        const scope: ContextScopeRef = {
            ...reference.scope,
            kind: reference.scope.kind,
            name: reference.scope.name ?? (reference.scope.kind === 'personal' ? 'My workspace' : 'Workspace'),
        };
        const item = reference.kind === 'document'
            ? documentContextItem({ id: reference.id, title: reference.label }, scope, items)
            : reference.kind === 'tag'
                ? tagContextItem(reference.id, scope, items)
                : scopeContextItem(scope, items);
        return addContextItem(items, item);
    }, composerDraftContextItems(draft));
}

export function composerReferenceKey(reference: ComposerReference): string {
    if (reference.kind === 'document') {
        return `document:${reference.id}`;
    }
    const id = reference.kind === 'tag' ? reference.id.toLowerCase() : reference.id;
    return `${reference.kind}:${reference.scope.kind}:${reference.scope.id ?? ''}:${id}`;
}

export function composerDraftReferences(draft: ComposerDraft): ComposerReference[] {
    const references: ComposerReference[] = draft.contextItems.map((item) => ({
        kind: item.kind,
        id: item.id || (item.kind === 'scope' && item.scope.kind === 'personal' ? 'personal' : ''),
        label: item.label,
        scope: { ...item.scope },
    }));
    for (const upload of draft.uploads) {
        if (upload.state === 'ready' && upload.reference) {
            references.push(upload.reference);
        }
    }
    const seen = new Set<string>();
    return references.filter((reference) => {
        if (!reference.id || (reference.scope.kind !== 'personal' && !reference.scope.id)) {
            return false;
        }
        const key = composerReferenceKey(reference);
        if (seen.has(key)) {
            return false;
        }
        seen.add(key);
        return true;
    }).map((reference) => ({ ...reference, scope: { ...reference.scope } }));
}

function documentReferenceFromScope(
    documentId: string,
    scope: ComposerReference['scope'],
): ImageReferenceRequest | null {
    if (scope.kind === 'personal') {
        return { type: 'document', document_id: documentId, scope: 'personal', scope_id: null };
    }
    if ((scope.kind === 'group' || scope.kind === 'public') && scope.id) {
        return { type: 'document', document_id: documentId, scope: scope.kind, scope_id: scope.id };
    }
    return null;
}

function uploadImageReference(upload: ComposerUpload): ImageReferenceRequest | null {
    if (upload.state !== 'ready' || !isReferenceImageFileName(upload.fileName) || isHeifFileName(upload.fileName)) {
        return null;
    }
    if (upload.fileMessageId) {
        return { type: 'message', message_id: upload.fileMessageId };
    }
    if (upload.reference?.kind === 'chat_attachment') {
        return { type: 'message', message_id: upload.reference.id };
    }
    if (upload.reference?.kind === 'document') {
        return documentReferenceFromScope(upload.reference.id, upload.reference.scope);
    }
    return null;
}

function contextImageReference(item: ContextItem): ImageReferenceRequest | null {
    if (item.kind !== 'document') {
        return null;
    }
    const fileName = item.meta?.fileName || item.label;
    if (!isReferenceImageFileName(fileName) || isHeifFileName(fileName)) {
        return null;
    }
    return documentReferenceFromScope(item.id, item.scope);
}

export function composerDraftImageReferences(
    draft: ComposerDraft,
    limit: number,
): ImageReferenceRequest[] {
    const candidates = [
        ...draft.uploads.map(uploadImageReference),
        ...draft.contextItems.map(contextImageReference),
        ...(draft.imageReferences ?? []),
    ].filter((reference): reference is ImageReferenceRequest => reference !== null);
    return normalizeImageReferences(candidates, limit);
}

export function addComposerDraftImageReference(
    draft: ComposerDraft,
    reference: ImageReferenceRequest,
    limit: number,
): ComposerDraft {
    const current = normalizeImageReferences(draft.imageReferences ?? [], limit);
    const next = normalizeImageReferences([...current, reference], limit);
    if (next.length === current.length
        && next.every((item, index) => imageReferenceKey(item) === imageReferenceKey(current[index]))) {
        return draft;
    }
    return { ...draft, imageReferences: next };
}

export function composerDraftHasContent(draft: ComposerDraft): boolean {
    return Boolean(
        draft.text.trim()
        || (draft.attachedPrompt && attachedPromptContent(draft.attachedPrompt).trim())
        || composerDraftReferences(draft).length,
    );
}

export function composerDraftPromptValues(
    draft: ComposerDraft,
    context: PromptResolutionContext,
): Record<string, string> {
    const content = draft.attachedPrompt ? attachedPromptContent(draft.attachedPrompt) : '';
    return resolvePromptVariableValues(parsePromptVariables(content), draft.promptValues, {
        ...context,
        composerText: draft.text,
    });
}

export function composerDraftUnfilledVariables(
    draft: ComposerDraft,
    context: PromptResolutionContext,
): PromptVariable[] {
    const content = draft.attachedPrompt ? attachedPromptContent(draft.attachedPrompt) : '';
    return describeUnfilledVariables(parsePromptVariables(content), composerDraftPromptValues(draft, context));
}

/** AI-derived values and built-ins are snapshots, not reusable personal preferences. */
export function composerDraftUserPromptValues(draft: ComposerDraft): Record<string, string> {
    const content = draft.attachedPrompt ? attachedPromptContent(draft.attachedPrompt) : '';
    return Object.fromEntries(parsePromptVariables(content)
        .filter((variable) => !variable.builtIn
            && !Object.prototype.hasOwnProperty.call(draft.promptAiValues ?? {}, variable.key)
            && Object.prototype.hasOwnProperty.call(draft.promptValues, variable.key))
        .map((variable) => [variable.key, draft.promptValues[variable.key]]));
}

export function buildComposerDraftSubmission(
    draft: ComposerDraft,
    context: PromptResolutionContext,
): { message: string; promptInfo: Json | null; references: ComposerReference[] } {
    const references = composerDraftReferences(draft);
    const typed = draft.text.trim();
    const attached = draft.attachedPrompt;
    if (!attached) {
        return { message: typed, promptInfo: null, references };
    }

    const content = attachedPromptContent(attached);
    const values = composerDraftPromptValues(draft, context);
    const promptText = applyPromptVariables(content, values);
    const outgoing = buildOutgoingMessage(content, promptText, typed);
    return {
        message: outgoing.message,
        promptInfo: buildPromptInfo({
            attached,
            promptText,
            userText: outgoing.userText,
            composerText: typed,
            values,
        }),
        references,
    };
}

// composerDraft.ts

import { addContextItem, documentContextItem, type ContextItem } from './chatContext';
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
    parsePromptVariables,
    resolveBuiltInPromptVariables,
    type PromptResolutionContext,
} from './promptVariables';
import type { ChatUploadTarget } from './endpoints';
import type { Json, PromptOption } from './types';

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
    uploads: ComposerUpload[];
}

export function createComposerDraft(): ComposerDraft {
    return { text: '', contextItems: [], attachedPrompt: null, promptValues: {}, uploads: [] };
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
        promptValues: draft.attachedPrompt?.id === String(prompt.id ?? '') ? draft.promptValues : {},
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

export function composerDraftHasContent(draft: ComposerDraft): boolean {
    return Boolean(
        draft.text.trim()
        || (draft.attachedPrompt && attachedPromptContent(draft.attachedPrompt).trim())
        || composerDraftReferences(draft).length,
    );
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
    // Only this prompt's user variables are supplied values. Built-ins always resolve now,
    // and {{composer}} always belongs to this editor, never another draft on the page.
    const values = Object.fromEntries(
        parsePromptVariables(content)
            .filter((variable) => !variable.builtIn && variable.key in draft.promptValues)
            .map((variable) => [variable.key, draft.promptValues[variable.key]]),
    );
    const promptText = applyPromptVariables(content, {
        ...values,
        ...resolveBuiltInPromptVariables({
            ...context,
            composerText: draft.text,
        }),
    });
    const outgoing = buildOutgoingMessage(content, promptText, typed);
    return {
        message: outgoing.message,
        promptInfo: buildPromptInfo({
            attached,
            promptText,
            userText: outgoing.userText,
            values,
        }),
        references,
    };
}

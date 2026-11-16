// documentSourceSelection.ts
import { scopeContextItem, tagContextItem, documentContextItem, type ContextItem, type ContextScopeRef } from './chatContext';
import { conversationDocumentName, conversationDocuments } from './conversationDocuments';
import type { ChatMessage, ConversationMetadata, UsedDocument } from './types';

export const DOCUMENT_DETAILS_UNAVAILABLE = 'Document details unavailable';

export type DocumentSourceScope = { kind: 'personal' } | { kind: 'group' | 'public'; id: string };
export type DocumentSource =
    | { kind: 'workspace'; scope: DocumentSourceScope }
    | { kind: 'document'; id: string; scope: DocumentSourceScope }
    | { kind: 'tag'; tag: string; scope: DocumentSourceScope };
export interface DocumentSourceSelection {
    version: 1;
    mode: 'all' | 'selected';
    sources: DocumentSource[];
}

export function isDocumentSourceSelection(value: unknown): value is DocumentSourceSelection {
    if (!value || typeof value !== 'object') return false;
    const selection = value as Record<string, unknown>;
    return selection.version === 1 && (selection.mode === 'all' || selection.mode === 'selected')
        && Array.isArray(selection.sources) && selection.sources.every((value: unknown) => {
            if (!value || typeof value !== 'object') return false;
            const source = value as Record<string, unknown>;
            if (!source.scope || typeof source.scope !== 'object') return false;
            const scope = source.scope as Record<string, unknown>;
            return (scope.kind === 'personal' || ((scope.kind === 'group' || scope.kind === 'public') && typeof scope.id === 'string'))
                && (source.kind === 'workspace' || (source.kind === 'document' && typeof source.id === 'string')
                    || (source.kind === 'tag' && typeof source.tag === 'string'));
        });
}

export function documentSourceSelection(searchAll: boolean, items: readonly ContextItem[]): DocumentSourceSelection | undefined {
    if (searchAll) return { version: 1, mode: 'all', sources: [] };
    if (!items.length) return undefined;
    return {
        version: 1, mode: 'selected',
        sources: items.map((item): DocumentSource => {
            const scope: DocumentSourceScope = item.scope.kind === 'personal'
                ? { kind: 'personal' } : { kind: item.scope.kind, id: item.scope.id ?? '' };
            if (item.kind === 'scope') return { kind: 'workspace', scope };
            if (item.kind === 'tag') return { kind: 'tag', tag: item.id, scope };
            return { kind: 'document', id: item.id, scope };
        }),
    };
}

export function restoreDocumentSources(
    selection: DocumentSourceSelection,
    workspaces: readonly { kind: string; id: string | null; name: string }[],
    documents: readonly UsedDocument[] = [],
): ContextItem[] {
    return selection.sources.map((source) => {
        const found = workspaces.find((item) => item.kind === source.scope.kind
            && item.id === ('id' in source.scope ? source.scope.id : null));
        const scope: ContextScopeRef = {
            kind: source.scope.kind, id: 'id' in source.scope ? source.scope.id : null,
            name: found?.name ?? (source.scope.kind === 'personal' ? 'My workspace' : source.scope.id),
        };
        if (source.kind === 'workspace') return scopeContextItem(scope);
        if (source.kind === 'tag') return tagContextItem(source.tag, scope);
        const document = documents.find((item) => item.document_id === source.id
            && (!item.scope?.type || (item.scope.type === source.scope.kind
                && (source.scope.kind === 'personal' || item.scope.id === source.scope.id))));
        const name = conversationDocumentName(document ?? { document_id: source.id });
        const filename = name.title !== 'Untitled document'
            && typeof document?.file_name === 'string' && document.file_name.trim() !== source.id
            ? document.file_name.trim() : undefined;
        return documentContextItem({
            id: source.id,
            title: name.title === 'Untitled document' ? DOCUMENT_DETAILS_UNAVAILABLE : name.title,
            file_name: filename,
        }, scope);
    });
}

export function conversationSourceDocuments(
    conversationId: string | null,
    messages: readonly ChatMessage[],
    metadata: ConversationMetadata | null,
): UsedDocument[] {
    if (!conversationId) return [];
    const uploads: UsedDocument[] = [];
    for (const message of messages) {
        if (message.conversation_id !== conversationId || typeof message.workspace_document_id !== 'string'
            || typeof message.filename !== 'string') continue;
        const value = message.metadata?.workspace_attachment;
        const attachment = value && typeof value === 'object' && !Array.isArray(value) ? value : null;
        const kind = attachment && 'scope' in attachment ? attachment.scope : undefined;
        const scopeId = attachment && 'group_id' in attachment ? attachment.group_id
            : attachment && 'scope_id' in attachment ? attachment.scope_id : undefined;
        uploads.push({
            document_id: message.workspace_document_id, file_name: message.filename,
            scope: typeof kind === 'string' ? {
                type: kind, id: typeof scopeId === 'string' ? scopeId : undefined,
            } : undefined,
        });
    }
    return conversationDocuments({
        conversation_id: conversationId, title: '',
        used_documents: metadata?.conversation_id === conversationId ? conversationDocuments(metadata) : [],
        linked_workspace_documents: uploads,
    });
}

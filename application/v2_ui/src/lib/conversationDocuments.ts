// conversationDocuments.ts

import type { ConversationMetadata, UsedDocument, WorkspaceRef } from './types';

function displayText(value: unknown, documentId = ''): string {
    if (typeof value !== 'string') return '';
    const text = value.trim();
    return text === documentId || ['unknown document', 'unknown', 'untitled document'].includes(text.toLowerCase())
        ? '' : text;
}

/** Preserve the used-document set while filling gaps from other records of the same document. */
export function conversationDocuments(metadata: ConversationMetadata | null): UsedDocument[] {
    const merged = new Map<string, UsedDocument>();
    for (const list of [
        metadata?.used_documents, metadata?.legacy_used_documents, metadata?.linked_workspace_documents,
    ]) {
        for (const document of list ?? []) {
            const id = String(document?.document_id ?? '').trim();
            if (!id) continue;
            const previous = merged.get(id);
            if (!previous) {
                merged.set(id, { ...document });
                continue;
            }
            const combined = { ...previous };
            for (const field of ['title', 'file_name', 'file_type'] as const) {
                if (!displayText(previous[field], id) && displayText(document[field], id)) {
                    combined[field] = document[field];
                }
            }
            if (!previous.scope?.type) {
                combined.scope = document.scope;
            } else if (previous.scope.type === document.scope?.type && previous.scope.id === document.scope.id) {
                combined.scope = { ...document.scope, ...previous.scope };
                if (!displayText(previous.scope.name, previous.scope.id)) {
                    combined.scope.name = document.scope.name;
                }
            }
            merged.set(id, combined);
        }
    }
    return [...merged.values()];
}

export function conversationDocumentName(document: UsedDocument): { title: string; filename: string } {
    const filename = displayText(document.file_name, document.document_id);
    const title = displayText(document.title, document.document_id) || filename || 'Untitled document';
    return { title, filename: filename === title ? '' : filename };
}

export function conversationDocumentSource(
    document: UsedDocument,
    groups: readonly WorkspaceRef[],
    publicWorkspaces: readonly WorkspaceRef[],
): string {
    const scope = document.scope;
    if (scope?.type === 'personal') return 'Personal workspace';
    if (scope?.type !== 'group' && scope?.type !== 'public') return '';
    const catalog = scope.type === 'group' ? groups : publicWorkspaces;
    const name = displayText(scope.name, scope.id)
        || displayText(catalog.find((workspace) => workspace.id === scope.id)?.name, scope.id);
    return name || (scope.type === 'group' ? 'Group workspace' : 'Public workspace');
}

// publicChatScope.ts

export type PublicWorkspaceSelection = 'all' | 'visible';

export function readPublicWorkspaceSelection(value: unknown): PublicWorkspaceSelection | null {
    return value === 'all' || value === 'visible' ? value : null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
    return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function record(value: unknown): Record<string, unknown> {
    return isRecord(value) ? value : {};
}

export function publicChatScopeFromMessages(
    messages: readonly { role?: string; metadata?: unknown }[],
): PublicWorkspaceSelection | null {
    const latest = [...messages].reverse().find((message) => message.role === 'user');
    const metadata = record(latest?.metadata);
    return readPublicWorkspaceSelection(
        record(metadata.workspace_search).public_workspace_selection
        ?? metadata.public_workspace_selection,
    );
}

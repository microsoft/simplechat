// publicWorkspaceNavigation.ts
//
// Path, blurb and status helpers for the read-only public workspace surface. Public
// workspaces reuse the same section registry as groups, so the section ids come from
// GROUP_WORKSPACE_SECTION_IDS; only the wording differs.

import {
    GROUP_WORKSPACE_SECTION_IDS, requireWorkspaceId, workspaceBasePath,
    type GroupWorkspaceSectionId, type PublicWorkspaceContext,
} from './workspaceContext';

export const PUBLIC_SECTION_BLURBS: Record<GroupWorkspaceSectionId, string> = {
    documents: 'Published files anyone here can search and use in chat.',
    tags: 'The shared labels that keep this workspace\'s documents organized.',
    sync: 'Bring approved files into this workspace from other systems.',
    prompts: 'Reusable wording published for everyone here.',
    agents: 'Assistants configured with this workspace\'s knowledge, models and tools.',
    actions: 'Tools for this workspace\'s agents, including calls to another agent.',
    workflows: 'Repeatable tasks using this workspace\'s agents and documents.',
    identities: 'Saved sign-ins for this workspace\'s file sources and actions.',
    endpoints: 'Model connections available to this workspace\'s agents and workflows.',
};

export function classicPublicSectionLabel(section: string, label: string): string {
    if (section === 'tags') return 'Documents, then Manage Tags';
    if (section === 'sync') return 'Sync';
    return label;
}

export function isPublicWorkspaceSection(value: string | undefined): value is GroupWorkspaceSectionId {
    return GROUP_WORKSPACE_SECTION_IDS.some((id) => id === value);
}

export function publicWorkspacePath(workspaceId: string, section?: string): string {
    const base = workspaceBasePath({ kind: 'public', id: workspaceId });
    return isPublicWorkspaceSection(section) ? `${base}/${section}` : base;
}

export function publicWorkspaceDocumentPath(workspaceId: string, documentId: string): string {
    const params = new URLSearchParams({ document_id: requireWorkspaceId(documentId) });
    return `${publicWorkspacePath(workspaceId, 'documents')}?${params}`;
}

export function readPublicDocumentTarget(search: string): { id: string | null; error: string | null } {
    const params = new URLSearchParams(search);
    const values = params.getAll('document_id');
    if (!values.length) return { id: null, error: null };
    if (params.has('public_workspace_id') || params.has('workspace_id')
        || params.has('group_id') || params.has('group_ids')) {
        return { id: null, error: 'This document link contains conflicting workspace arguments. Use the public workspace named in its path.' };
    }
    if (values.length !== 1) return { id: null, error: 'This document link has more than one target. Open a link to one document.' };
    try {
        return { id: requireWorkspaceId(values[0]), error: null };
    } catch {
        return { id: null, error: 'This document link has an invalid target. Open a valid document link or return to the list.' };
    }
}

export const PUBLIC_STATUS_LABELS: Record<PublicWorkspaceContext['status'], string> = {
    active: 'Active',
    locked: 'Locked - read only',
    upload_disabled: 'Uploads disabled',
    inactive: 'Inactive',
    unknown: 'Status unavailable',
};

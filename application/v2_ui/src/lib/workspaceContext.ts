// workspaceContext.ts

import { api } from './apiClient';
import { isRecord } from './workspaceAuthoring';
import type { WorkspaceAvailability, WorkspaceSectionAvailability } from './types';

export type WorkspaceRef =
    | { kind: 'personal'; id: string }
    | { kind: 'group'; id: string }
    | { kind: 'public'; id: string };

export const GROUP_WORKSPACE_SECTION_IDS = [
    'documents', 'tags', 'sync', 'prompts', 'agents', 'actions',
    'workflows', 'identities', 'endpoints',
] as const;

export type GroupWorkspaceSectionId = typeof GROUP_WORKSPACE_SECTION_IDS[number];
export type GroupWorkspaceRole = 'Owner' | 'Admin' | 'DocumentManager' | 'User';
export type GroupWorkspaceStatus = 'active' | 'locked' | 'upload_disabled' | 'inactive' | 'unknown';

export interface WorkspaceSectionAccess extends WorkspaceSectionAvailability {
    can_manage: boolean;
}

export interface GroupWorkspaceContext extends WorkspaceAvailability {
    schema_version: 1;
    enabled: true;
    viewer_id: string;
    scope: Extract<WorkspaceRef, { kind: 'group' }>;
    workspace: {
        name: string;
        description: string;
        owner: { display_name: string; email: string };
        hero_color: string;
        logo_url: string | null;
    };
    role: GroupWorkspaceRole;
    status: GroupWorkspaceStatus;
    can_manage_workspace: boolean;
    sections: Record<GroupWorkspaceSectionId, WorkspaceSectionAccess>;
    /** The already-shipped Call agent surface has its own eligibility, independent of the personal kernel. */
    native_delegation?: WorkspaceSectionAccess;
    document_permissions: {
        can_view: boolean;
        can_chat: boolean;
        can_upload: boolean;
        can_edit: boolean;
        can_delete: boolean;
        can_download: boolean;
    };
    document_queries: {
        sort_fields: string[];
        facets: boolean;
        places: boolean;
    };
    document_management?: {
        schema_version: number;
        operations: string[];
    };
    document_collaboration?: {
        schema_version: number;
        operations: string[];
    };
    /**
     * The group prompt management hint (M3). Present as `{schema_version: 1, operations: [...]}`
     * when the viewer may create, edit or delete group prompts, computed from role and status
     * exactly like document_management. Absence means "read-only", never an empty grant.
     */
    prompt_management?: {
        schema_version: number;
        operations: string[];
    };
    /**
     * The group action management hint (M4). Present as `{schema_version: 1, operations: [...]}`
     * when the viewer may create, edit, delete or test group actions, computed from role and
     * status exactly like prompt_management. Absence means "read-only", never an empty grant.
     */
    action_management?: {
        schema_version: number;
        operations: string[];
    };
}

/**
 * The public workspace context. Mirrors the group context field-for-field. In M3B it advertises
 * document_management when the viewer may manage documents; in M3C it also advertises
 * document_collaboration for the generated-artifact (publication) review surface. native_delegation
 * and cross-workspace sharing stay absent (public workspaces have no delegation or share surface):
 * absence means "not available", never "empty set".
 */
export interface PublicWorkspaceContext extends WorkspaceAvailability {
    schema_version: 1;
    enabled: true;
    viewer_id: string;
    scope: Extract<WorkspaceRef, { kind: 'public' }>;
    workspace: {
        name: string;
        description: string;
        owner: { display_name: string; email: string };
        hero_color: string;
        logo_url: string | null;
    };
    role: GroupWorkspaceRole;
    status: GroupWorkspaceStatus;
    can_manage_workspace: boolean;
    sections: Record<GroupWorkspaceSectionId, WorkspaceSectionAccess>;
    document_permissions: {
        can_view: boolean;
        can_chat: boolean;
        can_upload: boolean;
        can_edit: boolean;
        can_delete: boolean;
        can_download: boolean;
    };
    document_queries: {
        sort_fields: string[];
        facets: boolean;
        places: boolean;
    };
    document_management?: {
        schema_version: number;
        operations: string[];
    };
    document_collaboration?: {
        schema_version: number;
        operations: string[];
    };
}

export function requireWorkspaceId(id: string): string {
    if (typeof id !== 'string' || !id || id === '.' || id === '..'
        || id !== id.trim() || /[/\\?#\u0000-\u001f\u007f]/.test(id)) {
        throw new Error('Invalid workspace identifier.');
    }
    return id;
}

export function workspaceScopeKey(viewerId: string, scope: WorkspaceRef): string {
    return JSON.stringify([requireWorkspaceId(viewerId), scope.kind, requireWorkspaceId(scope.id)]);
}

function encodeWorkspaceId(id: string): string {
    // Match the server's urllib.parse.quote(..., safe='') for local resource URLs.
    return encodeURIComponent(id).replace(/[!'()*]/g, (character) =>
        `%${character.charCodeAt(0).toString(16).toUpperCase()}`);
}

export function workspaceBasePath(scope: WorkspaceRef): string {
    const id = encodeWorkspaceId(requireWorkspaceId(scope.id));
    if (scope.kind === 'personal') return '/workspace';
    return `/${scope.kind === 'group' ? 'groups' : 'public'}/${id}`;
}

function isSectionAccess(value: unknown): value is WorkspaceSectionAccess {
    return isRecord(value)
        && typeof value.enabled === 'boolean'
        && typeof value.can_manage === 'boolean'
        && typeof value.group === 'string'
        && ['knowledge', 'automation', 'connections'].includes(value.group)
        && (!value.can_manage || value.enabled)
        && (value.enabled ? value.reason === null : typeof value.reason === 'string' && Boolean(value.reason.trim()));
}

function matchesWorkspaceContextShape(
    value: unknown,
    viewerId: string,
    id: string,
    kind: 'group' | 'public',
    logoPrefix: string,
): boolean {
    if (!isRecord(value) || value.schema_version !== 1 || value.enabled !== true || value.viewer_id !== viewerId
        || !isRecord(value.scope) || value.scope.kind !== kind || value.scope.id !== id
        || !isRecord(value.workspace) || !isRecord(value.sections)
        || !isRecord(value.document_permissions) || !isRecord(value.document_queries)) return false;
    const { workspace, sections, document_permissions: permissions, document_queries: queries } = value;
    if (typeof workspace.name !== 'string' || typeof workspace.description !== 'string'
        || !isRecord(workspace.owner) || typeof workspace.owner.display_name !== 'string'
        || typeof workspace.owner.email !== 'string'
        || typeof workspace.hero_color !== 'string' || !/^#[0-9a-f]{6}$/i.test(workspace.hero_color)) return false;
    if (workspace.logo_url !== null && (typeof workspace.logo_url !== 'string'
        || !workspace.logo_url.startsWith(logoPrefix)
        || !/^[1-9]\d*$/.test(workspace.logo_url.slice(logoPrefix.length)))) return false;
    return typeof value.role === 'string'
        && ['Owner', 'Admin', 'DocumentManager', 'User'].includes(value.role)
        && typeof value.status === 'string'
        && ['active', 'locked', 'upload_disabled', 'inactive', 'unknown'].includes(value.status)
        && typeof value.can_manage_workspace === 'boolean'
        && GROUP_WORKSPACE_SECTION_IDS.every((sectionId) => isSectionAccess(sections[sectionId]))
        && (value.native_delegation === undefined || isSectionAccess(value.native_delegation))
        && ['can_view', 'can_chat', 'can_upload', 'can_edit', 'can_delete', 'can_download']
            .every((key) => typeof permissions[key] === 'boolean')
        && Array.isArray(queries.sort_fields)
        && queries.sort_fields.every((field) => typeof field === 'string' && field.length > 0)
        && typeof queries.facets === 'boolean' && typeof queries.places === 'boolean';
}

export function isGroupWorkspaceContext(
    value: unknown,
    viewerId: string,
    groupId: string,
): value is GroupWorkspaceContext {
    return matchesWorkspaceContextShape(value, viewerId, groupId, 'group',
        `/api/groups/${encodeWorkspaceId(groupId)}/logo?v=`);
}

/**
 * Public workspace logos are still served from the legacy underscore route
 * `/api/public_workspaces/<id>/logo`, even though the M3A document reads use the hyphenated
 * `/api/public-workspaces/<id>/documents` family. Validate the underscore prefix.
 */
export function isPublicWorkspaceContext(
    value: unknown,
    viewerId: string,
    workspaceId: string,
): value is PublicWorkspaceContext {
    return matchesWorkspaceContextShape(value, viewerId, workspaceId, 'public',
        `/api/public_workspaces/${encodeWorkspaceId(workspaceId)}/logo?v=`);
}

export async function fetchGroupWorkspaceContext(
    groupId: string,
    viewerId: string,
    signal?: AbortSignal,
): Promise<GroupWorkspaceContext> {
    const id = requireWorkspaceId(groupId);
    requireWorkspaceId(viewerId);
    const response = await api.get<unknown>(`/api/v2/workspaces/group/${encodeWorkspaceId(id)}`, signal);
    if (!isGroupWorkspaceContext(response, viewerId, id)) {
        throw new Error('The workspace returned invalid or mismatched details. Refresh and try again.');
    }
    return response;
}

export async function fetchPublicWorkspaceContext(
    workspaceId: string,
    viewerId: string,
    signal?: AbortSignal,
): Promise<PublicWorkspaceContext> {
    const id = requireWorkspaceId(workspaceId);
    requireWorkspaceId(viewerId);
    const response = await api.get<unknown>(`/api/v2/workspaces/public/${encodeWorkspaceId(id)}`, signal);
    if (!isPublicWorkspaceContext(response, viewerId, id)) {
        throw new Error('The workspace returned invalid or mismatched details. Refresh and try again.');
    }
    return response;
}

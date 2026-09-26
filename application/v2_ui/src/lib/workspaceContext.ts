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

/**
 * The group-only management sections, reported in the context's `manage` group. Kept apart
 * from GROUP_WORKSPACE_SECTION_IDS, which the public workspace context shares, so a public
 * workspace is never expected to report them. M7C adds settings, activity and statistics.
 */
export const GROUP_MANAGE_SECTION_IDS = ['members', 'settings', 'activity', 'statistics'] as const;

/**
 * The sections a public workspace reports. Deliberately its own list rather than a slice of
 * GROUP_WORKSPACE_SECTION_IDS: a public workspace never has agents, actions, workflows or
 * endpoints, so the public context and its registry leave those out entirely rather than
 * listing them as "not available yet". Keeping this apart from the group list means a change
 * to either surface's sections cannot silently move the other (M9A R5).
 */
export const PUBLIC_WORKSPACE_SECTION_IDS = [
    'documents', 'tags', 'sync', 'prompts', 'identities',
] as const;

export type GroupWorkspaceSectionId = typeof GROUP_WORKSPACE_SECTION_IDS[number];
export type GroupManageSectionId = typeof GROUP_MANAGE_SECTION_IDS[number];
export type PublicWorkspaceSectionId = typeof PUBLIC_WORKSPACE_SECTION_IDS[number];
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
    /**
     * The content sections, plus the group-only `manage` sections (M7B `members`). A manage
     * section the server does not report is unavailable, never assumed; when reported it must
     * be a valid section in the `manage` group. Its `can_manage` is navigation only: every
     * membership control is gated by the member list's own hints.
     */
    sections: Record<GroupWorkspaceSectionId, WorkspaceSectionAccess>
        & Partial<Record<GroupManageSectionId, WorkspaceSectionAccess>>;
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
     * The group content screening hint. Present as `{schema_version: 1, operations: ["manage"] | []}`:
     * `manage` is the authorization every group-scoped screening route checks (the group's Owner,
     * Admin or DocumentManager, in any status), so the Documents section offers the screening
     * controls to exactly the members the server accepts. Absence means "not offered".
     */
    screening_management?: {
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
    /**
     * The group agent management hint (M4C). Present as `{schema_version: 1, operations: [...]}`
     * when the viewer may create, edit or delete group agents, computed from role and status
     * exactly like action_management. Absence means "read-only", never an empty grant.
     */
    agent_management?: {
        schema_version: number;
        operations: string[];
    };
    /**
     * The group identity management hint (M5A). Present as `{schema_version: 1, operations: [...]}`
     * when the viewer may create, edit or delete group identities, computed from the identity
     * manage roles (Owner, Admin, DocumentManager) and status. Absence means "read-only", never an
     * empty grant.
     */
    identity_management?: {
        schema_version: number;
        operations: string[];
    };
    /**
     * The group model endpoint management hint (M5C). Present as `{schema_version: 1, operations:
     * [...]}` when the viewer may create model connections, computed from the endpoint manage roles
     * and status exactly like identity_management. Absence means "read-only", never an empty grant;
     * per-endpoint edit/enable/delete/test are gated by each row's own endpoint_actions.
     */
    endpoint_management?: {
        schema_version: number;
        operations: string[];
    };
    /**
     * The group file source management hint (M5B). Present as `{schema_version: 1, operations: [...]}`
     * when the viewer may create, edit, delete, sync or test group file sources, computed from the
     * file source manage roles and status exactly like identity_management. Absence means
     * "read-only", never an empty grant.
     */
    file_source_management?: {
        schema_version: number;
        operations: string[];
    };
    /**
     * The group settings management hint (M7C). Present as `{schema_version: 1, operations: [...],
     * reasons: {...}}`, gating the profile, logo, downloads, retention edits and the activity,
     * statistics and file-count reads. `operations` are the ops the viewer may perform; `reasons`
     * maps every withheld op to the server's reason code, so an unavailable control is explained,
     * never guessed. Absence means "read-only", never an empty grant.
     */
    settings_management?: {
        schema_version: number;
        operations: string[];
        reasons?: Record<string, string>;
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
    sections: Record<PublicWorkspaceSectionId, WorkspaceSectionAccess>;
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
     * The public prompt management hint (M9C). Present as `{schema_version: 1, operations: [...]}`
     * when the viewer may create, edit or delete public workspace prompts, computed from role and
     * status exactly like document_management. Absence means "read-only", never an empty grant.
     */
    prompt_management?: {
        schema_version: number;
        operations: string[];
    };
    /**
     * The public identity management hint (M10B). Present as `{schema_version: 1, operations: [...]}`
     * when the viewer may create, edit or delete public workspace identities, computed from role and
     * status exactly like prompt_management, and additionally gated on File Sync availability.
     * Absence means "read-only", never an empty grant.
     */
    identity_management?: {
        schema_version: number;
        operations: string[];
    };
    /**
     * The public file source management hint (M10B). Present as `{schema_version: 1, operations: [...]}`
     * when the viewer may create, edit, sync or delete public workspace file sources, computed from
     * file source manage roles and status exactly like identity_management, and gated on File Sync
     * availability. Absence means "read-only", never an empty grant.
     */
    file_source_management?: {
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

const CONTENT_SECTION_GROUPS = ['knowledge', 'automation', 'connections'];

function isSectionAccess(value: unknown, groups: readonly string[] = CONTENT_SECTION_GROUPS): value is WorkspaceSectionAccess {
    return isRecord(value)
        && typeof value.enabled === 'boolean'
        && typeof value.can_manage === 'boolean'
        && typeof value.group === 'string'
        && groups.includes(value.group)
        && (!value.can_manage || value.enabled)
        && (value.enabled ? value.reason === null : typeof value.reason === 'string' && Boolean(value.reason.trim()));
}

function matchesWorkspaceContextShape(
    value: unknown,
    viewerId: string,
    id: string,
    kind: 'group' | 'public',
    logoPrefix: string,
    sectionIds: readonly string[],
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
        && sectionIds.every((sectionId) => isSectionAccess(sections[sectionId]))
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
        `/api/groups/${encodeWorkspaceId(groupId)}/logo?v=`, GROUP_WORKSPACE_SECTION_IDS)
        && isRecord(value) && isRecord(value.sections)
        && GROUP_MANAGE_SECTION_IDS.every((sectionId) => {
            const sections = value.sections as Record<string, unknown>;
            return sections[sectionId] === undefined || isSectionAccess(sections[sectionId], ['manage']);
        });
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
        `/api/public_workspaces/${encodeWorkspaceId(workspaceId)}/logo?v=`, PUBLIC_WORKSPACE_SECTION_IDS);
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

// groupSettings.ts
// The scoped client for the native group Settings, Activity and Statistics views (M7C).
//
// Every read and write goes to the named-group routes, `/api/groups/<g>/settings...` and
// `/api/groups/<g>/insights/...`, so a group page never touches a personal or classic settings
// route. The envelopes are validated strictly and thrown on rather than rendered as empty, exactly
// as the group model-endpoint adapter validates its list: a drifted or truncated payload is a load
// error, never a blank surface that reads as "nothing to configure".
//
// Every write answers with the fresh settings read, which the caller replaces its state from
// wholesale -- the old state is never merged back in. A stale section revision comes back as a 409
// `group_settings_changed`, which the editor resolves by reloading that section and rebasing the
// draft; a write-guard exhaustion is a 409 `group_write_conflict`, which a plain retry resolves; a
// logo already gone is a 409 `no_group_logo`, which a quiet reload resolves. Any other failure --
// a 400 with the server's verbatim message, a 403 refusal carrying its reason code, or a 404 -- is
// surfaced as the server phrased it.

import { ApiError, api, apiUrl, CREDENTIALS_MODE, requestWithStatus } from './apiClient';
import { isRecord } from './workspaceAuthoring';
import { requireWorkspaceId } from './workspaceContext';
import type { GroupWorkspaceRole, GroupWorkspaceStatus, WorkspaceRef } from './workspaceContext';

export type GroupSettingsScope = Extract<WorkspaceRef, { kind: 'group' }>;

/** A retention period as the server resolves it: whole days, no automatic deletion, or the org default. */
export type GroupRetentionValue = number | 'none' | 'default';

export interface GroupProfileSettings {
    name: string;
    description: string;
    hero_color: string;
    revision: string;
}

export interface GroupLogoSettings {
    has_logo: boolean;
    logo_version: number;
    logo_url: string | null;
    revision: string;
}

export interface GroupDownloadsSettings {
    disable_file_downloads: boolean;
    file_downloads_enabled: boolean;
    revision: string;
}

export interface GroupRetentionBounds {
    min_days: number;
    max_days: number;
}

export interface GroupRetentionSettings {
    conversation_retention_days: GroupRetentionValue;
    document_retention_days: GroupRetentionValue;
    bounds: { conversation: GroupRetentionBounds; document: GroupRetentionBounds };
    organization_defaults: {
        conversation_retention_days: number | 'none';
        document_retention_days: number | 'none';
    };
    revision: string;
}

export interface GroupSettingsManagement {
    schema_version: number;
    operations: string[];
    reasons?: Record<string, string>;
}

export interface GroupSettings {
    schema_version: 1;
    group_id: string;
    viewer_role: GroupWorkspaceRole;
    status: GroupWorkspaceStatus;
    profile: GroupProfileSettings;
    logo: GroupLogoSettings;
    settings_management: GroupSettingsManagement;
    downloads?: GroupDownloadsSettings;
    retention?: GroupRetentionSettings;
}

/** One projected activity record. */
export interface GroupActivityActor {
    kind: 'member' | 'former_member' | 'system';
    display_name?: string;
}

export interface GroupActivityRecord {
    id: string | null;
    occurred_at: string | null;
    type: string;
    summary: string;
    actor: GroupActivityActor;
}

export interface GroupActivityFeed {
    activity: GroupActivityRecord[];
    limit: number;
}

/** The raw statistics envelope, kept as the server sends it so the export matches classic exactly. */
export interface GroupStatsPayload {
    totalDocuments: number;
    storageUsed: number;
    totalTokens: number;
    totalMembers: number;
    storage: { ai_search_size: number; storage_account_size: number };
    documentActivity: { labels: string[]; uploads: number[]; deletes: number[] };
    tokenUsage: { labels: string[]; data: number[] };
    dateRange: string[];
    window: { type: string; days: number; label: string; startDate: string; endDate: string };
}

/** The activity limits the server accepts, mirrored so the control offers exactly those. */
export const GROUP_ACTIVITY_LIMITS = [10, 20, 50] as const;
export const GROUP_ACTIVITY_DEFAULT_LIMIT = 50;

const MALFORMED_SETTINGS = 'The group settings were malformed. Refresh and try again.';
const MALFORMED_ACTIVITY = 'The group activity was malformed. Refresh and try again.';
const MALFORMED_STATS = 'The group statistics were malformed. Refresh and try again.';

/** A malformed envelope, a load error rather than a rendered blank. */
export class GroupSettingsResponseError extends Error {
    constructor(message: string) {
        super(message);
        this.name = 'GroupSettingsResponseError';
    }
}

/** A stale section revision (409 `group_settings_changed`): reload the section and rebase. */
export class GroupSettingsChangedError extends Error {
    constructor(message?: string) {
        super(message || 'These settings changed since you opened them. Reload them before saving.');
        this.name = 'GroupSettingsChangedError';
    }
}

/**
 * The shared write-conflict sentence, kept byte-identical to the server's
 * `functions_group.GROUP_WRITE_CONFLICT_MESSAGE` so a plain-retry 409 reads the same everywhere.
 */
export const GROUP_WRITE_CONFLICT_MESSAGE = 'The group changed while your request was being saved. Try again.';

/** A write-guard exhaustion (409 `group_write_conflict`): a plain retry resolves it. */
export class GroupSettingsWriteConflictError extends Error {
    constructor(message?: string) {
        super(message || GROUP_WRITE_CONFLICT_MESSAGE);
        this.name = 'GroupSettingsWriteConflictError';
    }
}

/** The logo is already gone (409 `no_group_logo`): reload quietly. */
export class GroupLogoMissingError extends Error {
    constructor(message?: string) {
        super(message || 'This group has no logo to remove.');
        this.name = 'GroupLogoMissingError';
    }
}

function errorCode(payload: unknown): string | undefined {
    return isRecord(payload) && typeof payload.error_code === 'string' ? payload.error_code : undefined;
}

/**
 * The server's reviewed refusal messages, keyed by the reason code its `reasons` map reports. The
 * keys and texts are pinned against `functions_group_settings.REFUSAL_MESSAGES` by a functional test
 * so the client can never drift from the codes the server actually sends (for example the plural
 * `create_groups_role_required`).
 */
const REFUSAL_TEXT: Record<string, string> = {
    group_owner_required: 'Only the group owner can do this.',
    group_manager_required: 'Only the group owner or an admin can do this.',
    create_groups_role_required:
        "You need the CreateGroups role to change this group's name, description or color.",
    group_status_unavailable:
        "This group is locked or inactive, so its name, description, color and logo can't be changed.",
    group_downloads_not_enabled: "An administrator hasn't turned on file downloads for this group.",
    group_retention_disabled: "Retention policies aren't turned on for group workspaces.",
};

/** The reviewed text for a withheld operation's reason code, or undefined when none is known. */
export function groupSettingsReasonText(code: string | undefined): string | undefined {
    return code ? REFUSAL_TEXT[code] : undefined;
}

/** Map a write failure: the three 409 codes to their typed errors, everything else surfaced verbatim. */
function mapWriteError(cause: unknown): never {
    if (cause instanceof ApiError && cause.status === 409) {
        const code = errorCode(cause.payload);
        if (code === 'group_write_conflict') {
            throw new GroupSettingsWriteConflictError(cause.message);
        }
        if (code === 'no_group_logo') {
            throw new GroupLogoMissingError(cause.message);
        }
        // `group_settings_changed` and any other 409 are stale-revision conflicts a reload resolves.
        throw new GroupSettingsChangedError(cause.message);
    }
    // A 400 (verbatim), a 403 refusal carrying its reason code, or a 404 is surfaced as phrased.
    throw cause;
}

function requireString(value: unknown): value is string {
    return typeof value === 'string';
}

function validateRevisionObject(value: unknown): value is Record<string, unknown> {
    return isRecord(value) && requireString(value.revision) && Boolean((value.revision as string).length);
}

/** Validate the settings read strictly, per the contract's §8.2 rules. */
function normalizeSettings(value: unknown): GroupSettings {
    if (!isRecord(value) || !isRecord(value.settings)) {
        throw new GroupSettingsResponseError(MALFORMED_SETTINGS);
    }
    const settings = value.settings;
    const management = settings.settings_management;
    if (
        settings.schema_version !== 1
        || !validateRevisionObject(settings.profile)
        || !validateRevisionObject(settings.logo)
        || !isRecord(management)
        || management.schema_version !== 1
        || !Array.isArray(management.operations)
        || !isRecord(management.reasons)
        || (settings.downloads !== undefined && !validateRevisionObject(settings.downloads))
        || (settings.retention !== undefined && !validateRevisionObject(settings.retention))
    ) {
        throw new GroupSettingsResponseError(MALFORMED_SETTINGS);
    }
    return settings as unknown as GroupSettings;
}

function normalizeActivity(value: unknown): GroupActivityFeed {
    if (!isRecord(value) || !Array.isArray(value.activity) || typeof value.limit !== 'number') {
        throw new GroupSettingsResponseError(MALFORMED_ACTIVITY);
    }
    const activity = value.activity.map((item) => {
        if (!isRecord(item) || !requireString(item.summary) || !requireString(item.type) || !isRecord(item.actor)
            || (item.id !== null && !requireString(item.id))
            || (item.occurred_at !== null && !requireString(item.occurred_at))) {
            throw new GroupSettingsResponseError(MALFORMED_ACTIVITY);
        }
        return item as unknown as GroupActivityRecord;
    });
    return { activity, limit: value.limit };
}

function numberArray(value: unknown): value is number[] {
    return Array.isArray(value) && value.every((item) => typeof item === 'number');
}

function stringArray(value: unknown): value is string[] {
    return Array.isArray(value) && value.every((item) => typeof item === 'string');
}

function normalizeStats(value: unknown): GroupStatsPayload {
    if (!isRecord(value) || !isRecord(value.stats)) {
        throw new GroupSettingsResponseError(MALFORMED_STATS);
    }
    const stats = value.stats;
    const documentActivity = stats.documentActivity;
    const tokenUsage = stats.tokenUsage;
    const storage = stats.storage;
    const window = stats.window;
    if (
        typeof stats.totalDocuments !== 'number' || typeof stats.storageUsed !== 'number'
        || typeof stats.totalTokens !== 'number' || typeof stats.totalMembers !== 'number'
        || !isRecord(storage) || typeof storage.ai_search_size !== 'number'
        || typeof storage.storage_account_size !== 'number'
        || !isRecord(documentActivity) || !stringArray(documentActivity.labels)
        || !numberArray(documentActivity.uploads) || !numberArray(documentActivity.deletes)
        || !isRecord(tokenUsage) || !stringArray(tokenUsage.labels) || !numberArray(tokenUsage.data)
        || !stringArray(stats.dateRange) || !isRecord(window) || !requireString(window.label)
    ) {
        throw new GroupSettingsResponseError(MALFORMED_STATS);
    }
    return stats as unknown as GroupStatsPayload;
}

function settingsBase(groupId: string): string {
    return `/api/groups/${encodeURIComponent(requireWorkspaceId(groupId))}/settings`;
}

function insightsUrl(groupId: string, resource: 'activity' | 'stats' | 'file-count', query = ''): string {
    const base = `/api/groups/${encodeURIComponent(requireWorkspaceId(groupId))}/insights/${resource}`;
    return query ? `${base}?${query}` : base;
}

/** A field changed by a profile write, sent alongside the profile revision. */
export interface GroupProfileChanges {
    name?: string;
    description?: string;
    hero_color?: string;
}

/** A retention change, merged server-side, sent alongside the retention revision. */
export interface GroupRetentionChanges {
    conversation_retention_days?: GroupRetentionValue;
    document_retention_days?: GroupRetentionValue;
}

export interface GroupSettingsAdapter {
    scope: GroupSettingsScope;
    /** Whether the viewer may perform a settings operation, from `settings_management.operations`. */
    allows: (operation: string) => boolean;
    /** The server's reason code for a withheld operation, for an honest explanation. */
    reason: (operation: string) => string | undefined;
    readSettings: (signal?: AbortSignal) => Promise<GroupSettings>;
    updateProfile: (changes: GroupProfileChanges, revision: string) => Promise<GroupSettings>;
    replaceLogo: (file: File, revision: string) => Promise<GroupSettings>;
    removeLogo: (revision: string) => Promise<GroupSettings>;
    updateDownloads: (disableFileDownloads: boolean, revision: string) => Promise<GroupSettings>;
    updateRetention: (changes: GroupRetentionChanges, revision: string) => Promise<GroupSettings>;
    readActivity: (limit: number, signal?: AbortSignal) => Promise<GroupActivityFeed>;
    readStats: (query: string, signal?: AbortSignal) => Promise<GroupStatsPayload>;
    readFileCount: (signal?: AbortSignal) => Promise<number>;
}

/**
 * Build the scoped settings client for one group. `management` is the context's or the read's
 * `settings_management` block; `allows`/`reason` read from it with no fallback, so an unavailable
 * control is explained by the server's own reason, never guessed.
 */
export function createGroupSettingsAdapter(
    scope: GroupSettingsScope,
    management: GroupSettingsManagement | undefined,
): GroupSettingsAdapter {
    const groupId = requireWorkspaceId(scope.id);
    const operations = new Set(Array.isArray(management?.operations) ? management!.operations : []);
    const reasons = isRecord(management?.reasons) ? (management!.reasons as Record<string, string>) : {};

    async function conditionalWrite(
        method: 'PATCH' | 'DELETE', url: string, body: Record<string, unknown>,
    ): Promise<GroupSettings> {
        try {
            const response = await requestWithStatus<unknown>(url, { method, body });
            return normalizeSettings(response.data);
        } catch (cause) {
            mapWriteError(cause);
        }
    }

    return {
        scope,
        allows: (operation) => operations.has(operation),
        reason: (operation) => reasons[operation],
        readSettings: async (signal) => normalizeSettings(await api.get<unknown>(settingsBase(groupId), signal)),
        updateProfile: (changes, revision) =>
            conditionalWrite('PATCH', `${settingsBase(groupId)}/profile`, { ...changes, revision }),
        replaceLogo: async (file, revision) => {
            const form = new FormData();
            form.append('logo_file', file);
            form.append('revision', revision);
            const response = await fetch(`${apiUrl(settingsBase(groupId))}/logo`, {
                method: 'PUT',
                credentials: CREDENTIALS_MODE,
                headers: { Accept: 'application/json' },
                body: form,
            });
            if (!response.ok) {
                let payload: unknown = null;
                try {
                    payload = await response.json();
                } catch {
                    payload = null;
                }
                const message = isRecord(payload) && typeof payload.error === 'string'
                    ? payload.error
                    : 'The logo could not be saved. Refresh and try again.';
                mapWriteError(new ApiError(message, response.status, payload));
            }
            return normalizeSettings(await response.json());
        },
        removeLogo: (revision) => conditionalWrite('DELETE', `${settingsBase(groupId)}/logo`, { revision }),
        updateDownloads: (disableFileDownloads, revision) =>
            conditionalWrite('PATCH', `${settingsBase(groupId)}/downloads`, {
                disable_file_downloads: disableFileDownloads, revision,
            }),
        updateRetention: (changes, revision) =>
            conditionalWrite('PATCH', `${settingsBase(groupId)}/retention`, { ...changes, revision }),
        readActivity: async (limit, signal) =>
            normalizeActivity(await api.get<unknown>(insightsUrl(groupId, 'activity', `limit=${limit}`), signal)),
        readStats: async (query, signal) =>
            normalizeStats(await api.get<unknown>(insightsUrl(groupId, 'stats', query), signal)),
        readFileCount: async (signal) => {
            const response = await api.get<unknown>(insightsUrl(groupId, 'file-count'), signal);
            if (!isRecord(response) || typeof response.file_count !== 'number') {
                throw new GroupSettingsResponseError('The document count was malformed. Refresh and try again.');
            }
            return response.file_count;
        },
    };
}

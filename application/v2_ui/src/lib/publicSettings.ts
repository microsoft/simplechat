// publicSettings.ts
// The scoped client for the native public workspace Settings, Activity and Statistics views (M10C).
//
// Every read and write goes to the named-workspace routes, `/api/public-workspaces/<w>/settings...`
// and `/api/public-workspaces/<w>/insights/...`, so a public page never touches a classic settings,
// download, retention, stats or file-count route. The client is the group's (createSettingsClient):
// the same strict envelope validation, the same wholesale replacement after every write and the same
// conflict mapping, with the public routes and codes. A stale section revision is a 409
// `public_workspace_settings_changed` (reload the section and rebase the draft), a write-guard
// exhaustion a 409 `public_workspace_write_conflict` (a plain retry), and a logo already gone a 409
// `no_public_workspace_logo` (a quiet reload). Anything else is surfaced as the server phrased it.

import {
    createSettingsClient,
    type GroupSettingsManagement,
    type WorkspaceSettings,
    type WorkspaceSettingsAdapter,
} from './groupSettings';
import { requireWorkspaceId, type WorkspaceRef } from './workspaceContext';

export type PublicSettingsScope = Extract<WorkspaceRef, { kind: 'public' }>;

export interface PublicSettings extends WorkspaceSettings {
    workspace_id: string;
}

export interface PublicSettingsAdapter extends WorkspaceSettingsAdapter<PublicSettings> {
    scope: PublicSettingsScope;
}

/**
 * The server's reviewed refusal messages, keyed by the reason code its `reasons` map reports. The
 * keys and texts are pinned against `functions_public_settings_policy.PUBLIC_SETTINGS_REFUSAL_MESSAGES`
 * by a functional test, so the client can never word a refusal differently from the route.
 */
const REFUSAL_TEXT: Record<string, string> = {
    public_workspace_owner_required: 'Only the workspace owner can do this.',
    public_workspace_manager_required: 'Only the workspace owner or an admin can do this.',
    public_workspace_member_required: 'Only the workspace owner, an admin or a document manager can do this.',
    public_workspace_status_unavailable:
        "This workspace is locked or inactive, so its name, description, color and logo can't be changed.",
    public_workspace_downloads_not_enabled: "An administrator hasn't turned on file downloads for this workspace.",
    public_workspace_retention_disabled: "Retention policies aren't turned on for public workspaces.",
};

/** The reviewed text for a withheld operation's reason code, or undefined when none is known. */
export function publicSettingsReasonText(code: string | undefined): string | undefined {
    return code ? REFUSAL_TEXT[code] : undefined;
}

/**
 * Build the scoped settings client for one public workspace. `management` is the context's or the
 * read's `settings_management` block, read with no fallback, exactly as the group client reads it.
 */
export function createPublicSettingsAdapter(
    scope: PublicSettingsScope,
    management: GroupSettingsManagement | undefined,
): PublicSettingsAdapter {
    const base = `/api/public-workspaces/${encodeURIComponent(requireWorkspaceId(scope.id))}`;
    return {
        ...createSettingsClient<PublicSettings>(scope, management, {
            settingsBase: `${base}/settings`,
            insightsBase: `${base}/insights`,
            writeConflictCode: 'public_workspace_write_conflict',
            logoMissingCode: 'no_public_workspace_logo',
            malformedSettings: 'The workspace settings were malformed. Refresh and try again.',
            malformedActivity: 'The workspace activity was malformed. Refresh and try again.',
            malformedStats: 'The workspace statistics were malformed. Refresh and try again.',
        }),
        scope,
    };
}

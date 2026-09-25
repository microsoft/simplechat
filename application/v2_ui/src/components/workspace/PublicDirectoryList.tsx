// PublicDirectoryList.tsx
// The presentational body of the public workspace directory: the rows, their role and status
// badges, an Open action and the per-workspace "Visible for chat" switch.
//
// Like the group DirectoryList it carries no network knowledge: the page above owns every
// fetch, the visibility map and the settings write, and hands this component the rows plus the
// callbacks to fire. A public row has no owner and no member count to show -- the directory
// deliberately withholds them -- so this is a sibling of the group list, not a reuse of it.
//
// Two states matter per row and are independent: whether a workspace is *available* (its status
// lets a reader chat it) and whether the reader has it *visible* for chat. An unavailable
// workspace is dimmed and labelled, but its switch still works, because hiding one you cannot
// currently use is a valid choice and must never error.

import { useState } from 'react';
import { ArrowUpRight } from 'lucide-react';
import { GlassButton, GlassPanel } from '../ui/primitives';
import { Pill } from './primitives';
import { publicRoleLabel, publicStatusLabel } from '../../lib/publicWorkspaceNavigation';
import { isChattableStatus } from '../../lib/publicVisibility';
import type { PublicDirectoryWorkspace } from '../../lib/publicDirectory';

function DirectoryLogo({ workspace, logoUrl }: { workspace: PublicDirectoryWorkspace; logoUrl: string | null }) {
    const [failed, setFailed] = useState(false);
    const initial = (workspace.name.trim()[0] ?? '?').toUpperCase();
    return (
        <div
            className="flex h-10 w-10 shrink-0 items-center justify-center overflow-hidden rounded-lg border bg-surface-1 text-sm font-semibold text-text-2"
            style={{ borderColor: workspace.heroColor }}
        >
            {logoUrl && !failed ? (
                <img src={logoUrl} alt="" className="h-full w-full object-contain" onError={() => setFailed(true)} />
            ) : (
                <span aria-hidden="true">{initial}</span>
            )}
        </div>
    );
}

function StatusBadge({ status }: { status: string }) {
    // Active is the ordinary state and needs no badge; anything else earns a toned pill so a
    // reader can see at a glance which workspaces they cannot currently use.
    if (status === 'active') return null;
    const tone = status === 'inactive' || status === 'unknown' ? 'danger' : 'warn';
    return <Pill tone={tone}>{publicStatusLabel(status)}</Pill>;
}

/**
 * A compact, accessible visibility switch that reuses the shared Toggle's track and thumb so the
 * directory row and the settings panel never drift. The label is carried by aria-label, not
 * visible text, to keep the row tight.
 */
function VisibilitySwitch({
    workspace, visible, disabled, onToggle,
}: {
    workspace: PublicDirectoryWorkspace;
    visible: boolean;
    disabled: boolean;
    onToggle: (id: string, next: boolean) => void;
}) {
    return (
        <label className={`flex shrink-0 cursor-pointer items-center gap-2 ${disabled ? 'cursor-not-allowed opacity-60' : ''}`}>
            <span className="hidden text-xs text-text-3 sm:inline">{visible ? 'Visible for chat' : 'Hidden from chat'}</span>
            <span className="relative inline-flex">
                <input
                    type="checkbox"
                    className="peer sr-only"
                    checked={visible}
                    disabled={disabled}
                    aria-label={`Show ${workspace.name} in public chat`}
                    onChange={(event) => onToggle(workspace.id, event.target.checked)}
                />
                <span
                    aria-hidden="true"
                    className="block h-6 w-11 rounded-full border border-edge bg-surface-sunken transition-colors peer-checked:border-transparent peer-checked:bg-accent peer-focus-visible:ring-2 peer-focus-visible:ring-accent peer-focus-visible:ring-offset-2"
                />
                <span
                    aria-hidden="true"
                    className="pointer-events-none absolute top-1 left-1 h-4 w-4 rounded-full bg-white shadow transition-transform duration-200 peer-checked:translate-x-5"
                />
            </span>
        </label>
    );
}

export function PublicDirectoryRow({
    workspace, visible, disabled, logoUrl, onOpen, onToggleVisibility,
}: {
    workspace: PublicDirectoryWorkspace;
    visible: boolean;
    disabled: boolean;
    logoUrl: string | null;
    onOpen: (id: string) => void;
    onToggleVisibility: (id: string, next: boolean) => void;
}) {
    const available = isChattableStatus(workspace.status);
    return (
        <GlassPanel elevation="flat" className={`flex flex-wrap items-center gap-3 p-3 ${available ? '' : 'opacity-70'}`}>
            <DirectoryLogo workspace={workspace} logoUrl={logoUrl} />
            <div className="min-w-0 flex-1 basis-56">
                <div className="flex min-w-0 flex-wrap items-center gap-2">
                    <p className="truncate text-sm font-medium text-text-1">{workspace.name}</p>
                    {workspace.membership === 'member' ? <Pill tone="accent">{publicRoleLabel(workspace.userRole)}</Pill> : null}
                    <StatusBadge status={workspace.status} />
                </div>
                <p className="mt-0.5 line-clamp-2 text-xs text-text-3">{workspace.description || 'No description provided.'}</p>
                {!available ? (
                    <p className="mt-1 text-[11px] text-text-3">Not available for chat right now. You can still hide it from your list.</p>
                ) : null}
            </div>
            <div className="ml-auto flex shrink-0 items-center gap-3">
                <VisibilitySwitch workspace={workspace} visible={visible} disabled={disabled} onToggle={onToggleVisibility} />
                <GlassButton size="sm" variant="subtle" disabled={disabled} aria-label={`Open ${workspace.name}`}
                    onClick={() => onOpen(workspace.id)}>
                    Open<ArrowUpRight size={14} />
                </GlassButton>
            </div>
        </GlassPanel>
    );
}

export function PublicDirectoryList({
    workspaces, busyId, disabled, visibleFor, logoUrlFor, onOpen, onToggleVisibility,
}: {
    workspaces: PublicDirectoryWorkspace[];
    busyId: string | null;
    disabled: boolean;
    visibleFor: (workspace: PublicDirectoryWorkspace) => boolean;
    logoUrlFor: (workspace: PublicDirectoryWorkspace) => string | null;
    onOpen: (id: string) => void;
    onToggleVisibility: (id: string, next: boolean) => void;
}) {
    return (
        <ul className="space-y-2">
            {workspaces.map((workspace) => (
                <li key={workspace.id}>
                    <PublicDirectoryRow workspace={workspace}
                        visible={visibleFor(workspace)}
                        disabled={disabled && busyId !== workspace.id}
                        logoUrl={logoUrlFor(workspace)}
                        onOpen={onOpen} onToggleVisibility={onToggleVisibility} />
                </li>
            ))}
        </ul>
    );
}

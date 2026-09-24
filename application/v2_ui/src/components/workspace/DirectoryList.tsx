// DirectoryList.tsx
// The presentational body of a workspace directory: the rows, their membership badge and
// the one action each row offers.
//
// It is deliberately free of any network knowledge, so the group directory (M7A) and the
// public directory (M9A) can drive the same layout from different adapters. The page above
// owns loading, paging, the create dialog and every fetch; this component is told what to
// show and which callbacks to fire, and it fires exactly one action per row from the
// server-derived membership and hint it was given.

import { useState } from 'react';
import type { ReactNode } from 'react';
import { ArrowUpRight, Loader2, Users } from 'lucide-react';
import { GlassButton, GlassPanel } from '../ui/primitives';
import { Pill } from './primitives';
import { groupRoleLabel } from '../../lib/groupWorkspaceNavigation';
import type { DirectoryGroup, DirectoryHints } from '../../lib/groupDirectory';

function DirectoryLogo({ group, logoUrl }: { group: DirectoryGroup; logoUrl: string | null }) {
    const [failed, setFailed] = useState(false);
    const initial = (group.name.trim()[0] ?? '?').toUpperCase();
    return (
        <div
            className="flex h-10 w-10 shrink-0 items-center justify-center overflow-hidden rounded-lg border bg-surface-1 text-sm font-semibold text-text-2"
            style={{ borderColor: group.heroColor }}
        >
            {logoUrl && !failed ? (
                <img src={logoUrl} alt="" className="h-full w-full object-contain" onError={() => setFailed(true)} />
            ) : (
                <span aria-hidden="true">{initial}</span>
            )}
        </div>
    );
}

function MembershipBadge({ group }: { group: DirectoryGroup }) {
    // The badge slot is always rendered so a change from "Requested" to a role, or to none,
    // never shifts the row height.
    return (
        <div className="flex min-h-[1.25rem] shrink-0 items-center">
            {group.membership === 'member' ? (
                <Pill tone="accent">{groupRoleLabel(group.userRole ?? 'User')}</Pill>
            ) : group.membership === 'pending' ? (
                <Pill tone="warn">Requested</Pill>
            ) : null}
        </div>
    );
}

function RowAction({
    group, hints, busy, disabled, onOpen, onJoin, onCancel,
}: {
    group: DirectoryGroup;
    hints: DirectoryHints;
    busy: boolean;
    disabled: boolean;
    onOpen: (id: string) => void;
    onJoin: (id: string) => void;
    onCancel: (id: string) => void;
}): ReactNode {
    if (group.membership === 'member') {
        return (
            <GlassButton size="sm" variant="subtle" disabled={disabled} aria-label={`Open ${group.name}`}
                onClick={() => onOpen(group.id)}>
                Open<ArrowUpRight size={14} />
            </GlassButton>
        );
    }
    if (group.membership === 'pending') {
        return (
            <GlassButton size="sm" disabled={busy || disabled} aria-label={`Cancel request for ${group.name}`}
                onClick={() => onCancel(group.id)}>
                {busy ? <Loader2 size={14} className="animate-spin" /> : null}Cancel request
            </GlassButton>
        );
    }
    if (hints.canRequestToJoin) {
        return (
            <GlassButton size="sm" variant="primary" disabled={busy || disabled} aria-label={`Request to join ${group.name}`}
                onClick={() => onJoin(group.id)}>
                {busy ? <Loader2 size={14} className="animate-spin" /> : null}Request to join
            </GlassButton>
        );
    }
    return null;
}

export function DirectoryRow({
    group, hints, busy, disabled, logoUrl, onOpen, onJoin, onCancel,
}: {
    group: DirectoryGroup;
    hints: DirectoryHints;
    busy: boolean;
    disabled: boolean;
    logoUrl: string | null;
    onOpen: (id: string) => void;
    onJoin: (id: string) => void;
    onCancel: (id: string) => void;
}) {
    return (
        <GlassPanel elevation="flat" className="flex flex-wrap items-center gap-3 p-3">
            <DirectoryLogo group={group} logoUrl={logoUrl} />
            <div className="min-w-0 flex-1 basis-56">
                <div className="flex min-w-0 items-center gap-2">
                    <p className="truncate text-sm font-medium text-text-1">{group.name}</p>
                    <MembershipBadge group={group} />
                </div>
                <p className="mt-0.5 line-clamp-2 text-xs text-text-3">{group.description || 'No description provided.'}</p>
                <p className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[11px] text-text-3">
                    <span className="inline-flex items-center gap-1"><Users size={12} />{group.memberCount} {group.memberCount === 1 ? 'member' : 'members'}</span>
                    <span className="truncate">Owner: {group.ownerDisplayName || 'Unknown'}</span>
                </p>
            </div>
            <div className="ml-auto flex shrink-0 items-center">
                <RowAction group={group} hints={hints} busy={busy} disabled={disabled}
                    onOpen={onOpen} onJoin={onJoin} onCancel={onCancel} />
            </div>
        </GlassPanel>
    );
}

export function DirectoryList({
    groups, hints, busyId, disabled, logoUrlFor, onOpen, onJoin, onCancel,
}: {
    groups: DirectoryGroup[];
    hints: DirectoryHints;
    busyId: string | null;
    disabled: boolean;
    logoUrlFor: (group: DirectoryGroup) => string | null;
    onOpen: (id: string) => void;
    onJoin: (id: string) => void;
    onCancel: (id: string) => void;
}) {
    return (
        <ul className="space-y-2">
            {groups.map((group) => (
                <li key={group.id}>
                    <DirectoryRow group={group} hints={hints}
                        busy={busyId === group.id} disabled={disabled && busyId !== group.id}
                        logoUrl={logoUrlFor(group)}
                        onOpen={onOpen} onJoin={onJoin} onCancel={onCancel} />
                </li>
            ))}
        </ul>
    );
}

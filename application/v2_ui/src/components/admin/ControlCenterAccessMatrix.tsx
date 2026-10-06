// ControlCenterAccessMatrix.tsx
// Who can open the Control Center, under the switches as they currently stand.
//
// Two switches decide Control Center access, and they interact in a way neither label can
// say on its own: requiring ControlCenterAdmin takes access away from general Admins, while
// the dashboard reader role works whether or not that requirement is on. The server-rendered
// page explained this in prose spread across a pane and a modal. A table read straight from
// the switches -- unsaved edits included -- shows the consequence of a change before it is
// saved.
//
// The rules are `controlCenterAccess`, which mirrors `control_center_required`.

import { clsx } from 'clsx';
import { Check, Minus } from 'lucide-react';
import { controlCenterAccess, type ControlCenterRole } from '../../lib/adminOperations';
import { CopyChip } from './CopyValue';
import { ReadoutRow } from './ReadoutRow';

const ROLE_DESCRIPTIONS: Record<ControlCenterRole, string> = {
    Admin: "SimpleChat's general administrator role.",
    ControlCenterAdmin: 'Delegated Control Center administration.',
    ControlCenterDashboardReader: 'The usage picture, with no way to change anything.',
};

function AccessCell({ granted, role, area }: { granted: boolean; role: string; area: string }) {
    return (
        <td className="px-3 py-2.5 align-top">
            <span
                className={clsx(
                    'inline-flex items-center gap-1.5 text-[0.8125rem]',
                    granted ? 'font-medium text-text-1' : 'text-text-3',
                )}
            >
                {granted ? (
                    <Check size={14} aria-hidden="true" className="shrink-0 text-ok" />
                ) : (
                    <Minus size={14} aria-hidden="true" className="shrink-0" />
                )}
                {granted ? 'Yes' : 'No'}
                <span className="sr-only">
                    {granted ? `, ${role} can use the ${area}` : `, ${role} cannot use the ${area}`}
                </span>
            </span>
        </td>
    );
}

export function ControlCenterAccessMatrix({
    label,
    help,
    requireAdminRole,
    allowDashboardReader,
    unsaved,
}: {
    label: string;
    help?: string;
    requireAdminRole: boolean;
    allowDashboardReader: boolean;
    /** Whether either switch holds an edit that has not been saved yet. */
    unsaved: boolean;
}) {
    const rows = controlCenterAccess(requireAdminRole, allowDashboardReader);

    return (
        <ReadoutRow label={label} help={help} width="full">
            {/* Positioned so the cells' screen-reader text, which is absolutely positioned,
                scrolls with the table instead of widening the card past the viewport. */}
            <div className="relative overflow-x-auto rounded-lg border border-edge">
                <table className="w-full min-w-[30rem] border-collapse text-left">
                    <caption className="sr-only">
                        Control Center access for each app role
                        {unsaved ? ', including changes that have not been saved' : ''}
                    </caption>
                    <thead className="bg-surface-2 text-xs text-text-2">
                        <tr>
                            <th scope="col" className="px-3 py-2 font-semibold">
                                App role
                            </th>
                            <th scope="col" className="px-3 py-2 font-semibold">
                                Dashboard
                                <span className="block font-normal text-text-3">
                                    Statistics, activity trends, usage metrics
                                </span>
                            </th>
                            <th scope="col" className="px-3 py-2 font-semibold">
                                Management
                                <span className="block font-normal text-text-3">
                                    Users, groups, public workspaces, activity logs
                                </span>
                            </th>
                        </tr>
                    </thead>
                    <tbody className="divide-y divide-edge">
                        {rows.map((row) => (
                            <tr key={row.role}>
                                <th scope="row" className="px-3 py-2.5 align-top font-normal">
                                    <CopyChip value={row.role} label={`the ${row.role} role value`} />
                                    <span className="mt-1 block text-xs text-text-3">
                                        {ROLE_DESCRIPTIONS[row.role]}
                                    </span>
                                </th>
                                <AccessCell
                                    granted={row.access !== 'none'}
                                    role={row.role}
                                    area="dashboard"
                                />
                                <AccessCell
                                    granted={row.access === 'full'}
                                    role={row.role}
                                    area="management features"
                                />
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
            <p className="mt-2 text-xs leading-relaxed text-text-3">
                Each row is one role held on its own; someone holding two gets the better row.
                {unsaved ? ' Showing your unsaved changes.' : ''}
            </p>
        </ReadoutRow>
    );
}

// AdminGlobalEditorPages.tsx
// The global agent and action editors, opened from Admin Settings.
//
// These are the same editors personal and group workspaces use, driven by the global
// workbench adapters, inside an Admin Settings page frame. Saving or going back returns to
// Admin Settings with the matching section in view. Only an administrator reaches them;
// anyone else is told why, and the server refuses every global editor route regardless.

import type { ReactNode } from 'react';
import { ShieldAlert } from 'lucide-react';
import { PageHeader } from '../components/layout/PageHeader';
import { GlassPanel } from '../components/ui/primitives';
import { GLOBAL_ACTION_WORKBENCH } from '../lib/actionWorkbench';
import { GLOBAL_AGENT_WORKBENCH } from '../lib/agentWorkbench';
import { useBootstrapStore } from '../stores/bootstrapStore';
import { ActionEditorPage } from './workspace/ActionEditorPage';
import { AgentEditorPage } from './workspace/AgentEditorPage';

function AdminEditorFrame({ description, children }: { description: string; children: ReactNode }) {
    const isAdmin = useBootstrapStore((state) => Boolean(state.data?.user?.is_admin));
    return (
        <>
            <PageHeader title="Admin settings" description={description} />
            {isAdmin ? (
                <div className="flex min-h-0 flex-1 flex-col overflow-hidden p-4 lg:px-6">
                    <div className="mx-auto flex min-h-0 w-full max-w-6xl flex-1 flex-col">{children}</div>
                </div>
            ) : (
                <div className="flex flex-1 items-center justify-center p-6">
                    <GlassPanel className="flex max-w-md items-start gap-3 p-5">
                        <ShieldAlert size={20} className="mt-0.5 shrink-0 text-warn" aria-hidden="true" />
                        <div>
                            <p className="font-medium text-text-1">Administrator access required</p>
                            <p className="mt-1 text-sm text-text-3">Your account does not hold the Admin role.</p>
                        </div>
                    </GlassPanel>
                </div>
            )}
        </>
    );
}

export function AdminAgentEditorPage() {
    return (
        <AdminEditorFrame description="Global agents">
            <AgentEditorPage adapter={GLOBAL_AGENT_WORKBENCH} />
        </AdminEditorFrame>
    );
}

export function AdminActionEditorPage() {
    return (
        <AdminEditorFrame description="Global actions">
            <ActionEditorPage adapter={GLOBAL_ACTION_WORKBENCH} />
        </AdminEditorFrame>
    );
}

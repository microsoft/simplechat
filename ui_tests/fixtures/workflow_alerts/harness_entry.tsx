// harness_entry.tsx
//
// Test-only harness entry (NOT application source) for ui_tests/test_v2_workflow_alert_notices.py.
//
// Mounts the real V2 frame -- AppShell with its rail, the notification bell, the workflow
// alert notice in the rail, the alert card and the live region -- in a memory router, with
// both notification runtimes running above it in the order App.tsx runs them. Nothing in
// application/v2_ui/src is replaced; the test answers HTTP and fakes only the browser APIs a
// headless page cannot drive (visibility and focus).
//
// The pages behind the frame are stand-ins: a page to type in and open a dialog from, and the
// two workflows lists Open workflow leads to. The real workflows section is exercised by its
// own suite; here only the address the alert sends the reader to matters.

import { StrictMode, useState, type ReactNode } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter, Route, Routes, useLocation, useParams } from 'react-router-dom';

import * as bootstrapStore from '../../../application/v2_ui/src/stores/bootstrapStore';
import * as notificationStore from '../../../application/v2_ui/src/stores/notificationStore';
import * as uiStore from '../../../application/v2_ui/src/stores/uiStore';
import * as userSettingsStore from '../../../application/v2_ui/src/stores/userSettingsStore';
import * as workflowAlertStore from '../../../application/v2_ui/src/stores/workflowAlertStore';
import * as appNavigation from '../../../application/v2_ui/src/lib/appNavigation';
import * as workflowAlertClaims from '../../../application/v2_ui/src/lib/workflowAlertClaims';
import * as workflowAlertMotion from '../../../application/v2_ui/src/lib/workflowAlertMotion';
import * as workflowAlertNotices from '../../../application/v2_ui/src/lib/workflowAlertNotices';
import * as workflowAlertRuntime from '../../../application/v2_ui/src/lib/useWorkflowAlertRuntime';
import { useNotificationRuntime } from '../../../application/v2_ui/src/lib/useNotificationRuntime';
import { useWorkflowAlertRuntime } from '../../../application/v2_ui/src/lib/useWorkflowAlertRuntime';
import { AppShell } from '../../../application/v2_ui/src/components/layout/AppShell';
import { Modal } from '../../../application/v2_ui/src/components/ui/Modal';
import type { NotificationCountChange } from '../../../application/v2_ui/src/stores/notificationStore';

function Runtime({ children }: { children: ReactNode }) {
    useNotificationRuntime(true);
    useWorkflowAlertRuntime(true);
    return <>{children}</>;
}

function CurrentRoute() {
    const { pathname, search } = useLocation();
    return (
        <output aria-label="Current route" data-current-route="" className="sr-only">
            {`${pathname}${search}`}
        </output>
    );
}

/** A page with somewhere to type and a dialog to open, as any page of the application has. */
function WorkPage() {
    const [dialogOpen, setDialogOpen] = useState(false);
    return (
        <div className="space-y-3 p-6">
            <h1 className="text-lg font-semibold text-text-1">Quarterly planning</h1>
            <textarea aria-label="Notes" rows={4} className="block w-full rounded-lg border border-edge p-2 text-text-1" />
            <button type="button" onClick={() => setDialogOpen(true)} className="rounded-lg border border-edge px-3 py-1.5">
                Open a dialog
            </button>
            {dialogOpen && (
                <Modal title="Share settings" onClose={() => setDialogOpen(false)}>
                    <p className="text-sm text-text-1">A dialog that has the reader&apos;s attention.</p>
                    <button type="button" onClick={() => setDialogOpen(false)}>Done</button>
                </Modal>
            )}
        </div>
    );
}

function WorkflowsPage() {
    const { groupId } = useParams();
    return <p className="p-6">{groupId ? `Workflows of group ${groupId}` : 'Your workflows'}</p>;
}

function Frame() {
    return (
        <div style={{ height: '100dvh' }}>
            <AppShell>
                <CurrentRoute />
                <Routes>
                    <Route path="/work" element={<WorkPage />} />
                    <Route path="/workspace/workflows" element={<WorkflowsPage />} />
                    <Route path="/groups/:groupId/workflows" element={<WorkflowsPage />} />
                    <Route path="/chat" element={<p className="p-6">Chat page</p>} />
                    <Route path="*" element={<p className="p-6">Another page</p>} />
                </Routes>
            </AppShell>
        </div>
    );
}

let root: Root | null = null;

function unmount(): void {
    root?.unmount();
    root = null;
}

function mount(path: string): void {
    unmount();
    const container = document.getElementById('root');
    if (!container) {
        throw new Error('Root container #root was not found in the harness page.');
    }
    root = createRoot(container);
    root.render(
        <StrictMode>
            <MemoryRouter initialEntries={[path]}>
                <Runtime>
                    <Frame />
                </Runtime>
            </MemoryRouter>
        </StrictMode>,
    );
}

// Every count read, as the workflow alert runtime hears it.
const countChanges: NotificationCountChange[] = [];
notificationStore.subscribeNotificationCount((change) => {
    countChanges.push(change);
});

declare global {
    interface Window {
        WorkflowAlertHarness: unknown;
    }
}

window.WorkflowAlertHarness = {
    mount,
    unmount,
    countChanges,
    stores: {
        bootstrap: bootstrapStore,
        notification: notificationStore,
        ui: uiStore,
        userSettings: userSettingsStore,
        workflowAlert: workflowAlertStore,
    },
    appNavigation,
    claims: workflowAlertClaims,
    motion: workflowAlertMotion,
    notices: workflowAlertNotices,
    runtime: workflowAlertRuntime,
};

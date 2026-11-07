// harness_entry.tsx
//
// Test-only harness entry (NOT application source) for ui_tests/test_v2_workflow_run_card.py.
//
// Mounts the real V2 frame -- AppShell with its chat list and notification bell, and the chat
// page -- in a memory router, with the notification runtime and the workflow run tracker running
// above it the way App.tsx runs them: both start only once the session has loaded, and the tracker
// only when the user can use the saved workflows a chat starts. Nothing in application/v2_ui/src is
// replaced; the test answers HTTP and fakes only the browser APIs a headless page cannot drive
// (Notification, visibility and focus).

import { StrictMode, type ReactNode } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';

import * as bootstrapStore from '../../../application/v2_ui/src/stores/bootstrapStore';
import * as chatStore from '../../../application/v2_ui/src/stores/chatStore';
import * as notificationStore from '../../../application/v2_ui/src/stores/notificationStore';
import * as orchestrationStore from '../../../application/v2_ui/src/stores/orchestrationStore';
import * as uiStore from '../../../application/v2_ui/src/stores/uiStore';
import * as userSettingsStore from '../../../application/v2_ui/src/stores/userSettingsStore';
import * as workflowRunTrackerStore from '../../../application/v2_ui/src/stores/workflowRunTrackerStore';
import * as replyEvents from '../../../application/v2_ui/src/lib/replyEvents';
import * as desktopNotifications from '../../../application/v2_ui/src/lib/desktopNotifications';
import * as appNavigation from '../../../application/v2_ui/src/lib/appNavigation';
import * as trackerHook from '../../../application/v2_ui/src/lib/useWorkflowRunTracker';
import { useNotificationRuntime } from '../../../application/v2_ui/src/lib/useNotificationRuntime';
import { useWorkflowRunTracker } from '../../../application/v2_ui/src/lib/useWorkflowRunTracker';
import { workflowRunTrackerShouldRun } from '../../../application/v2_ui/src/lib/workflowRunTracker';
import { AppShell } from '../../../application/v2_ui/src/components/layout/AppShell';
import { ChatPage } from '../../../application/v2_ui/src/pages/ChatPage';
import type { CompletedReply } from '../../../application/v2_ui/src/lib/replyEvents';

function Runtime({ children }: { children: ReactNode }) {
    const data = bootstrapStore.useBootstrapStore((state) => state.data);
    const error = bootstrapStore.useBootstrapStore((state) => state.error);
    const ready = Boolean(data) && !error;
    useNotificationRuntime(ready);
    useWorkflowRunTracker(ready && workflowRunTrackerShouldRun(data?.features));
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

/** Stands in for the Workflows page: it says which run a link asked it to open. */
function WorkflowsPlaceholder() {
    const { search } = useLocation();
    return <p className="p-6" data-workflows-page="">{`Workflows page ${search}`}</p>;
}

function Frame() {
    return (
        <div style={{ height: '100dvh' }}>
            <AppShell>
                <CurrentRoute />
                <Routes>
                    <Route path="/chat" element={<ChatPage />} />
                    <Route path="/workspace/workflows" element={<WorkflowsPlaceholder />} />
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

// Every finished reply announced, from the page's first moment, as the desktop notifier hears them.
const completedReplies: CompletedReply[] = [];
replyEvents.subscribeCompletedReplies((reply) => {
    completedReplies.push(reply);
});

declare global {
    interface Window {
        WorkflowRunTrackingHarness: unknown;
    }
}

window.WorkflowRunTrackingHarness = {
    mount,
    unmount,
    completedReplies,
    stores: {
        bootstrap: bootstrapStore,
        chat: chatStore,
        notification: notificationStore,
        orchestration: orchestrationStore,
        ui: uiStore,
        userSettings: userSettingsStore,
        workflowRunTracker: workflowRunTrackerStore,
    },
    tracker: trackerHook,
    replyEvents,
    desktopNotifications,
    appNavigation,
};

// harness_entry.tsx
//
// Test-only harness entry (NOT application source) for ui_tests/test_chat_workflow_results.py.
//
// Mounts the real chat page, the real run history of a personal and a group workflow, and the
// real workflow alert card host in a memory router, with the toaster, as the application
// frame does. Nothing in application/v2_ui/src is replaced; the test answers HTTP.
//
// The rail and the alert runtime belong to their own suite (test_v2_workflow_alert_notices.py).
// Here the alert card is shown straight from the store, so only what its actions do is tested.

import { StrictMode, useEffect } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import {
    MemoryRouter, Route, Routes, useLocation, useNavigate, useParams, type NavigateFunction,
} from 'react-router-dom';

import * as bootstrapStore from '../../../application/v2_ui/src/stores/bootstrapStore';
import * as chatStore from '../../../application/v2_ui/src/stores/chatStore';
import * as userSettingsStore from '../../../application/v2_ui/src/stores/userSettingsStore';
import * as workflowAlertStore from '../../../application/v2_ui/src/stores/workflowAlertStore';
import * as workflowAlertNotices from '../../../application/v2_ui/src/lib/workflowAlertNotices';
import { ChatPage } from '../../../application/v2_ui/src/pages/ChatPage';
import { WorkflowRunHistory } from '../../../application/v2_ui/src/components/workflows/WorkflowRunHistory';
import { WorkflowAlertCardHost } from '../../../application/v2_ui/src/components/notifications/WorkflowAlertCard';
import { Toaster } from '../../../application/v2_ui/src/components/ui/Toaster';

let routerNavigate: NavigateFunction | null = null;

/**
 * Lets the test move between pages inside one mounted router, the way the rail does, so
 * the stores and module state carry over exactly as they do in the application.
 */
function NavigatorBridge() {
    const navigateTo = useNavigate();
    useEffect(() => {
        routerNavigate = navigateTo;
        return () => {
            if (routerNavigate === navigateTo) {
                routerNavigate = null;
            }
        };
    }, [navigateTo]);
    return null;
}

function navigate(path: string): void {
    if (!routerNavigate) {
        throw new Error('The harness router is not mounted.');
    }
    routerNavigate(path);
}

function CurrentRoute() {
    const { pathname, search } = useLocation();
    return (
        <output aria-label="Current route" data-current-route="" className="sr-only">
            {`${pathname}${search}`}
        </output>
    );
}

/** A personal workflow's run history, as the workflows section shows it. */
function PersonalRuns() {
    return (
        <section aria-label="Weekly digest runs" className="p-4">
            <h1 className="pb-2 text-lg font-semibold text-text-1">Your workflows</h1>
            <WorkflowRunHistory scope={{ type: 'personal' }} workflowId="wf-digest" />
        </section>
    );
}

/** A group workflow's run history. */
function GroupRuns() {
    const { groupId = '' } = useParams();
    return (
        <section aria-label="Team digest runs" className="p-4">
            <h1 className="pb-2 text-lg font-semibold text-text-1">Workflows of group {groupId}</h1>
            <WorkflowRunHistory scope={{ type: 'group', groupId }} workflowId="wf-team" />
        </section>
    );
}

function Frame() {
    return (
        <div className="flex min-h-0 min-w-0 flex-col" style={{ height: '100dvh' }}>
            <NavigatorBridge />
            <CurrentRoute />
            <Routes>
                <Route path="/chat" element={<ChatPage />} />
                <Route path="/workspace/workflows" element={<PersonalRuns />} />
                <Route path="/groups/:groupId/workflows" element={<GroupRuns />} />
                <Route path="*" element={<p className="p-6">Another page</p>} />
            </Routes>
            <WorkflowAlertCardHost />
            <Toaster />
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
                <Frame />
            </MemoryRouter>
        </StrictMode>,
    );
}

/** Put these alerts on the card, as a tab that won them and was opened would. */
function showAlertCard(rawAlerts: unknown[]): number {
    workflowAlertStore.resetWorkflowAlertsForLab();
    const alerts = rawAlerts
        .map((raw) => workflowAlertNotices.readWorkflowAlert(raw))
        .filter((alert): alert is workflowAlertNotices.WorkflowAlert => alert !== null);
    workflowAlertStore.useWorkflowAlertStore.setState({
        entries: workflowAlertNotices.groupWorkflowAlerts(alerts),
        phase: 'card',
        cardIndex: 0,
        growFrom: null,
        suspended: false,
    });
    return alerts.length;
}

declare global {
    interface Window {
        WorkflowResultsHarness: unknown;
    }
}

window.WorkflowResultsHarness = {
    mount,
    unmount,
    navigate,
    showAlertCard,
    stores: {
        bootstrap: bootstrapStore,
        chat: chatStore,
        userSettings: userSettingsStore,
        workflowAlert: workflowAlertStore,
    },
    notices: workflowAlertNotices,
};

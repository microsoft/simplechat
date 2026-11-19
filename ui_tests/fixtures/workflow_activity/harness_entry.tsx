// harness_entry.tsx
//
// Test-only harness entry (NOT application source) for ui_tests/test_v2_workflow_activity.py.
//
// Mounts the real V2 Workflow Activity page, the chat page (for its header's activity link), and
// two small probes that draw a workflow's run history and its header link, in a memory router.
// The router's `/chat`, `/workspace/workflows` and `/groups/:id/workflows` routes only name
// where a link led, so a test can read the current route. `navigate` and `go` move inside the
// mounted router the way a notification and the Back button do, so a test can leave a run for
// another while the page stays mounted. Nothing in application/v2_ui/src is replaced; the test
// answers HTTP and seeds the stores the pages read.

import { StrictMode, useEffect, type ReactNode } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import {
    MemoryRouter, Route, Routes, useLocation, useNavigate, useSearchParams, type NavigateFunction,
} from 'react-router-dom';

import * as bootstrapStore from '../../../application/v2_ui/src/stores/bootstrapStore';
import * as chatStore from '../../../application/v2_ui/src/stores/chatStore';
import * as uiStore from '../../../application/v2_ui/src/stores/uiStore';
import { ChatPage } from '../../../application/v2_ui/src/pages/ChatPage';
import { WorkflowActivityPage } from '../../../application/v2_ui/src/pages/WorkflowActivityPage';
import { WorkflowRunHistory } from '../../../application/v2_ui/src/components/workflows/WorkflowRunHistory';
import { WorkflowActivityLink } from '../../../application/v2_ui/src/components/workflowActivity/WorkflowActivityLinks';
import type { WorkflowDefinition, WorkflowScope } from '../../../application/v2_ui/src/lib/workflowEditor';

let routerNavigate: NavigateFunction | null = null;

// Lets a test move inside the mounted router the way a link, the Back button or a notification
// does, so the page stays mounted and only its address changes.
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

function mountedRouter(): NavigateFunction {
    if (!routerNavigate) {
        throw new Error('The harness router is not mounted.');
    }
    return routerNavigate;
}

function navigate(to: string): void {
    mountedRouter()(to);
}

function go(delta: number): void {
    mountedRouter()(delta);
}

function CurrentRoute() {
    const { pathname, search } = useLocation();
    return (
        <output aria-label="Current route" data-current-route="" className="sr-only">
            {`${pathname}${search}`}
        </output>
    );
}

function scopeFromQuery(params: URLSearchParams): WorkflowScope {
    const groupId = params.get('groupId');
    return groupId ? { type: 'group', groupId } : { type: 'personal' };
}

// A workflow's run history, as the Workflows section draws it, for the workflow it names.
function RunHistoryProbe() {
    const [params] = useSearchParams();
    return (
        <div className="p-4">
            <WorkflowRunHistory scope={scopeFromQuery(params)} workflowId={params.get('workflowId') ?? 'wf-weekly'} />
        </div>
    );
}

// The workflow's own header link, for the workflow record the test put on the harness.
function WorkflowLinkProbe() {
    const [params] = useSearchParams();
    const workflow = (window.ActivityHarness?.workflow ?? {}) as WorkflowDefinition;
    return (
        <div className="p-4">
            <WorkflowActivityLink scope={scopeFromQuery(params)} workflow={workflow} />
        </div>
    );
}

function Frame() {
    return (
        <div className="flex min-w-0 flex-col" style={{ height: '100dvh' }}>
            <NavigatorBridge />
            <CurrentRoute />
            <div className="min-h-0 flex-1">
                <Routes>
                    <Route path="/workflow-activity" element={<WorkflowActivityPage />} />
                    <Route path="/chat" element={<ChatPage />} />
                    <Route path="/probe/run-history" element={<RunHistoryProbe />} />
                    <Route path="/probe/workflow-link" element={<WorkflowLinkProbe />} />
                    <Route path="*" element={<p className="p-6">Another page</p>} />
                </Routes>
            </div>
        </div>
    );
}

let root: Root | null = null;

function unmount(): void {
    root?.unmount();
    root = null;
}

function mount(path: string, options: { strict?: boolean } = {}): void {
    unmount();
    const container = document.getElementById('root');
    if (!container) {
        throw new Error('Root container #root was not found in the harness page.');
    }
    root = createRoot(container);
    const frame: ReactNode = (
        <MemoryRouter initialEntries={[path]}>
            <Frame />
        </MemoryRouter>
    );
    root.render(options.strict ? <StrictMode>{frame}</StrictMode> : frame);
}

declare global {
    interface Window {
        ActivityHarness: {
            mount: typeof mount;
            unmount: typeof unmount;
            navigate: typeof navigate;
            go: typeof go;
            workflow?: unknown;
            stores: {
                bootstrap: typeof bootstrapStore;
                chat: typeof chatStore;
                ui: typeof uiStore;
            };
        };
    }
}

window.ActivityHarness = {
    mount,
    unmount,
    navigate,
    go,
    stores: { bootstrap: bootstrapStore, chat: chatStore, ui: uiStore },
};

// harness_entry.tsx
//
// Test-only harness entry (NOT application source) for ui_tests/test_v2_notifications_page.py.
//
// Mounts the real V2 frame -- AppShell with its rail, bell, bell panel and account menu -- around
// the real Notifications page, in a browser router with the `/v2` base the application uses, so
// the address bar, Back and Forward behave as they do in production. The notification runtime
// runs above the frame the way App.tsx runs it. The page's own route is the only route that is
// real: any other page is a placeholder, because what the test needs from it is to have arrived.
// Nothing in application/v2_ui/src is replaced; the test answers HTTP only.

import { StrictMode, type ReactNode } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { BrowserRouter, Route, Routes, useLocation } from 'react-router-dom';

import * as bootstrapStore from '../../../application/v2_ui/src/stores/bootstrapStore';
import * as notificationStore from '../../../application/v2_ui/src/stores/notificationStore';
import * as uiStore from '../../../application/v2_ui/src/stores/uiStore';
import * as userSettingsStore from '../../../application/v2_ui/src/stores/userSettingsStore';
import { useNotificationRuntime } from '../../../application/v2_ui/src/lib/useNotificationRuntime';
import { AppShell } from '../../../application/v2_ui/src/components/layout/AppShell';
import { NotificationsPage } from '../../../application/v2_ui/src/pages/NotificationsPage';

function Runtime({ children }: { children: ReactNode }) {
    useNotificationRuntime(true);
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

function Frame() {
    return (
        <div style={{ height: '100dvh' }}>
            <AppShell>
                <CurrentRoute />
                <Routes>
                    <Route path="/notifications" element={<NotificationsPage />} />
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

function mount(): void {
    unmount();
    const container = document.getElementById('root');
    if (!container) {
        throw new Error('Root container #root was not found in the harness page.');
    }
    root = createRoot(container);
    root.render(
        <StrictMode>
            <BrowserRouter basename="/v2">
                <Runtime>
                    <Frame />
                </Runtime>
            </BrowserRouter>
        </StrictMode>,
    );
}

// Every count read, recorded from the page's first moment, as the workflow alert pop-ups would hear it.
const countChanges: notificationStore.NotificationCountChange[] = [];
notificationStore.subscribeNotificationCount((change) => {
    countChanges.push(change);
});

declare global {
    interface Window {
        NotificationsPageHarness: unknown;
    }
}

window.NotificationsPageHarness = {
    mount,
    unmount,
    countChanges,
    stores: {
        bootstrap: bootstrapStore,
        notification: notificationStore,
        ui: uiStore,
        userSettings: userSettingsStore,
    },
};

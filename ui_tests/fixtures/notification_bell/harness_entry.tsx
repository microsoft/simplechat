// harness_entry.tsx
//
// Test-only harness entry (NOT application source) for ui_tests/test_v2_notifications_bell.py.
//
// Mounts the real V2 frame -- AppShell with its rail and notification bell, the chat page and
// the preferences tab -- in a memory router, with the notification runtime running above it
// the way App.tsx runs it: as the parent of the frame, so the pages' own effects run first.
// Nothing in application/v2_ui/src is replaced; the test answers HTTP and fakes only the
// browser APIs a headless page cannot drive (Notification, visibility and focus).

import { StrictMode, type ReactNode } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';

import * as bootstrapStore from '../../../application/v2_ui/src/stores/bootstrapStore';
import * as chatStore from '../../../application/v2_ui/src/stores/chatStore';
import * as notificationStore from '../../../application/v2_ui/src/stores/notificationStore';
import * as uiStore from '../../../application/v2_ui/src/stores/uiStore';
import * as userSettingsStore from '../../../application/v2_ui/src/stores/userSettingsStore';
import * as replyEvents from '../../../application/v2_ui/src/lib/replyEvents';
import * as desktopNotifications from '../../../application/v2_ui/src/lib/desktopNotifications';
import * as appNavigation from '../../../application/v2_ui/src/lib/appNavigation';
import { useNotificationRuntime } from '../../../application/v2_ui/src/lib/useNotificationRuntime';
import { AppShell } from '../../../application/v2_ui/src/components/layout/AppShell';
import { ChatPage } from '../../../application/v2_ui/src/pages/ChatPage';
import { PreferencesTab } from '../../../application/v2_ui/src/components/settings/PreferencesTab';
import type { NotificationCountChange } from '../../../application/v2_ui/src/stores/notificationStore';

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
                    <Route path="/chat" element={<ChatPage />} />
                    <Route
                        path="/settings"
                        element={(
                            <div className="overflow-y-auto p-6">
                                <PreferencesTab />
                            </div>
                        )}
                    />
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

// Every count read, recorded from the page's first moment, as Track N2's pop-ups would hear it.
const countChanges: NotificationCountChange[] = [];
notificationStore.subscribeNotificationCount((change) => {
    countChanges.push(change);
});

declare global {
    interface Window {
        NotificationHarness: unknown;
    }
}

window.NotificationHarness = {
    mount,
    unmount,
    countChanges,
    stores: {
        bootstrap: bootstrapStore,
        chat: chatStore,
        notification: notificationStore,
        ui: uiStore,
        userSettings: userSettingsStore,
    },
    replyEvents,
    desktopNotifications,
    appNavigation,
};

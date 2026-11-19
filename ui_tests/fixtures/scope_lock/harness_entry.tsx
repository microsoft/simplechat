// harness_entry.tsx
//
// Test-only harness entry (NOT application source) for ui_tests/test_v2_scope_lock.py.
//
// Mounts the real V2 chat page -- its header, thread, composer and Documents picker, and the
// conversation details it opens -- in a memory router, with the toaster beside it as the app shell
// draws it. Nothing in application/v2_ui/src is replaced; the test answers HTTP and seeds the
// stores, so the scope lock control, its dialog, the optimistic write and the rollback all run as
// they do in the application.

import { StrictMode } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter, Route, Routes } from 'react-router-dom';

import * as bootstrapStore from '../../../application/v2_ui/src/stores/bootstrapStore';
import * as chatStore from '../../../application/v2_ui/src/stores/chatStore';
import * as collaborationStore from '../../../application/v2_ui/src/stores/collaborationStore';
import * as scopeLockStore from '../../../application/v2_ui/src/stores/scopeLockStore';
import * as uiStore from '../../../application/v2_ui/src/stores/uiStore';
import * as userSettingsStore from '../../../application/v2_ui/src/stores/userSettingsStore';
import { ChatPage } from '../../../application/v2_ui/src/pages/ChatPage';
import { Toaster } from '../../../application/v2_ui/src/components/ui/Toaster';

function Frame() {
    return (
        <div style={{ height: '100dvh' }} className="flex flex-col">
            <main className="flex min-h-0 min-w-0 flex-1 flex-col">
                <Routes>
                    <Route path="/chat" element={<ChatPage />} />
                    <Route path="*" element={<p className="p-6">Another page</p>} />
                </Routes>
            </main>
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

declare global {
    interface Window {
        ScopeLockHarness: unknown;
    }
}

window.ScopeLockHarness = {
    mount,
    unmount,
    stores: {
        bootstrap: bootstrapStore,
        chat: chatStore,
        collaboration: collaborationStore,
        scopeLock: scopeLockStore,
        ui: uiStore,
        userSettings: userSettingsStore,
    },
};

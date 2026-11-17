// harness_entry.tsx
//
// Test-only harness entry (NOT application source) for ui_tests/test_v2_classic_links.py.
//
// Mounts the real V2 frame -- AppShell with its rail and account menu -- in a browser router with the
// `/v2` base the application uses, with the real fragment translation hook mounted the way App.tsx
// mounts it, so the address bar, Back and Forward behave as they do in production. Every page is a
// placeholder, because what the test needs from a page is to have arrived. Nothing in
// application/v2_ui/src is replaced; the test answers HTTP only.

import { StrictMode } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { BrowserRouter, Route, Routes, useLocation } from 'react-router-dom';

import * as bootstrapStore from '../../../application/v2_ui/src/stores/bootstrapStore';
import * as chatStore from '../../../application/v2_ui/src/stores/chatStore';
import * as uiStore from '../../../application/v2_ui/src/stores/uiStore';
import * as userSettingsStore from '../../../application/v2_ui/src/stores/userSettingsStore';
import { AppShell } from '../../../application/v2_ui/src/components/layout/AppShell';
import { useClassicFragmentTranslation } from '../../../application/v2_ui/src/lib/useClassicFragmentTranslation';

function FragmentTranslation() {
    useClassicFragmentTranslation();
    return null;
}

function CurrentAddress() {
    const { pathname, search, hash } = useLocation();
    return (
        <output aria-label="Current address" data-current-address="" className="sr-only">
            {`${pathname}${search}${hash}`}
        </output>
    );
}

function Frame() {
    return (
        <div style={{ height: '100dvh' }}>
            <FragmentTranslation />
            <AppShell>
                <CurrentAddress />
                <Routes>
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
                <Frame />
            </BrowserRouter>
        </StrictMode>,
    );
}

declare global {
    interface Window {
        ClassicLinksHarness: unknown;
    }
}

window.ClassicLinksHarness = {
    mount,
    unmount,
    stores: {
        bootstrap: bootstrapStore,
        chat: chatStore,
        ui: uiStore,
        userSettings: userSettingsStore,
    },
};

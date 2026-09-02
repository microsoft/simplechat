// App.tsx
// Loads bootstrap, then renders the shell and routes.

import { useEffect } from 'react';
import { Navigate, Route, Routes, useLocation } from 'react-router-dom';
import { LogIn, TriangleAlert } from 'lucide-react';
import { AppShell } from './components/layout/AppShell';
import { GlassPanel, Skeleton } from './components/ui/primitives';
import { ErrorBoundary } from './components/ui/ErrorBoundary';
import { useBootstrapStore } from './stores/bootstrapStore';
import { useUserSettingsStore } from './stores/userSettingsStore';
import { initializeTheme } from './stores/uiStore';
import { ChatPage } from './pages/ChatPage';
import { AdminSettingsPage } from './pages/AdminSettingsPage';
import { SettingsPage } from './pages/SettingsPage';
import { WorkspacePage } from './pages/WorkspacePage';
import { PlaceholderPage } from './pages/PlaceholderPage';

function BootScreen() {
    return (
        <div className="flex h-full items-center justify-center p-6">
            <div className="w-full max-w-sm space-y-3">
                <Skeleton className="h-10 w-40" />
                <Skeleton className="h-4 w-full" />
                <Skeleton className="h-4 w-3/4" />
                <span className="sr-only">Loading SimpleChat</span>
            </div>
        </div>
    );
}

function BootError({ message, authExpired }: { message: string; authExpired: boolean }) {
    return (
        <div className="flex h-full items-center justify-center p-6">
            <GlassPanel edge className="max-w-md p-6">
                <div className="flex items-start gap-3">
                    {authExpired ? (
                        <LogIn size={20} className="mt-0.5 shrink-0 text-accent" />
                    ) : (
                        <TriangleAlert size={20} className="mt-0.5 shrink-0 text-danger" />
                    )}
                    <div>
                        <h1 className="font-semibold text-text-1">
                            {authExpired ? 'Your session has expired' : 'Could not start SimpleChat'}
                        </h1>
                        <p className="mt-1 text-sm text-text-3">
                            {authExpired
                                ? 'Sign in again to continue where you left off.'
                                : message}
                        </p>
                        <a
                            href={authExpired ? '/login' : '/chats'}
                            className="mt-4 inline-block rounded-xl bg-accent px-4 py-2 text-sm font-medium text-on-accent transition-colors hover:bg-accent-hover"
                        >
                            {authExpired ? 'Sign in' : 'Open the classic interface'}
                        </a>
                    </div>
                </div>
            </GlassPanel>
        </div>
    );
}

export function App() {
    const { data, loading, error, authExpired, load } = useBootstrapStore();
    const loadUserSettings = useUserSettingsStore((state) => state.load);
    const location = useLocation();

    useEffect(() => {
        initializeTheme();
        void load();
        // Loaded at startup rather than when the settings page opens, because preferences
        // shape the chat interface itself — the conversation list reads one of them.
        // Advisory: a failure leaves defaults in place rather than blocking the app.
        void loadUserSettings();
    }, [load, loadUserSettings]);

    useEffect(() => {
        const title = data?.branding?.app_title;
        if (title) {
            document.title = title;
        }
    }, [data]);

    if (loading) {
        return <BootScreen />;
    }

    if (error || !data) {
        return <BootError message={error ?? 'Unknown error'} authExpired={authExpired} />;
    }

    return (
        <AppShell>
            {/* Scoped to the content pane so a failed page never takes the rail with it,
            and keyed on the route so navigating away clears the error. */}
            <ErrorBoundary resetKey={location.pathname}>
            <Routes>
                <Route path="/" element={<Navigate to="/chat" replace />} />
                <Route path="/chat" element={<ChatPage />} />
                <Route path="/workspace" element={<WorkspacePage />} />
                <Route path="/settings" element={<SettingsPage />} />
                <Route path="/admin" element={<AdminSettingsPage />} />
                <Route
                    path="/agents"
                    element={
                        <PlaceholderPage
                            title="Agents"
                            description="The agent catalogue has not been rebuilt in the V2 interface yet. Agents you can access are still selectable from the chat composer."
                            classicHref="/agents"
                            classicLabel="Open the agent catalogue"
                        />
                    }
                />
                <Route
                    path="/groups"
                    element={
                        <PlaceholderPage
                            title="Group workspaces"
                            description="Group workspace management has not been rebuilt in the V2 interface yet."
                            classicHref="/group_workspaces"
                            classicLabel="Open group workspaces"
                        />
                    }
                />
                <Route
                    path="/public"
                    element={
                        <PlaceholderPage
                            title="Public workspaces"
                            description="Public workspace browsing has not been rebuilt in the V2 interface yet."
                            classicHref="/public_directory"
                            classicLabel="Open public workspaces"
                        />
                    }
                />
                <Route path="*" element={<Navigate to="/chat" replace />} />
                </Routes>
            </ErrorBoundary>
        </AppShell>
    );
}

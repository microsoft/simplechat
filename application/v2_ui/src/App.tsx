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
import { initializeTheme, hydrateUiPreferences } from './stores/uiStore';
import { startImageApprovalTracking } from './lib/imageProposalResume';
import { ChatPage } from './pages/ChatPage';
import { HomePage } from './pages/HomePage';
import { AdminSettingsPage } from './pages/AdminSettingsPage';
import { SettingsPage } from './pages/SettingsPage';
import { WorkspacePage } from './pages/workspace/WorkspacePage';
import { PlaceholderPage } from './pages/PlaceholderPage';
import { GroupAgentDelegationPage } from './pages/GroupAgentDelegationPage';

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
    const refreshBootstrap = useBootstrapStore((state) => state.refresh);
    const loadUserSettings = useUserSettingsStore((state) => state.load);
    const fontSize = useUserSettingsStore(
        (state) => (state.settings.fontSizePreference as string) || 'm',
    );
    const location = useLocation();

    useEffect(() => {
        initializeTheme();
        void load();
        // Loaded at startup rather than when the settings page opens, because preferences
        // shape the chat interface itself — the conversation list reads one of them.
        // Advisory: a failure leaves defaults in place rather than blocking the app.
        void loadUserSettings().then(() => {
            hydrateUiPreferences(useUserSettingsStore.getState().settings);
        });
        // An image approval survives the page that started it, so this runs in the shell
        // rather than in the chat page: a reload can land anywhere, and the approval still
        // has to be picked back up and reported.
        startImageApprovalTracking();
    }, [load, loadUserSettings]);

    /**
     * Re-read the payload when the tab comes back to the front.
     *
     * Bootstrap decides what the interface offers -- which capabilities the composer draws,
     * whether orchestration exists at all -- and it was otherwise fetched once at startup.
     * The V2 admin surface refreshes it after its own saves, but the classic Admin Settings
     * page is a different page in a different tab and cannot reach into this one. So the
     * ordinary way to enable a feature left an open chat tab insisting the feature did not
     * exist, with nothing on screen to explain why, until somebody thought to reload.
     *
     * Refreshing on re-focus closes that gap for every setting at once rather than for
     * whichever one is being complained about. `refresh` is advisory -- it leaves the page
     * alone if the request fails, and never shows the boot screen -- so the worst case of a
     * spurious wake-up is one wasted request.
     */
    useEffect(() => {
        const onVisible = () => {
            if (document.visibilityState === 'visible') {
                void refreshBootstrap();
            }
        };
        document.addEventListener('visibilitychange', onVisible);
        // Also on window focus: switching between two windows of the same browser does not
        // always change visibility, and moving from the admin page to the chat page is
        // exactly that journey.
        window.addEventListener('focus', onVisible);
        return () => {
            document.removeEventListener('visibilitychange', onVisible);
            window.removeEventListener('focus', onVisible);
        };
    }, [refreshBootstrap]);

    useEffect(() => {
        const title = data?.branding?.app_title;
        if (title) {
            document.title = title;
        }
    }, [data]);

    /**
     * Keep the tab icon in step with the stored favicon.
     *
     * The SPA shell is a build artefact, so the server rewrites its icon link on the way
     * out. That covers a page load but not an upload made in this session: the static file
     * keeps a stable name, so only the version in the URL tells the browser to fetch it
     * again.
     */
    useEffect(() => {
        const faviconUrl = data?.branding?.favicon_url;
        if (!faviconUrl) {
            return;
        }
        const link = document.querySelector<HTMLLinkElement>('link[rel="icon"]');
        if (link && link.getAttribute('href') !== faviconUrl) {
            link.setAttribute('href', faviconUrl);
        }
    }, [data]);

    // Applied from the stored preference on every load. The attribute name and its scale
    // are shared with the classic interface, so a size chosen in either applies to both.
    useEffect(() => {
        document.documentElement.dataset.fontSize = fontSize;
    }, [fontSize]);

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
                <Route path="/" element={<HomePage />} />
                <Route path="/chat" element={<ChatPage />} />
                <Route path="/workspace" element={<WorkspacePage />} />
                {/* Sections are real paths rather than a query parameter, so a link to one
                    reads as what it is and survives being shared. */}
                <Route path="/workspace/:section" element={<WorkspacePage />} />
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
                    element={<GroupAgentDelegationPage />}
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
                <Route path="*" element={<Navigate to="/" replace />} />
                </Routes>
            </ErrorBoundary>
        </AppShell>
    );
}

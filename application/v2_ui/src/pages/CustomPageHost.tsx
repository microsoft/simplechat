// CustomPageHost.tsx
// A custom page shown inside V2, with the navigation rail still on screen.
//
// Custom pages are trusted deployment content: static HTML, CSS and JavaScript, or a
// Python-backed template, rendered by the server at `/custom/<slug>`. They cannot be written
// again as React pages, so this page frames the copy the server renders without the classic
// navigation, `/custom/<slug>?embed=1`. The route is `/v2/custom/<slug>`, and the page has to be
// in the signed-in user's navigation list, which the server has already filtered by role and by
// whether the page is enabled. Anything else is a "Page not available" state, not a frame.
//
// A page that cannot or should not be framed gets a short explanation and a link that opens it
// in its own tab: one a Python extension has not declared embeddable, one whose metadata asks
// for its own tab, and any page when this interface is hosted on a different origin than the
// server, where the frame would be cross-origin. That link is the page's classic address.
//
// A framed page has its own two links to a tab of its own, the header action and the one on the
// failure panel. Both open the chrome-less document, `/custom/<slug>?embed=1`, and neither opens
// the classic address: once the modern interface is selected the server sends `/custom/<slug>`
// for a page V2 can host to this very route, so that link would open a second host and, from the
// failure panel, load the same failing frame again. `embed=1` is never redirected, so the new tab
// shows the page by itself with a way back, or the real error when it cannot be shown.
//
// A frame's `load` event also fires for a 403, a 404 and a server error page, so it cannot say
// that the page rendered. The page tells the host itself with a message sent while it is being
// parsed. The frame stays hidden behind a loading panel until that message arrives, and behind
// a failure panel if it does not (see lib/customPageEmbed). A page that reports late replaces the
// failure panel on its own, so a slow server is not shown as a broken one.

import { useCallback, useEffect, useLayoutEffect, useReducer, useRef, useState, type ReactNode } from 'react';
import { Link, useParams } from 'react-router-dom';
import { clsx } from 'clsx';
import { ExternalLink, FileQuestion, TriangleAlert } from 'lucide-react';
import { PageHeader } from '../components/layout/PageHeader';
import type { HeaderActionItems } from '../components/layout/HeaderActions';
import { EmptyState, GlassButton, Skeleton } from '../components/ui/primitives';
import { useBootstrapStore } from '../stores/bootstrapStore';
import { useUiStore } from '../stores/uiStore';
import { API_BASE, apiUrl } from '../lib/apiClient';
import {
    CUSTOM_PAGE_LOAD_TIMEOUT_MS,
    CUSTOM_PAGE_READY_GRACE_MS,
    customPageThemeMessage,
    isCustomPageReadyMessage,
    nextCustomPageFrameStatus,
    resolveCustomPageHost,
    safeCustomPageEmbedSrc,
    safeCustomPageStandaloneHref,
    safeCustomPageUrl,
} from '../lib/customPageEmbed';
import type { CustomPageNavItem } from '../lib/types';

/**
 * What the frame is allowed to do.
 *
 * This is a guard rail, not a security boundary, and it is chosen with that in mind. The page is
 * trusted same-origin deployment code that calls its own `/api/custom/...` operations with the
 * user's session, so it needs `allow-scripts` and `allow-same-origin`, and a page with both can
 * lift the rest of its own sandbox by reloading itself. What the flags still do is stop a page
 * by accident: without a top-navigation flag a stray `target="_top"` link or a script cannot
 * replace the whole application, and the pointer-lock and presentation capabilities are never
 * granted. Forms, popups (which leave the sandbox, so a page opened from a link is not confined),
 * downloads and dialogs are what an ordinary page does, so they stay on.
 *
 * The real controls are elsewhere: the server renders the embed document only for an
 * authorised request and frames it for this origin alone (`X-Frame-Options: SAMEORIGIN` and a
 * `frame-ancestors 'self'` policy), and every message between the two documents is checked for
 * its origin and sender.
 */
const FRAME_SANDBOX = [
    'allow-scripts',
    'allow-same-origin',
    'allow-forms',
    'allow-popups',
    'allow-popups-to-escape-sandbox',
    'allow-downloads',
    'allow-modals',
].join(' ');

const LINK_BUTTON_CLASS =
    'inline-flex items-center gap-2 rounded-xl bg-accent px-4 py-2 text-sm font-medium text-on-accent transition-colors hover:bg-accent-hover';
/** The same link beside a primary button, where it should not compete with it. */
const SECONDARY_LINK_BUTTON_CLASS =
    'glass-flat inline-flex items-center gap-2 rounded-xl px-4 py-2 text-sm font-medium text-text-1 transition-colors hover:bg-surface-2';

/** Why a page is not framed, in the words the reader sees. */
const NEW_TAB_REASONS = {
    'own-tab': 'Your administrators set this page to open in its own tab.',
    'not-embeddable':
        'This page is built for the classic interface and cannot be shown inside this one. Open it in its own tab to use it.',
    'cross-origin':
        'This interface is hosted separately from the page, so it cannot be shown here. Open it in its own tab to use it.',
} as const;

function HostFrame({ title, actions, children }: {
    title: string;
    actions?: HeaderActionItems;
    children: ReactNode;
}) {
    return (
        <div className="flex h-full min-h-0 flex-col">
            <PageHeader title={title} actions={actions} />
            {children}
        </div>
    );
}

function UnavailableCustomPage() {
    return (
        <HostFrame title="Page not available">
            <div className="min-h-0 flex-1 overflow-y-auto">
                <EmptyState
                    icon={<FileQuestion size={28} />}
                    title="This page is not available"
                    description="It may have been removed or switched off, or your account may not have access to it."
                    action={
                        <Link to="/" className={LINK_BUTTON_CLASS}>
                            Go to home
                        </Link>
                    }
                />
            </div>
        </HostFrame>
    );
}

function NewTabCustomPage({ page, reason }: {
    page: CustomPageNavItem;
    reason: keyof typeof NEW_TAB_REASONS;
}) {
    // The classic address is right for these pages: the server's classic-to-V2 redirect leaves a
    // page that asks for its own tab, or that is not embeddable, alone. When this interface is on
    // another origin the link leaves for the server's origin, which decides for itself.
    const newTabHref = apiUrl(safeCustomPageUrl(page.slug));

    return (
        <HostFrame title={page.label}>
            <div className="min-h-0 flex-1 overflow-y-auto">
                <EmptyState
                    icon={<ExternalLink size={28} />}
                    title={`${page.label} opens in a new tab`}
                    description={NEW_TAB_REASONS[reason]}
                    action={
                        <a href={newTabHref} target="_blank" rel="noopener noreferrer" className={LINK_BUTTON_CLASS}>
                            Open in a new tab
                            <ExternalLink size={15} aria-hidden="true" />
                        </a>
                    }
                />
            </div>
        </HostFrame>
    );
}

function EmbeddedCustomPage({ page }: { page: CustomPageNavItem }) {
    const theme = useUiStore((state) => state.theme);
    const [status, dispatch] = useReducer(nextCustomPageFrameStatus, 'loading');
    // The frame is remounted for a retry, so a fresh request is made rather than a reload of a
    // document that may be an error page.
    const [attempt, setAttempt] = useState(0);
    const [loaded, setLoaded] = useState(false);
    const frameRef = useRef<HTMLIFrameElement>(null);
    const afterFrameRef = useRef<HTMLSpanElement>(null);
    const themeRef = useRef(theme);
    themeRef.current = theme;

    const frameSrc = safeCustomPageEmbedSrc(page.slug);
    // The same chrome-less document on its own, not the classic address: in the modern interface
    // the server sends `/custom/<slug>` back to this page, and for a page that failed to load that
    // would only reopen the failing frame. `embed=1` is never redirected (see lib/customPageEmbed).
    // A path on this site, like the frame's: this component only renders when V2 and the server
    // share an origin.
    const newTabHref = safeCustomPageStandaloneHref(page.slug);

    const sendTheme = useCallback(() => {
        frameRef.current?.contentWindow?.postMessage(
            customPageThemeMessage(themeRef.current),
            window.location.origin,
        );
    }, []);

    // A layout effect, so the listener exists in the same task that inserts the frame. The page
    // sends its message while it is being parsed, and nothing else may run between the two.
    useLayoutEffect(() => {
        const onMessage = (event: MessageEvent) => {
            if (!isCustomPageReadyMessage(event, frameRef.current?.contentWindow, window.location.origin)) {
                return;
            }
            dispatch('ready');
            // The page applies the theme it read from storage until told otherwise, which is
            // only right when both interfaces last agreed on it.
            sendTheme();
        };
        window.addEventListener('message', onMessage);
        return () => window.removeEventListener('message', onMessage);
    }, [sendTheme]);

    // The theme the reader chooses in V2 while a page is open reaches the page as it happens.
    useEffect(() => {
        if (status === 'ready') {
            sendTheme();
        }
    }, [theme, status, sendTheme]);

    useEffect(() => {
        if (status !== 'loading') {
            return undefined;
        }
        // Once the frame has loaded the page has only to say so, which it does while parsing.
        const delay = loaded ? CUSTOM_PAGE_READY_GRACE_MS : CUSTOM_PAGE_LOAD_TIMEOUT_MS;
        const timer = window.setTimeout(() => dispatch('timeout'), delay);
        return () => window.clearTimeout(timer);
    }, [status, loaded, attempt]);

    const retry = () => {
        setLoaded(false);
        setAttempt((value) => value + 1);
        dispatch('retry');
    };

    return (
        <HostFrame
            title={page.label}
            actions={[
                {
                    id: 'open-in-new-tab',
                    label: 'Open in a new tab',
                    icon: <ExternalLink size={15} />,
                    variant: 'subtle',
                    iconOnly: true,
                    testId: 'custom-page-open-in-new-tab',
                    onClick: () => window.open(newTabHref, '_blank', 'noopener,noreferrer'),
                },
            ]}
        >
            <div className="relative min-h-0 flex-1 bg-surface-solid" data-testid="custom-page-pane">
                {/* Two ways past the frame for a keyboard or screen reader user. Tabbing walks
                    through every control the page has, which is a long way when it has many. */}
                <button
                    type="button"
                    onClick={() => frameRef.current?.focus()}
                    className="sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-3 focus:z-30 focus:rounded-lg focus:bg-accent focus:px-3 focus:py-1.5 focus:text-sm focus:font-medium focus:text-on-accent"
                >
                    Skip to {page.label}
                </button>
                <button
                    type="button"
                    onClick={() => afterFrameRef.current?.focus()}
                    className="sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-3 focus:z-30 focus:rounded-lg focus:bg-accent focus:px-3 focus:py-1.5 focus:text-sm focus:font-medium focus:text-on-accent"
                >
                    Skip past {page.label}
                </button>

                <iframe
                    key={attempt}
                    ref={frameRef}
                    title={page.label}
                    src={frameSrc}
                    sandbox={FRAME_SANDBOX}
                    referrerPolicy="same-origin"
                    allow=""
                    onLoad={() => setLoaded(true)}
                    data-testid="custom-page-frame"
                    // Hidden until the page reports in, which also takes an error page out of
                    // the tab order and the accessibility tree.
                    className={clsx(
                        'absolute inset-0 h-full w-full border-0',
                        status !== 'ready' && 'invisible',
                    )}
                />

                {status === 'loading' && (
                    <div
                        role="status"
                        data-testid="custom-page-loading"
                        className="absolute inset-0 z-10 bg-surface-solid p-6"
                    >
                        <div className="mx-auto w-full max-w-3xl space-y-3">
                            <Skeleton className="h-8 w-48" />
                            <Skeleton className="h-4 w-full" />
                            <Skeleton className="h-4 w-3/4" />
                        </div>
                        <span className="sr-only">Loading {page.label}</span>
                    </div>
                )}

                {status === 'failed' && (
                    <div
                        role="alert"
                        data-testid="custom-page-failed"
                        className="absolute inset-0 z-10 overflow-y-auto bg-surface-solid p-6"
                    >
                        <EmptyState
                            icon={<TriangleAlert size={28} />}
                            title="This page could not be loaded"
                            description="It may have been removed, your account may no longer have access to it, or your session may have expired."
                            action={
                                <div className="flex flex-wrap items-center justify-center gap-2">
                                    <GlassButton type="button" variant="primary" onClick={retry}>
                                        Try again
                                    </GlassButton>
                                    <a href={newTabHref} target="_blank" rel="noopener noreferrer" className={SECONDARY_LINK_BUTTON_CLASS}>
                                        Open in a new tab
                                        <ExternalLink size={15} aria-hidden="true" />
                                    </a>
                                </div>
                            }
                        />
                    </div>
                )}
            </div>
            <span ref={afterFrameRef} tabIndex={-1} className="sr-only">
                End of {page.label}
            </span>
        </HostFrame>
    );
}

export function CustomPageHost() {
    const { slug } = useParams<{ slug: string }>();
    const navigation = useBootstrapStore((state) => state.data?.navigation);
    const view = resolveCustomPageHost(slug, navigation, API_BASE === '');

    if (view.kind === 'frame') {
        // Keyed by slug, so moving between two pages starts a fresh frame and a fresh state.
        return <EmbeddedCustomPage key={view.page.slug} page={view.page} />;
    }
    if (view.kind === 'new-tab') {
        return <NewTabCustomPage page={view.page} reason={view.reason} />;
    }
    return <UnavailableCustomPage />;
}

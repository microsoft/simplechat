// AccessRestrictedPage.tsx
// The V2 Access restricted page. When an administrator suspends or blocks an account, the
// server's access gate sends every V2 page here instead of showing an error, so the user can
// read what they were told, see whether access comes back on its own, and sign out.
//
// Rendered outside the application shell: every other API call is refused while the account
// is restricted, so nothing the shell needs could load. It reads one route, which only ever
// describes the signed-in user's own account.

import { useEffect, useState } from 'react';
import { CalendarClock, CircleCheck, LogIn, LogOut, ShieldAlert, TriangleAlert } from 'lucide-react';
import { GlassButton, GlassPanel, Skeleton } from '../components/ui/primitives';
import { useUiStore } from '../stores/uiStore';
import { ApiError, apiUrl } from '../lib/apiClient';
import {
    fetchAccessRestriction,
    formatRestoreTime,
    type AccessRestrictionStatus,
} from '../lib/accessRestriction';

const LINK_BUTTON =
    'inline-flex h-10 items-center justify-center gap-2 rounded-xl px-4 text-sm font-medium transition-colors';

export function AccessRestrictedPage() {
    const theme = useUiStore((state) => state.theme);
    const [status, setStatus] = useState<AccessRestrictionStatus | null>(null);
    const [loadError, setLoadError] = useState<string | null>(null);
    const [sessionExpired, setSessionExpired] = useState(false);
    const [attempt, setAttempt] = useState(0);

    useEffect(() => {
        const controller = new AbortController();
        setLoadError(null);
        fetchAccessRestriction(controller.signal)
            .then((result) => {
                if (!controller.signal.aborted) {
                    setStatus(result);
                }
            })
            .catch((error: unknown) => {
                if (controller.signal.aborted) {
                    return;
                }
                if (error instanceof ApiError && error.status === 401) {
                    setSessionExpired(true);
                    return;
                }
                setLoadError('Your account status could not be loaded. Try again in a moment.');
            });
        return () => controller.abort();
    }, [attempt]);

    const branding = status?.branding;
    const appTitle = branding?.app_title || 'SimpleChat';
    useEffect(() => {
        document.title = status?.restricted ? `Access restricted - ${appTitle}` : appTitle;
    }, [status, appTitle]);

    const banner = branding?.classification_banner;
    const themedLogoUrl = theme === 'dark' ? branding?.logo_dark_url : branding?.logo_url;
    const logoUrl = branding?.show_logo ? themedLogoUrl : null;
    const restriction = status?.restriction ?? null;
    const restoreTime = restriction?.kind === 'suspended' ? formatRestoreTime(restriction.until) : null;

    const signOut = (
        <a
            href={apiUrl('/logout')}
            className={`${LINK_BUTTON} glass-flat text-text-1 hover:bg-surface-2`}
            data-testid="v2-access-restricted-signout"
        >
            <LogOut size={16} aria-hidden="true" />
            Sign out
        </a>
    );

    return (
        <div className="flex h-full flex-col">
            {banner?.enabled && banner.text ? (
                <div
                    id="classification-banner"
                    role="note"
                    className="flex h-8 shrink-0 items-center justify-center text-sm font-bold tracking-wide"
                    style={{ background: banner.color, color: banner.text_color }}
                >
                    {banner.text}
                </div>
            ) : null}

            <main className="flex min-h-0 flex-1 items-start justify-center overflow-y-auto p-4 sm:items-center sm:p-6">
                <GlassPanel
                    edge
                    elevation="raised"
                    className="flex max-h-full w-full max-w-2xl flex-col p-6 sm:p-8"
                    data-testid="v2-access-restricted"
                >
                    {(logoUrl || (branding && !branding.hide_app_title)) && (
                        <div className="mb-5 flex items-center gap-3">
                            {logoUrl ? (
                                <img src={logoUrl} alt="" className="h-8 w-auto max-w-[160px] object-contain" />
                            ) : null}
                            {branding && !branding.hide_app_title ? (
                                <span className="text-sm font-semibold text-text-2">{appTitle}</span>
                            ) : null}
                        </div>
                    )}

                    {sessionExpired ? (
                        <div className="flex items-start gap-3">
                            <LogIn size={20} className="mt-0.5 shrink-0 text-accent" aria-hidden="true" />
                            <div>
                                <h1 className="font-semibold text-text-1">Your session has expired</h1>
                                <p className="mt-1 text-sm text-text-3">Sign in again to see your account status.</p>
                                <a href={apiUrl('/login')} className={`${LINK_BUTTON} mt-4 bg-accent text-on-accent hover:bg-accent-hover`}>
                                    Sign in
                                </a>
                            </div>
                        </div>
                    ) : loadError ? (
                        <div role="alert" className="flex items-start gap-3">
                            <TriangleAlert size={20} className="mt-0.5 shrink-0 text-danger" aria-hidden="true" />
                            <div>
                                <h1 className="font-semibold text-text-1">Account status unavailable</h1>
                                <p className="mt-1 text-sm text-text-3">{loadError}</p>
                                <div className="mt-4 flex flex-wrap gap-2">
                                    <GlassButton variant="primary" onClick={() => setAttempt((value) => value + 1)}>
                                        Try again
                                    </GlassButton>
                                    {signOut}
                                </div>
                            </div>
                        </div>
                    ) : !status ? (
                        <div className="space-y-3" aria-busy="true">
                            <Skeleton className="h-7 w-64" />
                            <Skeleton className="h-4 w-full" />
                            <Skeleton className="h-4 w-2/3" />
                            <span className="sr-only">Loading your account status</span>
                        </div>
                    ) : restriction ? (
                        <>
                            <div className="flex items-start gap-3">
                                <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-danger-soft text-danger">
                                    <ShieldAlert size={20} aria-hidden="true" />
                                </span>
                                <div className="min-w-0">
                                    <p className="text-xs font-semibold tracking-wide text-danger uppercase">
                                        Access restricted
                                    </p>
                                    <h1 className="mt-0.5 text-xl font-semibold text-text-1">{restriction.title}</h1>
                                </div>
                            </div>

                            {/* Plain text the administrator wrote. Never HTML. */}
                            <div
                                className="mt-5 min-h-0 overflow-y-auto rounded-xl border border-edge bg-surface-sunken p-4 text-sm leading-relaxed whitespace-pre-wrap text-text-1"
                                data-testid="v2-access-restricted-message"
                            >
                                {restriction.message}
                            </div>

                            <dl className="mt-5 grid gap-x-4 gap-y-2 text-sm sm:grid-cols-[max-content_1fr]">
                                <dt className="flex items-center gap-1.5 font-medium text-text-2">
                                    <CalendarClock size={14} aria-hidden="true" />
                                    Access returns
                                </dt>
                                <dd className="text-text-1" data-testid="v2-access-restricted-until">
                                    {restriction.kind === 'suspended' && restriction.until ? (
                                        <time dateTime={restriction.until}>{restoreTime ?? restriction.until}</time>
                                    ) : (
                                        'No automatic restore date. Contact your administrator about this decision.'
                                    )}
                                </dd>
                                {restriction.referenceId ? (
                                    <>
                                        <dt className="font-medium text-text-2">Reference</dt>
                                        <dd className="break-all text-text-1" data-testid="v2-access-restricted-reference">
                                            {restriction.referenceId}
                                        </dd>
                                    </>
                                ) : null}
                            </dl>

                            <div className="mt-6 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">{signOut}</div>
                        </>
                    ) : (
                        <>
                            <div className="flex items-start gap-3">
                                <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-ok-soft text-ok">
                                    <CircleCheck size={20} aria-hidden="true" />
                                </span>
                                <div className="min-w-0">
                                    <h1 className="text-xl font-semibold text-text-1">Your access is available</h1>
                                    <p className="mt-1 text-sm text-text-3">
                                        Your account is not restricted, so you can continue to {appTitle}.
                                    </p>
                                </div>
                            </div>
                            <div className="mt-6 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
                                {signOut}
                                <a
                                    href="/v2"
                                    className={`${LINK_BUTTON} bg-accent text-on-accent hover:bg-accent-hover`}
                                    data-testid="v2-access-restricted-continue"
                                >
                                    Continue
                                </a>
                            </div>
                        </>
                    )}
                </GlassPanel>
            </main>
        </div>
    );
}

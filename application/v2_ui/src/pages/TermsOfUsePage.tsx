// TermsOfUsePage.tsx
// The V2 Terms of Use interstitial. The server's gate sends a V2 user here instead of to the
// classic page, so accepting returns them to the V2 page they were opening.
//
// Rendered outside the application shell: until the terms are accepted every other API
// call is refused, so nothing the shell needs could load.

import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { FileText, TriangleAlert } from 'lucide-react';
import { GlassButton, GlassPanel, Skeleton } from '../components/ui/primitives';
import { useUiStore } from '../stores/uiStore';
import {
    acceptTermsOfUse,
    declineTermsOfUse,
    fetchTermsOfUse,
    type TermsOfUsePayload,
} from '../lib/termsOfUse';

type Pending = 'accept' | 'decline' | null;

function errorText(error: unknown, fallback: string): string {
    return error instanceof Error && error.message ? error.message : fallback;
}

export function TermsOfUsePage() {
    const [searchParams] = useSearchParams();
    const next = searchParams.get('next');
    const theme = useUiStore((state) => state.theme);
    const [terms, setTerms] = useState<TermsOfUsePayload | null>(null);
    const [loadError, setLoadError] = useState<string | null>(null);
    const [actionError, setActionError] = useState<string | null>(null);
    const [pending, setPending] = useState<Pending>(null);

    useEffect(() => {
        let cancelled = false;
        fetchTermsOfUse(next)
            .then((payload) => {
                if (cancelled) {
                    return;
                }
                // Nothing to accept -- terms are off or already accepted -- so carry on to
                // where the user was going rather than showing an empty interstitial.
                if (!payload.enabled || !payload.required) {
                    window.location.replace(payload.return_path || '/v2');
                    return;
                }
                setTerms(payload);
            })
            .catch((error: unknown) => {
                if (!cancelled) {
                    setLoadError(errorText(error, 'The Terms of Use could not be loaded.'));
                }
            });
        return () => {
            cancelled = true;
        };
    }, [next]);

    useEffect(() => {
        if (terms?.title) {
            document.title = terms.branding.app_title
                ? `${terms.title} - ${terms.branding.app_title}`
                : terms.title;
        }
    }, [terms]);

    const decide = async (decision: Exclude<Pending, null>) => {
        setPending(decision);
        setActionError(null);
        try {
            const result =
                decision === 'accept' ? await acceptTermsOfUse() : await declineTermsOfUse();
            window.location.assign(result.redirect_url || (decision === 'accept' ? '/v2' : '/'));
        } catch (error) {
            setPending(null);
            setActionError(
                errorText(
                    error,
                    decision === 'accept'
                        ? 'Your acceptance could not be recorded. Try again.'
                        : 'Your response could not be recorded. Try again.',
                ),
            );
        }
    };

    const branding = terms?.branding;
    const banner = branding?.classification_banner;
    const themedLogoUrl = theme === 'dark' ? branding?.logo_dark_url : branding?.logo_url;
    const logoUrl = branding?.show_logo ? themedLogoUrl : null;
    const appTitle = branding?.app_title || 'SimpleChat';

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
                    className="flex max-h-full w-full max-w-3xl flex-col p-6 sm:p-8"
                    data-testid="v2-terms-of-use"
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

                    {loadError ? (
                        <div role="alert" className="flex items-start gap-3">
                            <TriangleAlert size={20} className="mt-0.5 shrink-0 text-danger" />
                            <div>
                                <h1 className="font-semibold text-text-1">Terms of Use unavailable</h1>
                                <p className="mt-1 text-sm text-text-3">{loadError}</p>
                                <GlassButton
                                    variant="primary"
                                    className="mt-4"
                                    onClick={() => window.location.reload()}
                                >
                                    Try again
                                </GlassButton>
                            </div>
                        </div>
                    ) : !terms ? (
                        <div className="space-y-3" aria-busy="true">
                            <Skeleton className="h-7 w-56" />
                            <Skeleton className="h-4 w-full" />
                            <Skeleton className="h-4 w-full" />
                            <Skeleton className="h-4 w-2/3" />
                            <span className="sr-only">Loading the Terms of Use</span>
                        </div>
                    ) : (
                        <>
                            <div className="flex items-start gap-3">
                                <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-accent-soft text-accent">
                                    <FileText size={20} aria-hidden="true" />
                                </span>
                                <div className="min-w-0">
                                    <h1 className="text-xl font-semibold text-text-1">{terms.title}</h1>
                                    <p className="mt-0.5 text-sm text-text-3">
                                        Review and accept these terms to continue.
                                    </p>
                                </div>
                            </div>

                            {/* Plain text by design, matching the classic page. Never HTML. */}
                            <div
                                className="mt-5 min-h-0 flex-1 overflow-y-auto rounded-xl border border-edge bg-surface-sunken p-4 text-sm leading-relaxed whitespace-pre-wrap text-text-1"
                                data-testid="v2-terms-of-use-message"
                                tabIndex={0}
                                aria-label="Terms of Use text"
                            >
                                {terms.message}
                            </div>

                            {actionError ? (
                                <p role="alert" className="mt-4 text-sm text-danger">
                                    {actionError}
                                </p>
                            ) : null}

                            <div className="mt-6 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
                                <GlassButton
                                    variant="subtle"
                                    disabled={pending !== null}
                                    onClick={() => void decide('decline')}
                                    data-testid="v2-terms-decline"
                                    className="justify-center"
                                >
                                    {pending === 'decline' ? 'Signing out...' : terms.decline_button_text}
                                </GlassButton>
                                <GlassButton
                                    variant="primary"
                                    disabled={pending !== null}
                                    onClick={() => void decide('accept')}
                                    data-testid="v2-terms-accept"
                                    className="justify-center"
                                >
                                    {pending === 'accept' ? 'Saving...' : terms.accept_button_text}
                                </GlassButton>
                            </div>
                        </>
                    )}
                </GlassPanel>
            </main>
        </div>
    );
}

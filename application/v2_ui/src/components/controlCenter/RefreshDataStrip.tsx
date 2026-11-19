// RefreshDataStrip.tsx
// The Control Center's refresh status, and the action that recalculates its stored figures.
//
// The Users and Groups views read stored snapshots of each person's and group's activity, so
// they say "Not refreshed" until a refresh has run. It runs daily by itself, but an
// administrator who has just changed something, or who opens a deployment whose schedule has
// never fired, needs to run it now -- and until this strip existed that meant leaving V2 for
// the classic Control Center. The strip sits above every section, because one run feeds them
// all, and the section on screen reloads when it finishes.
//
// The server answers both routes only for the full Control Center capability, so the page
// draws this only for it; a dashboard-only reader would otherwise see a button that can
// only fail.

import { useCallback, useEffect, useState } from 'react';
import { clsx } from 'clsx';
import { AlertCircle, CalendarClock, History, RefreshCw } from 'lucide-react';
import { api } from '../../lib/apiClient';
import {
    CONTROL_CENTER_REFRESH_ENDPOINT,
    CONTROL_CENTER_REFRESH_STATUS_ENDPOINT,
    describeAutoRefresh,
    describeLastRefresh,
    describeRefreshOutcome,
    readRefreshOutcome,
    readRefreshStatus,
    type RefreshStatus,
} from '../../lib/controlCenterRefresh';
import { useNow } from '../admin/useNow';
import { GlassButton } from '../ui/primitives';

/** How long a clean result stays on screen. A partial result or a failure stays until the next run. */
const SUCCESS_VISIBLE_MS = 8000;

export function RefreshDataStrip({ onRefreshed }: { onRefreshed: () => void }) {
    const now = useNow();
    const [status, setStatus] = useState<RefreshStatus | null>(null);
    const [statusError, setStatusError] = useState<string | null>(null);
    const [busy, setBusy] = useState(false);
    const [result, setResult] = useState<{ tone: 'success' | 'warning'; text: string } | null>(null);
    const [failure, setFailure] = useState<string | null>(null);

    const loadStatus = useCallback(async (signal?: AbortSignal) => {
        try {
            const read = readRefreshStatus(await api.get<unknown>(CONTROL_CENTER_REFRESH_STATUS_ENDPOINT, signal));
            if (!read) {
                throw new Error('The refresh status was not in a form this page understands.');
            }
            setStatus(read);
            setStatusError(null);
        } catch (error) {
            if (!signal?.aborted) {
                setStatusError(error instanceof Error ? error.message : 'The refresh status could not be loaded.');
            }
        }
    }, []);

    useEffect(() => {
        const controller = new AbortController();
        void loadStatus(controller.signal);
        return () => controller.abort();
    }, [loadStatus]);

    useEffect(() => {
        if (result?.tone !== 'success') {
            return;
        }
        const timer = window.setTimeout(() => setResult(null), SUCCESS_VISIBLE_MS);
        return () => window.clearTimeout(timer);
    }, [result]);

    const refresh = async () => {
        // aria-disabled keeps the button focusable while it works, so a keyboard user is not
        // dropped to the top of the page; the click is ignored here instead.
        if (busy) {
            return;
        }
        setBusy(true);
        setResult(null);
        setFailure(null);
        try {
            const outcome = readRefreshOutcome(await api.post<unknown>(CONTROL_CENTER_REFRESH_ENDPOINT, {}));
            if (!outcome) {
                throw new Error('The refresh did not report that it finished.');
            }
            setResult(describeRefreshOutcome(outcome));
            await loadStatus();
            onRefreshed();
        } catch (error) {
            setFailure(error instanceof Error ? error.message : 'The data could not be refreshed.');
        } finally {
            setBusy(false);
        }
    };

    return (
        <div
            data-testid="control-center-refresh"
            className="flex shrink-0 flex-wrap items-center justify-between gap-x-6 gap-y-2 border-b border-edge px-4 py-2.5 lg:px-6"
        >
            <div className="min-w-0 flex-[1_1_18rem] space-y-0.5 text-xs leading-relaxed text-text-3">
                {status ? (
                    <>
                        <p className="flex items-start gap-1.5">
                            <History size={13} aria-hidden="true" className="mt-0.5 shrink-0" />
                            <span>{describeLastRefresh(status, now)}</span>
                        </p>
                        <p className="flex items-start gap-1.5">
                            <CalendarClock size={13} aria-hidden="true" className="mt-0.5 shrink-0" />
                            <span>{describeAutoRefresh(status, now)}</span>
                        </p>
                    </>
                ) : statusError ? (
                    <p role="alert" className="flex items-start gap-1.5 text-danger">
                        <AlertCircle size={13} aria-hidden="true" className="mt-0.5 shrink-0" />
                        <span>{statusError}</span>
                    </p>
                ) : (
                    <p>Loading when the data was last refreshed…</p>
                )}
            </div>

            <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-2">
                <div role="status" className="min-w-0 text-xs">
                    {result ? (
                        <p className={result.tone === 'success' ? 'text-ok' : 'text-warn'}>{result.text}</p>
                    ) : null}
                </div>
                {failure ? (
                    <p role="alert" className="flex min-w-0 items-start gap-1.5 text-xs text-danger">
                        <AlertCircle size={13} aria-hidden="true" className="mt-0.5 shrink-0" />
                        <span>{failure}</span>
                    </p>
                ) : null}
                <GlassButton
                    type="button"
                    variant="subtle"
                    size="sm"
                    aria-disabled={busy || undefined}
                    aria-busy={busy || undefined}
                    title="Recalculates the stored activity figures for every user and group."
                    className={clsx(busy && 'cursor-progress opacity-70')}
                    onClick={() => void refresh()}
                >
                    <RefreshCw
                        size={14}
                        aria-hidden="true"
                        className={clsx(busy && 'animate-spin motion-reduce:animate-none')}
                    />
                    {busy ? 'Refreshing data…' : 'Refresh data'}
                </GlassButton>
            </div>
        </div>
    );
}

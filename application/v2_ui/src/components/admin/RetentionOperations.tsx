// RetentionOperations.tsx
// Run retention now, and reset every chosen period back to the organization defaults.
//
// Both act on everything stored for a workspace type and neither can be undone, so a click
// opens a review rather than acting: the types it may touch, the defaults those types
// follow, and plainly what happens to the data. The review sits inline rather than in a
// dialog so the defaults above stay in view, and so a run that takes minutes on a large
// deployment does not hold the whole page behind a modal.
//
// Both work from saved settings only, because the routes read what is stored. While the
// draft holds an edit they depend on, both are held with a message saying to save first,
// and only workspace types whose retention is on in the saved settings can be chosen.

import { useEffect, useId, useRef, useState, type ReactNode, type RefObject } from 'react';
import { clsx } from 'clsx';
import {
    AlertCircle,
    AlertTriangle,
    CheckCircle2,
    CirclePlay,
    Loader2,
    RotateCcw,
    XCircle,
    type LucideIcon,
} from 'lucide-react';
import { api } from '../../lib/apiClient';
import { asBoolean, type AdminField } from '../../lib/adminFields';
import {
    CONVERSATION_ARCHIVING_KEY,
    RETENTION_AFFECTED_NOUNS,
    RETENTION_LAST_RUN_KEY,
    RETENTION_NEXT_RUN_KEY,
    RETENTION_RUN_KEYS,
    RETENTION_SCOPES,
    RETENTION_SCOPE_LABELS,
    RETENTION_SETTING_KEYS,
    retentionRequestError,
    savedEnabledScopes,
    scopeDefaultsSummary,
    summarizeRetentionReset,
    summarizeRetentionRun,
    unsavedKeys,
    type RetentionResetSummary,
    type RetentionRunSummary,
    type RetentionScope,
} from '../../lib/retentionPolicy';
import type { Json } from '../../lib/types';
import { GlassButton } from '../ui/primitives';
import { RETENTION_SCOPE_ICONS } from './retentionScopeIcons';

type Phase = 'idle' | 'review' | 'working' | 'done' | 'failed';

function plural(count: number, [one, many]: readonly [string, string]): string {
    return `${count.toLocaleString()} ${count === 1 ? one : many}`;
}

/** A row laid out like every other setting: label and help on the left, action on the right. */
function OperationRow({ field, children }: { field: AdminField; children: ReactNode }) {
    return (
        <div className="admin-field py-3" data-field-width="wide">
            <div className="admin-field-heading text-sm font-semibold text-text-1">{field.label}</div>
            {field.help ? (
                <p className="admin-field-help text-[0.8125rem] leading-relaxed text-text-3">{field.help}</p>
            ) : null}
            <div className="admin-field-control min-w-0">{children}</div>
        </div>
    );
}

function Callout({ tone, children }: { tone: 'warn' | 'danger' | 'ok'; children: ReactNode }) {
    const Icon: LucideIcon = tone === 'ok' ? CheckCircle2 : tone === 'danger' ? XCircle : AlertTriangle;
    return (
        <div
            className={clsx(
                'flex items-start gap-2 rounded-lg border px-3 py-2 text-xs leading-relaxed text-text-2',
                tone === 'warn' && 'border-warn/40 bg-warn/5',
                tone === 'danger' && 'border-danger/40 bg-danger/5',
                tone === 'ok' && 'border-ok/40 bg-ok/5',
            )}
        >
            <Icon
                size={13}
                aria-hidden="true"
                className={clsx(
                    'mt-0.5 shrink-0',
                    tone === 'warn' && 'text-warn',
                    tone === 'danger' && 'text-danger',
                    tone === 'ok' && 'text-ok',
                )}
            />
            <div className="min-w-0 space-y-1">{children}</div>
        </div>
    );
}

/** Why an action is held, shown under its trigger and inside an open review. */
function HeldNotice({ children }: { children: ReactNode }) {
    return (
        <p className="mt-1.5 flex items-start gap-1.5 text-xs text-warn">
            <AlertCircle size={13} className="mt-0.5 shrink-0" aria-hidden="true" />
            <span>{children}</span>
        </p>
    );
}

function ScopeChoices({
    idPrefix,
    legend,
    enabled,
    selected,
    disabled,
    describe,
    onToggle,
}: {
    idPrefix: string;
    legend: string;
    enabled: readonly RetentionScope[];
    selected: readonly RetentionScope[];
    disabled: boolean;
    describe: (scope: RetentionScope) => ReactNode;
    onToggle: (scope: RetentionScope, checked: boolean) => void;
}) {
    return (
        <fieldset className="mt-3 min-w-0">
            <legend className="text-xs font-medium text-text-3">{legend}</legend>
            <ul className="mt-1 divide-y divide-edge-strong">
                {RETENTION_SCOPES.map((scope) => {
                    const available = enabled.includes(scope);
                    const Icon = RETENTION_SCOPE_ICONS[scope];
                    const id = `${idPrefix}-${scope}`;
                    return (
                        <li key={scope} className="flex items-start gap-3 py-2.5">
                            <input
                                id={id}
                                type="checkbox"
                                className="mt-1 accent-[var(--accent)]"
                                checked={available && selected.includes(scope)}
                                disabled={disabled || !available}
                                onChange={(event) => onToggle(scope, event.target.checked)}
                            />
                            <label
                                htmlFor={id}
                                className={clsx(
                                    'min-w-0 flex-1',
                                    available && !disabled ? 'cursor-pointer' : 'cursor-not-allowed',
                                )}
                            >
                                <span
                                    className={clsx(
                                        'block text-sm font-medium',
                                        available ? 'text-text-1' : 'text-text-3',
                                    )}
                                >
                                    {/* Inline rather than a flex sibling, so a narrow card gives
                                        the label its whole width instead of a column beside it. */}
                                    <Icon
                                        size={14}
                                        aria-hidden="true"
                                        className="mr-1.5 inline-block align-[-0.125em]"
                                    />
                                    {RETENTION_SCOPE_LABELS[scope]}
                                </span>
                                <span className="mt-0.5 block text-xs leading-relaxed text-text-3">
                                    {available
                                        ? describe(scope)
                                        : 'Retention is off for this type in the saved settings, so it is left alone.'}
                                </span>
                            </label>
                        </li>
                    );
                })}
            </ul>
        </fieldset>
    );
}

/**
 * The open/close, focus and selection behaviour both reviews share.
 *
 * Opening moves focus to the review's heading so a keyboard or screen reader user lands in
 * it; closing hands focus back to the button that opened it.
 */
function useReview(enabled: readonly RetentionScope[]) {
    const [phase, setPhase] = useState<Phase>('idle');
    const [selected, setSelected] = useState<RetentionScope[]>([]);
    const triggerRef = useRef<HTMLButtonElement>(null);
    const headingRef = useRef<HTMLHeadingElement>(null);
    const returnFocus = useRef(false);

    useEffect(() => {
        if (phase === 'review' || phase === 'done' || phase === 'failed') {
            headingRef.current?.focus();
        } else if (phase === 'idle' && returnFocus.current) {
            returnFocus.current = false;
            triggerRef.current?.focus();
        }
    }, [phase]);

    return {
        phase,
        setPhase,
        // A type switched off and saved while the review is open drops out of the choice.
        chosen: selected.filter((scope) => enabled.includes(scope)),
        triggerRef,
        headingRef,
        open: () => {
            setSelected([]);
            setPhase('review');
        },
        close: () => {
            returnFocus.current = true;
            setPhase('idle');
        },
        toggle: (scope: RetentionScope, checked: boolean) =>
            setSelected((current) =>
                checked ? [...new Set([...current, scope])] : current.filter((item) => item !== scope),
            ),
    };
}

/**
 * The button that opens a review, styled like the other in-row actions (Test connection).
 *
 * It grows with its label rather than holding a fixed height, so at a large text size on a
 * narrow card the label wraps inside the button instead of spilling over the help text.
 */
function ReviewTrigger({
    triggerRef,
    icon: Icon,
    label,
    disabled,
    onOpen,
}: {
    triggerRef: RefObject<HTMLButtonElement>;
    icon: LucideIcon;
    label: string;
    disabled: boolean;
    onOpen: () => void;
}) {
    return (
        <button
            ref={triggerRef}
            type="button"
            aria-expanded={false}
            disabled={disabled}
            onClick={onOpen}
            className={clsx(
                'inline-flex max-w-full items-center gap-2 rounded-lg border border-edge px-3 py-2',
                'text-left text-sm font-medium text-text-1 transition-colors hover:bg-surface-2',
                'disabled:cursor-not-allowed disabled:opacity-60 disabled:hover:bg-transparent',
            )}
        >
            <Icon size={15} aria-hidden="true" className="shrink-0" />
            {label}
        </button>
    );
}

interface OperationProps {
    field: AdminField;
    /** The saved settings. Both actions work from these alone. */
    settings: Json;
    draft: Json;
    /** True while the page is saving. */
    disabled?: boolean;
}

export function RetentionRunNow({
    field,
    settings,
    draft,
    disabled = false,
    onStoredSettingsChange,
    onOpenSection,
}: OperationProps & {
    /** Merge the run's new last and next run into the page's copy of the saved settings. */
    onStoredSettingsChange: (partial: Json) => void;
    onOpenSection: (sectionId: string) => void;
}) {
    const enabled = savedEnabledScopes(settings);
    const held = unsavedKeys(draft, RETENTION_RUN_KEYS).length > 0;
    const archiving = asBoolean(settings[CONVERSATION_ARCHIVING_KEY]);
    const review = useReview(enabled);
    const [summary, setSummary] = useState<RetentionRunSummary | null>(null);
    const [failure, setFailure] = useState('');
    const idPrefix = useId();
    const headingId = `${idPrefix}-heading`;

    const refreshSchedule = async () => {
        try {
            const response = await api.get<{ settings?: Json }>('/api/admin/retention-policy/settings');
            const stored = response.settings ?? {};
            onStoredSettingsChange({
                [RETENTION_LAST_RUN_KEY]: stored[RETENTION_LAST_RUN_KEY] ?? null,
                [RETENTION_NEXT_RUN_KEY]: stored[RETENTION_NEXT_RUN_KEY] ?? null,
            });
        } catch {
            // The run's own outcome is already on screen; a stale schedule readout is not
            // worth a second error beside it, and "Check again" can read it later.
        }
    };

    const run = async () => {
        const scopes = review.chosen;
        if (!scopes.length || held) {
            return;
        }
        review.setPhase('working');
        setSummary(null);
        setFailure('');
        try {
            const response = await api.post<unknown>('/api/admin/retention-policy/execute', { scopes });
            setSummary(summarizeRetentionRun(response, scopes));
            review.setPhase('done');
        } catch (error) {
            setFailure(retentionRequestError(error, 'run'));
            review.setPhase('failed');
        } finally {
            void refreshSchedule();
        }
    };

    if (review.phase === 'idle') {
        return (
            <OperationRow field={field}>
                <ReviewTrigger
                    triggerRef={review.triggerRef}
                    icon={CirclePlay}
                    label="Run now…"
                    disabled={disabled || held || !enabled.length}
                    onOpen={review.open}
                />
                {held ? (
                    <HeldNotice>
                        Save or discard your changes first. Retention runs on saved settings only.
                    </HeldNotice>
                ) : null}
            </OperationRow>
        );
    }

    const working = review.phase === 'working';

    return (
        <OperationRow field={field}>
            <section
                role="region"
                aria-labelledby={headingId}
                className="rounded-xl border border-edge-strong bg-surface-sunken p-3 sm:p-4"
                data-testid="retention-run-review"
            >
                {review.phase === 'done' && summary ? (
                    <>
                        <h3
                            ref={review.headingRef}
                            id={headingId}
                            tabIndex={-1}
                            className="text-sm font-semibold text-text-1 focus:outline-none"
                        >
                            {summary.ok && !summary.errorCount ? 'Retention finished' : 'Retention finished with problems'}
                        </h3>
                        <div role="status" className="mt-2 space-y-3">
                            <Callout tone={summary.ok && !summary.errorCount ? 'ok' : 'warn'}>
                                <p>
                                    {summary.conversations || summary.documents
                                        ? `Removed ${plural(summary.conversations, ['conversation', 'conversations'])} and ${plural(summary.documents, ['document', 'documents'])}.`
                                        : 'Nothing was past its period, so nothing was removed.'}
                                </p>
                                {summary.errorCount ? (
                                    <p>
                                        The run reported {plural(summary.errorCount, ['problem', 'problems'])}. Check
                                        the application logs for the cause before running it again.
                                    </p>
                                ) : null}
                            </Callout>
                            {summary.rows.length ? (
                                <div className="overflow-x-auto">
                                    <table className="w-full text-left text-xs">
                                        <thead className="text-text-3">
                                            <tr>
                                                <th scope="col" className="py-1.5 pr-3 font-medium">Workspace type</th>
                                                <th scope="col" className="py-1.5 pr-3 text-right font-medium">Conversations</th>
                                                <th scope="col" className="py-1.5 pr-3 text-right font-medium">Documents</th>
                                                <th scope="col" className="py-1.5 text-right font-medium">Affected</th>
                                            </tr>
                                        </thead>
                                        <tbody className="divide-y divide-edge-strong tabular-nums text-text-1">
                                            {summary.rows.map((row) => (
                                                <tr key={row.scope}>
                                                    <th scope="row" className="py-1.5 pr-3 font-normal">
                                                        {RETENTION_SCOPE_LABELS[row.scope]}
                                                    </th>
                                                    <td className="py-1.5 pr-3 text-right">{row.conversations.toLocaleString()}</td>
                                                    <td className="py-1.5 pr-3 text-right">{row.documents.toLocaleString()}</td>
                                                    <td className="py-1.5 text-right">
                                                        {plural(row.affected, RETENTION_AFFECTED_NOUNS[row.scope])}
                                                    </td>
                                                </tr>
                                            ))}
                                        </tbody>
                                    </table>
                                </div>
                            ) : null}
                        </div>
                        <div className="mt-3 flex justify-end">
                            <GlassButton type="button" variant="ghost" size="sm" onClick={review.close}>
                                Done
                            </GlassButton>
                        </div>
                    </>
                ) : review.phase === 'failed' ? (
                    <>
                        <h3
                            ref={review.headingRef}
                            id={headingId}
                            tabIndex={-1}
                            className="text-sm font-semibold text-text-1 focus:outline-none"
                        >
                            Retention did not report back
                        </h3>
                        <div role="alert" className="mt-2">
                            <Callout tone="danger">
                                <p>{failure}</p>
                            </Callout>
                        </div>
                        <div className="mt-3 flex justify-end">
                            <GlassButton type="button" variant="ghost" size="sm" onClick={review.close}>
                                Close
                            </GlassButton>
                        </div>
                    </>
                ) : (
                    <>
                        <h3
                            ref={review.headingRef}
                            id={headingId}
                            tabIndex={-1}
                            className="text-sm font-semibold text-text-1 focus:outline-none"
                        >
                            Review before running
                        </h3>
                        <p className="mt-1 text-xs leading-relaxed text-text-3">
                            Every user, group or workspace keeps the period it chose. The rest follow
                            the defaults shown.
                        </p>
                        <ScopeChoices
                            idPrefix={idPrefix}
                            legend="Workspace types to clean up"
                            enabled={enabled}
                            selected={review.chosen}
                            disabled={working || disabled}
                            describe={(scope) => scopeDefaultsSummary(settings, scope, 'run')}
                            onToggle={review.toggle}
                        />
                        <div className="mt-3">
                            <Callout tone="warn">
                                <p>
                                    <span className="font-semibold text-text-1">
                                        This deletes data now and cannot be undone.
                                    </span>{' '}
                                    Conversations idle and documents unchanged for longer than their
                                    period are removed from the chosen types.
                                </p>
                                <p>Documents are deleted permanently, with their search entries and stored files.</p>
                                <p>
                                    {archiving
                                        ? 'Conversations are copied to the archive first, because Conversation Archiving is on. '
                                        : 'Conversations are deleted permanently, because Conversation Archiving is off. '}
                                    <button
                                        type="button"
                                        className="text-accent underline underline-offset-2 hover:no-underline"
                                        onClick={() => onOpenSection('conversation-archiving-section')}
                                    >
                                        Review archiving
                                    </button>
                                </p>
                                <p>Affected owners are notified of what was removed.</p>
                            </Callout>
                        </div>
                        {held ? (
                            <HeldNotice>
                                Save or discard your changes first. Retention runs on saved settings only.
                            </HeldNotice>
                        ) : null}
                        {working ? (
                            <p role="status" className="mt-2 text-xs text-text-3">
                                Running. On a large deployment this can take several minutes; the result
                                appears here when it finishes.
                            </p>
                        ) : null}
                        <div className="mt-3 flex flex-wrap justify-end gap-2">
                            <GlassButton
                                type="button"
                                variant="ghost"
                                size="sm"
                                disabled={working}
                                onClick={review.close}
                            >
                                Cancel
                            </GlassButton>
                            <GlassButton
                                type="button"
                                variant="danger"
                                size="sm"
                                disabled={working || disabled || held || !review.chosen.length}
                                onClick={() => void run()}
                            >
                                {working ? (
                                    <Loader2 size={14} className="animate-spin" aria-hidden="true" />
                                ) : (
                                    <CirclePlay size={14} aria-hidden="true" />
                                )}
                                {working ? 'Running…' : 'Run retention now'}
                            </GlassButton>
                        </div>
                    </>
                )}
            </section>
        </OperationRow>
    );
}

export function RetentionResetDefaults({ field, settings, draft, disabled = false }: OperationProps) {
    const enabled = savedEnabledScopes(settings);
    const held = unsavedKeys(draft, RETENTION_SETTING_KEYS).length > 0;
    const review = useReview(enabled);
    const [summary, setSummary] = useState<RetentionResetSummary | null>(null);
    const [failure, setFailure] = useState('');
    const idPrefix = useId();
    const headingId = `${idPrefix}-heading`;

    const reset = async () => {
        const scopes = review.chosen;
        if (!scopes.length || held) {
            return;
        }
        review.setPhase('working');
        setSummary(null);
        setFailure('');
        try {
            const response = await api.post<unknown>('/api/admin/retention-policy/force-push', { scopes });
            setSummary(summarizeRetentionReset(response, scopes));
            review.setPhase('done');
        } catch (error) {
            setFailure(retentionRequestError(error, 'reset'));
            review.setPhase('failed');
        }
    };

    if (review.phase === 'idle') {
        return (
            <OperationRow field={field}>
                <ReviewTrigger
                    triggerRef={review.triggerRef}
                    icon={RotateCcw}
                    label="Reset to defaults…"
                    disabled={disabled || held || !enabled.length}
                    onOpen={review.open}
                />
                {held ? (
                    <HeldNotice>
                        Save or discard your changes first. The reset applies the saved defaults only.
                    </HeldNotice>
                ) : null}
            </OperationRow>
        );
    }

    const working = review.phase === 'working';

    return (
        <OperationRow field={field}>
            <section
                role="region"
                aria-labelledby={headingId}
                className="rounded-xl border border-edge-strong bg-surface-sunken p-3 sm:p-4"
                data-testid="retention-reset-review"
            >
                {review.phase === 'done' && summary ? (
                    <>
                        <h3
                            ref={review.headingRef}
                            id={headingId}
                            tabIndex={-1}
                            className="text-sm font-semibold text-text-1 focus:outline-none"
                        >
                            {summary.ok ? 'Defaults applied' : 'The reset did not finish'}
                        </h3>
                        <div role="status" className="mt-2 space-y-3">
                            <Callout tone={summary.ok ? 'ok' : 'warn'}>
                                <p>
                                    {summary.ok
                                        ? `Reset ${plural(summary.total, ['retention policy', 'retention policies'])} to follow the organization defaults.`
                                        : 'Some policies may already follow the defaults. Check the application logs, then try again.'}
                                </p>
                            </Callout>
                            {summary.rows.length ? (
                                <ul className="divide-y divide-edge-strong text-xs">
                                    {summary.rows.map((row) => (
                                        <li key={row.scope} className="flex items-baseline justify-between gap-3 py-1.5">
                                            <span className="text-text-2">{RETENTION_SCOPE_LABELS[row.scope]}</span>
                                            <span className="tabular-nums text-text-1">
                                                {plural(row.updated, RETENTION_AFFECTED_NOUNS[row.scope])}
                                            </span>
                                        </li>
                                    ))}
                                </ul>
                            ) : null}
                        </div>
                        <div className="mt-3 flex justify-end">
                            <GlassButton type="button" variant="ghost" size="sm" onClick={review.close}>
                                Done
                            </GlassButton>
                        </div>
                    </>
                ) : review.phase === 'failed' ? (
                    <>
                        <h3
                            ref={review.headingRef}
                            id={headingId}
                            tabIndex={-1}
                            className="text-sm font-semibold text-text-1 focus:outline-none"
                        >
                            The reset did not report back
                        </h3>
                        <div role="alert" className="mt-2">
                            <Callout tone="danger">
                                <p>{failure}</p>
                            </Callout>
                        </div>
                        <div className="mt-3 flex justify-end">
                            <GlassButton type="button" variant="ghost" size="sm" onClick={review.close}>
                                Close
                            </GlassButton>
                        </div>
                    </>
                ) : (
                    <>
                        <h3
                            ref={review.headingRef}
                            id={headingId}
                            tabIndex={-1}
                            className="text-sm font-semibold text-text-1 focus:outline-none"
                        >
                            Review before resetting
                        </h3>
                        <p className="mt-1 text-xs leading-relaxed text-text-3">
                            Everyone in the chosen types goes back to following these defaults.
                        </p>
                        <ScopeChoices
                            idPrefix={idPrefix}
                            legend="Workspace types to reset"
                            enabled={enabled}
                            selected={review.chosen}
                            disabled={working || disabled}
                            describe={(scope) => scopeDefaultsSummary(settings, scope, 'reset')}
                            onToggle={review.toggle}
                        />
                        <div className="mt-3">
                            <Callout tone="warn">
                                <p>
                                    <span className="font-semibold text-text-1">This cannot be undone.</span>{' '}
                                    Every user, group and public workspace of the chosen types loses the
                                    period it chose. They would have to choose again.
                                </p>
                                <p>Nothing is deleted by the reset itself; the next run applies the defaults.</p>
                            </Callout>
                        </div>
                        {held ? (
                            <HeldNotice>
                                Save or discard your changes first. The reset applies the saved defaults only.
                            </HeldNotice>
                        ) : null}
                        {working ? (
                            <p role="status" className="mt-2 text-xs text-text-3">
                                Resetting. This visits every user, group or workspace of the chosen types.
                            </p>
                        ) : null}
                        <div className="mt-3 flex flex-wrap justify-end gap-2">
                            <GlassButton
                                type="button"
                                variant="ghost"
                                size="sm"
                                disabled={working}
                                onClick={review.close}
                            >
                                Cancel
                            </GlassButton>
                            <GlassButton
                                type="button"
                                variant="danger"
                                size="sm"
                                disabled={working || disabled || held || !review.chosen.length}
                                onClick={() => void reset()}
                            >
                                {working ? (
                                    <Loader2 size={14} className="animate-spin" aria-hidden="true" />
                                ) : (
                                    <RotateCcw size={14} aria-hidden="true" />
                                )}
                                {working ? 'Resetting…' : 'Reset to defaults'}
                            </GlassButton>
                        </div>
                    </>
                )}
            </section>
        </OperationRow>
    );
}

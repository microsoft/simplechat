// FileProcessingLogCleanup.tsx
// Delete stored file processing logs, by age or all at once.
//
// File processing logs are written to Cosmos DB for every upload while logging is on and
// are never pruned, so a container left to grow is a cost. The server-rendered page has
// always offered this cleanup; it posts to the same admin endpoint, which deletes the
// records, records the action in the admin activity log and reports how many went.
//
// It acts immediately rather than joining the page's Save, because it is not a setting:
// there is nothing to store, and a deletion queued behind unrelated edits would be easy to
// trigger by accident. The confirmation states exactly what will go.

import { useId, useRef, useState } from 'react';
import { clsx } from 'clsx';
import { AlertCircle, Trash2 } from 'lucide-react';
import { ApiError, api } from '../../lib/apiClient';
import {
    FILE_PROCESSING_LOG_CLEANUP_ENDPOINT,
    LOG_CLEANUP_UNITS,
    buildLogCleanupRequest,
    type LogCleanupRequest,
    type LogCleanupUnit,
} from '../../lib/adminOperations';
import { toast } from '../../stores/toastStore';
import { ConfirmDialog } from '../ui/ConfirmDialog';
import { GlassButton } from '../ui/primitives';
import { inputClass } from './fields';
import { ReadoutRow } from './ReadoutRow';

interface CleanupResponse {
    success?: boolean;
    deleted_count?: number;
}

/** How many were deleted before a failed cleanup stopped, when the server says. */
function partialCount(payload: unknown): number {
    if (payload && typeof payload === 'object' && 'deleted_count' in payload) {
        const count = Number((payload as { deleted_count?: unknown }).deleted_count);
        return Number.isInteger(count) && count > 0 ? count : 0;
    }
    return 0;
}

function plural(count: number, noun: string): string {
    return `${count} ${noun}${count === 1 ? '' : 's'}`;
}

export function FileProcessingLogCleanup({
    label,
    help,
    disabled,
}: {
    label: string;
    help?: string;
    disabled?: boolean;
}) {
    const ageId = useId();
    const unitId = useId();
    const errorId = useId();
    const ageRef = useRef<HTMLInputElement>(null);

    const [age, setAge] = useState('30');
    const [unit, setUnit] = useState<LogCleanupUnit>('days');
    const [formError, setFormError] = useState<string | null>(null);
    const [pending, setPending] = useState<{ request: LogCleanupRequest; confirmation: string } | null>(null);
    const [busy, setBusy] = useState(false);
    const [failure, setFailure] = useState<string | null>(null);

    const begin = (mode: 'older' | 'all') => {
        const result = buildLogCleanupRequest(mode, age, unit);
        if ('error' in result) {
            setFormError(result.error);
            ageRef.current?.focus();
            return;
        }
        setFormError(null);
        setFailure(null);
        setPending(result);
    };

    const confirm = async () => {
        if (!pending) {
            return;
        }
        setBusy(true);
        setFailure(null);
        try {
            const response = await api.post<CleanupResponse>(FILE_PROCESSING_LOG_CLEANUP_ENDPOINT, {
                ...pending.request,
                confirmed: true,
            });
            const count = Number(response.deleted_count) || 0;
            toast.success(`Deleted ${plural(count, 'file processing log')}.`);
            setPending(null);
        } catch (error) {
            const message = error instanceof Error ? error.message : 'The logs could not be deleted.';
            const deleted = error instanceof ApiError ? partialCount(error.payload) : 0;
            // Kept in the dialog, so the administrator can retry or step back knowing what
            // already happened rather than reading it from a toast that has gone.
            setFailure(
                deleted
                    ? `${message} ${plural(deleted, 'log')} ${deleted === 1 ? 'was' : 'were'} deleted before it stopped.`
                    : message,
            );
        } finally {
            setBusy(false);
        }
    };

    return (
        <ReadoutRow label={label} help={help} width="full">
            <div className="flex flex-wrap items-end gap-2">
                <div>
                    <label htmlFor={ageId} className="mb-1 block text-xs text-text-2">
                        Delete logs older than
                    </label>
                    <input
                        ref={ageRef}
                        id={ageId}
                        type="number"
                        inputMode="numeric"
                        min={1}
                        step={1}
                        value={age}
                        disabled={disabled || busy}
                        aria-invalid={formError ? true : undefined}
                        aria-describedby={formError ? errorId : undefined}
                        onChange={(event) => {
                            setAge(event.target.value);
                            setFormError(null);
                        }}
                        className={clsx(inputClass, 'w-28', formError && 'border-danger')}
                    />
                </div>
                <div>
                    <label htmlFor={unitId} className="mb-1 block text-xs text-text-2">
                        Unit
                    </label>
                    <select
                        id={unitId}
                        value={unit}
                        disabled={disabled || busy}
                        onChange={(event) => setUnit(event.target.value as LogCleanupUnit)}
                        className={clsx(inputClass, 'w-44 appearance-none pr-8')}
                    >
                        {LOG_CLEANUP_UNITS.map((option) => (
                            <option key={option.value} value={option.value}>
                                {option.label}
                            </option>
                        ))}
                    </select>
                </div>
                <GlassButton
                    type="button"
                    variant="danger"
                    disabled={disabled || busy}
                    onClick={() => begin('older')}
                >
                    <Trash2 size={14} aria-hidden="true" />
                    Delete older logs
                </GlassButton>
                <GlassButton
                    type="button"
                    variant="danger"
                    disabled={disabled || busy}
                    onClick={() => begin('all')}
                >
                    <Trash2 size={14} aria-hidden="true" />
                    Delete all logs
                </GlassButton>
            </div>

            {formError ? (
                <p id={errorId} role="alert" className="mt-1.5 flex items-start gap-1.5 text-xs text-danger">
                    <AlertCircle size={13} className="mt-0.5 shrink-0" aria-hidden="true" />
                    {formError}
                </p>
            ) : null}

            {pending ? (
                <ConfirmDialog
                    title="Delete file processing logs"
                    description={pending.confirmation}
                    confirmLabel="Delete logs"
                    confirmIcon={<Trash2 size={14} aria-hidden="true" />}
                    busy={busy}
                    onConfirm={() => void confirm()}
                    onClose={() => {
                        if (!busy) {
                            setPending(null);
                            setFailure(null);
                        }
                    }}
                >
                    <div className="space-y-2 text-xs leading-relaxed text-text-2">
                        <p>
                            The records are removed from Cosmos DB for good. Logging itself is not
                            changed.
                        </p>
                        {failure ? (
                            <p role="alert" className="flex items-start gap-1.5 text-danger">
                                <AlertCircle size={13} className="mt-0.5 shrink-0" aria-hidden="true" />
                                {failure}
                            </p>
                        ) : null}
                    </div>
                </ConfirmDialog>
            ) : null}
        </ReadoutRow>
    );
}

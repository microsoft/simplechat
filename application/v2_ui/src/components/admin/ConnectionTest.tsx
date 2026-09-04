// ConnectionTest.tsx
// Runs one administrator-requested connection test and reports the result.
//
// Endpoints and credentials are worth nothing if they are wrong, and the only way to find
// out is to try them. Without this, configuring a connection means saving blind and
// waiting for a user to hit the failure.
//
// The test runs against the values currently on screen, not the saved ones, so a
// connection can be verified before it is committed. The one value the browser cannot
// supply is a stored credential: it holds only the redaction placeholder, and the server
// swaps that back for the real secret before making the call.
//
// Nothing here knows about a specific service. Which test to run and how to shape its
// payload are both read from the field definition, so a new connection test is a schema
// entry rather than a component.

import { useState } from 'react';
import { clsx } from 'clsx';
import { CheckCircle2, Loader2, PlugZap, XCircle } from 'lucide-react';
import { ApiError, api } from '../../lib/apiClient';
import { evaluateDependency, type AdminField } from '../../lib/adminFields';
import type { Json } from '../../lib/types';

/** What the shared connection-test dispatcher returns. Shapes vary by test. */
interface ConnectionTestResponse {
    success?: boolean;
    message?: string;
    error?: string;
    details?: string[];
    guidance?: string[];
}

interface TestOutcome {
    ok: boolean;
    message: string;
    details: string[];
    guidance: string[];
}

/**
 * Write a value at a dotted path, creating intermediate objects.
 *
 * Payload shapes are nested -- `direct.endpoint`, `apim.subscription_key` -- because that
 * is what the existing test handlers expect. Declaring them flat and expanding here keeps
 * the schema readable.
 */
function assignPath(target: Json, path: string, value: unknown): void {
    const parts = path.split('.');
    let cursor = target as Record<string, unknown>;

    for (const part of parts.slice(0, -1)) {
        if (typeof cursor[part] !== 'object' || cursor[part] === null) {
            cursor[part] = {};
        }
        cursor = cursor[part] as Record<string, unknown>;
    }

    cursor[parts[parts.length - 1]] = value;
}

/**
 * Turn a response into something worth showing.
 *
 * The handlers behind these tests are inconsistent: some return `{success, error}`, some
 * `{message}`, some add `details` and `guidance`. Normalising here means the schema does
 * not have to describe each one, and a handler that grows a better message improves the
 * V2 surface without a change on this side.
 */
function readOutcome(payload: ConnectionTestResponse | undefined, ok: boolean): TestOutcome {
    const body = payload ?? {};
    const succeeded = ok && body.success !== false;

    return {
        ok: succeeded,
        message:
            body.message ||
            body.error ||
            (succeeded ? 'Connection succeeded.' : 'Connection failed.'),
        details: Array.isArray(body.details) ? body.details : [],
        guidance: Array.isArray(body.guidance) ? body.guidance : [],
    };
}

export function ConnectionTest({
    field,
    settings,
    draft,
    disabled,
}: {
    field: AdminField;
    settings: Json;
    draft: Json;
    disabled?: boolean;
}) {
    const [running, setRunning] = useState(false);
    const [outcome, setOutcome] = useState<TestOutcome | null>(null);

    const read = (key: string): unknown =>
        Object.prototype.hasOwnProperty.call(draft, key) ? draft[key] : settings[key];

    const run = async () => {
        if (!field.test_type) {
            return;
        }

        setRunning(true);
        setOutcome(null);

        const payload: Json = { test_type: field.test_type };
        for (const [path, source] of Object.entries(field.test_payload ?? {})) {
            // A payload entry can be conditional, which is how one declaration covers
            // both sides of an APIM-or-direct choice without sending the branch that is
            // not in use.
            if (!evaluateDependency(source.when, read)) {
                continue;
            }
            const value = source.key !== undefined ? read(source.key) : source.value;
            assignPath(payload, path, value ?? '');
        }

        try {
            const response = await api.post<ConnectionTestResponse>(
                '/api/v2/admin/settings/test-connection',
                payload,
            );
            setOutcome(readOutcome(response, true));
        } catch (caught) {
            if (caught instanceof ApiError) {
                setOutcome(
                    readOutcome(caught.payload as ConnectionTestResponse | undefined, false),
                );
            } else {
                setOutcome({
                    ok: false,
                    message: caught instanceof Error ? caught.message : 'Connection failed.',
                    details: [],
                    guidance: [],
                });
            }
        } finally {
            setRunning(false);
        }
    };

    return (
        <div className="py-3">
            <button
                type="button"
                className={clsx(
                    'flex items-center gap-2 rounded-lg border border-edge px-3 py-2',
                    'text-sm text-text-2 hover:bg-surface-2',
                    'disabled:cursor-not-allowed disabled:opacity-60',
                )}
                disabled={disabled || running}
                onClick={() => void run()}
            >
                {running ? (
                    <Loader2 size={14} className="animate-spin" />
                ) : (
                    <PlugZap size={14} />
                )}
                {running ? 'Testing…' : field.label}
            </button>

            {field.help ? (
                <p className="mt-1.5 text-xs leading-relaxed text-text-3">{field.help}</p>
            ) : null}

            {outcome ? (
                <div
                    role="status"
                    aria-live="polite"
                    className={clsx(
                        'mt-2 rounded-lg border px-3 py-2 text-xs',
                        outcome.ok
                            ? 'border-ok/40 bg-ok/5 text-text-2'
                            : 'border-danger/40 bg-danger/5 text-text-2',
                    )}
                >
                    <div className="flex items-start gap-2">
                        {outcome.ok ? (
                            <CheckCircle2 size={13} className="mt-0.5 shrink-0 text-ok" />
                        ) : (
                            <XCircle size={13} className="mt-0.5 shrink-0 text-danger" />
                        )}
                        <span>{outcome.message}</span>
                    </div>

                    {outcome.details.length ? (
                        <ul className="mt-1.5 ml-5 list-disc space-y-0.5 text-text-3">
                            {outcome.details.map((detail) => (
                                <li key={detail}>{detail}</li>
                            ))}
                        </ul>
                    ) : null}

                    {/* Guidance is what the handler suggests trying next, and it is the
                        most useful part of a failure. */}
                    {outcome.guidance.length ? (
                        <div className="mt-2">
                            <span className="font-medium text-text-2">Try this</span>
                            <ul className="mt-0.5 ml-5 list-disc space-y-0.5 text-text-3">
                                {outcome.guidance.map((hint) => (
                                    <li key={hint}>{hint}</li>
                                ))}
                            </ul>
                        </div>
                    ) : null}
                </div>
            ) : null}
        </div>
    );
}

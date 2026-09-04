// EnhancedCitationsStorageTest.tsx
// On-demand reachability check for the Enhanced Citations storage account.
//
// Startup deliberately skips live storage checks so a storage outage cannot stop the
// application booting, which means a misconfigured account is otherwise only discovered
// when a citation fails to open. This runs the same check the server-rendered admin page
// runs, against the values currently on screen, so a connection string can be validated
// before it is saved.
//
// The credentials are masked, so the draft usually holds the redaction placeholder rather
// than a real secret. That is sent as-is: the test endpoint resolves the placeholder back
// to the stored value, exactly as the settings save does.

import { useState } from 'react';
import { clsx } from 'clsx';
import { CheckCircle2, Loader2, PlugZap, TriangleAlert, XCircle } from 'lucide-react';
import { ApiError, api } from '../../lib/apiClient';
import { GlassButton } from '../ui/primitives';

interface StorageTestResponse {
    success?: boolean;
    status?: string;
    message?: string;
    error?: string;
    details?: string[];
    guidance?: string[];
}

type Outcome = 'success' | 'warning' | 'error';

interface TestResult {
    outcome: Outcome;
    message: string;
    details: string[];
    guidance: string[];
}

const OUTCOME_STYLES: Record<Outcome, { icon: typeof CheckCircle2; className: string }> = {
    success: { icon: CheckCircle2, className: 'text-ok' },
    warning: { icon: TriangleAlert, className: 'text-warn' },
    error: { icon: XCircle, className: 'text-danger' },
};

/** Coerce whatever the endpoint returned into something renderable. */
function toStrings(value: unknown): string[] {
    return Array.isArray(value) ? value.map((item) => String(item)) : [];
}

export function EnhancedCitationsStorageTest({
    help,
    authenticationType,
    connectionString,
    blobEndpoint,
}: {
    help?: string;
    authenticationType: string;
    connectionString: string;
    blobEndpoint: string;
}) {
    const [testing, setTesting] = useState(false);
    const [result, setResult] = useState<TestResult | null>(null);

    const runTest = async () => {
        setTesting(true);
        setResult(null);

        try {
            const response = await api.post<StorageTestResponse>(
                '/api/admin/settings/test_connection',
                {
                    test_type: 'enhanced_citations_storage',
                    authentication_type: authenticationType || 'key',
                    connection_string: connectionString,
                    blob_endpoint: blobEndpoint,
                },
            );

            setResult({
                outcome: response.status === 'warning' ? 'warning' : 'success',
                message: response.message ?? 'Enhanced Citations storage is reachable.',
                details: toStrings(response.details),
                guidance: toStrings(response.guidance),
            });
        } catch (testError) {
            const payload =
                testError instanceof ApiError
                    ? (testError.payload as StorageTestResponse | undefined)
                    : undefined;

            setResult({
                outcome: 'error',
                message:
                    payload?.error ??
                    (testError instanceof Error
                        ? testError.message
                        : 'The storage test could not be completed.'),
                details: toStrings(payload?.details),
                guidance: toStrings(payload?.guidance),
            });
        } finally {
            setTesting(false);
        }
    };

    const styles = result ? OUTCOME_STYLES[result.outcome] : null;
    const Icon = styles?.icon;

    return (
        <div className="py-3">
            <span className="mb-1.5 block text-sm font-medium text-text-1">
                Storage Connection
            </span>

            <GlassButton
                type="button"
                variant="subtle"
                size="sm"
                disabled={testing}
                onClick={() => void runTest()}
            >
                {testing ? (
                    <Loader2 size={14} className="animate-spin" />
                ) : (
                    <PlugZap size={14} />
                )}
                {testing ? 'Testing…' : 'Test storage connection'}
            </GlassButton>

            {help ? <p className="mt-1.5 text-xs leading-relaxed text-text-3">{help}</p> : null}

            {result && Icon ? (
                <div
                    role="status"
                    className="mt-2 rounded-lg border border-edge bg-surface-1 p-3"
                >
                    <p className={clsx('flex items-start gap-1.5 text-sm', styles.className)}>
                        <Icon size={15} className="mt-0.5 shrink-0" />
                        {result.message}
                    </p>

                    {result.details.length ? (
                        <ul className="mt-1.5 ml-5 list-disc text-xs text-text-3">
                            {result.details.map((detail) => (
                                <li key={detail}>{detail}</li>
                            ))}
                        </ul>
                    ) : null}

                    {result.guidance.length ? (
                        <ul className="mt-1.5 ml-5 list-disc text-xs text-text-2">
                            {result.guidance.map((item) => (
                                <li key={item}>{item}</li>
                            ))}
                        </ul>
                    ) : null}
                </div>
            ) : null}
        </div>
    );
}

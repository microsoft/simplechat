// ConnectionTest.tsx
// Inline "does this actually work" check for an integration section.
//
// A misconfigured integration does not announce itself in Admin Settings. Content Safety
// with a wrong key looks identical to Content Safety with a right one until a user sends
// a message and it is blocked, or worse, silently not checked. This runs the same
// `/api/admin/settings/test_connection` probe the server-rendered page uses, against the
// values currently on screen rather than the ones last saved, so a mistake is caught
// before Save rather than after.
//
// Secrets are the reason the payload is built here rather than generically: the browser
// holds a placeholder, not the key, so it sends the placeholder and the endpoint resolves
// it against the stored document.

import { useState } from 'react';
import { clsx } from 'clsx';
import { CheckCircle2, Loader2, PlugZap, XCircle } from 'lucide-react';
import { api } from '../../lib/apiClient';
import { asBoolean, asString, type AdminField } from '../../lib/adminFields';
import type { Json } from '../../lib/types';

interface TestResult {
    ok: boolean;
    message: string;
}

/**
 * Shape the payload each `test_type` branch expects.
 *
 * The endpoint takes a different object per integration, so this is the one place that
 * has to know the difference. Returning null means the section is not configured enough
 * to be worth probing.
 */
function buildPayload(testType: string, read: (key: string) => unknown): Json | null {
    if (testType === 'key_vault') {
        const vaultName = asString(read('key_vault_name')).trim();
        if (!vaultName) {
            return null;
        }
        return {
            test_type: 'key_vault',
            vault_name: vaultName,
            client_id: asString(read('key_vault_identity')).trim(),
        };
    }

    if (testType === 'safety') {
        const useApim = asBoolean(read('enable_content_safety_apim'));
        return {
            test_type: 'safety',
            enabled: true,
            enable_apim: useApim,
            apim: {
                endpoint: asString(read('azure_apim_content_safety_endpoint')).trim(),
                subscription_key: asString(read('azure_apim_content_safety_subscription_key')),
            },
            direct: {
                endpoint: asString(read('content_safety_endpoint')).trim(),
                key: asString(read('content_safety_key')),
                // The endpoint reads `auth_type`, not the settings key name. Sending the
                // settings name would leave the managed identity branch unreachable, so
                // the probe would test the key path on a deployment that does not use it.
                auth_type: asString(read('content_safety_authentication_type'), 'key'),
            },
        };
    }

    return null;
}

export function ConnectionTest({
    field,
    read,
}: {
    field: AdminField;
    read: (key: string) => unknown;
}) {
    const [running, setRunning] = useState(false);
    const [result, setResult] = useState<TestResult | null>(null);

    const run = async () => {
        const payload = buildPayload(field.test_type ?? '', read);
        if (!payload) {
            setResult({
                ok: false,
                message: 'Fill in the connection details above before testing.',
            });
            return;
        }

        setRunning(true);
        setResult(null);
        try {
            const response = await api.post<{ message?: string }>(
                '/api/admin/settings/test_connection',
                payload,
            );
            setResult({ ok: true, message: response.message ?? 'Connection succeeded.' });
        } catch (error) {
            // ApiError already prefers the endpoint's `error` field for its message.
            setResult({
                ok: false,
                message: error instanceof Error ? error.message : 'Connection failed.',
            });
        } finally {
            setRunning(false);
        }
    };

    return (
        <div className="py-3">
            <button
                type="button"
                onClick={() => void run()}
                disabled={running}
                className={clsx(
                    'inline-flex items-center gap-2 rounded-lg border border-edge px-3 py-2',
                    'text-sm font-medium text-text-1 transition-colors',
                    running
                        ? 'cursor-not-allowed opacity-60'
                        : 'hover:border-accent hover:bg-surface-2',
                )}
            >
                {running ? (
                    <Loader2 size={15} className="animate-spin" />
                ) : (
                    <PlugZap size={15} />
                )}
                {field.label}
            </button>

            {field.help ? (
                <p className="mt-1.5 text-xs leading-relaxed text-text-3">{field.help}</p>
            ) : null}

            {result ? (
                <p
                    role="status"
                    className={clsx(
                        'mt-2 flex items-start gap-1.5 rounded-lg px-2.5 py-1.5 text-xs',
                        result.ok ? 'bg-ok-soft text-ok' : 'bg-danger-soft text-danger',
                    )}
                >
                    {result.ok ? (
                        <CheckCircle2 size={13} className="mt-0.5 shrink-0" />
                    ) : (
                        <XCircle size={13} className="mt-0.5 shrink-0" />
                    )}
                    {result.message}
                </p>
            ) : null}
        </div>
    );
}

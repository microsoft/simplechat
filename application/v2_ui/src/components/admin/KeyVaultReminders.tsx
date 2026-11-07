// KeyVaultReminders.tsx
// Inventory of the Key Vault secrets SimpleChat tracks for expiry.
//
// Key Vault secret names written by SimpleChat are content hashes, so an expiry alert
// from Azure names something like `sc-a1b2c3…` and nothing else. Nobody can act on that.
// This is the lookup in the other direction: given the secret name in the alert, who owns
// it, which action or agent it belongs to, which field it fills, and who to contact.
//
// Loaded on demand rather than with the page, because it is a Cosmos query behind a
// section most visits never open.

import { useCallback, useState } from 'react';
import { clsx } from 'clsx';
import { Loader2, PlayCircle, RefreshCw } from 'lucide-react';
import { api } from '../../lib/apiClient';

interface ReminderRow {
    id?: string;
    secret_name?: string;
    scope?: string;
    scope_value?: string;
    source_display_name?: string;
    source_name?: string;
    source_id?: string;
    field_label?: string;
    field_path?: string;
    contact_email?: string;
    status?: string;
    key_vault_sync_status?: string;
    key_vault_sync_error?: string;
    expires_on?: string;
    days_until_expiry?: number;
}

const STATUS_OPTIONS = [
    { value: '', label: 'All statuses' },
    { value: 'active', label: 'Active' },
    { value: 'sync_failed', label: 'Sync failed' },
    { value: 'disabled', label: 'Disabled' },
];

/** Expiry with its distance from today, which is what makes a date actionable. */
function formatExpiry(reminder: ReminderRow): string {
    const expiresOn = reminder.expires_on || 'Unknown';
    const days = reminder.days_until_expiry;
    if (typeof days !== 'number') {
        return expiresOn;
    }
    if (days < 0) {
        return `${expiresOn} (${Math.abs(days)} days expired)`;
    }
    if (days === 0) {
        return `${expiresOn} (today)`;
    }
    return `${expiresOn} (${days} days)`;
}

function formatStatus(reminder: ReminderRow): string {
    if (reminder.key_vault_sync_status === 'sync_failed') {
        return `${reminder.status || 'sync_failed'}: ${
            reminder.key_vault_sync_error || 'Key Vault sync failed'
        }`;
    }
    return reminder.status || '';
}

const controlClass = clsx(
    'rounded-lg border border-edge bg-surface-1 px-2.5 py-1.5',
    'text-xs text-text-1 placeholder:text-text-3 focus:border-accent focus:outline-none',
);

const buttonClass = clsx(
    'inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-edge px-2.5 py-1.5',
    'text-xs font-medium text-text-1 transition-colors',
    'hover:border-accent hover:bg-surface-2 disabled:cursor-not-allowed disabled:opacity-60',
);

export function KeyVaultReminders({ label, help }: { label: string; help?: string }) {
    const [rows, setRows] = useState<ReminderRow[] | null>(null);
    const [search, setSearch] = useState('');
    const [status, setStatus] = useState('');
    const [loading, setLoading] = useState(false);
    const [sweeping, setSweeping] = useState(false);
    const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);

    const load = useCallback(async () => {
        setLoading(true);
        setMessage(null);
        try {
            const params = new URLSearchParams();
            if (search.trim()) {
                params.set('search', search.trim());
            }
            if (status) {
                params.set('status', status);
            }
            const query = params.toString();
            const response = await api.get<{ reminders?: ReminderRow[] }>(
                `/api/admin/settings/key-vault/secret-reminders${query ? `?${query}` : ''}`,
            );
            setRows(response.reminders ?? []);
        } catch (error) {
            setMessage({
                ok: false,
                text: error instanceof Error ? error.message : 'Failed to load inventory.',
            });
        } finally {
            setLoading(false);
        }
    }, [search, status]);

    const runSweep = useCallback(async () => {
        setSweeping(true);
        setMessage(null);
        try {
            await api.post('/api/admin/settings/key-vault/secret-reminders/run');
            setMessage({ ok: true, text: 'Sweep completed. Reloading inventory…' });
            await load();
        } catch (error) {
            setMessage({
                ok: false,
                text: error instanceof Error ? error.message : 'Failed to run the sweep.',
            });
        } finally {
            setSweeping(false);
        }
    }, [load]);

    return (
        <div className="py-3">
            <p className="mb-1.5 text-sm font-medium text-text-1">{label}</p>
            {help ? <p className="mb-2 text-xs leading-relaxed text-text-3">{help}</p> : null}

            <div className="mb-2 flex flex-wrap gap-2">
                <input
                    type="search"
                    value={search}
                    onChange={(event) => setSearch(event.target.value)}
                    onKeyDown={(event) => {
                        if (event.key === 'Enter') {
                            event.preventDefault();
                            void load();
                        }
                    }}
                    placeholder="Owner, action, field, email, reminder ID or secret name"
                    aria-label="Search tracked secrets"
                    className={clsx(controlClass, 'min-w-48 flex-1')}
                />
                <select
                    value={status}
                    onChange={(event) => setStatus(event.target.value)}
                    aria-label="Reminder status filter"
                    className={controlClass}
                >
                    {STATUS_OPTIONS.map((option) => (
                        <option key={option.value} value={option.value}>
                            {option.label}
                        </option>
                    ))}
                </select>
                <button
                    type="button"
                    className={buttonClass}
                    disabled={loading}
                    onClick={() => void load()}
                >
                    {loading ? (
                        <Loader2 size={13} className="animate-spin" />
                    ) : (
                        <RefreshCw size={13} />
                    )}
                    Refresh
                </button>
                <button
                    type="button"
                    className={buttonClass}
                    disabled={sweeping}
                    onClick={() => void runSweep()}
                >
                    {sweeping ? (
                        <Loader2 size={13} className="animate-spin" />
                    ) : (
                        <PlayCircle size={13} />
                    )}
                    Run sweep
                </button>
            </div>

            {message ? (
                <p
                    role="status"
                    className={clsx(
                        'mb-2 rounded-lg px-2.5 py-1.5 text-xs',
                        message.ok ? 'bg-ok-soft text-ok' : 'bg-danger-soft text-danger',
                    )}
                >
                    {message.text}
                </p>
            ) : null}

            <div className="overflow-x-auto rounded-lg border border-edge">
                <table className="w-full text-left text-xs">
                    <thead className="bg-surface-2 text-text-3">
                        <tr>
                            <th scope="col" className="px-2.5 py-1.5 font-medium">Expires</th>
                            <th scope="col" className="px-2.5 py-1.5 font-medium">Scope</th>
                            <th scope="col" className="px-2.5 py-1.5 font-medium">Source</th>
                            <th scope="col" className="px-2.5 py-1.5 font-medium">Field</th>
                            <th scope="col" className="px-2.5 py-1.5 font-medium">Contact</th>
                            <th scope="col" className="px-2.5 py-1.5 font-medium">Status</th>
                            <th scope="col" className="px-2.5 py-1.5 font-medium">Reminder ID</th>
                            <th scope="col" className="px-2.5 py-1.5 font-medium">Secret</th>
                        </tr>
                    </thead>
                    <tbody className="divide-y divide-edge">
                        {rows === null ? (
                            <tr>
                                <td colSpan={8} className="px-2.5 py-3 text-text-3">
                                    Refresh to load tracked secrets.
                                </td>
                            </tr>
                        ) : rows.length === 0 ? (
                            <tr>
                                <td colSpan={8} className="px-2.5 py-3 text-text-3">
                                    No tracked secrets match the current filters.
                                </td>
                            </tr>
                        ) : (
                            rows.map((reminder, index) => (
                                <tr key={reminder.id ?? index} className="text-text-2">
                                    <td className="px-2.5 py-1.5">{formatExpiry(reminder)}</td>
                                    <td className="px-2.5 py-1.5">
                                        {[reminder.scope, reminder.scope_value]
                                            .filter(Boolean)
                                            .join(': ')}
                                    </td>
                                    <td className="px-2.5 py-1.5">
                                        {reminder.source_display_name ||
                                            reminder.source_name ||
                                            reminder.source_id ||
                                            ''}
                                    </td>
                                    <td className="px-2.5 py-1.5">
                                        {reminder.field_label || reminder.field_path || ''}
                                    </td>
                                    <td className="px-2.5 py-1.5">{reminder.contact_email || ''}</td>
                                    <td className="px-2.5 py-1.5">{formatStatus(reminder)}</td>
                                    <td className="px-2.5 py-1.5 font-mono">{reminder.id || ''}</td>
                                    <td className="px-2.5 py-1.5 font-mono">
                                        {reminder.secret_name || ''}
                                    </td>
                                </tr>
                            ))
                        )}
                    </tbody>
                </table>
            </div>
        </div>
    );
}

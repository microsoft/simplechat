// RetentionCard.tsx
// How long the signed-in user's own conversations and documents are kept.
//
// Mirrors the classic profile page's Retention Policy section and saves through the same
// route (POST /api/retention-policy/user), so the stored `retention_policy` is the one the
// nightly retention run reads. Shown only when an administrator turned on personal retention.
//
// Unlike the other preferences this one is saved with a button: choosing a shorter period
// means items older than it are deleted at the next run, so it should be a deliberate step.

import { useEffect, useMemo, useState } from 'react';
import { Hourglass } from 'lucide-react';
import { api, ApiError } from '../../lib/apiClient';
import type { UserSettings } from '../../lib/userSettings';
import { useUserSettingsStore } from '../../stores/userSettingsStore';
import { toast } from '../../stores/toastStore';
import { SettingsCard } from './SettingsCard';

/** The classic profile page's choices, in its order. */
export const PERSONAL_RETENTION_DAYS = [1, 2, 3, 4, 5, 6, 7, 10, 14, 21, 30, 60, 90, 180, 365, 730] as const;

const DAY_LABELS: Record<number, string> = {
    1: '1 day',
    7: '7 days (1 week)',
    14: '14 days (2 weeks)',
    21: '21 days (3 weeks)',
    90: '90 days (3 months)',
    180: '180 days (6 months)',
    365: '365 days (1 year)',
    730: '730 days (2 years)',
};

function dayLabel(days: number): string {
    return DAY_LABELS[days] ?? `${days} days`;
}

interface RetentionDefaults {
    success?: boolean;
    default_conversation_label?: string;
    default_document_label?: string;
}

/** A stored value as the select reads it: 'default' when nothing has been chosen. */
export function readRetentionChoice(value: unknown): string {
    if (value === undefined || value === null || value === '') {
        return 'default';
    }
    return String(value);
}

function choices(current: string): { value: string; label: string }[] {
    const days: number[] = [...PERSONAL_RETENTION_DAYS];
    const numeric = Number(current);
    // A period set elsewhere that this list doesn't offer stays selectable.
    if (current !== 'default' && current !== 'none' && Number.isInteger(numeric) && !days.includes(numeric)) {
        days.push(numeric);
        days.sort((left, right) => left - right);
    }
    return [
        { value: 'none', label: 'No automatic deletion' },
        ...days.map((value) => ({ value: String(value), label: dayLabel(value) })),
    ];
}

const SELECT_CLASS =
    'mt-1.5 w-full rounded-lg border border-edge bg-surface-solid px-2.5 py-2 text-sm text-text-1';

export function RetentionCard({ settings }: { settings: UserSettings }) {
    const stored = useMemo(() => {
        const policy = (settings.retention_policy ?? {}) as Record<string, unknown>;
        return {
            conversation: readRetentionChoice(policy.conversation_retention_days),
            document: readRetentionChoice(policy.document_retention_days),
        };
    }, [settings.retention_policy]);
    const [conversation, setConversation] = useState(stored.conversation);
    const [document, setDocument] = useState(stored.document);
    const [defaults, setDefaults] = useState<RetentionDefaults | null>(null);
    const [saving, setSaving] = useState(false);

    useEffect(() => {
        setConversation(stored.conversation);
        setDocument(stored.document);
    }, [stored]);

    useEffect(() => {
        const controller = new AbortController();
        api.get<RetentionDefaults>('/api/retention-policy/defaults/personal', controller.signal)
            .then((response) => setDefaults(response))
            .catch(() => undefined);
        return () => controller.abort();
    }, []);

    const dirty = conversation !== stored.conversation || document !== stored.document;

    const save = async () => {
        setSaving(true);
        try {
            await api.post('/api/retention-policy/user', {
                conversation_retention_days: conversation,
                document_retention_days: document,
            });
            // The route writes `retention_policy` itself; reflect it locally without a second write.
            useUserSettingsStore.setState((state) => ({
                settings: {
                    ...state.settings,
                    retention_policy: {
                        conversation_retention_days: conversation,
                        document_retention_days: document,
                    },
                },
            }));
            toast.success('Retention settings saved.');
        } catch (error) {
            toast.error(error instanceof ApiError || error instanceof Error ? error.message : 'Retention settings could not be saved.');
        } finally {
            setSaving(false);
        }
    };

    const field = (
        label: string,
        value: string,
        onChange: (next: string) => void,
        defaultLabel: string | undefined,
        help: string,
    ) => (
        <label className="block">
            <span className="block text-sm font-medium text-text-1">{label}</span>
            <select value={value} onChange={(event) => onChange(event.target.value)} className={SELECT_CLASS}>
                <option value="default">
                    {defaultLabel ? `Organization default (${defaultLabel})` : 'Organization default'}
                </option>
                {choices(value).map((choice) => (
                    <option key={choice.value} value={choice.value}>
                        {choice.label}
                    </option>
                ))}
            </select>
            <span className="mt-1 block text-xs text-text-3">{help}</span>
        </label>
    );

    return (
        <SettingsCard
            title="Retention"
            Icon={Hourglass}
            description="How long your own conversations and documents are kept before they are deleted automatically. Follow your organization's default, keep them indefinitely, or choose your own period."
            actions={(
                <button
                    type="button"
                    onClick={() => void save()}
                    disabled={!dirty || saving}
                    className="rounded-lg bg-accent px-3 py-1.5 text-sm font-medium text-on-accent hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
                >
                    {saving ? 'Saving…' : 'Save'}
                </button>
            )}
        >
            <div className="grid gap-4 sm:grid-cols-2">
                {field(
                    'Conversations',
                    conversation,
                    setConversation,
                    defaults?.default_conversation_label,
                    'Conversations older than this are deleted.',
                )}
                {field(
                    'Documents',
                    document,
                    setDocument,
                    defaults?.default_document_label,
                    'Documents older than this are deleted.',
                )}
            </div>
            <p className="mt-3 rounded-lg border border-warn/30 bg-warn-soft px-3 py-2 text-xs text-text-2">
                Deleted conversations are archived first when your organization has archiving turned on, and every
                deletion is recorded in the activity history.
            </p>
        </SettingsCard>
    );
}

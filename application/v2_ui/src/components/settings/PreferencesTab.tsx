// PreferencesTab.tsx
// Preferences that change how this interface behaves for the signed-in user.
//
// A section appears only when the capability it controls is enabled, and only settings this
// interface actually honours are offered. A toggle that silently changes nothing here — or
// worse, only changes the classic interface — is more confusing than its absence, so the
// remaining classic preferences are deliberately left to that page until V2 implements the
// behaviour behind them.

import { useEffect } from 'react';
import { clsx } from 'clsx';
import { useUserSettingsStore } from '../../stores/userSettingsStore';
import { useBootstrapStore } from '../../stores/bootstrapStore';
import {
    FONT_SIZE_LABELS,
    FONT_SIZE_PREFERENCES,
    type FontSizePreference,
} from '../../lib/userSettings';
import { Toggle, Skeleton } from '../ui/primitives';
import { SettingsSection } from './TabScaffold';

/** Voices offered for spoken replies, matching what the speech endpoint accepts. */
const TTS_VOICES = [
    { id: '', label: 'Deployment default' },
    { id: 'en-US-AriaNeural', label: 'Aria (US)' },
    { id: 'en-US-GuyNeural', label: 'Guy (US)' },
    { id: 'en-US-JennyNeural', label: 'Jenny (US)' },
    { id: 'en-GB-SoniaNeural', label: 'Sonia (UK)' },
    { id: 'en-GB-RyanNeural', label: 'Ryan (UK)' },
    { id: 'en-AU-NatashaNeural', label: 'Natasha (AU)' },
];

function FontSizeChoice({
    value,
    onChange,
}: {
    value: FontSizePreference;
    onChange: (next: FontSizePreference) => void;
}) {
    return (
        <div role="radiogroup" aria-label="Text size" className="flex flex-wrap gap-1.5">
            {FONT_SIZE_PREFERENCES.map((size) => (
                <button
                    key={size}
                    type="button"
                    role="radio"
                    aria-checked={size === value}
                    onClick={() => onChange(size)}
                    className={clsx(
                        'rounded-lg border px-3 py-1.5 text-sm transition-colors',
                        size === value
                            ? 'border-accent bg-accent-soft font-medium text-accent'
                            : 'border-edge text-text-2 hover:bg-surface-2 hover:text-text-1',
                    )}
                >
                    {FONT_SIZE_LABELS[size]}
                </button>
            ))}
        </div>
    );
}

export function PreferencesTab() {
    const { settings, loading, error, update, saveError } = useUserSettingsStore();
    const features = useBootstrapStore((state) => state.data?.features ?? {});
    const enabled = (key: string) => features[key] === true;

    const fontSize = (settings.fontSizePreference as FontSizePreference) || 'm';

    // Applied here as well as at startup so the change is visible while it is being chosen,
    // rather than only after a reload.
    useEffect(() => {
        document.documentElement.dataset.fontSize = fontSize;
    }, [fontSize]);

    if (loading) {
        return (
            <div className="space-y-3">
                <Skeleton className="h-28 w-full" />
                <Skeleton className="h-28 w-full" />
                <Skeleton className="h-28 w-full" />
            </div>
        );
    }

    if (error) {
        return (
            <p className="rounded-xl border border-danger/30 bg-danger-soft px-4 py-3 text-sm text-danger">
                {error}
            </p>
        );
    }

    return (
        <div className="space-y-3">
            {saveError && (
                <p className="rounded-xl border border-danger/30 bg-danger-soft px-4 py-2 text-xs text-danger">
                    {saveError}
                </p>
            )}

            <SettingsSection
                title="Text size"
                description="Scales the whole interface, not only body text. Shared with the classic interface, so the two match."
            >
                <FontSizeChoice
                    value={fontSize}
                    onChange={(next) => update({ fontSizePreference: next })}
                />
            </SettingsSection>

            <SettingsSection
                title="Conversation list"
                description="What the list of conversations shows alongside each title."
            >
                <Toggle
                    checked={settings.showConversationWorkspaceTags !== false}
                    onChange={(next) => update({ showConversationWorkspaceTags: next })}
                    label="Show workspace tags"
                    description="Label conversations that belong to a group or public workspace, or that are shared with other people. Personal conversations stay unlabelled."
                />
            </SettingsSection>

            {enabled('enable_conversation_contents_drawer') && (
                <SettingsSection
                    title="Conversation navigation"
                    description="A contents drawer for jumping between your own prompts in a long conversation."
                >
                    <Toggle
                        checked={settings.conversationContentsDrawerEnabled !== false}
                        onChange={(next) =>
                            update({ conversationContentsDrawerEnabled: next })
                        }
                        label="Show the conversation contents drawer"
                    />
                </SettingsSection>
            )}

            {enabled('enable_text_to_speech') && (
                <SettingsSection
                    title="Spoken replies"
                    description="The voice used when you play an assistant message aloud."
                >
                    <label className="block">
                        <span className="block text-sm font-medium text-text-1">Voice</span>
                        <select
                            value={String(settings.ttsVoice ?? '')}
                            onChange={(event) => update({ ttsVoice: event.target.value })}
                            className="mt-1.5 w-full max-w-xs rounded-lg border border-edge bg-surface-solid px-2.5 py-2 text-sm text-text-1"
                        >
                            {TTS_VOICES.map((voice) => (
                                <option key={voice.id} value={voice.id}>
                                    {voice.label}
                                </option>
                            ))}
                        </select>
                    </label>
                </SettingsSection>
            )}

            {enabled('enable_desktop_notifications') && (
                <SettingsSection
                    title="Desktop notifications"
                    description="A notification from your operating system when a reply finishes while this tab is hidden or unfocused."
                >
                    <Toggle
                        checked={settings.desktopNotificationsEnabled !== false}
                        onChange={(next) => update({ desktopNotificationsEnabled: next })}
                        label="Notify me when a reply is ready"
                    />
                </SettingsSection>
            )}
        </div>
    );
}

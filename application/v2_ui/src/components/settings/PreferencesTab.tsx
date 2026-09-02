// PreferencesTab.tsx
// Preferences that change how this interface behaves for the signed-in user.
//
// Sections appear only when the capability they control is enabled, because a control for a
// disabled feature does nothing and only raises questions.

import { useUserSettingsStore } from '../../stores/userSettingsStore';
import { useBootstrapStore } from '../../stores/bootstrapStore';
import { Toggle, Skeleton } from '../ui/primitives';
import { SettingsSection } from './TabScaffold';

export function PreferencesTab() {
    const { settings, loading, error, update, saveError } = useUserSettingsStore();
    const features = useBootstrapStore((state) => state.data?.features ?? {});
    const enabled = (key: string) => features[key] === true;

    if (loading) {
        return (
            <div className="space-y-3">
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
        </div>
    );
}

// agentSectionAppearance.ts

import { UserRound, UsersRound } from 'lucide-react';
import type { SettingsSectionAppearance } from './SettingsSection';
import { RETENTION_SCOPE_ICONS } from './retentionScopeIcons';

// Presentation only: field order, visibility, and status still come from the schema.
//
// Section icons now come from the navigation definition, and which switch leads which
// settings is derived from `depends_on`, so the Agent Runtime emphasis no longer needs
// declaring here. What remains are cues the schema cannot express: whether a workspace
// permission applies to a person or to a group, and which workspace type each retention
// switch governs.
export const agentSectionAppearances: Readonly<
    Partial<Record<string, SettingsSectionAppearance>>
> = {
    'agent-toggles-card': {
        Icon: UsersRound,
        fields: {
            allow_user_agents: { Icon: UserRound },
            allow_group_agents: { Icon: UsersRound },
            allow_user_custom_endpoints: { Icon: UserRound },
            allow_group_custom_endpoints: { Icon: UsersRound },
        },
    },
    // The three workspace types are peers, so the first is not promoted to the switch the
    // card is about, which is what the derived hierarchy would otherwise do with it.
    'retention-policy-section': {
        fields: {
            enable_retention_policy_personal: { Icon: RETENTION_SCOPE_ICONS.personal, emphasis: 'none' },
            enable_retention_policy_group: { Icon: RETENTION_SCOPE_ICONS.group },
            enable_retention_policy_public: { Icon: RETENTION_SCOPE_ICONS.public },
        },
    },
};

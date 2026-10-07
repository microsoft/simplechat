// agentSectionAppearance.ts

import { Globe, UserRound, UsersRound } from 'lucide-react';
import type { SettingsSectionAppearance } from './SettingsSection';

// Presentation only: field order, visibility, and status still come from the schema.
//
// Section icons now come from the navigation definition, and which switch leads which
// settings is derived from `depends_on`, so the Agent Runtime emphasis no longer needs
// declaring here. What remains is the one cue the schema cannot express: whether a
// setting applies to a person, to a group, or to everyone.
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
    // The schema pairs each personal switch with its group counterpart, so on a wide card
    // the person icon leads the left column and the group icon the right.
    'governance-feature-toggles-section': {
        fields: {
            governance_user_endpoints: { Icon: UserRound },
            governance_user_agents: { Icon: UserRound },
            governance_user_actions: { Icon: UserRound },
            governance_group_endpoints: { Icon: UsersRound },
            governance_group_agents: { Icon: UsersRound },
            governance_group_actions: { Icon: UsersRound },
            governance_global_endpoints: { Icon: Globe },
            governance_global_agents_usage: { Icon: Globe },
            governance_global_actions_usage: { Icon: Globe },
        },
    },
};

// agentSectionAppearance.ts

import { UserRound, UsersRound } from 'lucide-react';
import type { SettingsSectionAppearance } from './SettingsSection';

// Presentation only: field order, visibility, and status still come from the schema.
//
// Section icons now come from the navigation definition, and which switch leads which
// settings is derived from `depends_on`, so the Agent Runtime emphasis no longer needs
// declaring here. What remains is the one cue the schema cannot express: whether a
// workspace permission applies to a person or to a group.
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
};

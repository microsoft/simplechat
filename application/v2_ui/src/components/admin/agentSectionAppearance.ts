// agentSectionAppearance.ts

import { Bot, Layers, Palette, UserRound, UsersRound } from 'lucide-react';
import type { SettingsSectionAppearance } from './SettingsSection';

// Presentation only: field order, visibility, and status still come from the schema.
export const agentSectionAppearances: Readonly<
    Partial<Record<string, SettingsSectionAppearance>>
> = {
    'agents-config': {
        Icon: Bot,
        fields: {
            enable_semantic_kernel: { emphasis: 'primary' },
            per_user_semantic_kernel: { emphasis: 'dependent' },
            merge_global_semantic_kernel_with_workspace: { emphasis: 'dependent' },
        },
    },
    'agent-toggles-card': {
        Icon: UsersRound,
        fields: {
            allow_user_agents: { Icon: UserRound },
            allow_group_agents: { Icon: UsersRound },
            allow_user_custom_endpoints: { Icon: UserRound },
            allow_group_custom_endpoints: { Icon: UsersRound },
        },
    },
    'agents-page-customization-card': { Icon: Palette },
    'agent-template-approvals-section': { Icon: Layers },
};

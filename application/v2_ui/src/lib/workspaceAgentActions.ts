// workspaceAgentActions.ts

import { actionTarget, referenceKey, type AgentTargetCatalog } from './agentDelegation';
import type { ActionConfiguration, AgentConfiguration } from './workspaceAuthoring';
import { agentObject, agentText, updateAgentSetting } from './workspaceAgentAuthoring';

export interface AgentActionCapability {
    key: string;
    label: string;
    defaultEnabled?: boolean;
}

const capabilityList = (items: [string, string][]): AgentActionCapability[] =>
    items.map(([key, label]) => ({ key, label }));

// Matches the three capability families in the V1 agent controller and runtime plugins.
export const AGENT_ACTION_CAPABILITIES: Record<string, AgentActionCapability[]> = {
    simplechat: [
        ...capabilityList([
            ['create_group', 'Create groups'],
            ['add_group_member', 'Add users to groups'],
            ['make_group_inactive', 'Make groups inactive'],
            ['create_group_conversation', 'Create group multi-user conversations'],
            ['invite_group_conversation_members', 'Invite group conversation members'],
            ['create_personal_conversation', 'Create personal conversations'],
            ['create_personal_workflow', 'Create personal workflows'],
            ['add_conversation_message', 'Add conversation messages'],
            ['upload_markdown_document', 'Upload markdown documents'],
            ['upload_word_document', 'Upload Word documents'],
            ['upload_powerpoint_document', 'Upload PowerPoint documents'],
            ['create_personal_collaboration_conversation', 'Create personal collaborative conversations'],
        ]),
        { key: 'raise_workflow_alert', label: 'Raise workflow alerts', defaultEnabled: false },
    ],
    msgraph: capabilityList([
        ['get_my_profile', 'Read my profile'],
        ['get_my_timezone', 'Read my mailbox timezone'],
        ['get_my_events', 'Read my calendar events'],
        ['create_calendar_invite', 'Create calendar invites'],
        ['get_my_messages', 'Read my mail'],
        ['mark_message_as_read', 'Update message read state'],
        ['send_mail', 'Send mail'],
        ['search_users', 'Search directory users'],
        ['get_user_by_email', 'Lookup user by email'],
        ['list_drive_items', 'List OneDrive items'],
        ['get_my_security_alerts', 'Read my security alerts'],
    ]),
    chart: capabilityList([
        ['line', 'Line charts'], ['bar', 'Bar charts'], ['pie', 'Pie charts'],
        ['doughnut', 'Doughnut charts'], ['scatter', 'Scatter plots'], ['area', 'Area charts'],
        ['bubble', 'Bubble charts'], ['radar', 'Radar charts'],
        ['stacked_bar', 'Stacked bar charts'], ['stacked_line', 'Stacked line charts'],
    ]),
};

export function agentActionLabel(action: ActionConfiguration): string {
    return action.displayName || agentText(action.display_name) || action.name || 'Untitled action';
}

export function resolveAgentAction(reference: string, actions: ActionConfiguration[]): ActionConfiguration | undefined {
    const byId = actions.filter((action) => action.id === reference);
    if (byId.length === 1) return byId[0];
    if (byId.length > 1) return undefined;
    const byName = actions.filter((action) => action.name === reference);
    return byName.length === 1 ? byName[0] : undefined;
}

export function agentHasAction(draft: AgentConfiguration, action: ActionConfiguration, actions: ActionConfiguration[]): boolean {
    return draft.actions_to_load.some((reference) => resolveAgentAction(reference, actions) === action);
}

export function toggleAgentAction(
    draft: AgentConfiguration, action: ActionConfiguration, enabled: boolean, actions: ActionConfiguration[],
): AgentConfiguration {
    return {
        ...draft,
        actions_to_load: enabled
            ? agentHasAction(draft, action, actions) ? draft.actions_to_load : [...draft.actions_to_load, action.id || action.name]
            : draft.actions_to_load.filter((reference) => resolveAgentAction(reference, actions) !== action),
    };
}

export function agentActionUnavailableReason(
    draft: AgentConfiguration,
    action: ActionConfiguration,
    targets: AgentTargetCatalog | null,
    ownerId: string,
): string | null {
    if (action.is_enabled === false) return 'This action is disabled.';
    if (action.type !== 'agent') return null;
    const target = actionTarget(action);
    if (!target) return 'The target agent reference is incomplete.';
    const scope = draft.is_global ? 'global' : 'personal';
    if (draft.id && target.id === draft.id && target.scope_type === scope &&
        target.scope_id === (scope === 'global' ? 'global' : agentText(draft.user_id) || ownerId)) {
        return 'This action calls this same agent. Direct self-calls are blocked.';
    }
    if (!targets) return 'Load the authorized target catalogue before assigning this action.';
    if (!action.is_global && targets.can_manage !== true) {
        return 'New personal Call agent attachments are unavailable under your current permissions.';
    }
    if (!targets.targets.some((item) => referenceKey(item) === referenceKey(target))) return 'The target agent is no longer available to you.';
    return null;
}

export function newAgentActionErrors(
    draft: AgentConfiguration,
    previous: AgentConfiguration | null,
    actions: ActionConfiguration[],
    targets: AgentTargetCatalog | null,
    ownerId: string,
): string[] {
    if (draft.agent_type !== 'local') return [];
    return draft.actions_to_load.filter((reference) => !previous?.actions_to_load.includes(reference)).flatMap((reference) => {
        const action = resolveAgentAction(reference, actions);
        if (!action) return [];
        const reason = agentActionUnavailableReason(draft, action, targets, ownerId);
        return reason ? [`${agentActionLabel(action)}: ${reason}`] : [];
    });
}

export function agentActionCapabilities(draft: AgentConfiguration, action: ActionConfiguration): Record<string, unknown> {
    const definitions = AGENT_ACTION_CAPABILITIES[action.type] ?? [];
    const field = `${action.type}_capabilities`;
    const defaults = agentObject(action.additionalFields[field] ?? agentObject(action.additional_fields)[field] ?? action[field]);
    const map = agentObject(draft.other_settings.action_capabilities);
    const stored = agentObject(map[action.id] ?? map[action.name]);
    const values: Record<string, unknown> = { ...stored };
    for (const definition of definitions) {
        values[definition.key] = Object.hasOwn(stored, definition.key) ? Boolean(stored[definition.key])
            : Object.hasOwn(defaults, definition.key) ? Boolean(defaults[definition.key])
            : definition.defaultEnabled !== false;
    }
    if (action.type === 'simplechat') {
        for (const key of ['upload_word_document', 'upload_powerpoint_document']) {
            if (!Object.hasOwn(stored, key) && Object.hasOwn(stored, 'upload_markdown_document')) {
                values[key] = Boolean(stored.upload_markdown_document);
            } else if (!Object.hasOwn(stored, key) && !Object.hasOwn(defaults, key) && Object.hasOwn(defaults, 'upload_markdown_document')) {
                values[key] = Boolean(defaults.upload_markdown_document);
            }
        }
    }
    return values;
}

export function updateAgentCapability(
    draft: AgentConfiguration, action: ActionConfiguration, key: string, enabled: boolean,
): AgentConfiguration {
    const map = agentObject(draft.other_settings.action_capabilities);
    const storedKey = Object.hasOwn(map, action.id) ? action.id
        : Object.hasOwn(map, action.name) ? action.name : action.id || action.name;
    return updateAgentSetting(draft, 'action_capabilities', {
        [storedKey]: { ...agentActionCapabilities(draft, action), [key]: enabled },
    });
}

export function agentSelectedActionsContext(draft: AgentConfiguration, actions: ActionConfiguration[]) {
    if (draft.agent_type !== 'local') return [];
    return draft.actions_to_load.map((reference) => {
        const action = resolveAgentAction(reference, actions);
        if (!action) return { id: reference, name: reference, display_name: reference, type: 'unavailable', description: 'Unresolved saved reference', capabilities: [] };
        const values = agentActionCapabilities(draft, action);
        return {
            id: action.id, name: action.name, display_name: agentActionLabel(action),
            description: action.description, type: action.type, is_global: Boolean(action.is_global),
            capabilities: (AGENT_ACTION_CAPABILITIES[action.type] ?? []).filter((item) => Boolean(values[item.key])),
        };
    });
}

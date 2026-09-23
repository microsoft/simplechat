// workspaceActionTypes.ts

import type { Dispatch, SetStateAction } from 'react';
import type { ActionConfiguration, AuthoringResource } from './workspaceAuthoring';

export interface ActionIdentity {
    id: string;
    name: string;
    auth_type: string;
    description?: string;
    scope_type?: string;
    scope_id?: string;
}

/**
 * The group a connection test runs in. Present only for group actions, whose test payload carries
 * `action_scope: 'group'` and the group id, never the personal payload. Absent for personal and
 * global actions.
 */
export interface ActionTestGroupScope {
    id: string;
    name?: string;
}

export interface ActionConnectorProps {
    draft: ActionConfiguration;
    original: AuthoringResource<ActionConfiguration> | null;
    onChange: Dispatch<SetStateAction<ActionConfiguration>>;
    readOnly: boolean;
    errors: Record<string, string>;
    onValidityChange: (key: string, message: string | null) => void;
    identities: ActionIdentity[];
    identitiesLoading: boolean;
    identitiesError: string | null;
    /** Set when the action belongs to a group, so connector tests send the group test payload. */
    groupScope?: ActionTestGroupScope;
}

export interface ActionFieldDescriptor {
    path: string;
    label: string;
    kind?: 'text' | 'textarea' | 'number' | 'boolean' | 'select' | 'secret' | 'lines' | 'json';
    help?: string;
    placeholder?: string;
    required?: boolean;
    min?: number;
    max?: number;
    step?: number;
    options?: { value: string; label: string }[];
    visible?: (draft: ActionConfiguration) => boolean;
    readOnly?: boolean;
}

export interface ActionCapability {
    key: string;
    label: string;
    description: string;
    defaultEnabled?: boolean;
}

export interface ActionNativeDefinition {
    fields: ActionFieldDescriptor[];
    defaults?: Partial<ActionConfiguration>;
    help?: string;
    internal?: boolean;
    testPath?: string;
    identityTypes?: string[];
    capabilities?: { path: string; options: ActionCapability[] };
}

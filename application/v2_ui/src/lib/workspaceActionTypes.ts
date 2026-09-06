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

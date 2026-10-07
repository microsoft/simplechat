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

/**
 * A global action's test, discovery and validation run in the global scope, which the server opens
 * only to administrators and resolves stored credentials from the global Key Vault namespace.
 */
export interface ActionTestGlobalScope {
    global: true;
}

/** The scope a connector command runs in; absent for personal actions. */
export type ActionTestScope = ActionTestGroupScope | ActionTestGlobalScope;

export const GLOBAL_ACTION_TEST_SCOPE: ActionTestGlobalScope = { global: true };

export function isGlobalActionTestScope(scope?: ActionTestScope): scope is ActionTestGlobalScope {
    return Boolean(scope && 'global' in scope && scope.global === true);
}

export function isGroupActionTestScope(scope?: ActionTestScope): scope is ActionTestGroupScope {
    return Boolean(scope && 'id' in scope && typeof scope.id === 'string');
}

/** The `action_scope` a connector payload names. */
export function actionTestScopeName(scope?: ActionTestScope): 'personal' | 'group' | 'global' {
    return isGlobalActionTestScope(scope) ? 'global' : isGroupActionTestScope(scope) ? 'group' : 'personal';
}

/** The scope a connector command should run in, from the editor's connector props. */
export function connectorTestScope(props: Pick<ActionConnectorProps, 'groupScope' | 'globalScope'>): ActionTestScope | undefined {
    return props.groupScope ?? (props.globalScope ? GLOBAL_ACTION_TEST_SCOPE : undefined);
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
    /**
     * Whether the identity list was resolvable at all in this scope. False when the group forbids
     * listing identities (a member gets 403); the connector then keeps neutral "kept as is" copy
     * rather than treating the empty list as "none configured".
     */
    identitiesResolvable: boolean;
    /** Set when the action belongs to a group, so connector tests send the group test payload. */
    groupScope?: ActionTestGroupScope;
    /**
     * Set when an administrator edits a global action, so connector commands run in the global
     * scope and MCP preconfigurations are read for global actions.
     */
    globalScope?: boolean;
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

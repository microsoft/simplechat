// actionCredentialTypes.ts

import type { ConversationKind } from './endpoints';

export type CredentialSlot = 'service' | 'proxy';
export type PersonalCredentialAuth = 'username_password' | 'api_key' | 'bearer_token';

export interface ActionCredentialRequirements {
    version: 1;
    slots: Partial<Record<CredentialSlot, { source: 'personal'; auth_type: PersonalCredentialAuth }>>;
}

export interface CredentialRequest {
    id: string;
    etag: string;
    conversation_id: string;
    conversation_kind?: ConversationKind;
    action_name: string;
    destination_label: string;
    reason: string;
    status: string;
    requirements: { slot: CredentialSlot; auth_type: PersonalCredentialAuth; label: string }[];
    identities: { id: string; name: string; auth_type: string; etag?: string }[];
    run_id?: string;
    turn_id?: string;
}

export type CredentialSubmission =
    | { slot: CredentialSlot; identity_id: string }
    | { slot: CredentialSlot; name: string; credentials: {
        auth_type: PersonalCredentialAuth;
        username?: string;
        password?: string;
        secret?: string;
    } }
    | { slot: CredentialSlot; identity_id: string; expected_identity_etag: string; credentials: {
        auth_type: PersonalCredentialAuth;
        username?: string;
        password?: string;
        secret?: string;
    } };

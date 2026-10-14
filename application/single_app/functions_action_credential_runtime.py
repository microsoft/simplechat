# functions_action_credential_runtime.py
"""Web/scheduler composition of credential services after runtime initialization."""

from action_credential_contracts import ActionCredentialError
import functions_action_credentials as credentials
import functions_action_credential_continuation as continuation


def configure_action_credential_runtime():
    # Owners are imported only by initialized web/scheduler composition. Lower
    # credential modules never import these owners, even through deferred imports.
    import functions_action_catalog
    import functions_agent_delegation
    import functions_authentication
    import functions_settings
    import functions_workspace_identities as identities
    import route_backend_chats
    from content_screening import access

    def resolve_manifest(user_id, action_ref):
        user = functions_authentication.get_current_user_info() or {}
        return functions_action_catalog.resolve_action_manifest(
            user_id, action_ref, settings=functions_settings.get_settings(), user_roles=user.get("roles") or [],
        )

    def resolve_agent(reference, *, user_id):
        return functions_agent_delegation.resolve_delegation_agent(
            reference, user_id=user_id, settings=functions_settings.get_settings(),
        )

    def update_identity(*args, **kwargs):
        try:
            return identities.update_workspace_identity_conditional(*args, **kwargs)
        except identities.WorkspaceIdentityConflict:
            raise ActionCredentialError("identity_changed") from None

    credentials.configure_action_credential_services(credentials.CredentialServices(
        current_user_id=functions_authentication.get_current_user_id_or_none,
        authorize_conversation=route_backend_chats._authorize_personal_conversation_access,
        resolve_manifest=resolve_manifest,
        read_identity=identities.get_workspace_identity,
        list_identities=identities.list_workspace_identities,
        identity_supports_usage=identities.identity_supports_usage,
        read_identity_auth=identities.get_workspace_identity_auth,
        create_identity=identities.create_workspace_identity,
        update_identity=update_identity,
    ))
    continuation.configure_action_credential_continuation_services(continuation.CredentialContinuationServices(
        collect_sources=access.current_request_source_provenance,
        authorize_source=access.assert_document_available,
        resolve_agent=resolve_agent,
    ))

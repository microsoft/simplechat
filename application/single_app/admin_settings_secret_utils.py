# admin_settings_secret_utils.py
"""Masking and restoring the secrets an administrator edits in Admin Settings.

Admin Settings is the one surface that legitimately edits keys, connection
strings and client secrets, so it cannot use ``sanitize_settings_for_user``,
which removes those keys entirely. Instead it round-trips them: the stored value
is replaced with a fixed sentinel on the way out, and a submitted value still
equal to that sentinel resolves back to the stored value on the way in. An
administrator can therefore see that a secret is configured, and replace or clear
it, without the secret itself ever reaching the browser.

These helpers live here rather than in ``functions_settings`` because
``admin_settings_fields`` needs them to normalize a ``secret`` field, and
``functions_settings`` builds a Cosmos client at import time.
``functions_settings`` re-exports everything below, so existing callers are
unaffected.
"""

import copy


ADMIN_SETTINGS_SECRET_REDACTED_VALUE = "***REDACTED***"

# Top-level settings keys holding a secret. Editing Admin Settings must never
# send these to the browser, and must never overwrite one with the mask.
ADMIN_SETTINGS_FORM_SECRET_FIELDS = (
    "azure_openai_gpt_key",
    "azure_apim_gpt_subscription_key",
    "azure_openai_embedding_key",
    "azure_apim_embedding_subscription_key",
    "azure_openai_image_gen_key",
    "azure_apim_image_gen_subscription_key",
    "redis_key",
    "office_docs_storage_account_url",
    "office_docs_storage_account_blob_endpoint",
    # Storage account keys used to sign SAS tokens for citation file access. No
    # form submits these, so they are read-only from the interface's point of
    # view, but they are live credentials and must not be sent to a browser.
    "office_docs_key",
    "video_files_key",
    "audio_files_key",
    "video_files_storage_account_url",
    "audio_files_storage_account_url",
    "content_safety_key",
    "azure_apim_content_safety_subscription_key",
    "azure_ai_search_key",
    "azure_apim_ai_search_subscription_key",
    "azure_document_intelligence_key",
    "azure_apim_document_intelligence_subscription_key",
    "azure_content_understanding_key",
    "speech_service_key",
    "model_endpoint_identity_header_hmac_secret",
)

# Secrets stored inside a nested object rather than at the top level, addressed
# by a dotted path.
ADMIN_SETTINGS_NESTED_SECRET_FIELDS = (
    "web_search_agent.other_settings.azure_ai_foundry.client_secret",
)


def is_admin_settings_redacted_secret(value):
    """Return True when a submitted value is the mask rather than a real secret."""
    return str(value or '').strip() == ADMIN_SETTINGS_SECRET_REDACTED_VALUE


def get_nested_setting_value(settings, field_path):
    """Read a dotted path out of a settings document, or '' when absent."""
    current = settings if isinstance(settings, dict) else {}
    for part in str(field_path or '').split('.'):
        if not isinstance(current, dict):
            return ''
        current = current.get(part)
    return current if current is not None else ''


def set_nested_setting_value(settings, field_path, value):
    """Write a dotted path into a settings document, creating missing levels."""
    current = settings
    parts = str(field_path or '').split('.')
    for part in parts[:-1]:
        if not isinstance(current.get(part), dict):
            current[part] = {}
        current = current[part]
    current[parts[-1]] = value


def resolve_admin_settings_secret_value(field_name, submitted_value, existing_settings):
    """Return the value to store for a secret an administrator submitted.

    A submitted value equal to the mask means "leave it alone", so the stored
    value is returned. Anything else is taken at face value, including an empty
    string, which is how a secret is deliberately cleared.
    """
    submitted_text = str(submitted_value or '').strip()
    if not is_admin_settings_redacted_secret(submitted_text):
        return submitted_text
    return str(get_nested_setting_value(existing_settings, field_name) or '').strip()


def redact_admin_settings_secrets_for_form(settings):
    """Return a copy of a settings document with every configured secret masked.

    Only populated secrets are masked. An unset secret stays empty so the
    interface can tell "not configured" from "configured but hidden".

    Model endpoint credentials live inside the ``model_endpoints`` list rather
    than at a fixed key, so they are not reachable from the lists above and must
    be stripped separately by the caller.
    """
    redacted_settings = copy.deepcopy(settings or {})
    for field_name in ADMIN_SETTINGS_FORM_SECRET_FIELDS:
        if redacted_settings.get(field_name):
            redacted_settings[field_name] = ADMIN_SETTINGS_SECRET_REDACTED_VALUE
    for field_path in ADMIN_SETTINGS_NESTED_SECRET_FIELDS:
        if get_nested_setting_value(redacted_settings, field_path):
            set_nested_setting_value(
                redacted_settings, field_path, ADMIN_SETTINGS_SECRET_REDACTED_VALUE
            )
    return redacted_settings

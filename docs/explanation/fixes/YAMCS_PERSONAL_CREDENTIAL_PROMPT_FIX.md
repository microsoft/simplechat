# YAMCS Personal Credential Prompt Fix (0.261.341)

Fixed in version: **0.261.341**, recorded in
`application/single_app/config.py`.

## Issue

A correctly configured YAMCS action using each user's personal proxy identity
could fail in chat without displaying its credential card. The agent instead
reported `Yamcs configuration or response is invalid.` No pending credential
request was created. The YAMCS server and authenticating proxy could be healthy.

## Root Cause

Private credential requests and bindings identify actions as
`<scope>:<scope-id>:<action-id>`. The shared action catalog resolves a canonical
`action:v1:<scope>:<encoded-scope-id>:<encoded-action-id>` reference.

The initialized credential runtime passed its stored reference directly to the
catalog. The catalog rejected it with a `ValueError` before personal credential
resolution could create a request. The YAMCS plugin correctly kept that internal
exception out of the model response, but its generic validation result concealed
the reference mismatch from users.

## Change

`application/single_app/functions_action_credential_runtime.py` now splits the
stored reference at its first two separators and calls the existing catalog
reference builder before resolving the action. Splitting only twice preserves
action IDs that contain a colon.

The catalog still reauthorizes the exact action against the current actor,
workspace ownership or membership, governance, and enabled state. Stored private
references and fingerprints are unchanged, so existing identities, bindings, and
pending interactions do not require migration. No credential is copied into a
shared action, and no frontend or route changes are needed.

## Validation

`functional_tests/test_action_credentials_bootstrap.py` exercises the real
runtime, catalog, and credential owners in fresh processes with network access
blocked and installed-SDK CosmosDict responses. The regression failed at the
catalog parser before the fix and passed afterward.

Coverage includes global and personal proxy-only actions, creation of the
private pending credential challenge, colon-bearing action IDs, foreign personal
action rejection, and rejection of a group the actor has not joined. Existing
normal/optimized Python, import-order, web startup, and scheduler checks remain
in the same suite.

Related coverage remains in `functional_tests/test_action_personal_credentials.py`
and `functional_tests/test_action_credentials_sk_continuation.py` for identity
storage, secret redaction, credential submission, SDK transport, and continuation.

## Deployment

Deploy version **0.261.341** or later, then invoke the saved action in chat. When
the invoking user has no confirmed personal proxy binding, chat should display
the credential card instead of returning the generic validation failure. The
hosted UI must be retested after deployment; offline regression coverage is not
a claim that an older hosted build has changed.

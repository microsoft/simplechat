# Index Auto-Login

Implemented in version: **0.250.222**

## Overview

Index auto-login lets SimpleChat start the existing Microsoft Entra sign-in flow when an unauthenticated browser loads the home page. This supports environments where users already have a browser single sign-on session and should enter OIG Chat without first clicking a sign-in link.

## Technical Specifications

- Configuration: `ENABLE_AUTO_LOGIN_ON_INDEX=true`
- Entry point: `/`
- Redirect target: `frontend_authentication.login`, which uses the existing MSAL authorization code flow
- Default behavior: disabled, preserving the public landing page unless an admin opts in
- Government cloud support: uses the existing `AZURE_ENVIRONMENT=usgovernment` authority selection in `config.py`

When enabled, unauthenticated requests to `/` redirect to `/login`. If Microsoft Entra already has a valid browser session for the user, Entra can complete sign-in without an additional password prompt. Conditional Access, MFA, consent, or account selection can still require user interaction.

## Usage Instructions

Set the following environment variable for the SimpleChat app service or deployment environment:

```text
ENABLE_AUTO_LOGIN_ON_INDEX=true
```

Keep `TENANT_ID` pointed at the OIG Chat tenant where the invited user accounts exist. For Azure Government deployments, keep `AZURE_ENVIRONMENT=usgovernment` so the Entra authority uses `login.microsoftonline.us`.

## Testing and Validation

- Functional test: `functional_tests/test_index_auto_login.py`
- Route policy tests remain applicable because `/` is still a public route whose runtime behavior is controlled by configuration.

Known limitation: this feature cannot bypass Microsoft Entra interaction requirements. It only starts the normal OpenID Connect redirect automatically.

# Cross-Cloud Account Selection Login Fix

Fixed/Implemented in version: **0.261.030**

## Issue Description

Cross-cloud Microsoft Entra B2B users could be signed in automatically with a native
Azure Government account that did not have the SimpleChat `User` or `Admin` app role.
The landing page correctly denied access, but it did not provide a direct way to return
to the tenant-specific Entra flow and choose the synchronized commercial identity.

## Root Cause Analysis

SimpleChat's Flask/MSAL `/login` route always used the identity provider's default account
selection behavior. Making account selection the default would add friction for typical
users, while changing the authority or supplying the resource-tenant `#EXT#` UPN as a
login hint would be incorrect for this cross-cloud identity model.

## Technical Details

- The existing `/login` flow remains prompt-free by default and continues to clear the
  Flask user, token cache, and idle-session state before authentication.
- `/login?select_account=1` adds the fixed MSAL value `prompt="select_account"`.
- The query value is treated as a strict boolean flag. Arbitrary `prompt` values and
  other `select_account` values are not forwarded to Microsoft Entra.
- Authenticated users without the required app role now see a **Sign in with another
  account** action on the access-denied landing state.
- The denied state identifies the current signed-in account using the display name and
  an available `email` or `mail` claim. A normal `preferred_username` is the fallback,
  while resource-tenant `#EXT#` UPNs are deliberately hidden.
- The account-selection action uses theme-aware foreground, border, hover, and active
  colors so it remains clearly visible in both light and dark themes.
- The tenant-specific authority, role authorization behavior, ordinary unauthenticated
  sign-in link, and App Service Easy Auth configuration are unchanged.
- No UPN or login hint is stored or added to a URL.

## Validation

- `functional_tests/test_cross_cloud_account_selection_login.py` covers normal login,
  explicit account selection, invalid prompt injection attempts, both landing-page links,
  and pre-login Flask session clearing.
- `ui_tests/test_cross_cloud_account_selection_login.py` renders both landing-page states
  and verifies the visible link targets and dark-theme WCAG AA contrast in Chromium.
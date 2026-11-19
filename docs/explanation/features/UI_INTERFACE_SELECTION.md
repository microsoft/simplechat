# Interface selection

Implemented in version: **0.261.449**, recorded in `application/single_app/config.py`.

## Overview

Admins can govern access to the modern React interface and the legacy interface
from **Appearance > Branding > Appearance** in either admin UI. Allowing both
supports a gradual rollout without asking users to keep special bookmarks.

Choose **Modern only**, **Legacy only**, or **Legacy and modern**. The restriction
applies to admins too. When both are available, **Default interface** applies to
accounts that have not explicitly chosen an interface. Unconfigured deployments
allow both and default to modern.

## Architecture and configuration

`functions_ui_mode.py` resolves `ui_mode_policy` (`both`, `classic`, `modern`),
then the account's `preferredUiMode`, then `ui_default_mode` (`modern`, `classic`).
The internal value `classic` means the interface labeled Legacy.

V1's settings form and V2's admin settings schema share enum validation. The
authenticated `/api/user/settings` endpoint stores the preference on the current
account. The V2 bootstrap and classic template context expose the effective policy
without exposing raw administrator configuration.

Navigation uses a read-only account snapshot cached only for the request, not the
lightweight page-chrome cache. A stale preference in another worker therefore
cannot undo a switch immediately after it is saved.

The existing route registry maps corresponding pages and supported query state.
The navigation hook enforces forced policies in both directions. API requests,
form submissions, authentication callbacks, and custom-page embed content remain
backend operations, not alternate application interfaces. Interface selection
does not grant access to data or roles.

Dependencies are the existing Flask settings service, user settings storage, V2
bundle, and `ui_route_map.json`; no new packages or external browser assets are needed.

## User workflow

When both interfaces are allowed, open the account menu and choose **Switch to
modern UI** or **Switch to legacy UI**. The account preference is saved before
navigating, follows the account across browsers and sign-ins, and keeps the
corresponding page or open conversation where supported.

A failed save leaves the current page open and displays an error. Admin restrictions
temporarily override saved choices without deleting them. Restoring both interfaces
restores the user's preference. A changed admin default does not replace a user's
explicit choice.

## Availability and parity

Modern-only ignores the one-page `ui=classic` escape. Legacy-only maps direct V2
links back to legacy; V2-only destinations return to legacy chat.

**Availability exception:** if the modern bundle is missing, navigation temporarily
falls back to legacy, even under modern-only, and emits a throttled `[UI_MODE]`
warning. Build or redeploy the V2 bundle to restore modern routing.

The registered signed-in core pages have modern counterparts. Pre-sign-in Terms
of Use now uses a modern standalone template when modern is selected. Public
landing/policy pages and authentication flows can remain server-rendered without
being legacy application pages. Teams sign-in is a shared standalone page.
Deployment-supplied Python custom pages still need to support the embed contract;
this feature does not rewrite extension code.

## Testing and limitations

`functional_tests/test_ui_interface_selection.py` exercises durable account
preferences, policy enforcement, failed persistence, direct-link fallback and
SDK-backed settings consumers in fresh normal and optimized Python processes.
`test_ui_mode_seam.py` covers precedence and validation; the existing redirect,
route-parity, return-link, Appearance parity and standalone suites cover integration.

`ui_tests/test_ui_interface_selection.py` and `ui_tests/test_v2_classic_links.py`
cover both switch directions, failed saves, keyboard interaction, mobile layouts,
page mapping and modern pre-auth terms. Page-route coverage is not a claim of
exhaustive feature-by-feature parity. Policy is re-evaluated on page navigation
and V2 bootstrap refresh, not pushed immediately to every open browser tab.

Accounts without personal agents are covered by the related
[empty-agent preference save fix](../fixes/UI_PREFERENCE_EMPTY_AGENTS_FIX.md).

# Stored XSS Admin Rendering Fix

Fixed/Implemented in version: **0.241.010**

## Header Information

Issue description:
This hardening addresses the stored-XSS finding, where several admin-facing rendering paths still inserted user-controlled workspace, member, or agent metadata into HTML with `innerHTML`, allowing stored content to execute script in an administrator's browser session.

Root cause analysis:
The affected admin UI flows relied on template-string HTML assembly without consistently escaping untrusted text first. A related issue in the Control Center toast helper also treated all toast messages as HTML, which made any attacker-controlled value passed into a toast another potential browser-side sink. This version closes the group-member and agent-rendering portions of the finding set and adds safer default behavior for the shared Control Center toast sink used alongside those admin flows.

Version implemented:
`config.py` was updated to `VERSION = "0.241.010"` for this fix.

## Technical Details

Files modified:
- `application/single_app/templates/control_center.html`
- `application/single_app/static/js/control-center.js`
- `application/single_app/static/js/admin/admin_agents.js`
- `application/single_app/config.py`
- `functional_tests/test_stored_xss_admin_rendering_fix.py`
- `ui_tests/test_control_center_group_members_escaping.py`

Code changes summary:
- Escaped `member.name` and `member.email` before injecting the group-members modal rows in the Control Center.
- Hardened `ControlCenter.showToast()` so toast content is escaped by default and only renders HTML when a caller explicitly opts in with `allowHtml=true`.
- Updated the two ownership-transfer success toasts that intentionally use `<br>` formatting to opt into HTML explicitly.
- Added a local `escapeHtml()` helper to the admin agents table module and routed `agent.name`, `agent.display_name`, and `agent.description` through it before row rendering.

Testing approach:
- Added a functional regression test that checks the affected source files for the required escaping and toast-hardening patterns.
- Added a Playwright UI regression that injects malicious group-member metadata into the Control Center group-members modal and verifies the values render as inert text without creating executable DOM nodes.

Impact analysis:
The change is low-risk and low-latency. It does not alter authorization logic or data storage. It only changes how admin UI code renders previously stored values into the browser.

## Validation

Test results:
- The functional regression is designed to fail if raw member or agent fields are reintroduced into admin HTML renderers.
- The UI regression is designed to fail if malicious group-member metadata creates DOM nodes or sets the injected `window.__controlCenterMember*Xss` flags.

Before/after comparison:
- Before: attacker-controlled member or agent names could be stored and later rendered into admin HTML sinks, enabling stored XSS in an administrator session.
- After: the admin UI paths now escape stored values before HTML insertion, and Control Center toasts no longer interpret arbitrary message content as HTML by default.

User experience improvements:
Administrators still see the same names and descriptions, but suspicious markup now displays as text instead of executing in the browser.
# V2 Admin Runtime Flag Field Visibility Fix

## Issue

With inbound MCP enabled for the deployment (`ENABLE_MCP_UI=true`), the V2 Admin Settings
**Agents & Actions > Inbound MCP** card rendered as a title with an empty body. None of its
settings could be reached from V2.

**Fixed in version:** 0.261.260

## Root cause

Every Inbound MCP field depends on the `mcp_ui_enabled` runtime flag, which the server
resolves outside the settings document and sends in `runtime_flags`.

Fields were filtered twice. `AdminSettingsPage` filtered each section's fields with
`isFieldVisible(..., runtimeFlags)`. `SettingsSection` then filtered the same fields again
with `isFieldVisible(field, settings, draft)`, without the flags. A missing flag reads as
false, so the second filter dropped every field that needs the flag on, and the one field
that needs it off, the preview notice, had already been dropped by the first. Nothing was
left to render.

Only `inbound-mcp-configuration` declares flag-gated fields, which is why no other section
showed the problem.

## Technical details

### Files modified

- `application/v2_ui/src/components/admin/SettingsSection.tsx`: a `runtimeFlags` prop, passed
  to `isFieldVisible` in the field filter.
- `application/v2_ui/src/pages/AdminSettingsPage.tsx`: passes the page's runtime flags to
  every section.
- `functional_tests/test_v2_admin_section_logic.ts`: renders a section with flag-gated fields
  under both flag values.

### Impact

The Inbound MCP card now shows its settings when inbound MCP is enabled, and only the
preview notice when it is not. Sections without flag-gated fields are unaffected.

## Validation

- `functional_tests/test_v2_admin_section_shell.py`, which runs the TypeScript check above.
- `ui_tests/test_v2_admin_governance_settings.py::test_inbound_shortcut_creates_a_source_policy_and_links_to_governance`,
  which uses the first control on the card.

| | Before | After |
| --- | --- | --- |
| Inbound MCP enabled | Empty card | Governance status, Runtime gate, Request limits, Allowlists |
| Inbound MCP not enabled | Preview notice | Preview notice |

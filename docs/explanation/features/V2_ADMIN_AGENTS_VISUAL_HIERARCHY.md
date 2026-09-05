# V2 Admin Agents Visual Hierarchy

## Overview

The Agents cards in V2 Admin Settings distinguish runtime controls, workspace
permissions, catalog presentation, and template approvals without changing their
order or behavior. Neutral header bands, section icons, larger titles, and stronger
inset boundaries make those different responsibilities easier to recognize.

## Implemented in version: **0.261.093**

The application version is maintained in `application/single_app/config.py`.
This change increments its third segment from `0.261.092` to `0.261.093`.

**Dependencies:** the existing React/TypeScript V2 UI, local Lucide icons,
`SettingsSection`, and the server-declared admin field schema. No new packages,
settings, routes, or browser asset sources are required.

## Technical specifications

`AdminSettingsPage` supplies an optional appearance configuration to the existing
section renderer. The configuration is limited to these section IDs:

| Section | Presentation |
| --- | --- |
| `agents-config` | Robot icon, an accent-backed Enable Agents row, and subordinate styling for Workspace Mode and its global-agent option. |
| `agent-toggles-card` | People icon with separate person/group cues alongside the existing permission labels. |
| `agents-page-customization-card` | Palette icon and stronger Hero, Guidance, and Promoted agents disclosure headers. |
| `agent-template-approvals-section` | Layers icon and the same neutral section-header treatment. |

The appearance map contains no values or dependency rules. Field order,
conditional visibility, section status, acknowledgement handling, and saving
continue to use the existing schema and callbacks. In particular, emphasizing
Enable Agents does not turn it into a new readiness indicator.

The opt-in CSS uses existing semantic theme tokens. Each card is an inline-size
container: when it is narrow relative to the selected text size, labels, color
inputs, promotion controls, and setting counts wrap instead of extending past
the card. Normal-width layouts and all non-Agents sections keep their previous
presentation.

### File structure

| File | Responsibility |
| --- | --- |
| `application/v2_ui/src/components/admin/agentSectionAppearance.ts` | The four-section appearance map. |
| `application/v2_ui/src/components/admin/SettingsSection.tsx` | Opt-in headers, decorative field cues, and disclosure styling. |
| `application/v2_ui/src/components/admin/fields.tsx` | Inert CSS hooks for field headings and color controls. |
| `application/v2_ui/src/components/admin/PromotedAgentsEditor.tsx` | Inert CSS hooks for promotion controls and rows. |
| `application/v2_ui/src/pages/AdminSettingsPage.tsx` | Applies the map while retaining the shared renderer. |
| `application/v2_ui/src/styles/theme.css` | Scoped contrast and container-based wrapping rules. |

There are no API or persistence changes. The main save bar still buffers settings,
and orchestration retains its existing separate save endpoint.

## Usage

In V2 Admin Settings, choose **Agents & Actions**. Use **Agent Runtime** for the
runtime and workspace-source controls; use **Workspace Agent Permissions** to
distinguish personal and group permissions. Their full labels and endpoint
guidance remain visible.

Expand **Hero**, **Guidance**, or **Promoted agents** in **Agents Page** to work on
catalog presentation. The disclosure headers still show setting counts when
collapsed. Search continues to reveal matching fields inside collapsed groups.

Use the existing save bar to save or discard a draft. The new header bands and
icons do not indicate that a change has already been saved.

## Testing and validation

- `functional_tests/test_v2_admin_section_logic.ts`, run by
  `test_v2_admin_section_shell.py`, covers the four-section boundary, retained
  rendering callbacks and order, unchanged status semantics, and collapse defaults.
- `functional_tests/test_v2_admin_agents_parity.py` retains schema and visibility
  parity coverage.
- `ui_tests/test_v2_admin_agents_visual_hierarchy.py` exercises the built SPA with
  real schema metadata and intercepted APIs: light/dark contrast, heading sizes,
  keyboard disclosure, search, permission visibility, save/discard, rejected
  saves, promotions, narrow viewports, and 200% text scaling.

Browser fixtures never write to a live settings document. Local Chromium is the
default; the fixture can connect to a configured Azure Playwright workspace using
`PLAYWRIGHT_SERVICE_URL`, `PLAYWRIGHT_WORKSPACE_RESOURCE_ID`, and
`DefaultAzureCredential`. Azure execution requires an existing workspace and
appropriate access; no resource provisioning is performed by these tests.

The enhancement adds no API requests or per-field state. The classic interface,
Actions, Inbound MCP, and other admin categories are outside its scope.

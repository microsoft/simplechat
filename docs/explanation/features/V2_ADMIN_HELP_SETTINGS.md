# V2 Admin Help Settings

**Implemented in version: 0.261.274**

## Overview

The V2 React admin surface draws the **Help** group from the field schema in
`admin_settings_fields.py`. Only three Help switches were declared, so V2 offered
a fraction of what the classic page does:

| Classic capability | V2 before this change |
| --- | --- |
| Support Menu name, Send Feedback destination, support recipient email | Missing. `enable_support_send_feedback` was guessed onto the Send Feedback **Overview** card by the `enable_*` fallback scan |
| Send Feedback forms that email the SimpleChat team | Missing |
| Per-announcement visibility for the user Latest Features page | Missing. The documentation-links switch was hidden unless the menu and destination were on |
| Admin Latest Features catalog with a **New** badge | Nothing rendered. The tab declares no sections |
| Registered / Unregistered release notifications badge | Missing |

This change brings V2 to parity with the classic page while staying in V2's design
language:

- section cards with status chips;
- settings nested under the switch they depend on;
- collapsible groups;
- search across the whole page;
- in-page jumps between related cards.

## Dependencies

- `admin_settings_nav.py`: the Help tabs and sections. Admin Latest Features is
  `render: "latest_features"` with no sections.
- `support_menu_config.py`: both release catalogs and the visibility defaults.
- `route_backend_settings.py`: the existing `send_feedback_email` and
  `release_notifications_registration` endpoints, which are reused unchanged.
- React/TypeScript V2 UI with local `lucide-react` icons. No new packages or
  browser asset sources are added.

## Technical specifications

### Schema

| Section | Fields |
| --- | --- |
| `support-menu-section` | `enable_support_menu`, `support_menu_name`, `enable_support_send_feedback`, `support_feedback_recipient_email` (email, `required`), and `enable_support_latest_features` |
| `send-feedback-overview-card` | component `send-feedback-overview` |
| `send-feedback-bug-card` | component `send-feedback-bug-report` |
| `send-feedback-feature-card` | component `send-feedback-feature-request` |
| `user-facing-latest-features-section` | component `support-latest-features-publication`, `enable_support_latest_feature_documentation_links`, and component `support-latest-features-visibility` (key `support_latest_features_visibility`) |

Other schema additions:

- `ADMIN_SECTION_STATUS["support-menu-section"]` reports **Off** while the menu
  is off. While Send Feedback is on with no recipient it reports **Needs
  configuration**, and otherwise **Configured**.
- `LEGACY_FIELD_NAMES` maps the visibility map to the classic page's generated
  `support_latest_feature_<id>` checkboxes.
- The new `LEGACY_FORM_ONLY_FIELDS` maps the eight Send Feedback inputs to the
  components that offer them. Those inputs are not settings.

### `related_section`

**Enable Latest Features Destination** declares
`{"section_id": "user-facing-latest-features-section", "label": "User-Facing Latest Features"}`.
This reuses the descriptor the Operations parity work introduced for the DAI
diagnostics switch. The card says where the announcements it publishes are chosen,
**Shown in Help › User-Facing Latest Features › User-Facing Latest Features**, and
offers **Go to User-Facing Latest Features**. `classic_only` is not set, because
V2 draws that card itself. `test_v2_admin_settings_schema.py` requires every
target to be a navigation section.

### Required flag

An empty text field declared `required` shows a **Required** pill beside its label
while its section reads **Needs configuration**. The chip says the card needs
attention, and the pill says which control to fill. The card shares its status
through `sectionStatusContext.ts`, so the pill stays hidden when a section is
**Off** or missing a prerequisite: blank fields under a disabled capability are not
the next step. This applies to every required text field, not only the recipient.

### Validation (`normalize_admin_settings_updates`)

| Input | Classic page | V2 |
| --- | --- | --- |
| Malformed recipient, such as spaces, two addresses or a display name | Clears it, switches Send Feedback off, flashes a warning | Refuses the save with a field error and keeps the typed value |
| Send Feedback on with no recipient | Switches Send Feedback off | Saves, adds a field warning, and the status reads **Needs configuration** |
| Blank menu name | "Support" | "Support"; capped at 60 characters |
| Visibility map | Rebuilt from every checkbox | Must be an object. Merged over the stored map, so a partial payload cannot re-share a hidden announcement. Unknown ids are dropped and the result normalized as the classic save does |

### Catalog API

`GET /api/v2/admin/latest-features` is registered on the `backend_v2_admin`
blueprint behind `swagger_route`, `login_required` and `admin_required`. It returns
`{version, admin, user}` release groups built by
`functions_support_latest_features.build_latest_features_payload`. That module is
pure: the route injects `url_for` for endpoint shortcuts and the static route for
screenshots.

Each shortcut has one of three kinds:

| Kind | Meaning |
| --- | --- |
| `admin` | A live tab id, with legacy ids resolved through `LEGACY_TAB_REDIRECTS` (now mirrored in `admin_settings_nav.py`), plus an optional section |
| `page` | A same-origin path |
| `external` | An http(s) address |

Any other shape is dropped. User shortcuts keep `requires_settings` so the preview
can follow the unsaved draft. User announcements carry `default_visible`.

The SPA requests the catalogs beside the settings, and only when its navigation
includes a Help catalog surface.

### Application title fix

`_apply_support_application_title` filled `{app_title}` before replacing
"SimpleChat". A configured title containing "SimpleChat" was therefore substituted
twice, and the group helpers ran every feature through the substitution a second
time. The product name is now replaced first, and a group-level pass leaves
features alone. This affects both interfaces.

### Interface

| Card | Behavior |
| --- | --- |
| Support | Schema-driven. The menu switch leads, and its settings sit nested beneath it |
| Overview | Explains the email workflow, warns that the draft is text only, and links to the Support settings for end-user feedback |
| Report a Bug / Request a Feature | Name and email prefilled from bootstrap. Inline validation, a POST, the mailto draft, and an "open the draft" fallback link. Typed text survives search and category changes. Never touches the save bar |
| User-Facing Latest Features | Publication notice that jumps to Support, the documentation-links switch, and a release-grouped share checklist. Rows expand to a preview with details, steps, screenshots and filtered user shortcuts. Per-release Share all / Hide all |
| Admin Latest Features | A synthetic `latest-features` card with a **New** badge. Releases collapse, rows expand to details, why it matters, rollout notes, screenshots and shortcuts. A shortcut jumps in-page when V2 draws the target and otherwise opens `/admin/settings#<tab>` |
| Version banner | Registered / Unregistered pill and a registration dialog, kept outside the version live region |

The Help category in the rail, and its option in the phone category picker, carry
the **New** marker. Page search matches announcement text in both catalogs and
narrows the cards to the matches.

### File structure

| File | Role |
| --- | --- |
| `application/single_app/admin_settings_fields.py` | Help declarations, status rule, validation, parity maps |
| `application/single_app/admin_settings_nav.py` | `LEGACY_TAB_REDIRECTS`, `resolve_admin_tab_id` |
| `application/single_app/functions_support_latest_features.py` | Catalog payload builder |
| `application/single_app/support_menu_config.py` | Preview groups, title substitution fix |
| `application/single_app/route_backend_v2.py` | `GET /api/v2/admin/latest-features` |
| `application/v2_ui/src/lib/latestFeatures.ts` | Catalog types, visibility, search, shortcut resolution, safe URLs |
| `application/v2_ui/src/lib/supportFeedback.ts` | Draft wording, address check, `safeMailtoHref` |
| `application/v2_ui/src/components/admin/LatestFeatureParts.tsx` | Release groups, rows, details, screenshots |
| `application/v2_ui/src/components/admin/AdminLatestFeatures.tsx` | Admin catalog card body |
| `application/v2_ui/src/components/admin/LatestFeaturesVisibility.tsx` | User-facing share checklist |
| `application/v2_ui/src/components/admin/LatestFeaturesPublication.tsx` | Publication notice |
| `application/v2_ui/src/components/admin/SendFeedback.tsx` | Overview and feedback forms |
| `application/v2_ui/src/components/admin/ReleaseNotificationsBadge.tsx` | Registration badge and dialog |
| `application/v2_ui/src/components/admin/latestFeatureIcons.ts` | Catalog icon names to Lucide |
| `application/v2_ui/src/components/admin/fields.tsx` | Required flag |
| `application/v2_ui/src/components/admin/sectionStatusContext.ts` | Section status for field controls |
| `application/v2_ui/src/components/admin/SettingsSection.tsx` | Header `badge` slot, status context |
| `application/v2_ui/src/pages/AdminSettingsPage.tsx` | Catalog fetch, synthetic card, search, rail marker, banner |

## Usage

Open **Admin Settings › Help** in V2. Turn on the Support menu, set the recipient
email, choose the announcements users should see, then save. Use the Send Feedback
cards to reach the SimpleChat team. Select **Unregistered** beside the version to
register the deployment. See `docs/admin/help.md` for the administrator guide.

## Testing and validation

| Test | Covers |
| --- | --- |
| `functional_tests/test_v2_admin_help_parity.py` | Panes against navigation, every V1 Help field claimed, no invented fields, the disabled template block ignored, components declared, status rule, the catalog tab rendered |
| `functional_tests/test_v2_admin_help_settings_normalization.py` | Recipient validation, the missing-recipient warning, menu name fallback, visibility merge and validation |
| `functional_tests/test_v2_admin_latest_features_api.py` | Catalog shape, defaults, shortcut resolution and safety, requirements kept, single title substitution, the alias map matching JavaScript, route guards |
| `functional_tests/test_v2_admin_help_logic.py` (+ `.ts`) | Visibility, search, shortcut targets, safe URLs and mailto, draft wording, publication states, static renders of every card |
| `functional_tests/test_v2_admin_capability_placement.py` | Help is fully described, and `enable_support_send_feedback` lives in Support |
| `functional_tests/test_v2_admin_settings_schema.py` | `related_section` targets exist |
| `ui_tests/test_v2_admin_help_settings.py` | The built SPA with the real schema and catalogs: Support status and validation, Send Feedback, visibility save and preview, catalog shortcuts and search, registration, and no overflow at 390–1920px in light and dark |

### Known limitations

- The end-user Support pages, Latest Features and Send Feedback, are still
  classic pages. The V2 user rail has no Support menu.
- A catalog shortcut whose target V2 does not draw, such as Backup, opens the
  classic admin page.
- Very long feedback details can exceed what some mail apps accept in a mailto:
  URL, the same limit the classic page has.

## Related

- `docs/admin/help.md`
- `docs/explanation/features/V2_ADMIN_SETTINGS_LAYOUT_AND_HIERARCHY.md`
- `docs/explanation/features/LATEST_FEATURES_NAVIGATION_HIDE_PREFERENCE.md`

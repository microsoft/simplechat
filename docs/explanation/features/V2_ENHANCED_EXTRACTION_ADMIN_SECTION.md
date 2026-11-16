# Enhanced Extraction Section in the V2 Admin Surface

**Implemented in version:** 0.261.265

## Overview

Enhanced extraction and the Azure AI Content Understanding connection behind it now form
one section of V2 Admin Settings, **Knowledge › Document Extraction › Enhanced
Extraction**. The section is led by the "Enable Enhanced extraction" switch, and every
setting that only takes effect while Enhanced is on sits beneath it.

Before this change the two read as unrelated settings:

- **The switch was buried.** It sat in the *Extraction* group of the Document Intelligence
  card, and that group starts collapsed, so an administrator had to open the group before
  they could find the switch.
- **Content Understanding stood apart from the switch it depends on.** It was a card of
  its own with no visibility condition, so it could be filled in while Enhanced was off,
  the one state in which it is never called.
- **Turning Enhanced on in V2 changed nothing by itself.** The server-rendered form moves
  the extraction mode from Standard to Auto when Enhanced is switched on, and the
  Content Understanding feature documentation promises the same. V2 left the mode on
  Standard, and with a Standard mode Content Understanding is never used.
- **Content Understanding was offered in every cloud.** The server-rendered page hides it
  where `AZURE_ENVIRONMENT` has no Content Understanding. V2 showed its fields regardless.

### Dependencies

- `admin_settings_fields.py` schema vocabulary (`role: capability`, groups, `depends_on`)
- `functions_settings.is_content_understanding_supported_environment`
- The V2 admin renderer: `SettingsSection.tsx`, `adminSections.ts`, `adminFields.ts`

## Technical specifications

### Section layout

| Section | Contents |
| --- | --- |
| `document-intelligence-section` | The Document Intelligence connection only: API Management routing, endpoint, authentication, key, connection test. |
| `enhanced-extraction-section` | The capability switch, then extraction mode, Auto sample pages and formula extraction, the engine notice, the **Content Understanding connection** group and the **Content Understanding analyzers** group. |

`content-understanding-section` is removed from `ADMIN_NAV`. The server-rendered sidebar
resolves the new section to the Enhanced switch row in `templates/admin/_panes/extraction.html`,
which now carries `id="enhanced-extraction-section"`. The server-rendered layout is
otherwise unchanged; it already nests Content Understanding under the Enhanced switch.

### Visibility

Every field in the Enhanced Extraction section other than the switch declares
`enable_enhanced_extraction == true`. Content Understanding fields also declare the runtime
flag `content_understanding_supported == true`, which `GET /api/v2/admin/settings` reports
from `is_content_understanding_supported_environment()`.

`SettingsSection` now receives the page's runtime flags. It filters fields a second time,
and that filter previously ran without them, so a field gated on a flag that was on read as
unmet and was dropped from the card. The fix applies to every flag-gated field, including the
Inbound MCP settings.

### Schema vocabulary

| Descriptor | Purpose |
| --- | --- |
| Group `open_until_set: <key>` | Opens the group while the section's capability is on and that key is blank. Content Understanding cannot be `required`, because Enhanced works without it, but it is usually the next step after turning Enhanced on. |
| Field `on_enable: {set, when}` | Companion values a switch sets when it is turned on. Enhanced extraction declares `set: {document_intelligence_pdf_image_extraction_mode: "auto"}` when the mode is `read`. |
| `flag` in Python `evaluate_dependency` | The server evaluates runtime-flag conditions as the browser does when flags are supplied, and treats them as met when they are not. |

`on_enable` is applied in two places, with the same rules:

- **Browser** (`applyEnableEffect` in `adminFields.ts`): applied to the draft as the switch
  flips, so the new mode is on screen before saving. Turning the switch back off before
  saving takes the companion back if it still holds the value that was set.
- **Server** (`_apply_enable_defaults` in `admin_settings_fields.py`): applied to a save
  that turns the switch on without naming the companion, with a field warning. It is
  applied only on a transition from off. A companion named in the same save always wins.

### Engine notice

The `enhanced-extraction-engine` component (`EnhancedExtractionEngine.tsx`) names the engine
a document extracted as Enhanced will use. The resolver in `lib/enhancedExtraction.ts`
mirrors `resolve_enhanced_extraction_engine` and `is_content_understanding_configured`:

| Reading | Shown as |
| --- | --- |
| Cloud without Content Understanding | Document Intelligence Layout; nothing more to configure |
| No Content Understanding endpoint | Document Intelligence Layout; add a Foundry endpoint |
| Key authentication without a key | Document Intelligence Layout; add the key or use managed identity |
| Configured | Azure AI Content Understanding |

A stored key arrives in the browser as the redaction placeholder and counts as
configured. The notice reads the settings on screen and says "Takes effect when you save"
while that differs from what is saved. It judges configuration, not connectivity; the
connection test confirms the service answers.

### Connection test payload

The Document Intelligence connection test sends the extraction mode and Auto sample pages
only while Enhanced is on. With Enhanced off every document uses Standard, so the test
exercises Read.

### Files

| File | Change |
| --- | --- |
| `application/single_app/admin_settings_nav.py` | `enhanced-extraction-section` replaces `content-understanding-section` |
| `application/single_app/admin_settings_fields.py` | Section split, gating, `on_enable`, `open_until_set`, flag evaluation, `_apply_enable_defaults` |
| `application/single_app/route_backend_v2.py` | `content_understanding_supported` runtime flag |
| `application/single_app/templates/admin/_panes/extraction.html` | Navigation anchor on the Enhanced switch row |
| `application/v2_ui/src/lib/adminFields.ts` | `on_enable` and `open_until_set` types, `applyEnableEffect` |
| `application/v2_ui/src/lib/adminSections.ts` | `shouldGroupStartOpen` honours `open_until_set` |
| `application/v2_ui/src/lib/enhancedExtraction.ts` | Engine resolver |
| `application/v2_ui/src/components/admin/EnhancedExtractionEngine.tsx` | Engine notice |
| `application/v2_ui/src/components/admin/SettingsSection.tsx` | Runtime flags in the visibility filter, reader for group disclosure |
| `application/v2_ui/src/pages/AdminSettingsPage.tsx` | Engine notice, `on_enable`, runtime flags passed to sections |

## Usage

1. Open **Admin Settings › Knowledge › Document Extraction** and configure **Document
   Intelligence**. Standard extraction needs nothing else.
2. In **Enhanced Extraction**, turn on **Enable Enhanced extraction**. The extraction mode
   moves to Auto if it was Standard, and the engine notice shows which engine Enhanced will
   use.
3. In commercial clouds, the **Content Understanding connection** group opens while no
   endpoint is set. Add the Foundry endpoint and either a key or managed identity, then
   test the connection. Leaving it blank keeps Enhanced on Document Intelligence Layout.
4. Save. The engine notice stops saying "Takes effect when you save".

The section's status chip reads **Off** while the switch is off and **Configured** while it
is on. Running on the Layout fallback is a valid, cheaper setup, so it is not reported as
needing configuration; the engine notice is what nudges toward Content Understanding.

## Testing and validation

| Test | Covers |
| --- | --- |
| `functional_tests/test_v2_admin_enhanced_extraction_section.py` | Navigation, section shape, gating, cloud flag, `on_enable` on the server, connection test payload, API and page wiring, server-rendered anchor |
| `functional_tests/test_v2_admin_knowledge_extraction.py` | Tab sections, connection-only Document Intelligence, sample pages gating, Content Understanding nesting |
| `functional_tests/test_v2_admin_schema_vocabulary.py` | `open_until_set` and `on_enable` validity, runtime flag evaluation |
| `functional_tests/test_v2_admin_section_logic.ts` | Group disclosure, engine resolver, `applyEnableEffect`, notice copy, card rendering with and without flags |
| `ui_tests/test_v2_admin_enhanced_extraction_section.py` | Off state, turning on (Auto, open connection, live engine notice, saved payload), turning back off before saving, connected summary, cloud without Content Understanding, phone and desktop widths |

### Known limitations

- The engine notice reads configuration, not connectivity.
- Deep links to `#content-understanding-section` no longer match a card in V2, because the
  connection is part of the Enhanced Extraction section. The server-rendered page still has
  that element inside its Enhanced block, and the documentation keeps the anchor as a
  sub-heading of the Enhanced Extraction section.

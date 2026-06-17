# Agents Page Customization

Documentation Version: 0.242.061
Version Implemented: 0.241.229
Updated in: 0.242.061
Related Config Update: `application/single_app/config.py` -> `VERSION = "0.242.061"`

## Overview
Admins can customize the public Agents page hero from the AI and Agents admin settings tab. The feature controls the hero title, subtitle, single-color or two-tone hero background, an optional markdown guidance message shown below the hero, and whether agent instructions are visible in the Agents page details popup.

## Purpose
The Agents page often needs organization-specific language. Admins can now explain how users should request new agents, provide contact details, or add governance notes without editing templates.

## Dependencies
- Admin Settings page and existing settings persistence flow
- `/agents` frontend route
- Local `marked` and `DOMPurify` browser assets for markdown rendering
- Bootstrap form controls and page layout styles

## Technical Specifications

### Architecture Overview
1. `functions_settings.py` defines defaults for `agents_page_*` settings.
2. `route_frontend_admin_settings.py` renders and persists the fields from Admin Settings.
3. `route_frontend_agents.py` builds a sanitized public `agents_page_config` with validated hex colors.
4. `templates/agents.html` applies the configured title, subtitle, hero colors, and markdown payload.
5. `static/js/agents_catalog.js` renders the optional markdown disclaimer through `DOMPurify.sanitize(marked.parse(...))` before inserting sanitized nodes into the page.

### Configuration Options
- `agents_page_title`: Hero title text.
- `agents_page_subtitle`: Hero subtitle text.
- `agents_page_hero_color_mode`: `single` or `two_tone`.
- `agents_page_hero_primary_color`: Valid `#RRGGBB` primary hero color.
- `agents_page_hero_secondary_color`: Valid `#RRGGBB` secondary color for two-tone hero mode.
- `agents_page_disclaimer_markdown`: Optional markdown guidance text shown below the hero.
- `agents_page_show_instructions_in_details`: Shows agent instructions in the Agents page details popup when enabled. When disabled, the Agents catalog API omits the `instructions` field for that page.

### File Structure
- `application/single_app/functions_settings.py`
- `application/single_app/route_frontend_admin_settings.py`
- `application/single_app/route_frontend_agents.py`
- `application/single_app/templates/admin_settings.html`
- `application/single_app/templates/agents.html`
- `application/single_app/static/css/agents-catalog.css`
- `application/single_app/static/js/agents_catalog.js`

## Usage Instructions
1. Open Admin Settings.
2. Go to the AI and Agents tab.
3. Use Agents Page Customization to set the title, subtitle, hero color mode, hero colors, optional guidance text, and details popup instruction visibility.
4. Save settings.
5. Open `/agents` to review the customized page.

## Testing and Validation
- Functional coverage: `functional_tests/test_agents_catalog_feature.py` validates defaults, admin controls, persistence wiring, sanitized disclaimer rendering, instruction visibility redaction, and the public route handoff.
- JavaScript syntax checks cover `static/js/agents_catalog.js`.
- Python parse checks cover the changed route/config/test files.

## Known Limitations
- The disclaimer supports markdown formatting only. Runtime JavaScript sanitization strips unsafe HTML before display.
- Hero colors accept six-digit hex colors only.
# Agents Page Customization

Documentation Version: 0.242.064
Version Implemented: 0.241.229
Updated in: 0.242.064
Implemented in version: **0.241.229**
Updated in version: **0.242.064**
Related Config Update: `application/single_app/config.py` -> `VERSION = "0.242.064"`

## Overview
Admins can customize the public Agents page hero from the AI and Agents admin settings tab. The feature controls the hero title, subtitle, single-color or two-tone hero background, an optional markdown guidance message shown below the hero, whether agent instructions are visible in the Agents page details popup, and which agents are promoted into the Popular tab.

## Purpose
The Agents page often needs organization-specific language and curation. Admins can now explain how users should request new agents, provide contact details, add governance notes, or highlight important agents before usage counts naturally make them popular without editing templates.

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
5. `functions_agent_catalog.py` annotates accessible catalog records that match admin-selected Popular tab promotions. Stored catalog keys never expose agents outside the current user's normal visibility.
6. `static/js/agents_catalog.js` renders the optional markdown disclaimer through `DOMPurify.sanitize(marked.parse(...))`, merges promoted agents into Popular rankings, and renders the optional promoted badge.

### Configuration Options
- `agents_page_title`: Hero title text.
- `agents_page_subtitle`: Hero subtitle text.
- `agents_page_hero_color_mode`: `single` or `two_tone`.
- `agents_page_hero_primary_color`: Valid `#RRGGBB` primary hero color.
- `agents_page_hero_secondary_color`: Valid `#RRGGBB` secondary color for two-tone hero mode.
- `agents_page_disclaimer_markdown`: Optional markdown guidance text shown below the hero.
- `agents_page_show_instructions_in_details`: Shows agent instructions in the Agents page details popup when enabled. When disabled, the Agents catalog API omits the `instructions` field for that page.
- `agents_page_promoted_popular_agents`: Ordered list of promoted agent catalog keys with display metadata and a visibility window of `all_time`, `30_days`, or `both`.
- `agents_page_promoted_popular_order`: Places promoted agents `before`, `after`, or `mixed` with usage-ranked agents.
- `agents_page_promoted_popular_tag_enabled`: Controls whether promoted agents show a promoted badge.
- `agents_page_promoted_popular_tag_label`: Badge text shown for promoted agents, defaulting to `Promoted`.

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
4. In Promoted Popular Agents, select any visible agent, choose whether it appears in All Time, Last 30 Days, or both Popular views, set placement, and choose whether to show the promoted badge.
5. Save settings.
6. Open `/agents` to review the customized page.

## Testing and Validation
- Functional coverage: `functional_tests/test_agents_catalog_feature.py` validates defaults, admin controls, persistence wiring, sanitized disclaimer rendering, instruction visibility redaction, promoted Popular tab ranking, and the public route handoff.
- JavaScript syntax checks cover `static/js/agents_catalog.js`.
- Python parse checks cover the changed route/config/test files.

## Known Limitations
- The disclaimer supports markdown formatting only. Runtime JavaScript sanitization strips unsafe HTML before display.
- Hero colors accept six-digit hex colors only.
- Promoted Popular agents only render for users who can already access the selected agent through personal, group, or enterprise catalog rules.
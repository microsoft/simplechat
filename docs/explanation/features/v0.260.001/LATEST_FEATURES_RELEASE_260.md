# Latest Features Release 260 (v0.260.001)

## Overview

SimpleChat v0.260.001 restructures the in-app **Latest Features** experience into a three-tier release model for both end users and admins. The current release now highlights the v0.260.001 feature set, the previous tier preserves v0.250.001, and the archive tier keeps older release highlights available without mixing them into the newest cards.

The purpose of this release document is to describe how the Latest Features catalogs, galleries, admin visibility settings, placeholder screenshots, and release workflow hooks fit together.

Implemented in version: **0.260.001**

## Dependencies

- `application/single_app/support_menu_config.py`
- `application/single_app/templates/latest_features.html`
- `application/single_app/templates/admin_settings.html`
- `application/single_app/static/images/features/`
- `functional_tests/test_latest_features_release_group_integrity.py`
- `functional_tests/test_admin_latest_features_tab.py`
- `.github/prompts/update-latest-features.prompt.md`
- `.github/PULL_REQUEST_TEMPLATE.md`
- `.github/workflows/release-notes-check.yml`
- `docs/explanation/release_notes.md`

## Technical Specifications

### Architecture Overview

Latest Features is now modeled as ordered release groups rather than one long, flat catalog. Both audiences expose the same tier IDs:

- `current_release` — the v0.260.001 cards that should be most prominent and expanded by default.
- `previous_release` — the v0.250.001 cards, collapsed by default for reference.
- `archive_release` — older release cards, collapsed by default for long-term lookup.

The end-user page uses `_SUPPORT_LATEST_FEATURE_RELEASE_GROUPS`; the admin Latest Features tab uses `_ADMIN_LATEST_FEATURE_RELEASE_GROUPS`. Each group carries `id`, `label`, `description`, `release_version`, `default_expanded`, `collapse_id`, and `features` metadata.

### Catalog Constants and Tiers

| Catalog source(s) | Audience | Tier | Release version |
| --- | --- | --- | --- |
| `_SUPPORT_RELEASE_260_FEATURE_CATALOG` | End user | `current_release` | `0.260.001` |
| `_ADMIN_RELEASE_260_FEATURE_CATALOG` | Admin | `current_release` | `0.260.001` |
| `_SUPPORT_RELEASE_250_FEATURE_CATALOG` | End user | `previous_release` | `0.250.001` |
| `_ADMIN_RELEASE_250_FEATURE_CATALOG` | Admin | `previous_release` | `0.250.001` |
| `_SUPPORT_RELEASE_241_FEATURE_CATALOG` + `_SUPPORT_RELEASE_239_FEATURE_CATALOG` | End user | `archive_release` | `0.239.001 - 0.241.007` |
| `_ADMIN_RELEASE_241_FEATURE_CATALOG` | Admin | `archive_release` | `0.241.001 - 0.241.007` |

The v0.260.001 end-user tier contains 20 cards. Each card carries seven concrete "How To Try It" steps and three images. The v0.260.001 admin tier contains 16 cards. Each admin card carries four admin rollout steps and one image.

### `_latest_feature_card(...)` Contract

`_latest_feature_card(...)` builds a normalized card dictionary with these core fields:

- `id`
- `title`
- `icon`
- `summary`
- `details`
- `why`
- `guidance`
- `actions`
- `image`
- `image_alt`
- `images`

The helper accepts the older single-image arguments (`image_label`, `image_title`, `image_caption`, `image_name`, and `include_media`) and the newer `images=[...]` gallery form. When `images` is provided, each image spec can define `name`, `title`, `alt`, `caption`, and `label`. If `name` is omitted, the helper derives `feature_id_1.png`, `feature_id_2.png`, and so on.

Worked example:

```python
_latest_feature_card(
    'release_260_enhanced_extraction',
    'Sharper Document Extraction with Figure Descriptions',
    'bi-file-earmark-richtext',
    'Enhanced extraction now reads charts, diagrams, and figures inside your documents and writes searchable descriptions of them, so answers can draw on pictures instead of skipping past them.',
    'When your admins turn on Enhanced extraction, SimpleChat uses Azure AI Content Understanding to describe figures, charts, and diagrams as it processes a file.',
    'This matters because a large share of the meaning in reports, decks, and scanned documents lives in pictures, and until now that content was effectively invisible to search.',
    [
        'Open Personal Workspace and upload a document that contains charts, diagrams, or scanned figures.',
        'Wait for processing to finish, then expand the document row to see the extraction badge.',
        'Hover the badge to see which engine ran, and the fallback reason if a different engine was used.',
        'Open the document details to read the generated figure descriptions alongside the extracted text.',
        'Go to Chat, ground on that document, and ask a question that can only be answered from a figure or chart.',
        'If an older document was uploaded before this change, use Change Extraction to reprocess it with the newer engine.',
        'If you do not see the option, ask your admin whether Enhanced extraction is enabled for your environment.',
    ],
    images=[
        {'title': 'Upload a Document With Figures', 'label': 'Upload', 'caption': 'Upload a report or deck that contains charts, diagrams, or scanned figures from Personal Workspace.'},
        {'title': 'Check the Extraction Badge', 'label': 'Extraction Badge', 'caption': 'The document row badge names the extraction engine that ran and explains any fallback.'},
        {'title': 'Ask About a Chart', 'label': 'Chart Answer', 'caption': 'Ground a chat on the document and ask a question that can only be answered from a figure.'},
    ],
)
```

### Accessor Functions

- `get_support_latest_feature_release_groups()` returns a deep copy of all end-user release groups with normalized legacy action endpoints.
- `get_support_latest_feature_release_groups_for_settings(settings)` returns end-user release groups with actions filtered by `requires_settings` and application-title placeholders resolved.
- `get_visible_support_latest_feature_groups(settings)` applies tenant visibility choices and settings-gated actions before rendering `/support/latest-features`.
- `get_default_support_latest_features_visibility()` creates default visibility entries for every user-facing card, with the 20 new v0.260.001 cards defaulting to visible.
- `normalize_support_latest_features_visibility(raw_visibility)` merges stored tenant choices over current defaults, preserving existing admin selections during the tier shift.
- `get_admin_latest_feature_release_groups_for_settings(settings)` returns admin release groups with actions filtered and media normalized for Admin Settings.

### Visibility Toggle Model

End-user card visibility is stored under `support_latest_features_visibility`. Admin choices are not reset when release tiers shift: `normalize_support_latest_features_visibility(raw_visibility)` starts from current defaults, then overlays saved values only for feature IDs that still exist. That means existing v0.250.001 and archived preferences remain honored, while the 20 new v0.260.001 cards default to **hidden** until their placeholder screenshots are replaced with real captures.

Admin-only cards are not controlled by user-facing visibility toggles. They are always available in the Admin Settings Latest Features tab as tenant rollout guidance.

### File Structure

- `support_menu_config.py` owns the catalog constants, release groups, helper, accessors, action filtering, visibility normalization, and media normalization.
- `latest_features.html` renders the end-user page with grouped release panels and gallery thumbnails from `feature.images`.
- `admin_settings.html` renders the admin current tier directly and every non-current tier through dynamic card and collapse IDs.
- `application/single_app/static/images/features/` contains screenshot assets referenced by catalog cards.
- `functional_tests/test_latest_features_release_group_integrity.py` guards tier shape, required keys, image existence, defaults, action gates, and version alignment.
- `functional_tests/test_admin_latest_features_tab.py` pins current-tier IDs and image maps for the v0.260.001 user and admin catalogs.

## Usage Instructions

### Controlling What End Users See

1. Open **Admin Settings**.
2. Go to **General > User-Facing Latest Features**.
3. Review the current, previous, and archive release groups.
4. Toggle individual user-facing cards on or off for the tenant.
5. Save settings, then open **Support > Latest Features** as an end user to verify the visible cards.

Stored choices are merged over defaults, so disabling an older card remains honored after the v0.260.001 tier shift.

The 20 new v0.260.001 cards ship **hidden**. Their screenshots are still placeholders, so publishing them immediately would show end users a page full of "Screenshot pending" tiles. The intended rollout is:

1. Replace `release_260_<slug>_1.png`, `_2.png`, and `_3.png` for a card with real captures.
2. Open **Admin Settings > General > User-Facing Latest Features** and tick that card.
3. Save, then confirm it on **Support > Latest Features** as an end user.

Until a card is enabled, end users continue to see the previous and archive tiers, which carry real screenshots. Admins still see all 16 v0.260.001 admin cards in the Latest Features tab, since admins are the ones capturing the screenshots.

Once every card is published, the `for item in _SUPPORT_RELEASE_260_FEATURE_CATALOG` loop in `get_default_support_latest_features_visibility()` can be dropped so future tenants get the cards on by default.

The **Latest Features** admin tab also carries a read-only preview of the user-facing catalog. Each non-current tier renders as a collapsible panel whose cards show a **Shared with Users** or **Hidden from Users** badge, so an admin can review exactly what the previous and archive tiers look like without leaving Admin Settings. Its element ids are namespaced `latest-features-user-preview-*` and `latestFeaturesUserPreview*` so they never collide with the admin-facing release-group cards.

### Adding a New Card

1. Read `_latest_feature_card(...)` and the current catalog style in `support_menu_config.py` before editing.
2. Add end-user cards to the appropriate `_SUPPORT_RELEASE_*_FEATURE_CATALOG` and admin cards to the matching `_ADMIN_RELEASE_*_FEATURE_CATALOG`.
3. Use stable IDs: `release_260_<slug>` for end-user cards and `admin_release_260_<slug>` for admin cards in this release set.
4. Write card copy for the audience that sees it.
5. Add local images under `application/single_app/static/images/features/` and reference them through the helper.
6. Update tests that intentionally pin catalog IDs, image maps, or tier placement.

### Performing the Next Tier Shift

1. Move the current catalog to the `previous_release` tier.
2. Move the previous catalog into the `archive_release` tier.
3. Add the new release catalog as `current_release`.
4. Update both `_SUPPORT_LATEST_FEATURE_RELEASE_GROUPS` and `_ADMIN_LATEST_FEATURE_RELEASE_GROUPS` with the new `release_version`, `description`, `collapse_id`, and `features` values.
5. Keep only the newest current tier expanded by default.
6. Preserve visibility by relying on `normalize_support_latest_features_visibility(raw_visibility)` rather than resetting stored settings.
7. Update `functional_tests/test_latest_features_release_group_integrity.py` and `functional_tests/test_admin_latest_features_tab.py` for the new release boundary.

### Placeholder Screenshot Convention

v0.260.001 generated 76 branded "Screenshot pending" placeholders into `application/single_app/static/images/features/`:

- 60 end-user placeholders named `release_260_<slug>_1.png`, `release_260_<slug>_2.png`, and `release_260_<slug>_3.png`.
- 16 admin placeholders named `admin_release_260_<slug>.png`.

Replace a placeholder by saving the real screenshot over the same file name. No catalog change is required as long as the path stays the same.

### PR Process Hooks

- `.github/prompts/update-latest-features.prompt.md` documents the authoring workflow for turning release notes into Latest Features cards.
- `.github/PULL_REQUEST_TEMPLATE.md` includes a **Release Notes & Latest Features** block so feature PRs explicitly consider release notes, user visibility, admin visibility, card eligibility, and screenshots.
- `.github/workflows/release-notes-check.yml` warns when a feature PR appears to skip the Latest Features catalog.

## Testing and Validation

Run the focused guards after changing Latest Features catalogs or templates:

```powershell
python functional_tests\test_latest_features_release_group_integrity.py
python functional_tests\test_admin_latest_features_tab.py
```

Coverage includes:

- three-tier release group shape and ordering for user and admin catalogs
- current, previous, and archive release-version metadata
- required feature-card keys
- unique feature IDs
- screenshot asset existence and gallery path consistency
- current-tier visibility defaults
- preservation of stored visibility choices
- settings-gated action key validation
- Admin Settings tab markers, dynamic IDs, image modal hooks, and current-tier ID/image maps

### Known Limitations

- The Jekyll documentation site under `docs/latest-release/` and `docs/_data/latest_release_features.yml` was deliberately not changed in this pass and still describes the v0.250.001 set. Updating that docs site is a follow-up.
- Placeholder screenshots are intentionally branded as "Screenshot pending" until real captures are available.
- `docs/explanation/release_notes.md` preserves the 117 original v0.250.003 through v0.250.229 patch entries verbatim inside the v0.260.001 detailed change log for traceability.

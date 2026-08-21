---
name: "Update Latest Features"
description: "Use when turning SimpleChat release notes into in-app Latest Features cards for end users and admins. Guides release-tier discovery, card authoring, screenshot placeholders, tests, and tier shifts."
argument-hint: "Release version or range to publish, optional theme hints or screenshot availability"
agent: "agent"
---

# Update SimpleChat Latest Features

You are updating the in-app Latest Features catalog from `docs/explanation/release_notes.md`.

Latest Features has two audiences:

- End users see `/support/latest-features`, rendered by `application/single_app/templates/latest_features.html`.
- Admins see the Latest Features tab in Admin Settings, rendered by `application/single_app/templates/admin_settings.html`, where per-feature toggles control which user-facing cards end users can see.

All catalog data lives in `application/single_app/support_menu_config.py`. Do not guess its current structure; read it before editing.

## Initial Discovery

1. Read `application/single_app/support_menu_config.py`:
   - The helper `_latest_feature_card(...)` near the top.
   - The current user and admin catalog constants.
   - The release-group definitions near the end:
     - `_SUPPORT_LATEST_FEATURE_RELEASE_GROUPS`
     - `_ADMIN_LATEST_FEATURE_RELEASE_GROUPS`
2. Record the current tier boundary from each release group's `release_version` value:
   - `current_release`
   - `previous_release`
   - `archive_release` when present
3. Read `docs/explanation/release_notes.md` from the top down to the current tier boundary version. Stop once entries are older than the content that is already represented in the catalog.
4. Identify the target release set. Tiers always shift down by one: the outgoing current set becomes
   previous, the outgoing previous set becomes archive, and the new set becomes current. As a worked
   example, the v0.260.001 shift produced:
   - `current_release`: `0.260.001`
   - `previous_release`: `0.250.001`
   - `archive_release`: `0.239.001 - 0.241.007`

## Theme Extraction

Release notes are patch-oriented; Latest Features cards should be user-meaningful.

1. Cluster many patch entries into coherent themes by user outcome, not by file or implementation detail.
2. Merge consecutive patches that iterate the same capability, especially when several patches stabilize or expand one workflow.
3. Prefer fewer strong cards over many thin cards.
4. Classify each theme:
   - `USER_FACING`: visible to end users in chat, workspaces, support pages, agents, document flows, or public/group experiences.
   - `ADMIN_FACING`: primarily Admin Settings, tenant governance, deployment, configuration, observability, scale, or management.
   - `BOTH`: user-visible capability with meaningful admin controls or rollout responsibilities.
5. Create user cards for `USER_FACING` and the user side of `BOTH` themes.
6. Create admin cards for `ADMIN_FACING` and the admin side of `BOTH` themes.

## Card Authoring Rules

Each card must be written for the audience that sees it.

### Required keys

Every card needs:

- `id`
- `title`
- `icon`
- `summary`
- `details`
- `why`
- `guidance`
- `actions`
- image metadata through `_latest_feature_card(...)` or the current helper pattern

Use the current helper signature and existing catalog style in `support_menu_config.py`. If the helper has been expanded to support multi-image cards, use that existing pattern rather than inventing a new structure.

### IDs

Use the release number of the set you are publishing (for example `260` for v0.260.001):

- End-user card IDs use `release_<NNN>_<slug>`.
- Admin card IDs use `admin_release_<NNN>_<slug>`.
- Keep slugs short, stable, lowercase, and underscore-separated.
- Do not reuse an ID from another tier.

### Copy

- `summary`: one concise sentence describing what users/admins can do now.
- `details`: explain the workflow in product language, not implementation language.
- `why`: frame why it matters as user or admin benefit, not internal refactoring.
- `guidance`: for end-user cards, write 5-7 concrete "How To Try It" steps as actions a real user performs.
- Admin guidance should point to the exact settings, controls, governance checks, or rollout steps an admin should review.
- Avoid naming internal patch mechanics unless they directly affect the workflow.

### Icons

- Use Bootstrap Icons class names such as `bi-robot`, `bi-shield-check`, or `bi-folder2-open`.
- Choose an icon that describes the user's mental model for the theme.
- Reuse existing icon patterns when a new card extends an existing capability area.

### Actions and settings gates

- Each action should include `label`, `description`, `href`, and `icon`.
- Add `requires_settings` to user-facing actions when the linked experience should hide if the feature is disabled. Match existing setting keys already used in `support_menu_config.py`.
- Admin cards should use Admin Settings deep links with `admin_tab` and, when targeting a specific section, `admin_section`.
- Keep action links local to SimpleChat routes or Admin Settings anchors.

## Image Convention

Feature screenshots live in `application/single_app/static/images/features/`.

For v0.260.001:

- End-user card placeholders are named:
  - `release_260_<slug>_1.png`
  - `release_260_<slug>_2.png`
  - `release_260_<slug>_3.png`
- Admin card placeholders are named:
  - `admin_release_260_<slug>.png`

End-user cards should carry three images. Use placeholder images labeled "Screenshot pending" until real screenshots are available. Real screenshots replace the placeholder files in place, using the same filenames, so `support_menu_config.py` does not need a config change when screenshots are finalized.

While a release set still has placeholder screenshots, ship its end-user cards **hidden** so no one sees a "Screenshot pending" tile. Add a loop in `get_default_support_latest_features_visibility()` defaulting the new catalog's ids to `False`, and remove that loop once every card has a real capture. Admin-facing cards stay visible throughout, because admins are the ones producing the screenshots. Tests that assert card structure must then opt the cards in explicitly via `support_latest_features_visibility` rather than relying on defaults.

When adding image metadata:

- Use descriptive `alt`, `title`, `caption`, and `label` text.
- Keep placeholder captions honest: say the screenshot is pending and describe what should be captured.
- Do not link to CDN-hosted or external assets.

## Tier Shift Procedure

When publishing a new release set:

1. Move the current release catalog to the previous tier.
2. Move the previous release catalog to the archive tier.
3. Add the new release cards as the current tier.
4. Update user release groups in `_SUPPORT_LATEST_FEATURE_RELEASE_GROUPS`:
   - `id`
   - `label`
   - `description`
   - `release_version`
   - `default_expanded`
   - `collapse_id`
   - `features`
5. Update admin release groups in `_ADMIN_LATEST_FEATURE_RELEASE_GROUPS` with the same tier intent.
6. Preserve stable collapse IDs used by templates/tests unless the tier's semantic purpose changes:
   - `supportLatestFeaturesCurrentRelease`
   - `supportLatestFeaturesPreviousRelease`
   - `supportLatestFeaturesArchiveRelease`
   - `adminLatestFeaturesCurrentRelease`
   - `adminLatestFeaturesPreviousRelease`
   - `adminLatestFeaturesArchiveRelease`
7. Ensure only the newest current tier is expanded by default.
8. Keep the user and admin `current_release` and `previous_release` tiers pointing at the same
   `release_version` values so the two audiences never disagree about which release is current.

The v0.260.001 shift is the worked example of this procedure. Its end state was:

- current = `0.260.001`
- previous = `0.250.001`
- archive = `0.239.001 - 0.241.007` for users, `0.241.001 - 0.241.007` for admins

Apply the same pattern with the next release numbers when you repeat this.

## Test Updates

Update tests that intentionally hardcode catalog placement:

- `functional_tests/test_admin_latest_features_tab.py`
  - Current-tier user card ID lists.
  - Current-tier admin card ID lists.
  - Image maps and expected placeholder filenames.
  - The `release_version` assertions for each tier.
- `ui_tests/test_admin_latest_features_previous_release_images.py`
  - Specific tier placement expectations for previous-release images.
- `ui_tests/test_support_latest_features_image_modal.py`
  - The current-release cards it asserts by heading and image filename.
- `functional_tests/test_latest_features_release_group_integrity.py`
  - Structural guard covering unique IDs, required keys, on-disk images, tier ordering and version
    metadata, visibility default coverage, and `requires_settings` key validity. This should pass
    without edits if the new cards follow the conventions above; a failure here usually means a card
    is malformed rather than that the test needs changing.

Run the smallest relevant tests first, then broaden if failures indicate wider catalog issues.

## Validation Checklist

- [ ] Read `support_menu_config.py` helper and release groups before editing.
- [ ] Read release notes from the top down to the prior current boundary.
- [ ] Clustered patch entries into user-meaningful themes.
- [ ] Classified each theme as `USER_FACING`, `ADMIN_FACING`, or `BOTH`.
- [ ] Added user cards with `release_<NNN>_<slug>` IDs where appropriate.
- [ ] Added admin cards with `admin_release_<NNN>_<slug>` IDs where appropriate.
- [ ] Wrote 5-7 concrete "How To Try It" steps for each end-user card.
- [ ] Added `requires_settings` gates for actions that depend on disabled/enabled features.
- [ ] Added `admin_tab` and `admin_section` deep links for admin cards.
- [ ] Added three user placeholder images and one admin placeholder image per card, following naming conventions.
- [ ] Shifted current, previous, and archive release groups and updated `release_version` values.
- [ ] Updated hardcoded functional and UI tests for tier placement, IDs, and image maps.
- [ ] Ran relevant catalog integrity and Latest Features tests.
- [ ] Confirmed no unrelated files were changed.

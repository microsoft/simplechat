<!-- Thanks for contributing to SimpleChat! Keep this practical and delete sections that truly do not apply. -->

## Summary

<!-- What changed and why? Include the user/admin impact in 2-4 bullets. -->

-
-

## Linked issue

<!-- Use one when applicable: Fixes #123, Closes #123, Refs #123. -->

Refs #

## Release Notes & Latest Features

<!-- Check the most relevant category. Release notes go under the current VERSION from application/single_app/config.py in docs/explanation/release_notes.md. -->

- [ ] New Feature
- [ ] Bug Fix
- [ ] UI Enhancement
- [ ] Breaking Change
- [ ] Internal only

Is this visible to end users?

- [ ] Yes
- [ ] No

Is this admin-facing (Admin Settings, governance, deployment, config)?

- [ ] Yes
- [ ] No

Should this become a Latest Feature card?

- [ ] Yes
- [ ] No
- [ ] Already added

Screenshot needed for the card?

- [ ] Yes
- [ ] No
- [ ] Attached

## Version bump

<!-- Confirm application/single_app/config.py VERSION patch segment was bumped for code changes. If deployers/ changed, also bump deployers/version.txt. -->

- [ ] `application/single_app/config.py` `VERSION` third segment bumped, or not needed because this is docs-only
- [ ] `deployers/version.txt` bumped, or not needed because `deployers/` was not changed

## Testing / validation

<!-- List commands run and any manual validation. -->

-
-

## Documentation

<!-- Feature docs: docs/explanation/features/. Fix docs: docs/explanation/fixes/. -->

- [ ] Release notes updated, or not needed
- [ ] Feature documentation updated, or not needed
- [ ] Fix documentation updated, or not needed

## Security checklist

<!-- These are common SimpleChat review requirements. -->

- [ ] New Flask routes include `@swagger_route(security=get_auth_security())`
- [ ] Settings sent to non-admin frontends use `sanitize_settings_for_user()`
- [ ] Browser JavaScript is served from local SimpleChat static assets only; no CDN-hosted JS
- [ ] No secrets, keys, connection strings, or local-only artifacts are included

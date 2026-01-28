---
applyTo: '**'
---

# Release Notes Update Instructions

## When to Update Release Notes

After completing a code change (bug fix, new feature, enhancement, or breaking change), always ask the user:

**"Would you like me to update the release notes in `docs/explanation/release_notes.md`?"**

## If the User Confirms Yes

Update the release notes file following these guidelines:

### 1. Location
Release notes are located at: `docs/explanation/release_notes.md`

### 2. Version Placement
- Add new entries under the **current version** from `config.py`
- If the version has changed, create a new version section at the TOP of the file
- Format: `### **(vX.XXX.XXX)**`

### 3. Entry Categories

Organize entries under the appropriate category:

#### New Features
```markdown
#### New Features

*   **Feature Name**
    *   Brief description of what the feature does and its benefits.
    *   Additional details about functionality or configuration.
    *   (Ref: relevant files, components, or concepts)
```

#### Bug Fixes
```markdown
#### Bug Fixes

*   **Fix Name**
    *   Description of what was broken and how it was fixed.
    *   Impact or affected areas.
    *   (Ref: relevant files, functions, or components)
```

#### User Interface Enhancements
```markdown
#### User Interface Enhancements

*   **Enhancement Name**
    *   Description of UI/UX improvements.
    *   (Ref: relevant templates, CSS, or JavaScript files)
```

#### Breaking Changes
```markdown
#### Breaking Changes

*   **Change Name**
    *   Description of what changed and why.
    *   **Migration**: Steps users need to take (if any).
```

### 4. Entry Format Guidelines

- **Bold the title** of each entry
- Use bullet points for details
- Include a `(Ref: ...)` line with relevant file names, functions, or concepts
- Keep descriptions concise but informative
- Focus on user-facing impact, not implementation details

### 5. Example Entry

```markdown
*   **Custom Logo Display Fix**
    *   Fixed issue where custom logos uploaded via Admin Settings would only display on the admin page but not on other pages (chat, sidebar, landing page).
    *   Root cause was overly aggressive sanitization removing logo URLs from public settings.
    *   (Ref: logo display, settings sanitization, template conditionals)
```

### 6. Checklist Before Updating

- [ ] Confirm the current version in `config.py`
- [ ] Determine the correct category (New Feature, Bug Fix, Enhancement, Breaking Change)
- [ ] Write a clear, user-focused description
- [ ] Include relevant file/component references
- [ ] Place entry under the correct version section

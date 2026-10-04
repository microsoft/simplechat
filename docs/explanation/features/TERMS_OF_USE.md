# Terms of Use

## Overview

Implemented in version: **0.250.055**
Current documentation version: **0.261.051**
Markdown rendering implemented in version: **0.261.049**

Terms of Use lets administrators require users to accept configurable terms, rules of behavior, or an entry notice before using SimpleChat. It is separate from the existing upload-focused User Agreement.

## Technical Specifications

* **Admin settings**: Notices & Agreements settings control enablement, title, message, recurrence, cancel redirect, and button labels.
* **Message formatting**: Server-rendered Markdown supports headings, emphasis, ordered and unordered lists, links, blockquotes, horizontal rules, tables, inline code, and fenced code blocks. Ordinary line breaks are preserved. Titles and button labels remain plain text.
* **Rendering safety**: The shared Markdown filter sanitizes generated HTML with Bleach before rendering. Raw HTML is escaped, unsafe link protocols are removed, and images are not rendered. No browser scripts or external rendering services are required, including before sign-in or with JavaScript disabled.
* **Recurrence options**:
  * Every session: stored in the Flask session.
  * Once per day: stored in user settings with the accepted UTC date.
  * Just once: stored in user settings for the current terms version.
* **Terms versioning**: A hash of the title, message, and frequency invalidates older acceptances when admins change the Terms of Use.
  Rendering does not change the stored Markdown or acceptance hash. Upgrading the renderer alone does not force reacceptance; edit the message or title when updated terms should be accepted again.
  From **0.261.051**, server-assigned numbers (`v1`, `v2`, ...) identify saved
  revisions for reporting. A changed normalized title, message, or frequency
  advances the number, including edits made while disabled. Re-saving identical
  content, changing button labels or redirects, and toggling enablement do not.
  Restoring earlier text creates a new numbered revision, while acceptance
  continues to use the unchanged content-hash rules.
* **Authentication integration**:
  * Standard Microsoft sign-in users see the Terms of Use before being sent to Entra ID.
  * SSO/passive sign-in users are gated immediately after the SimpleChat session is created.
* **Redirect safety**: User-controlled return paths are local-only and stored server-side in the session. The decline destination is admin-configured and may be local or an HTTPS URL.
* **Server-side enforcement**: Authenticated browser requests are redirected to the Terms of Use page until accepted. Authenticated API requests receive a `403` response with `terms_of_use_required`.
* **Audit logging**: Accepted and declined events are written to activity logs when a user identity is known.
  In **0.261.051**, Control Center row details, the activity detail modal, and CSV
  export show **Terms version: v1** (or the recorded number). No JSON inspection is
  required. The full hash remains available in raw audit JSON for verification.
  Separate acceptance/decline filters are available. The number is local to this
  SimpleChat instance's Terms history, not the application release or UI version.
  See [#1616 and validation](../fixes/TERMS_OF_USE_AUDIT_REVISION_FIX.md).

### Numbering existing installations

The current non-empty Terms configuration becomes the `v1` baseline when its
revision metadata is successfully persisted. A new installation with no Terms
message starts numbering when its first non-empty message is saved. Admin Settings
shows the current saved version; it cannot be edited manually.

Historical audit events without a recorded number display **Legacy**, even when
they contain a hash. Their original hashes are retained; the application does not
guess historical publication order or relabel old acceptances with today's number.
Pre-authentication acceptance retains the version recorded when the user accepted.

Numbers and Terms content are committed together through the existing
conflict-protected settings store. Conflicting or failed saves cannot consume a
revision number. If migration cannot be persisted, the application does not claim
an uncommitted `v1`. The baseline itself does not invalidate existing acceptances.

## Usage Instructions

1. Open **Admin Settings**.
2. Select **Notices & Agreements**.
3. Enable **Require terms of use**.
4. Enter the Terms of Use title and message. The message supports Markdown.
5. Choose the recurrence:
   * **At the start of every session**
   * **Once per day**
   * **Just once per terms version**
6. Configure the cancel redirect URL. Use a local path such as `/` or an admin-approved HTTP(S) URL.
7. Save settings.

Users who decline are logged out locally and redirected to the configured cancel destination.

### Example message

````markdown
## Rules of behavior

Please **protect sensitive information** and use the service *responsibly*.

- Use approved data sources.
- Report unexpected behavior.

1. Review the policy.
2. Accept to continue.

[Read the policy](https://example.com/policy)

| Requirement | Action |
| --- | --- |
| Privacy | Use approved data only |

```text
Example text shown without interpreting markup.
```
````

Use backticks for literal Markdown characters. Raw HTML is shown literally rather
than interpreted. Markdown image syntax does not display images or load remote
tracking resources. Existing plain text remains supported, but Markdown punctuation
now has its usual formatting meaning.

## Testing and Validation

* Functional coverage: [acceptance and recurrence tests](../../../functional_tests/test_terms_of_use.py).
* Route policy coverage: `functional_tests/route_tests/`
* UI coverage: [Terms of Use browser tests](../../../ui_tests/test_terms_of_use_ui.py) exercise the actual template and shared Markdown filter at desktop/mobile sizes, with JavaScript disabled, safe rendering of hostile content, line breaks, scrolling, and unchanged accept/cancel POST forms.
* Revision coverage: [settings-store concurrency tests](../../../functional_tests/test_app_settings_store_consistency.py) and [Activity Logs UI/export tests](../../../ui_tests/test_terms_of_use_activity_logs.py).
* Related implementation: [pure configuration and revision helpers](../../../application/single_app/functions_terms_of_use_config.py), [terms template](../../../application/single_app/templates/terms_of_use.html), [shared Markdown filter](../../../application/single_app/app.py), and [application version](../../../application/single_app/config.py).

## Known Limitations

Before standard authentication, SimpleChat cannot know which user is signing in. Daily and once-per-version persistence is therefore applied after authentication, while the pre-auth prompt is tracked in the anonymous Flask session.

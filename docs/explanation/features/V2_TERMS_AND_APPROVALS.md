# V2 Terms of Use and Approval Requests

## Overview

Implemented in version: **0.261.277**

Brings two surfaces that still sent V2 users back to the classic interface into the React V2 UI:

* **Terms of Use**: when the terms gate fires for a `/v2` request, the user now lands on a V2 page at `/v2/terms-of-use` instead of the classic `/terms-of-use` template.
* **Approval Requests**: a V2 page at `/v2/approvals` with full parity with the classic `/approvals` page -- generic group approvals, Microsoft 365 approvals, content-screening requests, outgoing Microsoft 365 actions, paused (waiting) requests, and admin agent template approvals -- laid out like V2 Admin Settings.

Dependencies: the existing Terms of Use feature ([TERMS_OF_USE.md](TERMS_OF_USE.md)), the approvals and Microsoft 365 APIs, and the React V2 shell ([REACT_V2_UI.md](REACT_V2_UI.md)).

## Technical Specifications

### Terms of Use

* `app.py`
  * `build_terms_of_use_url(path, query_string)` picks `/v2/terms-of-use` for a V2 page or V2 API request and the classic page otherwise.
  * `/v2/terms-of-use` and the three V2 API paths are added to `TERMS_OF_USE_EXEMPT_PATHS`.
* `route_backend_v2.py` (all `@swagger_route`, `@login_required`, `@user_required`):
  * `GET /api/v2/terms-of-use?next=` returns `enabled`, `required`, the title, plain-text message, button labels, a local-only `return_path`, and sanitized branding.
  * `POST /api/v2/terms-of-use/accept` records acceptance with the classic logic and returns `redirect_url`.
  * `POST /api/v2/terms-of-use/decline` logs out and returns the configured cancel destination.
* Frontend
  * `lib/termsOfUse.ts`, `pages/TermsOfUsePage.tsx`. The message is rendered as text, never HTML.
  * `App.tsx` renders the terms page alone without loading bootstrap or user settings, since every other call is refused until acceptance.
  * `lib/apiClient.ts` sends the tab to `/v2/terms-of-use?next=<current page>` when any call returns the `terms_of_use_required` 403, for example after the terms change or a daily acceptance lapses while a tab is open.

### Approval Requests

* `pages/ApprovalsPage.tsx`: category rail (collapsible, persisted as the `v2ApprovalsRailCollapsed` user setting), a phone-width category picker, header with description and **Refresh**, and a pending-count badge for the active category.
* `components/approvals/`
  * `ApprovalParts.tsx`: shared list/detail split, toolbar, rows, pager, and notices.
  * `GenericApprovalsPanel.tsx`: All, Group, Microsoft 365 and Content screening categories from one `/api/approvals` fetch per status, filtered on the client.
  * `M365ApprovalDetail.tsx`: Microsoft 365 approval decisions, with the CSRF retry the classic page uses.
  * `PendingActionsPanel.tsx`: `/api/msgraph/pending-actions` send, send now, and cancel.
  * `PausedRequestsPanel.tsx`: `/api/m365/requests` with continuation, resume, and connect-and-resume.
  * `AgentTemplatesPanel.tsx`: `/api/admin/agent-templates` approve, reject (reason required), and delete. Admin only.
* `lib/approvalsApi.ts`: every approvals call and request-type label.
* Routes: `/approvals`, `/approvals/:category`, `/approvals/:category/:itemId`. Classic deep links (`?approval_id&group_id`, `?m365_approval`, `#agent-template-approvals`) redirect to the matching route.
* Navigation: a sidebar **Approval requests** entry; the notification bell and the Agent Templates admin link now open the V2 page.
* `route_backend_users.py`: `v2ApprovalsRailCollapsed` is an allowed user setting.

## Usage Instructions

* Terms of Use are configured as before in Admin Settings; nothing new to enable.
* Users open **Approval requests** from the V2 sidebar, pick a category, select a request, and decide in the right pane. See [Review approval requests](../../guides/review-approval-requests.md).

## Testing and Validation

* `functional_tests/test_v2_terms_and_approvals.py`: terms URL selection, exempt paths, route decorators, and frontend wiring.
* `functional_tests/test_v2_notifications_bell.py`: approval notifications route into the V2 page.
* `ui_tests/test_v2_approvals_and_terms_pages.py`: rail/list/detail layout, approve flow, classic deep link, admin-only category, phone picker, and the terms page rendering and accept redirect.

## Known Limitations

* The approvals list API filters one request type at a time and ignores search, so the page reads up to 2,000 records per status and filters them in the browser.

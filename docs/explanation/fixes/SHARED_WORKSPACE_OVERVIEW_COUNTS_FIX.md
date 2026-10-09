# Shared Workspace Overview Counts Fix

Fixed in version: **0.261.310**, recorded in
`application/single_app/config.py`.

Current application version: **0.261.313** after integrating the base branch's
file-source configuration changes and correcting review fixture initialization;
the original implementation version remains **0.261.310**.

## Issue and root cause

My workspace displayed resource counts, but the group and public workspace
overviews did not. Both shared pages rendered `WorkspaceOverview` without its
`counts` property. The badge renderer was already working; no shared-scope
count loader supplied it with data.

## Technical details

`SharedWorkspaceOverview.tsx` now loads counts only while an authorized shared
workspace overview is mounted. `sharedWorkspaceCounts.ts` reuses the scoped
document readers, authoring adapters, workflow and delegation readers, and
membership clients. Every request explicitly names the selected workspace.
Disabled sections are not fetched, and personal/admin resource readers are
never used as a fallback.

Documents use validated facets, or a minimal document page's total when facets
are unavailable. Prompts and Members use server totals from minimal unfiltered
pages, avoiding a first-page limit. Tags count distinct vocabulary entries.
Unpaginated resource collections use their validated list lengths.
Group Actions counts the full native list when enabled, or only Call agent
tools when that is the available surface.

Independent results render as they arrive. Zero is a successful empty count.
Malformed responses and failed reads produce a small red circled X with an
accessible label and tooltip, never a false zero. Locked cards remain uncounted.
Settings, Activity, and Statistics are navigation destinations, not resource
collections, so no count is added to them.

The loader aborts when the overview unmounts or its authorized context changes.
An identity-bound state prevents an old viewer/workspace's results from rendering
during a switch, even before effect cleanup. Returning from another section or
revalidating workspace access reloads counts. Personal overview behavior is
unchanged.

Members counts current roster entries, excluding pending requests. In a public
workspace, these are its Owner, Admins, and DocumentManagers, not all readers.
The existing membership API's access and disclosure rules still apply.
Public readers outside that roster do not request or display a Members count.

## Files modified

- Shared overview component and badge renderer under `application/v2_ui/src/components/workspace/`.
- Scoped count readers and related prompt, identity, workflow, and delegation helpers under `application/v2_ui/src/lib/`.
- `GroupWorkspacePage.tsx` and `PublicWorkspacePage.tsx`.
- `application/single_app/config.py` for the application patch version.
- Workspace UI fixtures and the regression tests listed below.
- Group and public workspace guides.

## Testing and validation

`functional_tests/test_v2_shared_workspace_counts.mjs` executes the production
readers with controlled HTTP responses. It covers full totals beyond 500 prompts,
zero counts, malformed responses, explicit group/public scope, document totals
without facets, Call agent-only counts, partial failure, and aborted late reads.

`ui_tests/test_v2_shared_workspace_overview_counts.py` exercises the real built SPA
through the existing Azure Playwright-compatible fixtures. It covers desktop
and mobile in both themes, available/locked cards, pagination totals, failures,
workspace switching, stale responses, returning to Overview, and access
revalidation. The fixture boundary rejects unexpected personal/admin reads.

Before the fix, shared overview cards had no counts. After the fix, each available
resource card reports its selected workspace's total without making a failed
service look like an empty workspace. There are no new routes, settings,
dependencies, storage migrations, or classic-UI changes.

### Validation results

The **0.261.313** review follow-up passes the initial group/public selection
through optional keyword-only base fixture constructor arguments rather than
overwriting inherited attributes in the overview fixture constructors. Omitted
arguments retain the existing unselected defaults. The focused overview suite
passes **24** cases, including six constructor/bootstrap checks for default,
explicitly empty, and selected scopes.

- The production-reader count test passed, as did the existing personal section
  and group/public context runtime contracts.
- The production V2 TypeScript/Vite build passed.
- All **18** new count UI cases passed in local Chromium through the shared
  Azure-compatible connection fixture. The combined count, group-shell, and
  public-journey run passed **79 of 80** cases.
- The remaining public journey checks immediate deployment-wide feature
  activation on focus. It still fails against the existing bootstrap refresh
  cooldown; this count fix does not change that behavior.
- The personal workspace and group prompt seam Python contracts passed
  (**15** checks). Additional legacy Flask-backed checks could not complete
  because the installed Flask test client expects `werkzeug.__version__`,
  which the installed Werkzeug no longer exposes.
- Documentation coverage/quality checks and the whitespace check passed.
  The changed-UI detector reported no deterministic findings.

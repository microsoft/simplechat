# V2 Workspace Presentation Fix

## Issue

A bounded presentation pass over the V2 group and public workspace sections
(M11 §2.4) found these defects. It covered desktop and mobile, light and dark,
200% text, keyboard reach, focus, accessible names, long names, and empty,
loading and failed states.

- **Dialogs lost keyboard focus.** Opening a dialog didn't move focus into it,
  Tab could leave it, and closing it, even with Escape, left focus on the page
  body. That fails WCAG 2.4.3. The dialogs are shared, so this affected every V2
  dialog, My Workspace's included.
- **A failed read looked like an empty list.** In the group and public Prompts,
  Identities, File sources, Endpoints and Workflows sections, a list that failed
  to load showed "No … yet" and a create button under the error, with no way to
  retry. The prompts error wasn't announced to screen readers.
- **Tag chips were hard to read.** A chip's text was always white, so on a
  mid-tone tag colour such as the default green it fell to 3.76:1.
- **At 200% text,** the prompt list left the details pane no width at all.
- **On a phone,** the group Actions list collapsed to nothing under the Call
  agent panel, which covered its controls, and a narrow agent or action card
  squeezed its title to a letter per line.
- **Locked overview entries** were faded to about 2.8:1 in the dark theme.
- **Public workspace copy:**
  - the Documents header offered "Browse in Classic", though public documents
    are native and only the legacy document upgrade still needs classic;
  - a link to a public document that no longer exists opened a dialog saying
    "Public workspaces have no access-removal cleanup to repair.";
  - the Identities section described identities for file sources and actions,
    though a public workspace has no actions;
  - the overview said its sections could be classic, and its Manage group
    described "Who belongs to this group".
- **A settings profile read-only because of an unrecognized status** was
  explained with the "locked or inactive" sentence.
- **Small items:** the Tags inline link wasn't underlined, the Agents title's
  target was under 24px, and the directory's visibility switch didn't wrap.

## Root cause

Each surface was built and tested on the happy path of a desktop viewport with
normal text. The shared `Modal` never managed focus, and the shared section list
treated a failed read and an empty one alike.

Fixed in version: **0.261.188**

## Technical details

- **Dialogs** (`components/ui/Modal.tsx`): focus moves into the dialog when it
  opens; Tab and Shift+Tab stay inside the innermost dialog, while a popover it
  opens keeps its own order; closing returns focus to the control that opened
  it, or to the last focused control if that one disabled itself. Escape is
  unchanged.
- **Failed reads** (`useSectionResource`, `SectionList`, the prompt workbench and
  the AI connections manager): a failed read shows its error with a
  **Retry** button and `role="alert"`, never the empty state or its create
  button. Sections that don't pass the new properties render as before. The
  section headers' create buttons stay.
- **Tag chips** take black or white text, whichever contrasts more with the
  tag's colour.
- **Layout:** the prompt list is capped at 45% of the width, and its details
  pane scrolls and can take focus. Group Actions become one scrolling column on
  a phone, and narrow cards wrap their buttons. Locked overview entries are
  outlined instead of faded. The overview is shared, so group and My Workspace
  entries change too.
- **Public copy:** the Documents header reads **Classic tools**, naming the
  legacy upgrade; a gone document says it's gone; the Identities blurb names
  file sources only; the overview describes a public workspace's sections and
  gives its Manage group its own sentence. The group text is unchanged.
- **Settings:** an unrecognized status shows the server's own sentence
  (`WorkspaceSettingsSection.tsx`, each wrapper supplying its text).

## Validation

- Every fix has a browser pin, and each of the 27 mutations of the fixes fails
  one.
- The affected group, public, workflow and My Workspace browser suites pass, one
  process each; the refusal-text parity tests hold the new settings texts.
- The remaining findings (compact explorer mode at 200% text, light-theme
  contrast tokens, and smaller items) are listed for follow-up in decision 33.

## Related

- [V2 Public Connections](../features/V2_PUBLIC_CONNECTIONS.md)
- [V2 Public Settings](../features/V2_PUBLIC_SETTINGS.md)
- [V2 My Workspace](../features/V2_MY_WORKSPACE.md)

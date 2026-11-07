# Document Collaboration Bound Scope Fix

## Issue

The V2 document collaboration adapters, for group sharing and publication
decisions and for public publication decisions, were created for one
workspace. They built every request path from that workspace, but they checked
the server's receipt against the caller's scope object as it was when the
receipt arrived. So if a caller changed its scope object after creating the
adapter, a decision the original workspace had confirmed was rejected with "The
server did not confirm this exact sharing or publication decision. Refresh
before retrying.", even though the server had applied it. The public adapter
also read the workspace name for its review details from the live object.

Found by the full comparison of the React V2 base branch's test suites against
this branch: `test_v2_group_document_collaboration.mjs` failed on this branch
only.

## Root cause

In version 0.261.134, public generated-artifact approval changed
`parseCollaborationReceipt` to take a scope object instead of a group ID. Both
adapters then passed their `scope` argument, the caller's object, where the
group adapter had captured the ID when it was created. The logic test that
would have caught it was already failing at an earlier check, and it never ran
in the milestone gates.

Fixed in version: **0.261.169**

## Technical details

| File | Change |
| --- | --- |
| `application/v2_ui/src/lib/documentCollaboration.ts` | `createDocumentCollaboration` and `createPublicDocumentCollaboration` each keep one frozen copy of their scope. It's used for the paths, the receipt check and the public review's workspace name, and it's what the adapter exposes as `scope` |
| `functional_tests/test_v2_group_document_collaboration.mjs` | A public adapter check: the caller renames and retargets its scope after binding, and every decision still goes to, and is confirmed for, the original workspace. The group check asserts the exposed scope can't be changed |

The logic test also still passed the old group-ID string to its five direct
`parseCollaborationReceipt` calls. Three of them were refusal checks that passed
only because the string wasn't a scope; they now pass the scope and must fail
with the receipt's own error. The other two, success cases, now pass too.

The same comparison found three stale tests on this branch, aligned in the same
change:
- `test_prompt_variable_knowledge_fill.py` builds the V2 route registrar from
  source. The registrar has applied `@enabled_required(...)` to the group and
  public context routes since the V2 group shell, so its namespace gains a
  pass-through.
- `test_v2_workspace_agent_authoring_logic.mjs` expects the agent knowledge
  refusal's current wording, "This agent can assign only its authorized
  knowledge sources."
- `test_workflow_per_document_analysis_mode.py` pins the validated
  `navigation.href` that the workflow alert's new tab now opens, instead of
  the raw link.

## Validation

- `test_v2_group_document_collaboration.mjs`: 19 of 19 checks. With the
  original `documentCollaboration.ts` restored, the file fails.
- `test_prompt_variable_knowledge_fill.py`: the five route tests that failed
  only on this branch pass. Its three remaining failures fail identically on
  the React V2 base branch.
- `test_v2_workspace_agent_authoring_logic.mjs` 37 of 37, and
  `test_workflow_per_document_analysis_mode.py` 3 of 3.
- No user-visible change today: both V2 Documents sections
  (`DocumentsSection.tsx`) build a new scope object for each workspace and
  never change it. The fix removes the adapters' dependency on that.

## Related

- [V2 Group Document Collaboration](../features/V2_GROUP_DOCUMENT_COLLABORATION.md)
- [Public Document Artifact Approval APIs](../features/PUBLIC_DOCUMENT_ARTIFACT_APPROVAL_APIS.md)

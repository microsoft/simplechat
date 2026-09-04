# Admin Settings Registry Merge Fixes

## Issue

Six branches described different groups of the V2 admin settings surface at the
same time, all writing into the same three registries: `ADMIN_SETTINGS_FIELDS`
in `admin_settings_fields.py`, the field type union in `adminFields.ts`, and the
component switch in `AdminSettingsPage.tsx`.

Merging them surfaced four defects that a passing build would not have caught.
Every one of them produced code that parsed, imported and ran; three of them
would have shipped silently.

**Fixed in version:** 0.261.074

## Root cause

Each branch inserts its entries at the same anchor in a large dict literal, so
git resolves the two sides by line similarity rather than by structure. The
resulting conflict regions cut through unterminated dict literals, and a
"keep both" resolution that happens to parse is not the same as a correct one.

Merging these files by text is the underlying mistake. The reliable approach is
to parse both sides with `ast`, diff the section and field key sets, and rebuild
the union — then assert the result is exactly that union.

## Defects and fixes

### 1. Nine sections declared twice

The Agents & Actions sections were added to the merged file twice: once by
splicing the section sources, and again by applying a patch that also contained
them. Python keeps the last definition of a duplicate dict key, so the file
parsed, imported and behaved correctly. Nothing failed.

`functional_tests/test_admin_settings_fields_registry_integrity.py`, added by
the Chat work, caught it on its first run.

**Fix:** rebuild the file from the incoming branch and apply this branch's diff
exactly once, rather than combining two mechanisms that each carry the same
additions.

### 2. An emptied section can orphan a setting that arrived later

`actions-config` was emptied when `enable_text_plugin` moved into
`core-plugin-toggles` with the other built-in actions. That was safe at the
time. It stopped being obviously safe when the Chat work moved a second toggle,
`enable_default_embedding_model_plugin`, into the same section afterwards —
by the time the branches met, removing the section would have dropped a setting
that had arrived while nobody was looking.

Both keys are declared in `core-plugin-toggles`, so nothing was lost, but that
was verified rather than assumed.

**Fix:** `test_removing_a_section_did_not_orphan_its_settings` in
`test_v2_admin_actions_parity.py` asserts every key that section used to hold is
declared somewhere. The general form — *a removed section must not take a
setting with it* — is the reusable part.

Restoring `actions-config` now fails the registry integrity test instead, because
its fields would be declared twice.

### 3. One key, two writable declarations

Both this branch and the Chat work declared `fact-memory-section`, identically,
with one writable field. Fact memory is a chat capability that also decides
whether agents get a memory action, so it appears in both surfaces: editable
under Chat, and as a read-only mirror under Built-in Actions.

Two writable declarations give the key two owners. `get_field_definition` prefers
a writable declaration over a mirror, but cannot choose between two writable
ones, so which declaration governed saving would have depended on dict order.

**Fix:** the Chat group owns the section, so its declaration is kept and this
branch's dropped. `test_fact_memory_stays_editable_where_it_is_owned` now asserts
there is exactly one writable declaration and that it is the one Chat owns.

### 4. A resolved duplicate exposed a latent crash

`test_v2_admin_workflow_parity.py` read `depends_on` as a single dict and raised
`'list' object has no attribute 'get'`.

The chained dependency it choked on was not new: `group_workflow_allowed_group_ids`
had carried a two-link chain for some time. It was invisible because
`workflow-settings-section` was declared **twice**, and Python keeps the later
definition — which was not the chained one. Resolving that duplicate made the
chained field live and the assumption failed immediately.

**Fix:** the test reads gates through `fields_module.iter_field_dependencies`,
the schema's own iterator, like every other caller.

This is the most transferable of the four: **fixing a duplicate declaration can
expose a bug in code that only ever saw the other copy.** The duplicate was known
and considered harmless.

## Test changed rather than code

`test_v2_admin_capability_placement.py` asserted that a suppressed capability is
not *declared*. It was narrowed to assert it is not *editable*.

A read-only mirror is not an editable declaration, and cannot be saved — the
schema rejects a write to a `readonly` field and returns an error naming its
owner. Suppression and mirroring solve the same problem differently: suppression
removes the key from the surface, while a mirror reports the derived value and
names what computes it. For `enable_tabular_processing_plugin` the mirror is more
use, because an administrator looking at what an agent can do should see that
tabular processing is on and that Enhanced Citations is what turns it on.

Both mechanisms remain: the key is still suppressed from the fallback scan, so it
is never drawn as a switch.

## Semantic collisions

Three collisions produced no conflict markers at all, because each side added an
equivalently-named-but-different helper that compiled fine alongside the other:

| Collision | Resolution |
|---|---|
| `iter_dependencies` vs `iter_field_dependencies` / `_dependency_is_satisfied` | Kept the Security work's pair; taught `_dependency_is_satisfied` to return `True` for a condition naming a runtime flag, which has no settings key and would otherwise raise `KeyError` |
| `groupFields` vs `buildSectionBlocks` | Kept `buildSectionBlocks`; it groups identically and also supports a collapsed group |
| `AdminFieldDependency` renamed to `AdminFieldCondition` | Kept both names: `AdminFieldCondition` for one condition, `AdminFieldDependency` for the one-or-many alias |

A duplicated helper is worse than a conflict. Two functions answering the same
question drift, and nothing reports it.

## Validation

| Check | Result |
|---|---|
| `test_admin_settings_fields_registry_integrity.py` | 55 sections, no duplicate sections or fields |
| `test_v2_admin_actions_parity.py` | Emptied section orphans nothing; one writable owner per key |
| `test_v2_admin_workflow_parity.py` | Chained dependencies read correctly |
| `test_v2_admin_capability_placement.py` | Read-only mirrors survive; suppression still enforced |
| All admin parity suites | 132 tests passing across every group |
| `python -m compileall application/single_app` | Clean |
| `npm run typecheck` / `npm run build` | Clean |

## Related

- `docs/explanation/features/V2_ADMIN_AGENTS_ACTIONS.md`
- `functional_tests/test_admin_settings_fields_registry_integrity.py`

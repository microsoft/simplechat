# SimpleChat Group Creation Import Fix

Fixed/Implemented in version: **0.241.121**

Related config.py update: `VERSION = "0.241.121"`

## Header Information

- Issue description: App startup failed while importing `route_backend_groups.py` because `functions_simplechat_operations.py` no longer exported `create_group_for_current_user`.
- Root cause analysis: A refactor in the shared SimpleChat operations module removed the exported group-creation wrapper even though both the group route layer and the SimpleChat Semantic Kernel plugin still import that symbol.
- Version implemented: 0.241.121

## Technical Details

- Files modified: `application/single_app/functions_simplechat_operations.py`, `application/single_app/config.py`, `functional_tests/test_simplechat_group_creation_wrapper.py`
- Code changes summary: Restored `create_group_for_current_user(...)`, preserved its feature-gating and notification flow, and added a focused regression test that compiles the wrapper in isolation and verifies its call sequence and normalization behavior.
- Testing approach: Added a functional regression test for the wrapper export and behavior, then validated the source surface with a dependency-free AST check because full app import in this environment is blocked by local Cosmos credential configuration.

## Validation

- Test results: The new regression test verifies the wrapper exists, normalizes blank group names to `Untitled Group`, trims descriptions, and still notifies after group creation.
- Before/after comparison: Before the fix, importing the group route failed immediately with `ImportError: cannot import name 'create_group_for_current_user'`. After the fix, the expected wrapper symbol is present again for both route and plugin callers.
- User experience improvements: The app can proceed past this startup regression instead of crashing during module import.
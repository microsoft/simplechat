# Group Membership Edge Cases Fix (v0.261.151)

## Issue

The classic group membership routes accepted or produced invalid data in five
cases:

1. **Approving someone who was already a member added them twice.** Approve and
   reject also removed only the first pending entry for the user, so a
   duplicate request survived. A member added directly kept their pending
   request.
2. **The owner's role could be changed.** The role change put the owner into
   `admins` or `documentManagers`. The owner stayed the owner, but the stored
   roles no longer made sense.
3. **Transferring ownership could store a nameless member.** When the old owner
   wasn't in `users[]`, they were appended as `{userId}`, with no email or name.
4. **Classic bulk remove reported every successful removal as a failure.** The
   manage page counts a row as removed only when the response carries
   `success`, and the remove route's response didn't.
5. **The members list could fail with a server error.** An entry without a
   `userId`, or a member with no name or email when searching, raised an error.

Fixed in version: **0.261.151**, tracked in `application/single_app/config.py`.

## Technical details

### Files modified

- `route_backend_groups.py`:
  - approve and reject settle every pending entry for the user, and approve
    adds the member only when they don't already hold a role;
  - a role change on the owner is refused with 409, `{"error": "Transfer
    ownership to change the owner's role.", "error_code": "owner_target"}`,
    the same answer the native route gives. The existing 403, 400 and 404
    answers keep their precedence;
  - transfer appends the old owner with the stored owner's email and name;
  - both successful remove responses gain `"success": true`;
  - the members list skips entries without a `userId`, treats a missing name or
    email as empty when searching, and returns an empty list when `users` is
    missing. The rows it returns are unchanged.
- `functions_simplechat_operations.py`: a direct add clears the added user's
  pending requests.

Every other response is unchanged. V2's group conversation invites read the
members list, so its shape was kept exactly.

### Tests

- `functional_tests/test_group_membership_legacy_responses.py`: the recorded
  classic responses, now showing the fixed behaviour. It includes
  `test_classic_bulk_remove_counts_a_removal_as_a_success`, which reads the
  manage page's bulk-remove check and calls the real route.
- `functional_tests/test_group_membership_audit_parity.py`: the fixed classic
  cases match the native routes, including the owner role refusal.
- `functional_tests/test_group_membership_legacy_guard.py`: the pending-request
  cleanup applies to the fresh copy.
- `functional_tests/test_group_membership_policy.py`: the classic and native
  rules now agree with no recorded exceptions.

These tests fail 24 times on the code before the fix.

## Impact

Approvals no longer duplicate members, and a user's requests are settled in one
decision. The owner's role changes only by transfer, and transfers keep the old
owner's details. The classic bulk remove reports its results correctly.
**Existing duplicates and stray role entries aren't repaired.** The native
member list shows each member once.

## Validation

- Before: duplicate members, an owner listed as an admin, nameless members, bulk
  removals reported as failures, and a members list that could fail.
- After: none of these can be produced, and the classic responses otherwise
  match what they were.

## Related

- [Group Membership APIs](../features/GROUP_MEMBERSHIP_APIS.md)
- [Group Membership Write Safety Fix](GROUP_MEMBERSHIP_WRITE_SAFETY_FIX.md)

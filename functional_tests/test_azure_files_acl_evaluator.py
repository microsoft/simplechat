#!/usr/bin/env python3
# test_azure_files_acl_evaluator.py
"""
Functional test for the Azure Files SDDL parser and read-access evaluator.
Version: 0.261.294
Implemented in: 0.261.294

This test ensures that Azure Files security descriptors are parsed correctly and that
read access is decided the way Windows orders a DACL, failing closed: unresolved principals,
conditional or object ACEs, and rights granted only through generic bits produce an
unverified outcome instead of access.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"
FUNCTIONAL_TESTS_ROOT = REPO_ROOT / "functional_tests"
for _path in (str(APP_ROOT), str(FUNCTIONAL_TESTS_ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import functions_azure_files_acl as acl  # noqa: E402
from test_support.versioning import assert_app_version_at_least  # noqa: E402

USER_SID = "S-1-12-1-1111111111-2222222222-3333333333-4444444444"
MEMBER_GROUP_SID = "S-1-12-1-5555555555-6666666666-7777777777-8888888888"
OTHER_GROUP_SID = "S-1-12-1-1000000001-1000000002-1000000003-1000000004"
UNKNOWN_DOMAIN_SID = "S-1-5-21-1111111111-2222222222-3333333333-1105"
ONPREM_USER_SID = "S-1-5-21-900000001-900000002-900000003-1201"


def _membership(**kwargs):
    known_non_members = {OTHER_GROUP_SID}
    return acl.build_membership(
        [USER_SID, MEMBER_GROUP_SID],
        resolve_unknown_sid=lambda sid: acl.NOT_MEMBER if sid in known_non_members else acl.UNKNOWN,
        **kwargs,
    )


def _decide(sddl, **kwargs):
    return acl.evaluate_sddl_read_access(sddl, _membership(**kwargs))


def test_version():
    assert_app_version_at_least("0.261.294")


def test_parse_owner_group_flags_and_aces():
    descriptor = acl.parse_sddl(f"O:BAG:SYD:PAI(A;OICIID;FA;;;SY)(A;;0x1200a9;;;{USER_SID})(D;IO;FA;;;CO)S:AI(AU;SA;FA;;;WD)")
    assert descriptor.owner_sid == "S-1-5-32-544"
    assert descriptor.group_sid == "S-1-5-18"
    assert descriptor.dacl_present and not descriptor.dacl_null
    assert descriptor.dacl_flags == frozenset({"P", "AI"})
    assert [ace.ace_type for ace in descriptor.dacl] == ["A", "A", "D"]
    assert descriptor.dacl[0].flags == frozenset({"OI", "CI", "ID"})
    assert descriptor.dacl[0].mask == 0x1F01FF
    assert descriptor.dacl[1].mask == 0x1200A9 and descriptor.dacl[1].sid == USER_SID
    assert descriptor.dacl[2].sid == acl.CREATOR_OWNER_SID


def test_parse_owner_sid_followed_by_group_and_lowercase_sid():
    descriptor = acl.parse_sddl(f"O:{ONPREM_USER_SID}G:DUD:(A;;FR;;;{USER_SID.lower()})")
    assert descriptor.owner_sid == ONPREM_USER_SID
    assert descriptor.group_sid == "alias:DU"
    assert descriptor.dacl[0].sid == USER_SID


def test_parse_conditional_ace_expression():
    descriptor = acl.parse_sddl('O:BAG:SYD:(XA;;FR;;;WD;(@User.Department == "Sales (EU)"))')
    assert descriptor.dacl[0].ace_type == "XA"
    assert descriptor.dacl[0].sid == acl.EVERYONE_SID


def test_malformed_descriptors_are_unverified():
    for sddl in (
        "",
        "garbage",
        "O:BAG:SYD:(A;;FR;;;WD",
        "O:BAG:SYD:(A;;FR;;;ZZ)",
        "O:BAG:SYD:(Q;;FR;;;WD)",
        "O:BAG:SYD:(A;;QQ;;;WD)",
        "O:BAG:SYD:(A;XX;FR;;;WD)",
        "O:BAG:SYD:(A;;FR;;WD)",
        "O:BAG:SYD:NO_ACCESS_CONTROL(A;;FR;;;WD)",
        "O:BAO:SY",
        "O:BAG:SYD:" + "(A;;FR;;;WD)" * (acl.MAX_ACE_COUNT + 1),
    ):
        decision = _decide(sddl)
        assert decision.outcome == acl.OUTCOME_UNVERIFIED, sddl[:60]
        assert decision.reason == acl.REASON_ACL_PARSE_ERROR, sddl[:60]


def test_test_environment_scenarios():
    scenarios = [
        (f"O:BAG:SYD:P(A;;FA;;;SY)(A;;FA;;;BA)(A;;FR;;;{USER_SID})", acl.OUTCOME_ALLOWED, acl.REASON_ACL_ALLOW),
        (f"O:BAG:SYD:P(A;;FA;;;SY)(A;;FA;;;BA)(A;;0x1200a9;;;{MEMBER_GROUP_SID})", acl.OUTCOME_ALLOWED, acl.REASON_ACL_ALLOW),
        (f"O:BAG:SYD:P(A;;FA;;;SY)(A;;FA;;;BA)(A;;FR;;;{OTHER_GROUP_SID})", acl.OUTCOME_DENIED, acl.REASON_ACL_NO_ALLOW),
        (f"O:BAG:SYD:P(D;;FA;;;{USER_SID})(A;;FR;;;WD)", acl.OUTCOME_DENIED, acl.REASON_ACL_EXPLICIT_DENY),
        (f"O:BAG:SYD:P(A;;FA;;;SY)(A;;FR;;;{UNKNOWN_DOMAIN_SID})", acl.OUTCOME_UNVERIFIED, acl.REASON_SID_UNRESOLVED),
        ("O:BAG:SYD:P(A;;FR;;;WD)", acl.OUTCOME_ALLOWED, acl.REASON_ACL_ALLOW),
        ("O:BAG:SYD:P(A;;FA;;;SY)(A;;FR;;;BU)", acl.OUTCOME_UNVERIFIED, acl.REASON_SID_UNRESOLVED),
    ]
    for sddl, outcome, reason in scenarios:
        decision = _decide(sddl)
        assert (decision.outcome, decision.reason) == (outcome, reason), (sddl, decision)
    unresolved = _decide(f"O:BAG:SYD:P(A;;FA;;;SY)(A;;FR;;;{UNKNOWN_DOMAIN_SID})")
    assert unresolved.unresolved_sids == (UNKNOWN_DOMAIN_SID,)


def test_builtin_users_policy_is_opt_in():
    sddl = "O:BAG:SYD:P(A;;FA;;;SY)(A;;FR;;;BU)"
    assert _decide(sddl, treat_builtin_users_as_member=True).outcome == acl.OUTCOME_ALLOWED


def test_ordered_evaluation():
    assert _decide(f"O:BAG:SYD:(A;;FR;;;{USER_SID})(D;;FA;;;{USER_SID})").outcome == acl.OUTCOME_ALLOWED
    assert _decide(f"O:BAG:SYD:(D;;FA;;;{USER_SID})(A;;FR;;;{USER_SID})").outcome == acl.OUTCOME_DENIED
    # A deny that does not name read data does not block reading.
    assert _decide(f"O:BAG:SYD:(D;;0x2;;;{USER_SID})(A;;FR;;;WD)").outcome == acl.OUTCOME_ALLOWED
    # Inherit-only entries do not apply to the file itself.
    assert _decide(f"O:BAG:SYD:(D;IO;FA;;;{USER_SID})(A;;FR;;;WD)").outcome == acl.OUTCOME_ALLOWED


def test_uncertain_entries_only_matter_when_they_could_change_the_answer():
    unknown_deny_first = _decide(f"O:BAG:SYD:(D;;FA;;;{UNKNOWN_DOMAIN_SID})(A;;FR;;;WD)")
    assert unknown_deny_first.outcome == acl.OUTCOME_UNVERIFIED
    assert unknown_deny_first.unresolved_sids == (UNKNOWN_DOMAIN_SID,)
    assert _decide(f"O:BAG:SYD:(A;;FR;;;WD)(D;;FA;;;{UNKNOWN_DOMAIN_SID})").outcome == acl.OUTCOME_ALLOWED
    unknown_allow_before_member_allow = _decide(f"O:BAG:SYD:(A;;FR;;;{UNKNOWN_DOMAIN_SID})(A;;FR;;;{USER_SID})")
    assert unknown_allow_before_member_allow.outcome == acl.OUTCOME_ALLOWED
    unknown_deny_before_member_deny = _decide(f"O:BAG:SYD:(D;;FR;;;{UNKNOWN_DOMAIN_SID})(D;;FR;;;{USER_SID})")
    assert unknown_deny_before_member_deny.outcome == acl.OUTCOME_DENIED
    only_unknown_denies = _decide(f"O:BAG:SYD:(D;;FA;;;{UNKNOWN_DOMAIN_SID})(A;;FR;;;{OTHER_GROUP_SID})")
    assert (only_unknown_denies.outcome, only_unknown_denies.reason) == (acl.OUTCOME_DENIED, acl.REASON_ACL_NO_ALLOW)


def test_unsupported_and_generic_entries_fail_closed():
    conditional = _decide("O:BAG:SYD:(XA;;FR;;;WD;(@User.Department == \"Sales\"))")
    assert (conditional.outcome, conditional.reason) == (acl.OUTCOME_UNVERIFIED, acl.REASON_ACL_UNSUPPORTED)
    assert conditional.unsupported_aces == ("XA",)
    generic_only = _decide(f"O:BAG:SYD:(A;;GR;;;{USER_SID})")
    assert (generic_only.outcome, generic_only.reason) == (acl.OUTCOME_UNVERIFIED, acl.REASON_ACL_UNSUPPORTED)
    assert generic_only.unsupported_aces == ("generic_rights",)
    generic_with_specific = _decide(f"O:BAG:SYD:(A;;GAFR;;;{USER_SID})")
    assert generic_with_specific.outcome == acl.OUTCOME_ALLOWED
    object_ace = _decide("O:BAG:SYD:(OA;;FR;;;WD)")
    assert object_ace.outcome == acl.OUTCOME_UNVERIFIED


def test_null_empty_and_missing_dacls():
    assert _decide("O:BAG:SYD:NO_ACCESS_CONTROL").outcome == acl.OUTCOME_ALLOWED
    empty = _decide("O:BAG:SYD:P")
    assert (empty.outcome, empty.reason) == (acl.OUTCOME_DENIED, acl.REASON_ACL_EMPTY)
    missing = _decide("O:BAG:SY")
    assert (missing.outcome, missing.reason) == (acl.OUTCOME_UNVERIFIED, acl.REASON_ACL_MISSING)


def test_owner_rights_and_creator_placeholders():
    assert _decide(f"O:{USER_SID}G:SYD:(A;;FR;;;OW)").outcome == acl.OUTCOME_ALLOWED
    assert _decide(f"O:{OTHER_GROUP_SID}G:SYD:(A;;FR;;;OW)").outcome == acl.OUTCOME_DENIED
    assert _decide(f"O:{UNKNOWN_DOMAIN_SID}G:SYD:(A;;FR;;;OW)").outcome == acl.OUTCOME_UNVERIFIED
    assert _decide("O:BAG:SYD:(A;;FR;;;CO)").outcome == acl.OUTCOME_DENIED


def test_membership_policy():
    domain_sid, rid = acl.domain_sid_and_rid(ONPREM_USER_SID)
    assert (domain_sid, rid) == ("S-1-5-21-900000001-900000002-900000003", 1201)
    membership = acl.build_membership([ONPREM_USER_SID])
    assert membership(f"{domain_sid}-513") == acl.MEMBER
    assert membership("S-1-5-21-1-2-3-513") == acl.UNKNOWN
    assert membership(f"{domain_sid}-512") == acl.NOT_MEMBER
    assert membership(acl.EVERYONE_SID) == acl.MEMBER
    assert membership(acl.NETWORK_SID) == acl.MEMBER
    assert membership("S-1-5-4") == acl.NOT_MEMBER
    assert membership("S-1-5-32-544") == acl.NOT_MEMBER
    assert membership("alias:DA") == acl.NOT_MEMBER
    assert membership("alias:DU") == acl.UNKNOWN
    assert membership(UNKNOWN_DOMAIN_SID) == acl.UNKNOWN


def test_unknown_sid_resolver_cannot_grant_membership():
    granting = acl.build_membership([USER_SID], resolve_unknown_sid=lambda sid: acl.MEMBER)
    assert granting(UNKNOWN_DOMAIN_SID) == acl.UNKNOWN

    def failing(sid):
        raise RuntimeError("directory unavailable")

    assert acl.build_membership([USER_SID], resolve_unknown_sid=failing)(UNKNOWN_DOMAIN_SID) == acl.UNKNOWN

    def raising_membership(sid):
        raise RuntimeError("lookup failed")

    decision = acl.evaluate_sddl_read_access("O:BAG:SYD:(A;;FR;;;WD)", raising_membership)
    assert decision.outcome == acl.OUTCOME_UNVERIFIED


if __name__ == "__main__":
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    results = []
    for test in tests:
        try:
            test()
            print(f"PASS {test.__name__}")
            results.append(True)
        except Exception as exc:
            print(f"FAIL {test.__name__}: {exc}")
            results.append(False)
    sys.exit(0 if all(results) else 1)

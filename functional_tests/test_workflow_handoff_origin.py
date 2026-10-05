#!/usr/bin/env python3
# test_workflow_handoff_origin.py
"""
Functional test for the one-time marker on a hand-off workflow's origin.
Version: 0.261.238
Implemented in: 0.261.238

This test ensures that ``origin.one_time``, which marks a workflow chat orchestration created for a
single hand-off run, is server-only on every client path:

* a save-route create never records it, whether the payload puts it in ``origin`` or at the top
  level, and a version 3 save refuses a top-level ``one_time``;
* an editor save of a hand-off workflow keeps it, whatever origin the payload forges or removes; the
  first material change marks the origin ``edited`` and keeps it, and re-saving, enabling, pausing
  or recording runtime progress is not an edit;
* it is outside the definition revision and the Microsoft 365 execution fingerprint;
* a chat proposal's create, dry run and edited-payload create never record it, and the personal and
  group payload dry runs record no origin at all;
* a hand-off create never adopts a chat proposal's workflow, and a chat proposal's create never
  adopts a hand-off's, including when a concurrent create wins the id.

Two client paths are covered elsewhere. The hand-off accept with an edited payload that forges
``one_time`` or ``origin`` is in ``test_workflow_handoff_builder.py``. The chat tool that creates a
workflow (``create_personal_workflow_for_current_user`` in ``simplechat_operations``) saves through
``save_personal_workflow`` with no origin, which the save-route tests here exercise.

Checks use explicit raises, so they hold under ``python -O``.
"""

import copy
import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parent))

from test_support.versioning import assert_app_version_at_least  # noqa: E402
from test_workflow_draft_save_parity import GROUP_ID, OWNER_ID, _task, _v2  # noqa: E402
from test_workflow_draft_service import (  # noqa: E402
    EMAIL_DIGEST,
    EMAIL_HANDLES,
    PROPOSAL_ID,
    USER_INFO,
    DraftHarness,
)
from test_workflow_draft_service import ORIGIN as PROPOSAL_ORIGIN  # noqa: E402
from test_workflow_origin_provenance import (  # noqa: E402
    EDITED,
    FORGED_ORIGINS,
    ORIGIN,
    SCOPES,
    UNEDITED,
    WORKFLOW_ID,
    OriginRoutes,
    _definition,
    _with_origin,
)


MINIMUM_VERSION = "0.261.238"
ONE_TIME = {**UNEDITED, "one_time": True}
ONE_TIME_EDITED = {**EDITED, "one_time": True}
# Every origin an editor save of a hand-off might carry, plus a removed one (``...``).
HANDOFF_FORGERIES = {
    **FORGED_ORIGINS,
    "not_one_time": {**UNEDITED, "one_time": False},
    "unmarked": copy.deepcopy(UNEDITED),
    "removed": ...,
}
CONFLICT_MESSAGE = "A different workflow already uses this id."


def _require(condition, message):
    """Fail even under ``python -O``, which removes assert statements."""
    if not condition:
        raise AssertionError(message)


def _same(actual, expected, label):
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


@pytest.fixture
def routes():
    return OriginRoutes()


def _handoff_create(routes, payload, *, workflow_id=WORKFLOW_ID, origin=ORIGIN):
    """The hand-off create path: a server-chosen id and origin, recorded as one-time."""
    with routes.harness.active():
        return routes.harness.personal.create_personal_workflow_if_absent(
            OWNER_ID, copy.deepcopy(payload), workflow_id=workflow_id, origin=copy.deepcopy(origin),
            actor_user_id=OWNER_ID, one_time=True,
        )


def _created_handoff(routes, version):
    workflow, created = _handoff_create(routes, _definition(version))
    _require(created is True, "The hand-off workflow was not created.")
    _same(workflow["origin"], ONE_TIME, "the created hand-off origin")
    return workflow


def _body(response):
    return response.get_data(as_text=True)


def test_version_includes_the_one_time_origin():
    assert_app_version_at_least(MINIMUM_VERSION)


# Save routes ------------------------------------------------------------------------------------

@pytest.mark.parametrize("version", [2, 3])
@pytest.mark.parametrize("scope", SCOPES)
def test_a_save_route_create_never_records_one_time(routes, scope, version):
    """Neither an origin claiming one-time nor a top-level ``one_time`` reaches a created workflow."""
    in_origin = routes.post(scope, _with_origin(_definition(version), {**ORIGIN, "one_time": True}))
    _same(in_origin.status_code, 201, f"a create with a one-time origin ({_body(in_origin)})")
    from_origin = in_origin.json["workflow"]
    stored_from_origin = copy.deepcopy(routes.stored(scope, from_origin["id"]))

    top_level = routes.post(scope, {**_definition(version), "one_time": True})
    top_level_status = top_level.status_code
    top_level_workflow = (top_level.json or {}).get("workflow") or {}
    stored_top_level = copy.deepcopy(routes.stored(scope, top_level_workflow.get("id"))) or {}
    writes = routes.writes()

    _require("origin" not in from_origin, "A save-route create returned an origin.")
    _require("origin" not in stored_from_origin, "A save-route create stored an origin.")
    if version == 2:
        _same(top_level_status, 201, f"a version 2 create with a top-level one_time ({_body(top_level)})")
        _require("one_time" not in top_level_workflow, "A version 2 create returned a top-level one_time.")
        _require(
            "one_time" not in stored_top_level and "origin" not in stored_top_level,
            "A version 2 create stored a one-time marker.",
        )
        _same(writes, 2, "the save-route creates' writes")
    else:
        _same(top_level_status, 400, f"a version 3 create with a top-level one_time ({_body(top_level)})")
        _same(writes, 1, "the save-route creates' writes")


@pytest.mark.parametrize("forged", sorted(HANDOFF_FORGERIES))
@pytest.mark.parametrize("version", [2, 3])
def test_an_editor_save_keeps_a_hand_off_one_time(routes, version, forged):
    """An editor save cannot clear, forge or remove the one-time origin a hand-off create recorded."""
    _created_handoff(routes, version)

    response = routes.post("personal", _with_origin(routes.load("personal"), HANDOFF_FORGERIES[forged]))

    _same(response.status_code, 200, f"the editor save ({_body(response)})")
    _same(response.json["workflow"]["origin"], ONE_TIME, "the saved origin")
    _same(routes.stored("personal")["origin"], ONE_TIME, "the stored origin")


@pytest.mark.parametrize("version", [2, 3])
def test_re_saving_enabling_or_pausing_a_hand_off_is_not_an_edit(routes, version):
    """Saving what the editor loaded keeps the origin unedited and one-time."""
    _created_handoff(routes, version)

    origins = []
    for change in ({}, {"is_enabled": True}, {"is_enabled": False}, {}):
        response = routes.post("personal", {**routes.load("personal"), **change})
        _same(response.status_code, 200, f"the re-save ({_body(response)})")
        origins.append(response.json["workflow"]["origin"])

    _same(origins, [ONE_TIME] * 4, "the re-saved origins")
    _same(routes.stored("personal")["origin"], ONE_TIME, "the stored origin")


@pytest.mark.parametrize("version", [2, 3])
def test_a_material_change_marks_a_hand_off_edited_and_keeps_it_one_time(routes, version):
    """The first material change sets ``edited`` for good, and ``one_time`` stays."""
    created = _created_handoff(routes, version)

    renamed = routes.post("personal", {**routes.load("personal"), "name": "Renamed digest"})
    renamed_origin = renamed.json["workflow"]["origin"] if renamed.status_code == 200 else None
    reverted = routes.post(
        "personal",
        _with_origin({**routes.load("personal"), "name": created["name"]}, {**UNEDITED, "one_time": False}),
    )

    _same(renamed.status_code, 200, f"the rename ({_body(renamed)})")
    _same(renamed_origin, ONE_TIME_EDITED, "the renamed origin")
    _same(reverted.status_code, 200, f"the revert ({_body(reverted)})")
    _same(reverted.json["workflow"]["origin"], ONE_TIME_EDITED, "the reverted origin")
    _same(routes.stored("personal")["origin"], ONE_TIME_EDITED, "the stored origin")


@pytest.mark.parametrize("version", [2, 3])
def test_a_top_level_one_time_cannot_change_a_hand_off(routes, version):
    """A version 3 save refuses the field, and a version 2 save drops it; the origin stays one-time."""
    _created_handoff(routes, version)
    before = copy.deepcopy(routes.stored("personal"))
    writes_before = routes.writes()

    response = routes.post("personal", {**routes.load("personal"), "one_time": False})
    stored = copy.deepcopy(routes.stored("personal"))
    writes_after = routes.writes()

    if version == 3:
        _same(response.status_code, 400, f"a version 3 save with a top-level one_time ({_body(response)})")
        _same(stored, before, "the stored hand-off after a refused save")
        _same(writes_after, writes_before, "the refused save's writes")
    else:
        _same(response.status_code, 200, f"a version 2 save with a top-level one_time ({_body(response)})")
        _require("one_time" not in response.json["workflow"], "A version 2 save returned a top-level one_time.")
        _require("one_time" not in stored, "A version 2 save stored a top-level one_time.")
    _same(stored["origin"], ONE_TIME, "the stored origin")


def test_runtime_progress_keeps_a_hand_off_one_time(routes):
    """A run's progress updates leave the one-time origin as the create recorded it."""
    _created_handoff(routes, 3)
    updates = {"run_count": 1, "last_run_status": "completed", "last_run_at": "2026-10-05T12:01:00+00:00"}

    with routes.harness.active():
        updated = routes.harness.personal.update_personal_workflow_runtime_fields(OWNER_ID, WORKFLOW_ID, updates)
    resaved = routes.post("personal", routes.load("personal"))

    _same(updated["origin"], ONE_TIME, "the origin after a runtime update")
    _same(resaved.status_code, 200, f"the re-save after a runtime update ({_body(resaved)})")
    _same(resaved.json["workflow"]["origin"], ONE_TIME, "the re-saved origin")


def test_one_time_is_outside_the_revision_and_the_fingerprint(routes):
    """Recording, clearing or removing the marker leaves both hashes where they were."""
    created = _created_handoff(routes, 3)
    binding = routes.harness.modules["functions_m365_workflow_binding"]
    variants = [
        created,
        {**created, "origin": UNEDITED},
        {**created, "origin": {**UNEDITED, "one_time": False}},
        {**created, "origin": ONE_TIME_EDITED},
        {key: value for key, value in created.items() if key != "origin"},
    ]

    revisions = {routes.definitions.workflow_definition_revision(variant) for variant in variants}
    fingerprints = {binding.workflow_execution_fingerprint(variant) for variant in variants}

    _require("one_time" not in routes.definitions.WORKFLOW_DEFINITION_FIELDS, "one_time is a definition field.")
    _require("one_time" not in binding.M365_WORKFLOW_FIELDS, "one_time is a Microsoft 365 field.")
    _same(revisions, {created["definition_revision"]}, "the definition revisions")
    _same(len(fingerprints), 1, "the distinct execution fingerprints")
    if created.get("m365_revision"):
        _same(fingerprints, {created["m365_revision"]}, "the execution fingerprints")


# Server creates -----------------------------------------------------------------------------------

@pytest.mark.parametrize("scope", SCOPES)
def test_a_chat_proposal_create_never_records_one_time(routes, scope):
    """A Phase 4 server create drops a one-time marker its origin claims."""
    workflow, created = routes.server_create(scope, _definition(), origin={**ORIGIN, "one_time": True})
    stored = copy.deepcopy(routes.stored(scope))

    _require(created is True, "The chat proposal's workflow was not created.")
    _same(workflow["origin"], UNEDITED, "the created origin")
    _same(stored["origin"], UNEDITED, "the stored origin")


@pytest.mark.parametrize("raced", [False, True], ids=["found", "raced"])
def test_a_hand_off_and_a_chat_proposal_never_adopt_each_other(raced, monkeypatch):
    """The same id and proposal still conflict when one create is a hand-off and the other is not."""
    proposal_first = OriginRoutes()
    handoff_first = OriginRoutes()
    proposal_first.server_create("personal", _definition())
    _handoff_create(handoff_first, _definition())
    if raced:
        # The lookup misses the record, so the conditional create's 409 path classifies it.
        for routes in (proposal_first, handoff_first):
            monkeypatch.setattr(routes.harness.personal, "get_personal_workflow", lambda *args, **kwargs: None)

    outcomes = {}
    for label, routes, attempt in (
        ("handoff_over_proposal", proposal_first,
         lambda: _handoff_create(proposal_first, _definition(name="A hand-off"))),
        ("proposal_over_handoff", handoff_first,
         lambda: handoff_first.server_create("personal", _definition(name="A proposal"))),
    ):
        # Each harness loads its own modules, so each raises its own conflict class.
        try:
            attempt()
            outcomes[label] = "adopted"
        except routes.definitions.WorkflowDefinitionConflict as exc:
            outcomes[label] = str(exc)

    _same(outcomes, {
        "handoff_over_proposal": CONFLICT_MESSAGE, "proposal_over_handoff": CONFLICT_MESSAGE,
    }, "the cross-kind creates")
    _same(proposal_first.stored("personal")["origin"], UNEDITED, "the chat proposal's stored origin")
    _same(handoff_first.stored("personal")["origin"], ONE_TIME, "the hand-off's stored origin")
    _same((proposal_first.writes(), handoff_first.writes()), (1, 1), "the cross-kind creates' writes")


def test_a_repeated_create_adopts_only_its_own_kind():
    """``existing_server_created_workflow`` matches the one-time marker exactly, both ways."""
    definitions = OriginRoutes().definitions
    records = {
        "proposal": {"origin": copy.deepcopy(UNEDITED)},
        "handoff": {"origin": copy.deepcopy(ONE_TIME)},
        "false_marker": {"origin": {**UNEDITED, "one_time": False}},
        "truthy_marker": {"origin": {**UNEDITED, "one_time": "yes"}},
    }

    outcomes = {}
    for label, record in records.items():
        for one_time in (False, True):
            try:
                definitions.existing_server_created_workflow(record, ORIGIN["proposal_id"], one_time=one_time)
                outcomes[(label, one_time)] = "adopted"
            except definitions.WorkflowDefinitionConflict:
                outcomes[(label, one_time)] = "conflict"

    _same(outcomes, {
        ("proposal", False): "adopted", ("proposal", True): "conflict",
        ("handoff", False): "conflict", ("handoff", True): "adopted",
        ("false_marker", False): "adopted", ("false_marker", True): "conflict",
        ("truthy_marker", False): "adopted", ("truthy_marker", True): "conflict",
    }, "the repeated-create outcomes")


# Draft service paths ----------------------------------------------------------------------------------

def test_a_chat_proposal_draft_never_records_one_time():
    """The Phase 4 blueprint dry run and create, and the edited-payload create, drop the marker."""
    forged = {**PROPOSAL_ORIGIN, "one_time": True}
    blueprint = DraftHarness()
    dry = blueprint.dry_run(EMAIL_DIGEST, EMAIL_HANDLES, origin=copy.deepcopy(forged))
    created = blueprint.create(EMAIL_DIGEST, EMAIL_HANDLES, origin=copy.deepcopy(forged))
    workflow_id = blueprint.drafts.orchestration_workflow_id(OWNER_ID, PROPOSAL_ID)
    stored = copy.deepcopy(blueprint.containers["personal_workflows"].items.get((OWNER_ID, workflow_id)) or {})

    edited = DraftHarness()
    payload = edited.call(
        "build_workflow_blueprint_payload", copy.deepcopy(EMAIL_DIGEST), copy.deepcopy(EMAIL_HANDLES),
        workflow_id=workflow_id, user_id=OWNER_ID, settings=edited.settings,
    )
    from_payload = edited.call(
        "create_personal_workflow_from_payload", OWNER_ID,
        {**payload, "name": "My digest", "one_time": True, "origin": copy.deepcopy(forged)},
        origin=copy.deepcopy(forged), settings=edited.settings, user_info=USER_INFO,
    )
    stored_from_payload = copy.deepcopy(
        edited.containers["personal_workflows"].items.get((OWNER_ID, workflow_id)) or {},
    )

    expected = {**PROPOSAL_ORIGIN, "edited": False}
    _require(dry["ok"] is True, f"The blueprint dry run failed: {dry['errors']!r}")
    _same(dry["workflow"]["origin"], expected, "the dry-run origin")
    _require(created["ok"] is True and created["created"] is True, f"The create failed: {created['errors']!r}")
    _same(created["workflow"]["origin"], expected, "the created origin")
    _same(stored.get("origin"), expected, "the stored origin")
    _require(from_payload["ok"] is True, f"The edited-payload create failed: {from_payload['errors']!r}")
    _same(stored_from_payload.get("origin"), expected, "the edited-payload stored origin")
    _require("one_time" not in stored_from_payload, "The edited-payload create stored a top-level one_time.")
    _same(stored_from_payload.get("name"), "My digest", "the edited-payload name")


def test_a_payload_dry_run_records_no_origin():
    """The personal and group payload dry runs, which back the editors, never record an origin."""
    harness = DraftHarness()
    payload = {
        **_v2("Weekly digest", tasks=[_task("sum", "Summarize", "Summarize the week.")]),
        "one_time": True,
        "origin": {**ORIGIN, "one_time": True},
    }

    personal = harness.call("dry_run_personal_workflow", OWNER_ID, copy.deepcopy(payload), settings=harness.settings)
    group = harness.call(
        "dry_run_group_workflow", GROUP_ID, copy.deepcopy(payload), OWNER_ID, user_info=USER_INFO,
        settings=harness.settings,
    )

    for label, result in (("personal", personal), ("group", group)):
        _require(result["ok"] is True, f"The {label} dry run failed: {result['errors']!r}")
        _require("origin" not in result["workflow"], f"The {label} dry run recorded an origin.")
        _require("one_time" not in result["workflow"], f"The {label} dry run recorded a top-level one_time.")
    _same(harness.writes(), {}, "the dry runs' writes")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))

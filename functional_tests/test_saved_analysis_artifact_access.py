# test_saved_analysis_artifact_access.py
"""
Functional tests for Analyze artifact association and publication eligibility.
Version: 0.261.109
Implemented in: 0.261.109

New projections require their exact saved producer and current source access.
Legacy artifacts keep their existing access rules.
"""

from copy import deepcopy

import pytest

from test_saved_analysis_service import read_options, saved, saved_chat
from test_support.app_stubs import import_app_module


access = import_app_module("functions_analysis_access")


def artifact_for(fixture):
    return {
        "id": "artifact-1", "conversation_id": "conversation-1", "role": "file",
        "metadata": saved.analysis_artifact_metadata({
            "kind": "chat", "conversation_id": "conversation-1", "message_id": "assistant-1",
        }),
    }


def authorize(fixture, artifact, **kwargs):
    return saved.authorize_analysis_artifact(
        "reader", artifact,
        parents_loader=lambda *args: [fixture["message"]],
        result_reader=lambda user_id, context: saved.load_saved_analysis(
            user_id, context, **read_options(fixture)
        ),
        **kwargs,
    )


def test_projection_is_readable_only_through_its_saved_producer(saved_chat):
    authorize(saved_chat, artifact_for(saved_chat))


def test_staged_unassociated_artifact_is_not_readable(saved_chat):
    with pytest.raises(access.AnalysisResultUnavailable) as failure:
        saved.authorize_analysis_artifact(
            "reader", artifact_for(saved_chat), parents_loader=lambda *args: [],
        )
    assert failure.value.code == "analysis_artifact_unbound"


def test_another_analysis_cannot_satisfy_the_artifact_binding(saved_chat):
    artifact = artifact_for(saved_chat)
    artifact["metadata"]["analysis_producer"]["message_id"] = "another-analysis"
    with pytest.raises(access.AnalysisResultUnavailable):
        authorize(saved_chat, artifact)


def test_revoked_source_blocks_an_existing_projection(saved_chat):
    saved_chat["state"]["source_allowed"] = False
    with pytest.raises(access.AnalysisResultUnavailable):
        authorize(saved_chat, artifact_for(saved_chat))


def test_partial_report_can_be_inspected_but_cannot_be_published(saved_chat):
    artifact = artifact_for(saved_chat)

    def partial_reader(*args):
        return {"execution": {"status": "succeeded"}, "validation": {"status": "partial"}}, None, {}

    saved.authorize_analysis_artifact(
        "reader", artifact, parents_loader=lambda *args: [saved_chat["message"]],
        result_reader=partial_reader,
    )
    with pytest.raises(access.AnalysisResultUnavailable) as failure:
        saved.authorize_analysis_artifact(
            "reader", artifact, for_publication=True,
            parents_loader=lambda *args: [saved_chat["message"]], result_reader=partial_reader,
        )
    assert failure.value.code == "analysis_artifact_not_valid"


def test_legacy_artifact_does_not_invent_an_analysis_binding():
    saved.authorize_analysis_artifact(
        "reader", {"id": "legacy", "metadata": {}},
        parents_loader=lambda *args: pytest.fail("Legacy artifacts have no result-parent query."),
    )


@pytest.mark.parametrize("producer", [{}, {"kind": []}, {"kind": "chat"}, {"kind": "workflow", "workflow_id": "w"}])
def test_incomplete_producers_are_rejected(producer):
    with pytest.raises(ValueError):
        saved.analysis_artifact_metadata(producer)


def test_a_mirrored_message_rebases_context_without_changing_the_producer(saved_chat):
    original = deepcopy(saved_chat["message"])
    original["metadata"]["analysis_result_contexts"] = [
        saved.saved_analysis_context(saved_chat["descriptor"])
    ]
    mirrored = {**deepcopy(original), "id": "mirror-1", "conversation_id": "mirror-conversation"}
    rebased = saved.rebase_saved_analysis_message(mirrored)
    descriptor = rebased["metadata"]["saved_analysis"]
    assert descriptor["conversation_id"] == "mirror-conversation"
    assert descriptor["message_id"] == "mirror-1"
    assert descriptor["binding"] == saved_chat["descriptor"]["binding"]
    assert rebased["metadata"]["analysis_result_contexts"] == [
        saved.saved_analysis_context(descriptor)
    ]
    assert mirrored["metadata"]["saved_analysis"] == original["metadata"]["saved_analysis"]

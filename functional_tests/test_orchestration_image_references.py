# test_orchestration_image_references.py
#!/usr/bin/env python3
"""
Functional test for orchestration image references.
Version: 0.261.205
Implemented in: 0.261.192
Missing signed-in session failure for image inputs implemented in: 0.261.205

This test ensures orchestration plans can seed, validate, bind, and execute image
references without trusting planner or browser-supplied labels.
"""

import sys
from types import SimpleNamespace

import pytest

from test_support.versioning import assert_app_version_at_least


assert_app_version_at_least("0.261.192")


def test_seed_normalization_and_invalid_input():
    from functions_image_references import ImageReferenceError
    from functions_orchestration_context import resolve_seeds

    seeds = resolve_seeds({
        "image_references": [
            {"type": "message", "message_id": "conversation-1_image_1"},
            {"type": "message", "message_id": "conversation-1_image_1"},
            {"type": "document", "document_id": "doc-1", "scope": "personal"},
        ],
    })

    assert seeds["image_references"] == [
        {"type": "message", "message_id": "conversation-1_image_1"},
        {"type": "document", "document_id": "doc-1", "scope": "personal", "scope_id": None},
    ]
    with pytest.raises(ImageReferenceError):
        resolve_seeds({"image_references": "doc-1"})


def test_candidate_computation_images_only_and_conversation_mismatch(monkeypatch):
    import functions_orchestration_source_access as source_access
    from functions_orchestration_context import (
        CatalogResolutionError,
        resolve_image_reference_candidates,
    )

    def manifest(ids, *_args, **_kwargs):
        names = {
            "doc-image": "house.jpg",
            "doc-heic": "photo.heic",
            "doc-text": "notes.txt",
            "doc-ref": "map.png",
        }
        return [
            {
                "document_id": document_id,
                "file_name": names[document_id],
                "display_name": names[document_id],
                "scope": "personal",
                "scope_id": None,
                "authorization_status": "authorized",
                "source_kind": "narrative",
            }
            for document_id in ids
        ]

    class Messages:
        def read_item(self, item, partition_key):
            if item == "conversation-1_file_1" and partition_key == "conversation-1":
                return {
                    "id": item,
                    "conversation_id": "conversation-1",
                    "role": "file",
                    "filename": "sketch.png",
                    "workspace_document_id": "doc-upload",
                }
            if item == "conversation-2_image_1":
                return {"id": item, "conversation_id": "conversation-2", "role": "image"}
            raise KeyError(item)

    monkeypatch.setattr(source_access, "resolve_orchestration_source_manifest", manifest)
    monkeypatch.setitem(
        sys.modules,
        "config",
        SimpleNamespace(cosmos_messages_container=Messages()),
    )

    seeds = {
        "document_ids": ["doc-image", "doc-heic", "doc-text"],
        "image_references": [
            {"type": "document", "document_id": "doc-ref", "scope": "personal", "scope_id": None},
            {"type": "message", "message_id": "conversation-1_file_1"},
        ],
    }
    resolved = resolve_image_reference_candidates(seeds, "user-1", "conversation-1")
    assert resolved["image_reference_documents"] == [
        {"document_id": "doc-image", "scope": "personal", "scope_id": None, "file_name": "house.jpg"},
        {"document_id": "doc-ref", "scope": "personal", "scope_id": None, "file_name": "map.png"},
    ]
    assert resolved["image_reference_messages"] == [
        {"message_id": "conversation-1_file_1", "file_name": "sketch.png", "label": "sketch.png"},
    ]

    with pytest.raises(CatalogResolutionError):
        resolve_image_reference_candidates(
            {"image_references": [{"type": "message", "message_id": "conversation-2_image_1"}]},
            "user-1",
            "conversation-1",
        )


def _capability():
    return {
        "enabled": True,
        "editing": True,
        "max_reference_images": 2,
        "input_formats": ["image/png", "image/jpeg"],
        "sizes": ["1024x1024"],
        "qualities": ["high"],
        "backgrounds": [],
    }


def test_registry_schema_offers_reference_fields_and_max_items():
    from functions_orchestration_registry import generate_image_arguments_schema

    schema = generate_image_arguments_schema({
        **_capability(),
        "image_reference_documents": [{"document_id": "doc-image", "file_name": "house.jpg"}],
        "image_reference_messages": [{"message_id": "conversation-1_file_1", "file_name": "sketch.png"}],
    })
    assert schema["properties"]["reference_document_ids"]["items"]["enum"] == ["doc-image"]
    assert schema["properties"]["reference_message_ids"]["items"]["enum"] == ["conversation-1_file_1"]
    assert schema["properties"]["reference_document_ids"]["maxItems"] == 2

    omitted = generate_image_arguments_schema({**_capability(), "max_reference_images": 0})
    assert "reference_document_ids" not in omitted["properties"]


def _plan(args):
    return {
        "planner_contract_version": 2,
        "steps": [{
            "step_id": "image_1",
            "capability_id": "generate_image",
            "title": "Image",
            "rationale": "Create it",
            "arguments": {"prompt": "Make a cartoon.", "title": "Cartoon", **args},
            "depends_on": [],
            "inputs": {},
            "outputs": [{"name": "image", "kind": "image-asset-v1"}],
        }],
    }


def test_validation_rejects_unknown_duplicate_and_over_limit(monkeypatch):
    import functions_image_edit
    from functions_orchestration_schema import PlanValidationError, validate_plan

    monkeypatch.setattr(functions_image_edit, "resolve_image_edit_capability", lambda _settings: _capability())
    seeds = {
        "image_reference_documents": [{"document_id": "doc-image", "scope": "personal", "scope_id": None, "file_name": "house.jpg"}],
        "image_reference_messages": [{"message_id": "conversation-1_file_1", "file_name": "sketch.png", "label": "sketch.png"}],
    }

    checked = validate_plan(
        _plan({"reference_document_ids": ["doc-image"]}),
        settings={},
        authorized_document_ids={"doc-image"},
        available_capability_ids={"generate_image"},
        seeds=seeds,
    )
    assert checked["steps"][0]["arguments"]["reference_document_ids"] == ["doc-image"]

    with pytest.raises(PlanValidationError):
        validate_plan(
            _plan({"reference_document_ids": ["missing"]}),
            settings={},
            authorized_document_ids={"doc-image"},
            available_capability_ids={"generate_image"},
            seeds=seeds,
        )
    with pytest.raises(PlanValidationError):
        validate_plan(
            _plan({"reference_document_ids": ["doc-image", "doc-image"]}),
            settings={},
            authorized_document_ids={"doc-image"},
            available_capability_ids={"generate_image"},
            seeds=seeds,
        )
    with pytest.raises(PlanValidationError):
        validate_plan(
            _plan({
                "reference_document_ids": ["doc-image"],
                "reference_message_ids": ["conversation-1_file_1", "conversation-1_file_2"],
            }),
            settings={},
            authorized_document_ids={"doc-image"},
            available_capability_ids={"generate_image"},
            seeds={**seeds, "image_reference_messages": [
                *seeds["image_reference_messages"],
                {"message_id": "conversation-1_file_2", "file_name": "other.png", "label": "other.png"},
            ]},
        )


def test_plan_document_ids_include_reference_documents():
    from functions_orchestration_schema import plan_document_ids

    assert plan_document_ids(_plan({"reference_document_ids": ["doc-image"]})) == ["doc-image"]


_SEEDS = {
    "image_reference_documents": [{"document_id": "doc-image", "scope": "personal", "scope_id": None, "file_name": "house.jpg"}],
    "image_reference_messages": [{"message_id": "conversation-1_file_1", "file_name": "sketch.png", "label": "sketch.png"}],
}


def _validated_reference_plan(monkeypatch):
    import functions_image_edit
    from functions_orchestration_schema import validate_plan

    monkeypatch.setattr(functions_image_edit, "resolve_image_edit_capability", lambda _settings: _capability())
    return validate_plan(
        _plan({"reference_document_ids": ["doc-image"], "reference_message_ids": ["conversation-1_file_1"]}),
        settings={},
        authorized_document_ids={"doc-image"},
        available_capability_ids={"generate_image"},
        seeds=_SEEDS,
    )


def test_validation_requires_the_runs_seeded_candidates(monkeypatch):
    from functions_orchestration_schema import PlanValidationError, validate_plan

    plan = _validated_reference_plan(monkeypatch)
    # The executor re-validates with the run's seeds; without them nothing is offered.
    with pytest.raises(PlanValidationError, match="reference image is unavailable"):
        validate_plan(
            plan, settings={}, authorized_document_ids={"doc-image"},
            available_capability_ids={"generate_image"}, seeds=None,
        )
    with pytest.raises(PlanValidationError, match="reference image is unavailable"):
        validate_plan(
            _plan({"reference_document_ids": ["doc-image"]}), settings={},
            authorized_document_ids=set(), available_capability_ids={"generate_image"}, seeds=_SEEDS,
        )


def test_approval_edits_remove_references_down_to_a_prompt_only_image(monkeypatch):
    from functions_orchestration_schema import apply_plan_edits, validate_plan

    unchanged = apply_plan_edits(_validated_reference_plan(monkeypatch), {})
    assert unchanged["steps"][0]["arguments"]["reference_message_ids"] == ["conversation-1_file_1"]

    without_message = apply_plan_edits(
        _validated_reference_plan(monkeypatch),
        {"removed_document_ids": {"image_1": ["conversation-1_file_1"]}},
    )
    arguments = without_message["steps"][0]["arguments"]
    assert "reference_message_ids" not in arguments
    assert arguments["reference_document_ids"] == ["doc-image"]
    assert without_message["approval"]["edited"] is True

    prompt_only = apply_plan_edits(
        _validated_reference_plan(monkeypatch),
        {"removed_document_ids": {"image_1": ["conversation-1_file_1", "doc-image"]}},
    )
    arguments = prompt_only["steps"][0]["arguments"]
    assert "reference_message_ids" not in arguments and "reference_document_ids" not in arguments
    assert arguments["prompt"] == "Make a cartoon."
    # The edited plan still passes the run-time validation it will meet in the executor.
    validate_plan(
        prompt_only, settings={}, authorized_document_ids={"doc-image"},
        available_capability_ids={"generate_image"}, seeds=_SEEDS,
    )


def _manifest_recorder(sources, requests):
    def manifest(ids, _user_id, **kwargs):
        requests.append((list(ids), kwargs.get("doc_scope")))
        return [dict(sources[document_id], document_id=document_id) for document_id in ids if document_id in sources]
    return manifest


def _source(file_name, scope="personal", scope_id="user-1", status="authorized"):
    return {
        "file_name": file_name, "display_name": file_name, "scope": scope, "scope_id": scope_id,
        "authorization_status": status, "source_kind": "narrative",
    }


def test_candidates_use_enriched_metadata_scopes_and_fold_uploads(monkeypatch):
    import functions_orchestration_source_access as source_access
    from functions_orchestration_context import (
        image_reference_provenance_from_seeds,
        resolve_image_reference_candidates,
    )

    requests = []
    sources = {
        "doc-upload": _source("house.jpg"),
        "doc-group": _source("map.png", scope="group", scope_id="group-1"),
        "doc-group-unscoped": _source("plan.png", scope="group", scope_id=""),
        "doc-chat": _source("chat.png", scope="chat", scope_id="conversation-1"),
        "doc-denied": _source("secret.png", status="unavailable"),
    }
    monkeypatch.setattr(source_access, "resolve_orchestration_source_manifest", _manifest_recorder(sources, requests))

    class Messages:
        def read_item(self, item, partition_key):
            assert partition_key == "conversation-1"
            return {
                "id": item, "conversation_id": "conversation-1", "role": "file",
                "filename": "house.jpg", "workspace_document_id": "doc-upload",
            }

    monkeypatch.setitem(sys.modules, "config", SimpleNamespace(cosmos_messages_container=Messages()))
    selected = ["doc-upload", "doc-report", "doc-group", "doc-group-unscoped", "doc-chat", "doc-denied"]
    enriched = [
        {"document_id": document_id, "file_name": (sources.get(document_id) or {}).get("file_name", "report.pdf")}
        for document_id in selected
    ]
    seeds = {
        "document_ids": selected,
        "image_references": [{"type": "message", "message_id": "conversation-1_file_1"}],
    }

    resolved = resolve_image_reference_candidates(seeds, "user-1", "conversation-1", candidates=enriched)

    # Only selected images are read again; the report's enriched metadata already answered it.
    assert requests == [(["doc-upload", "doc-group", "doc-group-unscoped", "doc-chat", "doc-denied"], "all")]
    assert resolved["image_reference_documents"] == [
        {"document_id": "doc-upload", "scope": "personal", "scope_id": None, "file_name": "house.jpg"},
        {"document_id": "doc-group", "scope": "group", "scope_id": "group-1", "file_name": "map.png"},
    ]
    # The upload message and its selected workspace document are offered once, as the document.
    assert resolved["image_reference_messages"] == []
    assert resolved["image_references"] == [
        {"type": "document", "document_id": "doc-upload", "scope": "personal", "scope_id": None},
    ]
    assert image_reference_provenance_from_seeds(resolved) == [
        {"type": "document", "document_id": "doc-upload", "scope": "personal", "scope_id": None, "file_name": "house.jpg"},
    ]
    # The caller's seeds are left as they were.
    assert seeds["image_references"] == [{"type": "message", "message_id": "conversation-1_file_1"}]


def test_candidate_manifests_are_read_in_bounded_batches(monkeypatch):
    import functions_orchestration_source_access as source_access
    from functions_mixed_source_orchestration import SOURCE_MANIFEST_MAX_SOURCES
    from functions_orchestration_context import resolve_image_reference_candidates

    requests = []
    selected = [f"doc-{index}" for index in range(SOURCE_MANIFEST_MAX_SOURCES * 2 + 5)]
    sources = {document_id: _source(f"{document_id}.png") for document_id in selected}
    monkeypatch.setattr(source_access, "resolve_orchestration_source_manifest", _manifest_recorder(sources, requests))

    resolved = resolve_image_reference_candidates({"document_ids": selected}, "user-1", "conversation-1")

    assert [len(ids) for ids, _scope in requests] == [SOURCE_MANIFEST_MAX_SOURCES, SOURCE_MANIFEST_MAX_SOURCES, 5]
    assert [item["document_id"] for item in resolved["image_reference_documents"]] == selected


def test_an_explicit_reference_document_is_never_dropped_silently(monkeypatch):
    import functions_orchestration_source_access as source_access
    from functions_orchestration_context import CatalogResolutionError, resolve_image_reference_candidates

    sources = {"doc-heic": _source("photo.heic"), "doc-image": _source("house.jpg")}
    monkeypatch.setattr(source_access, "resolve_orchestration_source_manifest", _manifest_recorder(sources, []))
    reference = {"type": "document", "document_id": "doc-heic", "scope": "personal", "scope_id": None}

    with pytest.raises(CatalogResolutionError, match="could not be opened"):
        resolve_image_reference_candidates(
            {"document_ids": ["doc-heic"], "image_references": [reference]}, "user-1", "conversation-1",
        )
    with pytest.raises(CatalogResolutionError, match="could not be opened"):
        resolve_image_reference_candidates(
            {"image_references": [{**reference, "document_id": "doc-missing"}]}, "user-1", "conversation-1",
        )
    # A selected HEIC document that nobody asked to use as a reference is simply not offered.
    resolved = resolve_image_reference_candidates(
        {"document_ids": ["doc-heic", "doc-image"]}, "user-1", "conversation-1",
    )
    assert [item["document_id"] for item in resolved["image_reference_documents"]] == ["doc-image"]


def test_candidate_metadata_failures_are_user_safe(monkeypatch):
    import functions_orchestration_source_access as source_access
    from functions_orchestration_context import CatalogResolutionError, resolve_image_reference_candidates

    def broken(*_args, **_kwargs):
        raise RuntimeError("cosmos://secret-endpoint unavailable")

    monkeypatch.setattr(source_access, "resolve_orchestration_source_manifest", broken)
    with pytest.raises(CatalogResolutionError) as caught:
        resolve_image_reference_candidates({"document_ids": ["doc-image"]}, "user-1", "conversation-1")
    assert caught.value.code == "image_reference_unavailable"
    assert "secret" not in caught.value.message


def test_candidates_are_withheld_when_the_image_model_cannot_use_references(monkeypatch):
    import functions_orchestration_images as images
    import functions_orchestration_source_access as source_access
    from functions_orchestration_context import CatalogResolutionError, resolve_image_reference_candidates

    requests = []
    monkeypatch.setattr(
        source_access, "resolve_orchestration_source_manifest",
        _manifest_recorder({"doc-image": _source("house.jpg")}, requests),
    )
    reference = {"type": "document", "document_id": "doc-image", "scope": "personal", "scope_id": None}

    monkeypatch.setattr(images, "image_generation_readiness", lambda _settings: {"status": "available", "max_reference_images": 0})
    with pytest.raises(CatalogResolutionError, match="cannot use reference images"):
        resolve_image_reference_candidates(
            {"document_ids": ["doc-image"], "image_references": [reference]}, "user-1", "conversation-1", settings={},
        )
    withheld = resolve_image_reference_candidates(
        {"document_ids": ["doc-image"], "image_generation": True}, "user-1", "conversation-1", settings={},
    )
    assert withheld["image_reference_documents"] == [] and withheld["image_reference_messages"] == []
    assert withheld["document_ids"] == ["doc-image"]

    monkeypatch.setattr(images, "image_generation_readiness", lambda _settings: {"status": "unavailable"})
    unavailable = resolve_image_reference_candidates(
        {"document_ids": ["doc-image"], "image_references": [reference]}, "user-1", "conversation-1", settings={},
    )
    assert unavailable["image_reference_documents"] == [] and unavailable["image_reference_messages"] == []
    assert requests == []

    monkeypatch.setattr(images, "image_generation_readiness", lambda _settings: {"status": "available", "max_reference_images": 2})
    offered = resolve_image_reference_candidates(
        {"document_ids": ["doc-image"], "image_references": [reference]}, "user-1", "conversation-1", settings={},
    )
    assert [item["document_id"] for item in offered["image_reference_documents"]] == ["doc-image"]


def test_readiness_keeps_prompt_only_images_when_reference_metadata_fails(monkeypatch):
    import functions_image_api_route
    import functions_image_edit
    from functions_orchestration_images import image_generation_readiness

    settings = {"enable_image_generation": True}
    monkeypatch.setattr(
        functions_image_api_route, "resolve_selected_image_capability",
        lambda _settings: {"sizes": ["1024x1024", 7], "qualities": ["high"], "backgrounds": []},
    )

    def broken(_settings):
        raise RuntimeError("edit profile unavailable")

    monkeypatch.setattr(functions_image_edit, "resolve_image_edit_capability", broken)
    readiness = image_generation_readiness(settings)
    assert readiness["status"] == "available" and readiness["sizes"] == ["1024x1024"]
    assert readiness["editing"] is False and readiness["max_reference_images"] == 0

    monkeypatch.setattr(
        functions_image_edit, "resolve_image_edit_capability",
        lambda _settings: {**_capability(), "max_reference_images": 16, "input_fidelity": True},
    )
    readiness = image_generation_readiness(settings)
    assert readiness["editing"] is True and readiness["max_reference_images"] == 10
    assert readiness["input_fidelity"] is True
    assert readiness["input_formats"] == ["image/png", "image/jpeg"]

    monkeypatch.setattr(
        functions_image_edit, "resolve_image_edit_capability",
        lambda _settings: {**_capability(), "enabled": False},
    )
    readiness = image_generation_readiness(settings)
    assert readiness["editing"] is False and readiness["max_reference_images"] == 0

    def unavailable(_settings):
        raise RuntimeError("no image model")

    monkeypatch.setattr(functions_image_api_route, "resolve_selected_image_capability", unavailable)
    assert image_generation_readiness(settings) == {"status": "unavailable", "reason": "image_generation_unavailable"}
    assert image_generation_readiness({})["reason"] == "image_generation_disabled"


def _execution_source(document_id="doc-image", *, status="authorized"):
    """One entry of the step's authorized source manifest, as the executor supplies it."""
    return {
        "document_id": document_id,
        "display_name": "house.jpg",
        "file_name": "house.jpg",
        "scope": "personal",
        "scope_id": "user-1",
        "source_version": 3,
        "source_revision": None,
        "storage_locator": {"container": "user-documents", "path": "user-1/house.jpg"},
        "authorization_status": status,
        "source_kind": "narrative",
    }


def _adapter_harness(monkeypatch, *, execution_manifest):
    import functions_image_edit
    import functions_image_generation
    import functions_image_references
    import functions_orchestration_images as images

    captured = {"generated": 0}
    monkeypatch.setattr(images, "require_result_service", lambda context: context.result_service)
    monkeypatch.setattr(images, "resolve_step_inputs", lambda step, context: {})
    monkeypatch.setattr(images, "image_generation_readiness", lambda settings: {"status": "available"})
    monkeypatch.setattr(images, "build_step_result", lambda **kwargs: kwargs)
    monkeypatch.setattr(functions_image_edit, "resolve_image_edit_capability", lambda settings: _capability())

    def resolve_refs(settings, user_id, conversation_id, refs, capability):
        assert refs == [{"type": "document", "document_id": "doc-image", "scope": "personal", "scope_id": None}]
        captured["resolved"] = refs
        return {
            "sources": [{"bytes": b"abc", "mime_type": "image/png", "file_name": "reference.png"}],
            "provenance": [{"type": "document", "document_id": "doc-image", "scope": "personal", "scope_id": None, "file_name": "house.jpg"}],
        }

    def generate(**kwargs):
        captured["generated"] += 1
        captured.update(kwargs)
        return {
            "message_id": "conversation-1_image_1",
            "mime_type": "image/png",
            "image_size": 3,
            "image_sha256": "a" * 64,
            "model_deployment_name": "gpt-image-1",
            "image_message": {"prompt": kwargs["prompt"]},
        }

    monkeypatch.setattr(functions_image_references, "resolve_image_references", resolve_refs)
    monkeypatch.setattr(functions_image_generation, "generate_chat_image_message", generate)

    class Access:
        def authorize_producer(self, producer, for_write=False):
            return None

    class Service:
        access = Access()

        def persist_task_result(self, **kwargs):
            captured["persisted"] = kwargs
            return {"task": "ok"}

    context = SimpleNamespace(
        result_service=Service(),
        user_id="user-1",
        conversation_id="conversation-1",
        run_id="run-1",
        plan_contract_version=2,
        user_email="user@example.com",
        seeds={
            "image_reference_documents": [
                {"document_id": "doc-image", "scope": "personal", "scope_id": None, "file_name": "house.jpg"},
            ],
        },
        execution_manifest=execution_manifest,
        result_producer=lambda step: SimpleNamespace(user_id="user-1", run_id="run-1", step_id=step["step_id"], attempt_index=1),
        result_guard_token_for_step=lambda step_id: "guard",
        result_input_fingerprint_for_step=lambda step_id: "fingerprint",
    )
    step = _plan({"reference_document_ids": ["doc-image"]})["steps"][0]
    return images, context, step, captured


def test_adapter_passes_sources_metadata_and_maps_reference_failures(monkeypatch):
    import functions_image_references

    images, context, step, captured = _adapter_harness(
        monkeypatch, execution_manifest=[_execution_source()],
    )

    result = images.adapter_generate_image(step, context, settings={}, user_id="user-1")

    assert result["status"] == "completed"
    assert result["summary"] == "Generated an AI-generated image."
    assert captured["reference_sources"][0]["file_name"] == "reference.png"
    assert captured["extra_metadata"]["image_references"][0]["file_name"] == "house.jpg"
    assert captured["input_fidelity"] == "high"
    assert captured["prompt"].startswith("Use the attached reference image as the visual basis.")
    # Lineage is the executor's authorized snapshot of the document, without storage locators.
    assert captured["persisted"]["sources"] == [{
        "document_id": "doc-image", "scope": "personal", "scope_id": "user-1",
        "source_version": 3, "source_revision": None,
    }]
    assert captured["persisted"]["origin"] == "grounded"

    def fail_refs(*_args, **_kwargs):
        raise functions_image_references.ImageReferenceError("Reference unavailable.", "image_reference_not_found", 404)

    monkeypatch.setattr(functions_image_references, "resolve_image_references", fail_refs)
    failed = images.adapter_generate_image(step, context, settings={}, user_id="user-1")
    assert failed["status"] == "failed"
    assert failed["failure"]["message"] == "Reference unavailable."
    assert failed["failure"]["reference_error_code"] == "image_reference_not_found"


@pytest.mark.parametrize("execution_manifest", [
    [],
    [_execution_source("doc-other")],
    [_execution_source(status="unavailable")],
], ids=["no-manifest", "other-document", "unauthorized"])
def test_adapter_fails_closed_without_an_authorized_reference_source(monkeypatch, execution_manifest):
    images, context, step, captured = _adapter_harness(monkeypatch, execution_manifest=execution_manifest)

    failed = images.adapter_generate_image(step, context, settings={}, user_id="user-1")

    assert failed["status"] == "failed"
    assert failed["failure"]["code"] == "result_unavailable"
    assert captured["generated"] == 0 and "resolved" not in captured and "persisted" not in captured


@pytest.mark.parametrize("reason, code", [
    ("external_identity_session_unavailable", "external_session_required"),
    ("external_identity_access_denied", "result_unavailable"),
])
def test_adapter_explains_a_refused_retained_input(monkeypatch, reason, code):
    """A background continuation has no signed-in session, so the image step asks for a resend."""
    from functions_orchestration_results import ResultUnavailableError

    images, context, step, captured = _adapter_harness(monkeypatch, execution_manifest=[_execution_source()])

    class RefusedInput:
        reference = "retained-web-result"

        def recheck(self):
            raise ResultUnavailableError(reason)

    monkeypatch.setattr(images, "resolve_step_inputs", lambda step, context: {"facts": RefusedInput()})
    failed = images.adapter_generate_image(step, context, settings={}, user_id="user-1")

    assert failed["status"] == "failed"
    assert failed["failure"]["code"] == code
    assert reason not in failed["failure"]["message"]
    assert captured["generated"] == 0 and "resolved" not in captured and "persisted" not in captured


def test_reference_ids_change_step_fingerprint():
    from functions_orchestration_result_contracts import canonical_digest

    first = canonical_digest(_plan({"reference_document_ids": ["doc-a"]})["steps"][0]["arguments"])
    second = canonical_digest(_plan({"reference_document_ids": ["doc-b"]})["steps"][0]["arguments"])
    assert first != second

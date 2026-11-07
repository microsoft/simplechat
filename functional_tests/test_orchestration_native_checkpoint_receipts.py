# test_orchestration_native_checkpoint_receipts.py
"""Native receipts use the exact durable owning checkpoint, not a recomputed hash.

Version: 0.261.127
Implemented in: 0.261.127

Real bootstrap, native builders, execution leases, checkpoints and result readers
run through the shared headless harness. Only external storage/model I/O is
doubled. Observations read committed proof while its actual execution lease is
held; no guard, producer, fingerprint or adapter is substituted.
"""

from copy import deepcopy
import importlib
from uuid import uuid4

import pytest

from test_orchestration_harness_execution import harness, initialized_application
from test_support.orchestration_harness_execution import decoded_frames, native_step


def observing_checkpoints(environment, observations):
    class ObservedCheckpoints(environment.recovery.ExecutionCheckpoints):
        def commit(self, step, result, input_fingerprint, *, reused=None):
            super().commit(step, result, input_fingerprint, reused=reused)
            if step["capability_id"] != "tabular_analyze":
                return
            saved_input = self.store.load(step["step_id"], input_only=True)
            checkpoint = self.store.load(
                step["step_id"], waiting=result["status"] == "waiting",
            )
            producer = self.context.result_producer(step)
            service = self.context.result_service
            receipt = service.store.load_orchestration_result_receipt(
                producer, saved_input["input_fingerprint"],
            )
            recovered = service.recover_task_result(
                producer=producer, input_fingerprint=saved_input["input_fingerprint"],
            )
            metadata, rows = [], []
            if recovered is not None:
                for reference in recovered.outputs:
                    reader = service.open_result(reference)
                    metadata.append(reader.metadata())
                    if reference.output_name == "records":
                        rows = list(reader.iter_records())
            observations.append({
                "argument": input_fingerprint,
                "input": deepcopy(saved_input),
                "checkpoint": deepcopy(checkpoint),
                "receipt": deepcopy(receipt),
                "recovered": recovered.to_dict() if recovered is not None else None,
                "metadata": metadata,
                "rows": rows,
                "producer": producer.to_dict(),
                "claim_id": self.lease.claim_id,
                "token": self.lease.token,
            })

    return ObservedCheckpoints


def continue_observed(environment, checkpoint_factory):
    current = environment.read()
    authorize = lambda: environment.bootstrap.read_owned_conversation("owner", "conversation-1")
    claimed = environment.recovery.claim_waiting_continuation(
        current["id"], "owner", {
            "conversation_id": "conversation-1",
            "submission_id": str(uuid4()),
            "expected_version": current["recovery_version"],
        },
        authorize=authorize, message_container=environment.messages,
    )
    if claimed["acquired"] is not True:
        raise AssertionError("The real same-attempt continuation claim was not acquired.")
    lease = environment.recovery.ExecutionLease(
        claimed["record"], authorize, message_container=environment.messages,
    )
    return environment.execution.prepare_harness_execution(
        claimed["record"], settings=environment.settings, lease=lease,
        checkpoint_factory=checkpoint_factory,
    )


@pytest.mark.parametrize("operation", ["query", "transform"])
@pytest.mark.parametrize("deferred", [False, True], ids=["inline", "same-attempt-resume"])
def test_native_receipt_equals_saved_input_and_completion_checkpoints(
    harness, monkeypatch, operation, deferred,
):
    harness.settings.update({
        "enable_tabular_generation_plan": False,
        "enable_tabular_completion_driven_checkpointing": False,
        "tabular_generated_output_inline_max_rows": 1 if deferred else 1000,
    })
    step = native_step()
    if operation == "query":
        step["arguments"].update(
            native_operation="query", question="Select amounts at least 36.",
            columns=["Item_ID", "amount"], query_expression="amount >= 36",
        )
        step["arguments"].pop("transformation_spec")
    observations = []
    checkpoint_factory = observing_checkpoints(harness, observations)
    with harness.native_io() as native:
        harness.create(
            [step], seeds={"document_ids": ["document-1"], "doc_scope": "personal"},
            original_seeds={"document_ids": ["document-1"], "doc_scope": "personal"},
        )
        first = harness.prepare(checkpoint_factory=checkpoint_factory)
        first_frames = first.execute()
        first_done = decoded_frames(first_frames)[-1]
        first_record = harness.read()
        assert first_done["status"] == ("waiting" if deferred else "completed"), first_done
        assert len(observations) == 1
        original_input = observations[0]["input"]
        original_digest = original_input["input_fingerprint"]
        original_token = first.lease.token
        original_deadline = first_record["execution_deadline_at"]
        native_jobs = native.jobs.created
        opens = []
        if deferred:
            original_wait = deepcopy(first_record["pending_results"]["compute"])
            assert original_wait["handle"]["request_fingerprint"] != original_digest

            def forbidden(*args, **kwargs):
                raise AssertionError("Native continuation rebuilt or resubmitted the producer.")

            # Resolve the real bridge only after the shared offline application bootstrap.
            bridge_module = importlib.import_module("functions_orchestration_native_results")
            open_result = native.results.open_native_tabular_result

            def open_once(**kwargs):
                opens.append(deepcopy(kwargs["handle"]))
                return open_result(**kwargs)

            monkeypatch.setattr(bridge_module, "build_native_orchestration_request", forbidden)
            monkeypatch.setattr(bridge_module.NativeOrchestrationBridge, "execute", forbidden)
            monkeypatch.setattr(native.native, "build_native_tabular_compute_callback", forbidden)
            monkeypatch.setattr(native.results, "open_native_tabular_result", open_once)
            pending = continue_observed(harness, checkpoint_factory)
            pending_frames = pending.execute()
            pending_done = decoded_frames(pending_frames)[-1]
            assert pending_done["status"] == "waiting", pending_done
            assert len(opens) == 1
            native.engine.process_tabular_generated_output_run(original_wait["handle"]["job_id"], "owner")
            completed = continue_observed(harness, checkpoint_factory)
            completed_frames = completed.execute()
            completed_done = decoded_frames(completed_frames)[-1]
            assert completed_done["status"] == "completed", completed_done
            assert opens == [original_wait["handle"], original_wait["handle"]]
            assert len(observations) == 3
            assert len({item["claim_id"] for item in observations}) == 3

        saved = harness.read()
        assert saved["status"] == "completed"
        assert saved["attempt_index"] == first_record["attempt_index"] == 1
        assert saved["execution_deadline_at"] == original_deadline
        assert native.jobs.created == native_jobs
        assert harness.model_calls == [] and harness.blobs.file_uploads == 0
        assert all(client.closed for client in harness.clients)
        assert saved["pending_results"] == {} and saved["execution_lease"] is None
        for observed in observations:
            assert observed["input"] == original_input
            assert observed["argument"] == observed["checkpoint"]["input_fingerprint"] == original_digest
            assert observed["producer"] == original_input["result_producer"]
            assert observed["token"] == original_token
            if observed["checkpoint"]["result"]["status"] == "waiting":
                assert observed["receipt"] is None and observed["recovered"] is None

        terminal = observations[-1]
        assert terminal["receipt"] is not None
        manifest_sha256, manifest = terminal["receipt"]
        assert manifest["input_fingerprint"] == original_digest
        assert manifest["producer"] == original_input["result_producer"]
        assert terminal["recovered"] == terminal["checkpoint"]["result"]["task_result"]
        assert terminal["recovered"] == saved["task_results"]["compute"]
        assert len(terminal["metadata"]) == 2
        assert all(item["input_fingerprint"] == original_digest for item in terminal["metadata"])
        assert all(
            reference["manifest_sha256"] == manifest_sha256
            for reference in terminal["recovered"]["outputs"]
        )
        assert len(terminal["rows"]) == (2 if operation == "query" else 37)
        assert terminal["rows"][-1] == (
            {"Item_ID": "item-000037", "amount": 37}
            if operation == "query" else {"Item_ID": "item-000037", "doubled": 74}
        )

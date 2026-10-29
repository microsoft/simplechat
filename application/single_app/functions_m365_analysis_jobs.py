# functions_m365_analysis_jobs.py
"""Durable, provider-independent batches over captured conversation evidence.

Start a separate analysis run from completed provider references before dispatch.
Published captures remain immutable; their exact evidence is copied through
authorized memory APIs, not re-fetched from Microsoft 365 or summarized away.
The application supplies dispatch/scheduling, policy revalidation, and a bounded
read-only analysis processor. No token, Flask request, thread, or remote-source
client is captured here. A processor can be retried after a crash before its
result is durable; it must not perform external mutations. Persisted checkpoints
and stable batch IDs prevent already committed results from being processed twice.
"""

from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any

from functions_conversation_memory import (
    ConversationMemoryStore,
    MAX_PAGE_SIZE,
    MemoryAuthorizationError,
    MemoryConflictError,
    MemoryContext,
    MemoryIncompleteCaptureError,
    MemoryIntegrityError,
    MemoryLimitError,
    MemoryStateError,
    WorkerClaim,
)


ANALYSIS_JOB_VERSION = 1
ANALYSIS_INPUT_VERSION = 1
MAX_ANALYSIS_INPUT_REFERENCES = 32
_MEMORY_REFERENCE = re.compile(r"([0-9a-f]{32})(?::(s[0-9a-f]{16}))?\Z")


@dataclass(frozen=True)
class AnalysisBatch:
    batch_id: str
    run_id: str
    evidence: dict
    previous_state: Mapping[str, Any]
    heartbeat: Callable[[], None]
    trust: str = "untrusted_source_data"


@dataclass(frozen=True)
class AnalysisBatchResult:
    output: Any
    note: str = ""
    state: Mapping[str, Any] | None = None


class ConversationAnalysisJobRunner:
    """Process at most one bounded evidence window per dispatcher invocation."""

    def __init__(
        self,
        store: ConversationMemoryStore,
        *,
        processor: Callable[[AnalysisBatch], AnalysisBatchResult],
        authorize_resume: Callable[[MemoryContext, dict], bool],
        processor_version: str,
        batch_chunks: int = 8,
        lease_seconds: int = 300,
    ):
        if not callable(processor) or not callable(authorize_resume):
            raise ValueError("A processor and server-side resume authorization callback are required.")
        if not isinstance(processor_version, str) or not processor_version or len(processor_version) > 128:
            raise ValueError("A bounded processor revision is required for durable analysis.")
        if type(batch_chunks) is not int or not 1 <= batch_chunks <= MAX_PAGE_SIZE:
            raise ValueError("Analysis batches exceed the supported evidence range size.")
        if type(lease_seconds) is not int or not 1 <= lease_seconds <= 3600:
            raise ValueError("Analysis worker lease is outside the supported range.")
        self.store = store
        self.processor = processor
        self.authorize_resume = authorize_resume
        self.processor_version = processor_version
        self.batch_chunks = batch_chunks
        self.lease_seconds = lease_seconds

    def start_analysis(
        self, ctx: MemoryContext, memory_ids: str | Iterable[str], *,
        analysis_key: str | None = None, approval_ids: Iterable[str] = (),
    ) -> dict:
        """Prepare a distinct writable run from stable, authorized captured-source snapshots.

        Startup is request-keyed and resumable. It copies evidence, not provider
        preparation checkpoints, and initializes a fresh analysis cursor. At most
        32 input references are accepted; each full-run reference may contain any
        number of paginated sources. No external source access occurs here.
        """
        if not isinstance(ctx, MemoryContext) or ctx.request_id is None:
            raise MemoryAuthorizationError("Analysis startup requires a server-bound logical request context.")
        inputs = self._snapshot_inputs(ctx, memory_ids)
        fingerprint = hashlib.sha256(json.dumps(
            {"version": ANALYSIS_INPUT_VERSION, "processor_version": self.processor_version, "inputs": inputs},
            sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")).hexdigest()
        manifest = self.store.get_or_create_manifest(
            ctx, kind="conversation_analysis",
            key=fingerprint if analysis_key is None else analysis_key, approval_ids=approval_ids,
        )
        run_id = manifest["run_id"]
        if self.authorize_resume(ctx, manifest) is not True:
            raise MemoryAuthorizationError("Starting this captured-evidence analysis is not authorized.")
        if manifest["status"] == "canceled":
            raise MemoryStateError("This analysis was canceled; use a new server analysis key to start another.")
        latest = self.store.read_checkpoint(ctx, run_id)
        if latest is not None and "analysis_job" in latest["checkpoint"]:
            self._check_input_fingerprint(latest["checkpoint"]["analysis_job"], fingerprint)
            self._cursor(manifest, latest)
            return manifest
        if manifest["status"] == "completed":
            raise MemoryStateError("The selected analysis key does not contain a prepared analysis run.")
        if manifest["status"] in {"failed", "waiting"}:
            self.store.resume(ctx, run_id)
        claim = self.store.claim(ctx, run_id, lease_seconds=self.lease_seconds)
        succeeded = False
        try:
            result = self._prepare_analysis(ctx, run_id, inputs, fingerprint, claim)
            succeeded = True
            return result
        finally:
            if not succeeded:
                self._release_failed_claim(ctx, run_id, claim)

    def _snapshot_inputs(self, ctx: MemoryContext, memory_ids: str | Iterable[str]) -> list[dict]:
        values = (memory_ids,) if isinstance(memory_ids, str) else memory_ids
        references = []
        for value in values:
            if len(references) >= MAX_ANALYSIS_INPUT_REFERENCES:
                raise MemoryLimitError("Select at most 32 captured-source references for one analysis run.")
            match = _MEMORY_REFERENCE.fullmatch(value) if isinstance(value, str) else None
            if match is None:
                raise ValueError("Analysis inputs must be memory run IDs or run ID:evidence ID references.")
            run_id, evidence_id = match.groups()
            if any(
                other_run == run_id and (other_evidence is None or evidence_id is None or other_evidence == evidence_id)
                for other_run, other_evidence in references
            ):
                raise ValueError("Analysis inputs must not duplicate or overlap a captured source.")
            references.append((run_id, evidence_id))
        if not references:
            raise ValueError("Analysis requires at least one captured-source reference.")
        inputs = []
        for run_id, evidence_id in references:
            manifest = self.store.read_manifest(ctx, run_id)
            if manifest["status"] != "completed" or manifest["pending_operation"] is not None:
                raise MemoryStateError("Complete source capture before starting independent analysis.")
            if manifest["evidence_count"] < 1:
                raise MemoryStateError("The selected memory run contains no captured source evidence.")
            selected = self.store.read_source_manifest(ctx, run_id, evidence_id) if evidence_id is not None else None
            inputs.append({
                "run_id": run_id, "evidence_id": evidence_id,
                "content_revision": manifest["content_revision"], "run_content_sha256": manifest["content_sha256"],
                "source_content_sha256": selected["content_sha256"] if selected is not None else None,
            })
        return inputs

    def _iter_sources(self, ctx: MemoryContext, run_id: str) -> Iterator[dict]:
        offset = 0
        while True:
            page = self.store.list_sources(ctx, run_id, start=offset, count=MAX_PAGE_SIZE)
            yield from page["sources"]
            if page["next_start"] is None:
                return
            offset = page["next_start"]

    def _selected_sources(self, ctx: MemoryContext, inputs: list[dict]) -> Iterator[tuple[dict, dict]]:
        for item in inputs:
            manifest = self.store.read_manifest(ctx, item["run_id"])
            if (
                manifest["status"] != "completed" or manifest["content_revision"] != item["content_revision"]
                or manifest["content_sha256"] != item["run_content_sha256"]
            ):
                raise MemoryConflictError("The selected captured-source snapshot changed during analysis startup.")
            if item["evidence_id"] is None:
                sources = self._iter_sources(ctx, item["run_id"])
            else:
                source = self.store.read_source_manifest(ctx, item["run_id"], item["evidence_id"])
                if source["content_sha256"] != item["source_content_sha256"]:
                    raise MemoryConflictError("The selected evidence hash changed during analysis startup.")
                sources = iter((source,))
            for source in sources:
                yield item, source

    def _check_input_fingerprint(self, state: dict, expected: str):
        if (
            not isinstance(state, dict) or state.get("input_fingerprint") != expected
            or state.get("processor_version") != self.processor_version
        ):
            raise MemoryStateError("This analysis key is bound to different inputs or a different processor revision.")

    def _prepare_analysis(
        self, ctx: MemoryContext, run_id: str, inputs: list[dict], fingerprint: str, claim: WorkerClaim,
    ) -> dict:
        manifest = self.store.read_manifest(ctx, run_id)
        if manifest["pending_operation"] is not None:
            try:
                self.store.recover_pending(ctx, run_id, claim=claim)
            except MemoryIncompleteCaptureError:
                # These are local immutable copies, not ambiguous external side effects.
                self.store.recover_pending(ctx, run_id, discard=True, claim=claim)
        latest = self.store.read_checkpoint(ctx, run_id)
        manifest = self.store.read_manifest(ctx, run_id)
        if latest is not None:
            prepared = latest["checkpoint"].get("analysis_job")
            if prepared is not None:
                self._check_input_fingerprint(prepared, fingerprint)
                self._cursor(manifest, latest)
                return self.store.release_claim(ctx, claim, status="queued")
            setup = latest["checkpoint"].get("analysis_setup")
            self._check_input_fingerprint(setup, fingerprint)
        elif manifest["evidence_count"]:
            raise MemoryIntegrityError("Analysis input copies have no durable initialization contract.")
        else:
            self._save_setup(ctx, run_id, inputs, fingerprint, 0, claim)
        copied_count = manifest["evidence_count"]
        existing_sources = self._iter_sources(ctx, run_id)
        selected_count = 0
        for item, source in self._selected_sources(ctx, inputs):
            if selected_count < copied_count:
                existing = next(existing_sources, None)
                origin = {} if existing is None else existing.get("copied_from", {})
                expected = {
                    "run_id": item["run_id"], "evidence_id": source["evidence_id"],
                    "content_revision": item["content_revision"],
                    "run_content_sha256": item["run_content_sha256"],
                    "source_content_sha256": source["content_sha256"],
                }
                if (
                    existing is None or any(origin.get(key) != value for key, value in expected.items())
                    or existing["content_sha256"] != source["content_sha256"]
                ):
                    raise MemoryIntegrityError("Previously copied analysis evidence does not match the input contract.")
            else:
                if self.authorize_resume(ctx, self.store.read_manifest(ctx, run_id)) is not True:
                    raise MemoryAuthorizationError("The analysis-start authorization changed during preparation.")
                self.store.copy_evidence_to_run(
                    ctx, item["run_id"], source["evidence_id"], run_id, claim=claim,
                    expected_content_revision=item["content_revision"],
                    expected_source_sha256=source["content_sha256"],
                    expected_run_sha256=item["run_content_sha256"],
                )
                self._save_setup(ctx, run_id, inputs, fingerprint, selected_count + 1, claim)
            selected_count += 1
            claim = self.store.renew_claim(ctx, claim, lease_seconds=self.lease_seconds)
        if selected_count < copied_count:
            raise MemoryIntegrityError("The analysis run contains evidence outside its captured-input contract.")
        manifest = self.store.read_manifest(ctx, run_id)
        if not manifest["captured_chunk_count"]:
            raise MemoryStateError("Analysis requires captured evidence, not an empty source inventory.")
        if self.authorize_resume(ctx, manifest) is not True:
            raise MemoryAuthorizationError("The analysis-start authorization changed before initialization.")
        self.store.append_checkpoint(
            ctx, run_id, claim=claim, completed_units=0, total_units=manifest["captured_chunk_count"],
            checkpoint={
                "analysis_job": {
                    "version": ANALYSIS_JOB_VERSION, "processor_version": self.processor_version,
                    "input_fingerprint": fingerprint, "source_slots": manifest["committed_source_slots"],
                    "source_index": 0, "chunk_start": 0, "processed_chunks": 0,
                },
                "state": {},
            },
        )
        return self.store.release_claim(ctx, claim, status="queued")

    def _save_setup(
        self, ctx: MemoryContext, run_id: str, inputs: list[dict], fingerprint: str,
        copied_sources: int, claim: WorkerClaim,
    ):
        self.store.append_checkpoint(
            ctx, run_id, claim=claim, checkpoint={
                "analysis_setup": {
                    "version": ANALYSIS_INPUT_VERSION, "processor_version": self.processor_version,
                    "input_fingerprint": fingerprint, "inputs": inputs, "copied_sources": copied_sources,
                },
            },
        )

    def _release_failed_claim(self, ctx: MemoryContext, run_id: str, claim: WorkerClaim):
        try:
            self.store.release_claim(ctx, claim, status="failed")
        except (MemoryConflictError, MemoryStateError):
            self.store.log_event(
                "[SIMPLE_CHAT] Conversation analysis worker lost its claim after a batch failure",
                {"conversation_id": ctx.conversation_id, "run_id": run_id},
            )

    def run_next_batch(self, ctx: MemoryContext, run_id: str) -> dict:
        manifest = self.store.read_manifest(ctx, run_id)
        if self.authorize_resume(ctx, manifest) is not True:
            raise MemoryAuthorizationError("The analysis continuation is not currently authorized.")
        if manifest["status"] == "completed":
            latest = self.store.read_checkpoint(ctx, run_id)
            if latest is None or "analysis_job" not in latest["checkpoint"]:
                raise MemoryStateError("Completed capture is not completed analysis; call start_analysis first.")
            self._cursor(manifest, latest)
            return {"status": "completed", "manifest": manifest, "checkpoint": latest}
        if manifest["status"] in {"failed", "waiting"}:
            self.store.resume(ctx, run_id)
        claim = self.store.claim(ctx, run_id, lease_seconds=self.lease_seconds)
        succeeded = False
        try:
            result = self._run_claimed_batch(ctx, run_id, manifest, claim)
            succeeded = True
            return result
        finally:
            if not succeeded:
                self._release_failed_claim(ctx, run_id, claim)

    def _run_claimed_batch(
        self, ctx: MemoryContext, run_id: str, manifest: dict, claim: WorkerClaim,
    ) -> dict:
        if manifest["pending_operation"] is not None:
            self.store.recover_pending(ctx, run_id, claim=claim)
        manifest = self.store.read_manifest(ctx, run_id)
        latest = self.store.read_checkpoint(ctx, run_id)
        cursor, previous_state = self._cursor(manifest, latest)
        source_index = cursor["source_index"]
        while source_index < cursor["source_slots"]:
            page = self.store.list_sources(ctx, run_id, start=source_index, count=1)
            if page["sources"]:
                source = page["sources"][0]
                break
            source_index += 1
        else:
            if cursor["processed_chunks"] != manifest["captured_chunk_count"]:
                raise MemoryIntegrityError("Analysis cannot complete without processing every selected captured chunk.")
            completed = self.store.complete_run(ctx, run_id, claim=claim)
            return {"status": "completed", "manifest": completed, "checkpoint": latest}

        evidence = self.store.read_evidence_range(
            ctx, run_id, source["evidence_id"], start=cursor["chunk_start"], count=self.batch_chunks,
        )
        if not evidence["chunks"]:
            raise MemoryIntegrityError("The persisted analysis cursor points outside captured evidence.")
        batch_id = hashlib.sha256(json.dumps(
            {
                "version": ANALYSIS_JOB_VERSION, "processor": self.processor_version,
                "run_id": run_id, "source": source["evidence_id"], "hash": source["content_sha256"],
                "start": cursor["chunk_start"], "count": len(evidence["chunks"]),
            }, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")).hexdigest()

        def heartbeat():
            nonlocal claim
            claim = self.store.renew_claim(ctx, claim, lease_seconds=self.lease_seconds)

        result = self.processor(AnalysisBatch(batch_id, run_id, evidence, previous_state, heartbeat))
        if not isinstance(result, AnalysisBatchResult):
            raise ValueError("The analysis processor must return a typed batch result.")
        heartbeat()
        if self.authorize_resume(ctx, self.store.read_manifest(ctx, run_id)) is not True:
            raise MemoryAuthorizationError("The analysis continuation authorization changed before commit.")
        next_chunk = evidence["next_start"]
        next_source = source_index if next_chunk is not None else source_index + 1
        processed = cursor["processed_chunks"] + len(evidence["chunks"])
        checkpoint = self.store.append_checkpoint(
            ctx, run_id, claim=claim, output=result.output, note=result.note,
            completed_units=processed, total_units=manifest["captured_chunk_count"],
            checkpoint={
                "analysis_job": {
                    "version": ANALYSIS_JOB_VERSION, "processor_version": self.processor_version,
                    "input_fingerprint": cursor.get("input_fingerprint"),
                    "source_slots": cursor["source_slots"], "source_index": next_source,
                    "chunk_start": next_chunk if next_chunk is not None else 0,
                    "processed_chunks": processed, "batch_id": batch_id,
                },
                "state": dict(result.state) if result.state is not None else {},
            },
        )
        status = "completed" if next_source >= cursor["source_slots"] else "queued"
        updated = self.store.release_claim(ctx, claim, status=status)
        return {"status": status, "manifest": updated, "checkpoint": checkpoint}

    def _cursor(self, manifest: dict, latest: dict | None) -> tuple[dict, Mapping[str, Any]]:
        if latest is None:
            if not manifest["captured_chunk_count"]:
                raise MemoryStateError("Start analysis from captured evidence before dispatching a batch.")
            return {
                "source_slots": manifest["committed_source_slots"], "source_index": 0,
                "chunk_start": 0, "processed_chunks": 0,
            }, {}
        state = latest["checkpoint"]
        cursor = state.get("analysis_job")
        if not isinstance(cursor, dict) or (
            cursor.get("version") != ANALYSIS_JOB_VERSION
            or cursor.get("processor_version") != self.processor_version
            or cursor.get("source_slots") != manifest["committed_source_slots"]
        ):
            raise MemoryStateError("The processor or captured source set changed; start a new analysis run.")
        for field in ("source_slots", "source_index", "chunk_start", "processed_chunks"):
            if type(cursor.get(field)) is not int or cursor[field] < 0:
                raise MemoryIntegrityError("The analysis continuation cursor is invalid.")
        if (
            cursor["source_index"] > cursor["source_slots"]
            or cursor["processed_chunks"] != latest["completed_units"]
            or cursor["processed_chunks"] > manifest["captured_chunk_count"]
            or not isinstance(state.get("state"), dict)
        ):
            raise MemoryIntegrityError("The analysis continuation does not match captured evidence.")
        if manifest["status"] == "completed" and (
            cursor["processed_chunks"] != manifest["captured_chunk_count"]
            or cursor["source_index"] != cursor["source_slots"] or cursor["chunk_start"] != 0
        ):
            raise MemoryIntegrityError("Capture completion cannot stand in for unprocessed analysis evidence.")
        return cursor, state["state"]

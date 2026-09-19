# functions_workflow_journal.py
"""Paged schema-2 journal records in the existing fenced workflow partition."""

import base64
import json
from copy import deepcopy

from azure.cosmos import exceptions as cosmos_exceptions

from functions_workflow_identity import canonical_digest, workflow_execution_id


JOURNAL_TYPE = "workflow_runtime_journal"
JOURNAL_KINDS = frozenset({"execution", "attempt", "unit", "decision", "request", "admission", "loop", "iteration"})
PUBLIC_EXECUTION_FIELDS = (
    "execution_id", "node_id", "node_kind", "task_id", "iteration_path", "region_id",
    "sequence", "state", "attempt", "reason_code", "decision", "workflow_result",
    "workflow_validation", "consumed_inputs", "iteration_inputs", "started_at", "completed_at",
)
PUBLIC_DECISION_FIELDS = (
    "sequence", "execution_id", "node_id", "iteration_path", "attempt", "gate_id",
    "gate_kind", "choice", "decision", "actor_user_id", "decided_at", "reason_code", "input_digest",
    "decision_kind", "iteration", "batch_number", "condition_result", "repeat", "event_id",
)


def journal_record_id(kind, key):
    return f"workflow-journal:v2:{kind}:{canonical_digest(key)}"


def _public_journal_value(value):
    if isinstance(value, dict):
        private = {"repeat_state"} if {"producer", "result_ref", "output_name", "output_ref"} <= value.keys() else set()
        if {"loop_id", "loop_execution_id", "iteration", "state_ref"} <= value.keys():
            private.add("state_ref")
        return {
            name: _public_journal_value(item) for name, item in value.items()
            if name not in private
        }
    if isinstance(value, list):
        return [_public_journal_value(item) for item in value]
    return deepcopy(value)


class WorkflowJournalMixin:
    """Atomic decision/cursor/admission updates; control does not grow per execution."""

    def journal_read(self, kind, key):
        self._read_control()
        if kind not in JOURNAL_KINDS:
            raise ValueError("Unsupported workflow journal record kind.")
        try:
            row = self.container.read_item(
                item=journal_record_id(kind, key), partition_key=self.identity["run_id"],
            )
        except cosmos_exceptions.CosmosResourceNotFoundError:
            return None
        if (
            any(row.get(name) != value for name, value in self.identity.items())
            or row.get("type") != JOURNAL_TYPE or row.get("record_kind") != kind or row.get("key") != key
        ):
            self._journal_conflict("identity_mismatch")
        return row

    @staticmethod
    def _journal_conflict(code):
        # Runtime store imports this mixin; resolve its public error only at use.
        from functions_workflow_runtime_store import WorkflowRuntimeConflict

        raise WorkflowRuntimeConflict(code)

    def journal_commit(self, token, kind, key, payload, *, updates=None, admission=False, immutable=False):
        if kind not in JOURNAL_KINDS:
            raise ValueError("Unsupported workflow journal record kind.")
        identifier = journal_record_id(kind, key)
        for _ in range(8):
            control = self._read_control()
            self._assert_current_owned(control, token)
            if control.get("schema_version") != 2:
                self._journal_conflict("schema_mismatch")
            previous = self.journal_read(kind, key)
            if previous is not None and immutable:
                if previous.get("payload") != payload:
                    self._journal_conflict("immutable_conflict")
                return previous
            replacement = self._base_replacement(control)
            if admission and previous is None:
                admitted = int(control.get("admitted_count") or 0)
                if admitted >= control["max_executions"]:
                    from functions_workflow_execution import WorkflowSuspended

                    self.pause_execution_limit(token, "execution_budget_exceeded")
                    raise WorkflowSuspended("paused")
                replacement["admitted_count"] = admitted + 1
            if self._now().isoformat() >= control["deadline_at"]:
                from functions_workflow_execution import WorkflowSuspended

                self.pause_execution_limit(token, "deadline_exceeded")
                raise WorkflowSuspended("paused")
            sequence = previous["sequence"] if previous else int(control.get("journal_sequence") or 0) + 1
            if previous is None:
                replacement["journal_sequence"] = sequence
                counts = dict(control.get("journal_counts") or {})
                counts[kind] = int(counts.get(kind) or 0) + 1
                replacement["journal_counts"] = counts
            if kind == "unit":
                was_completed = bool(previous and previous["payload"].get("state") == "completed")
                is_completed = payload.get("state") == "completed"
                replacement["completed_unit_count"] = int(control.get("completed_unit_count") or 0) + int(is_completed) - int(was_completed)
            if updates:
                if set(updates) - {"cursor", "progress", "phase", "state", "gate", "lease", "loop_progress"}:
                    self._journal_conflict("invalid_payload")
                replacement.update(deepcopy(updates))
            replacement["version"] = control["version"] + 1
            body = self._runtime_record({
                "id": identifier, "run_id": self.identity["run_id"], "type": JOURNAL_TYPE,
                "item_type": JOURNAL_TYPE, "record_kind": kind, "key": key, "sequence": sequence,
                "execution_id": payload.get("execution_id"), "payload": deepcopy(payload),
            })
            operation = (
                ("replace", (identifier, body), {"if_match_etag": previous["_etag"]})
                if previous else ("create", (body,))
            )
            try:
                self.container.execute_item_batch(batch_operations=[
                    ("replace", (control["id"], replacement), {"if_match_etag": control["_etag"]}),
                    operation,
                ], partition_key=self.identity["run_id"])
                return self.journal_read(kind, key)
            except (cosmos_exceptions.CosmosBatchOperationError, cosmos_exceptions.CosmosHttpResponseError) as exc:
                if getattr(exc, "status_code", None) in {409, 412}:
                    continue
                # A lost acknowledgement is reconciled against the exact immutable key/payload.
                saved = self.journal_read(kind, key)
                if saved and saved.get("payload") == payload:
                    self.assert_owned(token)
                    return saved
                raise
        self._journal_conflict("etag_conflict")

    def journal_commit_many(self, token, entries, *, updates=None, counters=None):
        """Commit a bounded transition behind one immutable acknowledgement marker."""
        from functions_workflow_execution import WorkflowSuspended
        from functions_workflow_runtime_store import _bounded_json_copy, _validate_gate

        if (
            not isinstance(entries, list) or not 1 <= len(entries) <= 12
            or not entries[0].get("immutable")
            or any(entry.get("kind") not in JOURNAL_KINDS for entry in entries)
            or len({journal_record_id(entry["kind"], entry["key"]) for entry in entries}) != len(entries)
        ):
            self._journal_conflict("invalid_payload")
        updates = deepcopy(updates or {})
        if set(updates) - {"cursor", "progress", "phase", "state", "gate", "lease", "loop_progress", "repeat_progress"}:
            self._journal_conflict("invalid_payload")
        if updates.get("gate") is not None:
            updates["gate"] = _validate_gate(updates["gate"], updates.get("state", "paused"))
        counters = counters or {}
        if set(counters) - {"exhaustion_count", "continuation_count"} or any(
            type(value) is not int or value < 0 for value in counters.values()
        ):
            self._journal_conflict("invalid_payload")
        marker = entries[0]
        for _ in range(8):
            control = self._read_control()
            saved = self.journal_read(marker["kind"], marker["key"])
            if saved is not None:
                if saved["payload"] != marker["payload"]:
                    self._journal_conflict("immutable_conflict")
                return saved
            self._assert_current_owned(control, token)
            if control.get("schema_version") != 2:
                self._journal_conflict("schema_mismatch")
            if self._now().isoformat() >= control["deadline_at"]:
                self.pause_execution_limit(token, "deadline_exceeded")
                raise WorkflowSuspended("paused")
            replacement = self._base_replacement(control)
            sequence = int(control.get("journal_sequence") or 0)
            counts = dict(control.get("journal_counts") or {})
            admitted = int(control.get("admitted_count") or 0)
            operations = []
            for entry in entries:
                kind, key, payload = entry["kind"], entry["key"], entry["payload"]
                previous = self.journal_read(kind, key)
                if "expected" in entry and (previous["payload"] if previous else None) != entry["expected"]:
                    self._journal_conflict("transition_changed")
                if previous is not None and entry.get("immutable"):
                    self._journal_conflict("immutable_conflict")
                if previous is None:
                    sequence += 1
                    counts[kind] = int(counts.get(kind) or 0) + 1
                    admitted += int(bool(entry.get("admission")))
                body = self._runtime_record({
                    "id": journal_record_id(kind, key), "run_id": self.identity["run_id"],
                    "type": JOURNAL_TYPE, "item_type": JOURNAL_TYPE, "record_kind": kind,
                    "key": key, "sequence": previous["sequence"] if previous else sequence,
                    "execution_id": payload.get("execution_id"), "payload": deepcopy(payload),
                })
                operations.append(
                    ("replace", (body["id"], body), {"if_match_etag": previous["_etag"]})
                    if previous else ("create", (body,))
                )
            if admitted > control["max_executions"]:
                self.pause_execution_limit(token, "execution_budget_exceeded")
                raise WorkflowSuspended("paused")
            metrics = dict(control.get("repeat_counts") or {})
            for name, value in counters.items():
                metrics[name] = int(metrics.get(name) or 0) + value
            replacement.update(
                **updates, version=control["version"] + 1, journal_sequence=sequence,
                journal_counts=counts, admitted_count=admitted,
            )
            if counters:
                replacement["repeat_counts"] = metrics
            _bounded_json_copy(replacement)
            operations.insert(0, ("replace", (control["id"], replacement), {"if_match_etag": control["_etag"]}))
            if len(json.dumps(operations, ensure_ascii=True).encode("ascii")) > 1500000:
                self._journal_conflict("transition_too_large")
            if self._now().isoformat() >= control["deadline_at"]:
                self.pause_execution_limit(token, "deadline_exceeded")
                raise WorkflowSuspended("paused")
            self._assert_current_owned(control, token)
            try:
                self.container.execute_item_batch(batch_operations=operations, partition_key=self.identity["run_id"])
                return self.journal_read(marker["kind"], marker["key"])
            except (cosmos_exceptions.CosmosBatchOperationError, cosmos_exceptions.CosmosHttpResponseError) as exc:
                acknowledged = self.journal_read(marker["kind"], marker["key"])
                if acknowledged is not None:
                    if acknowledged["payload"] != marker["payload"]:
                        self._journal_conflict("immutable_conflict")
                    return acknowledged
                if getattr(exc, "status_code", None) in {409, 412}:
                    continue
                raise
        self._journal_conflict("etag_conflict")

    def journal_page(self, kind, *, cursor=None, limit=50, execution_id=None):
        control = self._read_control()
        if kind not in {"execution", "attempt", "decision"} or type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("Journal pages require a supported kind and a limit from 1 to 100.")
        scope = canonical_digest({**self.identity, "kind": kind, "execution_id": execution_id})
        after = 0
        through = int(control.get("journal_sequence") or 0)
        total = int((control.get("journal_counts") or {}).get(kind) or 0)
        if cursor:
            try:
                if not isinstance(cursor, str) or len(cursor) > 1024:
                    raise ValueError
                decoded = json.loads(base64.urlsafe_b64decode(cursor.encode("ascii")))
                if set(decoded) != {"scope", "after", "through", "total"} or decoded["scope"] != scope:
                    raise ValueError
                after, bound, count = decoded["after"], decoded["through"], decoded["total"]
                if not all(type(value) is int for value in (after, bound, count)) or not (
                    0 <= after <= bound <= through and 0 <= count <= total
                ):
                    raise ValueError
                through, total = bound, count
            except (ValueError, TypeError, UnicodeError, json.JSONDecodeError) as exc:
                raise ValueError("Invalid workflow journal cursor.") from exc
        parameters = [
            {"name": "@run_id", "value": self.identity["run_id"]},
            {"name": "@workflow_id", "value": self.identity["workflow_id"]},
            {"name": "@kind", "value": kind}, {"name": "@after", "value": after},
            {"name": "@through", "value": through},
        ]
        where = (
            "c.run_id = @run_id AND c.workflow_id = @workflow_id "
            "AND c.item_type = 'workflow_runtime_journal' AND c.record_kind = @kind "
            "AND c.sequence > @after AND c.sequence <= @through"
        )
        if execution_id is not None:
            where += " AND c.execution_id = @execution_id"
            parameters.append({"name": "@execution_id", "value": execution_id})
        rows = list(self.container.query_items(
            query=f"SELECT TOP {limit + 1} * FROM c WHERE {where} ORDER BY c.sequence ASC",
            parameters=parameters, partition_key=self.identity["run_id"],
        ))
        for row in rows:
            if any(row.get(name) != value for name, value in self.identity.items()) or row.get("record_kind") != kind:
                self._journal_conflict("identity_mismatch")
        fields = PUBLIC_DECISION_FIELDS if kind == "decision" else PUBLIC_EXECUTION_FIELDS
        entries = []
        for row in rows[:limit]:
            entry = {name: _public_journal_value(value) for name, value in {**row["payload"], "sequence": row["sequence"]}.items() if name in fields}
            decision = entry.get("decision")
            if isinstance(decision, dict):
                decision = {name: value for name, value in decision.items() if name in {"choice", "target"}}
                target = decision.get("target")
                if isinstance(target, dict):
                    decision["target"] = {name: value for name, value in target.items() if name in {"node_id", "exit_region_id"}}
                entry["decision"] = decision
                if kind == "decision":
                    entry["choice"] = decision.get("choice") or ("route" if target else "continue")
                    if decision.get("choice") in {"then", "else"}:
                        entry["selected_branch"] = decision["choice"]
                    if isinstance(target, dict):
                        entry["target_node_id"] = target.get("node_id")
                        entry["exit_region_id"] = target.get("exit_region_id")
            entries.append(entry)
        next_cursor = None
        if len(rows) > limit:
            next_cursor = base64.urlsafe_b64encode(json.dumps(
                {"scope": scope, "after": rows[limit - 1]["sequence"], "through": through, "total": total}, separators=(",", ":"),
            ).encode("ascii")).decode("ascii")
        return {"items": entries, "next_cursor": next_cursor,
                "total_count": total}

    def journal_decide(self, *, expected_version, gate_id, choice, actor_user_id, request_id):
        from functions_workflow_runtime_store import NEXT_STATE_BY_DECISION, _require_id

        if type(expected_version) is not int:
            self._journal_conflict("stale_version")
        for name, value in (("gate_id", gate_id), ("choice", choice),
                            ("actor_user_id", actor_user_id), ("request_id", request_id)):
            _require_id(value, name)
        request_key = ["decision", request_id]
        wanted = {"gate_id": gate_id, "choice": choice, "actor_user_id": actor_user_id}
        for _ in range(8):
            control = self._read_control()
            prior = self.journal_read("request", request_key)
            if prior:
                if prior["payload"] != wanted:
                    self._journal_conflict("request_conflict")
                return control
            if control["version"] != expected_version:
                self._journal_conflict("stale_version")
            gate = control.get("gate") or {}
            if gate.get("id") != gate_id:
                self._journal_conflict("stale_gate")
            pair = (gate.get("kind"), choice)
            if pair not in NEXT_STATE_BY_DECISION or choice not in gate.get("choices", []):
                self._journal_conflict("invalid_choice")
            if choice in {"approve", "retry", "resume", "continue_repeat"} and self._now().isoformat() >= control["deadline_at"]:
                self.expire_deadline()
                self._journal_conflict("deadline_exceeded")
            repeat_row, repeat_head = None, None
            if choice == "continue_repeat":
                from functions_workflow_repeat_state import prepare_repeat_grant

                if int(control.get("admitted_count") or 0) >= control["max_executions"]:
                    self._replace(control, self._limit_pause(control, "execution_budget_exceeded"))
                    self._journal_conflict("execution_budget_exceeded")
                repeat_row, repeat_head = prepare_repeat_grant(self, control, gate, actor_user_id=actor_user_id)
            decision = {
                **wanted, "gate_kind": gate["kind"], "decided_at": self._now().isoformat(),
                **{key: deepcopy(gate[key]) for key in (
                    "unit_id", "execution_id", "node_id", "iteration_path", "attempt",
                    "input_digest", "definition_revision",
                ) if key in gate},
            }
            if repeat_head is not None:
                decision.update(
                    repeat=deepcopy(gate["repeat"]), reason_code="repeat_iteration_limit", request_id=request_id,
                    event_id=canonical_digest(["workflow_repeat_manually_continued", gate_id, request_id]),
                )
            active = self.journal_read("execution", gate.get("execution_id")) if gate.get("execution_id") else None
            if active:
                decision["consumed_inputs"] = deepcopy(active["payload"].get("consumed_inputs") or [])
                decision["reference_sources"] = deepcopy(active["payload"].get("reference_sources") or [])
                decision["iteration_inputs"] = deepcopy(active["payload"].get("iteration_inputs") or [])
            replacement = self._base_replacement(control)
            sequence = int(control.get("journal_sequence") or 0)
            replacement.update(state=NEXT_STATE_BY_DECISION[pair], gate=None, lease=None,
                               version=control["version"] + 1, journal_sequence=sequence + 2)
            counts = dict(control.get("journal_counts") or {})
            operations = [("replace", (control["id"], replacement), {"if_match_etag": control["_etag"]})]
            if repeat_head is not None:
                from functions_workflow_repeat_state import repeat_summary

                body = {key: value for key, value in repeat_row.items() if not key.startswith("_")}
                body["payload"] = repeat_head
                operations.append(("replace", (body["id"], body), {"if_match_etag": repeat_row["_etag"]}))
                replacement["repeat_progress"] = repeat_summary(repeat_head)
                metrics = dict(control.get("repeat_counts") or {})
                metrics["continuation_count"] = int(metrics.get("continuation_count") or 0) + 1
                replacement["repeat_counts"] = metrics
            elif choice in {"cancel", "reject"}:
                repeat_cancellations = self._repeat_cancellation_operations(control, replacement)
                operations.extend(repeat_cancellations)
                if repeat_cancellations and active is not None:
                    attempt = self.journal_read("attempt", [active["payload"]["execution_id"], active["payload"]["attempt"]])
                    for row in (active, attempt):
                        if row is None:
                            continue
                        body = {name: value for name, value in row.items() if not name.startswith("_")}
                        body["payload"] = {
                            **body["payload"], "state": "cancelled", "reason_code": "run_cancelled",
                            "completed_at": self._now().isoformat(),
                        }
                        operations.append(("replace", (row["id"], body), {"if_match_etag": row["_etag"]}))
            for offset, (kind, key, payload) in enumerate((
                ("decision", ["gate", gate_id], decision), ("request", request_key, wanted),
            ), start=1):
                counts[kind] = int(counts.get(kind) or 0) + 1
                body = self._runtime_record({
                    "id": journal_record_id(kind, key), "run_id": self.identity["run_id"],
                    "type": JOURNAL_TYPE, "item_type": JOURNAL_TYPE, "record_kind": kind, "key": key,
                    "sequence": sequence + offset, "execution_id": decision.get("execution_id"), "payload": payload,
                })
                operations.append(("create", (body,)))
            replacement["journal_counts"] = counts
            if choice in {"approve", "retry", "resume", "continue_repeat"} and self._now().isoformat() >= control["deadline_at"]:
                self.expire_deadline()
                self._journal_conflict("deadline_exceeded")
            try:
                self.container.execute_item_batch(batch_operations=operations, partition_key=self.identity["run_id"])
                if repeat_head is not None:
                    from functions_workflow_repeat_state import log_repeat_event

                    log_repeat_event(self, decision)
                return self._read_control()
            except (cosmos_exceptions.CosmosBatchOperationError, cosmos_exceptions.CosmosHttpResponseError) as exc:
                if getattr(exc, "status_code", None) in {409, 412}:
                    continue
                marker = self.journal_read("request", request_key)
                if marker and marker["payload"] == wanted:
                    if repeat_head is not None:
                        from functions_workflow_repeat_state import log_repeat_event

                        log_repeat_event(self, decision)
                    return self._read_control()
                raise
        self._journal_conflict("etag_conflict")

    def _repeat_cancellation_operations(self, control, replacement):
        from functions_workflow_repeat_state import repeat_summary

        cursor = control.get("cursor") or {}
        path = cursor.get("iteration_path") or []
        identifiers = set()
        if any("iteration" in frame for frame in path):
            snapshot = self.run_definition()
            identifiers.update(
                workflow_execution_id(snapshot, self.identity["run_id"], frame["loop_id"], path[:index])
                for index, frame in enumerate(path) if "iteration" in frame
            )
        if cursor.get("execution_id"):
            identifiers.add(cursor["execution_id"])
        for summary in ((control.get("gate") or {}).get("repeat"), control.get("repeat_progress")):
            if summary and summary.get("execution_id"):
                identifiers.add(summary["execution_id"])
        operations = []
        for identifier in sorted(identifiers):
            row = self.journal_read("loop", identifier)
            if row is None or row["payload"].get("kind") != "repeat_until" or row["payload"].get("state") in {"completed", "cancelled"}:
                continue
            body = {name: value for name, value in row.items() if not name.startswith("_")}
            body["payload"] = {**body["payload"], "state": "cancelled"}
            operations.append(("replace", (row["id"], body), {"if_match_etag": row["_etag"]}))
            if (control.get("repeat_progress") or {}).get("execution_id") == identifier:
                replacement["repeat_progress"] = repeat_summary(body["payload"])
            iteration = self.journal_read("iteration", [identifier, row["payload"]["next_iteration"]])
            if iteration and iteration["payload"].get("state") == "running":
                body = {name: value for name, value in iteration.items() if not name.startswith("_")}
                body["payload"] = {**body["payload"], "state": "cancelled", "completed_at": self._now().isoformat()}
                operations.append(("replace", (iteration["id"], body), {"if_match_etag": iteration["_etag"]}))
        return operations

    def journal_request(self, action, *, actor_user_id, request_id, expected_version=None):
        from functions_workflow_runtime_store import RESUMABLE_STATES, TERMINAL_STATES, _require_id

        _require_id(actor_user_id, "actor_user_id")
        _require_id(request_id, "request_id")
        key = [action, request_id]
        wanted = {"action": action, "actor_user_id": actor_user_id}
        for _ in range(8):
            control = self._read_control()
            marker = self.journal_read("request", key)
            if marker:
                if marker["payload"] != wanted:
                    self._journal_conflict("request_conflict")
                return control
            if action == "resume":
                if type(expected_version) is not int or expected_version != control["version"]:
                    self._journal_conflict("stale_version")
                if control["state"] not in RESUMABLE_STATES:
                    self._journal_conflict("invalid_state")
                if self._now().isoformat() >= control["deadline_at"]:
                    self.expire_deadline()
                    self._journal_conflict("deadline_exceeded")
                state = "queued"
            elif action == "cancel":
                if control["state"] in TERMINAL_STATES:
                    return control
                state = "cancelled"
            else:
                self._journal_conflict("invalid_payload")
            replacement = self._base_replacement(control)
            sequence = int(control.get("journal_sequence") or 0) + 1
            counts = dict(control.get("journal_counts") or {})
            counts["request"] = int(counts.get("request") or 0) + 1
            replacement.update(state=state, gate=None, lease=None, version=control["version"] + 1,
                               journal_sequence=sequence, journal_counts=counts)
            body = self._runtime_record({
                "id": journal_record_id("request", key), "run_id": self.identity["run_id"],
                "type": JOURNAL_TYPE, "item_type": JOURNAL_TYPE, "record_kind": "request",
                "key": key, "sequence": sequence, "payload": wanted,
            })
            operations = [
                ("replace", (control["id"], replacement), {"if_match_etag": control["_etag"]}),
                ("create", (body,)),
            ]
            if action == "cancel":
                operations.extend(self._repeat_cancellation_operations(control, replacement))
                node_id = (control.get("cursor") or {}).get("node_id")
                execution_id = (control.get("gate") or {}).get("execution_id") or (control.get("cursor") or {}).get("execution_id")
                if not execution_id and node_id:
                    execution_id = workflow_execution_id(
                        self.workflow, self.identity["run_id"], node_id,
                        (control.get("cursor") or {}).get("iteration_path") or [],
                    )
                active = self.journal_read("execution", execution_id) if execution_id else None
                if active and active["payload"].get("state") in {"running", "waiting_output", "waiting_approval", "waiting_recovery", "paused"}:
                    attempt = self.journal_read("attempt", [execution_id, active["payload"]["attempt"]])
                    for row in (active, attempt):
                        if row is None or row["payload"].get("state") not in {"running", "waiting_output", "waiting_approval", "waiting_recovery", "paused"}:
                            continue
                        cancelled = {key: value for key, value in row.items() if not key.startswith("_")}
                        cancelled["payload"] = {
                            **cancelled["payload"], "state": "cancelled", "reason_code": "run_cancelled",
                            "completed_at": self._now().isoformat(),
                        }
                        operations.append(("replace", (row["id"], cancelled), {"if_match_etag": row["_etag"]}))
            try:
                self.container.execute_item_batch(batch_operations=operations, partition_key=self.identity["run_id"])
                return self._read_control()
            except (cosmos_exceptions.CosmosBatchOperationError, cosmos_exceptions.CosmosHttpResponseError) as exc:
                if getattr(exc, "status_code", None) in {409, 412}:
                    continue
                marker = self.journal_read("request", key)
                if marker and marker["payload"] == wanted:
                    return self._read_control()
                raise
        self._journal_conflict("etag_conflict")

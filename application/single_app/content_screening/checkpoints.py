# checkpoints.py
"""Private immutable checkpoints for completed model inspection windows."""

import json
from datetime import datetime, timezone

from content_screening.contracts import (
    SCREENING_FIELD,
    ScreeningConflictError,
    ScreeningError,
    hash_payload,
    normalize_identifier,
)


MAX_WINDOW_RESULT_BYTES = 1024 * 1024


class ModelWindowCheckpoints:
    def __init__(self, subject, scan_id, check, owner, *, repository, storage):
        self.subject = subject
        self.scan_id = scan_id
        self.check = {key: value for key, value in check.items() if key != "limits"}
        self.check_fingerprint = hash_payload(self.check)
        self.owner = owner
        self.repository = repository
        self.storage = storage
        scan = self._require_scan()
        self.content_fingerprint = scan["content_fingerprint"]
        self.policy_fingerprint = scan["policy_fingerprint"]

    def _require_scan(self):
        scan = self.repository.get_scan(self.scan_id)
        if not scan or scan.get("subject") != self.subject.to_dict():
            raise ScreeningConflictError()
        document = self.repository.read_document(self.subject)
        marker = document.get(SCREENING_FIELD) or {}
        lease = scan.get("lease") or {}
        try:
            expires = datetime.fromisoformat(lease["expires_at"])
        except (KeyError, TypeError, ValueError) as error:
            raise ScreeningConflictError() from error
        if (
            scan.get("state") != "scanning" or marker.get("state") != "scanning"
            or marker.get("scan_id") != self.scan_id or lease.get("owner") != self.owner
            or expires.tzinfo is None or expires <= datetime.now(timezone.utc)
            or not scan.get("content_fingerprint")
            or hash_payload(scan.get("policy")) != scan.get("policy_fingerprint")
            or getattr(self, "content_fingerprint", scan["content_fingerprint"]) != scan["content_fingerprint"]
            or getattr(self, "policy_fingerprint", scan["policy_fingerprint"]) != scan["policy_fingerprint"]
        ):
            raise ScreeningConflictError()
        expected = next(
            (check for check in scan["policy"].get("ai_checks", []) if check.get("id") == self.check.get("id")),
            None,
        )
        if expected is None or hash_payload(expected) != self.check_fingerprint:
            raise ScreeningConflictError()
        return scan

    def _identity(self, window_id):
        window_id = normalize_identifier(window_id, "window_id")
        binding = {
            "scan_id": self.scan_id, "subject": self.subject.to_dict(), "window_id": window_id,
            "content_fingerprint": self.content_fingerprint,
            "policy_fingerprint": self.policy_fingerprint,
            "check_fingerprint": self.check_fingerprint,
        }
        return f"model-window-{hash_payload(binding)}", binding

    def _latch_findings(self, payload):
        result = payload.get("result") if isinstance(payload, dict) else None
        if not isinstance(result, str):
            return
        try:
            verdict = json.loads(result)
        except (TypeError, ValueError) as error:
            raise ScreeningError(code="screening_checkpoint_invalid") from error
        if not isinstance(verdict, dict) or not isinstance(verdict.get("results"), list):
            raise ScreeningError(code="screening_checkpoint_invalid")
        if not any(isinstance(row, dict) and row.get("matched") is True for row in verdict["results"]):
            return
        for _attempt in range(3):
            scan = self._require_scan()
            document = self.repository.read_document(self.subject)
            marker = document.get(SCREENING_FIELD) or {}
            try:
                if not marker.get("review_required"):
                    self.repository.update_document(self.subject, {
                        SCREENING_FIELD: {**marker, "review_required": True},
                    }, etag=document["_etag"])
                if not scan.get("review_required"):
                    self.repository.replace({
                        **scan, "review_required": True, "review_reason": "model_window_finding",
                    }, scan["_etag"])
                return
            except ScreeningConflictError:
                continue
        raise ScreeningConflictError()

    def get(self, window_id):
        self._require_scan()
        record_id, binding = self._identity(window_id)
        record = self.repository.get(record_id, self.scan_id)
        if record is None:
            return None
        if record.get("kind") != "model_window" or any(record.get(key) != value for key, value in binding.items()):
            raise ScreeningConflictError()
        payload = self.storage.read_json(record["result_ref"], self.subject)
        if hash_payload(payload) != record.get("payload_fingerprint"):
            raise ScreeningConflictError()
        self._require_scan()
        self._latch_findings(payload)
        return payload

    def put(self, window_id, payload):
        self._require_scan()
        if not isinstance(payload, dict):
            raise ScreeningError(code="screening_checkpoint_invalid")
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
        if len(encoded) > MAX_WINDOW_RESULT_BYTES:
            raise ScreeningError(code="screening_checkpoint_limit")
        self._latch_findings(payload)
        record_id, binding = self._identity(window_id)
        fingerprint = hash_payload(payload)
        reference = self.storage.write_json(
            self.subject, self.scan_id, f"{record_id}-{fingerprint}", payload,
        )
        self._require_scan()
        record = {
            "id": record_id, "partition_key": self.scan_id, "kind": "model_window",
            "scope_key": self.subject.scope_key, "scope_type": self.subject.scope_type,
            "scope_id": self.subject.scope_id, "document_id": self.subject.document_id,
            **binding, "payload_fingerprint": fingerprint, "result_ref": reference,
        }
        try:
            self.repository.create(record)
        except ScreeningConflictError:
            existing = self.repository.get(record_id, self.scan_id)
            if (
                not existing or existing.get("kind") != "model_window"
                or existing.get("payload_fingerprint") != fingerprint
                or any(existing.get(key) != value for key, value in binding.items())
            ):
                raise

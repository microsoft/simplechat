# app_settings_store.py
"""Shared settings reads and fenced, optimistic writes; never cache settings in a worker."""

import copy
import json
import time
import uuid

from azure.core import MatchConditions
from azure.cosmos.exceptions import (
    CosmosAccessConditionFailedError,
    CosmosResourceExistsError,
    CosmosResourceNotFoundError,
)
from redis.exceptions import RedisError


SETTINGS_ID = "app_settings"
SETTINGS_STATE_KEY = "APP_SETTINGS_STATE_V2"
SETTINGS_REVISION_FIELD = "_settings_revision"
WRITE_LEASE_SECONDS = 30
MAX_WRITE_ATTEMPTS = 5
COSMOS_METADATA_FIELDS = {"_etag", "_rid", "_self", "_attachments", "_ts"}

# A single key keeps publication atomic on both clustered and non-clustered Redis.
# Pending records deliberately have no TTL: a crashed writer must not expose old data.
COMPARE_AND_SET = """
local current = redis.call('GET', KEYS[1])
if (current or '') ~= ARGV[1] then return 0 end
redis.call('SET', KEYS[1], ARGV[2])
return 1
"""


class SettingsConflictError(RuntimeError):
    """The settings changed after the caller's read."""


class SettingsUnavailableError(RuntimeError):
    """A settings write cannot safely start or finish."""


class AppSettingsStore:
    def __init__(self, container, redis_client=None, *, redis_required=False, on_fallback=None):
        self.container = container
        self.redis = redis_client
        self.redis_required = redis_required
        self.on_fallback = on_fallback

    def _fallback(self, error):
        if self.on_fallback is not None:
            self.on_fallback(error)

    def _read_cosmos(self, session_token=None):
        headers = {}

        def capture_headers(response_headers, _body):
            headers.update(response_headers)

        document = self.container.read_item(
            item=SETTINGS_ID,
            partition_key=SETTINGS_ID,
            session_token=session_token,
            response_hook=capture_headers,
        )
        return copy.deepcopy(document), headers.get("x-ms-session-token", session_token)

    @staticmethod
    def _decode(raw):
        if raw is None:
            return None
        state = json.loads(raw)
        if not isinstance(state, dict) or state.get("state") not in {"ready", "pending"}:
            raise SettingsUnavailableError("Invalid shared settings state.")
        if state["state"] == "ready":
            document = state.get("document")
            if not isinstance(document, dict) or not document.get("_etag"):
                raise SettingsUnavailableError("Invalid shared settings document.")
        elif not isinstance(state.get("deadline"), (int, float)):
            raise SettingsUnavailableError("Invalid shared settings write marker.")
        return state

    def _raw_state(self):
        if self.redis is None:
            raise SettingsUnavailableError("Configured Redis is unavailable; settings were not saved.")
        return self.redis.get(SETTINGS_STATE_KEY)

    def _compare_and_set(self, previous, replacement):
        return bool(self.redis.eval(COMPARE_AND_SET, 1, SETTINGS_STATE_KEY, previous or "", replacement))

    def read(self, *, use_cosmos=False):
        if not self.redis_required:
            return self._read_cosmos()[0]
        try:
            raw = self._raw_state()
            state = self._decode(raw)
            if state and state["state"] == "ready" and not use_cosmos:
                return copy.deepcopy(state["document"])
            token = state.get("session_token") if state else None
            if use_cosmos or (state and state["deadline"] > time.time()):
                return self._read_cosmos(token)[0]
            self._read_cosmos(token)
            # Cache misses and abandoned writes are repaired with an ETag-checked
            # write. A plain GET/SET could publish an older session snapshot.
            return self._write(lambda document: document, observed_raw=raw)
        except (RedisError, SettingsUnavailableError, SettingsConflictError, ValueError) as error:
            self._fallback(error)
            return self._read_cosmos()[0]

    def write(self, transform, *, expected_etag=None, defaults=None):
        """Apply a change to authoritative settings, conditional on the read ETag."""
        try:
            return self._write(transform, expected_etag=expected_etag, defaults=defaults)
        except RedisError as error:
            raise SettingsUnavailableError(
                "Unable to confirm the settings save. Reload and verify before retrying."
            ) from error

    def _write(self, transform, *, expected_etag=None, defaults=None, observed_raw=None):
        marker = None
        session_token = None
        if self.redis_required:
            raw = self._raw_state()
            if observed_raw is not None and raw != observed_raw:
                raise SettingsConflictError("Shared settings changed; retry the read.")
            state = self._decode(raw)
            if state:
                session_token = state.get("session_token")
                if state["state"] == "pending" and state["deadline"] > time.time():
                    raise SettingsUnavailableError("Another settings save is in progress. Please retry.")
                if (
                    state["state"] == "ready"
                    and expected_etag is not None
                    and state["document"]["_etag"] != expected_etag
                ):
                    raise SettingsConflictError("Settings changed. Reload before saving again.")
            marker = json.dumps({
                "state": "pending",
                "owner": uuid.uuid4().hex,
                "deadline": time.time() + WRITE_LEASE_SECONDS,
                "session_token": session_token,
            })
            if not self._compare_and_set(raw, marker):
                raise SettingsConflictError("Another worker started a settings save.")

        for _ in range(MAX_WRITE_ATTEMPTS):
            try:
                current, session_token = self._read_cosmos(session_token)
            except CosmosResourceNotFoundError:
                if defaults is None:
                    raise
                current = copy.deepcopy(defaults)

            if expected_etag is not None and current.get("_etag") != expected_etag:
                # Leave the marker pending. Readers use Cosmos until safe repair;
                # never publish a snapshot that has not passed an ETag check.
                raise SettingsConflictError("Settings changed. Reload before saving again.")
            candidate = transform(copy.deepcopy(current))
            candidate = {
                key: copy.deepcopy(value)
                for key, value in candidate.items()
                if key not in COSMOS_METADATA_FIELDS
            }
            candidate["id"] = SETTINGS_ID
            candidate[SETTINGS_REVISION_FIELD] = int(current.get(SETTINGS_REVISION_FIELD, 0)) + 1

            if marker is not None:
                # Fencing plus Cosmos OCC prevents an expired writer committing
                # over the replacement writer, even if it resumes much later.
                raw = self._raw_state()
                if raw not in (marker, marker.encode("utf-8")):
                    raise SettingsConflictError("Settings write ownership expired.")

            headers = {}

            def capture_headers(response_headers, _body):
                headers.update(response_headers)

            try:
                if current.get("_etag"):
                    stored = self.container.replace_item(
                        item=SETTINGS_ID,
                        body=candidate,
                        etag=current["_etag"],
                        match_condition=MatchConditions.IfNotModified,
                        session_token=session_token,
                        response_hook=capture_headers,
                    )
                else:
                    stored = self.container.create_item(body=candidate, response_hook=capture_headers)
            except (CosmosAccessConditionFailedError, CosmosResourceExistsError):
                if expected_etag is not None:
                    raise SettingsConflictError("Settings changed during the save.")
                continue

            if marker is not None:
                ready = json.dumps({
                    "state": "ready",
                    "document": dict(stored),
                    "session_token": headers.get("x-ms-session-token", session_token),
                })
                if not self._compare_and_set(marker, ready):
                    raise SettingsUnavailableError(
                        "The database save completed but shared publication was superseded. Reload to verify."
                    )
            return copy.deepcopy(stored)
        raise SettingsConflictError("Settings kept changing; reload and retry.")

# functions_session_store.py
"""Server-side session persistence that does not lose concurrent writes.

Flask-Session 0.8 writes the whole stored session back at the end of every request, so the
request that finishes last wins. A slow request that loaded the session before another
request saved a change then writes its stale copy over that change. SimpleChat runs several
instances and threads against one Redis store, and the V2 interface keeps several requests in
flight, so this happens in practice: a pending Microsoft 365 sign-in saved by one request was
erased by a bootstrap request that had started earlier and finished later.

These interfaces keep Flask-Session's cookie and storage format and change only how a request
writes its changes back:

* A request that changed nothing only refreshes the stored session's expiry.
* A request that changed keys writes just those keys, and removes just the keys it removed,
  into the latest stored copy. Redis applies the merge atomically.
* A new session, a cleared session and a session whose id changed are written whole, as
  before.
* A session deleted while the request ran, by sign-out or the idle timeout, is not recreated
  from the request's stale copy.

Two requests that change the same key still resolve last writer wins, as before.
"""

import copy
import logging
import warnings

from flask_session.defaults import Defaults
from flask_session.filesystem import FileSystemSession, FileSystemSessionInterface
from flask_session.redis import RedisSession, RedisSessionInterface
from redis.exceptions import WatchError

from functions_appinsights import log_event


MERGE_ATTEMPTS = 5
PERMANENT_KEY = "_permanent"
_BASELINE_ATTR = "_simplechat_baseline"
_BASELINE_SID_ATTR = "_simplechat_baseline_sid"
_REPLACED_ATTR = "_simplechat_replaced"


def _ttl_seconds(session_lifetime):
    """Whole seconds in the session lifetime, as Flask-Session computes its storage TTL."""
    return session_lifetime.days * 86400 + session_lifetime.seconds


def _has_content(data):
    """A stored session needs at least one key besides the permanent flag."""
    return any(key != PERMANENT_KEY for key in data)


def _apply_changes(stored, changed, removed):
    """The stored session with this request's changes applied, other keys untouched."""
    merged = dict(stored) if isinstance(stored, dict) else {}
    merged.update(changed)
    for key in removed:
        merged.pop(key, None)
    return merged


def session_changes(session):
    """Keys this request changed and removed, or None when the session must be written whole.

    A session opened by another interface carries no baseline, which happens on a worker's
    first request when initialization swaps the session backend mid-request, and is written
    whole as before.
    """
    baseline = getattr(session, _BASELINE_ATTR, None)
    if (
        baseline is None
        or getattr(session, _REPLACED_ATTR, False)
        or getattr(session, _BASELINE_SID_ATTR, None) != session.sid
    ):
        return None
    current = dict(session)
    changed = {
        key: value for key, value in current.items()
        if key not in baseline or baseline[key] != value
    }
    removed = [key for key in baseline if key not in current]
    return changed, removed


class _MergingSessionMixin:
    """Record what a request loaded so the save can write only what it changed."""

    def open_session(self, app, request):
        session = super().open_session(app, request)
        # A stored session always holds more than the permanent flag; a new one does not.
        if session:
            setattr(session, _BASELINE_ATTR, copy.deepcopy(dict(session)))
            setattr(session, _BASELINE_SID_ATTR, session.sid)
        return session

    def _upsert_session(self, session_lifetime, session, store_id):
        changes = session_changes(session)
        if changes is None:
            self._write_whole(session_lifetime, session, store_id)
            return
        changed, removed = changes
        ttl = _ttl_seconds(session_lifetime)
        if not changed and not removed:
            self._refresh_expiry(store_id, ttl)
            return
        self._merge_changes(session_lifetime, session, store_id, changed, removed, ttl)

    def _write_whole(self, session_lifetime, session, store_id):
        """Flask-Session's own save, which replaces the stored session with this one."""
        super()._upsert_session(session_lifetime, session, store_id)

    def _refresh_expiry(self, store_id, ttl):
        raise NotImplementedError()

    def _merge_changes(self, session_lifetime, session, store_id, changed, removed, ttl):
        raise NotImplementedError()


class MergingRedisSession(RedisSession):
    def clear(self):
        setattr(self, _REPLACED_ATTR, True)
        super().clear()


class MergingRedisSessionInterface(_MergingSessionMixin, RedisSessionInterface):
    """Redis sessions whose saves merge into the latest stored copy with WATCH/MULTI/EXEC."""

    session_class = MergingRedisSession

    def _refresh_expiry(self, store_id, ttl):
        # EXPIRE never recreates a key, so a session deleted meanwhile stays deleted.
        self.client.expire(store_id, ttl)

    def _decode_stored(self, stored):
        try:
            return self.serializer.decode(stored)
        except Exception as exc:
            log_event(
                "[SESSION_STORE] The stored session could not be read; writing this request's session whole.",
                extra={"exception_type": type(exc).__name__},
                level=logging.WARNING,
            )
            return None

    def _merge_changes(self, session_lifetime, session, store_id, changed, removed, ttl):
        for _attempt in range(MERGE_ATTEMPTS):
            with self.client.pipeline() as pipe:
                try:
                    pipe.watch(store_id)
                    stored = pipe.get(store_id)
                    if stored is None:
                        # Signed out or expired while this request ran: do not recreate it.
                        return
                    current = self._decode_stored(stored)
                    if current is None:
                        pipe.reset()
                        self._write_whole(session_lifetime, session, store_id)
                        return
                    merged = _apply_changes(current, changed, removed)
                    pipe.multi()
                    if _has_content(merged):
                        pipe.set(store_id, self.serializer.encode(merged), ex=ttl)
                    else:
                        pipe.delete(store_id)
                    pipe.execute()
                    return
                except WatchError:
                    continue
        log_event(
            "[SESSION_STORE] Session save kept losing an optimistic-lock race; merging without the lock.",
            extra={"attempts": MERGE_ATTEMPTS, "changed_key_count": len(changed), "removed_key_count": len(removed)},
            level=logging.WARNING,
        )
        stored = self.client.get(store_id)
        if stored is None:
            return
        current = self._decode_stored(stored)
        if current is None:
            self._write_whole(session_lifetime, session, store_id)
            return
        merged = _apply_changes(current, changed, removed)
        if _has_content(merged):
            self.client.set(name=store_id, value=self.serializer.encode(merged), ex=ttl)
        else:
            self.client.delete(store_id)


class MergingFileSystemSession(FileSystemSession):
    def clear(self):
        setattr(self, _REPLACED_ATTR, True)
        super().clear()


class MergingFileSystemSessionInterface(_MergingSessionMixin, FileSystemSessionInterface):
    """Filesystem sessions that merge into the latest stored copy.

    The file cache has no transactions, so the merge is a read and an atomic file replace a
    moment apart rather than the whole request apart. This backend serves single-instance
    and development deployments, and the Redis fallback.
    """

    session_class = MergingFileSystemSession

    def _refresh_expiry(self, store_id, ttl):
        stored = self.cache.get(store_id)
        if stored is not None:
            self.cache.set(key=store_id, value=stored, timeout=ttl)

    def _merge_changes(self, session_lifetime, session, store_id, changed, removed, ttl):
        stored = self.cache.get(store_id)
        if stored is None:
            return
        merged = _apply_changes(stored, changed, removed)
        if _has_content(merged):
            self.cache.set(key=store_id, value=merged, timeout=ttl)
        else:
            self.cache.delete(store_id)


def install_merging_session_interface(app):
    """Replace the interface ``Session(app)`` installed with its merging equivalent.

    Call it straight after every ``Session(app)``. The replacement reuses the installed
    interface's Redis client or file cache, so storage and existing sessions are unchanged.
    """
    current = app.session_interface
    if isinstance(current, _MergingSessionMixin):
        return current
    config = app.config
    common = {
        "app": app,
        "key_prefix": config.get("SESSION_KEY_PREFIX", Defaults.SESSION_KEY_PREFIX),
        "use_signer": config.get("SESSION_USE_SIGNER", Defaults.SESSION_USE_SIGNER),
        "permanent": config.get("SESSION_PERMANENT", Defaults.SESSION_PERMANENT),
        "sid_length": config.get("SESSION_ID_LENGTH", Defaults.SESSION_ID_LENGTH),
        "serialization_format": config.get(
            "SESSION_SERIALIZATION_FORMAT", Defaults.SESSION_SERIALIZATION_FORMAT,
        ),
    }
    # Session(app) already raised these deprecation warnings for the same configuration.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        if isinstance(current, RedisSessionInterface):
            replacement = MergingRedisSessionInterface(client=current.client, **common)
        elif isinstance(current, FileSystemSessionInterface):
            replacement = MergingFileSystemSessionInterface(
                cache_dir=config.get("SESSION_FILE_DIR", Defaults.SESSION_FILE_DIR),
                threshold=config.get("SESSION_FILE_THRESHOLD", Defaults.SESSION_FILE_THRESHOLD),
                mode=config.get("SESSION_FILE_MODE", Defaults.SESSION_FILE_MODE),
                **common,
            )
            replacement.cache = current.cache
        else:
            log_event(
                "[SESSION_STORE] The configured session backend has no merging interface; concurrent saves stay last writer wins.",
                extra={"session_interface": type(current).__name__},
                level=logging.WARNING,
            )
            return current
    app.session_interface = replacement
    return replacement

# model_catalog_updates.py
"""Catalog storage owner and fixed-source transport, with injected runtime dependencies."""

import base64
from copy import deepcopy
from datetime import datetime, timezone
import logging
from pathlib import Path
import threading

from azure.cosmos.exceptions import CosmosResourceExistsError
import requests

from cosmos_document_utils import normalize_cosmos_document
from model_catalog_package import (
    CATALOG_REPOSITORY, DISCOVERY_URL, MAX_PACKAGE_BYTES, CatalogUpdateError,
    package_url, read_json, trusted_keys, verify_package,
)


ACTIVE = "model_catalog_revision"
PREVIOUS = "model_catalog_previous_revision"
ONLINE = "enable_model_catalog_online_updates"
CHECK = "model_catalog_update_check"


def _download(url, maximum):
    with requests.get(
        url, timeout=(3, 10), stream=True, allow_redirects=False,
        headers={"Accept": "application/json"},
    ) as response:
        if response.status_code != 200:
            raise CatalogUpdateError("The official catalog source is unavailable.")
        data = bytearray()
        for chunk in response.iter_content(16384):
            data.extend(chunk)
            if len(data) > maximum:
                raise CatalogUpdateError("The official catalog response exceeds its size limit.")
        return bytes(data)


class CatalogUpdates:
    def __init__(self, container, store, version, log_event, *, keys=None, download=_download):
        self.container = container
        self.store = store
        self.version = version
        self.log_event = log_event
        self.keys = keys
        self.download = download
        self._cache = {}
        self._lock = threading.Lock()

    def _keys(self):
        return trusted_keys() if self.keys is None else self.keys

    def _baseline(self):
        path = Path(__file__).resolve().parent / "static" / "json" / "model_capabilities.json"
        return read_json(path.read_bytes())

    def _read_revision(self, digest):
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise CatalogUpdateError("The stored catalog revision reference is invalid.")
        with self._lock:
            cached = self._cache.get(digest)
        if cached is not None:
            return deepcopy(cached)
        record_id = f"model_catalog:{digest}"
        record = normalize_cosmos_document(self.container.read_item(item=record_id, partition_key=record_id))
        try:
            raw = base64.b64decode(record["package"], validate=True)
        except (KeyError, ValueError, TypeError) as exc:
            raise CatalogUpdateError("The stored catalog package is invalid.") from exc
        verified = verify_package(raw, self.version, keys=self._keys())
        if verified["digest"] != digest:
            raise CatalogUpdateError("The stored catalog package does not match its revision.")
        with self._lock:
            if len(self._cache) >= 4:
                self._cache.clear()
            self._cache[digest] = verified
        return deepcopy(verified)

    def snapshot(self):
        settings = self.store.read()
        digest = settings.get(ACTIVE)
        if not digest:
            return None
        try:
            return self._read_revision(digest)["document"]
        except Exception as exc:
            self.log_event(
                "[MODELS] Active model catalog unavailable.", level=logging.ERROR,
                extra={"error_type": type(exc).__name__},
            )
            raise

    def status(self, settings=None):
        settings = self.store.read() if settings is None else settings
        installed = self._read_revision(settings[ACTIVE]) if settings.get(ACTIVE) else None
        return {
            "etag": settings.get("_etag"),
            "onlineEnabled": settings.get(ONLINE) is True,
            "publisherConfigured": bool(self._keys()),
            "repository": CATALOG_REPOSITORY,
            "discoveryUrl": DISCOVERY_URL,
            "installed": installed["manifest"] if installed else {
                "revision": "bundled", "publishedAt": self._baseline()["lastUpdated"],
            },
            "digest": settings.get(ACTIVE),
            "canRollback": bool(settings.get(ACTIVE)),
            "check": settings.get(CHECK),
        }

    def _validate_change(self, candidate, settings, *, rollback=False):
        previous = self._read_revision(settings[ACTIVE]) if settings.get(ACTIVE) else None
        current = previous["document"] if previous else self._baseline()
        if candidate is None:
            document = self._baseline()
        else:
            document = candidate["document"]
            if not rollback and previous and int(candidate["manifest"]["revision"]) <= int(previous["manifest"]["revision"]):
                raise CatalogUpdateError("Choose a newer catalog revision, or use explicit rollback.")
        before = {item["id"]: item for item in current["models"]}
        after = {item["id"]: item for item in document["models"]}
        removed = sorted(before.keys() - after.keys())
        if removed and not rollback:
            raise CatalogUpdateError("This update removes existing model IDs. Removals are not supported.")
        # A previous package is not necessarily safe after new profiles/connections were saved.
        custom = (settings.get("model_catalog") or {}).get("profiles") or []
        aliases = {
            str(value).casefold() for item in custom
            for value in [item["id"], *item.get("aliases", [])]
        }
        built_in = {
            str(value).casefold() for item in document["models"]
            for value in [item["id"], *item.get("aliases", [])]
        }
        if aliases & built_in:
            raise CatalogUpdateError("Catalog identities conflict with a custom profile. Resolve its aliases first.")
        for endpoint in settings.get("model_endpoints") or []:
            for model in endpoint.get("models") or []:
                for field in ("catalogProfileId", "catalogModelId"):
                    linked = model.get(field)
                    if linked in before and linked not in after:
                        raise CatalogUpdateError("This change would break a model connection link.")
        if rollback and removed:
            # Personal/group links are not enumerated here. Do not silently strand them.
            raise CatalogUpdateError("Rollback would remove model IDs. Review those connections before recovery.")
        return {
            "added": sorted(after.keys() - before.keys()),
            "changed": sorted(key for key in before.keys() & after.keys() if before[key] != after[key]),
            "removed": removed,
            "operationMetadataChanged": current.get("imageOperationProfiles") != document.get("imageOperationProfiles"),
        }

    def preview(self, raw, actor):
        candidate = verify_package(raw, self.version, keys=self._keys())
        settings = self.store.read()
        changes = self._validate_change(candidate, settings)
        record_id = f"model_catalog:{candidate['digest']}"
        try:
            self.container.create_item({
                "id": record_id, "type": "model_catalog_package",
                "package": base64.b64encode(raw).decode("ascii"),
                "createdBy": actor,
            })
        except CosmosResourceExistsError:
            # Re-read and verify an existing immutable record, never overwrite it.
            self._read_revision(candidate["digest"])
        return {
            "digest": candidate["digest"], "manifest": candidate["manifest"],
            "signatureVerified": True, "changes": changes, "etag": settings.get("_etag"),
        }

    def preview_staged(self, digest):
        candidate = self._read_revision(digest)
        settings = self.store.read()
        return {
            "digest": candidate["digest"], "manifest": candidate["manifest"],
            "signatureVerified": True, "changes": self._validate_change(candidate, settings),
            "etag": settings.get("_etag"),
        }

    def set_online(self, enabled, etag, actor):
        if type(enabled) is not bool:
            raise CatalogUpdateError("Online access must be enabled or disabled explicitly.")

        def transform(settings):
            settings[ONLINE] = enabled
            return settings

        saved = self.store.write(transform, expected_etag=etag)
        self.log_event("[MODELS] Catalog online access changed.", extra={"actor": actor, "enabled": enabled})
        return self.status(saved)

    def activate(self, digest, etag, actor, *, rollback=False):
        candidate = self._read_revision(digest) if digest is not None else None
        if not rollback and candidate is None:
            raise CatalogUpdateError("Preview a signed package before applying it.")
        audit = {}

        def transform(settings):
            target = settings.get(PREVIOUS) if rollback else digest
            if rollback and target != digest:
                raise CatalogUpdateError("The rollback target changed. Reload before retrying.")
            if not rollback and settings.get(ACTIVE) == digest:
                raise CatalogUpdateError("This catalog is already installed.")
            self._validate_change(candidate, settings, rollback=rollback)
            audit.update(previous=settings.get(ACTIVE), revision=target)
            settings[PREVIOUS] = settings.get(ACTIVE)
            settings[ACTIVE] = target
            if (settings.get(CHECK) or {}).get("digest") == target:
                settings[CHECK] = {**settings[CHECK], "status": "current"}
            return settings

        saved = self.store.write(transform, expected_etag=etag)
        self.log_event("[MODELS] Catalog revision activated.", extra={
            **audit, "actor": actor, "rollback": rollback,
            "key_id": candidate["manifest"]["keyId"] if candidate else "bundled",
        })
        return self.status(saved)

    def rollback_target(self):
        settings = self.store.read()
        digest = settings.get(PREVIOUS)
        candidate = self._read_revision(digest) if digest else None
        return {
            "digest": digest, "etag": settings.get("_etag"),
            "manifest": candidate["manifest"] if candidate else {"revision": "bundled"},
            "changes": self._validate_change(candidate, settings, rollback=True),
        }

    def check(self, actor):
        now = datetime.now(timezone.utc)

        def start(settings):
            if settings.get(ONLINE) is not True:
                raise CatalogUpdateError("Enable online catalog access before contacting GitHub.")
            if not self._keys():
                raise CatalogUpdateError("The publisher verification key has not been configured.")
            last = (settings.get(CHECK) or {}).get("attemptedAt")
            if last:
                try:
                    elapsed = (now - datetime.fromisoformat(last)).total_seconds()
                except (ValueError, TypeError) as exc:
                    raise CatalogUpdateError("The stored catalog check timestamp is invalid.") from exc
                if elapsed < 60:
                    raise CatalogUpdateError("Wait one minute between catalog update checks.")
            settings[CHECK] = {"status": "checking", "attemptedAt": now.isoformat()}
            return settings

        self.store.write(start)
        try:
            discovery = read_json(self.download(DISCOVERY_URL, 8192), 8192)
            if not isinstance(discovery, dict) or set(discovery) != {"commit", "filename"}:
                raise CatalogUpdateError("The official catalog discovery response is invalid.")
            url = package_url(discovery["commit"], discovery["filename"])
            # Re-check the setting immediately before the second outbound request.
            if self.store.read().get(ONLINE) is not True:
                raise CatalogUpdateError("Online catalog access was disabled.")
            raw = self.download(url, MAX_PACKAGE_BYTES)
            verified = verify_package(raw, self.version, keys=self._keys())
            expected_filename = f"catalog-{verified['manifest']['revision']}-{verified['manifest']['publishedAt'][:10]}.json"
            if discovery["filename"] != expected_filename:
                raise CatalogUpdateError("The package does not match the discovered catalog release.")
            current = self.store.read()
            installed = self._read_revision(current[ACTIVE]) if current.get(ACTIVE) else None
            if installed and int(verified["manifest"]["revision"]) <= int(installed["manifest"]["revision"]):
                result = {"status": "current", "attemptedAt": now.isoformat(), "downloadUrl": url}
            else:
                preview = self.preview(raw, actor)
                result = {
                    "status": "available", "attemptedAt": now.isoformat(),
                    "downloadUrl": url, "digest": preview["digest"], "manifest": preview["manifest"],
                }
        except (requests.RequestException, CatalogUpdateError) as exc:
            self.log_event("[MODELS] Catalog update check failed.", level=logging.WARNING, extra={
                "error_type": type(exc).__name__, "actor": actor,
            })
            self.store.write(lambda settings: {**settings, CHECK: {
                "status": "failed", "attemptedAt": now.isoformat(),
            }})
            raise CatalogUpdateError("Unable to verify an official catalog update. The installed catalog is unchanged.") from exc
        saved = self.store.write(lambda settings: {**settings, CHECK: result})
        return self.status(saved)

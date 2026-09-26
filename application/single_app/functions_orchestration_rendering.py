# functions_orchestration_rendering.py
"""Explicit retained-input rendering with durable, independent file attempts.

No producer, composition model, executor, route, or configuration owner is
imported. Runtime owners supply current capability/admission checks and private
transport. Approved deadlines and retry admissions survive worker replacement.
"""

import hashlib
import io
import math
import random
import time
import uuid
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict
from datetime import timedelta

from azure.core.exceptions import AzureError, ResourceNotFoundError
from azure.cosmos.exceptions import CosmosResourceNotFoundError
from werkzeug.utils import secure_filename

from content_screening.contracts import (
    DocumentHeldError,
    ScreeningError,
    SourceAuthorityUnavailableError,
    SourceAuthorityUnverifiedError,
)
from functions_analysis_access import AnalysisResultUnavailable
from functions_export_cleanup import ClosingExportResource
from functions_generated_export_contracts import (
    GeneratedFileExportError,
    GeneratedFileExportLimits,
    GeneratedFileExportRequest,
    GeneratedFileExportStream,
)
from functions_generated_export_registry import resolve_generated_file_export_format
from functions_generated_file_exports import build_generated_file_export
from functions_orchestration_artifacts import (
    OrchestrationArtifactTransport,
    assert_artifact_matches,
    binding_for_intent,
    committed_artifact_card,
    external_authority_failure,
    orchestration_artifact_file_extensions,
    output_storage_failure,
    validate_orchestration_artifact_binding,
)
from functions_orchestration_export_sources import open_orchestration_export_source
from functions_orchestration_output_store import (
    OUTPUT_UNAVAILABLE_MESSAGES,
    OrchestrationOutputStore,
    OutputClaim,
    OutputConflictError,
    OutputError,
    OutputStorageError,
    OutputUnavailableError,
    _OUTPUT_ID,
    _step_signature,
    parse_time,
    public_output,
)
from functions_orchestration_result_contracts import (
    IMAGE_ASSET_KIND, MAX_IMAGE_ASSET_PIXELS, ProducerIdentity, ResultContractError, ResultRef,
    validate_image_asset_value,
)
from functions_orchestration_results import (
    OrchestrationResultReader,
    OrchestrationResults,
    ResultUnavailableError,
)
from functions_workflow_result_store import AnalysisWorkUnitConflictError, WorkflowResultIntegrityError


MAX_OUTPUT_BYTES = 500 * 1024 * 1024
# A render re-proves its claim, run state, capability admission and source access on this
# cadence rather than on every block it writes. Publication boundaries still check in full.
RENDER_FULL_CHECK_INTERVAL_SECONDS = 5.0
_REQUEST_FIELDS = frozenset({"output_format", "profile", "columns", "title", "sheet_name"})
_STOP_CODES = frozenset({
    "output_cancelled", "output_deleted", "output_superseded", "output_plan_changed",
    "output_run_unavailable", "output_conversation_unavailable",
})
_TRANSIENT_RENDER_CODES = frozenset({"render_io", "source_unavailable"})
_VALIDATION_CODES = frozenset({
    "unsupported_format", "unsupported_profile", "unsupported_source", "invalid_options",
    "invalid_source", "invalid_data", "incomplete_source", "count_mismatch", "invalid_limit",
    "output_too_large", "size_limit", "source_limit", "invalid_report", "invalid_deck",
    "layout_overflow", "image_unavailable", "invalid_image", "invalid_structure",
})
_SOURCE_CONFIGURATION_CODES = frozenset({
    "result_source_reader_required", "result_external_authorizer_required",
})
_SOURCE_CHANGED_CODES = frozenset({
    "analysis_source_snapshot_changed", "result_source_snapshot_changed",
    "result_external_snapshot_changed",
})
_SOURCE_READ_FAILURES = (
    PermissionError, LookupError, DocumentHeldError, AnalysisWorkUnitConflictError,
    WorkflowResultIntegrityError, ResultContractError, ResourceNotFoundError,
    CosmosResourceNotFoundError, OutputError,
)


class OutputStepTimeLimitError(RuntimeError):
    """The owning step's time budget ended this attempt before its file was staged.

    Deliberately not a ValueError: the bounded serializers turn a ValueError raised by an
    execution check into a value-limit failure.
    """

    retryable = False
    code = "output_step_time_limit"

    def __init__(self):
        super().__init__("The generated file's step reached its time limit.")


def raise_output_read_infrastructure_failure(error):
    """An authorization wrapper must not disguise a failed backing-store read."""
    authority = external_authority_failure(error)
    if authority is not None:
        raise authority[0]
    storage = output_storage_failure(error)
    if isinstance(storage, OutputStorageError):
        raise storage
    if storage is not None:
        raise OutputStorageError() from error
    seen = set()
    current = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, (OutputStorageError, TimeoutError, ConnectionError)) or (
            isinstance(current, AzureError)
            and not isinstance(current, (ResourceNotFoundError, CosmosResourceNotFoundError))
        ):
            raise OutputStorageError() from error
        if isinstance(current, ScreeningError) and not isinstance(current, DocumentHeldError):
            raise current
        if isinstance(current, OutputError) and current.code == "output_source_configuration_invalid":
            raise current
        if isinstance(current, ResultUnavailableError) and current.code in _SOURCE_CONFIGURATION_CODES:
            raise current
        if current is not error:
            known_source_failure = isinstance(current, _SOURCE_READ_FAILURES)
            if isinstance(current, LookupError):
                known_source_failure = type(current) is LookupError
            if not known_source_failure:
                raise current
        current = current.__cause__


def _source_visibility_code(error):
    raise_output_read_infrastructure_failure(error)
    if isinstance(error, DocumentHeldError):
        return "output_screening_hold"
    if isinstance(error, OutputUnavailableError):
        return error.code if error.code in OUTPUT_UNAVAILABLE_MESSAGES else None
    if isinstance(error, (ResultUnavailableError, AnalysisResultUnavailable)):
        if error.code in _SOURCE_CONFIGURATION_CODES:
            return None
        if error.code in _SOURCE_CHANGED_CODES:
            return "output_source_changed"
        if error.code in {"result_producer_unavailable", "result_attempt_mismatch", "result_attempt_stopped"}:
            return "output_source_unavailable"
        return "output_access_denied"
    if isinstance(error, PermissionError):
        return "output_access_denied"
    if type(error) is LookupError:
        return "output_source_unavailable"
    if isinstance(error, AnalysisWorkUnitConflictError):
        return "output_source_unavailable" if error.code in {"analysis_work_deleted", "analysis_work_missing"} else None
    if isinstance(error, (
        WorkflowResultIntegrityError, ResultContractError, ResourceNotFoundError,
        CosmosResourceNotFoundError,
    )):
        return "output_source_unavailable"
    if isinstance(error, OutputError) and error.code == "output_invalid_result":
        return "output_source_unavailable"
    return None


def output_failure(exc):
    """Classify once without persisting or exposing provider exception messages."""
    if isinstance(exc, OutputStepTimeLimitError):
        return exc.code, False
    authority = external_authority_failure(exc)
    if authority is not None:
        return authority[1], authority[2]
    if output_storage_failure(exc) is not None:
        return "output_storage_unavailable", True
    if isinstance(exc, DocumentHeldError):
        return "output_screening_hold", False
    if isinstance(exc, SourceAuthorityUnavailableError):
        return exc.code, True
    if isinstance(exc, SourceAuthorityUnverifiedError):
        return exc.code, False
    if isinstance(exc, ScreeningError):
        return "output_screening_unavailable", exc.retryable is True
    if isinstance(exc, OutputStorageError):
        return exc.code, True
    if isinstance(exc, (OutputError, OutputUnavailableError)):
        return exc.code, False
    if isinstance(exc, PermissionError):
        return "output_access_denied", False
    if isinstance(exc, ResultContractError):
        return "output_invalid_result", False
    if isinstance(exc, GeneratedFileExportError):
        code = exc.code if exc.code in _VALIDATION_CODES | _TRANSIENT_RENDER_CODES else "render_validation_failed"
        return code, bool(exc.retryable is True and code in _TRANSIENT_RENDER_CODES)
    if isinstance(exc, (TimeoutError, ConnectionError)):
        return "output_transport_unavailable", True
    if isinstance(exc, AzureError):
        status = getattr(exc, "status_code", None)
        retryable = status is None or status in (408, 429) or (type(status) is int and 500 <= status <= 599)
        return "output_storage_unavailable" if retryable else "output_storage_rejected", retryable
    if isinstance(exc, (ValueError, TypeError)):
        return "output_invalid", False
    return "output_failed", False


def _request(spec):
    values = {name: deepcopy(spec[name]) for name in _REQUEST_FIELDS}
    if values["columns"] is not None:
        values["columns"] = tuple(values["columns"])
    return GeneratedFileExportRequest(**values)


def _file_name(value, extensions):
    if (
        type(value) is not str or not value.strip()
        or any(char in value for char in "/\\") or any(ord(char) < 32 for char in value)
    ):
        raise OutputError("output_filename_invalid")
    try:
        size = len(value.encode("utf-8"))
    except UnicodeError as exc:
        raise OutputError("output_filename_invalid") from exc
    if size > 255:
        raise OutputError("output_filename_invalid")
    normalized = secure_filename(value)
    if not normalized or not normalized.lower().endswith(tuple(f".{extension}" for extension in extensions)):
        raise OutputError("output_filename_invalid")
    return normalized


def _render_request(step):
    arguments = step.get("arguments") or {}
    if (
        type(arguments) is not dict
        or set(arguments) - {"file_name", "output_format", "profile", "options"}
        or not {"file_name", "output_format", "profile"}.issubset(arguments)
    ):
        raise OutputError("output_request_invalid")
    options = arguments.get("options") or {}
    if type(options) is not dict or set(options) - {"columns", "title", "sheet_name"}:
        raise OutputError("output_request_invalid")
    options = deepcopy(options)
    if "columns" in options and type(options["columns"]) is list:
        options["columns"] = tuple(options["columns"])
    return arguments["file_name"], GeneratedFileExportRequest(
        arguments["output_format"], arguments["profile"], **options,
    )


# A document embeds each generated image as a rendition the Office renderers accept.
_DOCUMENT_IMAGE_FORMATS = frozenset({"PNG", "JPEG"})
_DOCUMENT_IMAGE_JPEG_QUALITIES = (90, 80)
_DOCUMENT_IMAGE_MIN_SIDE = 64
_DOCUMENT_IMAGE_SCALE_STEP = 0.75


def _encoded_image(image, image_format, **options):
    with io.BytesIO() as buffer:
        image.save(buffer, format=image_format, **options)
        return buffer.getvalue()


def document_image_bytes(content, *, max_bytes, max_pixels):
    """The PNG or JPEG bytes a DOCX, PDF, or PPTX embeds for one verified generated image.

    Chat keeps each image exactly as generated. The Office renderers accept only
    single-frame PNG or JPEG within their byte and pixel limits, so an image that already
    fits is embedded unchanged and anything else, such as WEBP or a large PNG, is re-encoded
    and scaled down only as far as needed. Generation admits only images this can always
    convert, so an image never fails its file for its size or format. Transparency is kept
    in PNG and flattened onto white for JPEG.
    """
    # Pillow is part of the lazily loaded file-rendering stack; see functions_generated_file_exports.
    from PIL import Image, UnidentifiedImageError

    try:
        with Image.open(io.BytesIO(content)) as image:
            width, height = image.size
            if not 0 < width * height <= MAX_IMAGE_ASSET_PIXELS:
                raise OutputError("output_invalid")
            if (
                image.format in _DOCUMENT_IMAGE_FORMATS and getattr(image, "n_frames", 1) == 1
                and len(content) <= max_bytes and width * height <= max_pixels
            ):
                return content
            source_format = image.format
            image.seek(0)
            image.load()
            alpha = "A" in image.getbands() or (image.mode == "P" and "transparency" in image.info)
            working = image.convert("RGBA" if alpha else "RGB")
    except OutputError:
        raise
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, SyntaxError, ValueError) as exc:
        raise OutputError("output_invalid") from exc
    scale = min(1.0, math.sqrt(max_pixels / (width * height)))
    while True:
        size = (max(1, math.floor(width * scale)), max(1, math.floor(height * scale)))
        frame = working if size == working.size else working.resize(size, Image.Resampling.LANCZOS)
        if source_format != "JPEG":
            data = _encoded_image(frame, "PNG")
            if len(data) <= max_bytes:
                return data
        flat = frame
        if frame.mode == "RGBA":
            flat = Image.new("RGB", frame.size, "white")
            flat.paste(frame, mask=frame.getchannel("A"))
        for quality in _DOCUMENT_IMAGE_JPEG_QUALITIES:
            data = _encoded_image(flat, "JPEG", quality=quality, optimize=True)
            if len(data) <= max_bytes:
                return data
        if min(size) <= _DOCUMENT_IMAGE_MIN_SIDE:
            raise OutputError("output_invalid")
        scale *= _DOCUMENT_IMAGE_SCALE_STEP


class _RenderAttempt:
    """Pace one claimed attempt's execution checks and time its phases.

    Renderers, digest verification and upload hashing call their check per record or
    block. Re-running the full claim check (owner row, parent run, capability admission
    and source access) on every call made large files spend most of their time
    re-authorizing. A full check still runs first, right before the intent is prepared,
    at least once per ``interval`` while work continues, and whenever the lease needs
    renewing or the deadline arrives. The calls in between do no I/O. The intent, staging
    writes and commit keep their own fenced checks.

    ``stop()`` is consulted only on full checks, until the file is staged. A stop the
    claim check does not explain (a user cancellation or the run deadline surface there
    first) ends the attempt with ``OutputStepTimeLimitError``.
    """

    def __init__(self, service, *, stop=None):
        self.service = service
        self.store = service.store
        self.stop = stop
        self.interval = min(service.full_check_interval, self.store.lease_seconds / 4)
        self.claim = None
        self.full_checks = 0
        self.light_checks = 0
        self.source_rechecks = 0
        self.paced_source_rechecks = 0
        self.stop_observed = False
        self.phases = {}
        self.started = service.monotonic()
        self._last_full = None
        self._last_recheck = None
        self._due_at = None

    def bind(self, claim):
        self.claim = claim

    def release_stop(self):
        """Staged bytes are always committed; a later budget overrun is the owner's to report."""
        self.stop = None

    @contextmanager
    def phase(self, name):
        started = self.service.monotonic()
        try:
            yield
        finally:
            elapsed = max(0.0, self.service.monotonic() - started)
            self.phases[name] = self.phases.get(name, 0.0) + elapsed

    def _stop_requested(self):
        if self.stop is None:
            return False
        if not self.stop_observed:
            try:
                self.stop_observed = bool(self.stop())
            except Exception:
                # A failing owner probe is not a render outcome. The claim check that
                # follows fences this attempt on the output's own ownership evidence.
                return False
        return self.stop_observed

    def full(self, operation="render"):
        stopping = self._stop_requested()
        self.full_checks += 1
        record = self.service._check_claim(self.claim, operation)
        self._last_full = self.service.monotonic()
        lease_expires = parse_time(record["lease"]["expires_at"])
        deadline = parse_time(record["deadline_at"])
        self._due_at = (
            lease_expires - timedelta(seconds=self.store.lease_seconds / 2)
            if lease_expires < deadline else deadline
        )
        if stopping:
            raise OutputStepTimeLimitError()
        return record

    def __call__(self):
        if (
            self._last_full is None
            or self.service.monotonic() - self._last_full >= self.interval
            or self.store.clock() > self._due_at
        ):
            self.full()
        else:
            self.light_checks += 1

    def paced_recheck(self, recheck):
        now = self.service.monotonic()
        if self._last_recheck is not None and now - self._last_recheck < self.interval:
            self.paced_source_rechecks += 1
            return
        self.source_rechecks += 1
        recheck()
        self._last_recheck = self.service.monotonic()

    def facts(self, outcome=None, failure=None):
        """Identifier-free timing, check counts and outcome for diagnostics."""
        facts = {f"{name}_ms": int(seconds * 1000) for name, seconds in self.phases.items()}
        facts.update({
            "total_ms": int(max(0.0, self.service.monotonic() - self.started) * 1000),
            "full_checks": self.full_checks,
            "light_checks": self.light_checks,
            "source_rechecks": self.source_rechecks,
            "paced_source_rechecks": self.paced_source_rechecks,
            "stop_observed": self.stop_observed,
        })
        if type(outcome) is dict:
            facts.update({
                "status": outcome.get("state"),
                "output_code": outcome.get("error_code"),
                "output_format": outcome.get("output_format"),
                "size_bytes": outcome.get("size_bytes"),
            })
        else:
            facts.update({
                "status": "raised",
                "output_code": output_failure(failure)[0] if failure is not None else None,
            })
        return facts


class _PacedSource:
    """The renderer's view of its source: frequent rechecks share the attempt's cadence.

    Only the renderer receives this view. The source's own rechecks at the start and end of
    every read, digest verification and the complete-consumption receipt use the real
    source, so a changed or revoked source is still refused before anything is published.
    """

    def __init__(self, source, attempt):
        self._source = source
        self._attempt = attempt

    def recheck(self):
        self._attempt.paced_recheck(self._source.recheck)

    def __getattr__(self, name):
        if name in {"_source", "_attempt"}:
            raise AttributeError(name)
        return getattr(self._source, name)


class OrchestrationRenderingService:
    """One actor/conversation, no implicit source resolution or client construction.

    ``authorize_execution(record, operation=...)`` must revalidate current
    capabilities and the approved server-owned render/source admission. It must
    raise on denial (or return False); it never receives a browser source path.
    Operations are admit/render/prepare/commit/retry/read/publication.
    """

    def __init__(
        self, store, results, transport, *, authorize_execution,
        max_output_bytes, limits=None, office_limits=None, image_resolver=None,
        image_asset_reader=None, renderer=build_generated_file_export, jitter=random.random,
        full_check_interval=RENDER_FULL_CHECK_INTERVAL_SECONDS, monotonic=time.monotonic,
    ):
        if (
            not isinstance(store, OrchestrationOutputStore)
            or not isinstance(results, OrchestrationResults)
            or not isinstance(transport, OrchestrationArtifactTransport)
            or not callable(authorize_execution) or not callable(renderer) or not callable(jitter)
            or not callable(monotonic)
            or results.access.user_id != store.user_id
            or results.access.conversation_id != store.conversation_id
            or (image_asset_reader is not None and not callable(image_asset_reader))
        ):
            raise OutputError("output_service_required")
        if type(max_output_bytes) is not int or not 1 <= max_output_bytes <= MAX_OUTPUT_BYTES:
            raise OutputError("output_limit_invalid")
        if limits is not None and type(limits) is not GeneratedFileExportLimits:
            raise OutputError("output_limit_invalid")
        if (
            type(full_check_interval) not in (int, float)
            or not math.isfinite(full_check_interval) or full_check_interval <= 0
        ):
            raise OutputError("output_limit_invalid")
        self.store = store
        self.results = results
        self.transport = transport
        self.authorize_execution = authorize_execution
        self.max_output_bytes = max_output_bytes
        self.limits = limits or GeneratedFileExportLimits()
        self.office_limits = office_limits
        self.image_resolver = image_resolver
        # ``image_asset_reader(asset)`` returns the stored bytes of one retained generated
        # image descriptor; the owner supplies it. The service decides which images a file
        # may contain and verifies every byte it is given.
        self.image_asset_reader = image_asset_reader
        self.renderer = renderer
        self.jitter = jitter
        self.full_check_interval = full_check_interval
        self.monotonic = monotonic

    def _image_resolver_for(self, record, entry):
        """Resolve only the generated images the rendered source was prepared from.

        The source's own retained lineage names them: a file can embed an image only when
        its prepared content consumed that image as an input, under the same owner and
        conversation, and only with the exact bytes the image step retained.
        """
        if not entry.rich_media:
            return None
        if self.image_asset_reader is None:
            return self.image_resolver
        source = ResultRef.from_dict(record["source_ref"])
        cache = {}
        # The Office stack loads lazily; its limits decide what an embedded image may be.
        from functions_office_file_renderers import OfficeRenderLimits

        office_limits = self.office_limits or OfficeRenderLimits()

        def images():
            if "lineage" not in cache:
                reader = self.results.open_result(
                    source, require_current_sources=record["render_spec"]["require_current_sources"],
                )
                cache["lineage"] = {
                    parent.producer.step_id: parent for parent in reader.upstream_references()
                    if parent.kind == IMAGE_ASSET_KIND and parent.producer.capability_id == "generate_image"
                }
            return cache["lineage"]

        def resolve(reference):
            asset_id = reference[len("asset:"):] if type(reference) is str and reference.startswith("asset:") else None
            parent = images().get(asset_id) if asset_id else None
            if parent is None:
                raise OutputUnavailableError("output_source_unavailable")
            reader = self.results.open_result(parent, require_current_sources=True)
            asset = validate_image_asset_value(reader.read_value())
            if asset["asset_id"] != asset_id:
                raise OutputUnavailableError("output_source_changed")
            content = self.image_asset_reader(deepcopy(asset))
            reader.recheck()
            if (
                type(content) is not bytes or len(content) != asset["size_bytes"]
                or hashlib.sha256(content).hexdigest() != asset["content_sha256"]
            ):
                raise OutputUnavailableError("output_source_changed")
            # The exact retained bytes are verified above; the file embeds their rendition.
            # Every image the source consumed shares the renderer's total pixel budget.
            return document_image_bytes(
                content, max_bytes=office_limits.max_image_bytes,
                max_pixels=min(
                    office_limits.max_image_pixels,
                    office_limits.max_total_image_pixels // max(1, len(images())),
                ),
            )

        return resolve

    @staticmethod
    def _read_metadata(read, *args, **kwargs):
        """A metadata I/O permission fault is not a source-access decision."""
        try:
            return read(*args, **kwargs)
        except PermissionError as exc:
            if type(exc) is not PermissionError:
                raise
            raise OutputStorageError() from exc

    def _authorize(self, record, operation):
        live = operation in {"admit", "render", "prepare", "commit", "retry"}
        self._read_metadata(self.store.current_run, record, live=live)
        if record.get("deleted_at") or record["state"] == "cancelled":
            raise OutputUnavailableError("output_deleted" if record.get("deleted_at") else "output_cancelled")
        try:
            if self.authorize_execution(deepcopy(record), operation=operation) is False:
                raise OutputUnavailableError("output_capability_disabled")
            reference = ResultRef.from_dict(record["source_ref"])
            return self.results.open_result(
                reference, require_current_sources=record["render_spec"]["require_current_sources"],
            )
        except ScreeningError as exc:
            raise_output_read_infrastructure_failure(exc)
            raise
        except (OutputError, OutputUnavailableError, OutputStorageError) as exc:
            authority = external_authority_failure(exc)
            if authority is not None:
                raise authority[0]
            if output_storage_failure(exc) is not None:
                raise_output_read_infrastructure_failure(exc)
            raise
        except ResultUnavailableError as exc:
            authority = external_authority_failure(exc)
            if authority is not None:
                raise authority[0]
            if exc.code in _SOURCE_CONFIGURATION_CODES:
                raise OutputError("output_source_configuration_invalid") from exc
            raise OutputUnavailableError(_source_visibility_code(exc)) from exc
        except PermissionError as exc:
            raise OutputUnavailableError(_source_visibility_code(exc)) from exc
        except LookupError as exc:
            authority = external_authority_failure(exc)
            if authority is not None:
                raise authority[0]
            if type(exc) is not LookupError:
                raise
            raise OutputUnavailableError("output_source_unavailable") from exc
        except (ResourceNotFoundError, CosmosResourceNotFoundError) as exc:
            authority = external_authority_failure(exc)
            if authority is not None:
                raise authority[0]
            raise OutputUnavailableError("output_source_unavailable") from exc
        except AnalysisWorkUnitConflictError as exc:
            code = _source_visibility_code(exc)
            if code is None:
                raise
            raise OutputUnavailableError(code) from exc
        except (AzureError, TimeoutError, ConnectionError) as exc:
            authority = external_authority_failure(exc)
            if authority is not None:
                raise authority[0]
            raise OutputStorageError() from exc
        except (ResultContractError, WorkflowResultIntegrityError) as exc:
            authority = external_authority_failure(exc)
            if authority is not None:
                raise authority[0]
            if output_storage_failure(exc) is not None:
                raise_output_read_infrastructure_failure(exc)
            raise OutputError("output_invalid_result") from exc
        except (RuntimeError, ValueError, TypeError, AttributeError, OSError) as exc:
            authority = external_authority_failure(exc)
            if authority is not None:
                raise authority[0]
            if output_storage_failure(exc) is not None:
                raise_output_read_infrastructure_failure(exc)
            raise

    def ensure_output(
        self, *, producer, source_ref, export_request, file_name,
        approved_work_id, deadline_at, require_current_sources=True,
    ):
        if type(source_ref) is not ResultRef or type(export_request) is not GeneratedFileExportRequest:
            raise OutputError("output_binding_invalid")
        if type(require_current_sources) is not bool:
            raise OutputError("output_binding_invalid")
        source = open_orchestration_export_source(
            self.results, source_ref, columns=export_request.columns,
            require_current_sources=require_current_sources,
        )
        entry = resolve_generated_file_export_format(export_request, source.kind)
        request = asdict(export_request)
        request["output_format"] = entry.format_id
        if request["columns"] is not None:
            request["columns"] = list(request["columns"])
        spec = {
            **request, "renderer_id": entry.renderer_id, "renderer_version": entry.renderer_version,
            "require_current_sources": require_current_sources,
            "max_output_bytes": self.max_output_bytes, "limits": asdict(self.limits),
        }
        record = self.store.ensure(
            producer=producer, source_ref=source_ref, render_spec=spec,
            file_name=_file_name(file_name, orchestration_artifact_file_extensions(entry.format_id)),
            approved_work_id=approved_work_id, deadline_at=deadline_at,
            check=self._authorize,
        )
        return public_output(record)

    def _check_claim(self, claim, operation="render"):
        record = self.store.owned(claim)
        self._authorize(record, operation).recheck()
        remaining = (parse_time(record["lease"]["expires_at"]) - self.store.clock()).total_seconds()
        if remaining < self.store.lease_seconds / 2:
            record = self.store.renew(claim)
        return record

    def _read_record(self, output_id):
        return self._read_record_state(self._read_metadata(self.store.get, output_id))

    def _authorize_read_record(self, record):
        self._authorize(record, "read").recheck()
        if record["state"] == "completed" and self._read_metadata(
            self.transport.message, record, committed=True,
        ) is None:
            raise OutputUnavailableError("output_artifact_missing")
        return record

    def _pending_deadline_exceeded(self, record):
        return (
            record["state"] in {"waiting", "rendering", "retry_scheduled"}
            or (record["state"] == "failed" and record["can_retry"])
        ) and parse_time(record["deadline_at"]) <= self.store.clock()

    def _read_record_state(self, record):
        record = self._authorize_read_record(record)
        if self._pending_deadline_exceeded(record):
            record = self.store.fail(
                record["id"], code="output_deadline_exceeded", retryable=False,
            )
        return record

    def read(self, output_id):
        return public_output(self._read_record(output_id))

    def _public_records(self, run_id):
        for candidate in self._read_metadata(self.store.list_outputs, run_id):
            try:
                record = self._read_record(candidate["id"])
            except _SOURCE_READ_FAILURES as exc:
                code = _source_visibility_code(exc)
                if code is None:
                    raise
                yield public_output(candidate, unavailable_code=code), None
            else:
                yield public_output(record), record

    def list_public_outputs(self, run_id):
        """Current per-file visibility; a source denial cannot hide its siblings."""
        return [projection for projection, _ in self._public_records(run_id)]

    def claim_due(self, output_id, *, worker_id=None):
        record = self.store.get(output_id)
        if record["state"] in {"completed", "cancelled", "failed"}:
            return None
        return self.store.claim_due(
            output_id, worker_id=worker_id or f"render-{uuid.uuid4().hex}",
            check=lambda current: self._authorize(current, "render").recheck(),
        )

    def _retry_delay(self, record, exc):
        base = min(30.0, float(2 ** (record["automatic_attempts"] - 1)))
        noise = self.jitter()
        if type(noise) not in (int, float) or not math.isfinite(noise) or not 0 <= noise <= 1:
            raise OutputError("output_retry_invalid")
        delay = base + noise * min(base / 4, 5)
        advice = getattr(exc, "retry_after", None)
        if advice is None:
            headers = getattr(exc, "headers", None) or {}
            advice = headers.get("Retry-After") or headers.get("retry-after")
        if advice is not None and not isinstance(advice, bool):
            try:
                seconds = float(advice)
            except (TypeError, ValueError):
                seconds = 0
            if math.isfinite(seconds) and 0 <= seconds <= 300:
                delay = max(delay, seconds)
        return min(delay, 300)

    def _commit(self, claim):
        record = self._check_claim(claim, "commit")
        committed = self.store.commit(
            claim, intent_id=record["intent"]["intent_id"],
            check=lambda current: self._authorize(current, "commit").recheck(),
        )
        self._authorize(committed, "read").recheck()
        return public_output(committed)

    def _verify_rendered(self, rendered, source, record, check):
        request = _request(record["render_spec"])
        entry = resolve_generated_file_export_format(request, source.kind)
        if (
            type(rendered) is not GeneratedFileExportStream
            or rendered.output_format != entry.format_id or rendered.media_type != entry.media_type
            or rendered.file_extension != entry.file_extension or rendered.profile != request.profile
            or rendered.source_kind != source.kind
            or type(rendered.size_bytes) is not int or rendered.size_bytes < 0
            or rendered.size_bytes > min(self.max_output_bytes, record["render_spec"]["max_output_bytes"])
            or type(rendered.record_count) is not int
            or rendered.record_count != (source.record_count if source.kind == "records" else 0)
            or rendered.character_count != (
                source.character_count if source.kind in {"text", "markdown"} else None
            )
            or (
                rendered.size_bytes == 0 and not (
                    entry.format_id in {"txt", "md"} and request.profile == "prepared_text_v1"
                    and rendered.character_count == 0
                )
            )
        ):
            raise OutputError("output_render_contract_invalid")
        source.require_complete_consumption()
        stream = rendered.file_content
        stream.seek(0)
        digest, size = hashlib.sha256(), 0
        while True:
            check()
            block = stream.read(64 * 1024)
            if not block:
                break
            if type(block) is not bytes:
                raise OutputError("output_render_contract_invalid")
            size += len(block)
            if size > rendered.size_bytes:
                raise OutputError("output_digest_mismatch")
            digest.update(block)
        if size != rendered.size_bytes or digest.hexdigest() != rendered.content_sha256:
            raise OutputError("output_digest_mismatch")
        stream.seek(0)
        source.require_complete_consumption()
        check()

    def _observe_output(self, output_id):
        current = self.store.get(output_id)
        return public_output(current) if current["state"] == "cancelled" else self.read(output_id)

    def _record_failure(self, output_id, exc, claim, *, skip_commit_reconciliation=False):
        record = self.store.get(output_id)
        if record["state"] == "completed":
            return self.read(output_id)
        if record["state"] == "cancelled":
            return public_output(record)
        if isinstance(exc, OutputConflictError):
            if (
                claim is not None and (record.get("lease") or {}).get("token") == claim.token
                and parse_time(record["deadline_at"]) <= self.store.clock()
            ):
                stopped = self.store.cancel(output_id, code="output_deadline_exceeded")
                return public_output(stopped)
            return self._observe_output(output_id)
        code, retryable = output_failure(exc)
        if code in _STOP_CODES:
            # An owner stop may close an expired lease, but never advances a live
            # replacement worker. The run's own cancellation/deletion fence wins.
            if claim is not None:
                lease = record.get("lease") or {}
                if lease.get("token") != claim.token:
                    return self._observe_output(output_id)
            try:
                cancelled = self.store.cancel(output_id, code=code)
            except OutputUnavailableError:
                raise OutputUnavailableError(code) from exc
            return public_output(cancelled)
        if retryable and claim is not None and record.get("intent") and not skip_commit_reconciliation:
            # A transport/commit timeout is not evidence of failure. If the
            # authoritative read is also unavailable, leave the attempt leased
            # for recovery instead of admitting another automatic attempt.
            try:
                self._check_claim(claim, "prepare")
                ready = self.transport.reconcile(
                    record, check=lambda: self._check_claim(claim, "prepare"),
                )
                if ready:
                    return self._commit(claim)
            except OutputConflictError:
                return self._observe_output(output_id)
            except Exception as recovery_error:
                # The authoritative row, not an unavailable blob response,
                # decides whether another admitted attempt is safe.
                current = self.store.get(output_id)
                if current["state"] == "completed":
                    return self.read(output_id)
                recovery_code, recovery_retryable = output_failure(recovery_error)
                code, retryable = recovery_code, recovery_retryable
                exc = recovery_error
        if code in _STOP_CODES:
            current = self.store.get(output_id)
            if claim is not None and (current.get("lease") or {}).get("token") != claim.token:
                return self._observe_output(output_id)
            return public_output(self.store.cancel(output_id, code=code))
        if claim is not None:
            current = self.store.get(output_id)
            lease = current.get("lease") or {}
            if lease.get("token") != claim.token:
                return self._observe_output(output_id)
            if parse_time(lease["expires_at"]) <= self.store.clock():
                if parse_time(current["deadline_at"]) <= self.store.clock():
                    stopped = self.store.cancel(output_id, code="output_deadline_exceeded")
                    return public_output(stopped)
                return self._observe_output(output_id)
        delay = self._retry_delay(record, exc) if retryable else 0
        try:
            failed = self.store.fail(
                output_id, code=code, retryable=retryable, retry_delay=delay, claim=claim,
            )
        except OutputConflictError:
            return self._observe_output(output_id)
        return public_output(
            failed, unavailable_code=code if code in OUTPUT_UNAVAILABLE_MESSAGES else None,
            withhold_details=external_authority_failure(exc) is not None or (
                isinstance(exc, ScreeningError) and not isinstance(exc, DocumentHeldError)
            ),
        )

    def _stage(self, claim, record, stream, *, check):
        intent_id = record["intent"]["intent_id"]
        staged = self.store.register_staging(claim, intent_id)
        try:
            self.transport.stage(staged, stream, check=check)
        except Exception:
            self.store.rearm_staging_cleanup(claim, intent_id)
            raise
        self.store.rearm_staging_cleanup(claim, intent_id)

    def render_attempt(self, output_id, *, claim=None, worker_id=None, stop=None, observe=None):
        """Run at most one admitted attempt; duplicate/live workers only observe.

        ``stop()`` is the owning step's stop probe. Once it reports a stop before the file
        is staged, the attempt ends as a non-retryable ``output_step_time_limit`` failure
        unless the claim check reports a more specific stop. ``observe(facts)`` receives the
        identifier-free timing and check counts of a claimed attempt.
        """
        if (stop is not None and not callable(stop)) or (observe is not None and not callable(observe)):
            raise OutputError("output_service_required")
        attempt = _RenderAttempt(self, stop=stop)
        outcome = failure = None
        try:
            outcome = self._render_attempt(output_id, claim, worker_id, attempt)
            return outcome
        except Exception as exc:
            failure = exc
            raise
        finally:
            if observe is not None and attempt.claim is not None:
                try:
                    observe(attempt.facts(outcome, failure))
                except Exception:
                    # Diagnostics never change the attempt's durable outcome.
                    pass

    def _render_attempt(self, output_id, claim, worker_id, attempt):
        record = self.store.get(output_id)
        if record["state"] in {"completed", "failed"}:
            return self.read(output_id)
        if record["state"] == "cancelled":
            return public_output(record)
        skip_commit_reconciliation = False
        observing = False
        try:
            claim = claim or self.claim_due(output_id, worker_id=worker_id)
            if claim is None:
                observing = True
                return self.read(output_id)
            attempt.bind(claim)
            record = attempt.full()
            check = attempt
            if claim.recovering:
                skip_commit_reconciliation = True
                if record.get("intent"):
                    self.transport.reconcile(record, check=check)
                interrupted = TimeoutError("The prior render worker did not finish.")
                return self._record_failure(
                    output_id, interrupted, claim, skip_commit_reconciliation=True,
                )
            if record.get("intent"):
                with attempt.phase("stage"):
                    recovered = self.transport.reconcile(
                        record, check=check, restore_message=True,
                        stage=lambda current, stream, **checks: self._stage(claim, current, stream, **checks),
                    )
                if recovered:
                    skip_commit_reconciliation = True
                    attempt.release_stop()
                    with attempt.phase("commit"):
                        return self._commit(claim)
            source = open_orchestration_export_source(
                self.results, ResultRef.from_dict(record["source_ref"]),
                columns=record["render_spec"]["columns"],
                max_value_bytes=min(self.limits.max_value_bytes, record["render_spec"]["limits"]["max_value_bytes"]),
                require_current_sources=record["render_spec"]["require_current_sources"],
            )
            request = _request(record["render_spec"])
            entry = resolve_generated_file_export_format(request, source.kind)
            if (
                entry.renderer_id != record["render_spec"]["renderer_id"]
                or entry.renderer_version != record["render_spec"]["renderer_version"]
            ):
                raise OutputError("output_renderer_changed")
            bounded_limits = GeneratedFileExportLimits(**{
                name: min(value, record["render_spec"]["limits"][name])
                for name, value in asdict(self.limits).items()
            })
            with attempt.phase("render"):
                rendered = self.renderer(
                    source=_PacedSource(source, attempt), export_request=request,
                    max_output_bytes=min(self.max_output_bytes, record["render_spec"]["max_output_bytes"]),
                    check=check, limits=bounded_limits, office_limits=self.office_limits,
                    image_resolver=self._image_resolver_for(record, entry),
                )
            with ClosingExportResource(rendered):
                with attempt.phase("verify"):
                    self._verify_rendered(rendered, source, record, check)
                descriptor = self.transport.descriptor(record, rendered)
                # The last stop consultation and full claim check before anything is staged.
                attempt.full()
                prepared = self.store.prepare_intent(
                    claim, descriptor, check=lambda current: self._authorize(current, "prepare").recheck(),
                )
                with attempt.phase("stage"):
                    self._stage(claim, prepared, rendered.file_content, check=check)
                attempt.release_stop()
                source.require_complete_consumption()
                if not self.transport.reconcile(prepared, check=check):
                    raise OutputError("output_artifact_missing")
                skip_commit_reconciliation = True
                with attempt.phase("commit"):
                    return self._commit(claim)
        except Exception as exc:
            if observing:
                raise
            return self._record_failure(
                output_id, exc, claim, skip_commit_reconciliation=skip_commit_reconciliation,
            )

    def reconcile(self, output_id, *, worker_id=None):
        record = self.store.get(output_id)
        cleaning_failure = record["state"] == "failed" and not record["retryable"]
        if record.get("cleanup_pending") and (
            record["state"] in {"cancelled", "completed"} or cleaning_failure
        ):
            self.transport.cleanup(record)
            record = self.store.cleanup_finished(
                output_id, generation=record.get("cleanup_generation", 0),
            )
        if record["state"] == "cancelled" or cleaning_failure:
            return public_output(record)
        self._authorize(record, "read").recheck()
        if record["state"] == "completed":
            ready = self.transport.reconcile(
                record, committed=True,
                check=lambda: self._authorize(self.store.get(output_id), "read").recheck(),
            )
            if not ready:
                raise OutputUnavailableError("output_artifact_missing")
            return public_output(record)
        if record["state"] != "rendering":
            return public_output(record)
        claim = self.store.claim_due(
            output_id, worker_id=worker_id or f"reconcile-{uuid.uuid4().hex}",
            reconcile_only=bool(record.get("intent")),
        )
        if claim is None:
            return public_output(self.store.get(output_id))
        try:
            record = self._check_claim(claim, "prepare")
            self.transport.reconcile(
                record, check=lambda: self._check_claim(claim, "prepare"),
            )
            if claim.recovering:
                return self._record_failure(
                    output_id, TimeoutError("The render worker stopped."), claim,
                    skip_commit_reconciliation=True,
                )
            return public_output(self.store.release_reconciliation(claim))
        except Exception as exc:
            return self._record_failure(
                output_id, exc, claim, skip_commit_reconciliation=claim.recovering,
            )

    def manual_retry(self, output_id, request_id):
        # This also checks for a prior completed manifest before reserving a new
        # manual attempt. It never resets or restarts the automatic cycle.
        self.reconcile(output_id)
        record = self.store.get(output_id)
        self._authorize(record, "retry" if record["state"] != "completed" else "read").recheck()
        if record["state"] == "completed":
            return public_output(record)
        saved = self.store.manual_retry(
            output_id, request_id, check=lambda current: self._authorize(current, "retry").recheck(),
        )
        return public_output(saved)

    def cancel(self, output_id, *, deleted=False):
        record = self.store.cancel(output_id, deleted=deleted)
        if record["state"] == "cancelled" and record.get("cleanup_pending"):
            self.transport.cleanup(record)
            record = self.store.cleanup_finished(
                output_id, generation=record.get("cleanup_generation", 0),
            )
        return public_output(record)

    def authorize_binding(self, value, *, require_ready=True, for_publication=False):
        binding = validate_orchestration_artifact_binding(value)
        record = self.store.get(binding["output_id"])
        descriptor = record.get("committed_intent") if require_ready else record.get("intent")
        if (
            descriptor is None or binding != binding_for_intent(record, descriptor)
            or (require_ready and record["state"] != "completed")
            or (not require_ready and record["state"] != "rendering")
        ):
            raise OutputUnavailableError("output_not_committed")
        self.transport.validate_descriptor(record, descriptor)
        if not require_ready:
            lease = record.get("lease") or {}
            if not lease.get("token") or parse_time(lease["expires_at"]) <= self.store.clock():
                raise OutputUnavailableError("output_ownership_lost")
            self.store.owned(OutputClaim(
                record["id"], lease["token"], record["attempt_count"],
                lease["generation"], "rendering",
            ))
        reader = self._authorize(
            record, "prepare" if not require_ready else "publication" if for_publication else "read",
        )
        reader.recheck()
        return {
            "binding": binding, "descriptor": deepcopy(descriptor), "source": reader,
            "idempotency_key": descriptor["idempotency_key"],
            "output_format": descriptor["output_format"],
        }

    def authorize_cleanup(self, value):
        binding = validate_orchestration_artifact_binding(value)
        record = self.store.get(binding["output_id"])
        self.store.current_run(record, stopping=True)
        matches = [item for item in record["intents"] if item["intent_id"] == binding["intent_id"]]
        if (
            len(matches) != 1 or binding_for_intent(record, matches[0]) != binding
            or (
                not (
                    record["state"] == "cancelled"
                    or (record["state"] == "failed" and not record["retryable"])
                )
                and (
                    (record.get("intent") or {}).get("intent_id") == binding["intent_id"]
                    or (record.get("committed_intent") or {}).get("intent_id") == binding["intent_id"]
                )
            )
        ):
            raise OutputUnavailableError("output_cleanup_denied")
        self.transport.validate_descriptor(record, matches[0])
        return {"binding": binding, "descriptor": deepcopy(matches[0])}

    def invalidate_artifact(self, value, artifact):
        binding = validate_orchestration_artifact_binding(value)
        record = self.store.get(binding["output_id"])
        matches = [item for item in record["intents"] if item["intent_id"] == binding["intent_id"]]
        if len(matches) != 1 or binding_for_intent(record, matches[0]) != binding:
            raise OutputUnavailableError("output_binding_invalid")
        assert_artifact_matches(artifact, binding, matches[0])
        return self.store.cancel(record["id"], deleted=True)

    def committed_artifacts(self, run_id):
        return [
            committed_artifact_card(record)
            for projection, record in self._public_records(run_id)
            if record is not None and projection["available"] and record["state"] == "completed"
        ]

    @contextmanager
    def open_download(self, output_id):
        record = self.store.get(output_id)
        if record["state"] != "completed":
            raise OutputUnavailableError("output_not_committed")
        self._authorize(record, "read").recheck()
        artifact = self.transport.message(record, committed=True)
        if artifact is None:
            raise OutputUnavailableError("output_artifact_missing")

        def check():
            current = self.store.get(output_id)
            self.authorize_binding(binding_for_intent(record, record["committed_intent"]))
            if current["committed_intent"] != record["committed_intent"]:
                raise OutputUnavailableError("output_artifact_mismatch")

        with self.transport.open_stream(artifact, check=check) as stream:
            yield stream


def _render_step_result(output, record, *, build_step_result, build_failure):
    if output["state"] == "completed":
        result = build_step_result(
            status="completed", summary=output["message"],
            artifacts=[committed_artifact_card(record)],
        )
    elif output["state"] in {"waiting", "rendering", "retry_scheduled"}:
        result = build_step_result(
            status="waiting", summary=output["message"],
            wait={"kind": "orchestration_output", **output},
        )
    elif output["state"] == "cancelled":
        result = build_step_result(status="cancelled", summary=output["message"])
    else:
        # A file its step's time budget stopped reports that budget, with its admin hint.
        failure_code = "step_timeout" if output.get("error_code") == OutputStepTimeLimitError.code else "step_failed"
        result = build_step_result(
            status="failed", summary=output["message"],
            failure=build_failure(failure_code), error=output["message"],
        )
    result["outputs"] = [output]
    return result


def _saved_render_output_id(saved_result):
    if type(saved_result) is not dict or saved_result.get("status") not in ("waiting", "completed"):
        raise OutputError("output_binding_invalid")
    candidates = []
    wait = saved_result.get("wait")
    if wait is not None:
        if type(wait) is not dict or wait.get("kind") != "orchestration_output":
            raise OutputError("output_binding_invalid")
        candidate = wait.get("output_id")
        if type(candidate) is not str or _OUTPUT_ID.fullmatch(candidate) is None:
            raise OutputError("output_binding_invalid")
        candidates.append(candidate)
    outputs = saved_result.get("outputs")
    if outputs is not None:
        if type(outputs) is not list or len(outputs) > 1:
            raise OutputError("output_binding_invalid")
        if outputs:
            if type(outputs[0]) is not dict:
                raise OutputError("output_binding_invalid")
            candidate = outputs[0].get("output_id")
            if candidate is not None or not candidates:
                if type(candidate) is not str or _OUTPUT_ID.fullmatch(candidate) is None:
                    raise OutputError("output_binding_invalid")
                candidates.append(candidate)
    if not candidates or any(candidate != candidates[0] for candidate in candidates):
        raise OutputError("output_binding_invalid")
    return candidates[0]


def resume_render_file(
    step, context, pending_result, *, service_factory, resolve_inputs, build_step_result,
    build_failure, settings, user_id, cancel_requested=None,
):
    """Observe a pinned output without effects; operational read failures raise."""
    output_id = None
    record = None
    binding_verified = False
    try:
        version = getattr(context, "plan_contract_version", None)
        if type(version) is not int or version != 2:
            raise OutputError("output_contract_unsupported")
        if type(step) is not dict or step.get("capability_id") != "render_file":
            raise OutputError("output_binding_invalid")
        output_id = _saved_render_output_id(pending_result)
        if cancel_requested is not None and cancel_requested():
            raise OutputUnavailableError("output_cancelled")
        producer = context.result_producer(step)
        if (
            type(producer) is not ProducerIdentity or producer.user_id != user_id
            or producer.step_id != step.get("step_id") or producer.capability_id != "render_file"
        ):
            raise OutputError("output_binding_invalid")
        service = service_factory(context, settings=settings, user_id=user_id)
        if not isinstance(service, OrchestrationRenderingService):
            raise OutputError("output_service_required")
        record = service._read_metadata(service.store.get, output_id)
        if (
            record["producer"] != producer.to_dict()
            or record["identity"]["approved_work_id"] != (
                getattr(context, "approved_work_id", None) or producer.run_id
            )
        ):
            raise OutputUnavailableError("output_binding_invalid")
        if record.get("step_signature") != _step_signature(step):
            raise OutputUnavailableError("output_plan_changed")
        file_name, export_request = _render_request(step)
        extensions = orchestration_artifact_file_extensions(record["render_spec"]["output_format"])
        if type(export_request.output_format) is not str or export_request.output_format not in extensions:
            raise OutputUnavailableError("output_binding_invalid")
        requested = asdict(export_request)
        requested["output_format"] = record["render_spec"]["output_format"]
        if requested["columns"] is not None:
            requested["columns"] = list(requested["columns"])
        if (
            any(requested[name] != record["render_spec"][name] for name in _REQUEST_FIELDS)
            or _file_name(file_name, extensions) != record["file_name"]
        ):
            raise OutputUnavailableError("output_binding_invalid")
        if parse_time(getattr(context, "execution_deadline_at", None)).isoformat() != record["deadline_at"]:
            raise OutputError("output_deadline_invalid")
        run = service._read_metadata(service.store.current_run, record)
        if record["state"] != "completed" and (
            run.get("cancellation_requested_at") or run.get("status") in {"cancelled", "canceled"}
        ):
            raise OutputUnavailableError("output_cancelled")
        if run.get("execution_deadline_at") and parse_time(run["execution_deadline_at"]) < parse_time(
            record["deadline_at"],
        ):
            raise OutputError("output_deadline_invalid")
        readers = resolve_inputs(step, context)
        if type(readers) is not dict or set(readers) != {"source"}:
            raise OutputError("output_binding_invalid")
        reader = readers["source"]
        if not isinstance(reader, OrchestrationResultReader) or type(reader.reference) is not ResultRef:
            raise OutputError("output_binding_invalid")
        if reader.reference.to_dict() != record["source_ref"]:
            raise OutputUnavailableError("output_binding_invalid")
        binding_verified = True
        record = service._authorize_read_record(record)
        if service._pending_deadline_exceeded(record):
            raise OutputError("output_deadline_exceeded")
        return _render_step_result(
            public_output(record), record, build_step_result=build_step_result, build_failure=build_failure,
        )
    except Exception as exc:
        code, retryable = output_failure(exc)
        outputs = []
        if code in {"output_cancelled", "output_deleted"}:
            result = build_step_result(status="cancelled", summary="This file was cancelled.")
        else:
            authority = external_authority_failure(exc)
            if authority is not None:
                raise authority[0]
            if output_storage_failure(exc) is not None:
                raise_output_read_infrastructure_failure(exc)
            if not isinstance(exc, (
                OutputError, OutputUnavailableError, ResultContractError, ResultUnavailableError, DocumentHeldError,
            )):
                raise
            raise_output_read_infrastructure_failure(exc)
            unavailable_code = _source_visibility_code(exc) if binding_verified else None
            if unavailable_code is not None:
                output = public_output(record, unavailable_code=unavailable_code)
                outputs = [output]
                result = build_step_result(
                    status="failed", summary=output["message"], failure=build_failure("result_unavailable"),
                )
            else:
                result = build_step_result(
                    status="failed", summary="This file is unavailable.",
                    failure=build_failure("step_failed"), error="This file is unavailable.",
                )
        result["outputs"] = outputs
        result["output_error"] = {"code": code, "retryable": retryable}
        return result


def execute_render_file(
    step, context, *, service_factory, resolve_inputs, build_step_result,
    build_failure, settings, user_id, cancel_requested=None, observe_render=None,
):
    """Injected adapter seam returning the real shared StepResult, without cycles.

    ``cancel_requested`` also bounds the attempt: it is consulted on the attempt's paced full
    checks until the file is staged. ``observe_render(facts)`` receives its diagnostics.
    """
    output = None
    try:
        if getattr(context, "plan_contract_version", None) != 2:
            raise OutputError("output_contract_unsupported")
        if cancel_requested is not None and cancel_requested():
            return build_step_result(status="cancelled", summary="This file was cancelled.")
        readers = resolve_inputs(step, context)
        if type(readers) is not dict or len(readers) != 1:
            raise OutputError("output_binding_invalid")
        reader = next(iter(readers.values()))
        if not isinstance(reader, OrchestrationResultReader):
            raise OutputError("output_binding_invalid")
        source_ref = reader.reference
        if type(source_ref) is not ResultRef:
            raise OutputError("output_binding_invalid")
        file_name, export_request = _render_request(step)
        service = service_factory(context, settings=settings, user_id=user_id)
        producer = context.result_producer(step)
        output = service.ensure_output(
            producer=producer, source_ref=source_ref,
            export_request=export_request,
            file_name=file_name,
            approved_work_id=getattr(context, "approved_work_id", None) or producer.run_id,
            deadline_at=context.execution_deadline_at,
        )
        output = service.render_attempt(
            output["output_id"], stop=cancel_requested, observe=observe_render,
        )
        record = service.store.get(output["output_id"]) if output["state"] == "completed" else None
        return _render_step_result(
            output, record, build_step_result=build_step_result, build_failure=build_failure,
        )
    except Exception as exc:
        code, retryable = output_failure(exc)
        if code == "output_cancelled":
            result = build_step_result(status="cancelled", summary="This file was cancelled.")
            result["outputs"] = []
            result["output_error"] = {"code": code, "retryable": False}
            return result
        uncertain_authority = external_authority_failure(exc) is not None or (
            isinstance(exc, ScreeningError) and not isinstance(exc, DocumentHeldError)
        )
        if retryable and output is not None:
            result = build_step_result(
                status="waiting", summary="The file's saved state is being checked.",
                wait={
                    "kind": "orchestration_output", "output_id": output["output_id"],
                    "error_code": code,
                },
            )
            result["outputs"] = [] if uncertain_authority or output["state"] == "completed" else [output]
            result["output_error"] = {"code": code, "retryable": retryable}
            return result
        result = build_step_result(
            status="failed", summary="This file could not be created.",
            failure=build_failure("step_failed"), error="This file could not be created.",
        )
        result["output_error"] = {"code": code, "retryable": retryable}
        return result

# functions_document_transform_sources.py
"""Actor-bound native reference inputs, not another source store.

Version: 0.261.321

Owners inject fresh document/conversation readers and the existing generated-file
authorization and byte transport. Only safe identity/format fields leave this module;
private Blob locations never become planner handles. Retained outputs keep their
container's authorization, not the permissions of the documents that produced them.
"""

from copy import deepcopy
import hashlib
import math
import posixpath
import re

from functions_document_transform import DocumentTransformError, GuardedPackage, SOURCE_FORMATS
from functions_message_deletion import is_soft_deleted_message


TEMPLATE_EXTENSIONS = frozenset({".dotx", ".potx"})
OFFICE_REFERENCE_MIME_TYPES = {
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".dotx": "application/vnd.openxmlformats-officedocument.wordprocessingml.template",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".potx": "application/vnd.openxmlformats-officedocument.presentationml.template",
}
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
MAX_REFERENCE_CANDIDATES = 15


def _error(code="source_unavailable"):
    raise DocumentTransformError(code, "The reference file is unavailable or has changed.")


def _handle(value):
    if type(value) is not dict:
        _error("invalid_reference")
    kind = value.get("kind")
    fields = (
        {"kind", "document_id"} if kind == "document"
        else {"kind", "conversation_id", "message_id"} if kind == "artifact" else set()
    )
    if not fields or set(value) != fields or any(
        type(value[key]) is not str or not _IDENTIFIER.fullmatch(value[key])
        for key in fields - {"kind"}
    ):
        _error("invalid_reference")
    return deepcopy(value)


def _reference(value):
    if type(value) is dict and "handle" in value:
        if (
            set(value) != {"handle", "content_sha256", "extension"}
            or type(value["content_sha256"]) is not str or not _DIGEST.fullmatch(value["content_sha256"])
            or type(value["extension"]) is not str or value["extension"] not in SOURCE_FORMATS
        ):
            _error("invalid_reference")
        return _handle(value["handle"]), value
    return _handle(value), None


def _file_name(record):
    metadata = record.get("metadata") or {}
    return str(
        record.get("file_name") or record.get("filename")
        or metadata.get("file_name") or metadata.get("filename") or ""
    ).replace("\\", "/").rsplit("/", 1)[-1][:500]


def native_template_pages(content, extension):
    """Validate a template and extract inert XML text without DI or adapter initialization.

    Text in headers, layouts, notes, alternative text and metadata is included in screening
    even when it is not part of the template's visible body. Empty templates have a
    metadata-only structural unit, not invented narrative text or a successful RAG chunk.
    """
    if extension not in TEMPLATE_EXTENSIONS:
        _error("unsupported_format")
    package = GuardedPackage(content, extension)
    pages = []
    supplemental = []
    if extension == ".dotx":
        visible_parts = [package.main_part]
    else:
        relationships = {
            item["id"]: item["target"] for item in package.relationships(package.main_part)
            if not item["external"] and item["type"].endswith("/slide")
        }
        visible_parts = [
            relationships[value] for element in package.parse_xml(package.main_part).iter()
            if isinstance(element.tag, str) and element.tag.rsplit("}", 1)[-1] == "sldId"
            for attribute, value in element.attrib.items()
            if attribute.endswith("}id") and value in relationships
        ]
    visible_text = {}
    for name in sorted(package.files):
        if not name.endswith(".xml") or name == "[Content_Types].xml":
            continue
        root = package.parse_xml(name)
        texts = []
        for element in root.iter():
            local_name = element.tag.rsplit("}", 1)[-1] if isinstance(element.tag, str) else ""
            if local_name in {"t", "delText", "instrText", "delInstrText"} and element.text:
                texts.append(element.text)
            for attribute in ("descr", "title"):
                if element.get(attribute):
                    texts.append(element.get(attribute))
        text = "\n".join(texts).strip()
        if name in visible_parts:
            visible_text[name] = text
        else:
            package_text = "\n".join(
                value.strip() for value in root.itertext() if value.strip()
            )
            if package_text or text:
                supplemental.append("\n".join(value for value in (package_text, text) if value))
    pages = [
        {"page_number": position, "content": visible_text.get(name, "")}
        for position, name in enumerate(visible_parts, start=1)
    ]
    return pages, supplemental, {
        "extension": extension, "package_parts": len(package.files),
        "source_role": "reference_template", "narrative_indexed": any(page["content"] for page in pages),
    }


class DocumentTransformSources:
    """Exact reference reader and planning metadata over the existing input boundaries."""

    def __init__(
        self, *, user_id, conversation_id, read_conversation, read_document_metadata,
        read_document_bytes, authorize_artifact, open_artifact_stream, list_artifacts=None,
        max_source_bytes=100 * 1024 * 1024,
    ):
        if not user_id or not conversation_id or any(not callable(reader) for reader in (
            read_conversation, read_document_metadata, read_document_bytes, authorize_artifact, open_artifact_stream,
        )) or type(max_source_bytes) is not int or max_source_bytes < 1:
            _error("invalid_source_services")
        if list_artifacts is not None and not callable(list_artifacts):
            _error("invalid_source_services")
        self.user_id = user_id
        self.conversation_id = conversation_id
        self.read_conversation = read_conversation
        self.read_document_metadata = read_document_metadata
        self.read_document_bytes = read_document_bytes
        self.authorize_artifact = authorize_artifact
        self.open_artifact_stream = open_artifact_stream
        self.list_artifacts = list_artifacts
        self.max_source_bytes = max_source_bytes

    def _conversation(self):
        conversation = self.read_conversation(self.conversation_id)
        if (
            not isinstance(conversation, dict) or conversation.get("id") != self.conversation_id
            or conversation.get("user_id") != self.user_id
            or conversation.get("deleted") or conversation.get("orchestration_deleted")
        ):
            raise PermissionError("Reference conversation not found or access denied.")
        return conversation

    def _artifact(self, handle):
        self._conversation()
        if handle["conversation_id"] != self.conversation_id:
            raise PermissionError("Reference file is not part of this conversation.")
        artifact = self.authorize_artifact(self.user_id, self.conversation_id, handle["message_id"])
        metadata = artifact.get("metadata") if isinstance(artifact, dict) else None
        if (
            not isinstance(metadata, dict) or artifact.get("id") != handle["message_id"]
            or artifact.get("conversation_id") != self.conversation_id or artifact.get("role") != "file"
            or metadata.get("is_generated_chat_artifact") is not True
            or is_soft_deleted_message(artifact) or artifact.get("content_unavailable")
            or metadata.get("masked") or metadata.get("masked_ranges") or artifact.get("masked")
            or type(metadata.get("generated_artifact_content_sha256")) is not str
            or not _DIGEST.fullmatch(metadata["generated_artifact_content_sha256"])
            or type(metadata.get("generated_artifact_size_bytes")) is not int
            or not 0 < metadata["generated_artifact_size_bytes"] <= self.max_source_bytes
        ):
            _error()
        return artifact

    def _metadata(self, record, handle):
        file_name = _file_name(record)
        extension = posixpath.splitext(file_name.lower())[1]
        if extension not in SOURCE_FORMATS:
            _error("native_source_unavailable")
        metadata = {
            "handle": deepcopy(handle), "file_name": file_name, "extension": extension,
            "output_format": SOURCE_FORMATS[extension], "source_role": "reference",
            "is_template": extension in TEMPLATE_EXTENSIONS,
        }
        if handle["kind"] == "document":
            if record.get("id") != handle["document_id"]:
                _error()
            scope = (
                "public" if record.get("public_workspace_id")
                else "group" if record.get("group_id") else "personal"
            )
            metadata.update({
                "scope": scope,
                "scope_id": record.get("public_workspace_id") or record.get("group_id") or record.get("user_id"),
                "source_kind": "narrative", "version": record.get("version"),
            })
        else:
            metadata["content_sha256"] = record["metadata"]["generated_artifact_content_sha256"]
        return metadata

    def describe_reference(self, reference):
        """Safe metadata for one currently authorized handle; no paths, URLs or credentials."""
        handle, bound = _reference(reference)
        self._conversation()
        record = (
            self.read_document_metadata(handle["document_id"])
            if handle["kind"] == "document" else self._artifact(handle)
        )
        metadata = self._metadata(record, handle)
        if bound is not None and metadata["extension"] != bound["extension"]:
            _error("source_changed")
        source = None
        if handle["kind"] == "document":
            source = {
                "document_id": handle["document_id"],
                "scope": metadata["scope"], "scope_id": metadata["scope_id"],
                "source_version": record.get("version") if record.get("version") is not None else record.get("source_version"),
                "source_revision": record.get("_etag") or record.get("updated_at") or record.get("last_updated"),
                "authorization_status": "authorized",
            }
            if type(source["scope_id"]) is not str or not source["scope_id"].strip() or any(
                value is not None and (
                    isinstance(value, bool) or not isinstance(value, (str, int, float))
                    or (isinstance(value, float) and not math.isfinite(value))
                )
                for value in (source["source_version"], source["source_revision"])
            ):
                _error("source_unavailable")
        metadata["source"] = source
        return metadata

    def resolve_reference(self, reference):
        """Resolve one live input to a filename and locator-free document provenance."""
        metadata = self.describe_reference(reference)
        return {"file_name": metadata["file_name"], "source": metadata["source"]}

    def read_reference(self, reference):
        """``handle`` for inspection or digest/extension-bound ``reference`` for replay."""
        handle, bound = _reference(reference)
        self._conversation()
        if handle["kind"] == "document":
            record, content = self.read_document_bytes(handle["document_id"])
            metadata = self._metadata(record, handle)
        else:
            record = self._artifact(handle)
            metadata = self._metadata(record, handle)

            def check():
                current = self._artifact(handle)
                if (
                    current.get("_etag") != record.get("_etag")
                    or current.get("blob_container") != record.get("blob_container")
                    or current.get("blob_path") != record.get("blob_path")
                    or current["metadata"].get("generated_artifact_content_sha256") != metadata["content_sha256"]
                    or current["metadata"].get("generated_artifact_size_bytes")
                    != record["metadata"]["generated_artifact_size_bytes"]
                    or self._metadata(current, handle)["extension"] != metadata["extension"]
                ):
                    _error("source_changed")
                return True

            with self.open_artifact_stream(record, check=check) as stream:
                content = stream.read(self.max_source_bytes + 1)
            check()
            if (
                len(content) != record["metadata"]["generated_artifact_size_bytes"]
                or hashlib.sha256(content).hexdigest() != metadata["content_sha256"]
            ):
                _error("source_changed")
        self._conversation()
        if type(content) is not bytes or len(content) > self.max_source_bytes:
            _error("source_too_large")
        if bound is not None and (
            metadata["extension"] != bound["extension"]
            or hashlib.sha256(content).hexdigest() != bound["content_sha256"]
        ):
            _error("source_changed")
        GuardedPackage(content, metadata["extension"])
        return content

    def planning_candidates(self, document_ids=()):
        """Offer selected native documents and bounded live files from this conversation."""
        self._conversation()
        candidates = []
        for document_id in dict.fromkeys(document_ids):
            if len(candidates) >= MAX_REFERENCE_CANDIDATES:
                break
            handle = _handle({"kind": "document", "document_id": document_id})
            record = self.read_document_metadata(document_id)
            if posixpath.splitext(_file_name(record).lower())[1] in SOURCE_FORMATS:
                candidates.append(self._metadata(record, handle))
        if self.list_artifacts is not None:
            for message in self.list_artifacts(self.conversation_id):
                if len(candidates) >= MAX_REFERENCE_CANDIDATES:
                    break
                if not isinstance(message, dict) or posixpath.splitext(_file_name(message).lower())[1] not in SOURCE_FORMATS:
                    continue
                try:
                    handle = _handle({
                        "kind": "artifact", "conversation_id": self.conversation_id, "message_id": message.get("id"),
                    })
                    record = self._artifact(handle)
                except (PermissionError, LookupError, DocumentTransformError):
                    continue
                candidates.append(self._metadata(record, handle))
        return candidates

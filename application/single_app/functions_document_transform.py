# functions_document_transform.py
"""Bounded, model-independent document transformation contracts and package dispatch.

Callers supply authorized reference bytes; handles here are identities, not permission
decisions or storage locators. Adapters are trusted Python modules, loaded only on use.
They inspect a GuardedPackage and mutate its ``files`` mapping without rewriting parts
they do not edit. Model-produced operations are inert data, never code or XML queries.

Prepared wire shape: {schema_version: "document_transform_v1", output_format:
"docx"|"pptx", mode: "create_from_reference"|"refresh", reference: {handle:
{kind: "document", document_id} or {kind: "artifact", conversation_id, message_id},
content_sha256: lowercase SHA-256 of exact bytes, extension: ".docx"|".dotx"|".pptx"|
".potx"}, operations: [{op, target, text|source|clone_id?}], unresolved: [{target,
reason}]}. The schema function is authoritative about each operation's required fields.
Identifiers start with an ASCII letter/digit, contain only letters/digits/_.:-, and
have at most 128 characters. Inspection accepts the handle alone and binds its revision.
An optional check() may raise (preserved unchanged) or return False to cancel.

Adapter contract:
    inspect_package(package, *, limits, check) -> dict
        {targets: [{id, type, text?, ...}], layouts: [...], limitations: [...]}
    transform_package(package, prepared, *, limits, check, image_resolver) -> dict
        {applied: [{op_index, target, reason?}], unchanged: [...], skipped: [...],
         unresolved: [{target, reason}], warnings: [str], metadata: dict?}

An operation must have exactly one applied/unchanged/skipped outcome, identified by its
zero-based op_index. Missing outcomes become skipped, never assumed successes. Unchanged
may also contain untargeted {target, reason?} entries. Image resolvers are injected by the
authorized source owner and receive opaque asset tokens; adapters must not fetch URLs.
"""

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import importlib
import io
import json
import math
import posixpath
import re
from urllib.parse import unquote, urlsplit
import zipfile
import zlib

from jsonschema import Draft202012Validator
from lxml import etree

from functions_document_merge_core import DocumentMergeError, fixed_zip_entry, guard_ooxml_package
from functions_ooxml_package_guard import content_type_of, is_office_xml_part


DOCUMENT_TRANSFORM_SCHEMA_VERSION = "document_transform_v1"
DOCUMENT_INSPECTION_VERSION = "document-inspection-v1"
DOCUMENT_TRANSFORM_REPORT_VERSION = "document-transformation-report-v1"
SOURCE_FORMATS = {".docx": "docx", ".dotx": "docx", ".pptx": "pptx", ".potx": "pptx"}
MEDIA_TYPES = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}
_MAIN_TYPES = {
    ".docx": MEDIA_TYPES["docx"] + ".main+xml",
    ".dotx": "application/vnd.openxmlformats-officedocument.wordprocessingml.template.main+xml",
    ".pptx": MEDIA_TYPES["pptx"] + ".main+xml",
    ".potx": "application/vnd.openxmlformats-officedocument.presentationml.template.main+xml",
}
_CT = "{http://schemas.openxmlformats.org/package/2006/content-types}"
_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"
_OFFICE_REL_NAMESPACES = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "http://purl.oclc.org/ooxml/officeDocument/relationships",
)
_WORD_NAMESPACES = (
    "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "http://purl.oclc.org/ooxml/wordprocessingml/main",
)
_IDENTIFIER_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$"
_IDENTIFIER = re.compile(_IDENTIFIER_PATTERN)
_PROGRAM_FIELD = re.compile(r"^\s*DDE(?:AUTO)?(?!\w)", re.IGNORECASE)
_ADAPTERS = {
    "docx": "functions_document_transform_docx",
    "pptx": "functions_document_transform_pptx",
}


class DocumentTransformError(ValueError):
    """A stable user-safe failure; never includes source XML or parser error text."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


class DocumentTransformCancelled(DocumentTransformError):
    def __init__(self):
        super().__init__("cancelled", "Document transformation was cancelled.")


@dataclass(frozen=True)
class DocumentTransformLimits:
    """Positive ceilings shared with adapters; callers may reduce or raise them."""

    max_source_bytes: int = 100 * 1024 * 1024
    max_output_bytes: int = 100 * 1024 * 1024
    max_package_entries: int = 10_000
    max_package_uncompressed_bytes: int = 256 * 1024 * 1024
    max_part_bytes: int = 32 * 1024 * 1024
    max_xml_nodes: int = 500_000
    max_operations: int = 500
    max_targets: int = 5000
    max_text_chars: int = 100_000
    max_json_bytes: int = 4 * 1024 * 1024
    max_json_nodes: int = 100_000
    max_json_depth: int = 12

    def __post_init__(self):
        for name in self.__dataclass_fields__:
            if type(getattr(self, name)) is not int or getattr(self, name) < 1:
                raise ValueError(f"{name} must be a positive integer.")


def _limits(value):
    if value is None:
        return DocumentTransformLimits()
    if not isinstance(value, DocumentTransformLimits):
        raise DocumentTransformError("invalid_limits", "Invalid document transformation limits.")
    return value


def _check(check):
    # Exceptions raised by a caller's authorization/cancellation check pass through.
    if check is not None and check() is False:
        raise DocumentTransformCancelled()


class _Callback:
    """Keep caller failures distinct from ZIP/parser failures with the same exception type."""

    def __init__(self, callback):
        self.callback = callback
        self.error = None

    def __call__(self):
        try:
            _check(self.callback)
        except Exception as exc:
            self.error = exc
            raise


def _invalid(code):
    raise DocumentTransformError(code, "Invalid document transformation data.")


def _plain_json(value, limits, code, check=None):
    """Bound before copying or schema traversal, including cycles, depth and non-JSON values."""
    nodes = 0
    characters = 0

    def visit(item, depth):
        nonlocal nodes, characters
        nodes += 1
        if nodes % 64 == 1:
            _check(check)
        if nodes > limits.max_json_nodes or depth > limits.max_json_depth:
            raise DocumentTransformError("resource_limit", "Document transformation data exceeds its limits.")
        if type(item) is str:
            characters += len(item)
            if len(item) > limits.max_text_chars or any(
                0xD800 <= ord(char) <= 0xDFFF or ord(char) < 32 and char not in "\t\n\r"
                for char in item
            ):
                _invalid(code)
            if characters > limits.max_json_bytes:
                raise DocumentTransformError("resource_limit", "Document transformation data exceeds its limits.")
        elif type(item) is dict:
            for key, child in item.items():
                if type(key) is not str:
                    _invalid(code)
                visit(key, depth + 1)
                visit(child, depth + 1)
        elif type(item) is list:
            for child in item:
                visit(child, depth + 1)
        elif item is not None and type(item) not in (bool, int, float):
            _invalid(code)
        elif type(item) is float and not math.isfinite(item):
            _invalid(code)
        elif type(item) is int and item.bit_length() > 64:
            _invalid(code)

    visit(value, 0)
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    if len(encoded) > limits.max_json_bytes:
        raise DocumentTransformError("resource_limit", "Document transformation data exceeds its limits.")
    return deepcopy(value)


def _object(properties, required=None):
    return {
        "type": "object", "additionalProperties": False, "properties": properties,
        "required": list(properties) if required is None else required,
    }


def _schema(limits):
    identifier = {
        "type": "string", "pattern": _IDENTIFIER_PATTERN, "maxLength": 128,
        "not": {"pattern": r"[\r\n]"},
    }
    text = {"type": "string", "maxLength": limits.max_text_chars}
    handle = {"oneOf": [
        _object({"kind": {"const": "document"}, "document_id": identifier}),
        _object({"kind": {"const": "artifact"}, "conversation_id": identifier, "message_id": identifier}),
    ]}
    operations = []
    for name, extra in (
        ("replace_text", {"text": text}), ("replace_image", {"source": identifier}),
        ("clone", {"clone_id": identifier}), ("remove", {}), ("append_text", {"text": text}),
    ):
        operations.append(_object({"op": {"const": name}, "target": identifier, **extra}))
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        **_object({
            "schema_version": {"const": DOCUMENT_TRANSFORM_SCHEMA_VERSION},
            "output_format": {"enum": ["docx", "pptx"]},
            "mode": {"enum": ["create_from_reference", "refresh"]},
            "reference": _object({
                "handle": handle,
                "content_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$", "maxLength": 64},
                "extension": {"enum": list(SOURCE_FORMATS)},
            }),
            "operations": {"type": "array", "maxItems": limits.max_operations, "items": {"oneOf": operations}},
            "unresolved": {
                "type": "array", "maxItems": limits.max_operations,
                "items": _object({"target": identifier, "reason": {**text, "minLength": 1}}),
            },
        }),
    }


def get_document_transform_schema():
    """Return a fresh bounded JSON Schema for the retained document_transform_v1 profile."""
    return _schema(DocumentTransformLimits())


def validate_document_transform(value, *, limits=None, check=None):
    """Return a detached validated wire dict, or raise DocumentTransformError."""
    limits = _limits(limits)
    value = _plain_json(value, limits, "invalid_transform", check)
    if not Draft202012Validator(_schema(limits)).is_valid(value):
        _invalid("invalid_transform")
    if SOURCE_FORMATS[value["reference"]["extension"]] != value["output_format"]:
        _invalid("format_mismatch")
    clone_ids = [op["clone_id"] for op in value["operations"] if op["op"] == "clone"]
    if len(clone_ids) != len(set(clone_ids)):
        _invalid("invalid_transform")
    _check(check)
    return value


def register_document_transform_adapter(output_format, adapter):
    """Register a trusted adapter/module name for a supported output, returning the previous one."""
    if output_format not in MEDIA_TYPES or (
        not isinstance(adapter, str) and not all(
            callable(getattr(adapter, name, None)) for name in ("inspect_package", "transform_package")
        )
    ):
        _invalid("invalid_adapter")
    previous = _ADAPTERS.get(output_format)
    _ADAPTERS[output_format] = adapter
    return previous


def _adapter(output_format):
    adapter = _ADAPTERS[output_format]
    if isinstance(adapter, str):
        # Format libraries must not initialize when this standalone module is imported.
        try:
            adapter = importlib.import_module(adapter)
        except ModuleNotFoundError as exc:
            if exc.name != _ADAPTERS[output_format]:
                raise
            raise DocumentTransformError("adapter_unavailable", "This document format adapter is unavailable.") from exc
    if not all(callable(getattr(adapter, name, None)) for name in ("inspect_package", "transform_package")):
        _invalid("invalid_adapter")
    return adapter


def _part_name(name):
    if (
        type(name) is not str or not name or len(name) > 512 or name.startswith("/")
        or "\\" in name or ":" in name or "%" in name or "?" in name or "#" in name
        or any(ord(char) < 32 for char in name)
        or any(segment in ("", ".", "..") for segment in name.split("/"))
    ):
        raise DocumentTransformError("invalid_package", "The document has invalid internal part names.")
    return name


def _parse_xml(data, *, limits, check):
    try:
        parser = etree.XMLParser(
            resolve_entities=False, load_dtd=False, no_network=True, huge_tree=False,
            remove_blank_text=False, recover=False,
        )
        root = etree.fromstring(data, parser)
    except (etree.LxmlError, ValueError, TypeError) as exc:
        raise DocumentTransformError("invalid_xml", "The document contains invalid XML.") from exc
    if root.getroottree().docinfo.doctype:
        raise DocumentTransformError("unsafe_xml", "The document contains unsafe XML.")
    for position, _element in enumerate(root.iter(), start=1):
        if position % 64 == 1:
            _check(check)
        if position > limits.max_xml_nodes:
            raise DocumentTransformError("resource_limit", "An XML document part exceeds its node limit.")
    return root


def _program_fields(root, check):
    """Detect split complex DDE fields as well as simple fields in any Word XML part."""
    for namespace in _WORD_NAMESPACES:
        prefix = f"{{{namespace}}}"
        codes = []
        for position, element in enumerate(root.iter()):
            if position % 64 == 0:
                _check(check)
            if element.tag == prefix + "fldSimple" and _PROGRAM_FIELD.match(element.get(prefix + "instr", "")):
                return True
            if element.tag == prefix + "fldChar":
                kind = element.get(prefix + "fldCharType")
                if kind == "begin":
                    codes.append([])
                elif kind in ("separate", "end") and codes:
                    if codes[-1] is not None and _PROGRAM_FIELD.match("".join(codes[-1])):
                        return True
                    codes[-1] = None
                    if kind == "end":
                        codes.pop()
            elif element.tag in (prefix + "instrText", prefix + "delInstrText"):
                for code in codes:
                    if code is not None:
                        code.append(element.text or "")
        if any(code is not None and _PROGRAM_FIELD.match("".join(code)) for code in codes):
            return True
    return False


class _BoundedBuffer(io.BytesIO):
    def __init__(self, ceiling):
        super().__init__()
        self.ceiling = ceiling

    def write(self, data):
        if self.tell() + len(data) > self.ceiling:
            raise DocumentTransformError("output_too_large", "The transformed document exceeds its size limit.")
        return super().write(data)


class GuardedPackage:
    """In-memory OPC parts with safe parsing, relationship validation and deterministic packing."""

    def __init__(self, content, extension, *, limits=None, check=None):
        self.limits = _limits(limits)
        self.check = _Callback(check)
        check = self.check
        self.extension = extension
        if extension not in SOURCE_FORMATS:
            _invalid("unsupported_format")
        _check(check)
        if type(content) is not bytes:
            _invalid("invalid_content")
        if len(content) > self.limits.max_source_bytes:
            raise DocumentTransformError("source_too_large", "The reference document exceeds its size limit.")
        # Reuse the existing guard's encoding, prolog and package-budget checks.
        try:
            guard_ooxml_package(content, self, self.limits, "Office document", check=lambda: _check(check))
        except DocumentMergeError as exc:
            if check.error is exc:
                raise
            raise DocumentTransformError(exc.code, "The reference document is not a safe readable Office package.") from exc
        self.files = {}
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                seen = set()
                for entry in archive.infolist():
                    _check(check)
                    # ZipInfo normalizes backslashes on Windows and truncates NULs;
                    # validate the original archive name, not just its normalized alias.
                    original_name = entry.orig_filename.rstrip("/") if entry.is_dir() else entry.orig_filename
                    _part_name(original_name)
                    name = entry.filename.rstrip("/") if entry.is_dir() else entry.filename
                    _part_name(name)
                    if name.casefold() in seen:
                        raise DocumentTransformError("invalid_package", "The document has duplicate internal parts.")
                    seen.add(name.casefold())
                    if entry.flag_bits & 1:
                        raise DocumentTransformError("encrypted_document", "Encrypted documents cannot be transformed.")
                    if entry.is_dir():
                        continue
                    if entry.file_size > self.limits.max_part_bytes:
                        raise DocumentTransformError("resource_limit", "An internal document part exceeds its size limit.")
                    self.files[name] = archive.read(entry)
        except (zipfile.BadZipFile, RuntimeError, NotImplementedError, EOFError, OSError, zlib.error) as exc:
            if check.error is exc:
                raise
            raise DocumentTransformError("invalid_package", "The document package cannot be read.") from exc
        self.limitations = []
        self._detach_linked_templates()
        self.validate()

    def display_name(self):
        return "The reference document"

    @staticmethod
    def rels_name(part_name):
        if not part_name:
            return "_rels/.rels"
        directory, name = posixpath.split(part_name)
        return posixpath.join(directory, "_rels", f"{name}.rels")

    def parse_xml(self, part_name):
        _check(self.check)
        data = self.files.get(part_name)
        if type(data) is not bytes or len(data) > self.limits.max_part_bytes:
            raise DocumentTransformError("invalid_package", "An internal document part cannot be read.")
        return _parse_xml(data, limits=self.limits, check=self.check)

    def write_xml(self, part_name, root):
        _part_name(part_name)
        _check(self.check)
        if root.getroottree().docinfo.doctype:
            raise DocumentTransformError("unsafe_xml", "The document contains unsafe XML.")
        data = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
        if len(data) > self.limits.max_part_bytes:
            raise DocumentTransformError("resource_limit", "An internal document part exceeds its size limit.")
        self.files[part_name] = data

    def _detach_linked_templates(self):
        """Word's remembered template location is not needed in a self-contained output."""
        if SOURCE_FORMATS[self.extension] != "docx":
            return
        for name in list(self.files):
            if not name.endswith(".rels") or name == "_rels/.rels":
                continue
            root = self.parse_xml(name)
            detached = [
                element for element in root
                if element.tag == _REL + "Relationship" and element.get("TargetMode") == "External"
                and element.get("Type", "").lower().endswith("/attachedtemplate")
            ]
            if not detached:
                continue
            directory, base = posixpath.split(name)
            if posixpath.basename(directory) != "_rels":
                _invalid("invalid_relationship")
            owner = posixpath.join(posixpath.dirname(directory), base[:-5])
            owner_root = self.parse_xml(owner)
            ids = {element.get("Id") for element in detached}
            changed = False
            for element in list(owner_root.iter()):
                if not isinstance(element.tag, str) or not element.tag.endswith("}attachedTemplate"):
                    continue
                if any(element.get(f"{{{namespace}}}id") in ids for namespace in _OFFICE_REL_NAMESPACES):
                    element.getparent().remove(element)
                    changed = True
            for element in detached:
                root.remove(element)
            self.write_xml(name, root)
            if changed:
                self.write_xml(owner, owner_root)
            self.limitations.append(
                "The external Word template link was removed; embedded formatting remains available."
            )

    def _types(self):
        root = self.parse_xml("[Content_Types].xml")
        if root.tag != _CT + "Types":
            _invalid("invalid_package")
        defaults, overrides = {}, {}
        names = {name.lower() for name in self.files}
        for position, element in enumerate(root):
            if position % 64 == 0:
                _check(self.check)
            if element.tag == _CT + "Default":
                key = (element.get("Extension") or "").lower()
                destination = defaults
                if not key or "/" in key or "\\" in key:
                    _invalid("invalid_package")
            elif element.tag == _CT + "Override":
                name = element.get("PartName", "")
                if not name.startswith("/"):
                    _invalid("invalid_package")
                key = _part_name(name[1:]).lower()
                destination = overrides
                if key not in names:
                    _invalid("invalid_package")
            else:
                continue
            content_type = element.get("ContentType", "")
            if key in destination or not content_type:
                _invalid("invalid_package")
            destination[key] = content_type
        return defaults, overrides

    def content_type(self, part_name):
        return content_type_of(part_name, *self._types())

    def relationships(self, part_name=""):
        """Internal targets are decoded, root-relative part names; external URLs stay inert."""
        name = self.rels_name(part_name)
        if name not in self.files:
            return []
        root = self.parse_xml(name)
        if root.tag != _REL + "Relationships":
            _invalid("invalid_package")
        relationships = []
        ids = set()
        for position, element in enumerate(root):
            if position % 64 == 0:
                _check(self.check)
            if element.tag != _REL + "Relationship":
                continue
            rid, reltype, target = (element.get(key, "") for key in ("Id", "Type", "Target"))
            mode = element.get("TargetMode")
            if not rid or rid in ids or not reltype or not target or mode not in (None, "Internal", "External"):
                _invalid("invalid_relationship")
            ids.add(rid)
            external = mode == "External"
            try:
                parsed = urlsplit(target)
            except ValueError as exc:
                raise DocumentTransformError("invalid_relationship", "The document has an invalid relationship.") from exc
            if external:
                if parsed.scheme.lower() in ("javascript", "vbscript", "data"):
                    raise DocumentTransformError("active_content", "The document contains unsafe active content.")
            else:
                if parsed.scheme or parsed.netloc or parsed.query:
                    _invalid("invalid_relationship")
                path = unquote(parsed.path)
                target = posixpath.normpath(
                    path.lstrip("/") if path.startswith("/") else posixpath.join(posixpath.dirname(part_name), path)
                ) if path else part_name
                _part_name(target)
                if target not in self.files:
                    raise DocumentTransformError("invalid_relationship", "The document has a missing related part.")
            if any(token in reltype.lower() for token in ("vbaproject", "activex")) or (
                external and reltype.lower().endswith("/attachedtemplate")
            ):
                raise DocumentTransformError("active_content", "The document contains unsafe active content.")
            relationships.append({"id": rid, "type": reltype, "target": target, "external": external})
        return relationships

    def validate(self):
        """Check both original and changed parts without sanitizing or reserializing untouched XML."""
        _check(self.check)
        if len(self.files) > self.limits.max_package_entries:
            raise DocumentTransformError("resource_limit", "The document has too many internal parts.")
        total = 0
        seen = set()
        for name, data in self.files.items():
            _check(self.check)
            _part_name(name)
            if name.casefold() in seen or type(data) is not bytes:
                _invalid("invalid_package")
            seen.add(name.casefold())
            total += len(data)
            if len(data) > self.limits.max_part_bytes or total > self.limits.max_package_uncompressed_bytes:
                raise DocumentTransformError("resource_limit", "The document package exceeds its resource limits.")
        defaults, overrides = self._types()
        main = [rel for rel in self.relationships() if rel["type"].endswith("/officeDocument") and not rel["external"]]
        if len(main) != 1:
            _invalid("invalid_package")
        self.main_part = main[0]["target"]
        self.main_content_type = content_type_of(self.main_part, defaults, overrides)
        if any(token in self.main_content_type.lower() for token in ("macroenabled", "vbaproject", "activex")):
            raise DocumentTransformError("active_content", "The document contains unsafe active content.")
        if self.main_content_type != _MAIN_TYPES[self.extension]:
            _invalid("format_mismatch")
        for name, data in self.files.items():
            _check(self.check)
            content_type = content_type_of(name, defaults, overrides)
            lowered = content_type.lower()
            if any(token in lowered or token in name.lower() for token in ("macroenabled", "vbaproject", "activex")):
                raise DocumentTransformError("active_content", "The document contains unsafe active content.")
            if name != "[Content_Types].xml" and not content_type:
                _invalid("invalid_package")
            if not is_office_xml_part(name, content_type):
                continue
            root = _parse_xml(data, limits=self.limits, check=self.check)
            if _program_fields(root, self.check):
                raise DocumentTransformError("active_content", "The document contains unsafe active content.")
            if name.endswith(".rels"):
                if name == "_rels/.rels":
                    owner = ""
                else:
                    directory, base = posixpath.split(name)
                    if posixpath.basename(directory) != "_rels":
                        _invalid("invalid_relationship")
                    owner = posixpath.join(posixpath.dirname(directory), base[:-5])
                    if owner not in self.files:
                        _invalid("invalid_relationship")
                self.relationships(owner)
                continue
            ids = {rel["id"] for rel in self.relationships(name)}
            for position, element in enumerate(root.iter()):
                if position % 64 == 0:
                    _check(self.check)
                if not isinstance(element.tag, str):
                    continue
                if element.get("action", "").strip().lower().startswith(("ppaction://program", "ppaction://macro")):
                    raise DocumentTransformError("active_content", "The document contains unsafe active content.")
                for attribute, rid in element.attrib.items():
                    if any(attribute.startswith(f"{{{namespace}}}") for namespace in _OFFICE_REL_NAMESPACES) and rid not in ids:
                        raise DocumentTransformError("invalid_relationship", "The document has a missing relationship.")
        main_root = self.parse_xml(self.main_part)
        namespaces = _WORD_NAMESPACES if SOURCE_FORMATS[self.extension] == "docx" else (
            "http://schemas.openxmlformats.org/presentationml/2006/main",
            "http://purl.oclc.org/ooxml/presentationml/main",
        )
        local = "document" if SOURCE_FORMATS[self.extension] == "docx" else "presentation"
        if main_root.tag not in {f"{{{namespace}}}{local}" for namespace in namespaces}:
            _invalid("invalid_package")

    def pack(self):
        """Return a bounded seekable buffer; template main content types normalize only here."""
        self.validate()
        output_format = SOURCE_FORMATS[self.extension]
        if self.extension in (".dotx", ".potx"):
            root = self.parse_xml("[Content_Types].xml")
            for element in root:
                if element.tag == _CT + "Override" and element.get("PartName") == f"/{self.main_part}":
                    element.set("ContentType", _MAIN_TYPES[f".{output_format}"])
                    break
            else:
                etree.SubElement(root, _CT + "Override", {
                    "PartName": f"/{self.main_part}", "ContentType": _MAIN_TYPES[f".{output_format}"],
                })
            self.write_xml("[Content_Types].xml", root)
            self.extension = f".{output_format}"
            self.validate()
        output = _BoundedBuffer(self.limits.max_output_bytes)
        try:
            with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
                for name in sorted(self.files):
                    _check(self.check)
                    archive.writestr(fixed_zip_entry(name), self.files[name])
            try:
                guard_ooxml_package(
                    output.getvalue(), self, self.limits, "Office document", check=lambda: _check(self.check),
                )
            except DocumentMergeError as exc:
                if self.check.error is exc:
                    raise
                raise DocumentTransformError(exc.code, "The transformed document is not a safe readable Office package.") from exc
            output.seek(0)
            _check(self.check)
            return output
        except BaseException:
            output.close()
            raise


def _inspection(adapter, package, limits, check):
    result = _plain_json(adapter.inspect_package(package, limits=limits, check=check), limits, "invalid_inspection", check)
    if type(result) is not dict:
        _invalid("invalid_inspection")
    result.setdefault("targets", [])
    result.setdefault("layouts", [])
    result.setdefault("limitations", [])
    if any(type(result[key]) is not list for key in ("targets", "layouts", "limitations")):
        _invalid("invalid_inspection")
    result["limitations"].extend(package.limitations)
    if len(result["targets"]) > limits.max_targets:
        raise DocumentTransformError("resource_limit", "The document has too many inspectable targets.")
    ids = set()
    for target in result["targets"]:
        if type(target) is not dict or not all(
            type(target.get(key)) is str and _IDENTIFIER.fullmatch(target[key]) for key in ("id", "type")
        ) or target["id"] in ids:
            _invalid("invalid_inspection")
        if "text" in target and type(target["text"]) is not str:
            _invalid("invalid_inspection")
        ids.add(target["id"])
    return result


def inspect_document(content, file_name, reference, *, limits=None, check=None):
    """Inspect authorized bytes; ``reference`` is a document/artifact handle, not a locator."""
    limits = _limits(limits)
    check = _Callback(check)
    extension = posixpath.splitext(str(file_name or "").lower())[1]
    if extension not in SOURCE_FORMATS:
        _invalid("unsupported_format")
    handle = _plain_json(reference, limits, "invalid_reference", check)
    handle_schema = _schema(limits)["properties"]["reference"]["properties"]["handle"]
    if not Draft202012Validator(handle_schema).is_valid(handle):
        _invalid("invalid_reference")
    package = GuardedPackage(content, extension, limits=limits, check=check)
    output_format = SOURCE_FORMATS[extension]
    result = _inspection(_adapter(output_format), package, limits, check)
    result.update({
        "version": DOCUMENT_INSPECTION_VERSION, "output_format": output_format,
        "reference": {"handle": handle, "content_sha256": hashlib.sha256(content).hexdigest(), "extension": extension},
    })
    return _plain_json(result, limits, "invalid_inspection", check)


def _report(raw, prepared, inspection, limits, check):
    raw = _plain_json(raw, limits, "invalid_report", check)
    if type(raw) is not dict or set(raw) - {"applied", "unchanged", "skipped", "unresolved", "warnings", "metadata"}:
        _invalid("invalid_report")
    report = {key: raw.get(key, []) for key in ("applied", "unchanged", "skipped", "unresolved", "warnings")}
    if any(type(value) is not list for value in report.values()):
        _invalid("invalid_report")
    if any(type(warning) is not str for warning in report["warnings"]):
        _invalid("invalid_report")
    if any(len(report[key]) > limits.max_targets + limits.max_operations for key in report):
        raise DocumentTransformError("resource_limit", "The document transformation report exceeds its limits.")
    covered = set()
    touched = set()
    operations = prepared["operations"]
    for status in ("applied", "unchanged", "skipped"):
        for entry in report[status]:
            if type(entry) is not dict or type(entry.get("target")) is not str or not _IDENTIFIER.fullmatch(entry["target"]):
                _invalid("invalid_report")
            if "reason" in entry and type(entry["reason"]) is not str:
                _invalid("invalid_report")
            index = entry.get("op_index")
            if index is None and status == "unchanged":
                continue
            if type(index) is not int or index < 0 or index >= len(operations) or index in covered:
                _invalid("invalid_report")
            if entry["target"] != operations[index]["target"]:
                _invalid("invalid_report")
            entry["op"] = operations[index]["op"]
            covered.add(index)
            touched.add(entry["target"])
    for index, operation in enumerate(operations):
        if index not in covered:
            report["skipped"].append({
                "op_index": index, "op": operation["op"], "target": operation["target"],
                "reason": "The adapter did not apply or report this operation.",
            })
            touched.add(operation["target"])
    unchanged = {entry["target"] for entry in report["unchanged"]}
    for target in inspection["targets"]:
        if target["id"] not in touched and target["id"] not in unchanged:
            report["unchanged"].append({"target": target["id"], "reason": "No operation requested."})
    for entry in report["unresolved"]:
        if (
            type(entry) is not dict or type(entry.get("target")) is not str
            or not _IDENTIFIER.fullmatch(entry["target"])
            or type(entry.get("reason")) is not str or not entry["reason"]
        ):
            _invalid("invalid_report")
    for entry in prepared["unresolved"]:
        if entry not in report["unresolved"]:
            report["unresolved"].append(deepcopy(entry))
    if not report["applied"]:
        report["warnings"].append("No changes applied; this output is an unchanged reference draft.")
    if prepared["mode"] == "create_from_reference" and (report["unchanged"] or report["skipped"]):
        report["warnings"].append("Unchanged reference material is not newly verified content.")
    report.update({
        "version": DOCUMENT_TRANSFORM_REPORT_VERSION, "mode": prepared["mode"],
        "output_format": prepared["output_format"], "reference": deepcopy(prepared["reference"]),
        "status": "draft" if report["skipped"] or report["unresolved"] or not report["applied"] else "transformed",
    })
    return _plain_json(report, limits, "invalid_report", check), raw.get("metadata", {})


class DocumentTransformResult:
    """Owns a seekable in-memory file stream. Use as a context manager or call close()."""

    def __init__(self, file_content, output_format, metadata):
        self.file_content = file_content
        self.size_bytes = file_content.seek(0, io.SEEK_END)
        file_content.seek(0)
        self.content_sha256 = hashlib.sha256(file_content.getbuffer()).hexdigest()
        self.output_format = output_format
        self.file_extension = f".{output_format}"
        self.media_type = MEDIA_TYPES[output_format]
        self.metadata = metadata

    def close(self):
        self.file_content.close()

    def __enter__(self):
        self.file_content.seek(0)
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.close()
        return False


def transform_document(content, prepared, *, limits=None, check=None, image_resolver=None):
    """Apply prepared edits to exact authorized bytes and return a context-managed result."""
    limits = _limits(limits)
    check = _Callback(check)
    prepared = validate_document_transform(prepared, limits=limits, check=check)
    if type(content) is not bytes:
        _invalid("invalid_content")
    if len(content) > limits.max_source_bytes:
        raise DocumentTransformError("source_too_large", "The reference document exceeds its size limit.")
    if hashlib.sha256(content).hexdigest() != prepared["reference"]["content_sha256"]:
        raise DocumentTransformError("reference_changed", "The reference document changed; prepare the edits again.")
    package = GuardedPackage(content, prepared["reference"]["extension"], limits=limits, check=check)
    adapter = _adapter(prepared["output_format"])
    inspection = _inspection(adapter, package, limits, check)
    _check(check)
    raw = adapter.transform_package(
        package, deepcopy(prepared), limits=limits, check=check, image_resolver=image_resolver,
    )
    if type(raw) is dict and package.limitations:
        raw = {**raw, "warnings": [*(raw.get("warnings") or []), *package.limitations]}
    _check(check)
    report, metadata = _report(raw, prepared, inspection, limits, check)
    if type(metadata) is not dict:
        _invalid("invalid_report")
    metadata = {**metadata, "transformation_report": report}
    output = package.pack()
    try:
        result = DocumentTransformResult(output, prepared["output_format"], metadata)
        report["output"] = {"content_sha256": result.content_sha256, "size_bytes": result.size_bytes}
        _check(check)
        return result
    except BaseException:
        output.close()
        raise


__all__ = [
    "DOCUMENT_TRANSFORM_SCHEMA_VERSION", "DOCUMENT_INSPECTION_VERSION", "DOCUMENT_TRANSFORM_REPORT_VERSION",
    "SOURCE_FORMATS", "MEDIA_TYPES", "DocumentTransformError", "DocumentTransformCancelled",
    "DocumentTransformLimits", "DocumentTransformResult", "GuardedPackage",
    "get_document_transform_schema", "validate_document_transform", "register_document_transform_adapter",
    "inspect_document", "transform_document",
]

# functions_ooxml_package_guard.py
"""Checks of an Office Open XML package's XML parts before any library parses them.

Version: 0.261.224
Implemented in: 0.261.224

Office Open XML requires its XML parts to be UTF-8 or UTF-16 and forbids document type
declarations in them, and Office refuses files that break either rule. A declaration is
how a hostile part asks an XML parser to read other files or to expand entities without
bound, and a part written or declared in another encoding could hide one, so file merges
refuse such packages before any library parses them, even though the parsers they use
don't resolve entities.

A part is checked when its name ends in ``.xml``, ``.rels`` or ``.vml``, or when the
package's ``[Content_Types].xml`` declares it an Office XML type, because Office and the
libraries choose how to read a part by its declared type, not its name. Pictures and web
pages, such as SVG images or imported HTML, may legitimately declare a document type and
are not checked. Only the prolog of each part is read: at most 4 KiB per part, read in
growing chunks, and at most 32 MiB for the whole package. Standard library only.
"""

import re
from xml.etree import ElementTree
import zipfile
import zlib

try:
    # zipfile imports lzma already when it is available.
    import lzma
    _LZMA_ERRORS = (lzma.LZMAError,)
except ImportError:  # pragma: no cover - only on Python builds without lzma
    _LZMA_ERRORS = ()


XML_PART_SUFFIXES = (".xml", ".rels", ".vml")
CONTENT_TYPES_PART = "[content_types].xml"
_GENERIC_XML_TYPES = frozenset({"application/xml", "text/xml"})
# Errors reading a damaged, encrypted or inconsistent ZIP entry, or an unreadable part list. The
# package is in memory, so an OSError here comes from a decompressor, not from storage.
_READ_ERRORS = (
    zipfile.BadZipFile, zipfile.LargeZipFile, RuntimeError, NotImplementedError, EOFError, OSError,
    zlib.error, ElementTree.ParseError, UnicodeError,
) + _LZMA_ERRORS
_FIRST_READ_BYTES = 256
_PROLOG_BYTES = 4 * 1024
_PACKAGE_READ_BUDGET = 32 * 1024 * 1024
_MAX_CONTENT_TYPES_BYTES = 16 * 1024 * 1024
_CHECK_EVERY_PARTS = 64
# Whitespace, the XML declaration, processing instructions and comments may come before the root element.
_PROLOG = re.compile(r"\ufeff?(?:\s+|<\?.*?\?>|<!--.*?-->)*", re.DOTALL)
_DECLARATION = re.compile(r"\ufeff?<\?xml\s(.*?)\?>", re.DOTALL)
_DECLARED_ENCODING = re.compile(r"""encoding\s*=\s*["']([^"']*)["']""")
# Office Open XML parts must be UTF-8 or UTF-16. A part that declares another encoding, such as
# UTF-7, could read one way here and another way in a parser.
_ALLOWED_ENCODINGS = frozenset({"utf-8", "utf8", "utf-16", "utf-16le", "utf-16be"})


class UnreadablePackageError(ValueError):
    """A part of the package, or its list of content types, couldn't be read."""


def _encoding(head):
    if head.startswith(b"\xff\xfe"):
        return "utf-16-le"
    if head.startswith(b"\xfe\xff"):
        return "utf-16-be"
    if len(head) >= 2 and head[0] != 0 and head[1] == 0:
        return "utf-16-le"
    if len(head) >= 2 and head[0] == 0 and head[1] != 0:
        return "utf-16-be"
    return "utf-8"


def _verdict(head, final):
    """True to refuse, False once the root element starts, None when more is needed.

    With ``final`` the whole part has been read, so the answer is never None.
    """
    text = head.decode(_encoding(head), errors="replace")
    declaration = _DECLARATION.match(text)
    if declaration is not None:
        encoding = _DECLARED_ENCODING.search(declaration.group(1))
        if encoding is not None and encoding.group(1).strip().lower() not in _ALLOWED_ENCODINGS:
            return True
    rest = text[_PROLOG.match(text).end():]
    if not rest:
        # Empty, or only whitespace, comments and instructions so far; nothing to parse yet.
        return False if final else None
    if rest[0] != "<":
        # Not UTF-8 or UTF-16 XML, which Office Open XML requires.
        return True
    if len(rest) == 1:
        return True if final else None
    marker = rest[1]
    if marker == "!":
        if rest.startswith("<!DOCTYPE"):
            return True
        if rest.startswith("<!--") or "<!DOCTYPE".startswith(rest) or "<!--".startswith(rest):
            # A comment or declaration that hasn't ended yet.
            return True if final else None
        return True
    if marker == "?":
        # An instruction that hasn't ended yet.
        return True if final else None
    if marker == "\ufffd" and len(rest) == 2 and not final:
        # The read may have stopped inside the first character of the root element's name.
        return None
    return not (marker.isalpha() or marker in "_:")


class _Budget:
    __slots__ = ("remaining",)

    def __init__(self, remaining):
        self.remaining = remaining


def _unsafe_prolog(archive, entry, budget):
    """Whether one part's prolog is unsafe; a prolog too long to check counts as unsafe."""
    head = b""
    size = _FIRST_READ_BYTES
    with archive.open(entry) as stream:
        while True:
            wanted = min(size - len(head), budget.remaining)
            if wanted <= 0:
                return True
            chunk = stream.read(wanted)
            budget.remaining -= len(chunk)
            head += chunk
            verdict = _verdict(head, final=len(chunk) < wanted)
            if verdict is not None:
                return verdict
            if len(head) >= _PROLOG_BYTES:
                return True
            size = min(size * 2, _PROLOG_BYTES)


def is_office_xml_part(name, content_type):
    """Whether Office or a library reads the part as Office XML, by its name or declared type."""
    if name.lower().endswith(XML_PART_SUFFIXES):
        return True
    content_type = (content_type or "").strip().lower()
    if content_type in _GENERIC_XML_TYPES:
        return True
    return content_type.startswith("application/vnd.") and (
        content_type.endswith("+xml") or content_type.endswith(".vmldrawing")
    )


def _declared_content_types(archive, entry, names):
    """Extension defaults and per-part overrides, lowercased, for the package's own parts."""
    defaults, overrides = {}, {}
    with archive.open(entry) as stream:
        # The prolog was checked first, so the list declares no entities.
        for _event, element in ElementTree.iterparse(stream):
            tag = element.tag.rsplit("}", 1)[-1]
            if tag == "Default":
                extension = (element.get("Extension") or "").strip().lower()
                if extension:
                    defaults[extension] = element.get("ContentType") or ""
            elif tag == "Override":
                part_name = (element.get("PartName") or "").strip().lstrip("/").lower()
                if part_name in names:
                    overrides[part_name] = element.get("ContentType") or ""
            element.clear()
    return defaults, overrides


def content_type_of(name, defaults, overrides):
    """A part's declared content type, matched without regard to case as Office does."""
    lowered = name.lower()
    if lowered in overrides:
        return overrides[lowered]
    base = lowered.rsplit("/", 1)[-1]
    return defaults.get(base.rpartition(".")[2] if "." in base else "", "")


def first_unsafe_xml_part(archive, entries, *, check=None):
    """The name of the first XML part with a document type declaration or unreadable XML, or None.

    ``check()`` is called between parts and its errors pass through unchanged. ZIP read
    errors and an unreadable part list raise ``UnreadablePackageError``.
    """
    budget = _Budget(_PACKAGE_READ_BUDGET)
    files = [entry for entry in entries if not entry.is_dir()]
    names = {entry.filename.lower() for entry in files}
    defaults, overrides = {}, {}
    listed = next((entry for entry in files if entry.filename.lower() == CONTENT_TYPES_PART), None)
    if listed is not None:
        if listed.file_size > _MAX_CONTENT_TYPES_BYTES:
            return listed.filename
        try:
            if _unsafe_prolog(archive, listed, budget):
                return listed.filename
            defaults, overrides = _declared_content_types(archive, listed, names)
        except _READ_ERRORS as exc:
            raise UnreadablePackageError(listed.filename) from exc
    for position, entry in enumerate(files):
        if check is not None and position % _CHECK_EVERY_PARTS == 0:
            check()
        if entry is listed or not is_office_xml_part(entry.filename, content_type_of(entry.filename, defaults, overrides)):
            continue
        try:
            unsafe = _unsafe_prolog(archive, entry, budget)
        except _READ_ERRORS as exc:
            raise UnreadablePackageError(entry.filename) from exc
        if unsafe:
            return entry.filename
    return None


__all__ = [
    "CONTENT_TYPES_PART",
    "UnreadablePackageError",
    "XML_PART_SUFFIXES",
    "content_type_of",
    "first_unsafe_xml_part",
    "is_office_xml_part",
]

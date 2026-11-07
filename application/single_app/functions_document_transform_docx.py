# functions_document_transform_docx.py
"""Package-preserving Word transformations for the document_transform_v1 contract.

Targets describe structure, not text matches: word:body.p1, word:body.tbl1.row1.cell1,
word:header1.p1.r1 and paragraph-local .image1 slots. Story anchors accept append_text.
Clones use the caller's clone_id as their root target; descendant aliases are returned
in metadata.clones. IDs bind to the inspected revision and stay fixed during a batch.

Only edited story XML and newly required image relationships/content types are written.
Complex fields, controls, revisions, linked pictures and unsupported structures remain
in the package. This adapter never reads files, downloads assets, or generates facts.
An authorized image_resolver(asset_token) returns bytes or None; its failures propagate.
"""

from copy import copy, deepcopy
from dataclasses import dataclass
import hashlib
import io
import posixpath
import warnings

from lxml import etree
from PIL import Image, UnidentifiedImageError

from functions_document_transform import DocumentTransformCancelled, DocumentTransformError


WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
OFFICE_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
CT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
DRAWING_NAMESPACES = {
    "http://schemas.openxmlformats.org/drawingml/2006/main",
    "http://purl.oclc.org/ooxml/drawingml/main",
}
PICTURE_NAMESPACES = {
    "http://schemas.openxmlformats.org/drawingml/2006/picture",
    "http://purl.oclc.org/ooxml/drawingml/picture",
}
WP_NAMESPACES = {
    "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
    "http://purl.oclc.org/ooxml/drawingml/wordprocessingDrawing",
}
REL_NAMESPACES = {OFFICE_REL_NS, "http://purl.oclc.org/ooxml/officeDocument/relationships"}
WORD14_NS = "http://schemas.microsoft.com/office/word/2010/wordml"
_TEXT_TAGS = {"t", "tab", "br", "cr"}
_OPAQUE_WORD_TAGS = {
    "sdt", "sdtContent", "customXml", "object", "pict", "altChunk", "subDoc",
    "ins", "del", "moveFrom", "moveTo", "fldSimple", "fldChar", "instrText",
    "delInstrText", "footnoteReference", "endnoteReference",
}
_STRUCTURAL_MARKERS = {
    "bookmarkStart", "bookmarkEnd", "commentRangeStart", "commentRangeEnd",
    "commentReference", "permStart", "permEnd", "sectPr",
    "moveFromRangeStart", "moveFromRangeEnd", "moveToRangeStart", "moveToRangeEnd",
}
_STRUCTURE_WORD_TAGS = {
    "p", "tbl", "tr", "tc", "r", "pPr", "rPr", "tblPr", "tblGrid", "gridCol",
    "trPr", "tcPr", "tblPrEx", "hyperlink", "drawing", "t", "tab", "br", "cr",
    "sym", "noBreakHyphen", "softHyphen", "lastRenderedPageBreak", "proofErr",
}
_PROPERTY_CONTAINERS = {"pPr", "rPr", "tblPr", "trPr", "tcPr", "tblPrEx"}
_RASTER_TYPES = {
    "PNG": ("png", "image/png"), "JPEG": ("jpeg", "image/jpeg"),
    "GIF": ("gif", "image/gif"), "BMP": ("bmp", "image/bmp"), "TIFF": ("tiff", "image/tiff"),
}
_LIMITATIONS = [
    "Fields, content controls, revisions, equations, linked images and unsupported objects are preserved, not populated.",
    "Clone/remove supports ordinary body paragraphs and tables, not section breaks, bookmarks or annotated blocks.",
    "Replacement text inherits the first changed run's formatting; matching prefixes/suffixes retain their formatting.",
    "Image replacements retain the existing size and crop; pagination, text fit and image fit need visual review.",
    "Target IDs describe the inspected revision; inspect the resulting artifact again before a later refresh.",
]


def _check(callback):
    if callback is not None and callback() is False:
        raise DocumentTransformCancelled()


def _qname(element):
    if not isinstance(element.tag, str):
        return "", ""
    name = etree.QName(element)
    return name.namespace, name.localname


def _id(path):
    if len(path) <= 128:
        return path
    return f"word:node:{hashlib.sha256(path.encode('utf-8')).hexdigest()[:32]}"


def _text_sample(element, word, ceiling, check):
    fragments = []
    length = 0
    for position, node in enumerate(element.iter()):
        if position % 64 == 0:
            _check(check)
        if node.tag == word + "t":
            text = node.text or ""
        elif node.tag == word + "tab":
            text = "\t"
        elif node.tag in (word + "br", word + "cr"):
            text = "\n"
        else:
            continue
        available = ceiling - length
        fragments.append(text[:available])
        length += len(text)
        if length > ceiling:
            return "".join(fragments), True
    return "".join(fragments), False


def _run_text(run, word):
    return "".join(
        (node.text or "") if node.tag == word + "t" else "\t" if node.tag == word + "tab" else "\n"
        for node in run if node.tag in {word + name for name in _TEXT_TAGS}
    )


def _write_run(run, text, word):
    """Change textual children, retaining the run attributes and its complete rPr."""
    textual = [node for node in run if node.tag in {word + name for name in _TEXT_TAGS}]
    insertion = run.index(textual[0]) if textual else len(run)
    for node in textual:
        run.remove(node)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    pieces = []
    buffer = []
    for char in text:
        if char in "\t\n":
            if buffer:
                node = etree.Element(word + "t")
                node.text = "".join(buffer)
                if node.text[0].isspace() or node.text[-1].isspace():
                    node.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
                pieces.append(node)
                buffer = []
            pieces.append(etree.Element(word + ("tab" if char == "\t" else "br")))
        else:
            buffer.append(char)
    if buffer:
        node = etree.Element(word + "t")
        node.text = "".join(buffer)
        if node.text[0].isspace() or node.text[-1].isspace():
            node.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        pieces.append(node)
    for offset, node in enumerate(pieces):
        run.insert(insertion + offset, node)


@dataclass
class _Target:
    id: str
    type: str
    part: str
    element: object
    reason: str = ""


class _WordPackage:
    def __init__(self, package, limits, check):
        self.package = package
        self.limits = limits
        self.check = check
        self.targets = {}
        self.manifest = []
        self.roots = {}
        self.dirty = set()
        self.field_nodes = set()
        self.styles = {}
        self.rel_cache = {}
        self.clones = []
        main = package.parse_xml(package.main_part)
        namespace, local = _qname(main)
        self.word = f"{{{namespace}}}"
        bodies = main.findall(self.word + "body")
        if local != "document" or len(bodies) != 1:
            raise DocumentTransformError("invalid_package", "The Word document has no unambiguous body.")
        self.body = bodies[0]
        self.roots[package.main_part] = main
        self._load_styles()
        self._field_context(main)
        self._story(package.main_part, self.body, "word:body", "body")
        for kind in ("header", "footer"):
            parts = sorted({
                rel["target"] for rel in self._relationships(package.main_part).values()
                if rel["type"].endswith(f"/{kind}") and not rel["external"]
            })
            for ordinal, part in enumerate(parts, start=1):
                _check(check)
                root = package.parse_xml(part)
                if root.tag != self.word + ("hdr" if kind == "header" else "ftr"):
                    raise DocumentTransformError("invalid_package", "A Word header or footer is invalid.")
                self.roots[part] = root
                self._field_context(root)
                self._story(part, root, f"word:{kind}{ordinal}", kind)

    def _relationships(self, part):
        if part not in self.rel_cache:
            self.rel_cache[part] = {rel["id"]: rel for rel in self.package.relationships(part)}
        return self.rel_cache[part]

    def _load_styles(self):
        for rel in self._relationships(self.package.main_part).values():
            if not rel["external"] and rel["type"].endswith("/styles"):
                root = self.package.parse_xml(rel["target"])
                for position, style in enumerate(root.findall(self.word + "style")):
                    if position % 64 == 0:
                        _check(self.check)
                    self.styles[style.get(self.word + "styleId", "")] = style

    def _heading(self, paragraph):
        outline = paragraph.find(f"{self.word}pPr/{self.word}outlineLvl")
        if outline is not None:
            return outline.get(self.word + "val")
        style = paragraph.find(f"{self.word}pPr/{self.word}pStyle")
        name = style.get(self.word + "val", "") if style is not None else ""
        seen = set()
        while name in self.styles and name not in seen:
            _check(self.check)
            seen.add(name)
            definition = self.styles[name]
            outline = definition.find(f"{self.word}pPr/{self.word}outlineLvl")
            if outline is not None:
                return outline.get(self.word + "val")
            based = definition.find(self.word + "basedOn")
            name = based.get(self.word + "val", "") if based is not None else ""
        return None

    def _field_context(self, root):
        """Fields can span runs and paragraphs; do not accidentally edit cached results."""
        depth = 0
        for position, node in enumerate(root.iter()):
            if position % 64 == 0:
                _check(self.check)
            if node.tag == self.word + "fldChar" and node.get(self.word + "fldCharType") == "begin":
                depth += 1
            if depth or node.tag in {self.word + "fldChar", self.word + "instrText"}:
                current = node
                while current is not None:
                    if current.tag in (self.word + "p", self.word + "r"):
                        self.field_nodes.add(current)
                    current = current.getparent()
            if node.tag == self.word + "fldChar" and node.get(self.word + "fldCharType") == "end":
                depth = max(0, depth - 1)

    def _run_reason(self, run):
        if run in self.field_nodes:
            return "Field instructions and cached field results are not editable."
        for node in run:
            if node.tag not in {self.word + name for name in _TEXT_TAGS | {"rPr"}}:
                return "This run contains a non-text object that must be preserved."
            if node.tag == self.word + "br" and node.get(self.word + "type", "textWrapping") != "textWrapping":
                return "Page and column break runs are preserved."
        return ""

    def _paragraph_reason(self, paragraph):
        if paragraph in self.field_nodes:
            return "Field instructions and cached field results are not editable."
        for child in paragraph:
            if child.tag in {self.word + name for name in (
                "pPr", "bookmarkStart", "bookmarkEnd", "commentRangeStart", "commentRangeEnd", "proofErr",
            )}:
                continue
            if child.tag == self.word + "r":
                reason = self._run_reason(child)
            elif child.tag == self.word + "hyperlink":
                reason = ""
                for run in child:
                    if run.tag != self.word + "r":
                        return "This hyperlink contains an unsupported structure."
                    reason = self._run_reason(run)
                    if reason:
                        break
            else:
                return "This paragraph contains an unsupported object, field, control or revision."
            if reason:
                return reason
        return ""

    def _cell_reason(self, cell):
        for child in cell:
            if child.tag == self.word + "tcPr":
                continue
            if child.tag != self.word + "p":
                return "Whole-cell text editing is unsupported for nested tables or other objects; target a paragraph instead."
            reason = self._paragraph_reason(child)
            if reason:
                return reason
            for node in child.iter():
                if _qname(node)[1] in _STRUCTURAL_MARKERS:
                    return "Whole-cell editing would disturb section, bookmark or annotation structure; target a paragraph instead."
        return ""

    def _structural_reason(self, target):
        if target.element.getparent() is not self.body or target.type not in ("paragraph", "heading", "table"):
            return "Clone/remove is supported only for ordinary top-level body paragraphs and tables."
        allowed_namespaces = DRAWING_NAMESPACES | PICTURE_NAMESPACES | WP_NAMESPACES | {self.word[1:-1]}
        for position, node in enumerate(target.element.iter()):
            if position % 64 == 0:
                _check(self.check)
            namespace, local = _qname(node)
            if not namespace:
                continue
            if namespace not in allowed_namespaces or (
                namespace == self.word[1:-1] and local in _OPAQUE_WORD_TAGS | _STRUCTURAL_MARKERS
            ) or node in self.field_nodes:
                return "This block has protected fields, section breaks, bookmarks, annotations or unsupported objects."
            if namespace == self.word[1:-1] and (
                local.endswith("PrChange") or local not in _STRUCTURE_WORD_TAGS and not any(
                    _qname(parent)[0] == namespace and _qname(parent)[1] in _PROPERTY_CONTAINERS
                    for parent in node.iterancestors()
                )
            ):
                return "This block contains unsupported Word structures or tracked formatting changes."
            for attribute in node.attrib:
                name = etree.QName(attribute)
                if name.namespace == WORD14_NS and name.localname in ("paraId", "textId"):
                    continue
                if name.namespace and name.namespace not in (
                    allowed_namespaces | REL_NAMESPACES | {"http://www.w3.org/XML/1998/namespace"}
                ):
                    return "This block has extension attributes whose identities cannot safely be duplicated or removed."
            if local == "drawing" and namespace == self.word[1:-1]:
                pictures = [item for item in node.iter()
                            if _qname(item)[0] in PICTURE_NAMESPACES and _qname(item)[1] == "pic"]
                if len(pictures) != 1:
                    return "Only ordinary picture drawings can be cloned or removed."
        return ""

    def _add(self, path, kind, part, element, reason="", **metadata):
        identifier = _id(path)
        if len(self.targets) >= self.limits.max_targets:
            raise DocumentTransformError("resource_limit", "The Word document has too many inspectable targets.")
        if identifier in self.targets:
            raise DocumentTransformError("invalid_transform", "A Word target or clone identifier is ambiguous.")
        target = _Target(identifier, kind, part, element, reason)
        self.targets[identifier] = target
        text, truncated = _text_sample(element, self.word, min(1024, self.limits.max_text_chars), self.check)
        if kind == "table_cell" and not reason:
            ceiling = min(1024, self.limits.max_text_chars)
            text = self._cell_text(element, ceiling + 1)
            truncated = len(text) > ceiling
            text = text[:ceiling]
        operations = []
        if not reason and kind in ("paragraph", "heading", "run", "table_cell"):
            operations.extend(("replace_text", "append_text"))
        if kind == "image" and not reason:
            operations.append("replace_image")
        if kind == "insertion_anchor":
            operations.append("append_text")
            text, truncated = "", False
        if kind in ("paragraph", "heading", "table") and not self._structural_reason(target):
            operations.extend(("clone", "remove"))
        self.manifest.append({
            "id": identifier, "type": kind, "part": part, "text": text,
            "text_truncated": truncated, "operations": operations, **metadata,
            **({"limitation": reason} if reason else {}),
        })
        return target

    def _story(self, part, root, path, kind):
        self._add(path, "insertion_anchor", part, root, story=kind)
        self._children(part, root, path)

    def _children(self, part, root, path):
        counts = {"p": 0, "tbl": 0, "object": 0}
        for child in root:
            _check(self.check)
            if child.tag in {self.word + "sectPr", self.word + "tcPr"}:
                continue
            local = _qname(child)[1]
            kind = local if child.tag in {self.word + "p", self.word + "tbl"} else "object"
            counts[kind] += 1
            child_path = f"{path}.{kind}{counts[kind]}"
            if kind in ("p", "tbl"):
                self._block(part, child, child_path)
            elif isinstance(child.tag, str):
                self._add(child_path, "content_control" if local == "sdt" else "unsupported",
                          part, child, "This object is preserved; targeted edits are not supported.")

    def _block(self, part, block, path):
        if block.tag == self.word + "p":
            outline = self._heading(block)
            heading = outline is not None and outline.isdigit() and 0 <= int(outline) <= 8
            style = block.find(f"{self.word}pPr/{self.word}pStyle")
            self._add(
                path, "heading" if heading else "paragraph", part, block, self._paragraph_reason(block),
                style=style.get(self.word + "val", "") if style is not None else "",
                **({"heading_level": int(outline) + 1} if heading else {}),
            )
            ordinal = 0
            for child in block:
                runs = [child] if child.tag == self.word + "r" else (
                    list(child) if child.tag == self.word + "hyperlink" else []
                )
                for run in runs:
                    if run.tag == self.word + "r":
                        ordinal += 1
                        self._add(f"{path}.r{ordinal}", "run", part, run, self._run_reason(run))
            self._images(part, block, path)
        else:
            rows = block.findall(self.word + "tr")
            self._add(path, "table", part, block, rows=len(rows))
            for row_index, row in enumerate(rows, start=1):
                for cell_index, cell in enumerate(row.findall(self.word + "tc"), start=1):
                    cell_path = f"{path}.row{row_index}.cell{cell_index}"
                    self._add(cell_path, "table_cell", part, cell, self._cell_reason(cell))
                    self._children(part, cell, cell_path)

    def _images(self, part, paragraph, path):
        ordinal = 0
        for position, node in enumerate(paragraph.iter()):
            if position % 64 == 0:
                _check(self.check)
            namespace, local = _qname(node)
            if namespace in DRAWING_NAMESPACES and local == "blip":
                ordinal += 1
                embeds = [(name, value) for name, value in node.attrib.items()
                          if etree.QName(name).namespace in REL_NAMESPACES and etree.QName(name).localname == "embed"]
                reason = ""
                relation = self._relationships(part).get(embeds[0][1]) if len(embeds) == 1 else None
                if any(etree.QName(name).namespace in REL_NAMESPACES and etree.QName(name).localname == "link"
                       for name in node.attrib) or len(node) or not any(
                    _qname(parent)[0] in PICTURE_NAMESPACES and _qname(parent)[1] == "pic"
                    for parent in node.iterancestors()
                ):
                    reason = "Linked, effect-bearing or complex picture slots are preserved."
                elif relation is None or relation["external"] or not relation["type"].endswith("/image"):
                    reason = "This slot does not have an ordinary embedded image relationship."
                self._add(f"{path}.image{ordinal}", "image", part, node, reason,
                          content_type=self.package.content_type(relation["target"]) if relation and not relation["external"] else "")
            elif node.tag == self.word + "pict":
                ordinal += 1
                self._add(f"{path}.image{ordinal}", "image", part, node, "Legacy VML picture slots are preserved.")

    def layouts(self):
        layouts = []
        for ordinal, section in enumerate(self.roots[self.package.main_part].iter(self.word + "sectPr"), start=1):
            _check(self.check)
            entry = {"id": f"word:section{ordinal}", "type": "section"}
            for child_name, metadata_name in (("pgSz", "page_size"), ("pgMar", "margins"), ("cols", "columns")):
                child = section.find(self.word + child_name)
                if child is not None:
                    entry[metadata_name] = {
                        etree.QName(key).localname: value for key, value in child.attrib.items()
                        if etree.QName(key).namespace == self.word[1:-1]
                    }
            layouts.append(entry)
        return layouts

    def alive(self, target):
        if target.element is self.body or target.element is self.roots[target.part]:
            return True
        return any(parent is self.roots[target.part] for parent in target.element.iterancestors())

    def _runs(self, element):
        if element.tag == self.word + "r":
            return [element]
        return [node for node in element.iter(self.word + "r")]

    def _replace_paragraph(self, element, text, report):
        existing, _truncated = _text_sample(element, self.word, self.limits.max_text_chars + 1, self.check)
        if len(existing) > self.limits.max_text_chars:
            return False, "Target text exceeds the editable text limit."
        runs = self._runs(element)
        values = [_run_text(run, self.word) for run in runs]
        old = "".join(values)
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        if len(text) > self.limits.max_text_chars:
            raise DocumentTransformError("resource_limit", "The replacement text exceeds its editable text limit.")
        if old == text:
            return False, ""
        if not runs:
            runs = [etree.SubElement(element, self.word + "r")]
            values = [""]
        prefix = 0
        while prefix < min(len(old), len(text)) and old[prefix] == text[prefix]:
            prefix += 1
        suffix = 0
        while suffix < min(len(old), len(text)) - prefix and old[-suffix - 1] == text[-suffix - 1]:
            suffix += 1
        old_end = len(old) - suffix
        replacement = text[prefix:len(text) - suffix if suffix else len(text)]
        position = 0
        host = len(runs) - 1
        for index, value in enumerate(values):
            if position + len(value) > prefix:
                host = index
                break
            position += len(value)
        position = 0
        styles = set()
        for index, (run, value) in enumerate(zip(runs, values)):
            _check(self.check)
            properties = run.find(self.word + "rPr")
            styles.add(etree.tostring(properties) if properties is not None else b"")
            before = value[:max(0, min(len(value), prefix - position))]
            after = value[max(0, min(len(value), old_end - position)):]
            updated = before + (replacement if index == host else "") + after
            if updated != value:
                _write_run(run, updated, self.word)
            position += len(value)
        if len(styles) > 1:
            warning = "Mixed-style replacement: unchanged prefixes/suffixes retain formatting; new text inherits the first changed run's style."
            if warning not in report["warnings"]:
                report["warnings"].append(warning)
        return True, ""

    def _cell_text(self, cell, ceiling=None):
        ceiling = self.limits.max_text_chars + 1 if ceiling is None else ceiling
        pieces = []
        length = 0
        for index, paragraph in enumerate(cell.findall(self.word + "p")):
            _check(self.check)
            if length >= ceiling:
                break
            if index:
                pieces.append("\n")
                length += 1
            text, truncated = _text_sample(paragraph, self.word, ceiling - length, self.check)
            pieces.append(text)
            length += len(text)
            if truncated:
                break
        return "".join(pieces)

    def _replace_cell(self, cell, text, report):
        paragraphs = cell.findall(self.word + "p")
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        old = self._cell_text(cell)
        if len(old) > self.limits.max_text_chars:
            return False, "Target text exceeds the editable text limit."
        if len(text) > self.limits.max_text_chars:
            raise DocumentTransformError("resource_limit", "The replacement text exceeds its editable text limit.")
        if old == text:
            return False, ""
        lines = text.split("\n")
        prototype = paragraphs[-1] if paragraphs else None
        for index, line in enumerate(lines):
            if index < len(paragraphs):
                paragraph = paragraphs[index]
            else:
                paragraph = self._new_paragraph(cell, line, prototype)
                continue
            self._replace_paragraph(paragraph, line, report)
        for paragraph in paragraphs[len(lines):]:
            cell.remove(paragraph)
        return True, ""

    def _new_paragraph(self, container, text, prototype=None):
        paragraph = etree.Element(self.word + "p")
        if prototype is not None:
            properties = prototype.find(self.word + "pPr")
            if properties is not None:
                paragraph.append(deepcopy(properties))
        run = etree.SubElement(paragraph, self.word + "r")
        if prototype is not None:
            runs = self._runs(prototype)
            properties = runs[-1].find(self.word + "rPr") if runs else None
            if properties is not None:
                run.append(deepcopy(properties))
        _write_run(run, text, self.word)
        section = container.find(self.word + "sectPr")
        if section is not None:
            container.insert(container.index(section), paragraph)
        else:
            container.append(paragraph)
        return paragraph

    def replace_text(self, target, operation, report):
        if target.reason:
            return False, target.reason
        if target.type == "insertion_anchor" and operation["op"] == "append_text":
            if not operation["text"]:
                return False, ""
            for line in operation["text"].replace("\r\n", "\n").replace("\r", "\n").split("\n"):
                self._new_paragraph(target.element, line)
            return True, ""
        if target.type not in ("paragraph", "heading", "run", "table_cell"):
            return False, "Text operations require a paragraph, run, table cell or insertion anchor."
        text = operation["text"]
        if operation["op"] == "append_text":
            old = self._cell_text(target.element) if target.type == "table_cell" else _text_sample(
                target.element, self.word, self.limits.max_text_chars + 1, self.check,
            )[0]
            text = old + text
        if target.type == "table_cell":
            return self._replace_cell(target.element, text, report)
        return self._replace_paragraph(target.element, text, report)

    def clone(self, target, clone_id):
        reason = self._structural_reason(target)
        if reason:
            return False, reason
        if _id(clone_id) in self.targets:
            return False, "The clone identifier already names an existing target."
        copied = deepcopy(target.element)
        staged = copy(self)
        staged.targets = {}
        staged.manifest = []
        staged._block(target.part, copied, clone_id)
        if set(staged.targets).intersection(self.targets):
            return False, "A clone descendant identifier already names an existing target."
        if len(self.targets) + len(staged.targets) > self.limits.max_targets:
            raise DocumentTransformError("resource_limit", "The Word document has too many inspectable targets.")
        self._renew_ids(copied)
        target.element.addnext(copied)
        for entry in staged.manifest:
            if entry["id"] == clone_id:
                entry["operations"].extend(("clone", "remove"))
        self.targets.update(staged.targets)
        self.manifest.extend(staged.manifest)
        self.clones.append({"id": clone_id, "source": target.id, "targets": [
            identifier for identifier in staged.targets
        ]})
        return True, ""

    def _renew_ids(self, copied):
        used = set()
        used_word = set()
        for root in self.roots.values():
            for position, node in enumerate(root.iter()):
                if position % 64 == 0:
                    _check(self.check)
                namespace, local = _qname(node)
                if namespace in WP_NAMESPACES | PICTURE_NAMESPACES and local in ("docPr", "cNvPr"):
                    used.add(node.get("id", ""))
                for name in ("paraId", "textId"):
                    used_word.add(node.get(f"{{{WORD14_NS}}}{name}", "").upper())
        candidate = 1
        word_candidate = 1
        for node in copied.iter():
            _check(self.check)
            namespace, local = _qname(node)
            if namespace in WP_NAMESPACES | PICTURE_NAMESPACES and local in ("docPr", "cNvPr"):
                while str(candidate) in used:
                    candidate += 1
                node.set("id", str(candidate))
                used.add(str(candidate))
            for name in ("paraId", "textId"):
                attribute = f"{{{WORD14_NS}}}{name}"
                if attribute in node.attrib:
                    while f"{word_candidate:08X}" in used_word:
                        word_candidate += 1
                    value = f"{word_candidate:08X}"
                    node.set(attribute, value)
                    used_word.add(value)

    def remove(self, target):
        reason = self._structural_reason(target)
        if reason:
            return False, reason
        self.body.remove(target.element)
        if not any(child.tag in (self.word + "p", self.word + "tbl") for child in self.body):
            self._new_paragraph(self.body, "")
        return True, ""

    def replace_image(self, target, source, resolver, cache):
        if target.type != "image":
            return False, "Image replacement requires an inspected image slot."
        if target.reason:
            return False, target.reason
        if not source.startswith("asset:") or not source[6:]:
            return False, "Images require an opaque authorized asset token."
        if resolver is None:
            return False, "No authorized image resolver is available."
        if source not in cache:
            _check(self.check)
            data = resolver(source)
            _check(self.check)
            cache[source] = self._image_bytes(data)
        image, reason = cache[source]
        if reason:
            return False, reason
        data, extension, content_type = image
        attribute = next(name for name in target.element.attrib
                         if etree.QName(name).namespace in REL_NAMESPACES and etree.QName(name).localname == "embed")
        existing = self._relationships(target.part)[target.element.get(attribute)]
        if self.package.files[existing["target"]] == data and self.package.content_type(existing["target"]) == content_type:
            return False, ""
        digest = hashlib.sha256(data).hexdigest()
        directory = posixpath.join(posixpath.dirname(self.package.main_part), "media")
        name = posixpath.join(directory, f"transform-{digest}.{extension}")
        ordinal = 1
        used_names = {part.casefold() for part in self.package.files}
        while name.casefold() in used_names:
            name = posixpath.join(directory, f"transform-{digest}-{ordinal}.{extension}")
            ordinal += 1
        self.package.files[name] = data
        types = self.package.parse_xml("[Content_Types].xml")
        etree.SubElement(types, f"{{{CT_NS}}}Override", PartName=f"/{name}", ContentType=content_type)
        self.package.write_xml("[Content_Types].xml", types)
        rels_name = self.package.rels_name(target.part)
        rels = self.package.parse_xml(rels_name)
        ids = self._relationships(target.part)
        rid_ordinal = 1
        while f"rId{rid_ordinal}" in ids:
            rid_ordinal += 1
        rid = f"rId{rid_ordinal}"
        etree.SubElement(rels, f"{{{REL_NS}}}Relationship", {
            "Id": rid, "Type": existing["type"],
            "Target": posixpath.relpath(name, posixpath.dirname(target.part)),
        })
        self.package.write_xml(rels_name, rels)
        self.rel_cache.pop(target.part, None)
        target.element.set(attribute, rid)
        return True, ""

    def _image_bytes(self, data):
        if type(data) is not bytes or not data:
            return None, "The authorized image asset is unavailable or does not contain image bytes."
        if len(data) > self.limits.max_part_bytes:
            raise DocumentTransformError("resource_limit", "The replacement image exceeds its size limit.")
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(data)) as image:
                    if image.width * image.height * 4 > self.limits.max_package_uncompressed_bytes:
                        raise DocumentTransformError("resource_limit", "The replacement image exceeds its pixel limit.")
                    kind = _RASTER_TYPES.get(image.format)
                    if kind is None:
                        return None, "This replacement image format is unsupported; use PNG, JPEG, GIF, BMP or TIFF."
                    image.verify()
        except DocumentTransformError:
            raise
        except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
            raise DocumentTransformError("resource_limit", "The replacement image exceeds its pixel limit.") from exc
        except (UnidentifiedImageError, OSError, ValueError, SyntaxError):
            return None, "The replacement asset is not a readable supported raster image."
        return (data, *kind), ""

    def write(self):
        for part in sorted(self.dirty):
            _check(self.check)
            self.package.write_xml(part, self.roots[part])


def inspect_package(package, *, limits, check):
    """Expose bounded structural targets without reserializing any package part."""
    document = _WordPackage(package, limits, check)
    return {"targets": document.manifest, "layouts": document.layouts(), "limitations": list(_LIMITATIONS)}


def transform_package(package, prepared, *, limits, check, image_resolver):
    """Apply independent supported operations; unsafe/corrupt/access failures propagate."""
    document = _WordPackage(package, limits, check)
    report = {"applied": [], "unchanged": [], "skipped": [], "warnings": [], "metadata": {}}
    cache = {}
    unresolved = {entry["target"] for entry in prepared["unresolved"]}
    for index, operation in enumerate(prepared["operations"]):
        _check(check)
        identifier = operation["target"]
        entry = {"op_index": index, "target": identifier}
        target = document.targets.get(identifier)
        overlap = identifier in unresolved
        if target is not None and operation["op"] != "clone" and not (
            target.type == "insertion_anchor" and operation["op"] == "append_text"
        ):
            ancestors = set(target.element.iterancestors())
            for unresolved_id in unresolved:
                unresolved_target = document.targets.get(unresolved_id)
                if unresolved_target is not None and (
                    unresolved_target.element is target.element or unresolved_target.element in ancestors
                    or target.element in unresolved_target.element.iterancestors()
                ):
                    overlap = True
                    break
        if overlap:
            report["unchanged"].append({**entry, "reason": "This target is unresolved; reference content was preserved."})
            continue
        if target is None or not document.alive(target):
            report["skipped"].append({**entry, "reason": "The target is unknown or its body block was removed."})
            continue
        name = operation["op"]
        if name in ("replace_text", "append_text"):
            changed, reason = document.replace_text(target, operation, report)
        elif name == "clone":
            changed, reason = document.clone(target, operation["clone_id"])
        elif name == "remove":
            changed, reason = document.remove(target)
        elif name == "replace_image":
            changed, reason = document.replace_image(target, operation["source"], image_resolver, cache)
        else:
            changed, reason = False, "This Word operation is unsupported."
        if changed:
            document.dirty.add(target.part)
            report["applied"].append(entry)
        elif reason:
            report["skipped"].append({**entry, "reason": reason})
        else:
            report["unchanged"].append({**entry, "reason": "The requested content already matches the target."})
    document.write()
    report["metadata"] = {"adapter": "word-package-v1", "clones": document.clones}
    if report["applied"]:
        report["warnings"].append("Word pagination, text fit and image fit have not been visually validated.")
    _check(check)
    return report


__all__ = ["inspect_package", "transform_package"]

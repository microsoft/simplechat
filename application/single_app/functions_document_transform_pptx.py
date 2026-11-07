# functions_document_transform_pptx.py
"""Package-preserving PowerPoint reference creation and selected-content refresh.

Original roots are ``slide:<sldId>`` and ``layout:<sldLayoutId>``. Shape IDs are
slide-wide ``:shape:<cNvPr id>`` even inside groups; text paragraphs are ``:p:N``
and table cells ``:cell:R:C`` (all indexes one-based). Every slide also exposes
``:notes`` even when no notes part exists. A clone's root is exactly clone_id,
with the same descendant suffixes, and clones append in operation order.
Paragraph slots are not reused after removal within a prepared plan; appended
paragraphs receive the next unused slot. Clone metadata includes the output's
canonical slide ID for subsequent inspections of the new artifact.

Layouts are read-only reference structures: clone instantiates their ordinary
placeholders, leaving background/artwork inherited from the original layout.
Inspection advertises each layout's clone_targets with target_suffix/operations;
the editable target is clone_id + target_suffix, not the read-only source ID.
Only slides/layouts support clone. Text bodies append paragraphs; a paragraph
target appends inline. Formatting follows the original paragraph/run boundaries.
Images accept authorized resolver bytes (or {content: bytes}); nothing is fetched.
"""

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import io
import posixpath
import warnings

from lxml import etree
from PIL import Image, UnidentifiedImageError

from functions_document_transform import DocumentTransformCancelled, DocumentTransformError


_P = "http://schemas.openxmlformats.org/presentationml/2006/main"
_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"
_CT = "{http://schemas.openxmlformats.org/package/2006/content-types}"
_CONTENT_PREFIX = "application/vnd.openxmlformats-officedocument.presentationml."
_LIMITATIONS = [
    "Charts, SmartArt, embedded objects and animations are preserved, not refreshed.",
    "Layout/master artwork is inherited; clone a layout to edit its slide placeholders.",
    "Text formatting is retained by paragraph/run boundaries; expanded text needs a fit review.",
    "Authorized raster images support PNG, JPEG, GIF, BMP and TIFF; crop/frame dimensions are retained.",
]


def _check(check):
    if check is not None and check() is False:
        raise DocumentTransformCancelled()


def _invalid():
    raise DocumentTransformError("invalid_package", "The presentation structure is invalid.")


def _number(value, minimum=1, maximum=4294967295):
    if not value or not value.isascii() or not value.isdecimal():
        _invalid()
    digits = value.lstrip("0") or "0"
    if len(digits) > 10:
        _invalid()
    number = int(digits)
    if not minimum <= number <= maximum:
        _invalid()
    return number


@dataclass
class _Target:
    id: str
    type: str
    part: str
    node: object
    parent: str = ""
    body: object = None
    readonly: bool = False
    name: str = ""


class _Deck:
    def __init__(self, package, limits, check):
        self.package, self.limits, self.check = package, limits, check
        self.roots, self.rels, self.dirty, self.targets = {}, {}, set(), {}
        self.next_paragraph = {}
        self.warnings, self.changed_children, self.removed = [], {}, []
        self.clones = []
        self.main = self.root(package.main_part)
        namespace = etree.QName(self.main).namespace
        self.p = namespace
        self.a = _A if namespace == _P else "http://purl.oclc.org/ooxml/drawingml/main"
        self.r = _R if namespace == _P else "http://purl.oclc.org/ooxml/officeDocument/relationships"
        self.slide_list = self.main.find(self.qp("sldIdLst"))
        self.slide_entries, self.layout_records, self.master_parts = {}, [], []
        self._load()
        self.next_slide_id = max(
            (_number(entry.get("id"), 256, 2147483647) for entry in self.slide_entries.values()),
            default=255,
        ) + 1

    def qp(self, name):
        return f"{{{self.p}}}{name}"

    def qa(self, name):
        return f"{{{self.a}}}{name}"

    def qr(self, name):
        return f"{{{self.r}}}{name}"

    def root(self, part):
        if part not in self.roots:
            self.roots[part] = self.package.parse_xml(part)
        return self.roots[part]

    def relationships(self, part):
        if part not in self.rels:
            self.rels[part] = self.package.relationships(part)
        return self.rels[part]

    def related(self, part, suffix):
        return [
            rel for rel in self.relationships(part)
            if rel["type"].endswith(f"/{suffix}") and not rel["external"]
        ]

    def add_target(self, target):
        _check(self.check)
        if len(target.id) > 128 or target.id in self.targets:
            _invalid()
        if len(self.targets) >= self.limits.max_targets:
            raise DocumentTransformError("resource_limit", "The presentation has too many editable targets.")
        self.targets[target.id] = target

    def _load(self):
        layouts_seen, slides_seen, layout_ids = set(), set(), set()
        master_list = self.main.find(self.qp("sldMasterIdLst"))
        main_rels = {rel["id"]: rel for rel in self.relationships(self.package.main_part)}
        if master_list is not None:
            for entry in master_list:
                _check(self.check)
                if entry.tag != self.qp("sldMasterId"):
                    continue
                rel = main_rels.get(entry.get(self.qr("id")))
                if not rel or rel["external"] or not rel["type"].endswith("/slideMaster"):
                    _invalid()
                part = rel["target"]
                if part in self.master_parts:
                    _invalid()
                self.master_parts.append(part)
                master = self.root(part)
                if master.tag != self.qp("sldMaster"):
                    _invalid()
                by_id = {rel["id"]: rel for rel in self.relationships(part)}
                layout_list = master.find(self.qp("sldLayoutIdLst"))
                if layout_list is None:
                    continue
                for layout in layout_list:
                    if layout.tag != self.qp("sldLayoutId"):
                        continue
                    number = _number(layout.get("id"), 2147483648)
                    rel = by_id.get(layout.get(self.qr("id")))
                    if number in layout_ids or not rel or rel["external"] or not rel["type"].endswith("/slideLayout"):
                        _invalid()
                    layout_ids.add(number)
                    layout_part = rel["target"]
                    if layout_part in layouts_seen:
                        _invalid()
                    layouts_seen.add(layout_part)
                    root = self.root(layout_part)
                    if root.tag != self.qp("sldLayout"):
                        _invalid()
                    csld = root.find(self.qp("cSld"))
                    name = (csld.get("name", "") if csld is not None else "")[:256]
                    target_id = f"layout:{number}"
                    self.add_target(_Target(target_id, "layout", layout_part, root, readonly=True, name=name))
                    self._shapes(layout_part, root, target_id, readonly=True)
                    self.layout_records.append({
                        "id": target_id, "type": "layout", "name": name,
                        "layout_type": root.get("type", "")[:128], "master_part": part,
                        "operations": ["clone"],
                    })
        if self.slide_list is not None:
            for entry in self.slide_list:
                _check(self.check)
                if entry.tag != self.qp("sldId"):
                    continue
                number = _number(entry.get("id"), 256, 2147483647)
                target_id = f"slide:{number}"
                rel = main_rels.get(entry.get(self.qr("id")))
                if not rel or rel["external"] or not rel["type"].endswith("/slide"):
                    _invalid()
                part = rel["target"]
                if part in slides_seen:
                    _invalid()
                slides_seen.add(part)
                self.slide_entries[target_id] = entry
                self._slide(part, target_id)

    def _slide(self, part, target_id):
        root = self.root(part)
        if root.tag != self.qp("sld") or len(self.related(part, "slideLayout")) != 1:
            _invalid()
        self.add_target(_Target(target_id, "slide", part, root))
        self._shapes(part, root, target_id)
        note_rels = self.related(part, "notesSlide")
        if len(note_rels) > 1:
            _invalid()
        notes_id = f"{target_id}:notes"
        if note_rels:
            notes_part = note_rels[0]["target"]
            notes = self.root(notes_part)
            if notes.tag != self.qp("notes"):
                _invalid()
            backrefs = self.related(notes_part, "slide")
            if len(backrefs) != 1 or backrefs[0]["target"] != part:
                _invalid()
            bodies = []
            for shape in notes.iter(self.qp("sp")):
                placeholder = shape.find(f"{self.qp('nvSpPr')}/{self.qp('nvPr')}/{self.qp('ph')}")
                if placeholder is not None and placeholder.get("type") == "body":
                    body = shape.find(self.qp("txBody"))
                    if body is not None:
                        bodies.append(body)
            self.add_target(_Target(notes_id, "notes", notes_part, notes, target_id, bodies[0] if bodies else None))
            self._shapes(notes_part, notes, notes_id)
        else:
            self.add_target(_Target(notes_id, "notes", part, None, target_id))

    def _shapes(self, part, root, owner, readonly=False):
        tree = root.find(f"{self.qp('cSld')}/{self.qp('spTree')}")
        if tree is None:
            _invalid()
        group_props = tree.find(f"{self.qp('nvGrpSpPr')}/{self.qp('cNvPr')}")
        if group_props is None or tree.find(self.qp("grpSpPr")) is None:
            _invalid()
        shape_ids = {_number(group_props.get("id"), 0)}
        shape_tags = {self.qp(name) for name in ("sp", "pic", "grpSp", "graphicFrame", "cxnSp", "contentPart")}

        def visit(container, parent):
            for node in container:
                _check(self.check)
                if node.tag not in shape_tags:
                    continue
                props = next(node.iter(self.qp("cNvPr")), None)
                if props is None:
                    _invalid()
                number = _number(props.get("id"), 0)
                if number in shape_ids:
                    _invalid()
                shape_ids.add(number)
                target_id = f"{owner}:shape:{number}"
                body = node.find(self.qp("txBody"))
                kind = "shape"
                placeholder = node.find(f"{self.qp('nvSpPr')}/{self.qp('nvPr')}/{self.qp('ph')}")
                if placeholder is not None and placeholder.get("type") == "pic":
                    kind = "picture"
                elif node.tag == self.qp("grpSp"):
                    kind = "group"
                elif node.tag == self.qp("pic"):
                    kind = "picture"
                elif node.tag == self.qp("graphicFrame"):
                    kind = "table" if next(node.iter(self.qa("tbl")), None) is not None else "unsupported"
                elif node.tag == self.qp("contentPart"):
                    kind = "unsupported"
                target = _Target(target_id, kind, part, node, parent, body, readonly, props.get("name", "")[:256])
                self.add_target(target)
                if body is not None:
                    self._paragraphs(target)
                if kind == "group":
                    visit(node, target_id)
                elif kind == "table":
                    table = next(node.iter(self.qa("tbl")))
                    for row_index, row in enumerate(table.findall(self.qa("tr")), 1):
                        for col_index, cell in enumerate(row.findall(self.qa("tc")), 1):
                            cell_id = f"{target_id}:cell:{row_index}:{col_index}"
                            cell_target = _Target(
                                cell_id, "table_cell", part, cell, target_id,
                                cell.find(self.qa("txBody")), readonly,
                            )
                            self.add_target(cell_target)
                            self._paragraphs(cell_target)

        visit(tree, owner)

    def _paragraphs(self, target):
        if target.body is None:
            return
        for index, node in enumerate(target.body.findall(self.qa("p")), 1):
            self.add_target(_Target(
                f"{target.id}:p:{index}", "paragraph", target.part, node, target.id,
                readonly=target.readonly,
            ))
        self.next_paragraph[target.id] = len(target.body.findall(self.qa("p"))) + 1

    def _sync_paragraphs(self, target):
        existing = [item for item in self.targets.values() if item.parent == target.id and item.type == "paragraph"]
        retained = {}
        for item in existing:
            if item.node.getparent() is target.body:
                retained[item.node] = item
            else:
                self.targets.pop(item.id)
        for node in target.body.findall(self.qa("p")):
            if node in retained:
                continue
            number = self.next_paragraph.get(target.id, 1)
            self.next_paragraph[target.id] = number + 1
            self.add_target(_Target(
                f"{target.id}:p:{number}", "paragraph", target.part, node, target.id,
                readonly=target.readonly,
            ))

    def paragraph_text(self, node):
        result = []
        for child in node:
            if child.tag in (self.qa("r"), self.qa("fld")):
                text = child.find(self.qa("t"))
                result.append(text.text or "" if text is not None else "")
            elif child.tag == self.qa("br"):
                result.append("\n")
        return "".join(result)

    def text(self, target):
        if target.type == "paragraph":
            return self.paragraph_text(target.node)
        if target.body is not None:
            return "\n".join(self.paragraph_text(p) for p in target.body.findall(self.qa("p")))
        return ""

    def _editable_operations(self, target):
        if target.type == "picture":
            return ["replace_image", "remove"]
        if target.body is not None or target.type in ("paragraph", "notes"):
            operations = ["replace_text", "append_text"]
            if target.type in ("paragraph", "shape"):
                operations.append("remove")
            return operations
        if target.type in ("shape", "group"):
            return ["remove"]
        return []

    def _layout_clone_owner(self, target):
        current = target
        while current.parent:
            parent = self.targets[current.parent]
            if parent.type == "layout":
                placeholder = next(current.node.iter(self.qp("ph")), None)
                if (
                    current.node.tag == self.qp("sp") and placeholder is not None
                    and placeholder.get("type") not in ("dt", "ftr", "sldNum")
                ):
                    return parent
                return None
            current = parent
        return None

    def inspect(self):
        targets = []
        layouts = [
            {
                **record, "clone_root_is_clone_id": True,
                "clone_targets": [{
                    "target_suffix": ":notes", "type": "notes",
                    "operations": ["replace_text", "append_text"],
                }],
            }
            for record in self.layout_records
        ]
        layout_by_id = {record["id"]: record for record in layouts}
        for target in self.targets.values():
            _check(self.check)
            text = self.text(target)
            entry = {"id": target.id, "type": target.type}
            if target.parent:
                entry["parent"] = target.parent
            if target.name:
                entry["name"] = target.name
            if target.type in ("paragraph", "notes") or target.body is not None:
                ceiling = min(2000, self.limits.max_text_chars)
                entry["text"] = text[:ceiling]
                if len(text) > ceiling:
                    entry["text_truncated"] = True
            if target.type in ("slide", "layout"):
                entry["operations"] = ["clone"] + (["remove"] if target.type == "slide" else [])
            elif target.readonly:
                entry["operations"] = []
                owner = self._layout_clone_owner(target)
                if owner is not None:
                    suffix = target.id[len(owner.id):]
                    operations = self._editable_operations(target)
                    entry.update({
                        "clone_layout": owner.id, "clone_target_suffix": suffix,
                        "clone_operations": operations,
                    })
                    layout_by_id[owner.id]["clone_targets"].append({
                        "source_target": target.id, "target_suffix": suffix,
                        "type": target.type, "operations": operations,
                    })
            else:
                entry["operations"] = self._editable_operations(target)
            targets.append(entry)
        size = self.main.find(self.qp("sldSz"))
        return {
            "targets": targets, "layouts": layouts, "limitations": list(_LIMITATIONS),
            "slide_size": dict(size.attrib) if size is not None else {},
            "slide_count": len(self.slide_entries),
            "target_naming": "clone_id is the cloned slide root; descendant suffixes match the source.",
        }

    def warn(self, message):
        if message not in self.warnings:
            self.warnings.append(message)

    def descendants(self, target_id):
        children = []
        parents = {target_id}
        for target in self.targets.values():
            if target.parent in parents:
                children.append(target.id)
                parents.add(target.id)
        return children

    def _part(self, directory, stem, extension=".xml"):
        index = 1
        names = {name.casefold() for name in self.package.files}
        while f"{directory}/{stem}{index}{extension}".casefold() in names:
            index += 1
        return f"{directory}/{stem}{index}{extension}"

    def _store(self, part, data, content_type):
        if len(data) > self.limits.max_part_bytes:
            raise DocumentTransformError("resource_limit", "An internal document part exceeds its size limit.")
        if part not in self.package.files and len(self.package.files) >= self.limits.max_package_entries:
            raise DocumentTransformError("resource_limit", "The presentation has too many internal parts.")
        total = sum(map(len, self.package.files.values())) - len(self.package.files.get(part, b"")) + len(data)
        if total > self.limits.max_package_uncompressed_bytes:
            raise DocumentTransformError("resource_limit", "The presentation exceeds its resource limits.")
        self.package.files[part] = data
        types = self.root("[Content_Types].xml")
        for entry in types:
            if entry.tag == _CT + "Override" and entry.get("PartName") == f"/{part}":
                entry.set("ContentType", content_type)
                break
        else:
            etree.SubElement(types, _CT + "Override", {"PartName": f"/{part}", "ContentType": content_type})
        self.dirty.add("[Content_Types].xml")

    def _write_rels(self, part):
        root = etree.Element(_REL + "Relationships", nsmap={None: _REL[1:-1]})
        for rel in self.relationships(part):
            attributes = {
                "Id": rel["id"], "Type": rel["type"],
                "Target": rel["target"] if rel["external"] else posixpath.relpath(
                    rel["target"], posixpath.dirname(part) or ".",
                ),
            }
            if rel["external"]:
                attributes["TargetMode"] = "External"
            etree.SubElement(root, _REL + "Relationship", attributes)
        name = self.package.rels_name(part)
        data = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
        if name not in self.package.files:
            self._store(name, data, "application/vnd.openxmlformats-package.relationships+xml")
        else:
            self.package.files[name] = data

    def _append_rel(self, owner, reltype, target, external=False):
        relationships = self.relationships(owner)
        used = {rel["id"] for rel in relationships}
        number = 1
        while f"rId{number}" in used:
            number += 1
        rid = f"rId{number}"
        relationships.append({"id": rid, "type": reltype, "target": target, "external": external})
        self._write_rels(owner)
        return rid

    def _add_rel(self, owner, suffix, target):
        return self._append_rel(owner, f"{self.r}/{suffix}", target)

    def _insert_main(self, node):
        order = ("sldMasterIdLst", "notesMasterIdLst", "handoutMasterIdLst", "sldIdLst", "sldSz", "notesSz")
        wanted = order.index(etree.QName(node).localname)
        for index, existing in enumerate(self.main):
            local = etree.QName(existing).localname if isinstance(existing.tag, str) else ""
            if local in order and order.index(local) > wanted:
                self.main.insert(index, node)
                break
        else:
            self.main.append(node)
        self.dirty.add(self.package.main_part)

    def clone(self, target, clone_id):
        if target.type not in ("slide", "layout"):
            return "Only slides and layouts can be cloned."
        source_tree = [target.id, *self.descendants(target.id)]
        source_targets = [self.targets[key] for key in source_tree]
        predicted = [clone_id + key[len(target.id):] for key in source_tree]
        predicted.append(f"{clone_id}:notes")
        if any(len(key) > 128 or key in self.targets for key in predicted):
            return "The clone identifier collides with a target or leaves no room for descendant IDs."
        if len(self.targets) + len(set(predicted)) > self.limits.max_targets:
            raise DocumentTransformError("resource_limit", "The presentation has too many editable targets.")
        new_part = self._part("ppt/slides", "slide")
        if target.type == "slide":
            new_root = deepcopy(target.node)
            self._store(new_part, self.package.files[target.part], _CONTENT_PREFIX + "slide+xml")
            self.roots[new_part] = new_root
            relationships = deepcopy(self.relationships(target.part))
            for rel in relationships:
                if not rel["external"] and rel["target"] == target.part:
                    rel["target"] = new_part
                if not rel["external"] and rel["type"].endswith("/notesSlide"):
                    original = rel["target"]
                    copied = self._part("ppt/notesSlides", "notesSlide")
                    self._store(copied, self.package.files[original], _CONTENT_PREFIX + "notesSlide+xml")
                    self.roots[copied] = deepcopy(self.root(original))
                    self.rels[copied] = deepcopy(self.relationships(original))
                    for backref in self.rels[copied]:
                        if not backref["external"] and backref["type"].endswith("/slide"):
                            backref["target"] = new_part
                        elif not backref["external"] and backref["target"] == original:
                            backref["target"] = copied
                    self._write_rels(copied)
                    self.dirty.add(copied)
                    rel["target"] = copied
            self.rels[new_part] = relationships
            self._write_rels(new_part)
        else:
            new_root = self._blank("sld")
            tree = new_root.find(f"{self.qp('cSld')}/{self.qp('spTree')}")
            source = target.node.find(f"{self.qp('cSld')}/{self.qp('spTree')}")
            for name in ("nvGrpSpPr", "grpSpPr"):
                old = tree.find(self.qp(name))
                tree.replace(old, deepcopy(source.find(self.qp(name))))
            for shape in source:
                placeholder = next(shape.iter(self.qp("ph")), None)
                if shape.tag == self.qp("sp") and placeholder is not None and placeholder.get("type") not in ("dt", "ftr", "sldNum"):
                    copied_shape = deepcopy(shape)
                    # Layout example strings are not actual new slide content.
                    for paragraph in copied_shape.iter(self.qa("p")):
                        self._replace_paragraph(paragraph, "", clone_id)
                    tree.append(copied_shape)
            # Preserve placeholder relationships (pictures/hyperlinks) without importing
            # the layout's master backreference into the new slide.
            self.rels[new_part] = [
                deepcopy(rel) for rel in self.relationships(target.part)
                if not rel["type"].endswith("/slideMaster")
            ]
            self._store(new_part, etree.tostring(new_root), _CONTENT_PREFIX + "slide+xml")
            self.roots[new_part] = new_root
            self._add_rel(new_part, "slideLayout", target.part)
        if self.slide_list is None:
            self.slide_list = etree.Element(self.qp("sldIdLst"))
            self._insert_main(self.slide_list)
        number = self.next_slide_id
        if number > 2147483647:
            raise DocumentTransformError("resource_limit", "The presentation has too many slide identifiers.")
        self.next_slide_id += 1
        rid = self._add_rel(self.package.main_part, "slide", new_part)
        entry = etree.SubElement(self.slide_list, self.qp("sldId"), {"id": str(number), self.qr("id"): rid})
        self.slide_entries[clone_id] = entry
        self.dirty.update((new_part, self.package.main_part))
        self._slide(new_part, clone_id)
        if target.type == "slide":
            # Preserve live paragraph slot IDs after earlier removals/appends, rather
            # than silently rebinding a requested source paragraph to its neighbor.
            for source in source_targets:
                if source.body is None or source.type == "notes":
                    continue
                copied = self.targets.get(clone_id + source.id[len(target.id):])
                if copied is None or copied.body is None:
                    continue
                original_nodes = source.body.findall(self.qa("p"))
                copied_nodes = copied.body.findall(self.qa("p"))
                source_paragraphs = [
                    item for item in self.targets.values()
                    if item.parent == source.id and item.type == "paragraph"
                ]
                if source_paragraphs:
                    for item in list(self.targets.values()):
                        if item.parent == copied.id and item.type == "paragraph":
                            self.targets.pop(item.id)
                    for item in source_paragraphs:
                        position = original_nodes.index(item.node)
                        self.add_target(_Target(
                            copied.id + item.id[len(source.id):], "paragraph", copied.part,
                            copied_nodes[position], copied.id,
                        ))
                self.next_paragraph[copied.id] = self.next_paragraph[source.id]
        self.clones.append({
            "source": target.id, "target": clone_id, "output_id": f"slide:{number}",
            "descendants": self.descendants(clone_id),
        })
        return None

    def _blank(self, kind):
        root = etree.Element(self.qp(kind), nsmap={"p": self.p, "a": self.a, "r": self.r})
        csld = etree.SubElement(root, self.qp("cSld"))
        tree = etree.SubElement(csld, self.qp("spTree"))
        nv = etree.SubElement(tree, self.qp("nvGrpSpPr"))
        etree.SubElement(nv, self.qp("cNvPr"), {"id": "1", "name": ""})
        etree.SubElement(nv, self.qp("cNvGrpSpPr"))
        etree.SubElement(nv, self.qp("nvPr"))
        group = etree.SubElement(tree, self.qp("grpSpPr"))
        transform = etree.SubElement(group, self.qa("xfrm"))
        for name, attributes in (
            ("off", {"x": "0", "y": "0"}), ("ext", {"cx": "0", "cy": "0"}),
            ("chOff", {"x": "0", "y": "0"}), ("chExt", {"cx": "0", "cy": "0"}),
        ):
            etree.SubElement(transform, self.qa(name), attributes)
        if kind != "notesMaster":
            color = etree.SubElement(root, self.qp("clrMapOvr"))
            etree.SubElement(color, self.qa("masterClrMapping"))
        return root

    def _note_placeholder(self, root, kind):
        tree = root.find(f"{self.qp('cSld')}/{self.qp('spTree')}")
        used = {_number(node.get("id"), 0) for node in root.iter(self.qp("cNvPr"))}
        number = max(used, default=1) + 1
        shape = etree.SubElement(tree, self.qp("sp"))
        nv = etree.SubElement(shape, self.qp("nvSpPr"))
        name = "Notes Text" if kind == "body" else "Slide Image"
        etree.SubElement(nv, self.qp("cNvPr"), {"id": str(number), "name": name})
        etree.SubElement(nv, self.qp("cNvSpPr"))
        placeholder = etree.SubElement(nv, self.qp("nvPr"))
        etree.SubElement(placeholder, self.qp("ph"), {"type": kind, "idx": "1" if kind == "body" else "2"})
        properties = etree.SubElement(shape, self.qp("spPr"))
        size = self.main.find(self.qp("notesSz"))
        width = _number(size.get("cx")) if size is not None else 6858000
        height = _number(size.get("cy")) if size is not None else 9144000
        transform = etree.SubElement(properties, self.qa("xfrm"))
        etree.SubElement(transform, self.qa("off"), {
            "x": str(width // 10), "y": str(height // 2 if kind == "body" else height // 12),
        })
        etree.SubElement(transform, self.qa("ext"), {
            "cx": str(width * 4 // 5), "cy": str(height * 2 // 5 if kind == "body" else height // 3),
        })
        geometry = etree.SubElement(properties, self.qa("prstGeom"), {"prst": "rect"})
        etree.SubElement(geometry, self.qa("avLst"))
        return shape

    def _note_body(self, root):
        shape = self._note_placeholder(root, "body")
        body = etree.SubElement(shape, self.qp("txBody"))
        etree.SubElement(body, self.qa("bodyPr"))
        etree.SubElement(body, self.qa("lstStyle"))
        etree.SubElement(body, self.qa("p"))
        return body

    def _notes_master(self):
        masters = self.related(self.package.main_part, "notesMaster")
        if masters:
            if self.root(masters[0]["target"]).tag != self.qp("notesMaster"):
                _invalid()
            return masters[0]["target"]
        part = self._part("ppt/notesMasters", "notesMaster")
        root = self._blank("notesMaster")
        self._note_placeholder(root, "sldImg")
        self._note_body(root)
        colors = {key: key for key in ("accent1", "accent2", "accent3", "accent4", "accent5", "accent6", "hlink", "folHlink")}
        colors.update({"bg1": "lt1", "tx1": "dk1", "bg2": "lt2", "tx2": "dk2"})
        etree.SubElement(root, self.qp("clrMap"), colors)
        style = etree.SubElement(root, self.qp("notesStyle"))
        level = etree.SubElement(style, self.qa("lvl1pPr"), {"algn": "l"})
        etree.SubElement(level, self.qa("defRPr"), {"sz": "1200"})
        self._store(part, etree.tostring(root), _CONTENT_PREFIX + "notesMaster+xml")
        self.roots[part] = root
        self.dirty.add(part)
        for master in self.master_parts:
            themes = self.related(master, "theme")
            if themes:
                self._add_rel(part, "theme", themes[0]["target"])
                break
        rid = self._add_rel(self.package.main_part, "notesMaster", part)
        container = self.main.find(self.qp("notesMasterIdLst"))
        if container is None:
            container = etree.Element(self.qp("notesMasterIdLst"))
            self._insert_main(container)
        etree.SubElement(container, self.qp("notesMasterId"), {self.qr("id"): rid})
        self.dirty.add(self.package.main_part)
        return part

    def ensure_notes(self, target):
        if target.node is None:
            slide = self.targets[target.parent]
            part = self._part("ppt/notesSlides", "notesSlide")
            root = self._blank("notes")
            master_part = self._notes_master()
            master = self.root(master_part)
            tree = root.find(f"{self.qp('cSld')}/{self.qp('spTree')}")
            body = None
            number = 2
            for source in master.iter(self.qp("sp")):
                placeholder = source.find(f"{self.qp('nvSpPr')}/{self.qp('nvPr')}/{self.qp('ph')}")
                if placeholder is None or placeholder.get("type") not in ("body", "sldImg", "sldNum"):
                    continue
                shape = deepcopy(source)
                properties = shape.find(f"{self.qp('nvSpPr')}/{self.qp('cNvPr')}")
                if properties is None:
                    _invalid()
                properties.set("id", str(number))
                number += 1
                for paragraph in shape.iter(self.qa("p")):
                    if next(paragraph.iter(self.qa("fld")), None) is None:
                        self._replace_paragraph(paragraph, "", target.id)
                tree.append(shape)
                if placeholder.get("type") == "body" and body is None:
                    body = shape.find(self.qp("txBody"))
            if body is None:
                body = self._note_body(root)
            self._store(part, etree.tostring(root), _CONTENT_PREFIX + "notesSlide+xml")
            self.roots[part] = root
            source_rels = {rel["id"]: rel for rel in self.relationships(master_part)}
            copied_ids = {}
            for node in root.iter():
                for attribute, old_id in list(node.attrib.items()):
                    if not attribute.startswith(f"{{{self.r}}}"):
                        continue
                    rel = source_rels.get(old_id)
                    if rel is None:
                        _invalid()
                    if old_id not in copied_ids:
                        copied_ids[old_id] = self._append_rel(part, rel["type"], rel["target"], rel["external"])
                    node.set(attribute, copied_ids[old_id])
            self._add_rel(part, "slide", slide.part)
            self._add_rel(part, "notesMaster", master_part)
            self._add_rel(slide.part, "notesSlide", part)
            target.part, target.node, target.body = part, root, body
            self._shapes(part, root, target.id)
        elif target.body is None:
            target.body = self._note_body(target.node)
            # Register only the newly added body, not all existing note shapes again.
            body_shape = target.body.getparent()
            number = next(body_shape.iter(self.qp("cNvPr"))).get("id")
            child = _Target(f"{target.id}:shape:{number}", "shape", target.part, body_shape, target.id, target.body)
            self.add_target(child)
            self._paragraphs(child)
        self.dirty.add(target.part)

    def _replace_paragraph(self, paragraph, text, target_id):
        runs = paragraph.findall(self.qa("r"))
        styles = {etree.tostring(run.find(self.qa("rPr"))) if run.find(self.qa("rPr")) is not None else b"" for run in runs}
        if len(styles) > 1:
            self.warn(f"Mixed run styles at {target_id} follow the original character boundaries.")
        templates = [(deepcopy(run), len(run.findtext(self.qa("t"), ""))) for run in runs]
        end = paragraph.find(self.qa("endParaRPr"))
        for node in list(paragraph):
            if node.tag in (self.qa("r"), self.qa("br")):
                paragraph.remove(node)
        cursor = 0
        for index, (run, length) in enumerate(templates or [(etree.Element(self.qa("r")), len(text))]):
            content = text[cursor:] if index == len(templates) - 1 or not templates else text[cursor:cursor + length]
            cursor += len(content)
            for chunk_index, chunk in enumerate(content.split("\n")):
                if chunk_index:
                    br = etree.Element(self.qa("br"))
                    paragraph.insert(paragraph.index(end) if end is not None else len(paragraph), br)
                node = deepcopy(run)
                existing = node.find(self.qa("t"))
                if existing is None:
                    existing = etree.SubElement(node, self.qa("t"))
                existing.text = chunk
                if chunk != chunk.strip():
                    existing.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
                paragraph.insert(paragraph.index(end) if end is not None else len(paragraph), node)

    def edit_text(self, target, operation, text):
        if target.readonly:
            return "Layouts are read-only; clone the layout and edit its slide placeholders."
        if target.type == "unsupported":
            return "Charts, SmartArt and embedded objects are preserved and cannot be refreshed."
        if target.type != "paragraph" and target.body is None and target.type != "notes":
            return "This target has no editable text body."
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        previous = self.text(target)
        if operation == "append_text" and not text:
            return False
        if operation == "replace_text" and previous == text:
            return False
        affected = self.descendants(target.id)
        body_or_paragraph = target.node if target.type == "paragraph" else target.body
        if body_or_paragraph is not None and next(body_or_paragraph.iter(self.qa("fld")), None) is not None:
            return "Dynamic text fields are preserved and cannot be safely refreshed."
        if target.type == "notes":
            self.ensure_notes(target)
        if target.type == "paragraph":
            self._replace_paragraph(target.node, previous + text if operation == "append_text" else text, target.id)
        else:
            paragraphs = target.body.findall(self.qa("p"))
            lines = text.split("\n")
            if operation == "append_text" and previous:
                template = paragraphs[-1] if paragraphs else etree.Element(self.qa("p"))
                for line in lines:
                    node = deepcopy(template)
                    self._replace_paragraph(node, line, target.id)
                    target.body.append(node)
            else:
                template = deepcopy(paragraphs[-1]) if paragraphs else etree.Element(self.qa("p"))
                for index, line in enumerate(lines):
                    node = paragraphs[index] if index < len(paragraphs) else deepcopy(template)
                    self._replace_paragraph(node, line, target.id)
                    if index >= len(paragraphs):
                        target.body.append(node)
                for node in paragraphs[len(lines):]:
                    target.body.remove(node)
            # A notes root and its body shape share the same paragraph nodes.
            owners = [item for item in self.targets.values() if item.body is target.body and item.type != "notes"]
            for owner in owners:
                self._sync_paragraphs(owner)
        self.dirty.add(target.part)
        for key in dict.fromkeys([*affected, *self.descendants(target.id)]):
            self.changed_children[key] = "Content updated through the parent target."
        if target.type != "notes" and (len(text) > len(previous) or operation == "append_text"):
            self.warn(f"Text expanded at {target.id}; review wrapping and overflow in PowerPoint.")
        return True

    def remove(self, target):
        if target.readonly or target.type in ("table_cell", "notes", "unsupported", "table"):
            return "Removing this target would damage or alter an unsupported structure."
        if target.type == "slide":
            entry = self.slide_entries[target.id]
            rid = entry.get(self.qr("id"))
            references = [
                node for node in self.main.iter() if node is not entry and node.get(self.qr("id")) == rid
            ]
            for node in references:
                parent = node.getparent()
                show = parent.getparent() if parent is not None else None
                if (
                    node.tag != self.qp("sld") or parent is None or parent.tag != self.qp("sldLst")
                    or show is None or show.tag != self.qp("custShow")
                ):
                    return "An unsupported presentation structure references this slide; it was preserved."
            for node in references:
                parent = node.getparent()
                parent.remove(node)
                show = parent.getparent()
                if not len(parent) and show is not None and show.tag == self.qp("custShow"):
                    shows = show.getparent()
                    shows.remove(show)
                    if not len(shows):
                        self.main.remove(shows)
            section_ns = "{http://schemas.microsoft.com/office/powerpoint/2010/main}"
            for node in list(self.main.iter(section_ns + "sldId")):
                if node.get("id") != entry.get("id"):
                    continue
                parent = node.getparent()
                if parent.tag != section_ns + "sldIdLst":
                    continue
                parent.remove(node)
                section = parent.getparent()
                if not len(parent) and section is not None and section.tag == section_ns + "section":
                    sections = section.getparent()
                    sections.remove(section)
                    if not len(sections):
                        extension = sections.getparent()
                        extension.remove(sections)
                        if extension.tag == self.qp("ext") and not len(extension):
                            extensions = extension.getparent()
                            extensions.remove(extension)
                            if extensions.tag == self.qp("extLst") and not len(extensions):
                                self.main.remove(extensions)
            self.slide_entries.pop(target.id)
            self.slide_list.remove(entry)
            self.rels[self.package.main_part] = [rel for rel in self.relationships(self.package.main_part) if rel["id"] != rid]
            self._write_rels(self.package.main_part)
            self.dirty.add(self.package.main_part)
            # Keep detached parts: other slides/custom XML may still link to them.
            self.warn("Removed slides are excluded from slide order; their package parts remain to preserve existing links.")
        elif target.type in ("shape", "picture", "group", "paragraph"):
            if target.node is None or target.node.getparent() is None:
                return "This target is no longer present."
            ids = {node.get("id") for node in target.node.iter(self.qp("cNvPr"))}
            root = self.root(target.part)
            for node in root.iter():
                if (node.tag == self.qp("spTgt") and node.get("spid") in ids) or (
                    node.tag in (self.qa("stCxn"), self.qa("endCxn")) and node.get("id") in ids
                ):
                    return "Animation or connector references require this shape; it was preserved."
            parent = target.node.getparent()
            parent.remove(target.node)
            if target.type == "paragraph" and not parent.findall(self.qa("p")):
                blank = deepcopy(target.node)
                self._replace_paragraph(blank, "", target.id)
                parent.append(blank)
            self.dirty.add(target.part)
        else:
            return "This target does not support removal."
        removed = [target.id, *self.descendants(target.id)]
        self.removed.extend(removed)
        for key in removed:
            self.targets.pop(key, None)
            if key != target.id:
                self.changed_children[key] = "Removed with the parent target."
        return None

    def image(self, target, source, resolver):
        if target.readonly or target.type != "picture":
            return "Only slide pictures support image replacement."
        if not source.startswith("asset:") or len(source) <= len("asset:"):
            return "Image sources must be authorized asset tokens."
        if resolver is None:
            return "An authorized image resolver is required."
        _check(self.check)
        data = resolver(source)
        _check(self.check)
        if data is None:
            return "The authorized image asset is unavailable."
        if type(data) is dict:
            data = data.get("content")
        if type(data) is not bytes:
            raise DocumentTransformError("invalid_image", "The authorized image asset is invalid.")
        if len(data) > self.limits.max_part_bytes:
            raise DocumentTransformError("resource_limit", "The authorized image exceeds its size limit.")
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(data)) as image:
                    image_format = image.format
                    if image.width * image.height > self.limits.max_xml_nodes * 64:
                        raise DocumentTransformError("resource_limit", "The authorized image exceeds its pixel limit.")
                    image.verify()
        except DocumentTransformError:
            raise
        except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
            raise DocumentTransformError("resource_limit", "The authorized image exceeds its pixel limit.") from exc
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            raise DocumentTransformError("invalid_image", "The authorized image asset cannot be read.") from exc
        formats = {"PNG": ("png", "image/png"), "JPEG": ("jpg", "image/jpeg"), "GIF": ("gif", "image/gif"),
                   "BMP": ("bmp", "image/bmp"), "TIFF": ("tiff", "image/tiff")}
        if image_format not in formats:
            return "This raster image format is not supported."
        blip = target.node.find(f"{self.qp('blipFill')}/{self.qa('blip')}")
        if blip is None:
            placeholder = target.node.find(f"{self.qp('nvSpPr')}/{self.qp('nvPr')}/{self.qp('ph')}")
            if target.node.tag != self.qp("sp") or placeholder is None or placeholder.get("type") != "pic":
                return "This picture has no supported image reference."
            old_node = target.node
            picture = etree.Element(self.qp("pic"), nsmap=old_node.nsmap)
            nv = etree.SubElement(picture, self.qp("nvPicPr"))
            old_nv = old_node.find(self.qp("nvSpPr"))
            nv.append(deepcopy(old_nv.find(self.qp("cNvPr"))))
            locks = etree.SubElement(nv, self.qp("cNvPicPr"))
            etree.SubElement(locks, self.qa("picLocks"), {"noChangeAspect": "1"})
            nv.append(deepcopy(old_nv.find(self.qp("nvPr"))))
            fill = etree.SubElement(picture, self.qp("blipFill"))
            blip = etree.SubElement(fill, self.qa("blip"))
            stretch = etree.SubElement(fill, self.qa("stretch"))
            etree.SubElement(stretch, self.qa("fillRect"))
            props = old_node.find(self.qp("spPr"))
            picture.append(deepcopy(props) if props is not None else etree.Element(self.qp("spPr")))
            old_node.getparent().replace(old_node, picture)
            target.node, target.body = picture, None
            for key in self.descendants(target.id):
                self.targets.pop(key, None)
                self.changed_children[key] = "Replaced with the parent picture placeholder."
        old_rid = blip.get(self.qr("embed"))
        old = next((rel for rel in self.relationships(target.part) if rel["id"] == old_rid), None)
        if old and not old["external"] and self.package.files[old["target"]] == data:
            return False
        extension, content_type = formats[image_format]
        part = f"ppt/media/transform_{hashlib.sha256(data).hexdigest()}.{extension}"
        if part in self.package.files and self.package.files[part] != data:
            _invalid()
        if part not in self.package.files:
            self._store(part, data, content_type)
        rid = self._add_rel(target.part, "image", part)
        blip.set(self.qr("embed"), rid)
        blip.attrib.pop(self.qr("link"), None)
        # Alternate SVG renditions can take precedence over the replaced raster.
        for alternate in list(blip.iter()):
            if isinstance(alternate.tag, str) and etree.QName(alternate).localname == "svgBlip":
                alternate.getparent().remove(alternate)
        self.dirty.add(target.part)
        self.warn(f"Image replaced at {target.id}; original crop and dimensions are retained.")
        return True

    def flush(self):
        for part in sorted(self.dirty):
            _check(self.check)
            root = self.roots[part]
            for count, _node in enumerate(root.iter(), 1):
                if count % 64 == 1:
                    _check(self.check)
                if count > self.limits.max_xml_nodes:
                    raise DocumentTransformError("resource_limit", "An XML document part exceeds its node limit.")
            self.package.write_xml(part, root)


def inspect_package(package, *, limits, check):
    """Inspect actual slides, notes and every presentation-master layout in memory."""
    return _Deck(package, limits, check).inspect()


def transform_package(package, prepared, *, limits, check, image_resolver):
    """Apply supported operations without round-tripping the Presentation object."""
    deck = _Deck(package, limits, check)
    report = {"applied": [], "unchanged": [], "skipped": [], "unresolved": [], "warnings": []}
    for index, operation in enumerate(prepared["operations"]):
        _check(check)
        target = deck.targets.get(operation["target"])
        outcome = {"op_index": index, "target": operation["target"]}
        if target is None:
            result = "The target is unknown or was removed by an earlier operation."
        elif operation["op"] in ("replace_text", "append_text"):
            result = deck.edit_text(target, operation["op"], operation["text"])
        elif operation["op"] == "clone":
            result = deck.clone(target, operation["clone_id"])
        elif operation["op"] == "remove":
            result = deck.remove(target)
        elif operation["op"] == "replace_image":
            result = deck.image(target, operation["source"], image_resolver)
        else:
            result = "This operation is not supported by the PowerPoint adapter."
        if isinstance(result, str):
            outcome["reason"] = result
            report["skipped"].append(outcome)
        elif result is False:
            outcome["reason"] = "The requested content is already present."
            report["unchanged"].append(outcome)
        else:
            report["applied"].append(outcome)
    deck.flush()
    for clone in deck.clones:
        clone["descendants"] = deck.descendants(clone["target"])
    touched = {operation["target"] for operation in prepared["operations"]}
    report["unchanged"].extend(
        {"target": key, "reason": reason}
        for key, reason in deck.changed_children.items() if key not in touched
    )
    report["warnings"] = deck.warnings
    report["metadata"] = {
        "adapter": "pptx-package-v1", "slide_count": len(deck.slide_entries),
        "master_count": len(deck.master_parts), "layout_count": len(deck.layout_records),
        "cloned_targets": deck.clones, "removed_targets": deck.removed,
        "limitations": list(_LIMITATIONS),
        "clone_target_naming": "clone_id replaces the original root; descendant suffixes are retained.",
    }
    return report

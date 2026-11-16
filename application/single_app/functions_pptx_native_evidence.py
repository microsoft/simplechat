# functions_pptx_native_evidence.py
"""Read-only, slide-local object identities and supported solid-color evidence."""

from native_document_evidence import drawing_native_fields, inaccessible_field, native_field


MAX_SLIDE_NATIVE_OBJECTS = 1000


def _local(element):
    return element.tag.rsplit("}", 1)[-1]


def _first(element, name):
    return next((child for child in element.iter() if _local(child) == name), None) if element is not None else None


def _solid_color(element):
    if element is None:
        return inaccessible_field("effective_solid_color_unresolved")
    container = next((child for child in element if _local(child) == "bgPr"), element)
    fill = next((child for child in container if _local(child) == "solidFill"), None)
    color = _first(fill, "srgbClr")
    if color is None or list(color):
        return inaccessible_field("effective_solid_color_unresolved")
    value = color.get("val", "")
    if len(value) != 6 or any(char not in "0123456789abcdefABCDEF" for char in value):
        return inaccessible_field("invalid_native_color")
    return {"state": "present_value", "value": "#" + value.upper()}


def inspect_pptx_slide_objects(root, slide_number, part):
    tree = _first(root, "spTree")
    records = []
    background = _solid_color(_first(root, "bg"))
    supported = {"sp", "pic", "graphicFrame", "cxnSp", "grpSp", "contentPart"}
    truncated = False

    def visit(container, parent_id=None):
        nonlocal truncated
        for element in container:
            kind = _local(element)
            if kind not in supported:
                continue
            if len(records) >= MAX_SLIDE_NATIVE_OBJECTS:
                truncated = True
                return
            nonvisual = next((child for child in element if _local(child).startswith("nv")), None)
            properties = _first(nonvisual, "cNvPr")
            if properties is None:
                records.append({
                    "kind": "unsupported_object", "source_part": part, "slide_number": slide_number,
                    "inspection_status": "inaccessible", "reason": "missing_object_identity",
                })
                continue
            decorative = _first(properties, "decorative")
            placeholder = _first(nonvisual, "ph")
            shape_properties = next((child for child in element if _local(child) in ("spPr", "grpSpPr")), None)
            geometry = _first(shape_properties, "prstGeom")
            transform = _first(shape_properties, "xfrm")
            text = " ".join(
                node.text for child in element if _local(child) == "txBody"
                for node in child.iter() if _local(node) == "t" and node.text
            )
            object_id = str(properties.get("id") or "")
            record = {
                "id": f"pptx:s{slide_number}:object:{object_id}",
                "object_id": object_id, "name": properties.get("name", ""),
                "kind": "picture" if kind == "pic" else "group" if kind == "grpSp"
                else "chart" if kind == "graphicFrame" and _first(element, "chart") is not None
                else "table" if kind == "graphicFrame" and _first(element, "tbl") is not None
                else "shape" if kind in ("sp", "cxnSp") else "unsupported_object",
                "slide_number": slide_number, "source_part": part, "parent_id": parent_id,
                "content_origin": "slide_local", "inspection_status": "complete",
                "geometry": geometry.get("prst") if geometry is not None else None,
                "transform": {
                    "units": "EMU", **dict(transform.attrib),
                    **{f"{_local(child)}_{key}": value for child in transform for key, value in child.attrib.items()},
                } if transform is not None else None,
                "hidden": properties.get("hidden") in ("1", "true"),
                "text": text[:8000], "text_complete": len(text) <= 8000,
                "native_fields": drawing_native_fields(
                    properties.attrib, decorative.attrib if decorative is not None else None,
                ),
                "is_decorative": (
                    True if decorative is not None and decorative.get("val") in ("1", "true")
                    else False if decorative is not None and decorative.get("val") in ("0", "false") else None
                ),
                "placeholder": dict(placeholder.attrib) if placeholder is not None else None,
            }
            if shape_properties is not None and any(_local(child) == "noFill" for child in shape_properties):
                record["background"] = background
                record["background_origin"] = "slide_background"
            else:
                record["background"] = _solid_color(shape_properties)
                record["background_origin"] = "object_fill"
            records.append(record)
            if kind == "grpSp":
                visit(element, record["id"])
    if tree is not None:
        visit(tree)
    return {
        "records": records, "status": "partial" if truncated or tree is None or any(
            item["inspection_status"] != "complete" for item in records
        ) else "complete",
        "scope": "supported slide-local XML objects; not a rendered or master-artwork inventory",
        "background": background,
    }


def pptx_core_native_fields(root):
    fields = {}
    for name in ("title", "creator", "keywords", "subject"):
        element = _first(root, name)
        fields["author" if name == "creator" else name] = {
            **native_field({name: element.text or ""} if element is not None else {}, name),
            "source": f"docProps/core.xml:{name}",
        }
    return fields

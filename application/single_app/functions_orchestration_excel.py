# functions_orchestration_excel.py
"""Read exact native annotation inventories, preserving Excel paging and Word threads."""

import json

from functions_orchestration_results import MAX_VALUE_BYTES


def collect_word_comments(document_id, user_id, *, read_page, cancel_check, source_count=1, **scope):
    cancel_check()
    report = read_page(document_id, user_id, sections="comments", **scope)
    cancel_check()
    inventory = report.get("word_inspection")
    if type(inventory) is not dict or inventory.get("section") != "comments":
        raise LookupError("The native Word comment inventory is unavailable.")
    values, total = inventory.get("records"), inventory.get("total_records")
    if (
        inventory.get("inventory_complete") is not True or type(values) is not list
        or type(total) is not int or total != len(values)
        or type(inventory.get("source_sha256")) is not str
        or any(type(record) is not dict for record in values)
    ):
        raise ValueError("The native Word comment inventory has invalid coverage.")
    budget = MAX_VALUE_BYTES // (4 * max(1, source_count))
    records, used = [], 0
    for record in values:
        cancel_check()
        size = len(json.dumps(record, ensure_ascii=False).encode("utf-8"))
        if used + size > budget:
            break
        records.append(record)
        used += size
    partial = len(records) != total
    return records, {
        "execution_mode": "native_inspection", "section": "comments", "format": report.get("format"),
        "source_sha256": inventory["source_sha256"], "total_records": total,
        "returned_records": len(records), "total_replies": inventory.get("total_replies"),
        "inventory_complete": True, "partial": partial, "pages_read": 1,
        "has_more": partial, "limit_reached": partial, "next_cursor": None,
        "limitations": inventory.get("limitations") or [],
    }


def collect_excel_comments(document_id, user_id, *, read_page, cancel_check, source_count=1, **scope):
    """Keep exact native records, including paginated large-record fragments."""
    cursor = None
    seen = set()
    records = []
    fragment = ""
    digest = None
    total = None
    used = 0
    pages = 0
    # Leave room for evidence/coverage wrappers in the existing retained-value budget.
    budget = MAX_VALUE_BYTES // (4 * max(1, source_count))
    while True:
        cancel_check()
        report = read_page(
            document_id, user_id, native_section="comments", native_cursor=cursor,
            native_page_size=200, _native_max_bytes=65536, **scope,
        )
        page = (report.get("excel_inspection") or {}).get("page")
        if not isinstance(page, dict) or page.get("section") != "comments":
            raise LookupError("The complete native workbook inventory is unavailable.")
        if digest is not None and (page.get("source_sha256"), page.get("total_records")) != (digest, total):
            raise ValueError("The workbook inventory changed during inspection.")
        digest, total = page.get("source_sha256"), page.get("total_records")
        if not isinstance(digest, str) or type(total) is not int or total < 0:
            raise ValueError("The workbook inventory has invalid coverage.")
        pages += 1
        values = page.get("records")
        if not isinstance(values, list):
            raise ValueError("The workbook inventory has invalid records.")
        for value in values:
            if not isinstance(value, dict):
                raise ValueError("The workbook inventory has invalid records.")
            if value.get("record_fragment"):
                if value.get("fragment_offset") != len(fragment):
                    raise ValueError("The workbook annotation continuation is invalid.")
                fragment += value["record_json_fragment"]
                if len(fragment.encode("utf-8")) > budget:
                    break
                if len(fragment) < value["record_characters"]:
                    continue
                value = json.loads(fragment)
                fragment = ""
            elif fragment:
                raise ValueError("The workbook annotation continuation is incomplete.")
            size = len(json.dumps(value, ensure_ascii=False).encode("utf-8"))
            if used + size > budget:
                break
            records.append(value)
            used += size
        else:
            next_cursor = page.get("next_cursor")
            if not page.get("has_more"):
                if fragment or len(records) != total:
                    raise ValueError("The workbook annotation inventory is incomplete.")
                break
            if not isinstance(next_cursor, str) or not next_cursor or next_cursor in seen:
                raise ValueError("The workbook annotation continuation is invalid.")
            seen.add(next_cursor)
            cursor = next_cursor
            if used + len(fragment.encode("utf-8")) <= budget:
                continue
        # A resource bound is partial evidence, never a workbook with no comments.
        break
    partial = bool(page.get("has_more") or fragment or len(records) != total or not page.get("inventory_complete"))
    coverage = {
        "execution_mode": "native_inspection", "section": "comments",
        "source_sha256": digest, "total_records": total, "returned_records": len(records),
        "inventory_complete": bool(page.get("inventory_complete")),
        "partial": partial, "pages_read": pages,
        "next_cursor": cursor if partial else None,
        "has_more": bool(page.get("has_more") or len(records) != total),
        "limit_reached": bool(fragment or len(records) != total),
        "worksheet_data_computed": False,
        "limitations": (report.get("accessibility_metadata") or {}).get("coverage"),
    }
    return records, coverage

# functions_orchestration_excel.py
"""Read authorized Excel annotation inventories, not worksheet-row previews."""

import json

from functions_orchestration_results import MAX_VALUE_BYTES


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

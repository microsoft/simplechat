# functions_orchestration_excel.py
"""Read exact native annotation inventories, preserving Excel paging and Word threads."""

import json

from functions_orchestration_results import MAX_VALUE_BYTES


WORD_COMMENT_PROVENANCE_COLUMNS = (
    "comment_thread_id", "comment_author", "comment_date", "reply_ids", "comment_replies",
)


def project_word_comment_provenance(records, prepared, source_ids):
    """Project authorized native Word thread metadata onto exact disposition rows."""
    if (
        type(records) is not list
        or type(prepared) is not dict
        or prepared.get("version") != "orchestration-gathered-content-v1"
        or prepared.get("capability_id") != "document_search"
        or prepared.get("content_scope") != "native_document_annotations"
    ):
        raise ValueError("The native Word comment provenance input is invalid.")
    coverage = (prepared.get("coverage") or {}).get("native_inspection")
    if (
        type(coverage) is not list or not coverage
        or any(
            type(item) is not dict
            or item.get("format") not in ("docx", "docm", "dotx")
            or item.get("section") != "comments"
            or item.get("execution_mode") != "native_inspection"
            or item.get("inventory_complete") is not True
            or item.get("partial") is True
            for item in coverage
        )
    ):
        raise ValueError("The native Word comment inventory is incomplete.")
    authorized = set(source_ids or ())
    covered = {item.get("document_id") for item in coverage}
    if not authorized or covered != authorized:
        raise ValueError("The native Word comment source set does not match its authorized lineage.")
    counts = [item.get("total_records") for item in coverage]
    if any(
        type(value) is not int or value < 0
        for value in counts
    ):
        raise ValueError("The native Word comment inventory has an invalid root count.")
    inventory = {}
    duplicates = set()
    for hit in prepared.get("search_results") or []:
        if not isinstance(hit, dict) or hit.get("document_id") not in authorized:
            continue
        try:
            payload = json.loads(hit.get("chunk_text") or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            raise ValueError("The native Word comment evidence is invalid.") from None
        comment = payload.get("word_annotation") if isinstance(payload, dict) else None
        if comment is None:
            continue
        if not isinstance(comment, dict) or not isinstance(comment.get("id"), str):
            raise ValueError("The native Word comment evidence is invalid.")
        key = (hit["document_id"], comment["id"])
        if key in inventory:
            duplicates.add(key)
        inventory[key] = comment
    expected_root_count = sum(counts)
    if duplicates or expected_root_count != len(inventory):
        raise ValueError("The native Word comment identity inventory is invalid.")
    expected = set(inventory)
    seen = set()
    projected = []
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("A disposition row is invalid.")
        thread_id = record.get("comment_thread_id")
        if not isinstance(thread_id, str):
            raise ValueError("A disposition row has no exact native comment identity.")
        declared_source = record.get("comment_document_id")
        if isinstance(declared_source, str) and declared_source:
            key = (declared_source, thread_id)
        else:
            matches = [candidate for candidate in inventory if candidate[1] == thread_id]
            if len(matches) != 1:
                raise ValueError("A disposition row cannot be matched to one authorized Word source.")
            key = matches[0]
        comment = inventory.get(key)
        if comment is None or key in seen:
            raise ValueError("A disposition row names an unknown or duplicate native comment.")
        seen.add(key)
        replies = comment.get("replies")
        if not isinstance(replies, list) or any(not isinstance(reply, dict) for reply in replies):
            raise ValueError("The native Word reply inventory is invalid.")
        reply_ids = json.dumps([reply.get("id") for reply in replies], separators=(",", ":"), ensure_ascii=False)
        reply_metadata = json.dumps([
            {
                name: reply.get(name)
                for name in ("id", "author", "initials", "date", "text", "done", "resolution_available")
                if name in reply
            }
            for reply in replies
        ], sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        values = {
            "comment_thread_id": comment["id"],
            "comment_author": comment.get("author"),
            "comment_date": comment.get("date"),
            "reply_ids": reply_ids,
            "comment_replies": reply_metadata,
        }
        for name, value in values.items():
            supplied = record.get(name)
            if supplied not in (None, "") and supplied != value:
                raise ValueError("A disposition row contains invented comment metadata.")
        projected.append({**record, **values})
    if seen != expected:
        raise ValueError("The disposition records do not cover every native Word root comment.")
    return projected


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

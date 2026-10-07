# cosmos_query_guard.py
"""Reject Cosmos SQL shapes that the azure-cosmos Python SDK cannot run across partitions.

The SDK asks the gateway for a query plan and lists the features it can execute
(Aggregate, CompositeAggregate, Distinct, MultipleOrderBy, OffsetAndLimit, OrderBy, Top
and a few others). GroupBy and DCount are not on that list, so a cross-partition query
that needs them fails with HTTP 400 before it runs. An ORDER BY over more than one
property also fails with HTTP 400 unless the container declares a matching composite
index. Fake containers accept any SQL, so tests run their queries through this guard.
"""

import re


GROUP_BY_PATTERN = re.compile(r"\bGROUP\s+BY\b", re.IGNORECASE)
DISTINCT_COUNT_PATTERN = re.compile(
    r"\bCOUNT\s*\(\s*DISTINCT\b|\bCOUNT\s*\([^()]*\)\s*FROM\s*\(\s*SELECT\s+DISTINCT\b",
    re.IGNORECASE,
)
ORDER_BY_PATTERN = re.compile(
    r"\bORDER\s+BY\b(?P<items>.*?)(?=\bOFFSET\b|\bLIMIT\b|\)|$)",
    re.IGNORECASE | re.DOTALL,
)
ORDER_ITEM_PATTERN = re.compile(r"^(?P<expression>.+?)(?:\s+(?P<direction>ASC|DESC))?$", re.IGNORECASE | re.DOTALL)
PROPERTY_PATH_PATTERN = re.compile(r"^c((?:\.[A-Za-z_][A-Za-z0-9_]*)+)$")


def _split_order_items(items):
    parts, depth, current = [], 0, []
    for character in items:
        if character in "([{":
            depth += 1
        elif character in ")]}":
            depth -= 1
        if character == "," and depth == 0:
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(character)
    parts.append("".join(current).strip())
    return [part for part in parts if part]


def _order_item(item):
    match = ORDER_ITEM_PATTERN.match(item.strip())
    expression = match.group("expression").strip()
    direction = "descending" if (match.group("direction") or "").upper() == "DESC" else "ascending"
    path_match = PROPERTY_PATH_PATTERN.match(expression)
    path = path_match.group(1).replace(".", "/") if path_match else None
    return path, direction


def _served_by_composite_index(order_items, composite_indexes):
    """A composite index serves its exact path order in its own or fully reversed directions."""
    requested = [_order_item(item) for item in order_items]
    if any(path is None for path, _ in requested):
        return False
    for index in composite_indexes:
        declared = [(entry[0], entry[1]) for entry in index]
        if [path for path, _ in declared] != [path for path, _ in requested]:
            continue
        same = all(want == have for (_, want), (_, have) in zip(requested, declared))
        reversed_ = all(want != have for (_, want), (_, have) in zip(requested, declared))
        if same or reversed_:
            return True
    return False


def cosmos_query_problems(query, composite_indexes=()):
    """Return why a cross-partition query would be rejected, or an empty list."""
    problems = []
    if GROUP_BY_PATTERN.search(query):
        problems.append("cross-partition GROUP BY is not supported by the Python SDK")
    if DISTINCT_COUNT_PATTERN.search(query):
        problems.append("COUNT over DISTINCT values (DCount) is not supported by the Python SDK")
    for match in ORDER_BY_PATTERN.finditer(query):
        items = _split_order_items(match.group("items"))
        if len(items) > 1 and not _served_by_composite_index(items, composite_indexes):
            problems.append(
                f"ORDER BY on {len(items)} properties needs a declared composite index: {', '.join(items)}"
            )
    return problems


def assert_cosmos_query_supported(query, composite_indexes=()):
    """Fail the calling test when a query shape cannot run through the Python SDK."""
    problems = cosmos_query_problems(query, composite_indexes)
    if problems:
        raise AssertionError(f"Unsupported Cosmos query ({'; '.join(problems)}): {' '.join(query.split())}")

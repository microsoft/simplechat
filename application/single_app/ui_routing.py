# ui_routing.py
"""Map classic (server-rendered) page URLs to their V2 (React, /v2) counterparts, and back.

SimpleChat serves two interfaces from one backend: the classic Jinja pages and the React V2
single-page application under ``/v2``. ``ui_route_map.json`` lists every classic page route
and the V2 route that replaces it. This module loads and validates that file and answers the
two questions the interface selector needs:

* ``resolve_v2_target``: where does this classic URL lead in V2? It feeds a classic to V2 edge
  redirect, so stored notification links, emails and bookmarks keep working.
* ``resolve_classic_target``: where is the classic version of this V2 URL? It feeds an
  "open this page in classic" link.

Only rows whose status is ``native``, ``alias`` or ``partial`` resolve. ``native`` and
``partial`` rows have a V2 page that can take the visitor (``partial`` still hands part of the
page to classic, which the row's notes say). ``alias`` rows are classic routes that only
redirect to another classic page, so they resolve to the V2 page of that target. A ``gap`` row
names a planned V2 route that does not exist yet, so following it would land on a page that is
not there; ``standalone``, ``deliberate``, ``dead`` and ``api_surface`` rows have no V2 page by
definition. Those all answer ``None`` and the classic page keeps serving the request.

Every URL this module returns is a same-site absolute path built from registry data and
validated path segments. A caller-supplied path that is not a plain same-site path (anything
with a scheme or host, ``//host``, backslashes, control characters, dot segments or encoded
slashes and dots) is refused, and only the query keys a row maps are carried across.

The module is pure: it reads one JSON file next to itself and imports neither Flask, settings
nor the network, so tests and scripts can load it without standing up the application.
"""

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from urllib.parse import parse_qsl, quote, unquote, urlencode


UI_ROUTE_MAP_PATH = Path(__file__).resolve().with_name("ui_route_map.json")
UI_ROUTE_MAP_SCHEMA_VERSION = 1

# The router basename the V2 application is served under (route_frontend_v2.py).
V2_BASE_PATH = "/v2"

STATUS_NATIVE = "native"
STATUS_ALIAS = "alias"
STATUS_PARTIAL = "partial"
STATUS_GAP = "gap"
STATUS_STANDALONE = "standalone"
STATUS_DELIBERATE = "deliberate"
STATUS_DEAD = "dead"
STATUS_API_SURFACE = "api_surface"

ROUTE_STATUSES = (
    STATUS_NATIVE,
    STATUS_ALIAS,
    STATUS_PARTIAL,
    STATUS_GAP,
    STATUS_STANDALONE,
    STATUS_DELIBERATE,
    STATUS_DEAD,
    STATUS_API_SURFACE,
)
RESOLVABLE_STATUSES = (STATUS_NATIVE, STATUS_ALIAS, STATUS_PARTIAL)
# These have no V2 page, so their `v2` must be null.
NO_V2_PAGE_STATUSES = (STATUS_STANDALONE, STATUS_DELIBERATE, STATUS_DEAD, STATUS_API_SURFACE)
HTTP_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")

# Field order of a row, used to render the registry the same way everywhere.
ROW_FIELDS = (
    "key",
    "classic",
    "methods",
    "classic_only_query",
    "status",
    "v2",
    "v2_query",
    "v2_subroutes",
    "v2_reserved",
    "path_params",
    "query_map",
    "hash_map",
    "templates",
    "alias_target",
    "plan_ref",
    "notes",
)
REQUIRED_ROW_FIELDS = ("key", "classic", "methods", "status", "v2")

MAX_PATH_LENGTH = 2048
MAX_SEGMENT_LENGTH = 256
MAX_QUERY_LENGTH = 4096
MAX_QUERY_FIELDS = 64
MAX_QUERY_VALUE_LENGTH = 1024
MAX_FRAGMENT_LENGTH = 256

_KEY_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_CLASSIC_TOKEN_RE = re.compile(r"<(?:(?P<converter>[a-z_]+):)?(?P<name>[A-Za-z_][A-Za-z0-9_]*)>")
_CLASSIC_LITERAL_RE = re.compile(r"[A-Za-z0-9/_.~-]*")
_V2_SEGMENT_RE = re.compile(r":(?P<param>[A-Za-z_][A-Za-z0-9_]*)|(?P<literal>[A-Za-z0-9._~-]+)")
_QUERY_KEY_RE = re.compile(r"[A-Za-z0-9_.-]{1,64}")
_FRAGMENT_KEY_RE = re.compile(r"[A-Za-z0-9_.:~-]{1,128}")
_SUFFIX_RE = re.compile(r"(?:/[A-Za-z0-9._~-]+)+")
_TEMPLATE_RE = re.compile(r"[A-Za-z0-9_]+(?:/[A-Za-z0-9_]+)*\.html")
# A path segment this module is willing to copy: unreserved characters and percent escapes.
_SAFE_SEGMENT_RE = re.compile(r"(?:[A-Za-z0-9._~-]|%[0-9A-Fa-f]{2})+")
# Escapes that change what a path means once decoded: dot, slash, backslash and controls.
_FORBIDDEN_ESCAPE_RE = re.compile(r"%(?:2e|2f|5c|[01][0-9a-f]|7f)", re.IGNORECASE)
_CONVERTER_PATTERNS = {"string": "[^/]+", "path": ".+", "int": "[0-9]+"}


class UiRouteMapError(ValueError):
    """The registry is malformed. ``problems`` lists every issue found, one sentence each."""

    def __init__(self, source, problems):
        self.source = source
        self.problems = tuple(problems)
        lines = "\n".join(f"  - {problem}" for problem in self.problems)
        super().__init__(
            f"{source} is malformed ({len(self.problems)} problem"
            f"{'' if len(self.problems) == 1 else 's'}):\n{lines}\n"
            "Fix the rows above, then see docs\\explanation\\features\\V2_CLASSIC_PAGE_PARITY.md "
            "for the row schema."
        )


@dataclass(frozen=True)
class V2Pattern:
    """A V2 route pattern split into segments: ``(is_param, text)`` pairs."""

    text: str
    segments: tuple
    literal_count: int
    param_names: tuple


@dataclass(frozen=True)
class QueryRule:
    """How one classic query key crosses to V2."""

    classic_key: str
    to: str = None
    values: dict = None
    local_path: bool = False
    path: dict = None


@dataclass(frozen=True, eq=False)
class UiRoute:
    """One validated registry row plus what resolving it needs."""

    index: int
    key: str
    classic: str
    methods: tuple
    classic_only_query: dict
    status: str
    v2: str
    v2_query: dict
    v2_subroutes: tuple
    v2_reserved: dict
    path_params: dict
    query_map: dict
    hash_map: dict
    templates: tuple
    alias_target: str
    plan_ref: str
    notes: str
    classic_regex: re.Pattern = field(repr=False, default=None)
    classic_params: tuple = ()
    classic_static_length: int = 0
    v2_patterns: tuple = ()
    reverse_query: dict = field(repr=False, default_factory=dict)
    reverse_suffixes: tuple = field(repr=False, default=())
    reverse_hash_queries: tuple = field(repr=False, default=())
    raw: dict = field(repr=False, default_factory=dict)

    @property
    def resolvable(self):
        return self.status in RESOLVABLE_STATUSES and self.v2 is not None

    @property
    def v2_param_names(self):
        return self.v2_patterns[0].param_names if self.v2_patterns else ()


class UiRouteMap:
    """The validated registry: rows in file order, plus lookups by key."""

    def __init__(self, routes, source):
        self.routes = tuple(routes)
        self.source = source
        self._by_key = {route.key: route for route in self.routes}

    def get(self, key):
        return self._by_key.get(key)

    def to_rows(self):
        """The rows as plain dictionaries in canonical field order, ready to serialize."""
        return [json.loads(json.dumps(route.raw)) for route in self.routes]


# ---------------------------------------------------------------------------
# Loading and validation
# ---------------------------------------------------------------------------

def _compile_classic_rule(rule):
    """Return ``(regex, param_names, static_length)`` for a Flask rule, or raise ValueError."""
    if not isinstance(rule, str) or not rule.startswith("/"):
        raise ValueError("must be a Flask rule that starts with '/'")
    if "//" in rule:
        raise ValueError("must not contain '//'")
    parts = []
    names = []
    static_length = 0
    position = 0
    for token in _CLASSIC_TOKEN_RE.finditer(rule):
        literal = rule[position:token.start()]
        if not _CLASSIC_LITERAL_RE.fullmatch(literal):
            raise ValueError(f"has characters this module does not support around {literal!r}")
        parts.append(re.escape(literal))
        static_length += len(literal)
        converter = token.group("converter") or "string"
        if converter not in _CONVERTER_PATTERNS:
            raise ValueError(
                f"uses the unsupported converter {converter!r} "
                f"(supported: {', '.join(sorted(_CONVERTER_PATTERNS))})"
            )
        name = token.group("name")
        if name in names:
            raise ValueError(f"repeats the placeholder <{name}>")
        names.append(name)
        parts.append(f"(?P<{name}>{_CONVERTER_PATTERNS[converter]})")
        position = token.end()
    tail = rule[position:]
    if not _CLASSIC_LITERAL_RE.fullmatch(tail):
        raise ValueError(f"has characters this module does not support in {tail!r}")
    parts.append(re.escape(tail))
    static_length += len(tail)
    return re.compile("".join(parts)), tuple(names), static_length


def _parse_v2_pattern(pattern):
    """Split a V2 route pattern (relative to /v2) into segments, or raise ValueError."""
    if not isinstance(pattern, str) or not pattern.startswith("/"):
        raise ValueError("must be a route path that starts with '/'")
    if pattern == "/":
        return V2Pattern(text=pattern, segments=(), literal_count=0, param_names=())
    segments = []
    names = []
    for text in pattern[1:].split("/"):
        match = _V2_SEGMENT_RE.fullmatch(text)
        if not match:
            raise ValueError(
                f"has the segment {text!r}; use letters, digits, '.', '_', '~', '-' or a :param"
            )
        if match.group("param"):
            name = match.group("param")
            if name in names:
                raise ValueError(f"repeats the parameter :{name}")
            names.append(name)
            segments.append((True, name))
        else:
            segments.append((False, match.group("literal")))
    literal_count = sum(1 for is_param, _ in segments if not is_param)
    return V2Pattern(
        text=pattern,
        segments=tuple(segments),
        literal_count=literal_count,
        param_names=tuple(names),
    )


def _is_text(value, maximum=512):
    return isinstance(value, str) and 0 < len(value) <= maximum and not _has_control(value)


def _has_control(value):
    return any(ord(char) < 0x20 or ord(char) == 0x7F for char in value)


def _string_map(value, label, problems, key_re=None, maximum=256):
    """Validate a ``{text: text}`` object and return it as a dict, or None after reporting."""
    if not isinstance(value, dict) or not value:
        problems.append(f"{label} must be a non-empty object of text values.")
        return None
    clean = {}
    ok = True
    for item_key, item_value in value.items():
        if key_re is not None and not (isinstance(item_key, str) and key_re.fullmatch(item_key)):
            problems.append(f"{label} has the key {item_key!r}, which is not allowed here.")
            ok = False
        elif not _is_text(item_key, maximum):
            problems.append(f"{label} has an empty or oversized key.")
            ok = False
        if not _is_text(item_value, maximum):
            problems.append(f"{label}[{item_key!r}] must be non-empty text of at most {maximum} characters.")
            ok = False
        clean[item_key] = item_value
    return clean if ok else None


def _parse_query_map(value, label, problems):
    if not isinstance(value, dict) or not value:
        problems.append(f"{label} must be a non-empty object.")
        return None
    rules = {}
    for classic_key, spec in value.items():
        where = f"{label}[{classic_key!r}]"
        if not (isinstance(classic_key, str) and _QUERY_KEY_RE.fullmatch(classic_key)):
            problems.append(f"{where} is not a usable query key.")
            continue
        if isinstance(spec, str):
            if not _QUERY_KEY_RE.fullmatch(spec):
                problems.append(f"{where} maps to {spec!r}, which is not a usable query key.")
                continue
            rules[classic_key] = QueryRule(classic_key=classic_key, to=spec)
            continue
        if not isinstance(spec, dict):
            problems.append(f"{where} must be a V2 key (text) or an object with 'to' or 'path'.")
            continue
        unknown = sorted(set(spec) - {"to", "values", "path", "local_path"})
        if unknown:
            problems.append(f"{where} has unknown fields {unknown}; use to, values, local_path or path.")
            continue
        has_to = "to" in spec
        has_path = "path" in spec
        if has_to == has_path:
            problems.append(f"{where} must have exactly one of 'to' (rename the key) or 'path' (add a route segment).")
            continue
        if has_path:
            if "values" in spec or "local_path" in spec:
                problems.append(f"{where} uses 'path', which does not combine with 'values' or 'local_path'.")
                continue
            mapping = _string_map(spec["path"], f"{where}.path", problems)
            if mapping is None:
                continue
            bad = [item for item in mapping.values() if not _SUFFIX_RE.fullmatch(item)]
            if bad:
                problems.append(f"{where}.path has {bad[0]!r}; route segments look like '/tags'.")
                continue
            rules[classic_key] = QueryRule(classic_key=classic_key, path=mapping)
            continue
        if not (isinstance(spec["to"], str) and _QUERY_KEY_RE.fullmatch(spec["to"])):
            problems.append(f"{where}.to must be a usable query key.")
            continue
        values = None
        if "values" in spec:
            values = _string_map(spec["values"], f"{where}.values", problems, maximum=128)
            if values is None:
                continue
        local_path = spec.get("local_path", False)
        if not isinstance(local_path, bool):
            problems.append(f"{where}.local_path must be true or false.")
            continue
        rules[classic_key] = QueryRule(
            classic_key=classic_key, to=spec["to"], values=values, local_path=local_path,
        )
    return rules


def _parse_hash_map(value, label, problems):
    if not isinstance(value, dict) or not value:
        problems.append(f"{label} must be a non-empty object.")
        return None
    entries = {}
    for fragment, spec in value.items():
        where = f"{label}[{fragment!r}]"
        if not (isinstance(fragment, str) and _FRAGMENT_KEY_RE.fullmatch(fragment)):
            problems.append(f"{where} is not a usable fragment name (without the '#').")
            continue
        if not isinstance(spec, dict) or not spec:
            problems.append(f"{where} must be an object with 'path' and/or 'query'.")
            continue
        unknown = sorted(set(spec) - {"path", "query"})
        if unknown:
            problems.append(f"{where} has unknown fields {unknown}; use path or query.")
            continue
        entry = {}
        if "path" in spec:
            if not (isinstance(spec["path"], str) and _SUFFIX_RE.fullmatch(spec["path"])):
                problems.append(f"{where}.path must be a route segment such as '/documents'.")
                continue
            entry["path"] = spec["path"]
        if "query" in spec:
            query = _string_map(spec["query"], f"{where}.query", problems, key_re=_QUERY_KEY_RE)
            if query is None:
                continue
            entry["query"] = query
        entries[fragment] = entry
    return entries


def _parse_row(index, row, problems):
    """Validate one row. Returns a UiRoute, or None after reporting every problem found."""
    key_text = row.get("key") if isinstance(row, dict) else None
    label = f"row {index + 1} ({key_text!r})" if isinstance(key_text, str) else f"row {index + 1}"
    if not isinstance(row, dict):
        problems.append(f"{label} must be an object.")
        return None

    start = len(problems)
    unknown = sorted(set(row) - set(ROW_FIELDS))
    if unknown:
        problems.append(f"{label} has unknown fields {unknown}; the fields are {', '.join(ROW_FIELDS)}.")
    missing = [name for name in REQUIRED_ROW_FIELDS if name not in row]
    if missing:
        problems.append(f"{label} is missing required fields {missing}.")
        return None

    key = row["key"]
    if not (isinstance(key, str) and _KEY_RE.fullmatch(key)):
        problems.append(f"{label} needs a kebab-case `key` such as 'group-manage'.")
    status = row["status"]
    if status not in ROUTE_STATUSES:
        problems.append(f"{label} has status {status!r}; use one of: {', '.join(ROUTE_STATUSES)}.")
    methods = row["methods"]
    if (
        not isinstance(methods, list) or not methods
        or any(method not in HTTP_METHODS for method in methods)
        or len(set(methods)) != len(methods)
    ):
        problems.append(f"{label} `methods` must be a non-empty list of unique upper-case HTTP methods ({', '.join(HTTP_METHODS)}).")
        methods = []

    classic_regex = None
    classic_params = ()
    static_length = 0
    try:
        classic_regex, classic_params, static_length = _compile_classic_rule(row["classic"])
    except ValueError as error:
        problems.append(f"{label} `classic` {error}.")

    v2 = row["v2"]
    base_pattern = None
    if v2 is not None:
        try:
            base_pattern = _parse_v2_pattern(v2)
        except ValueError as error:
            problems.append(f"{label} `v2` {error}.")
    if status in RESOLVABLE_STATUSES and v2 is None:
        problems.append(f"{label} is {status}, so it needs a `v2` route to resolve to.")
    if status in NO_V2_PAGE_STATUSES and v2 is not None:
        problems.append(f"{label} is {status}, which has no V2 page; set `v2` to null.")

    v2_query = {}
    if "v2_query" in row:
        parsed = _string_map(row["v2_query"], f"{label} `v2_query`", problems, key_re=_QUERY_KEY_RE)
        v2_query = parsed or {}

    classic_only_query = {}
    if "classic_only_query" in row:
        parsed = _string_map(row["classic_only_query"], f"{label} `classic_only_query`", problems, key_re=_QUERY_KEY_RE)
        classic_only_query = parsed or {}

    patterns = [base_pattern] if base_pattern is not None else []
    subroutes = []
    if "v2_subroutes" in row:
        raw_subroutes = row["v2_subroutes"]
        if not isinstance(raw_subroutes, list) or not raw_subroutes:
            problems.append(f"{label} `v2_subroutes` must be a non-empty list of V2 route patterns.")
        elif base_pattern is None:
            problems.append(f"{label} `v2_subroutes` needs a `v2` route to extend.")
        else:
            for text in raw_subroutes:
                try:
                    pattern = _parse_v2_pattern(text)
                except ValueError as error:
                    problems.append(f"{label} `v2_subroutes` entry {text!r} {error}.")
                    continue
                base_length = len(base_pattern.segments)
                if (
                    len(pattern.segments) <= base_length
                    or pattern.segments[:base_length] != base_pattern.segments
                ):
                    problems.append(
                        f"{label} `v2_subroutes` entry {text!r} must extend `v2` ({v2!r}) with more segments."
                    )
                    continue
                if text in subroutes:
                    problems.append(f"{label} `v2_subroutes` lists {text!r} twice.")
                    continue
                subroutes.append(text)
                patterns.append(pattern)

    reserved = {}
    if "v2_reserved" in row:
        raw_reserved = row["v2_reserved"]
        if not isinstance(raw_reserved, dict) or not raw_reserved:
            problems.append(f"{label} `v2_reserved` must be an object of parameter name to a list of values.")
        else:
            known = {name for pattern in patterns for name in pattern.param_names}
            for param, values in raw_reserved.items():
                if param not in known:
                    problems.append(f"{label} `v2_reserved` names :{param}, which is not a parameter of `v2` or its `v2_subroutes`.")
                elif (
                    not isinstance(values, list) or not values
                    or any(not (isinstance(item, str) and _SAFE_SEGMENT_RE.fullmatch(item)) for item in values)
                ):
                    problems.append(f"{label} `v2_reserved`[{param!r}] must be a non-empty list of path segments.")
                else:
                    reserved[param] = tuple(values)

    path_params = {}
    if "path_params" in row:
        parsed = _string_map(row["path_params"], f"{label} `path_params`", problems)
        path_params = parsed or {}
        for classic_name, v2_name in path_params.items():
            if classic_name not in classic_params:
                problems.append(f"{label} `path_params` names <{classic_name}>, which is not a placeholder of `classic`.")
            if base_pattern is None or v2_name not in base_pattern.param_names:
                problems.append(f"{label} `path_params` maps to :{v2_name}, which is not a parameter of `v2`.")
    if status in RESOLVABLE_STATUSES and base_pattern is not None:
        unfed = [name for name in base_pattern.param_names if name not in path_params.values()]
        unmapped = [name for name in classic_params if name not in path_params]
        if unfed:
            problems.append(f"{label} `v2` has :{unfed[0]}, which no entry of `path_params` supplies.")
        if unmapped:
            problems.append(f"{label} `classic` has <{unmapped[0]}>, which `path_params` does not map to a V2 parameter.")

    query_map = {}
    if "query_map" in row:
        query_map = _parse_query_map(row["query_map"], f"{label} `query_map`", problems) or {}
    hash_map = {}
    if "hash_map" in row:
        hash_map = _parse_hash_map(row["hash_map"], f"{label} `hash_map`", problems) or {}

    templates = ()
    if "templates" in row:
        raw_templates = row["templates"]
        if (
            not isinstance(raw_templates, list) or not raw_templates
            or any(not (isinstance(item, str) and _TEMPLATE_RE.fullmatch(item)) for item in raw_templates)
        ):
            problems.append(f"{label} `templates` must be a non-empty list of template file names such as 'chats.html'.")
        else:
            templates = tuple(raw_templates)

    alias_target = None
    if "alias_target" in row:
        target = row["alias_target"]
        if not (_is_text(target) and target.startswith("/") and not target.startswith("//") and "\\" not in target):
            problems.append(f"{label} `alias_target` must be a same-site path such as '/profile?tab=groups'.")
        else:
            alias_target = target

    plan_ref = row.get("plan_ref")
    if "plan_ref" in row and not _is_text(plan_ref):
        problems.append(f"{label} `plan_ref` must be non-empty text.")
        plan_ref = None
    notes = row.get("notes")
    if "notes" in row and not _is_text(notes, maximum=4000):
        problems.append(f"{label} `notes` must be non-empty text.")
        notes = None

    if len(problems) > start:
        return None

    raw = {name: row[name] for name in ROW_FIELDS if name in row}
    reverse_query = {}
    for classic_key, rule in query_map.items():
        if rule.path is not None or rule.to in reverse_query:
            continue
        reverse_values = None
        if rule.values is not None:
            reverse_values = {}
            for classic_value, v2_value in rule.values.items():
                reverse_values.setdefault(v2_value, classic_value)
        reverse_query[rule.to] = QueryRule(
            classic_key=classic_key, to=rule.to, values=reverse_values, local_path=rule.local_path,
        )
    reverse_suffixes = []
    reverse_hash_queries = []
    for fragment, entry in hash_map.items():
        if "path" in entry:
            reverse_suffixes.append((tuple(entry["path"][1:].split("/")), "hash", fragment))
        elif "query" in entry:
            reverse_hash_queries.append((tuple(entry["query"].items()), fragment))
    for classic_key, rule in query_map.items():
        if rule.path is not None:
            for classic_value, suffix in rule.path.items():
                reverse_suffixes.append((tuple(suffix[1:].split("/")), "query", (classic_key, classic_value)))

    return UiRoute(
        index=index,
        key=key,
        classic=row["classic"],
        methods=tuple(methods),
        classic_only_query=classic_only_query,
        status=status,
        v2=v2,
        v2_query=v2_query,
        v2_subroutes=tuple(subroutes),
        v2_reserved=reserved,
        path_params=path_params,
        query_map=query_map,
        hash_map=hash_map,
        templates=templates,
        alias_target=alias_target,
        plan_ref=plan_ref,
        notes=notes,
        classic_regex=classic_regex,
        classic_params=classic_params,
        classic_static_length=static_length,
        v2_patterns=tuple(patterns),
        reverse_query=reverse_query,
        reverse_suffixes=tuple(reverse_suffixes),
        reverse_hash_queries=tuple(reverse_hash_queries),
        raw=raw,
    )


def parse_ui_route_map(data, source=UI_ROUTE_MAP_PATH.name):
    """Validate registry data (the parsed JSON) and return a ``UiRouteMap``.

    Every problem found is reported in one ``UiRouteMapError``, so a contributor fixes the
    file once instead of once per run. Only structure that resolving relies on is checked
    here; whether rows are documented well enough is the parity guard test's concern.
    """
    problems = []
    if not isinstance(data, dict):
        raise UiRouteMapError(source, ["The top level must be an object with `schema_version` and `routes`."])
    if data.get("schema_version") != UI_ROUTE_MAP_SCHEMA_VERSION:
        problems.append(
            f"`schema_version` is {data.get('schema_version')!r}; this module reads version {UI_ROUTE_MAP_SCHEMA_VERSION}."
        )
    rows = data.get("routes")
    if not isinstance(rows, list) or not rows:
        problems.append("`routes` must be a non-empty list of rows.")
        raise UiRouteMapError(source, problems)

    routes = []
    for index, row in enumerate(rows):
        route = _parse_row(index, row, problems)
        if route is not None:
            routes.append(route)

    seen_keys = {}
    seen_rules = {}
    for route in routes:
        if route.key in seen_keys:
            problems.append(f"The key {route.key!r} is used by row {seen_keys[route.key] + 1} and row {route.index + 1}; keys must be unique.")
        seen_keys.setdefault(route.key, route.index)
        for method in route.methods:
            rule_key = (route.classic, method)
            if rule_key in seen_rules:
                problems.append(
                    f"{method} {route.classic} appears in row {seen_rules[rule_key] + 1} and row {route.index + 1}; "
                    "each classic route and method needs exactly one row."
                )
            seen_rules.setdefault(rule_key, route.index)
    if problems:
        raise UiRouteMapError(source, problems)
    return UiRouteMap(routes, source)


@lru_cache(maxsize=4)
def _load_cached(path_text):
    path = Path(path_text)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise UiRouteMapError(path.name, [f"The file could not be read ({type(error).__name__})."]) from error
    except json.JSONDecodeError as error:
        raise UiRouteMapError(
            path.name, [f"The file is not valid JSON (line {error.lineno}, column {error.colno}: {error.msg})."],
        ) from error
    return parse_ui_route_map(data, source=path.name)


def load_ui_route_map(path=None):
    """Return the validated registry. The result is cached per file for the life of the process."""
    return _load_cached(str(Path(path) if path is not None else UI_ROUTE_MAP_PATH))


def clear_ui_route_map_cache():
    """Forget loaded registries, for tests that rewrite the file."""
    _load_cached.cache_clear()


# ---------------------------------------------------------------------------
# Input hygiene
# ---------------------------------------------------------------------------

def _clean_request_path(path):
    """Return ``path`` when it is a plain same-site path this module may act on, else None."""
    if not isinstance(path, str) or not path or len(path) > MAX_PATH_LENGTH:
        return None
    if path[0] != "/" or path[:2] == "//":
        return None
    if "\\" in path or "?" in path or "#" in path or _has_control(path):
        return None
    if _FORBIDDEN_ESCAPE_RE.search(path):
        return None
    if path != "/" and any(segment in ("", ".", "..") for segment in path[1:].split("/")):
        return None
    return path


def _is_safe_segment(value):
    return (
        isinstance(value, str)
        and 0 < len(value) <= MAX_SEGMENT_LENGTH
        and value not in (".", "..")
        and _SAFE_SEGMENT_RE.fullmatch(value) is not None
        and _FORBIDDEN_ESCAPE_RE.search(value) is None
    )


def _is_safe_output(path):
    """Final check on every URL returned: one leading '/', no backslash, no controls."""
    return (
        isinstance(path, str)
        and path.startswith("/")
        and path[1:2] not in ("/", "\\")
        and "\\" not in path
        and not _has_control(path)
        and " " not in path
    )


def _read_method(method):
    return isinstance(method, str) and method.upper() in ("GET", "HEAD")


def _parse_query(query_string):
    """The first value of each query key, in order; None when the query is unusable."""
    if query_string is None:
        return {}
    if isinstance(query_string, (bytes, bytearray)):
        query_string = bytes(query_string).decode("utf-8", "replace")
    if not isinstance(query_string, str):
        return None
    text = query_string[1:] if query_string.startswith("?") else query_string
    if len(text) > MAX_QUERY_LENGTH:
        return None
    if not text:
        return {}
    try:
        pairs = parse_qsl(text, keep_blank_values=True, max_num_fields=MAX_QUERY_FIELDS, encoding="utf-8", errors="replace")
    except ValueError:
        return None
    first = {}
    for key, value in pairs:
        first.setdefault(key, value)
    return first


def _clean_query_value(value, local_path=False):
    if not isinstance(value, str) or not value or len(value) > MAX_QUERY_VALUE_LENGTH or _has_control(value):
        return None
    if local_path and (not value.startswith("/") or value[1:2] in ("/", "\\") or "\\" in value):
        return None
    return value


def _clean_fragment(fragment):
    """The fragment name used to look up a ``hash_map`` entry; empty when unusable. Never echoed."""
    if not isinstance(fragment, str):
        return ""
    text = fragment[1:] if fragment.startswith("#") else fragment
    if not text or len(text) > MAX_FRAGMENT_LENGTH:
        return ""
    if "%" in text:
        try:
            text = unquote(text, errors="strict")
        except UnicodeDecodeError:
            return ""
    return text if _FRAGMENT_KEY_RE.fullmatch(text) else ""


# ---------------------------------------------------------------------------
# Classic -> V2
# ---------------------------------------------------------------------------

def _match_classic(route_map, path, method):
    """The most specific row whose classic rule matches ``path`` and ``method``, with its values."""
    verb = "GET" if method.upper() == "HEAD" else method.upper()
    best = None
    for route in route_map.routes:
        if verb not in route.methods:
            continue
        match = route.classic_regex.fullmatch(path)
        if match is None:
            continue
        # Flask prefers the rule with more fixed text, then fewer placeholders, then the first.
        rank = (route.classic_static_length, -len(route.classic_params), -route.index)
        if best is None or rank > best[0]:
            best = (rank, route, match.groupdict())
    return None if best is None else (best[1], best[2])


def _render_route_path(pattern, values, suffix=""):
    parts = []
    for is_param, text in pattern.segments:
        parts.append(quote(values[text], safe="%~") if is_param else text)
    route_path = ("/" + "/".join(parts)) if parts else ""
    route_path += suffix
    return route_path or "/"


def _query_suffix_and_pairs(route, params):
    """What the row carries from the first-values of a classic query: ``(route segment suffix, pairs)``."""
    suffix = ""
    pairs = {}
    for classic_key, rule in route.query_map.items():
        raw_value = params.get(classic_key)
        if raw_value is None:
            continue
        if rule.path is not None:
            segment = rule.path.get(raw_value)
            if segment and not suffix:
                suffix = segment
            continue
        value = _clean_query_value(raw_value, local_path=rule.local_path)
        if value is None:
            continue
        if rule.values is not None:
            value = rule.values.get(value)
            if value is None:
                continue
        pairs.setdefault(rule.to, value)
    return suffix, pairs


def resolve_v2_target(path, query_string="", fragment="", *, method="GET", route_map=None):
    """Where a classic URL leads in V2, or None when it should stay classic.

    ``path`` is the request path as Flask reports it (``request.path``), ``query_string`` the
    raw query and ``fragment`` the part after ``#`` (a server never sees it; pass it when the
    browser can). Returns ``{"path": "/v2/chat?conversationId=abc", "router_path":
    "/chat?conversationId=abc", "key": "chat", "status": "partial", "params": {}}``: ``path`` is
    the same-site URL to redirect to and ``router_path`` the same place relative to the ``/v2``
    router basename. ``params`` holds the classic path parameters the URL carried
    (``{"slug": "handbook"}`` for ``/custom/handbook``), for a caller that has to check the
    page the URL names before it follows the answer.

    Returns None for an unknown path, a row that does not resolve (see the module docstring),
    a method other than GET or HEAD, and anything that is not a plain same-site path.
    A classic path parameter that is not a plain segment, or that is a name V2 reserves for
    another page, also answers None, as does a request carrying a row's ``classic_only_query``
    (the embed frame V2 itself loads from a classic page must never be redirected back into V2).
    Query keys the row does not map are dropped; a fragment is read only to look up the row's
    ``hash_map`` and is never copied.

    When both the query string and the fragment name a section, the query string wins; a
    row's fixed ``v2_query`` and a fragment's query values override same-named query values.
    """
    if not _read_method(method):
        return None
    clean = _clean_request_path(path)
    if clean is None:
        return None
    route_map = route_map or load_ui_route_map()
    matched = _match_classic(route_map, clean, method)
    if matched is None:
        return None
    route, classic_values = matched
    if not route.resolvable:
        return None

    params = _parse_query(query_string)
    if params is None:
        return None
    if route.classic_only_query and all(
        params.get(name) == value for name, value in route.classic_only_query.items()
    ):
        return None

    v2_values = {}
    for classic_name, v2_name in route.path_params.items():
        value = classic_values.get(classic_name)
        if not _is_safe_segment(value) or value in route.v2_reserved.get(v2_name, ()):
            return None
        v2_values[v2_name] = value

    suffix, pairs = _query_suffix_and_pairs(route, params)
    pairs.update(route.v2_query)
    entry = route.hash_map.get(_clean_fragment(fragment))
    if entry is not None:
        suffix = suffix or entry.get("path", "")
        pairs.update(entry.get("query", {}))

    route_path = _render_route_path(route.v2_patterns[0], v2_values, suffix)
    query = urlencode(list(pairs.items()), quote_via=quote) if pairs else ""
    router_path = f"{route_path}?{query}" if query else route_path
    full_path = V2_BASE_PATH + ("" if route_path == "/" else route_path) + (f"?{query}" if query else "")
    if not _is_safe_output(full_path):
        return None
    return {
        "path": full_path,
        "router_path": router_path,
        "key": route.key,
        "status": route.status,
        "params": dict(classic_values),
    }


# ---------------------------------------------------------------------------
# V2 -> classic
# ---------------------------------------------------------------------------

def _normalize_v2_path(v2_path):
    """A V2 router path, from either a router path or a full ``/v2/...`` URL path."""
    if not isinstance(v2_path, str):
        return None
    text = v2_path
    if text == V2_BASE_PATH or text.startswith(V2_BASE_PATH + "/"):
        text = text[len(V2_BASE_PATH):] or "/"
    if len(text) > 1 and text.endswith("/"):
        text = text[:-1]
    return _clean_request_path(text)


def _match_v2_pattern(pattern, segments, reserved):
    """Whole-path match of a V2 pattern; returns the parameter values, or None."""
    if len(pattern.segments) != len(segments):
        return None
    values = {}
    for (is_param, text), segment in zip(pattern.segments, segments):
        if not is_param:
            if segment != text:
                return None
            continue
        if not _is_safe_segment(segment) or segment in reserved.get(text, ()):
            return None
        values[text] = segment
    return values


def _render_classic_path(route, classic_values):
    def fill(match):
        return quote(classic_values[match.group("name")], safe="%~")
    return _CLASSIC_TOKEN_RE.sub(fill, route.classic)


def resolve_classic_target(v2_path, query_string="", fragment="", *, route_map=None):
    """Where the classic version of a V2 URL is, or None when it has no classic page.

    ``v2_path`` is a V2 router path (``/groups/abc/members``) or the same path under the
    ``/v2`` basename. It may be deeper than the row's main route: a row lists the other V2
    routes that are the same classic page in ``v2_subroutes``, and anything else under a
    page's prefix is not guessed at. Returns ``{"path": "/groups/abc", "key": "group-manage",
    "status": "partial"}`` where ``path`` includes the classic query string and fragment.

    Alias rows are forward-only (``/my_groups`` and ``/profile?tab=groups`` are one V2 page, and
    the canonical classic address is the second), and rows that do not resolve have no V2
    page to come from. ``fragment`` is accepted for symmetry with ``resolve_v2_target`` and
    ignored: V2 addresses sections with paths and query keys, never fragments.
    """
    clean = _normalize_v2_path(v2_path)
    if clean is None:
        return None
    segments = tuple(clean[1:].split("/")) if clean != "/" else ()
    route_map = route_map or load_ui_route_map()

    best = None
    for route in route_map.routes:
        if not route.resolvable or route.status == STATUS_ALIAS:
            continue
        for pattern in route.v2_patterns:
            values = _match_v2_pattern(pattern, segments, route.v2_reserved)
            if values is None:
                continue
            classic_values = {}
            for classic_name in route.classic_params:
                value = values.get(route.path_params.get(classic_name))
                if value is None:
                    break
                classic_values[classic_name] = value
            else:
                rank = (pattern.literal_count, -len(pattern.param_names), -route.index)
                if best is None or rank > best[0]:
                    best = (rank, route, classic_values)
    if best is None:
        return None
    _, route, classic_values = best

    v2_pairs = _parse_query(query_string)
    if v2_pairs is None:
        return None
    classic_pairs = {}
    for v2_key, value in v2_pairs.items():
        rule = route.reverse_query.get(v2_key)
        if rule is None:
            continue
        clean_value = _clean_query_value(value, local_path=rule.local_path)
        if clean_value is None:
            continue
        if rule.values is not None:
            clean_value = rule.values.get(clean_value)
            if clean_value is None:
                continue
        classic_pairs.setdefault(rule.classic_key, clean_value)

    classic_fragment = ""
    tail = segments[len(route.v2_patterns[0].segments):]
    best_suffix = None
    for suffix_segments, kind, payload in route.reverse_suffixes:
        if tail[:len(suffix_segments)] == suffix_segments and (
            best_suffix is None or len(suffix_segments) > len(best_suffix[0])
        ):
            best_suffix = (suffix_segments, kind, payload)
    if best_suffix is not None:
        _, kind, payload = best_suffix
        if kind == "hash":
            classic_fragment = payload
        else:
            classic_pairs.setdefault(payload[0], payload[1])
    if not classic_fragment:
        for required, fragment_name in route.reverse_hash_queries:
            if all(v2_pairs.get(key) == value for key, value in required):
                classic_fragment = fragment_name
                break

    full_path = _render_classic_path(route, classic_values)
    if classic_pairs:
        full_path += "?" + urlencode(list(classic_pairs.items()), quote_via=quote)
    if classic_fragment:
        full_path += "#" + classic_fragment
    if not _is_safe_output(full_path):
        return None
    return {"path": full_path, "key": route.key, "status": route.status}

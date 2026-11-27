# cosmos_patch.py
"""Cosmos partial-document updates for in-memory container doubles.

Version: 0.261.485
Implemented in: 0.261.485

Applies the pinned SDK's patch operations and evaluates the filter-predicate
subset that application owners send. Unsupported syntax fails the calling test
instead of being treated as a match, so a double cannot silently accept a
predicate it does not understand.
"""

from copy import deepcopy
import json
import operator
import re

from azure.cosmos.exceptions import CosmosAccessConditionFailedError, CosmosHttpResponseError


MAX_PATCH_OPERATIONS = 10
UNDEFINED = object()
_TOKEN = re.compile(
    r'\s*(?:(?P<string>"(?:[^"\\]|\\.)*")|(?P<number>-?\d+(?:\.\d+)?)'
    r'|(?P<operator><=|>=|!=|=|<|>)|(?P<punct>[()\[\].])|(?P<word>[A-Za-z_]\w*))'
)
_FUNCTIONS = {
    "IS_ARRAY": lambda value: isinstance(value, list),
    "IS_DEFINED": lambda value: value is not UNDEFINED,
    "IS_OBJECT": lambda value: isinstance(value, dict),
}
_ORDERING = {"<": operator.lt, "<=": operator.le, ">": operator.gt, ">=": operator.ge}


def _bad_request(message):
    return CosmosHttpResponseError(status_code=400, message=message)


def _type_name(value):
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "undefined"


def _child(value, key):
    if isinstance(value, dict) and isinstance(key, str):
        return value.get(key, UNDEFINED)
    if isinstance(value, list) and _type_name(key) == "number" and 0 <= key < len(value):
        return value[key]
    return UNDEFINED


def _tokenize(text):
    tokens, position = [], 0
    while text[position:].strip():
        match = _TOKEN.match(text, position)
        if match is None:
            raise AssertionError(f"Unsupported Cosmos filter predicate: {text!r}")
        tokens.append((match.lastgroup, match.group(match.lastgroup)))
        position = match.end()
    return tokens


class _Predicate:
    """Evaluates `FROM <alias> WHERE ...` with Cosmos three-valued logic."""

    def __init__(self, text, document):
        self.text = text
        self.tokens = _tokenize(text)
        self.position = 0
        self.document = document
        self.alias = None

    def _unsupported(self):
        return AssertionError(f"Unsupported Cosmos filter predicate: {self.text!r}")

    def _peek(self):
        return self.tokens[self.position] if self.position < len(self.tokens) else (None, None)

    def _keyword(self, name):
        kind, value = self._peek()
        if kind == "word" and value.upper() == name:
            self.position += 1
            return True
        return False

    def _expect(self, kind, value=None):
        token_kind, token_value = self._peek()
        if token_kind != kind or (value is not None and token_value != value):
            raise self._unsupported()
        self.position += 1
        return token_value

    def matches(self):
        if not self._keyword("FROM"):
            raise self._unsupported()
        self.alias = self._expect("word")
        if not self._keyword("WHERE"):
            raise self._unsupported()
        result = self._or()
        if self.position != len(self.tokens):
            raise self._unsupported()
        return result is True

    def _or(self):
        values = [self._and()]
        while self._keyword("OR"):
            values.append(self._and())
        if len(values) == 1:
            return values[0]
        if any(value is True for value in values):
            return True
        return False if all(value is False for value in values) else UNDEFINED

    def _and(self):
        values = [self._not()]
        while self._keyword("AND"):
            values.append(self._not())
        if len(values) == 1:
            return values[0]
        if any(value is False for value in values):
            return False
        return True if all(value is True for value in values) else UNDEFINED

    def _not(self):
        if self._keyword("NOT"):
            value = self._not()
            return (not value) if isinstance(value, bool) else UNDEFINED
        return self._comparison()

    def _comparison(self):
        left = self._operand()
        kind, symbol = self._peek()
        if kind != "operator":
            return left
        self.position += 1
        right = self._operand()
        if left is UNDEFINED or right is UNDEFINED or _type_name(left) != _type_name(right):
            return UNDEFINED
        if symbol in ("=", "!="):
            return (left == right) == (symbol == "=")
        if _type_name(left) not in ("number", "string"):
            return UNDEFINED
        return _ORDERING[symbol](left, right)

    def _operand(self):
        kind, value = self._peek()
        if (kind, value) == ("punct", "("):
            self.position += 1
            result = self._or()
            self._expect("punct", ")")
            return result
        if kind in ("string", "number"):
            self.position += 1
            return json.loads(value)
        if kind != "word":
            raise self._unsupported()
        self.position += 1
        if value in ("true", "false", "null"):
            return json.loads(value)
        if value.upper() in _FUNCTIONS:
            self._expect("punct", "(")
            argument = self._or()
            self._expect("punct", ")")
            return _FUNCTIONS[value.upper()](argument)
        if value != self.alias:
            raise self._unsupported()
        return self._path(self.document)

    def _path(self, value):
        while True:
            kind, token = self._peek()
            if (kind, token) == ("punct", "."):
                self.position += 1
                key = self._expect("word")
            elif (kind, token) == ("punct", "["):
                self.position += 1
                key_kind, raw = self._peek()
                if key_kind not in ("string", "number"):
                    raise self._unsupported()
                self.position += 1
                key = json.loads(raw)
                self._expect("punct", "]")
            else:
                return value
            value = _child(value, key)


def predicate_matches(document, predicate):
    return _Predicate(predicate, document).matches()


def _pointer(path):
    if not isinstance(path, str) or not path.startswith("/") or path == "/":
        raise _bad_request("Invalid patch path.")
    return [part.replace("~1", "/").replace("~0", "~") for part in path[1:].split("/")]


def _parent(document, path):
    parts = _pointer(path)
    target = document
    for part in parts[:-1]:
        target = _child(target, int(part) if isinstance(target, list) and part.isdigit() else part)
        if not isinstance(target, (dict, list)):
            raise _bad_request("Patch parent does not exist.")
    return target, parts[-1]


def _apply_array_operation(target, key, operation):
    op = operation.get("op")
    index = len(target) if key == "-" and op == "add" else (int(key) if key.isdigit() else None)
    if index is None or index > len(target) or (index == len(target) and op != "add"):
        raise _bad_request("Invalid array patch path.")
    if op == "add":
        target.insert(index, deepcopy(operation["value"]))
    elif op in ("set", "replace"):
        target[index] = deepcopy(operation["value"])
    elif op == "remove":
        del target[index]
    else:
        raise AssertionError(f"Unsupported Cosmos array patch operation: {op}")


def apply_patch_operations(document, operations):
    """Returns the patched copy; the caller stores it only after every operation succeeds."""
    if not isinstance(operations, list) or not 1 <= len(operations) <= MAX_PATCH_OPERATIONS:
        raise _bad_request("Patch requests require 1 to 10 operations.")
    updated = deepcopy(dict(document))
    for operation in operations:
        target, key = _parent(updated, operation.get("path"))
        if isinstance(target, list):
            _apply_array_operation(target, key, operation)
            continue
        op = operation.get("op")
        if op in ("add", "set") or (op == "replace" and key in target):
            target[key] = deepcopy(operation["value"])
        elif op == "remove" and key in target:
            del target[key]
        elif op == "incr":
            current = target.get(key, 0)
            if _type_name(operation.get("value")) != "number" or _type_name(current) != "number":
                raise _bad_request("Increment requires numeric values.")
            target[key] = current + operation["value"]
        elif op in ("replace", "remove"):
            raise _bad_request("Patch target does not exist.")
        else:
            raise AssertionError(f"Unsupported Cosmos patch operation: {op}")
    return updated


def patch_document(document, operations, *, filter_predicate=None):
    if filter_predicate is not None and not predicate_matches(document, filter_predicate):
        raise CosmosAccessConditionFailedError(status_code=412, message="Precondition failed.")
    return apply_patch_operations(document, operations)

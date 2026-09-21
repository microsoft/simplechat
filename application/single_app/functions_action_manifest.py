# functions_action_manifest.py
"""Dependency-free action type, origin, and retired-transport contracts."""

from copy import deepcopy
from dataclasses import dataclass
import re


MCP_STDIO_REMOVED_CODE = "mcp_stdio_removed"
MCP_STDIO_REMOVED_MESSAGE = (
    "This action uses stdio, which is no longer supported. "
    "Reconfigure it to use a supported remote MCP server, or delete it."
)
MCP_TYPE_ALIASES = frozenset({
    "mcp", "mcpplugin", "modelcontextprotocol", "modelcontextprotocolplugin",
})


class McpConfigurationError(ValueError):
    """An invalid MCP configuration with a stable, safe public message."""

    def __init__(self, message="MCP configuration is invalid.", code="validation"):
        super().__init__(message)
        self.public_message = message
        self.code = code


class McpStdioRemovedError(McpConfigurationError):
    """A retired configuration must never reach an executable connector."""

    def __init__(self):
        super().__init__(MCP_STDIO_REMOVED_MESSAGE, MCP_STDIO_REMOVED_CODE)


def resolve_action_type(manifest):
    """Resolve supported MCP aliases without collapsing other runtime types."""
    if not isinstance(manifest, dict):
        raise ValueError("Action configuration must be an object.")
    declared_type = manifest.get("type")
    if declared_type is None or (isinstance(declared_type, str) and not declared_type.strip()):
        metadata = manifest.get("metadata")
        declared_type = metadata.get("type", "") if isinstance(metadata, dict) else ""
    if not isinstance(declared_type, str):
        raise ValueError("Action type must be a string.")
    declared_type = declared_type.strip()
    compact_type = re.sub(r"[\s_-]", "", declared_type).lower()
    return "mcp" if compact_type in MCP_TYPE_ALIASES else declared_type


def is_mcp_action(manifest):
    """Return whether the effective runtime action is MCP."""
    return resolve_action_type(manifest) == "mcp"


def is_retired_mcp_stdio(manifest):
    """Inspect historical records without running active-config normalization."""
    if not isinstance(manifest, dict):
        return False
    try:
        if not is_mcp_action(manifest):
            return False
    except ValueError:
        return False
    fields = manifest.get("additionalFields")
    transport = fields.get("transport", "") if isinstance(fields, dict) else ""
    return (
        str(transport or "").strip().lower() == "stdio"
        or str(manifest.get("endpoint") or "").strip().lower().startswith("stdio:")
    )


def get_action_execution_status(manifest):
    """Derive management information; never use it as execution authority."""
    if is_retired_mcp_stdio(manifest):
        return {
            "state": "unsupported",
            "code": MCP_STDIO_REMOVED_CODE,
            "message": MCP_STDIO_REMOVED_MESSAGE,
        }
    return None


@dataclass(frozen=True)
class McpActionOrigin:
    """Authoritative origin established by a server-side authorized lookup."""

    scope_type: str
    scope_id: str
    action_id: str = ""

    def __post_init__(self):
        if self.scope_type not in {"personal", "group", "global"}:
            raise ValueError("Action origin has an unsupported scope.")
        if not isinstance(self.scope_id, str) or not self.scope_id.strip():
            raise ValueError("Action origin requires a scope identifier.")
        if self.scope_type == "global" and self.scope_id != "global":
            raise ValueError("Global action origin requires the global scope.")
        if not isinstance(self.action_id, str):
            raise ValueError("Action origin has an invalid action identifier.")


class ScopedActionManifest(dict):
    """Compare JSON payloads, keeping server-only authorization origin separate."""

    def __init__(self, manifest, origin):
        if not isinstance(origin, McpActionOrigin):
            raise ValueError("Action origin is required.")
        super().__init__(manifest)
        self._action_origin = origin

    def __eq__(self, other):
        return dict.__eq__(self, other)

    def __ne__(self, other):
        return dict.__ne__(self, other)

    @property
    def action_origin(self):
        return self._action_origin

    def copy(self):
        return ScopedActionManifest(self, self._action_origin)


def get_action_origin(manifest):
    """Never interpret dictionary keys as proof of a trusted origin."""
    return manifest.action_origin if isinstance(manifest, ScopedActionManifest) else None


def copy_action_manifest(manifest):
    """Copy an internal manifest without discarding its lookup provenance."""
    return deepcopy(manifest)


def bind_action_origin(manifest, scope_type, scope_id):
    """Bind a record to the collection/partition used by its authorized caller."""
    origin = McpActionOrigin(
        scope_type=scope_type,
        scope_id=str(scope_id or ""),
        action_id=str(manifest.get("id") or ""),
    )
    bound = ScopedActionManifest(deepcopy(dict(manifest)), origin)
    bound["type"] = resolve_action_type(bound)
    for field in ("runtime_user_id", "action_origin", "_action_origin", "execution_status"):
        bound.pop(field, None)
    bound["scope"] = "user" if scope_type == "personal" else scope_type
    bound["scope_id"] = origin.scope_id
    bound["is_global"] = scope_type == "global"
    bound["is_group"] = scope_type == "group"
    if scope_type == "personal":
        bound["user_id"] = origin.scope_id
        bound.pop("group_id", None)
    elif scope_type == "group":
        bound["group_id"] = origin.scope_id
        bound.pop("user_id", None)
    else:
        bound.pop("user_id", None)
        bound.pop("group_id", None)
    return bound

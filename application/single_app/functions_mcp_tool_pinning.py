# functions_mcp_tool_pinning.py
"""MCP tool and prompt fingerprint helpers."""

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

from functions_action_manifest import get_action_origin, resolve_action_type
from functions_appinsights import log_event


MCP_TOOL_FINGERPRINTS_FIELD = "mcp_tool_fingerprints"
MCP_TOOL_DRIFT_FIELD = "mcp_tool_drift"
MCP_PROMPTS_FIELD = "mcp_prompts"
MCP_DRIFT_NOTIFICATION_TYPE = "mcp_tool_drift_detected"
MCP_PLUGIN_TYPE = "mcp"


def _canonical_hash(value: Any) -> str:
    """Return the SHA-256 hash for stable canonical JSON."""
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _tool_payload(tool: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "name": str(tool.get("original_name") or tool.get("name") or "").strip(),
        "description": str(tool.get("description") or "").strip(),
        "inputSchema": tool.get("inputSchema") if isinstance(tool.get("inputSchema"), dict) else tool.get("input_schema") if isinstance(tool.get("input_schema"), dict) else {},
        "outputSchema": tool.get("outputSchema") if isinstance(tool.get("outputSchema"), dict) else tool.get("output_schema") if isinstance(tool.get("output_schema"), dict) else {},
        "annotations": tool.get("annotations") if isinstance(tool.get("annotations"), dict) else {},
    }


def normalize_mcp_prompt_metadata(value: Any) -> List[Dict[str, Any]]:
    """Return normalized MCP prompt metadata entries."""
    if not isinstance(value, list):
        return []

    prompts = []
    seen_names = set()
    for prompt in value:
        if not isinstance(prompt, dict):
            continue
        name = str(prompt.get("name") or "").strip()
        if not name or name in seen_names:
            continue
        seen_names.add(name)
        arguments = prompt.get("arguments")
        if not isinstance(arguments, list):
            arguments = []
        prompts.append({
            "name": name,
            "description": str(prompt.get("description") or "").strip(),
            "arguments": [
                argument for argument in arguments
                if isinstance(argument, dict) and str(argument.get("name") or "").strip()
            ],
        })
    return prompts


def _normalize_mcp_tool_metadata(value: Any) -> List[Dict[str, Any]]:
    from functions_mcp_operations import normalize_mcp_tool_metadata

    return normalize_mcp_tool_metadata(value)


def _prompt_payload(prompt: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "name": str(prompt.get("name") or "").strip(),
        "description": str(prompt.get("description") or "").strip(),
        "arguments": prompt.get("arguments") if isinstance(prompt.get("arguments"), list) else [],
    }


def compute_mcp_tool_hash(tool: Dict[str, Any]) -> str:
    """Compute a stable fingerprint for one MCP tool."""
    return _canonical_hash(_tool_payload(tool))


def compute_mcp_prompt_hash(prompt: Dict[str, Any]) -> str:
    """Compute a stable fingerprint for one MCP prompt."""
    return _canonical_hash(_prompt_payload(prompt))


def build_mcp_tool_fingerprints(
    tools: Iterable[Dict[str, Any]],
    prompts: Optional[Iterable[Dict[str, Any]]] = None,
    *,
    discovered_at: Optional[str] = None,
) -> Dict[str, Any]:
    """Build the approved fingerprint manifest for discovered MCP tools and prompts."""
    normalized_tools = _normalize_mcp_tool_metadata(list(tools or []))
    normalized_prompts = normalize_mcp_prompt_metadata(list(prompts or []))
    tool_hashes = {
        tool["original_name"]: compute_mcp_tool_hash(tool)
        for tool in normalized_tools
        if tool.get("original_name")
    }
    prompt_hashes = {
        prompt["name"]: compute_mcp_prompt_hash(prompt)
        for prompt in normalized_prompts
        if prompt.get("name")
    }
    manifest_hash = _canonical_hash({
        "tools": tool_hashes,
        "prompts": prompt_hashes,
    })
    return {
        "manifest_hash": manifest_hash,
        "tools": tool_hashes,
        "prompts": prompt_hashes,
        "discovered_at": discovered_at or datetime.now(timezone.utc).isoformat(),
    }


def normalize_mcp_tool_fingerprints(value: Any) -> Dict[str, Any]:
    """Return a normalized approved fingerprint object, or an empty dict."""
    if not isinstance(value, dict):
        return {}
    manifest_hash = str(value.get("manifest_hash") or "").strip()
    tools = value.get("tools") if isinstance(value.get("tools"), dict) else {}
    prompts = value.get("prompts") if isinstance(value.get("prompts"), dict) else {}
    normalized = {
        "manifest_hash": manifest_hash,
        "tools": {
            str(name): str(fingerprint)
            for name, fingerprint in tools.items()
            if str(name).strip() and str(fingerprint).strip()
        },
        "prompts": {
            str(name): str(fingerprint)
            for name, fingerprint in prompts.items()
            if str(name).strip() and str(fingerprint).strip()
        },
        "discovered_at": str(value.get("discovered_at") or "").strip(),
    }
    return normalized if normalized["manifest_hash"] and normalized["discovered_at"] else {}


def compare_mcp_fingerprints(
    approved: Dict[str, Any],
    current: Dict[str, Any],
) -> Dict[str, Any]:
    """Compare approved and current fingerprint manifests."""
    approved = normalize_mcp_tool_fingerprints(approved)
    current = normalize_mcp_tool_fingerprints(current)
    approved_tools = approved.get("tools", {})
    current_tools = current.get("tools", {})
    approved_prompts = approved.get("prompts", {})
    current_prompts = current.get("prompts", {})

    def diff(before: Dict[str, str], after: Dict[str, str]) -> Dict[str, List[str]]:
        before_names = set(before.keys())
        after_names = set(after.keys())
        return {
            "new": sorted(after_names - before_names),
            "changed": sorted(name for name in before_names & after_names if before[name] != after[name]),
            "removed": sorted(before_names - after_names),
        }

    tool_diff = diff(approved_tools, current_tools)
    prompt_diff = diff(approved_prompts, current_prompts)
    return {
        "manifest_hash": current.get("manifest_hash", ""),
        "new": tool_diff["new"],
        "changed": tool_diff["changed"],
        "removed": tool_diff["removed"],
        "prompts_new": prompt_diff["new"],
        "prompts_changed": prompt_diff["changed"],
        "prompts_removed": prompt_diff["removed"],
        "has_drift": approved.get("manifest_hash") != current.get("manifest_hash"),
    }


def filter_pinned_mcp_tools(
    tools: Iterable[Dict[str, Any]],
    fingerprints: Dict[str, Any],
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Return only tools matching approved fingerprints, plus drift metadata."""
    normalized_tools = _normalize_mcp_tool_metadata(list(tools or []))
    approved = normalize_mcp_tool_fingerprints(fingerprints)
    approved_tools = approved.get("tools", {})
    if not approved_tools:
        return normalized_tools, {"has_drift": False, "new": [], "changed": [], "removed": []}
    allowed = []
    current_hashes = {}
    for tool in normalized_tools:
        name = tool.get("original_name")
        if not name:
            continue
        current_hash = compute_mcp_tool_hash(tool)
        current_hashes[name] = current_hash
        if approved_tools.get(name) == current_hash:
            allowed.append(tool)
    current = build_mcp_tool_fingerprints(normalized_tools, [])
    current["tools"] = current_hashes
    current["manifest_hash"] = _canonical_hash({"tools": current_hashes, "prompts": approved.get("prompts", {})})
    return allowed, compare_mcp_fingerprints(approved, current)


def validate_mcp_tool_pinning_for_save(action: Dict[str, Any], existing_action: Optional[Dict[str, Any]] = None) -> None:
    """Enforce MCP fingerprint approval for new or connection-changing saves."""
    if not isinstance(action, dict) or resolve_action_type(action) != MCP_PLUGIN_TYPE:
        return
    fields = action.get("additionalFields") if isinstance(action.get("additionalFields"), dict) else {}
    existing_fields = existing_action.get("additionalFields") if isinstance(existing_action, dict) and isinstance(existing_action.get("additionalFields"), dict) else {}
    fingerprints = normalize_mcp_tool_fingerprints(fields.get(MCP_TOOL_FINGERPRINTS_FIELD))
    existing_fingerprints = normalize_mcp_tool_fingerprints(existing_fields.get(MCP_TOOL_FINGERPRINTS_FIELD))
    relevant_keys = (
        "endpoint",
        "identity_id",
        "auth",
        "server_profile",
        "preconfiguration_id",
        "transport",
        "auth_method",
        "api_key_header_name",
        "custom_headers",
        "load_tools",
        "load_prompts",
        "mcp_tools",
        MCP_PROMPTS_FIELD,
        "allowed_tool_names",
    )

    def relevant(source: Dict[str, Any], additional: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "endpoint": source.get("endpoint"),
            "identity_id": source.get("identity_id"),
            "auth": source.get("auth"),
            **{key: additional.get(key) for key in relevant_keys if key not in {"endpoint", "identity_id", "auth"}},
        }

    # Lazy import: functions_mcp_operations imports this module.
    from functions_mcp_operations import normalize_mcp_additional_fields

    changed = existing_action is None or (
        relevant(action, normalize_mcp_additional_fields(fields))
        != relevant(existing_action, normalize_mcp_additional_fields(existing_fields))
    )
    if existing_action is not None and not existing_fingerprints and not changed:
        return
    if not fingerprints and (existing_action is None or changed or existing_fingerprints):
        raise ValueError("Discover and approve MCP tools before saving this action.")

    current = build_mcp_tool_fingerprints(
        _normalize_mcp_tool_metadata(fields.get("mcp_tools")),
        normalize_mcp_prompt_metadata(fields.get(MCP_PROMPTS_FIELD)),
        discovered_at=fingerprints.get("discovered_at"),
    )
    if fingerprints.get("tools") != current.get("tools") or fingerprints.get("prompts") != current.get("prompts"):
        raise ValueError("MCP tool fingerprints do not match the approved discovery metadata.")
    if fields.get(MCP_TOOL_DRIFT_FIELD) is None:
        fields.pop(MCP_TOOL_DRIFT_FIELD, None)


def persist_mcp_tool_drift(action: Dict[str, Any], drift: Dict[str, Any]) -> None:
    """Persist MCP drift metadata and notify the owner when possible."""
    if not isinstance(action, dict) or not drift.get("has_drift"):
        return
    origin = get_action_origin(action)
    if origin is None:
        return
    manifest_hash = str(drift.get("manifest_hash") or "").strip()
    if not manifest_hash:
        return
    detected_at = datetime.now(timezone.utc).isoformat()
    drift_doc = {
        "detected_at": detected_at,
        "manifest_hash": manifest_hash,
        "new": drift.get("new", []),
        "changed": drift.get("changed", []),
        "removed": drift.get("removed", []),
        "prompts_new": drift.get("prompts_new", []),
        "prompts_changed": drift.get("prompts_changed", []),
        "prompts_removed": drift.get("prompts_removed", []),
    }
    try:
        fields = action.setdefault("additionalFields", {})
        fields[MCP_TOOL_DRIFT_FIELD] = drift_doc
        if origin.scope_type == "personal":
            from config import cosmos_personal_actions_container
            stored = cosmos_personal_actions_container.read_item(item=origin.action_id, partition_key=origin.scope_id)
            stored.setdefault("additionalFields", {})[MCP_TOOL_DRIFT_FIELD] = drift_doc
            cosmos_personal_actions_container.replace_item(item=origin.action_id, body=stored)
        elif origin.scope_type == "group":
            from config import cosmos_group_actions_container
            stored = cosmos_group_actions_container.read_item(item=origin.action_id, partition_key=origin.scope_id)
            stored.setdefault("additionalFields", {})[MCP_TOOL_DRIFT_FIELD] = drift_doc
            cosmos_group_actions_container.replace_item(item=origin.action_id, body=stored)
        elif origin.scope_type == "global":
            from config import cosmos_global_actions_container
            stored = cosmos_global_actions_container.read_item(item=origin.action_id, partition_key=origin.action_id)
            stored.setdefault("additionalFields", {})[MCP_TOOL_DRIFT_FIELD] = drift_doc
            cosmos_global_actions_container.replace_item(item=origin.action_id, body=stored)
    except Exception as exc:
        log_event(
            "[MCP_PINNING] Failed to persist MCP tool drift",
            level=logging.WARNING,
            extra={"scope_type": origin.scope_type, "action_id": origin.action_id, "error_type": type(exc).__name__},
        )

    try:
        from functions_notifications import create_notification

        notification_kwargs = {
            "notification_type": MCP_DRIFT_NOTIFICATION_TYPE,
            "title": "MCP tools changed — review required",
            "message": "An MCP server changed its tool or prompt manifest. Review and re-approve the action before new or changed tools can run.",
            "metadata": {
                "action_id": origin.action_id,
                "scope_type": origin.scope_type,
                "scope_id": origin.scope_id,
                "manifest_hash": manifest_hash,
            },
            "idempotency_key": f"mcp-tool-drift:{origin.scope_type}:{origin.scope_id}:{origin.action_id}:{manifest_hash}",
        }
        if origin.scope_type == "personal":
            notification_kwargs["user_id"] = origin.scope_id
        elif origin.scope_type == "group":
            notification_kwargs["group_id"] = origin.scope_id
        else:
            notification_kwargs["assignment"] = {"roles": ["Admin", "ControlCenterAdmin"]}
        create_notification(**notification_kwargs)
    except Exception as exc:
        log_event(
            "[MCP_PINNING] Failed to deliver MCP tool drift notification",
            level=logging.WARNING,
            extra={"scope_type": origin.scope_type, "action_id": origin.action_id, "error_type": type(exc).__name__},
        )

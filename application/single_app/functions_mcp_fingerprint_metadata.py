# functions_mcp_fingerprint_metadata.py
"""Shared MCP prompt and tool fingerprint metadata normalization."""

from typing import Any, Dict, List


MCP_TOOL_FINGERPRINTS_FIELD = "mcp_tool_fingerprints"
MCP_TOOL_DRIFT_FIELD = "mcp_tool_drift"
MCP_PROMPTS_FIELD = "mcp_prompts"


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

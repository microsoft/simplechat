# action_runtime_contracts.py
"""Runtime-only action bindings. Stored names and trusted origins stay unchanged."""

from hashlib import sha256
import inspect
import json
import re

from semantic_kernel.functions import KernelPlugin

from functions_action_manifest import get_action_origin


class ActionLoadRequired(Exception):
    """Stop before model execution when assigned tools could not be loaded."""

    def __init__(self, manifests, failures):
        super().__init__("The selected agent has unavailable actions.")
        self.manifests = manifests
        self.failures = failures


class ActionRecoveryError(PermissionError):
    """A safe refusal of an expired, consumed or changed recovery decision."""

    def __init__(self):
        super().__init__("Action recovery changed or expired. Recheck the selected agent.")


class ActionRecoveryRequired(Exception):
    def __init__(self, event):
        super().__init__("The selected agent needs an action availability decision.")
        self.event = event


def action_binding_key(manifest, *, runtime_role=None):
    origin = get_action_origin(manifest)
    identity = (
        [origin.scope_type, origin.scope_id, origin.action_id]
        if origin else [manifest.get("type"), manifest.get("id"), manifest.get("name")]
    )
    if runtime_role:
        identity.append(runtime_role)
    return sha256(json.dumps(identity, separators=(",", ":")).encode()).hexdigest()


def _bindings(kernel):
    # Kernel is a Pydantic model: this private, non-field state is never serialized.
    return kernel.__dict__.setdefault("_simplechat_action_bindings", {})


def runtime_plugin_names(kernel, manifests, *, runtime_role=None):
    bindings = _bindings(kernel)
    counts = {}
    for manifest in manifests:
        name = manifest.get("name") or ""
        counts[name] = counts.get(name, 0) + 1
    for manifest in manifests:
        key = action_binding_key(manifest, runtime_role=runtime_role)
        if key in bindings:
            continue
        name = manifest.get("name") or ""
        occupied = set(kernel.plugins) | set(bindings.values())
        if (
            not re.fullmatch(r"[0-9A-Za-z_]+", name) or len(name) > 64
            or counts[name] > 1 or name in occupied or name.startswith("sc_action_")
        ):
            name = f"sc_action_{key[:14]}"
        if name in occupied:
            raise ValueError("Action runtime binding conflicts with an existing plugin.")
        bindings[key] = name
    return {id(manifest): bindings[action_binding_key(manifest, runtime_role=runtime_role)] for manifest in manifests}


def runtime_plugin_name(kernel, manifest, *, runtime_role=None):
    return runtime_plugin_names(kernel, [manifest], runtime_role=runtime_role)[id(manifest)]


def register_action_plugin(kernel, plugin, manifest, *, runtime_role=None):
    """Register without mutating the manifest used for secrets and authorization."""
    key = action_binding_key(manifest, runtime_role=runtime_role)
    name = runtime_plugin_name(kernel, manifest, runtime_role=runtime_role)
    # Discover the qualified-name budget before constructing the final kernel plugin.
    if hasattr(plugin, "get_functions"):
        functions = plugin.get_functions()
    else:
        functions = [
            getattr(method, "__kernel_function_name__", method_name)
            for method_name, method in inspect.getmembers(plugin, callable)
            if getattr(method, "__kernel_function__", False)
        ]
    longest = max((len(function) for function in functions), default=0)
    budget = 63 - longest
    if budget < 1:
        raise ValueError("Action tool name exceeds the supported qualified tool name budget.")
    if len(name) > budget:
        name = f"a_{key}"[:budget] if budget >= 3 else key[:budget]
        bindings = _bindings(kernel)
        occupied = set(kernel.plugins) | {
            value for binding, value in bindings.items() if binding != key
        }
        if name in occupied and bindings.get(key) != name:
            raise ValueError("Action runtime binding conflicts with an existing plugin.")
        _bindings(kernel)[key] = name
    if hasattr(plugin, "get_kernel_plugin"):
        prepared = plugin.get_kernel_plugin(name)
    else:
        prepared = KernelPlugin.from_object(name, plugin, description=manifest.get("description"))
    if not prepared.functions or any(
        len(function.metadata.fully_qualified_name) > 64 for function in prepared.functions.values()
    ):
        raise ValueError("Action has no functions or an unsupported qualified tool name.")
    kernel.add_plugin(prepared)
    return name

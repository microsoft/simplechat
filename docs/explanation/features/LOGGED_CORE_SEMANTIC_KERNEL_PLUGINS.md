# Logged Core Semantic Kernel Plugins

Version implemented: 0.239.153
Implemented in version: **0.239.153**

## Overview and Purpose

This feature moves SimpleChat's built-in Semantic Kernel core plugins onto local subclasses that emit plugin invocation logs through the existing plugin invocation logger. The change covers the Time, Wait, Math, and Text plugins and ensures that core-plugin invocations can now surface as thought records, not just custom plugin calls.

## Dependencies

- `semantic_kernel_plugins.plugin_invocation_logger`
- `semantic_kernel_plugins.plugin_invocation_thoughts`
- `semantic_kernel_loader.py`
- `route_backend_chats.py`
- Semantic Kernel upstream core plugins from the `semantic-kernel` repository

## Technical Specifications

### Architecture Overview

SimpleChat now owns thin subclasses for the upstream Semantic Kernel `TimePlugin`, `WaitPlugin`, `MathPlugin`, and `TextPlugin`. Each subclass lives in `application/single_app/semantic_kernel_plugins/` and calls the shared `auto_wrap_plugin_functions()` helper during initialization so inherited kernel functions receive the same invocation logging behavior as custom SimpleChat plugins.

### Configuration and Loader Flow

`semantic_kernel_loader.py` now imports the local SimpleChat versions of the Time and Wait plugins and continues to use the local Math and Text plugin modules. This means all existing loader paths that call `load_time_plugin()`, `load_wait_plugin()`, `load_math_plugin()`, and `load_text_plugin()` now register the logged subclasses automatically.

### Thought Integration

Thought formatting and callback registration were extracted into `semantic_kernel_plugins/plugin_invocation_thoughts.py`. The chat route reuses that helper in non-streaming agent execution, streaming agent execution, and the kernel-only Semantic Kernel fallback path so logged core-plugin invocations can generate `agent_tool_call` thoughts consistently. The formatter now emits user-readable summaries for wait and math operations, a parameter-aware fallback summary for other plugin calls, and an explicit `Invoking Plugin.Function` thought at the start of tool execution.

### File Structure

- `application/single_app/semantic_kernel_plugins/time_plugin.py`
- `application/single_app/semantic_kernel_plugins/wait_plugin.py`
- `application/single_app/semantic_kernel_plugins/math_plugin.py`
- `application/single_app/semantic_kernel_plugins/text_plugin.py`
- `application/single_app/semantic_kernel_plugins/plugin_invocation_logger.py`
- `application/single_app/semantic_kernel_plugins/plugin_invocation_thoughts.py`
- `application/single_app/semantic_kernel_plugins/logged_plugin_loader.py`
- `application/single_app/semantic_kernel_loader.py`
- `application/single_app/route_backend_chats.py`

## Usage Instructions

No additional configuration is required beyond the existing plugin enablement flags. When the Time, Wait, Math, or Text plugins are enabled in settings, the loader now registers the logged SimpleChat subclasses automatically.

For runtime behavior:

- Plugin invocations are recorded through the shared plugin invocation logger.
- Agent and kernel-only chat paths can register thought callbacks using `register_plugin_invocation_thought_callback()`.
- Thought content now includes human-readable operation summaries when possible, such as wait duration and math expressions/results, plus generic parameter summaries for other plugins.
- Streaming chat now polls pending thoughts while a response is still in flight so long-running tool calls can replace the active status badge before any content tokens are returned.
- Existing citation extraction still reads from the same invocation logger history.

## Testing and Validation

Functional coverage was added in `functional_tests/test_logged_core_plugins.py`.

The test validates:

- Inherited upstream methods are logged after auto-wrapping.
- SimpleChat-specific Math extensions remain available and logged.
- Async logging still works for the Wait plugin.
- Invocation callbacks can be transformed into thought records for both success and failure cases.
- Human-readable thought formatting includes meaningful wait, math, and generic plugin execution summaries.

## Known Limitations

- The standard upstream `HttpPlugin` fallback is not part of this first pass because SimpleChat already prefers `SmartHttpPlugin`.
- Prompt-based core plugins such as conversation summarization were intentionally left out to keep the change focused on native function plugins.
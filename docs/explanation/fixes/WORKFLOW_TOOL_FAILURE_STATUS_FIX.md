# Workflow Tool Failure Status and Structured Output Resilience Fix (v0.261.379)

Fixed/Implemented in version: **0.261.379**

Related `config.py` update: `VERSION = "0.261.379"` in `application/single_app/config.py`.

## Issue and Root Cause

When a workflow task invoked an agent or model with connector capabilities and an external tool call failed (for example, an OpenAPI action returning `HTTP 503` via `report_plugin_invocation_failure`, an MCP tool returning an error, or a failed delegated call), the workflow task and run could still be recorded as `succeeded` / `completed`:

1. `functions_workflow_results.py` stripped `tool_name`, `success`, and `error_message` when projecting `agent_citations` into `envelope["provenance"]["citations"]["agent_citations"]`, and `_execution_state()` ignored unrecovered failed tool citations (`success is False`), setting `envelope["execution"]["status"] = "succeeded"`.
2. `validate_workflow_task_output()` in `functions_workflow_validation.py` did not check for unrecovered failed tool calls in `agent_citations`. When a task configured an output contract JSON schema, `workflow_output_contract_instruction()` appended the target schema to the prompt, which could cause the model to fabricate a schema-matching JSON value (such as `{"status": "Evaluation"}`) despite the connector failure, or return only the schema-enumerated property while omitting other fields requested by the task instructions.
3. In `_execute_workflow_task_sequence()` (`functions_workflow_runner.py`), `task_status` was set to `validation["status"]` (`"invalid"` or `"incomplete"`) even when `envelope["execution"]["status"] == "failed"`, preventing `workflow_run_outcome()` from classifying producer/tool execution failures as `status: "failed"`.
4. `_structured_output()` in `functions_workflow_results.py` only extracted JSON when the entire reply was raw JSON or a full-string fenced code block, failing when an agent included brief surrounding text around a single fenced ` ```json ... ``` ` block.

## Technical Details

### Files Modified

- `application/single_app/functions_workflow_results.py`
  - Preserves `tool_name`, boolean `success`, bounded `error_message`, and `arguments_sha256` on citation provenance entries in `_provenance_references()`.
  - Updates `_execution_state()` to return `"failed"` when `failed_workflow_tool_citation_count()` detects unrecovered failed tool citations.
  - Updates `_structured_output()` to extract a single unambiguous fenced JSON block when full-string parsing does not match, while continuing to reject multiple competing blocks.
- `application/single_app/functions_workflow_validation.py`
  - Adds `failed_workflow_tool_citation_count()` to count tool calls whose latest recorded outcome for that call identity is `success is False`.
  - Records `"tool_invocation_failed"` (`eligible = False`, `status = "invalid"`) in `validate_workflow_task_output()` when unrecovered failed tool citations are present.
  - Updates `workflow_output_contract_instruction()` to forbid inventing schema values when a tool or source call fails and to instruct the model to include all task-requested fields alongside required schema properties when `additionalProperties` is not `False`.
- `application/single_app/functions_workflow_runner.py`
  - Sets `task_status = "failed"` in `_execute_workflow_task_sequence()` when `(envelope.get("execution") or {}).get("status") == "failed"`, ensuring both the task run item and `workflow_run_outcome()` persist `status = "failed"` while retaining the saved task result and releasing `active_run_id` so the workflow can be edited and re-run.
- `functional_tests/test_workflow_output_validation.py`
- `functional_tests/test_workflow_policy_failures.py`
- `application/single_app/config.py`

## Validation

- `python -m pytest -q -p no:cacheprovider functional_tests\test_workflow_output_validation.py functional_tests\test_workflow_result_contract.py functional_tests\test_workflow_policy_failures.py`
- `python .\functional_tests\test_docs_app_surface_coverage.py`
- `python .\functional_tests\test_docs_site_quality.py`

# Voice-Assisted Workflow and Action Creation

Implemented in version: **0.250.028**

## Overview

Voice-assisted creation extends the existing form speech-to-text controls from agent authoring into workflow and action authoring. Users can type or dictate brief creation details, then use drafting support to turn a workflow task brief into complete workflow or task instructions.

## Dependencies

- Azure Speech Service configuration for speech-to-text form controls.
- Existing SimpleChat agent instruction drafting model configuration for workflow instruction drafting.
- Personal workflow, group workflow, personal action, group action, or global action feature access as configured by administrators.

## Technical Specifications

### Architecture

- `application/single_app/static/js/form-voice-input.js` registers voice controls for workflow and action fields.
- `application/single_app/static/js/workspace/workspace_workflows.js` submits workflow draft requests and inserts returned instructions into the saved `task_prompt` field.
- `application/single_app/route_backend_workflows.py` exposes `POST /api/workflows/draft-instructions` and applies the same workflow access gates used by workflow management.
- `application/single_app/templates/workspace.html` and `application/single_app/templates/group_workspaces.html` render the task brief and draft workflow instruction controls.
- `application/single_app/templates/_plugin_modal.html` exposes the generated action name so users can edit or dictate it.

### API Endpoints

- `POST /api/workflows/draft-instructions`
  - Request: `workflow_scope`, `name`, `description`, `brief`, `existing_instructions`
  - Response: `success`, `instructions`
  - Access: authenticated users only; personal workflow app-role gates and group workflow management role gates are enforced.

### Configuration Options

No new settings are introduced. Voice buttons depend on the existing speech-to-text setting, and workflow drafting depends on existing GPT model settings.

## Usage Instructions

1. Open a personal or group workflow creation modal.
2. Enter or dictate a workflow name, description, and task brief.
3. Select **Draft Workflow Instructions** to generate editable workflow or task instructions.
4. Review and adjust the generated instructions before saving the workflow.
5. For actions, open the shared action modal and type or dictate display name, name, and description.

## Testing and Validation

- `functional_tests/test_workflow_instruction_drafting.py` validates route, template, JavaScript, voice registry, and payload contract wiring.
- `ui_tests/test_voice_assisted_form_inputs.py` validates voice controls render on agent, workflow, action, document metadata, and tag fields when speech-to-text is enabled.

## Known Limitations

- Voice controls only render when speech-to-text is enabled and the browser supports local audio recording APIs.
- Drafted workflow instructions still require user review before save.

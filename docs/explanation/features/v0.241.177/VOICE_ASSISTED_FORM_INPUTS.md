# Voice Assisted Form Inputs

Implemented in version: **0.241.177**

Fixed/Implemented in version: **0.241.177**

Related config.py version update: `application/single_app/config.py` is **0.241.177** for this implementation.

## Overview

Voice assisted form inputs add microphone controls to speech-enabled SimpleChat form surfaces so users can dictate agent details, group and public workspace names/descriptions, document metadata, and tag names. Agent instructions can also be drafted by the configured GPT model from typed or transcribed context before the user saves the agent.

## Dependencies

- Admin setting `enable_speech_to_text_input` must be enabled.
- Existing `/api/speech/transcribe-chat` Azure Speech transcription endpoint is reused.
- Existing Azure OpenAI or APIM Chat Model is reused for agent instruction drafting.
- Browser microphone access and `MediaRecorder` support are required for recording.

## Technical Specifications

- Shared browser helper: `application/single_app/static/js/form-voice-input.js`
- Shared layout loading: `application/single_app/templates/base.html`
- Agent instruction draft endpoint: `POST /api/agents/draft-instructions`
- Agent modal integration: `application/single_app/templates/_agent_modal.html` and `application/single_app/static/js/agent_modal_stepper.js`
- Manage-page refresh hooks: `application/single_app/static/js/group/manage_group.js` and `application/single_app/static/js/public/manage_public_workspace.js`

The helper normalizes dictated tag names to lowercase slug-style values and normalizes dictated keyword text to comma-separated values. Textarea fields append dictated text by default, while title/name/tag fields replace the current value.

## Usage

When speech input is enabled, microphone buttons appear beside supported fields. Users can click a microphone button to record, click again to stop, and the transcribed text is inserted into the target field.

For agents, users can dictate a brief in the Instruction Brief field and choose **Draft Instructions**. The model-generated instructions are inserted into the Markdown editor and remain editable before the user clicks Next or saves.

## Testing and Validation

- Functional source contract: `functional_tests/test_voice_assisted_authoring.py`
- Optional Playwright smoke test: `ui_tests/test_voice_assisted_form_inputs.py`
- JavaScript syntax validation: `node --check application/single_app/static/js/form-voice-input.js`
- Backend syntax validation: `python -m py_compile application/single_app/route_backend_agents.py`

Known limitation: browser and service permission failures are surfaced to the user, but the feature is unavailable when speech-to-text is disabled by configuration.
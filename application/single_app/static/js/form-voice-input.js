// form-voice-input.js
// Shared speech-to-text controls for form fields outside the chat composer.

(function () {
    const MAX_RECORDING_DURATION_MS = 90000;
    const DEFAULT_TRANSCRIPTION_ENDPOINT = '/api/speech/transcribe-chat';
    const fieldControls = new WeakMap();
    const controls = [];
    let activeControl = null;

    function isSpeechEnabled() {
        return Boolean(window.appSettings?.enable_speech_to_text_input);
    }

    function supportsRecording() {
        return Boolean(
            navigator.mediaDevices
            && navigator.mediaDevices.getUserMedia
            && window.MediaRecorder
            && (window.AudioContext || window.webkitAudioContext)
        );
    }

    function normalizeTagName(value) {
        return String(value || '')
            .trim()
            .toLowerCase()
            .replace(/&/g, ' and ')
            .replace(/[^a-z0-9_-]+/g, '-')
            .replace(/[-_]{2,}/g, '-')
            .replace(/^[-_]+|[-_]+$/g, '')
            .slice(0, 50);
    }

    function splitCommaList(value) {
        return String(value || '')
            .replace(/\r?\n/g, ',')
            .replace(/;/g, ',')
            .split(',')
            .map(item => item.trim().replace(/^[.\-:;]+|[.\-:;]+$/g, ''))
            .filter(Boolean);
    }

    function normalizeCommaList(value) {
        return splitCommaList(value).join(', ');
    }

    function mergeCommaLists(existingValue, newValue) {
        const combined = [...splitCommaList(existingValue), ...splitCommaList(newValue)];
        const seen = new Set();
        return combined
            .filter(item => {
                const key = item.toLowerCase();
                if (seen.has(key)) {
                    return false;
                }
                seen.add(key);
                return true;
            })
            .join(', ');
    }

    function createIcon(iconClass) {
        const icon = document.createElement('i');
        icon.className = iconClass;
        icon.setAttribute('aria-hidden', 'true');
        return icon;
    }

    function setButtonIcon(button, iconClass) {
        button.replaceChildren(createIcon(iconClass));
    }

    function createVoiceButton(label) {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'btn btn-outline-secondary btn-sm simplechat-voice-input-btn';
        button.title = label;
        button.setAttribute('aria-label', label);
        setButtonIcon(button, 'bi bi-mic-fill');
        return button;
    }

    function setControlState(control, state) {
        const { button } = control;
        button.classList.remove('btn-outline-secondary', 'btn-danger', 'btn-outline-primary');
        button.disabled = false;

        if (state === 'recording') {
            button.classList.add('btn-danger');
            button.title = 'Stop recording';
            button.setAttribute('aria-label', 'Stop recording');
            setButtonIcon(button, 'bi bi-stop-circle-fill');
        } else if (state === 'transcribing') {
            button.classList.add('btn-outline-primary');
            button.title = 'Transcribing';
            button.setAttribute('aria-label', 'Transcribing');
            button.disabled = true;
            const spinner = document.createElement('span');
            spinner.className = 'spinner-border spinner-border-sm';
            spinner.setAttribute('aria-hidden', 'true');
            button.replaceChildren(spinner);
        } else {
            button.classList.add('btn-outline-secondary');
            button.title = control.options.label || 'Dictate';
            button.setAttribute('aria-label', control.options.label || 'Dictate');
            setButtonIcon(button, 'bi bi-mic-fill');
            syncButtonDisabled(control);
        }
    }

    function showToast(message, type = 'info') {
        if (typeof window.showToast === 'function') {
            window.showToast(message, type);
            return;
        }

        if (!window.bootstrap?.Toast) {
            console.log(`[VoiceInput] ${message}`);
            return;
        }

        const allowedTypes = new Set(['success', 'danger', 'warning', 'info', 'primary', 'secondary']);
        const toastType = allowedTypes.has(type) ? type : 'info';
        let container = document.getElementById('voice-input-toast-container');
        if (!container) {
            container = document.createElement('div');
            container.id = 'voice-input-toast-container';
            container.className = 'toast-container position-fixed top-0 end-0 p-3';
            container.style.zIndex = '1080';
            document.body.appendChild(container);
        }

        const toastElement = document.createElement('div');
        toastElement.className = `toast align-items-center text-bg-${toastType} border-0`;
        toastElement.setAttribute('role', 'status');
        toastElement.setAttribute('aria-live', 'polite');
        toastElement.setAttribute('aria-atomic', 'true');

        const toastBodyRow = document.createElement('div');
        toastBodyRow.className = 'd-flex';

        const toastBody = document.createElement('div');
        toastBody.className = 'toast-body';
        toastBody.textContent = message;

        const closeButton = document.createElement('button');
        closeButton.type = 'button';
        closeButton.className = 'btn-close btn-close-white me-2 m-auto';
        closeButton.setAttribute('data-bs-dismiss', 'toast');
        closeButton.setAttribute('aria-label', 'Close');

        toastBodyRow.appendChild(toastBody);
        toastBodyRow.appendChild(closeButton);
        toastElement.appendChild(toastBodyRow);
        container.appendChild(toastElement);

        const toast = new window.bootstrap.Toast(toastElement, { delay: 4000 });
        toastElement.addEventListener('hidden.bs.toast', () => toastElement.remove());
        toast.show();
    }

    function getFieldValue(control) {
        if (typeof control.options.getValue === 'function') {
            return String(control.options.getValue() || '');
        }
        return String(control.field.value || '');
    }

    function setFieldValue(control, value) {
        if (typeof control.options.setValue === 'function') {
            control.options.setValue(value);
        } else {
            control.field.value = value;
        }

        control.field.dispatchEvent(new Event('input', { bubbles: true }));
        control.field.dispatchEvent(new Event('change', { bubbles: true }));

        if (typeof control.options.onValueChanged === 'function') {
            control.options.onValueChanged(value);
        }
    }

    function buildUpdatedValue(control, transcribedText) {
        const mode = control.options.mode || 'text';
        const insertMode = control.options.insertMode || (mode === 'tag' ? 'replace' : 'append');
        const existingValue = getFieldValue(control).trim();
        let normalizedText = String(transcribedText || '').trim();

        if (mode === 'tag') {
            normalizedText = normalizeTagName(normalizedText);
        } else if (mode === 'comma-list') {
            normalizedText = normalizeCommaList(normalizedText);
        }

        if (!normalizedText) {
            return existingValue;
        }

        if (mode === 'comma-list' && insertMode !== 'replace') {
            return mergeCommaLists(existingValue, normalizedText);
        }

        if (!existingValue || insertMode === 'replace') {
            return normalizedText;
        }

        const separator = control.field.tagName === 'TEXTAREA' ? '\n' : ' ';
        return `${existingValue}${separator}${normalizedText}`;
    }

    function getRecordingOptions() {
        if (window.MediaRecorder?.isTypeSupported?.('audio/webm;codecs=opus')) {
            return { mimeType: 'audio/webm;codecs=opus' };
        }
        if (window.MediaRecorder?.isTypeSupported?.('audio/webm')) {
            return { mimeType: 'audio/webm' };
        }
        return {};
    }

    function writeWavString(view, offset, value) {
        for (let index = 0; index < value.length; index += 1) {
            view.setUint8(offset + index, value.charCodeAt(index));
        }
    }

    function createWavBlob(samples, sampleRate) {
        const buffer = new ArrayBuffer(44 + samples.length * 2);
        const view = new DataView(buffer);

        writeWavString(view, 0, 'RIFF');
        view.setUint32(4, 36 + samples.length * 2, true);
        writeWavString(view, 8, 'WAVE');
        writeWavString(view, 12, 'fmt ');
        view.setUint32(16, 16, true);
        view.setUint16(20, 1, true);
        view.setUint16(22, 1, true);
        view.setUint32(24, sampleRate, true);
        view.setUint32(28, sampleRate * 2, true);
        view.setUint16(32, 2, true);
        view.setUint16(34, 16, true);
        writeWavString(view, 36, 'data');
        view.setUint32(40, samples.length * 2, true);

        for (let index = 0; index < samples.length; index += 1) {
            view.setInt16(44 + index * 2, samples[index], true);
        }

        return new Blob([buffer], { type: 'audio/wav' });
    }

    async function convertToWav(audioBlob) {
        const AudioContextCtor = window.AudioContext || window.webkitAudioContext;
        const audioContext = new AudioContextCtor({ sampleRate: 16000 });

        try {
            const arrayBuffer = await audioBlob.arrayBuffer();
            const audioBuffer = await audioContext.decodeAudioData(arrayBuffer);
            let audioData;

            if (audioBuffer.numberOfChannels > 1) {
                const left = audioBuffer.getChannelData(0);
                const right = audioBuffer.getChannelData(1);
                audioData = new Float32Array(left.length);
                for (let index = 0; index < left.length; index += 1) {
                    audioData[index] = (left[index] + right[index]) / 2;
                }
            } else {
                audioData = audioBuffer.getChannelData(0);
            }

            const samples = new Int16Array(audioData.length);
            for (let index = 0; index < audioData.length; index += 1) {
                const sample = Math.max(-1, Math.min(1, audioData[index]));
                samples[index] = sample < 0 ? sample * 0x8000 : sample * 0x7fff;
            }

            return createWavBlob(samples, audioBuffer.sampleRate);
        } finally {
            await audioContext.close();
        }
    }

    function stopTracks(control) {
        if (!control.stream) {
            return;
        }
        control.stream.getTracks().forEach(track => track.stop());
        control.stream = null;
    }

    async function sendForTranscription(control, audioChunks, mimeType) {
        if (!audioChunks.length) {
            return;
        }

        setControlState(control, 'transcribing');
        const originalBlob = new Blob(audioChunks, { type: mimeType || 'audio/webm' });
        const wavBlob = await convertToWav(originalBlob);
        const formData = new FormData();
        formData.append('audio', wavBlob, 'recording.wav');

        const response = await fetch(control.options.endpoint || DEFAULT_TRANSCRIPTION_ENDPOINT, {
            method: 'POST',
            body: formData,
        });
        const result = await response.json().catch(() => ({}));

        if (!response.ok || !result.success || !result.text) {
            throw new Error(result.error || 'Failed to transcribe audio.');
        }

        const updatedValue = buildUpdatedValue(control, result.text);
        setFieldValue(control, updatedValue);
        showToast(control.options.successMessage || 'Voice input transcribed.', 'success');
    }

    function clearRecordingTimeout(control) {
        if (control.recordingTimeoutId) {
            window.clearTimeout(control.recordingTimeoutId);
            control.recordingTimeoutId = null;
        }
    }

    function stopRecording(control) {
        if (!control.mediaRecorder || control.mediaRecorder.state !== 'recording') {
            return;
        }
        clearRecordingTimeout(control);
        control.mediaRecorder.stop();
        stopTracks(control);
    }

    async function startRecording(control) {
        if (!isSpeechEnabled()) {
            showToast('Speech-to-text input is not enabled.', 'warning');
            return;
        }

        if (!supportsRecording()) {
            showToast('Audio recording is not supported in this browser.', 'warning');
            return;
        }

        if (control.field.disabled || control.field.readOnly) {
            return;
        }

        if (activeControl && activeControl !== control) {
            showToast('Finish the current voice input first.', 'warning');
            return;
        }

        const audioChunks = [];
        try {
            control.stream = await navigator.mediaDevices.getUserMedia({
                audio: {
                    sampleRate: 16000,
                    channelCount: 1,
                    echoCancellation: true,
                    noiseSuppression: true,
                },
            });

            control.mediaRecorder = new MediaRecorder(control.stream, getRecordingOptions());
            control.mediaRecorder.addEventListener('dataavailable', event => {
                if (event.data && event.data.size > 0) {
                    audioChunks.push(event.data);
                }
            });

            control.mediaRecorder.addEventListener('stop', async () => {
                activeControl = null;
                try {
                    await sendForTranscription(control, audioChunks, control.mediaRecorder?.mimeType);
                } catch (error) {
                    console.error('[VoiceInput] Transcription failed:', error);
                    showToast(error.message || 'Voice input failed.', 'danger');
                } finally {
                    setControlState(control, 'idle');
                }
            }, { once: true });

            activeControl = control;
            setControlState(control, 'recording');
            control.mediaRecorder.start(1000);
            control.recordingTimeoutId = window.setTimeout(() => stopRecording(control), MAX_RECORDING_DURATION_MS);
        } catch (error) {
            activeControl = null;
            stopTracks(control);
            setControlState(control, 'idle');
            if (error.name === 'NotAllowedError' || error.name === 'PermissionDeniedError') {
                showToast('Microphone permission denied.', 'warning');
            } else {
                console.error('[VoiceInput] Recording failed:', error);
                showToast(error.message || 'Unable to start voice input.', 'danger');
            }
        }
    }

    function handleButtonClick(control) {
        if (activeControl === control && control.mediaRecorder?.state === 'recording') {
            stopRecording(control);
            return;
        }
        startRecording(control);
    }

    function syncButtonDisabled(control) {
        const shouldDisable = !isSpeechEnabled()
            || !supportsRecording()
            || control.field.disabled
            || control.field.readOnly;
        control.button.disabled = shouldDisable;
    }

    function getTextareaInsertionReference(field) {
        const nextElement = field.nextElementSibling;
        if (nextElement?.classList?.contains('CodeMirror')) {
            return nextElement;
        }

        const wrapper = field.closest('.EasyMDEContainer, .editor-preview-side, .CodeMirror')
            || field.parentElement?.querySelector('.CodeMirror');
        return wrapper || field;
    }

    function insertButtonForField(field, button) {
        if (field.tagName !== 'TEXTAREA') {
            const existingGroup = field.closest('.input-group');
            if (existingGroup) {
                existingGroup.appendChild(button);
                return;
            }

            const inputGroup = document.createElement('div');
            inputGroup.className = 'input-group';
            field.parentNode.insertBefore(inputGroup, field);
            inputGroup.appendChild(field);
            inputGroup.appendChild(button);
            return;
        }

        const toolbar = document.createElement('div');
        toolbar.className = 'd-flex justify-content-end mt-1 simplechat-voice-input-toolbar';
        toolbar.appendChild(button);

        const reference = getTextareaInsertionReference(field);
        reference.parentNode.insertBefore(toolbar, reference.nextSibling);
    }

    function enhanceField(field, options = {}) {
        if (!field) {
            return null;
        }

        const existingControl = fieldControls.get(field);
        if (existingControl) {
            existingControl.options = { ...existingControl.options, ...options };
            syncButtonDisabled(existingControl);
            return existingControl.button;
        }

        const control = {
            field,
            button: createVoiceButton(options.label || 'Dictate'),
            options: { ...options },
            mediaRecorder: null,
            stream: null,
            recordingTimeoutId: null,
        };

        control.button.addEventListener('click', () => handleButtonClick(control));
        insertButtonForField(field, control.button);
        fieldControls.set(field, control);
        controls.push(control);
        setControlState(control, 'idle');

        return control.button;
    }

    function enhanceFieldById(fieldId, options = {}) {
        return enhanceField(document.getElementById(fieldId), options);
    }

    function refreshButtons() {
        controls.forEach(control => syncButtonDisabled(control));
    }

    function initializeDefaultFields() {
        if (!isSpeechEnabled()) {
            return;
        }

        [
            ['agent-display-name', { label: 'Dictate display name', insertMode: 'replace' }],
            ['agent-description', { label: 'Dictate description' }],
            ['agent-instruction-brief', { label: 'Dictate instruction brief' }],
            ['workflow-name', { label: 'Dictate workflow name', insertMode: 'replace' }],
            ['workflow-description', { label: 'Dictate workflow description' }],
            ['workflow-task-brief', { label: 'Dictate task brief' }],
            ['workflow-task-prompt', { label: 'Dictate workflow or task instructions' }],
            ['plugin-display-name', { label: 'Dictate action display name', insertMode: 'replace' }],
            ['plugin-name', { label: 'Dictate action name', mode: 'tag', insertMode: 'replace' }],
            ['plugin-description', { label: 'Dictate action description' }],
            ['groupName', { label: 'Dictate group name', insertMode: 'replace' }],
            ['groupDescription', { label: 'Dictate group description' }],
            ['editGroupName', { label: 'Dictate group name', insertMode: 'replace' }],
            ['editGroupDescription', { label: 'Dictate group description' }],
            ['publicWorkspaceName', { label: 'Dictate public workspace name', insertMode: 'replace' }],
            ['publicWorkspaceDescription', { label: 'Dictate public workspace description' }],
            ['editWorkspaceName', { label: 'Dictate public workspace name', insertMode: 'replace' }],
            ['editWorkspaceDescription', { label: 'Dictate public workspace description' }],
            ['doc-title', { label: 'Dictate title', insertMode: 'replace' }],
            ['doc-abstract', { label: 'Dictate abstract' }],
            ['doc-keywords', { label: 'Dictate keywords', mode: 'comma-list' }],
            ['public-doc-title', { label: 'Dictate title', insertMode: 'replace' }],
            ['public-doc-abstract', { label: 'Dictate abstract' }],
            ['public-doc-keywords', { label: 'Dictate keywords', mode: 'comma-list' }],
            ['new-tag-name', { label: 'Dictate tag name', mode: 'tag', insertMode: 'replace' }],
            ['group-new-tag-name', { label: 'Dictate tag name', mode: 'tag', insertMode: 'replace' }],
            ['public-new-tag-name', { label: 'Dictate tag name', mode: 'tag', insertMode: 'replace' }],
        ].forEach(([fieldId, options]) => enhanceFieldById(fieldId, options));
    }

    window.SimpleChatVoiceInput = {
        enhanceField,
        enhanceFieldById,
        initializeDefaultFields,
        normalizeTagName,
        normalizeCommaList,
        refreshButtons,
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initializeDefaultFields);
    } else {
        initializeDefaultFields();
    }
})();
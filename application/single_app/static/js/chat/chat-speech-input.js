// chat-speech-input.js
/**
 * Speech-to-text chat input module
 * Handles voice recording with visual waveform feedback and transcription
 */

import { showToast } from './chat-toast.js';
import { sendMessage } from './chat-messages.js';
import { saveUserSetting } from './chat-layout.js';

let mediaRecorder = null;
let audioChunks = [];
let recordingStartTime = null;
let countdownInterval = null;
let autoSendTimeout = null;
let autoSendCountdown = null;
let audioContext = null;
let analyser = null;
let animationFrame = null;
let stream = null;
let waveformData = []; // Store waveform amplitudes over time
let isCanceling = false; // Flag to track if recording is being canceled
let microphonePermissionState = 'prompt'; // 'granted', 'denied', or 'prompt'
let userMicrophonePreference = 'ask-every-session'; // User's permission preference
let sessionPermissionRequested = false; // Track if permission was requested this session

const MAX_RECORDING_DURATION = 90; // seconds
let remainingTime = MAX_RECORDING_DURATION;

/**
 * Check if browser supports required APIs
 */
function checkBrowserSupport() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        return { supported: false, message: 'Your browser does not support audio recording' };
    }
    
    if (!window.MediaRecorder) {
        return { supported: false, message: 'Your browser does not support MediaRecorder API' };
    }
    
    if (!window.AudioContext && !window.webkitAudioContext) {
        return { supported: false, message: 'Your browser does not support Web Audio API' };
    }
    
    return { supported: true };
}

/**
 * Initialize speech input functionality
 */
export function initializeSpeechInput() {
    console.log('Initializing speech input...');
    
    const speechBtn = document.getElementById('speech-input-btn');
    
    if (!speechBtn) {
        console.warn('Speech input button not found in DOM');
        return; // Speech input not enabled
    }
    
    console.log('Speech input button found:', speechBtn);
    
    // Check browser support
    const support = checkBrowserSupport();
    if (!support.supported) {
        speechBtn.style.display = 'none';
        console.warn('Speech input disabled:', support.message);
        return;
    }
    
    console.log('Browser supports speech input');
    
    // Load user microphone preferences
    loadMicrophonePreference().then(() => {
        // Check permission state and update icon
        checkMicrophonePermissionState();
    });
    
    // Attach event listener
    speechBtn.addEventListener('click', handleSpeechButtonClick);
    
    // Attach recording control listeners
    const cancelBtn = document.getElementById('cancel-recording-btn');
    const sendBtn = document.getElementById('send-recording-btn');
    
    if (cancelBtn) {
        cancelBtn.addEventListener('click', cancelRecording);
        console.log('Cancel button listener attached');
    }
    
    if (sendBtn) {
        sendBtn.addEventListener('click', stopAndSendRecording);
        console.log('Send button listener attached');
    }
    
    console.log('Speech input initialization complete');
}

/**
 * Handle speech button click - check permission state first
 */
async function handleSpeechButtonClick() {
    console.log('Speech button clicked!');
    
    // If permission is denied, navigate to profile settings
    if (microphonePermissionState === 'denied') {
        console.log('Microphone permission denied, redirecting to profile settings');
        window.location.href = '/profile#speech-settings';
        return;
    }
    
    // Check if we should request permission based on user preference
    if (shouldRequestPermission()) {
        await checkMicrophonePermissionState();
    }
    
    // Start recording
    startRecording();
}

/**
 * Check if we should request permission based on user preference
 */
function shouldRequestPermission() {
    switch (userMicrophonePreference) {
        case 'remember':
            // Only request once ever
            return microphonePermissionState === 'prompt';
        case 'ask-every-session':
            // Request once per browser session
            return !sessionPermissionRequested;
        case 'ask-every-page-load':
            // Request on every page load
            return true;
        default:
            return !sessionPermissionRequested;
    }
}

/**
 * Load user's microphone permission preference from settings
 */
async function loadMicrophonePreference() {
    try {
        const response = await fetch('/api/user/settings');
        const data = await response.json();
        const settings = data.settings || {};
        
        // Microphone permission preference removed - browser controls permission state
        console.log('Loaded microphone preference:', userMicrophonePreference);
        
        return userMicrophonePreference;
    } catch (error) {
        console.error('Error loading microphone preference:', error);
        userMicrophonePreference = 'ask-every-session';
        return userMicrophonePreference;
    }
}

/**
 * Check microphone permission state and update UI
 */
async function checkMicrophonePermissionState() {
    try {
        // Try to get media to check permission state
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        
        // Permission granted
        stream.getTracks().forEach(track => track.stop());
        microphonePermissionState = 'granted';
        sessionPermissionRequested = true;
        updateMicrophoneIconState('granted');
        
        // Save state if preference is 'remember'
        if (userMicrophonePreference === 'remember') {
            await savePermissionState('granted');
        }
        
    } catch (error) {
        if (error.name === 'NotAllowedError' || error.name === 'PermissionDeniedError') {
            microphonePermissionState = 'denied';
            sessionPermissionRequested = true;
            updateMicrophoneIconState('denied');
            
            // Save state if preference is 'remember'
            if (userMicrophonePreference === 'remember') {
                await savePermissionState('denied');
            }
        } else {
            console.error('Error checking microphone permission:', error);
            microphonePermissionState = 'prompt';
            updateMicrophoneIconState('prompt');
        }
    }
}

/**
 * Update microphone icon state with color and tooltip
 */
function updateMicrophoneIconState(state) {
    const speechBtn = document.getElementById('speech-input-btn');
    if (!speechBtn) return;
    
    const icon = speechBtn.querySelector('i');
    if (!icon) return;
    
    // Remove existing state classes
    icon.classList.remove('text-success', 'text-danger', 'text-secondary');
    
    switch(state) {
        case 'granted':
            icon.classList.add('text-success');
            speechBtn.title = 'Voice Input (Microphone access granted)';
            break;
        case 'denied':
            icon.classList.add('text-danger');
            speechBtn.title = 'Microphone access denied - Click to manage permissions';
            break;
        case 'prompt':
        default:
            icon.classList.add('text-secondary');
            speechBtn.title = 'Voice Input (Click to enable microphone)';
            break;
    }
    
    console.log('Updated microphone icon state:', state);
}

/**
 * Save permission state to user settings
 */
async function savePermissionState(state) {
    try {
        await saveUserSetting({
            microphonePermissionState: state
        });
        console.log('Saved microphone permission state:', state);
    } catch (error) {
        console.error('Error saving microphone permission state:', error);
    }
}

/**
 * Start recording audio
 */
async function startRecording() {
    try {
        // Request microphone permission
        stream = await navigator.mediaDevices.getUserMedia({ 
            audio: {
                sampleRate: 16000,  // Azure Speech SDK works well with 16kHz
                channelCount: 1,     // Mono
                echoCancellation: true,
                noiseSuppression: true
            }
        });
        
        // Set up MediaRecorder - try WAV first, fallback to WebM
        let options = {};
        let fileExtension = 'webm';
        
        // Try WAV format first (best for Azure Speech SDK, no conversion needed)
        if (MediaRecorder.isTypeSupported('audio/wav')) {
            options.mimeType = 'audio/wav';
            fileExtension = 'wav';
        } 
        // Try WebM with Opus codec
        else if (MediaRecorder.isTypeSupported('audio/webm;codecs=opus')) {
            options.mimeType = 'audio/webm;codecs=opus';
            fileExtension = 'webm';
        }
        // Fallback to default WebM
        else if (MediaRecorder.isTypeSupported('audio/webm')) {
            options.mimeType = 'audio/webm';
            fileExtension = 'webm';
        }
        
        console.log('Using audio format:', options.mimeType || 'default');
        
        console.log('Using audio format:', options.mimeType || 'default');
        
        mediaRecorder = new MediaRecorder(stream, options);
        
        // Store the file extension for later use
        mediaRecorder.fileExtension = fileExtension;
        audioChunks = [];
        isCanceling = false; // Reset cancel flag when starting new recording
        
        mediaRecorder.addEventListener('dataavailable', (event) => {
            if (event.data.size > 0) {
                console.log('[Recording] Audio chunk received, size:', event.data.size);
                audioChunks.push(event.data);
            }
        });
        
        mediaRecorder.addEventListener('stop', handleRecordingStop);
        
        // Start recording - request data every second for better chunk collection
        mediaRecorder.start(1000); // Timeslice: 1000ms
        recordingStartTime = Date.now();
        remainingTime = MAX_RECORDING_DURATION;
        
        console.log('[Recording] Started with 1-second timeslice for better chunk collection');
        
        // Reset waveform data
        waveformData = [];
        
        // Show recording UI
        showRecordingUI();
        
        // Start waveform visualization
        startWaveformVisualization(stream);
        
        // Start countdown timer
        startCountdown();
        
        // Update permission state to granted
        microphonePermissionState = 'granted';
        sessionPermissionRequested = true;
        updateMicrophoneIconState('granted');
        
        // Save state if preference is 'remember'
        if (userMicrophonePreference === 'remember') {
            await savePermissionState('granted');
        }
        
    } catch (error) {
        console.error('Error starting recording:', error);
        
        if (error.name === 'NotAllowedError' || error.name === 'PermissionDeniedError') {
            microphonePermissionState = 'denied';
            sessionPermissionRequested = true;
            updateMicrophoneIconState('denied');
            
            // Save state if preference is 'remember'
            if (userMicrophonePreference === 'remember') {
                await savePermissionState('denied');
            }
            
            showToast('Microphone permission denied. Click the microphone icon to manage permissions.', 'warning');
        } else {
            showToast('Error starting recording: ' + error.message, 'danger');
        }
    }
}

/**
 * Stop recording and send for transcription
 */
function stopAndSendRecording() {
    if (mediaRecorder && mediaRecorder.state === 'recording') {
        const recordingDuration = (Date.now() - recordingStartTime) / 1000;
        console.log('[Recording] Stopping recording after', recordingDuration.toFixed(2), 'seconds');
        console.log('[Recording] Total chunks collected so far:', audioChunks.length);
        
        mediaRecorder.stop();
        
        // Stop all tracks
        if (stream) {
            stream.getTracks().forEach(track => track.stop());
        }
    }
}

/**
/**
 * Cancel recording
 */
function cancelRecording() {
    // Set cancel flag BEFORE stopping the recorder
    isCanceling = true;
    
    if (mediaRecorder && mediaRecorder.state === 'recording') {
        mediaRecorder.stop();
        
        // Stop all tracks
        if (stream) {
            stream.getTracks().forEach(track => track.stop());
        }
    }
    
    // Clear waveform data
    waveformData = [];
    
    // Clear audio chunks
    audioChunks = [];
    
    // Reset UI
    hideRecordingUI();
    stopWaveformVisualization();
    stopCountdown();
}

/**
 * Convert audio blob to WAV format using Web Audio API
 * @param {Blob} audioBlob - The audio blob to convert
 * @returns {Promise<Blob>} WAV formatted audio blob
 */
async function convertToWav(audioBlob) {
    console.log('Converting audio to WAV format...');
    
    // Create audio context
    const audioContext = new (window.AudioContext || window.webkitAudioContext)({
        sampleRate: 16000 // 16kHz for Azure Speech SDK
    });
    
    // Convert blob to array buffer
    const arrayBuffer = await audioBlob.arrayBuffer();
    
    // Decode audio data
    const audioBuffer = await audioContext.decodeAudioData(arrayBuffer);
    
    console.log('Audio decoded:', {
        sampleRate: audioBuffer.sampleRate,
        duration: audioBuffer.duration,
        channels: audioBuffer.numberOfChannels
    });
    
    // Get audio data (convert to mono if needed)
    let audioData;
    if (audioBuffer.numberOfChannels > 1) {
        // Mix down to mono
        const left = audioBuffer.getChannelData(0);
        const right = audioBuffer.getChannelData(1);
        audioData = new Float32Array(left.length);
        for (let i = 0; i < left.length; i++) {
            audioData[i] = (left[i] + right[i]) / 2;
        }
    } else {
        audioData = audioBuffer.getChannelData(0);
    }
    
    // Convert float32 to int16 (WAV PCM format)
    const int16Data = new Int16Array(audioData.length);
    for (let i = 0; i < audioData.length; i++) {
        const s = Math.max(-1, Math.min(1, audioData[i]));
        int16Data[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
    }
    
    // Create WAV file
    const wavBlob = createWavBlob(int16Data, audioBuffer.sampleRate);
    
    console.log('WAV conversion complete:', {
        originalSize: audioBlob.size,
        wavSize: wavBlob.size,
        sampleRate: audioBuffer.sampleRate
    });
    
    // Close audio context
    await audioContext.close();
    
    return wavBlob;
}

/**
 * Create a WAV blob from PCM data
 * @param {Int16Array} samples - PCM audio samples
 * @param {number} sampleRate - Sample rate in Hz
 * @returns {Blob} WAV formatted blob
 */
function createWavBlob(samples, sampleRate) {
    const buffer = new ArrayBuffer(44 + samples.length * 2);
    const view = new DataView(buffer);
    
    // Write WAV header
    const writeString = (offset, string) => {
        for (let i = 0; i < string.length; i++) {
            view.setUint8(offset + i, string.charCodeAt(i));
        }
    };
    
    writeString(0, 'RIFF');
    view.setUint32(4, 36 + samples.length * 2, true);
    writeString(8, 'WAVE');
    writeString(12, 'fmt ');
    view.setUint32(16, 16, true); // fmt chunk size
    view.setUint16(20, 1, true); // PCM format
    view.setUint16(22, 1, true); // Mono channel
    view.setUint32(24, sampleRate, true);
    view.setUint32(28, sampleRate * 2, true); // byte rate
    view.setUint16(32, 2, true); // block align
    view.setUint16(34, 16, true); // bits per sample
    writeString(36, 'data');
    view.setUint32(40, samples.length * 2, true);
    
    // Write PCM data
    const offset = 44;
    for (let i = 0; i < samples.length; i++) {
        view.setInt16(offset + i * 2, samples[i], true);
    }
    
    return new Blob([buffer], { type: 'audio/wav' });
}

/**
 * Handle recording stop event
 */
async function handleRecordingStop() {
    if (isCanceling) {
        console.log('Recording canceled by user');
        hideRecordingUI();
        isCanceling = false; // Reset flag
        return;
    }
    
    // Check if recording was canceled
    stopWaveformVisualization();
    stopCountdown();
    
    // Check if recording was canceled (no chunks)
    if (audioChunks.length === 0) {
        hideRecordingUI();
        return;
    }
    
    // Get the MIME type from the MediaRecorder
    const mimeType = mediaRecorder && mediaRecorder.mimeType ? mediaRecorder.mimeType : 'audio/webm';
    
    // Create blob from chunks with correct MIME type
    const originalBlob = new Blob(audioChunks, { type: mimeType });
    
    console.log('Original audio blob created:', { type: mimeType, size: originalBlob.size });
    
    // Show processing state
    const sendBtn = document.getElementById('send-recording-btn');
    const cancelBtn = document.getElementById('cancel-recording-btn');
    
    if (sendBtn) {
        sendBtn.disabled = true;
        sendBtn.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';
    }
    
    if (cancelBtn) {
        cancelBtn.disabled = true;
    }
    
    try {
        // Convert to WAV format for Azure Speech SDK compatibility
        const wavBlob = await convertToWav(originalBlob);
        
        console.log('[Recording] WAV conversion complete, sending to backend');
        
        // Update button text - keep same spinner
        if (sendBtn) {
            sendBtn.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';
        }
        
        // Send to backend for transcription
        const formData = new FormData();
        formData.append('audio', wavBlob, 'recording.wav');
        
        console.log('[Recording] Sending WAV audio to backend, size:', wavBlob.size);
        
        const response = await fetch('/api/speech/transcribe-chat', {
            method: 'POST',
            body: formData
        });
        
        const result = await response.json();
        
        if (result.success && result.text) {
            // Append transcribed text to existing input
            const userInput = document.getElementById('user-input');
            if (userInput) {
                console.log('[Speech Input] Transcription successful:', result.text);
                
                // Check if there's existing text
                const existingText = userInput.value.trim();
                
                if (existingText) {
                    // Append with newline separator
                    userInput.value = existingText + '\n' + result.text;
                } else {
                    // No existing text, just set the transcription
                    userInput.value = result.text;
                }
                
                console.log('[Speech Input] User input updated, value length:', userInput.value.length);
                
                // Adjust textarea height
                userInput.style.height = '';
                userInput.style.height = Math.min(userInput.scrollHeight, 200) + 'px';
                
                // Trigger input change to show send button
                if (window.handleInputChange) {
                    window.handleInputChange();
                }
            }
            
            showToast('Voice message transcribed successfully', 'success');
            
            console.log('[Speech Input] Starting auto-send countdown...');
            // Start auto-send countdown
            startAutoSendCountdown();
        } else {
            showToast(result.error || 'Failed to transcribe audio', 'danger');
        }
        
    } catch (error) {
        console.error('Error transcribing audio:', error);
        showToast('Error transcribing audio: ' + error.message, 'danger');
    } finally {
        // Reset UI
        hideRecordingUI();
        
        if (sendBtn) {
            sendBtn.disabled = false;
            sendBtn.innerHTML = '<i class="bi bi-check-circle-fill"></i>';
        }
        
        if (cancelBtn) {
            cancelBtn.disabled = false;
        }
    }
}

/**
 * Show recording UI and hide normal input
 */
function showRecordingUI() {
    const normalContainer = document.getElementById('normal-input-container');
    const recordingContainer = document.getElementById('recording-container');
    
    if (normalContainer) {
        normalContainer.style.display = 'none';
    }
    
    if (recordingContainer) {
        recordingContainer.style.display = 'block';
    }
}

/**
 * Hide recording UI and show normal input
 */
function hideRecordingUI() {
    const normalContainer = document.getElementById('normal-input-container');
    const recordingContainer = document.getElementById('recording-container');
    
    if (normalContainer) {
        normalContainer.style.display = 'block';
    }
    
    if (recordingContainer) {
        recordingContainer.style.display = 'none';
    }
}

/**
 * Start waveform visualization
 */
function startWaveformVisualization(audioStream) {
    const canvas = document.getElementById('waveform-canvas');
    if (!canvas) return;
    
    const canvasCtx = canvas.getContext('2d');
    
    // Set canvas size - height is now 36px to match buttons
    canvas.width = canvas.offsetWidth;
    canvas.height = 36;
    
    // Create audio context and analyser
    const AudioContext = window.AudioContext || window.webkitAudioContext;
    audioContext = new AudioContext();
    analyser = audioContext.createAnalyser();
    analyser.fftSize = 256;
    
    const source = audioContext.createMediaStreamSource(audioStream);
    source.connect(analyser);
    
    const bufferLength = analyser.frequencyBinCount;
    const dataArray = new Uint8Array(bufferLength);
    
    // Draw function
    function draw() {
        animationFrame = requestAnimationFrame(draw);
        
        analyser.getByteFrequencyData(dataArray);
        
        // Calculate average amplitude for this frame
        let sum = 0;
        for (let i = 0; i < bufferLength; i++) {
            sum += dataArray[i];
        }
        const avgAmplitude = sum / bufferLength / 255; // Normalize to 0-1
        
        // Store amplitude for this frame (keep as 0-1, we'll handle centering in drawing)
        waveformData.push(avgAmplitude);
        
        // Calculate progress (how much of the recording time has elapsed)
        const elapsed = Date.now() - recordingStartTime;
        const elapsedSeconds = elapsed / 1000;
        
        // Check if we've hit the time limit FIRST (before clamping progress)
        if (elapsedSeconds >= MAX_RECORDING_DURATION) {
            console.log('[Recording] Time limit reached at', elapsedSeconds.toFixed(2), 'seconds, auto-stopping...');
            stopAndSendRecording();
            return; // Stop the animation loop
        }
        
        const progress = Math.min(elapsed / (MAX_RECORDING_DURATION * 1000), 1);
        const progressWidth = canvas.width * progress;
        
        // Check if dark mode is active
        const isDarkMode = document.documentElement.getAttribute('data-bs-theme') === 'dark';
        
        // Clear canvas with appropriate background color
        canvasCtx.fillStyle = isDarkMode ? '#343a40' : '#f8f9fa';
        canvasCtx.fillRect(0, 0, canvas.width, canvas.height);
        
        // Draw unfilled area (dashed line at center)
        canvasCtx.setLineDash([5, 5]);
        canvasCtx.strokeStyle = isDarkMode ? '#495057' : '#dee2e6';
        canvasCtx.lineWidth = 1;
        canvasCtx.beginPath();
        canvasCtx.moveTo(progressWidth, canvas.height / 2);
        canvasCtx.lineTo(canvas.width, canvas.height / 2);
        canvasCtx.stroke();
        canvasCtx.setLineDash([]);
        
        // Draw recorded waveform (filled area) - vertical bars
        if (waveformData.length > 1) {
            const centerY = canvas.height / 2;
            const maxBarHeight = canvas.height * 1.95; // Bars can extend 48% of canvas height in each direction (96% total)
            const barSpacing = 3; // Pixels between bars
            const pointsToShow = Math.floor(progressWidth / barSpacing);
            const step = waveformData.length / pointsToShow;
            
            // Determine waveform color based on progress
            let waveformColor = '#0d6efd'; // Default blue
            if (progress >= 0.95) {
                waveformColor = '#dc3545'; // Red
            } else if (progress >= 0.85) {
                waveformColor = '#ffc107'; // Yellow
            }
            
            canvasCtx.lineWidth = 2;
            canvasCtx.strokeStyle = waveformColor;
            
            for (let i = 0; i < pointsToShow && i < waveformData.length; i++) {
                const dataIndex = Math.floor(i * step);
                const amplitude = waveformData[dataIndex];
                const x = i * barSpacing;
                
                // Draw vertical bar from center, extending both up and down
                const barHeight = amplitude * maxBarHeight;
                
                canvasCtx.beginPath();
                canvasCtx.moveTo(x, centerY - barHeight);
                canvasCtx.lineTo(x, centerY + barHeight);
                canvasCtx.stroke();
            }
        }
    }
    
    draw();
}

/**
 * Stop waveform visualization
 */
function stopWaveformVisualization() {
    if (animationFrame) {
        cancelAnimationFrame(animationFrame);
        animationFrame = null;
    }
    
    if (audioContext) {
        audioContext.close();
        audioContext = null;
    }
    
    analyser = null;
}

/**
 * Start countdown timer (progress bar)
 */
function startCountdown() {
    const timerBar = document.getElementById('recording-timer-bar');
    if (!timerBar) return;
    
    const startTime = Date.now();
    const duration = MAX_RECORDING_DURATION * 1000; // Convert to milliseconds
    
    const updateProgress = () => {
        const elapsed = Date.now() - startTime;
        const remaining = duration - elapsed;
        
        if (remaining <= 0) {
            // Time's up - auto stop recording
            remainingTime = 0;
            stopAndSendRecording();
        } else {
            // Calculate percentage remaining based on actual elapsed time
            const percentRemaining = (remaining / duration) * 100;
            remainingTime = Math.ceil(remaining / 1000);
            
            // Update bar width using CSS variable
            document.documentElement.style.setProperty('--recording-timer-width', percentRemaining + '%');
            
            // Change color classes when time is running out
            timerBar.classList.remove('warning', 'danger');
            if (percentRemaining <= 10) {
                timerBar.classList.add('danger');
            } else if (percentRemaining <= 30) {
                timerBar.classList.add('warning');
            }
            
            // Continue animation
            countdownInterval = requestAnimationFrame(updateProgress);
        }
    };
    
    // Start the animation loop
    countdownInterval = requestAnimationFrame(updateProgress);
}

/**
 * Stop countdown timer
 */
function stopCountdown() {
    if (countdownInterval) {
        cancelAnimationFrame(countdownInterval);
        countdownInterval = null;
    }
    
    const timerBar = document.getElementById('recording-timer-bar');
    if (timerBar) {
        document.documentElement.style.setProperty('--recording-timer-width', '100%');
        timerBar.classList.remove('warning', 'danger');
    }
    
    remainingTime = MAX_RECORDING_DURATION;
}

/**
 * Start auto-send countdown after transcription
 */
function startAutoSendCountdown() {
    console.log('[Auto-Send] Starting countdown...');
    
    const totalCountdown = 5; // seconds
    let countdown = totalCountdown;
    const sendBtn = document.getElementById('send-btn');
    
    if (!sendBtn) {
        console.error('[Auto-Send] Send button not found!');
        return;
    }
    
    console.log('[Auto-Send] Send button found, current conversation ID:', window.currentConversationId || 'NEW');
    
    // Store original button state
    const originalHTML = sendBtn.innerHTML;
    const originalDisabled = sendBtn.disabled;
    
    // Add a progress background element
    const progressBg = document.createElement('div');
    progressBg.style.cssText = `
        position: absolute;
        top: 0;
        left: 0;
        height: 100%;
        width: 0%;
        background: linear-gradient(90deg, #0d6efd, #0dcaf0);
        border-radius: 0.375rem;
        transition: width 0.1s linear;
        z-index: -1;
    `;
    sendBtn.style.position = 'relative';
    sendBtn.style.overflow = 'hidden';
    sendBtn.appendChild(progressBg);
    
    // Update button appearance for countdown mode
    sendBtn.style.color = 'white';
    sendBtn.classList.add('btn-primary');
    sendBtn.classList.remove('btn-warning');
    
    // Click handler to cancel auto-send
    const cancelAutoSend = (event) => {
        // Prevent default action and stop event propagation
        event.preventDefault();
        event.stopPropagation();
        event.stopImmediatePropagation();
        
        console.log('[Auto-Send] Cancelled by user');
        clearAutoSend();
        
        // Remove progress background
        if (progressBg.parentNode) {
            progressBg.remove();
        }
        
        sendBtn.innerHTML = originalHTML;
        sendBtn.disabled = originalDisabled;
        sendBtn.style.color = '';
        sendBtn.classList.remove('btn-warning');
        sendBtn.classList.add('btn-primary');
        sendBtn.removeEventListener('click', cancelAutoSend, true);
        showToast('Auto-send cancelled. Click Send when ready.', 'info');
    };
    
    // Add event listener with capture phase to intercept before other handlers
    sendBtn.addEventListener('click', cancelAutoSend, true);
    
    // Animation frame for smooth progress
    const startTime = Date.now();
    const duration = totalCountdown * 1000; // milliseconds
    
    const updateProgress = () => {
        const elapsed = Date.now() - startTime;
        const progress = Math.min(elapsed / duration, 1);
        const percentage = progress * 100;
        
        // Update progress background width
        progressBg.style.width = percentage + '%';
        
        if (progress < 1) {
            autoSendCountdown = requestAnimationFrame(updateProgress);
        } else {
            // Countdown complete - send immediately
            console.log('[Auto-Send] ===== COUNTDOWN COMPLETE =====');
            console.log('[Auto-Send] Current conversation ID:', window.currentConversationId || 'NEW');
            console.log('[Auto-Send] User input value:', document.getElementById('user-input')?.value);
            console.log('[Auto-Send] Chatbox children count:', document.getElementById('chatbox')?.children.length);
            
            // Remove progress background
            if (progressBg.parentNode) {
                progressBg.remove();
            }
            
            // Restore button to original state
            sendBtn.innerHTML = originalHTML;
            sendBtn.disabled = originalDisabled;
            sendBtn.style.color = '';
            sendBtn.classList.remove('btn-warning', 'auto-sending');
            sendBtn.classList.add('btn-primary');
            
            // Remove the cancel listener
            sendBtn.removeEventListener('click', cancelAutoSend, true);
            
            // Clear the auto-send state
            autoSendCountdown = null;
            autoSendTimeout = null;
            
            console.log('[Auto-Send] About to trigger click...');
            // Trigger the send by programmatically clicking the button
            // This ensures all normal send handlers fire
            requestAnimationFrame(() => {
                console.log('[Auto-Send] Clicking send button NOW');
                sendBtn.click();
                console.log('[Auto-Send] Click triggered, conversation ID after:', window.currentConversationId || 'NEW');
            });
        }
    };
    
    // Start the animation
    autoSendCountdown = requestAnimationFrame(updateProgress);
    
    // Also store timeout reference for cleanup
    autoSendTimeout = autoSendCountdown;
}

/**
 * Clear auto-send countdown
 */
function clearAutoSend() {
    if (autoSendCountdown) {
        cancelAnimationFrame(autoSendCountdown);
        autoSendCountdown = null;
    }
    
    if (autoSendTimeout) {
        clearTimeout(autoSendTimeout);
        autoSendTimeout = null;
    }
}


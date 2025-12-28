// chat-speech-input.js
/**
 * Speech-to-text chat input module
 * Handles voice recording with visual waveform feedback and transcription
 */

import { showToast } from './chat-toast.js';
import { sendMessage } from './chat-messages.js';

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
    
    // Attach event listener
    speechBtn.addEventListener('click', () => {
        console.log('Speech button clicked!');
        startRecording();
    });
    
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
        
        mediaRecorder.addEventListener('dataavailable', (event) => {
            if (event.data.size > 0) {
                audioChunks.push(event.data);
            }
        });
        
        mediaRecorder.addEventListener('stop', handleRecordingStop);
        
        // Start recording
        mediaRecorder.start();
        recordingStartTime = Date.now();
        remainingTime = MAX_RECORDING_DURATION;
        
        // Show recording UI
        showRecordingUI();
        
        // Start waveform visualization
        startWaveformVisualization(stream);
        
        // Start countdown timer
        startCountdown();
        
    } catch (error) {
        console.error('Error starting recording:', error);
        
        if (error.name === 'NotAllowedError' || error.name === 'PermissionDeniedError') {
            showToast('Microphone permission denied. Please allow microphone access to use voice input.', 'warning');
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
        mediaRecorder.stop();
        
        // Stop all tracks
        if (stream) {
            stream.getTracks().forEach(track => track.stop());
        }
    }
}

/**
 * Cancel recording
 */
function cancelRecording() {
    if (mediaRecorder && mediaRecorder.state === 'recording') {
        mediaRecorder.stop();
        
        // Stop all tracks
        if (stream) {
            stream.getTracks().forEach(track => track.stop());
        }
    }
    
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
        sendBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Converting...';
    }
    
    if (cancelBtn) {
        cancelBtn.disabled = true;
    }
    
    try {
        // Convert to WAV format for Azure Speech SDK compatibility
        const wavBlob = await convertToWav(originalBlob);
        
        // Update button text
        if (sendBtn) {
            sendBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Transcribing...';
        }
        
        // Send to backend for transcription
        const formData = new FormData();
        formData.append('audio', wavBlob, 'recording.wav');
        
        console.log('Sending WAV audio to backend');
        
        const response = await fetch('/api/speech/transcribe-chat', {
            method: 'POST',
            body: formData
        });
        
        const result = await response.json();
        
        if (result.success && result.text) {
            // Append transcribed text to existing input
            const userInput = document.getElementById('user-input');
            if (userInput) {
                // Check if there's existing text
                const existingText = userInput.value.trim();
                
                if (existingText) {
                    // Append with newline separator
                    userInput.value = existingText + '\n' + result.text;
                } else {
                    // No existing text, just set the transcription
                    userInput.value = result.text;
                }
                
                // Adjust textarea height
                userInput.style.height = '';
                userInput.style.height = Math.min(userInput.scrollHeight, 200) + 'px';
                
                // Trigger input change to show send button
                if (window.handleInputChange) {
                    window.handleInputChange();
                }
            }
            
            showToast('Voice message transcribed successfully', 'success');
            
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
            sendBtn.innerHTML = '<i class="bi bi-check-circle-fill"></i> Send';
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
    
    // Set canvas size
    canvas.width = canvas.offsetWidth;
    canvas.height = 100;
    
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
        
        canvasCtx.fillStyle = '#f8f9fa';
        canvasCtx.fillRect(0, 0, canvas.width, canvas.height);
        
        const barWidth = (canvas.width / bufferLength) * 2.5;
        let barHeight;
        let x = 0;
        
        for (let i = 0; i < bufferLength; i++) {
            barHeight = (dataArray[i] / 255) * canvas.height * 0.8;
            
            // Gradient from primary to success color
            const gradient = canvasCtx.createLinearGradient(0, canvas.height - barHeight, 0, canvas.height);
            gradient.addColorStop(0, '#0d6efd');
            gradient.addColorStop(1, '#198754');
            
            canvasCtx.fillStyle = gradient;
            canvasCtx.fillRect(x, canvas.height - barHeight, barWidth, barHeight);
            
            x += barWidth + 1;
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
    console.log('Starting auto-send countdown...');
    
    let countdown = 5;
    const sendBtn = document.getElementById('send-btn');
    
    if (!sendBtn) {
        console.warn('Send button not found for auto-send countdown');
        return;
    }
    
    // Store original button state
    const originalHTML = sendBtn.innerHTML;
    const originalDisabled = sendBtn.disabled;
    
    // Update button to show countdown number
    const updateCountdownButton = () => {
        sendBtn.innerHTML = `${countdown}`;
        sendBtn.classList.add('btn-warning');
        sendBtn.classList.remove('btn-primary');
    };
    
    updateCountdownButton();
    
    // Click handler to cancel auto-send
    const cancelAutoSend = (event) => {
        // Prevent default action and stop event propagation
        event.preventDefault();
        event.stopPropagation();
        event.stopImmediatePropagation();
        
        console.log('Auto-send cancelled by user');
        clearAutoSend();
        sendBtn.innerHTML = originalHTML;
        sendBtn.disabled = originalDisabled;
        sendBtn.classList.remove('btn-warning');
        sendBtn.classList.add('btn-primary');
        sendBtn.removeEventListener('click', cancelAutoSend, true);
        showToast('Auto-send cancelled. Click Send when ready.', 'info');
    };
    
    // Add event listener with capture phase to intercept before other handlers
    sendBtn.addEventListener('click', cancelAutoSend, true);
    
    // Countdown interval
    autoSendCountdown = setInterval(() => {
        countdown--;
        
        if (countdown > 0) {
            updateCountdownButton();
        } else {
            // Countdown reached 0, send message
            clearAutoSend();
            sendBtn.removeEventListener('click', cancelAutoSend, true);
            console.log('Auto-sending message...');
            
            // Restore button to original state
            sendBtn.innerHTML = originalHTML;
            sendBtn.disabled = originalDisabled;
            sendBtn.classList.remove('btn-warning');
            sendBtn.classList.add('btn-primary');
            
            // Call the actual sendMessage function directly
            sendMessage();
        }
    }, 1000);
    
    // Also store timeout reference for cleanup
    autoSendTimeout = autoSendCountdown;
}

/**
 * Clear auto-send countdown
 */
function clearAutoSend() {
    if (autoSendCountdown) {
        clearInterval(autoSendCountdown);
        autoSendCountdown = null;
    }
    
    if (autoSendTimeout) {
        clearTimeout(autoSendTimeout);
        autoSendTimeout = null;
    }
}


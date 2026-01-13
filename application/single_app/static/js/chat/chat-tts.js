// chat-tts.js - Text-to-Speech functionality for chat messages

import { showToast } from './chat-toast.js';

// TTS State Management
let ttsEnabled = false;
let ttsAutoplay = false;
let ttsVoice = 'en-US-Andrew:DragonHDLatestNeural';
let ttsSpeed = 1.0;
let currentPlayingAudio = null;
let currentPlayingMessageId = null;
let audioQueue = []; // Queue for chunked audio playback
let isQueueing = false; // Track if we're still loading chunks
let wordHighlightInterval = null; // Track word highlighting interval
let currentWordIndex = 0; // Current word being highlighted
let totalWords = 0; // Total words in current chunk
let wordOffset = 0; // Starting word index for current chunk
let highlightState = null; // Store state for pause/resume: { messageId, chunkText, duration, startWordIndex, msPerWord }

// Audio visualization
let audioContext = null;
let analyser = null;
let volumeCheckInterval = null;
let currentAudioSource = null;

/**
 * Initialize TTS settings from user preferences
 */
export async function initializeTTS() {
    try {
        const response = await fetch('/api/user/settings');
        if (!response.ok) {
            throw new Error('Failed to load user settings');
        }
        
        const data = await response.json();
        const settings = data.settings || {};
        
        ttsEnabled = settings.ttsEnabled || false;
        ttsAutoplay = settings.ttsAutoplay || false;
        ttsVoice = settings.ttsVoice || 'en-US-Andrew:DragonHDLatestNeural';
        ttsSpeed = settings.ttsSpeed || 1.0;
        
        console.log('TTS initialized:', { ttsEnabled, ttsAutoplay, ttsVoice, ttsSpeed });
        
        // Update button state after loading settings
        updateAutoplayButton();
        
    } catch (error) {
        console.error('Error initializing TTS:', error);
    }
}

/**
 * Check if TTS is enabled
 */
export function isTTSEnabled() {
    return ttsEnabled;
}

/**
 * Check if TTS autoplay is enabled
 */
export function isTTSAutoplayEnabled() {
    return ttsAutoplay;
}

/**
 * Play text-to-speech for a message with chunked delivery for faster start
 */
export async function playTTS(messageId, text) {
    // Stop any currently playing audio
    stopTTS();
    
    if (!text || text.trim() === '') {
        showToast('No text to read', 'warning');
        return;
    }
    
    try {
        // Update button to show loading state
        updateTTSButton(messageId, 'loading');
        
        // Strip HTML tags and get plain text
        const tempDiv = document.createElement('div');
        tempDiv.innerHTML = text;
        const plainText = tempDiv.textContent || tempDiv.innerText || '';
        
        // Split text into word-based chunks
        // Group 1: Progressive chunks (10, 15, 20, 25, 30 words)
        // Group 2+: Remaining in 40-word chunks
        const words = plainText.split(/\s+/);
        const chunks = [];
        
        let index = 0;
        
        // Group 1: Progressive chunks
        if (words.length > index) {
            chunks.push(words.slice(index, index + 10).join(' '));
            index += 10;
        }
        if (words.length > index) {
            chunks.push(words.slice(index, index + 15).join(' '));
            index += 15;
        }
        if (words.length > index) {
            chunks.push(words.slice(index, index + 20).join(' '));
            index += 20;
        }
        if (words.length > index) {
            chunks.push(words.slice(index, index + 25).join(' '));
            index += 25;
        }
        if (words.length > index) {
            chunks.push(words.slice(index, index + 30).join(' '));
            index += 30;
        }
        
        // Group 2+: Remaining words in 40-word chunks
        while (index < words.length) {
            chunks.push(words.slice(index, index + 40).join(' '));
            index += 40;
        }
        
        console.log(`[TTS] Split into ${chunks.length} chunks:`, chunks.map(c => `${c.split(/\s+/).length} words`));
        
        // Synthesize chunks 1 and 2 in parallel
        const firstChunk = chunks.shift();
        const secondChunk = chunks.length > 0 ? chunks.shift() : null;
        
        console.log('[TTS] Synthesizing chunks 1 and 2 in parallel...');
        const parallelPromises = [synthesizeChunk(firstChunk, messageId)];
        if (secondChunk) {
            parallelPromises.push(synthesizeChunk(secondChunk, messageId));
        }
        
        const [firstAudio, secondAudio] = await Promise.all(parallelPromises);
        if (!firstAudio) return;
        
        // Track word offsets for each chunk
        let currentWordOffset = 0;
        const firstChunkWordCount = firstChunk.trim().split(/\s+/).length;
        
        // Queue chunk 2 immediately (it's already synthesized)
        if (secondChunk && secondAudio) {
            const secondChunkWordCount = secondChunk.trim().split(/\s+/).length;
            audioQueue.push({
                audio: secondAudio,
                url: secondAudio.src,
                text: secondChunk,
                wordOffset: firstChunkWordCount // Start after first chunk's words
            });
            console.log('[TTS] Chunk 2 pre-queued, ready to play after chunk 1');
        }
        
        // Start playing first chunk
        console.log('[TTS] Playing chunk 1 immediately');
        currentPlayingAudio = firstAudio;
        currentPlayingMessageId = messageId;
        
        // Setup audio event handlers
        currentPlayingAudio.onloadedmetadata = () => {
            // Audio metadata loaded, duration is now available
            const duration = currentPlayingAudio.duration;
            startWordHighlighting(messageId, firstChunk, duration, 0); // Start at word 0
        };
        
        // If metadata is already loaded, start highlighting immediately
        if (currentPlayingAudio.duration && !isNaN(currentPlayingAudio.duration)) {
            const duration = currentPlayingAudio.duration;
            startWordHighlighting(messageId, firstChunk, duration, 0);
        }
        
        currentPlayingAudio.onpause = () => {
            updateTTSButton(messageId, 'paused');
            console.log('[TTS] Audio paused event fired');
            pauseWordHighlighting();
        };
        
        currentPlayingAudio.onplay = () => {
            console.log('[TTS] Audio play event fired, highlightState exists:', !!highlightState, 'interval is null:', wordHighlightInterval === null);
            updateTTSButton(messageId, 'playing');
            highlightPlayingMessage(messageId, true);
            // Resume word highlighting if we were paused (highlightState exists but no active interval)
            if (highlightState && wordHighlightInterval === null) {
                console.log('[TTS] Resuming from pause');
                resumeWordHighlighting();
            }
        };
        
        currentPlayingAudio.onended = () => {
            // Play next chunk from queue if available
            playNextChunk(messageId);
        };
        
        currentPlayingAudio.onerror = (error) => {
            console.error('Audio playback error:', error);
            showToast('Error playing audio', 'danger');
            updateTTSButton(messageId, 'stopped');
            highlightPlayingMessage(messageId, false);
            currentPlayingAudio = null;
            currentPlayingMessageId = null;
            audioQueue = [];
        };
        
        // Start playback of first chunk
        await currentPlayingAudio.play();
        
        // Synthesize remaining chunks in groups while audio is playing
        if (chunks.length > 0) {
            isQueueing = true;
            // Calculate starting word offset for remaining chunks (after chunks 1 and 2)
            const firstChunkWords = firstChunk.trim().split(/\s+/).length;
            const secondChunkWords = secondChunk ? secondChunk.trim().split(/\s+/).length : 0;
            const startingOffset = firstChunkWords + secondChunkWords;
            
            queueChunksInGroups(chunks, messageId, startingOffset).then(() => {
                isQueueing = false;
                console.log(`[TTS] All chunks queued successfully`);
            }).catch(error => {
                console.error('[TTS] Error queueing chunks:', error);
                isQueueing = false;
            });
        } else {
            console.log('[TTS] No remaining chunks - single chunk playback');
        }
        
    } catch (error) {
        console.error('Error playing TTS:', error);
        showToast(`TTS Error: ${error.message}`, 'danger');
        updateTTSButton(messageId, 'stopped');
        currentPlayingAudio = null;
        currentPlayingMessageId = null;
        audioQueue = [];
        isQueueing = false;
    }
}

/**
 * Synthesize a text chunk and return Audio element
 */
async function synthesizeChunk(text, messageId) {
    try {
        const response = await fetch('/api/chat/tts', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                text: text,
                voice: ttsVoice,
                speed: ttsSpeed
            })
        });
        
        if (!response.ok) {
            const errorData = await response.json();
            throw new Error(errorData.error || 'Failed to generate speech');
        }
        
        // Get audio blob
        const audioBlob = await response.blob();
        const audioUrl = URL.createObjectURL(audioBlob);
        
        return new Audio(audioUrl);
        
    } catch (error) {
        console.error('Error synthesizing chunk:', error);
        throw error;
    }
}

/**
 * Queue chunks in groups with parallel synthesis:
 * - Group 1: Chunks 3-7 all in parallel (5 chunks)
 * - Group 2+: Remaining chunks in batches of 5, all parallel within each batch
 */
async function queueChunksInGroups(chunks, messageId, startingWordOffset = 0) {
    console.log(`[TTS] Queueing ${chunks.length} remaining chunks in groups of 5 (parallel within each group)`);
    
    try {
        let groupNum = 1;
        let chunkNumOffset = 3; // Start at chunk 3 since chunks 1 and 2 are already handled
        let currentWordOffset = startingWordOffset;
        
        while (chunks.length > 0) {
            // Take up to 5 chunks for this group
            const groupSize = Math.min(5, chunks.length);
            const groupChunks = chunks.splice(0, groupSize);
            
            console.log(`[TTS] Group ${groupNum}: Synthesizing ${groupSize} chunks in parallel`);
            
            // Synthesize all chunks in this group in parallel
            const synthesisPromises = groupChunks.map((text, index) => {
                const chunkNum = chunkNumOffset + index;
                const wordCount = text.split(/\s+/).length;
                const thisChunkOffset = currentWordOffset;
                
                // Increment offset for next chunk
                currentWordOffset += wordCount;
                
                console.log(`[TTS] Starting synthesis for chunk ${chunkNum} (${wordCount} words, offset: ${thisChunkOffset})`);
                return synthesizeChunk(text, messageId).then(audio => ({
                    chunkNum: chunkNum,
                    audio: audio,
                    url: audio ? audio.src : null,
                    text: text,
                    wordOffset: thisChunkOffset
                }));
            });
            
            // Wait for all chunks in this group to complete
            const results = await Promise.all(synthesisPromises);
            
            // Add to queue in order
            results.forEach(result => {
                if (result.audio) {
                    audioQueue.push({
                        audio: result.audio,
                        url: result.url,
                        text: result.text,
                        wordOffset: result.wordOffset
                    });
                    console.log(`[TTS] Chunk ${result.chunkNum} queued (${result.text.split(/\s+/).length} words, offset: ${result.wordOffset}), queue size: ${audioQueue.length}`);
                }
            });
            
            console.log(`[TTS] Group ${groupNum} complete, ${chunks.length} chunks remaining`);
            chunkNumOffset += groupSize;
            groupNum++;
        }
        
        console.log(`[TTS] All ${groupNum - 1} groups complete, total queue size: ${audioQueue.length}`);
        
    } catch (error) {
        console.error('[TTS] Error in group queueing:', error);
        throw error;
    }
}

/**
 * Queue multiple text chunks for background synthesis (in parallel)
 */
async function queueMultipleChunks(chunks, messageId) {
    console.log(`[TTS] Queueing ${chunks.length} chunks in parallel`);
    
    try {
        // Start all syntheses in parallel
        const synthesisPromises = chunks.map((text, index) => {
            console.log(`[TTS] Starting synthesis for chunk ${index + 1}/${chunks.length}: ${text.split(/\s+/).length} words`);
            return synthesizeChunk(text, messageId).then(audio => ({
                index: index,
                audio: audio,
                url: audio.src,
                text: text
            }));
        });
        
        // Wait for all to complete
        const results = await Promise.all(synthesisPromises);
        
        // Sort by original order (in case they complete out of order)
        results.sort((a, b) => a.index - b.index);
        
        // Add to queue in correct order
        results.forEach((result, i) => {
            audioQueue.push({
                audio: result.audio,
                url: result.url,
                text: result.text
            });
            console.log(`[TTS] Queued chunk ${i + 1}: ${result.text.split(/\s+/).length} words, queue size: ${audioQueue.length}`);
        });
        
        console.log(`[TTS] All ${chunks.length} chunks synthesized and queued in parallel, final queue size: ${audioQueue.length}`);
        
    } catch (error) {
        console.error('[TTS] Error during parallel synthesis:', error);
        // Even if some fail, queue whatever succeeded
    }
}

/**
 * Play next chunk from queue
 */
function playNextChunk(messageId) {
    console.log(`[TTS] playNextChunk called - queue: ${audioQueue.length}, isQueueing: ${isQueueing}`);
    
    if (audioQueue.length === 0) {
        // Check if we're still loading chunks
        if (isQueueing) {
            console.log('[TTS] Queue empty but still loading chunks, waiting...');
            // Wait a bit and try again
            setTimeout(() => playNextChunk(messageId), 100);
            return;
        }
        
        // No more chunks, end playback
        console.log('[TTS] Playback complete');
        updateTTSButton(messageId, 'stopped');
        highlightPlayingMessage(messageId, false);
        currentPlayingAudio = null;
        currentPlayingMessageId = null;
        return;
    }
    
    // Get next chunk
    const nextChunk = audioQueue.shift();
    console.log(`[TTS] Playing next chunk, ${audioQueue.length} remaining in queue`);
    
    // Cleanup previous audio URL
    if (currentPlayingAudio && currentPlayingAudio.src) {
        URL.revokeObjectURL(currentPlayingAudio.src);
    }
    
    currentPlayingAudio = nextChunk.audio;
    
    // Setup handlers for next chunk
    currentPlayingAudio.onloadedmetadata = () => {
        // Start word highlighting for this chunk when metadata is loaded
        const duration = currentPlayingAudio.duration;
        const chunkText = nextChunk.text || '';
        const wordOffset = nextChunk.wordOffset || 0;
        startWordHighlighting(messageId, chunkText, duration, wordOffset);
    };
    
    // If metadata is already loaded, start highlighting immediately
    if (currentPlayingAudio.duration && !isNaN(currentPlayingAudio.duration)) {
        const duration = currentPlayingAudio.duration;
        const chunkText = nextChunk.text || '';
        const wordOffset = nextChunk.wordOffset || 0;
        startWordHighlighting(messageId, chunkText, duration, wordOffset);
    }
    
    currentPlayingAudio.onpause = () => {
        // Audio paused - pause word highlighting
        console.log('[TTS] Chunk audio paused event fired');
        pauseWordHighlighting();
    };
    
    currentPlayingAudio.onplay = () => {
        // Audio playing/resumed - resume word highlighting and restart visualization
        console.log('[TTS] Chunk audio play event fired, highlightState exists:', !!highlightState, 'interval is null:', wordHighlightInterval === null);
        
        // Restart audio visualization for new chunk
        startAudioVisualization(messageId);
        
        if (highlightState && wordHighlightInterval === null) {
            console.log('[TTS] Resuming from pause in chunk');
            resumeWordHighlighting();
        }
    };
    
    currentPlayingAudio.onended = () => {
        URL.revokeObjectURL(nextChunk.url);
        playNextChunk(messageId);
    };
    
    currentPlayingAudio.onerror = (error) => {
        console.error('Error playing queued chunk:', error);
        URL.revokeObjectURL(nextChunk.url);
        playNextChunk(messageId); // Try next chunk
    };
    
    // Play next chunk
    currentPlayingAudio.play().catch(error => {
        console.error('Error starting next chunk:', error);
        playNextChunk(messageId); // Try next chunk
    });
}


/**
 * Stop currently playing TTS
 */
export function stopTTS() {
    if (currentPlayingAudio) {
        currentPlayingAudio.pause();
        currentPlayingAudio = null;
        
        if (currentPlayingMessageId) {
            updateTTSButton(currentPlayingMessageId, 'stopped');
            highlightPlayingMessage(currentPlayingMessageId, false);
            currentPlayingMessageId = null;
        }
    }
    
    // Clear audio queue and revoke URLs
    audioQueue.forEach(chunk => {
        if (chunk.url) {
            URL.revokeObjectURL(chunk.url);
        }
    });
    audioQueue = [];
    isQueueing = false;
}

/**
 * Pause currently playing TTS
 */
export function pauseTTS() {
    if (currentPlayingAudio && !currentPlayingAudio.paused) {
        currentPlayingAudio.pause();
        if (currentPlayingMessageId) {
            updateTTSButton(currentPlayingMessageId, 'paused');
        }
    }
}

/**
 * Resume paused TTS
 */
export function resumeTTS() {
    if (currentPlayingAudio && currentPlayingAudio.paused) {
        currentPlayingAudio.play();
        if (currentPlayingMessageId) {
            updateTTSButton(currentPlayingMessageId, 'playing');
        }
    }
}

/**
 * Update TTS button state
 */
function updateTTSButton(messageId, state) {
    const button = document.querySelector(`[data-message-id="${messageId}"] .tts-play-btn`);
    if (!button) {
        console.log('[TTS] Button not found for message:', messageId);
        return;
    }
    
    const icon = button.querySelector('i');
    if (!icon) {
        console.log('[TTS] Icon not found in button for message:', messageId);
        return;
    }
    
    // Remove all state classes
    icon.classList.remove('bi-volume-up', 'bi-pause-fill', 'bi-stop-fill');
    button.classList.remove('btn-primary', 'btn-success', 'btn-warning');
    button.disabled = false;
    
    switch (state) {
        case 'loading':
            icon.className = 'bi bi-hourglass-split';
            button.disabled = true;
            button.title = 'One moment, I’m taking a look';
            break;
            
        case 'playing':
            icon.className = 'bi bi-pause-fill';
            button.classList.add('btn-success');
            button.title = 'Hold on, pause what you are reading';
            break;
            
        case 'paused':
            icon.className = 'bi bi-volume-up';
            button.classList.add('btn-warning');
            button.title = 'Go ahead, continue reading';
            break;
            
        case 'stopped':
        default:
            icon.className = 'bi bi-volume-up';
            button.title = 'Read this to me';
            break;
    }
}

/**
 * Highlight message being read
 */
/**
 * Prepare message text for word-by-word highlighting
 */
function prepareMessageForHighlighting(messageId) {
    const messageElement = document.querySelector(`[data-message-id="${messageId}"]`);
    if (!messageElement) return;
    
    const messageTextDiv = messageElement.querySelector('.message-text');
    if (!messageTextDiv || messageTextDiv.dataset.ttsWrapped === 'true') return;
    
    // Function to wrap words in text nodes only, not HTML
    function wrapWordsInTextNodes(node) {
        if (node.nodeType === Node.TEXT_NODE) {
            // This is a text node - wrap its words
            const text = node.textContent;
            if (text.trim().length === 0) return; // Skip whitespace-only nodes
            
            const words = text.split(/(\s+)/); // Split but keep whitespace
            const fragment = document.createDocumentFragment();
            
            words.forEach(word => {
                if (/\S/.test(word)) {
                    // Non-whitespace word - wrap it
                    const span = document.createElement('span');
                    span.className = 'tts-word';
                    span.textContent = word;
                    fragment.appendChild(span);
                } else {
                    // Whitespace - keep as text
                    fragment.appendChild(document.createTextNode(word));
                }
            });
            
            node.parentNode.replaceChild(fragment, node);
        } else if (node.nodeType === Node.ELEMENT_NODE) {
            // This is an element - recurse into its children
            // Convert to array to avoid live NodeList issues
            Array.from(node.childNodes).forEach(child => wrapWordsInTextNodes(child));
        }
    }
    
    wrapWordsInTextNodes(messageTextDiv);
    messageTextDiv.dataset.ttsWrapped = 'true';
}

/**
 * Start highlighting words progressively during playback
 */
function startWordHighlighting(messageId, chunkText, duration, startWordIndex = 0) {
    // Clear any existing highlighting
    stopWordHighlighting();
    
    // Validate duration
    if (!duration || duration === 0 || isNaN(duration)) {
        console.log('[TTS] Invalid duration for word highlighting, skipping');
        return;
    }
    
    // Prepare message for highlighting if not already done
    prepareMessageForHighlighting(messageId);
    
    const messageElement = document.querySelector(`[data-message-id="${messageId}"]`);
    if (!messageElement) return;
    
    const allWordElements = messageElement.querySelectorAll('.tts-word');
    if (allWordElements.length === 0) return;
    
    // Count words in this chunk
    const chunkWords = chunkText.trim().split(/\s+/).length;
    
    // Calculate which words to highlight for this chunk
    wordOffset = startWordIndex;
    totalWords = Math.min(chunkWords, allWordElements.length - wordOffset);
    currentWordIndex = 0;
    
    if (totalWords <= 0) {
        console.log('[TTS] No words to highlight for this chunk');
        return;
    }
    
    // Calculate time per word (in milliseconds)
    const msPerWord = (duration * 1000) / totalWords;
    
    // Store state for pause/resume
    highlightState = {
        messageId: messageId,
        chunkText: chunkText,
        duration: duration,
        startWordIndex: startWordIndex,
        msPerWord: msPerWord,
        allWordElements: allWordElements
    };
    
    console.log(`[TTS] Word highlighting: chunk has ${chunkWords} words, highlighting words ${wordOffset} to ${wordOffset + totalWords - 1}, ${duration.toFixed(2)}s duration, ${msPerWord.toFixed(0)}ms per word`);
    
    // Highlight first word immediately
    const firstWordIndex = wordOffset;
    if (firstWordIndex < allWordElements.length) {
        allWordElements[firstWordIndex].classList.add('tts-current-word');
    }
    
    // Set interval to highlight next words
    wordHighlightInterval = setInterval(() => {
        // Check if audio is paused - if so, stop highlighting
        if (currentPlayingAudio && currentPlayingAudio.paused) {
            console.log('[TTS] Audio paused, stopping word highlight interval');
            pauseWordHighlighting();
            return;
        }
        
        // Remove highlight from previous word
        const prevIndex = wordOffset + currentWordIndex;
        if (prevIndex < allWordElements.length) {
            allWordElements[prevIndex].classList.remove('tts-current-word');
        }
        
        currentWordIndex++;
        
        // Add highlight to current word
        const nextIndex = wordOffset + currentWordIndex;
        if (currentWordIndex < totalWords && nextIndex < allWordElements.length) {
            allWordElements[nextIndex].classList.add('tts-current-word');
        } else {
            // Reached the end of this chunk, clear interval
            stopWordHighlighting();
        }
    }, msPerWord);
}

/**
 * Pause word highlighting (keep state for resume)
 */
function pauseWordHighlighting() {
    console.log('[TTS] Pausing word highlighting, currentWordIndex:', currentWordIndex);
    if (wordHighlightInterval) {
        clearInterval(wordHighlightInterval);
        wordHighlightInterval = null;
    }
    // Keep currentWordIndex, totalWords, wordOffset, and highlightState for resume
}

/**
 * Resume word highlighting from current audio position
 */
function resumeWordHighlighting() {
    if (!highlightState || !currentPlayingAudio) return;
    
    const { messageId, msPerWord, allWordElements } = highlightState;
    
    // Calculate current word position based on audio time
    const elapsedTime = currentPlayingAudio.currentTime * 1000; // Convert to ms
    const calculatedWordIndex = Math.floor(elapsedTime / msPerWord);
    
    // Update currentWordIndex to match audio position
    currentWordIndex = Math.min(calculatedWordIndex, totalWords - 1);
    
    console.log(`[TTS] Resuming word highlighting from word ${currentWordIndex} (audio time: ${currentPlayingAudio.currentTime.toFixed(2)}s)`);
    
    // Highlight current word
    const currentIndex = wordOffset + currentWordIndex;
    if (currentIndex < allWordElements.length) {
        allWordElements[currentIndex].classList.add('tts-current-word');
    }
    
    // Continue highlighting from this point
    wordHighlightInterval = setInterval(() => {
        // Check if audio is paused - if so, stop highlighting
        if (currentPlayingAudio && currentPlayingAudio.paused) {
            console.log('[TTS] Audio paused during resume, stopping word highlight interval');
            pauseWordHighlighting();
            return;
        }
        
        // Remove highlight from previous word
        const prevIndex = wordOffset + currentWordIndex;
        if (prevIndex < allWordElements.length) {
            allWordElements[prevIndex].classList.remove('tts-current-word');
        }
        
        currentWordIndex++;
        
        // Add highlight to current word
        const nextIndex = wordOffset + currentWordIndex;
        if (currentWordIndex < totalWords && nextIndex < allWordElements.length) {
            allWordElements[nextIndex].classList.add('tts-current-word');
        } else {
            // Reached the end of this chunk, clear interval
            stopWordHighlighting();
        }
    }, msPerWord);
}

/**
 * Stop word highlighting
 */
function stopWordHighlighting() {
    if (wordHighlightInterval) {
        clearInterval(wordHighlightInterval);
        wordHighlightInterval = null;
    }
    
    // Remove all word highlights
    if (currentPlayingMessageId) {
        const messageElement = document.querySelector(`[data-message-id="${currentPlayingMessageId}"]`);
        if (messageElement) {
            const wordElements = messageElement.querySelectorAll('.tts-word');
            wordElements.forEach(word => word.classList.remove('tts-current-word'));
        }
    }
    
    currentWordIndex = 0;
    totalWords = 0;
    highlightState = null;
}

/**
 * Start audio visualization for avatar pulsing based on volume
 */
function startAudioVisualization(messageId) {
    if (!currentPlayingAudio) return;
    
    try {
        // Create AudioContext if not exists
        if (!audioContext) {
            audioContext = new (window.AudioContext || window.webkitAudioContext)();
        }
        
        // Create analyzer if not exists
        if (!analyser) {
            analyser = audioContext.createAnalyser();
            analyser.fftSize = 256;
        }
        
        // Only create a new source if we don't have one or audio element changed
        if (!currentAudioSource || currentAudioSource.mediaElement !== currentPlayingAudio) {
            // Disconnect old source if exists
            if (currentAudioSource) {
                try {
                    currentAudioSource.disconnect();
                } catch (e) {
                    // Ignore disconnect errors
                }
            }
            
            // Create new source and connect
            currentAudioSource = audioContext.createMediaElementSource(currentPlayingAudio);
            currentAudioSource.connect(analyser);
            analyser.connect(audioContext.destination);
        }
        
        const dataArray = new Uint8Array(analyser.frequencyBinCount);
        const avatar = document.querySelector(`[data-message-id="${messageId}"] .avatar`);
        
        if (!avatar) return;
        
        // Clear any existing interval
        if (volumeCheckInterval) {
            clearInterval(volumeCheckInterval);
        }
        
        // Update avatar glow based on volume
        volumeCheckInterval = setInterval(() => {
            if (!currentPlayingAudio || currentPlayingAudio.paused || currentPlayingAudio.ended) {
                return; // Don't stop completely, just pause updates
            }
            
            analyser.getByteFrequencyData(dataArray);
            
            // Calculate average volume
            const sum = dataArray.reduce((a, b) => a + b, 0);
            const average = sum / dataArray.length;
            
            // Remove all volume classes
            avatar.classList.remove('volume-low', 'volume-medium', 'volume-high', 'volume-peak');
            
            // Add appropriate class based on volume level
            if (average < 30) {
                avatar.classList.add('volume-low');
            } else if (average < 60) {
                avatar.classList.add('volume-medium');
            } else if (average < 90) {
                avatar.classList.add('volume-high');
            } else {
                avatar.classList.add('volume-peak');
            }
        }, 50); // Update every 50ms for smooth visualization
        
    } catch (error) {
        console.error('[TTS] Error setting up audio visualization:', error);
    }
}

/**
 * Stop audio visualization
 */
function stopAudioVisualization(messageId) {
    if (volumeCheckInterval) {
        clearInterval(volumeCheckInterval);
        volumeCheckInterval = null;
    }
    
    // Remove volume classes from avatar
    if (messageId) {
        const avatar = document.querySelector(`[data-message-id="${messageId}"] .avatar`);
        if (avatar) {
            avatar.classList.remove('volume-low', 'volume-medium', 'volume-high', 'volume-peak');
        }
    }
}

function highlightPlayingMessage(messageId, highlight) {
    const messageElement = document.querySelector(`[data-message-id="${messageId}"]`);
    if (!messageElement) return;
    
    if (highlight) {
        messageElement.classList.add('tts-playing');
        startAudioVisualization(messageId);
    } else {
        messageElement.classList.remove('tts-playing');
        stopAudioVisualization(messageId);
        stopWordHighlighting();
    }
}

/**
 * Handle TTS button click
 */
export function handleTTSButtonClick(messageId, text) {
    // If text is not provided, extract it from the DOM
    if (!text || text.trim() === '') {
        const messageElement = document.querySelector(`[data-message-id="${messageId}"]`);
        if (messageElement) {
            const messageTextDiv = messageElement.querySelector('.message-text');
            if (messageTextDiv) {
                text = messageTextDiv.innerText || messageTextDiv.textContent;
            }
        }
        
        // If still no text, show error
        if (!text || text.trim() === '') {
            showToast('No text to read', 'warning');
            return;
        }
    }
    
    // If this message is currently playing, pause it
    if (currentPlayingMessageId === messageId && currentPlayingAudio) {
        if (currentPlayingAudio.paused) {
            resumeTTS();
        } else {
            pauseTTS();
        }
    } else {
        // Play this message
        playTTS(messageId, text);
    }
}

/**
 * Create TTS button HTML
 */
export function createTTSButton(messageId) {
    return `
        <button class="btn btn-sm btn-link text-muted tts-play-btn" 
                title="Listen"
                onclick="window.chatTTS.handleButtonClick('${messageId}')">
            <i class="bi bi-volume-up"></i>
        </button>
    `;
}

/**
 * Auto-play TTS for new AI messages if enabled
 */
export function autoplayTTSIfEnabled(messageId, text) {
    console.log('[TTS Autoplay] Check:', { ttsEnabled, ttsAutoplay, messageId, hasText: !!text });
    if (ttsEnabled && ttsAutoplay) {
        console.log('[TTS Autoplay] Playing message:', messageId);
        
        // Wait for button to be rendered before playing
        const waitForButton = (attempts = 0) => {
            const button = document.querySelector(`[data-message-id="${messageId}"] .tts-play-btn`);
            
            if (button) {
                console.log('[TTS Autoplay] Button found, starting playback');
                playTTS(messageId, text);
            } else if (attempts < 10) {
                // Retry up to 10 times (1 second total)
                console.log(`[TTS Autoplay] Button not found, retry ${attempts + 1}/10`);
                setTimeout(() => waitForButton(attempts + 1), 100);
            } else {
                console.warn('[TTS Autoplay] Button not found after 10 attempts, skipping autoplay');
            }
        };
        
        // Start checking for button after small delay
        setTimeout(() => waitForButton(), 100);
    }
}

/**
 * Toggle TTS autoplay on/off
 */
export async function toggleTTSAutoplay() {
    ttsAutoplay = !ttsAutoplay;
    
    console.log('[TTS Autoplay] Toggled to:', ttsAutoplay);
    
    // Save to user settings
    try {
        const response = await fetch('/api/user/settings', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                settings: {
                    ttsAutoplay: ttsAutoplay
                }
            })
        });
        
        if (!response.ok) {
            throw new Error('Failed to save autoplay setting');
        }
        
        // Update button UI
        updateAutoplayButton();
        
        // Show toast notification
        const message = ttsAutoplay ? 'AI Voice enabled' : 'AI Voice disabled';
        showToast(message, 'success');
        
    } catch (error) {
        console.error('Error saving AI Voice setting:', error);
        showToast('Failed to save AI Voice setting', 'danger');
        // Revert the toggle
        ttsAutoplay = !ttsAutoplay;
    }
}

/**
 * Update the autoplay button UI based on current state
 */
export function updateAutoplayButton() {
    const button = document.getElementById('tts-autoplay-toggle-btn');
    if (!button) return;
    
    const icon = button.querySelector('i');
    if (ttsAutoplay) {
        icon.className = 'bi bi-volume-up-fill';
        button.title = 'Auto voice response enabled - click to disable';
        button.classList.remove('btn-outline-secondary');
        button.classList.add('btn-primary');
    } else {
        icon.className = 'bi bi-volume-mute';
        button.title = 'Auto voice response disabled - click to enable';
        button.classList.remove('btn-primary');
        button.classList.add('btn-outline-secondary');
    }
}

/**
 * Initialize the autoplay button state and event listener
 */
export function initializeAutoplayButton() {
    const button = document.getElementById('tts-autoplay-toggle-btn');
    if (!button) return;
    
    button.addEventListener('click', toggleTTSAutoplay);
    updateAutoplayButton();
}

// Export functions for global access
window.chatTTS = {
    handleButtonClick: handleTTSButtonClick,
    stop: stopTTS,
    pause: pauseTTS,
    resume: resumeTTS,
    toggleAutoplay: toggleTTSAutoplay
};

// Initialize autoplay button when module loads
initializeAutoplayButton();

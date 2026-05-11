# Text-to-Speech Chunking and Parallel Synthesis Strategy

## Overview
This document describes the intelligent chunking and parallel synthesis strategy used in the TTS feature to minimize audio playback latency and ensure seamless transitions between chunks.

**Version Implemented:** 0.234.204

## Goals
1. **Fast Initial Playback**: Audio should start playing within 1-2 seconds
2. **Seamless Transitions**: No pauses or gaps between chunks during playback
3. **Efficient Synthesis**: Use parallel API calls to minimize total synthesis time
4. **Scalability**: Handle messages of any length from short phrases to long responses

## Chunking Strategy

### Progressive Word-Based Chunks
Text is split into progressively larger chunks to balance fast initial playback with efficient synthesis:

```
Chunk 1: 10 words   (plays immediately, fast synthesis)
Chunk 2: 15 words   (synthesized with chunk 1, queued for seamless transition)
Chunk 3: 20 words   (synthesized in Group 1)
Chunk 4: 25 words   (synthesized in Group 1)
Chunk 5: 30 words   (synthesized in Group 1)
Chunk 6+: 40 words each (synthesized in subsequent groups)
```

### Why Progressive Sizing?
- **Small initial chunks** (10, 15 words) ensure fast synthesis and quick audio start
- **Growing chunk sizes** (20, 25, 30 words) provide smooth transitions while reducing total API calls
- **Large final chunks** (40 words) efficiently handle remaining content without excessive API requests

## Parallel Synthesis Strategy

### Phase 1: Initial Parallel Synthesis (Chunks 1 & 2)
```javascript
// Synthesize chunks 1 and 2 simultaneously
const [chunk1Audio, chunk2Audio] = await Promise.all([
    synthesizeChunk(chunk1Text),
    synthesizeChunk(chunk2Text)
]);

// Start playing chunk 1 immediately
playAudio(chunk1Audio);

// Queue chunk 2 (already synthesized, ready to play)
audioQueue.push(chunk2Audio);
```

**Timeline:**
- `t=0s`: Start synthesis of chunks 1 & 2 in parallel
- `t=2s`: Both chunks complete synthesis
- `t=2s`: Chunk 1 starts playing
- `t=5s`: Chunk 1 finishes, chunk 2 plays immediately (no pause!)

### Phase 2: Group-Based Parallel Synthesis (Chunks 3+)
While chunks 1 and 2 are playing, remaining chunks are synthesized in groups of 5:

**Group 1 (Chunks 3-7):**
```javascript
// While chunks 1 & 2 play, synthesize chunks 3-7 in parallel
await Promise.all([
    synthesizeChunk(chunk3),  // 20 words
    synthesizeChunk(chunk4),  // 25 words
    synthesizeChunk(chunk5),  // 30 words
    synthesizeChunk(chunk6),  // 40 words
    synthesizeChunk(chunk7)   // 40 words
]);
```

**Group 2 (Chunks 8-12):**
- After Group 1 completes, synthesize next 5 chunks in parallel
- Process continues until all chunks are synthesized

**Group N:**
- Final group may have fewer than 5 chunks
- All remaining chunks synthesized in parallel

## Playback Flow

### Example: 100-word message

```
Word Distribution:
├─ Chunk 1: Words 1-10     (10 words)
├─ Chunk 2: Words 11-25    (15 words)
├─ Chunk 3: Words 26-45    (20 words)
├─ Chunk 4: Words 46-70    (25 words)
└─ Chunk 5: Words 71-100   (30 words)

Synthesis Timeline:
t=0s:   Start synthesizing chunks 1 & 2 in parallel
t=2s:   Chunks 1 & 2 complete, chunk 1 starts playing
        Start synthesizing chunks 3-5 in parallel
t=3s:   Chunk 1 finishes, chunk 2 plays immediately
t=4s:   Chunks 3-5 complete synthesis
t=5s:   Chunk 2 finishes, chunk 3 plays immediately
t=7s:   Chunk 3 finishes, chunk 4 plays immediately
t=10s:  Chunk 4 finishes, chunk 5 plays immediately
t=13s:  Chunk 5 finishes, playback complete

Result: No pauses between chunks, seamless playback!
```

## Implementation Details

### Code Location
- **File:** `static/js/chat/chat-tts.js`
- **Function:** `playTTS()` - Main orchestration
- **Function:** `queueChunksInGroups()` - Group-based parallel synthesis

### Key Components

#### 1. Text Chunking
```javascript
const words = plainText.split(/\s+/);
const chunks = [];
let index = 0;

// Progressive chunks: 10, 15, 20, 25, 30 words
if (words.length > index) {
    chunks.push(words.slice(index, index + 10).join(' '));
    index += 10;
}
if (words.length > index) {
    chunks.push(words.slice(index, index + 15).join(' '));
    index += 15;
}
// ... continues for 20, 25, 30

// Remaining in 40-word chunks
while (index < words.length) {
    chunks.push(words.slice(index, index + 40).join(' '));
    index += 40;
}
```

#### 2. Initial Parallel Synthesis
```javascript
const firstChunk = chunks.shift();
const secondChunk = chunks.shift();

const [firstAudio, secondAudio] = await Promise.all([
    synthesizeChunk(firstChunk, messageId),
    synthesizeChunk(secondChunk, messageId)
]);

// Play first, queue second
currentPlayingAudio = firstAudio;
audioQueue.push({ audio: secondAudio, url: secondAudio.src });
await currentPlayingAudio.play();
```

#### 3. Group-Based Queue Processing
```javascript
while (chunks.length > 0) {
    const groupSize = Math.min(5, chunks.length);
    const groupChunks = chunks.splice(0, groupSize);
    
    // Synthesize all in parallel
    const results = await Promise.all(
        groupChunks.map(text => synthesizeChunk(text, messageId))
    );
    
    // Add to queue in order
    results.forEach(audio => audioQueue.push(audio));
}
```

#### 4. Continuous Playback
```javascript
currentPlayingAudio.onended = () => {
    playNextChunk(messageId);  // Automatically plays next queued chunk
};
```

## Performance Metrics

### Typical Performance (Azure Speech Service)
- **Single chunk synthesis:** ~2 seconds
- **5 chunks in parallel:** ~2-3 seconds (not 10 seconds!)
- **Audio start latency:** 2 seconds (time to synthesize chunk 1)
- **Chunk transition delay:** 0ms (next chunk already synthesized and queued)

### Comparison: Sequential vs Parallel

**Sequential Synthesis (Old Approach):**
```
Chunk 1: 2s synthesis → play
Chunk 2: 2s synthesis → play (user experiences pause)
Chunk 3: 2s synthesis → play (user experiences pause)
Total: 6s before all chunks synthesized
```

**Parallel Synthesis (Current Approach):**
```
Chunks 1 & 2: 2s synthesis in parallel
Chunks 3-7:   2s synthesis in parallel (while 1 & 2 play)
Total: 4s before all chunks synthesized
No pauses during playback
```

## Edge Cases Handled

### 1. Very Short Messages (<10 words)
- Single chunk created
- No grouping needed
- Plays immediately after synthesis

### 2. Messages with Odd Word Counts
- Final chunk may be smaller than 40 words
- Last group may have fewer than 5 chunks
- All handled gracefully with `Math.min()` and conditionals

### 3. Synthesis Failures
- Each chunk synthesis wrapped in try-catch
- Failed chunks logged but don't block other chunks
- Playback continues with available chunks

### 4. Race Conditions
- `isQueueing` flag prevents overlapping queue operations
- Queue checked with retry logic (100ms intervals, up to 10 retries)
- Ensures chunk 2 is available when chunk 1 ends

## Debugging and Monitoring

### Console Logging
The implementation includes comprehensive debug logging:

```javascript
[TTS] Split into 5 chunks: [10, 15, 20, 25, 30] words
[TTS] Synthesizing chunks 1 and 2 in parallel...
[TTS] Chunk 2 pre-queued, ready to play after chunk 1
[TTS] Playing chunk 1 immediately
[TTS] Group 1: Synthesizing 3 chunks in parallel
[TTS] Starting synthesis for chunk 3 (20 words)
[TTS] Starting synthesis for chunk 4 (25 words)
[TTS] Starting synthesis for chunk 5 (30 words)
[TTS] Chunk 3 queued (20 words), queue size: 1
[TTS] Group 1 complete, 0 chunks remaining
[TTS] All 1 groups complete, total queue size: 3
```

### Backend Logging
Backend route includes `debug_print` statements:
- Request received with text length
- Azure Speech SDK configuration
- Synthesis completion time
- Audio data size
- Error conditions

## Future Optimizations

### Potential Improvements
1. **Dynamic chunk sizing** based on average synthesis time
2. **Adaptive grouping** based on network latency
3. **Pre-synthesis caching** for common phrases
4. **Streaming synthesis** if Azure Speech SDK supports it
5. **Predictive synthesis** for anticipated follow-up messages

### Monitoring Considerations
- Track synthesis time per chunk size
- Monitor pause duration between chunks
- Log user interruptions/stops
- Measure total playback completion rate

## Related Files
- **Frontend:** `static/js/chat/chat-tts.js`
- **Backend:** `route_backend_tts.py`
- **Feature Documentation:** `TEXT_TO_SPEECH.md`
- **Configuration:** `config.py` (VERSION)

## Version History
- **0.234.199**: Initial parallel synthesis (all chunks at once)
- **0.234.200**: First attempt at dual-chunk synthesis (chunks 1+2)
- **0.234.201**: Staged synthesis (1, then 2, then 3+4, etc.)
- **0.234.202**: Unlimited staging with pairs
- **0.234.203**: Progressive chunking with group-based synthesis
- **0.234.204**: Final optimization - chunks 1+2 parallel, then groups of 5

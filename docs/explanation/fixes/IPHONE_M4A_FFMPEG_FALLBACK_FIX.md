# iPhone M4A FFmpeg Fallback Fix - Version 0.250.010

Fixed/Implemented in version: **0.250.010**

## Issue Description

Uploading an audio file recorded on an iPhone could fail in the Personal Workspace even though `.m4a` is listed as a supported audio extension and the same file works when uploaded directly to Azure Speech Service.

Observed error:

```text
Error: Processing failed: Segmentation failed: [Errno 2] No such file or directory: 'ffmpeg'
```

Related issue: microsoft/simplechat#974

## Root Cause Analysis

Audio document processing always attempted to split the uploaded file into PCM WAV chunks with `ffmpeg` before sending audio to Azure Speech. If the app host did not have a resolvable `ffmpeg` executable, supported source audio such as iPhone `.m4a` failed before Azure Speech could process it.

## Technical Details

Files modified:

- `application/single_app/functions_documents.py`
- `application/single_app/config.py`
- `application/single_app/Dockerfile`
- `application/single_app/route_frontend_admin_settings.py`
- `application/single_app/templates/admin_settings.html`
- `deployers/azure.yaml`
- `deployers/version.txt`
- `functional_tests/test_audio_ffmpeg_fallback.py`
- `ui_tests/test_admin_multimedia_guidance.py`

Code changes summary:

- Added a missing-`ffmpeg` detector for segmentation failures.
- Added a shared Azure Speech fast-transcription helper that preserves the caller-provided audio filename and MIME type.
- Updated public-cloud audio processing to fall back to sending the original source audio to Azure Speech fast transcription when local `ffmpeg` is unavailable.
- Expanded recognized audio upload extensions to include common containers and codecs such as 3GA, AIFF, AMR, AU, CAF, M4B, M4R, Matroska audio, Opus, Speex, WebM audio, WMA, and WavPack.
- Updated FFmpeg segmentation to target the first audio stream and emit mono 16 kHz PCM WAV chunks for Speech.
- Added FFmpeg/FFprobe runtime packaging to the distroless container build with a default-on `INSTALL_AUDIO_FFMPEG` build argument, wired through `SIMPLECHAT_INSTALL_FFMPEG` in the deployer.
- Added Admin Settings runtime status showing whether FFmpeg broad audio transcoding is available and which audio upload extensions are recognized.
- Preserved the existing chunked WAV path for environments where `ffmpeg` is available and for sovereign/custom clouds where fast transcription is not used.
- Updated `config.py` version to `0.250.010` and deployer version to `1.0.21` for traceability.

## Testing Approach

Functional coverage was added in `functional_tests/test_audio_ffmpeg_fallback.py` to validate:

- The missing-`ffmpeg` error signature from failed segmentation is detected.
- Public-cloud audio processing can route missing-`ffmpeg` failures to Azure Speech fast transcription.
- Common audio extensions and content types are registered consistently.
- Container and deployer build paths install FFmpeg by default and expose the opt-out flag.
- Admin Settings receives and renders audio runtime status details.
- The fast-transcription helper preserves source audio content types instead of forcing WAV.
- `config.py` was bumped to version `0.250.010`.

UI coverage in `ui_tests/test_admin_multimedia_guidance.py` validates that admins can see the FFmpeg runtime status and expanded audio extension list.

## Impact Analysis

Users can upload supported iPhone `.m4a` recordings in public Azure environments without requiring local media segmentation to succeed first. Container deployments can include FFmpeg to support a much broader set of audio codecs and containers before Azure Speech transcription, while native Python hosts without FFmpeg receive explicit admin guidance about the reduced fallback behavior.

## Validation

Before the fix, the upload failed during local segmentation with a missing `ffmpeg` executable error. After the fix, public-cloud deployments can bypass local segmentation for that failure mode and send the supported source audio directly to Azure Speech fast transcription.
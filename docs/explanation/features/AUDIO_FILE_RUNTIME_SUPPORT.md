# Audio File Runtime Support

Version implemented: **0.250.010**

Fixed/Implemented in version: **0.250.010**

## Overview

SimpleChat audio upload processing now distinguishes extension allow-list support, container runtime transcoding support, and Azure Speech source-file fallback behavior. Container deployments can package FFmpeg and FFprobe so common audio containers and codecs can be converted to Speech-compatible WAV chunks before transcription.

Related issue: microsoft/simplechat#974

## Dependencies

- `application/single_app/config.py` version `0.250.010`
- Azure Speech Service configured in Admin Settings
- Optional container runtime FFmpeg package installed by `application/single_app/Dockerfile`
- Deployer version `1.0.21` for `SIMPLECHAT_INSTALL_FFMPEG` build-arg wiring

## Technical Specifications

- Recognized audio upload extensions include 3GA, AAC, AC3, AIFF, AMR, APE, AU, CAF, DTS, F4A, FLAC, M4A, M4B, M4R, Matroska audio, MP2/MP3/MPA, OGA/OGG, Opus, Speex, WAV, WebM audio, WMA, and WavPack.
- When FFmpeg is available, audio processing maps the first audio stream and creates mono 16 kHz PCM WAV segments for Azure Speech transcription.
- When FFmpeg is missing in public Azure environments, processing can fall back to Azure Speech fast transcription with the original source file and MIME type.
- Sovereign and custom cloud environments continue to use the Speech SDK path and therefore still require local WAV preparation through FFmpeg for broad format support.
- Admin Settings receives `audio_runtime_capabilities` and displays whether broad FFmpeg transcoding is available in the current runtime.

## Configuration Options

- `INSTALL_AUDIO_FFMPEG=true` is the Docker build argument default.
- `SIMPLECHAT_INSTALL_FFMPEG=true` is the deployer environment flag that controls the Docker build argument during ACR builds.
- Set either value to `false`, `0`, `no`, or `off` only when the deployment intentionally excludes FFmpeg from the app container.

## Usage Instructions

1. Build and deploy the standard SimpleChat container image with the default FFmpeg setting.
2. Open **Admin Settings** > **Search & Extract** > **AI Voice Conversations**.
3. Check the audio runtime status under **Enable Audio File Upload & Processing**.
4. Enable audio uploads after Azure Speech Service settings are configured.

## Testing and Validation

- `functional_tests/test_audio_ffmpeg_fallback.py` validates extension registration, FFmpeg runtime capability reporting, Docker/deployer build flag wiring, and source-file fallback behavior.
- `ui_tests/test_admin_multimedia_guidance.py` validates the Admin Settings runtime status and expanded audio extension list when an authenticated admin UI test environment is available.
- Docker build validation should confirm the Azure Linux builder can install `ffmpeg` and that final distroless images can resolve `ffmpeg` on `PATH`.

## Known Limitations

- FFmpeg availability depends on the container build path or native host package installation.
- The runtime probe verifies FFmpeg execution, not every possible codec.
- Azure Speech can still reject files with unsupported codecs, corruption, extreme size, or no recognizable speech.
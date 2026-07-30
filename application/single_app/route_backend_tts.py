# route_backend_tts.py

from config import *
from functions_authentication import *
from functions_appinsights import log_event
from functions_documents import get_speech_synthesis_config
from functions_settings import *
from functions_debug import debug_print
from swagger_wrapper import swagger_route, get_auth_security
import azure.cognitiveservices.speech as speechsdk
import html
import io
import math
import random
import threading
import time

TTS_VOICE_CACHE_TTL_SECONDS = 15 * 60
TTS_DEFAULT_VOICE = "en-US-Andrew:DragonHDLatestNeural"
TTS_PREFERRED_DEFAULT_VOICES = (
    TTS_DEFAULT_VOICE,
    "en-US-AndrewMultilingualNeural",
    "en-US-AvaMultilingualNeural",
    "en-US-JennyNeural",
    "en-US-GuyNeural",
)
TTS_BACKUP_VOICES = [
    {
        "name": "en-US-AndrewMultilingualNeural",
        "gender": "Male",
        "language": "English (US)",
        "locale": "en-US",
        "status": "Fallback",
        "note": "Default fallback voice",
    },
    {
        "name": "en-US-AvaMultilingualNeural",
        "gender": "Female",
        "language": "English (US)",
        "locale": "en-US",
        "status": "Fallback",
    },
    {
        "name": "en-US-JennyNeural",
        "gender": "Female",
        "language": "English (US)",
        "locale": "en-US",
        "status": "Fallback",
    },
    {
        "name": "en-US-GuyNeural",
        "gender": "Male",
        "language": "English (US)",
        "locale": "en-US",
        "status": "Fallback",
    },
]
TTS_LOCALE_LABELS = {
    "de-DE": "German",
    "en-US": "English (US)",
    "es-ES": "Spanish (Spain)",
    "fr-FR": "French",
    "ja-JP": "Japanese",
    "zh-CN": "Chinese (Simplified)",
}
TTS_VOICE_CACHE = {}
TTS_VOICE_CACHE_LOCK = threading.Lock()
TTS_CONFIG_ERROR_MESSAGE = "Text-to-speech is not configured correctly."
TTS_SYNTHESIS_ERROR_MESSAGE = "Text-to-speech synthesis failed. Check Application Insights for [TTS] details."


def _get_speech_service_settings(settings):
    """Return normalized Speech service configuration and a client-safe error if invalid."""
    speech_endpoint = (settings.get('speech_service_endpoint') or '').strip().rstrip('/')
    speech_region = (settings.get('speech_service_location') or '').strip()
    speech_auth_type = settings.get('speech_service_authentication_type', 'key')

    if not speech_endpoint:
        return speech_endpoint, speech_region, speech_auth_type, "Speech service not configured"

    if speech_auth_type == 'key' and not (settings.get('speech_service_key') or '').strip():
        return speech_endpoint, speech_region, speech_auth_type, "Speech service not configured"

    if speech_auth_type == 'managed_identity' and not speech_region:
        return speech_endpoint, speech_region, speech_auth_type, "Speech service not configured"

    return speech_endpoint, speech_region, speech_auth_type, None


def _get_tts_voice_cache_key(settings, speech_endpoint, speech_region):
    """Build a non-secret cache key for the configured Speech resource."""
    speech_auth_type = settings.get('speech_service_authentication_type', 'key')
    resource_id = (settings.get('speech_service_resource_id') or '').strip()
    return f"{speech_auth_type}|{speech_endpoint}|{speech_region}|{resource_id}"


def _language_label_for_locale(locale):
    """Return a readable language label for voice dropdown grouping."""
    return TTS_LOCALE_LABELS.get(locale, locale or "Other")


def _stringify_voice_gender(gender):
    """Normalize Azure Speech SDK gender enum values for JSON responses."""
    gender_name = getattr(gender, "name", None)
    if not gender_name:
        gender_name = str(gender or "Unknown").split(".")[-1]
    return gender_name if gender_name and gender_name != "None" else "Unknown"


def _format_tts_voice_info(voice_info):
    """Convert an Azure Speech SDK VoiceInfo object into the app's voice schema."""
    voice_name = getattr(voice_info, "short_name", "") or getattr(voice_info, "name", "")
    locale = getattr(voice_info, "locale", "") or ""
    local_name = getattr(voice_info, "local_name", "") or voice_name
    style_list = list(getattr(voice_info, "style_list", []) or [])
    voice_type = getattr(voice_info, "voice_type", "")

    return {
        "name": voice_name,
        "display_name": local_name,
        "gender": _stringify_voice_gender(getattr(voice_info, "gender", "Unknown")),
        "language": _language_label_for_locale(locale),
        "locale": locale,
        "status": "Available",
        "voice_type": str(voice_type).split(".")[-1] if voice_type else "",
        "style_list": style_list,
    }


def _tts_voice_sort_key(voice):
    """Keep preferred/default and English voices near the top of the picker."""
    voice_name = voice.get("name", "")
    try:
        preferred_index = TTS_PREFERRED_DEFAULT_VOICES.index(voice_name)
    except ValueError:
        preferred_index = len(TTS_PREFERRED_DEFAULT_VOICES)

    locale = voice.get("locale", "")
    english_priority = 0 if locale == "en-US" or voice_name.startswith("en-US-") else 1
    return (preferred_index, english_priority, voice.get("language", ""), voice_name)


def _get_backup_tts_voices():
    """Return a conservative fallback list of broadly available Neural voices."""
    return [dict(voice) for voice in TTS_BACKUP_VOICES]


def _get_live_tts_voices(settings, speech_endpoint, speech_region, refresh=False):
    """Fetch the configured Speech resource's available synthesis voices from Azure."""
    cache_key = _get_tts_voice_cache_key(settings, speech_endpoint, speech_region)
    current_time = time.time()

    if not refresh:
        with TTS_VOICE_CACHE_LOCK:
            cached_voice_data = TTS_VOICE_CACHE.get(cache_key)
            if cached_voice_data and current_time - cached_voice_data["timestamp"] < TTS_VOICE_CACHE_TTL_SECONDS:
                debug_print("[TTS] Returning cached Azure voice list")
                return [dict(voice) for voice in cached_voice_data["voices"]]

    speech_config = get_speech_synthesis_config(settings, speech_endpoint, speech_region)
    speech_synthesizer = speechsdk.SpeechSynthesizer(speech_config=speech_config, audio_config=None)
    voices_result = speech_synthesizer.get_voices_async().get()
    voice_infos = list(getattr(voices_result, "voices", []) or [])

    if not voice_infos:
        error_details = getattr(voices_result, "error_details", "") or "No voices returned by Azure Speech."
        raise RuntimeError(error_details)

    voices = [
        _format_tts_voice_info(voice_info)
        for voice_info in voice_infos
        if getattr(voice_info, "short_name", "") or getattr(voice_info, "name", "")
    ]
    voices.sort(key=_tts_voice_sort_key)

    with TTS_VOICE_CACHE_LOCK:
        TTS_VOICE_CACHE[cache_key] = {
            "timestamp": current_time,
            "voices": [dict(voice) for voice in voices],
        }

    debug_print(f"[TTS] Retrieved {len(voices)} voices from Azure Speech")
    return voices


def _get_tts_voices_for_synthesis(settings, speech_endpoint, speech_region, refresh=False):
    """Return live voices for validation, falling back to conservative defaults on lookup failure."""
    try:
        return _get_live_tts_voices(settings, speech_endpoint, speech_region, refresh=refresh)
    except Exception as ex:
        debug_print(f"[TTS] Voice lookup failed, using fallback voices: {str(ex)}")
        log_event(
            "[TTS] Azure voice lookup failed; using fallback voices",
            extra={"error": str(ex)},
            level=logging.WARNING,
        )
        return _get_backup_tts_voices()


def _select_supported_tts_voice(requested_voice, voices, excluded_voice_names=None):
    """Choose the requested voice when available, otherwise a preferred or first available voice."""
    excluded_voice_names = set(excluded_voice_names or [])
    available_voice_names = [
        voice.get("name", "")
        for voice in voices
        if voice.get("name") and voice.get("name") not in excluded_voice_names
    ]
    normalized_requested_voice = str(requested_voice or "").strip()

    if normalized_requested_voice in available_voice_names:
        return normalized_requested_voice

    for preferred_voice in TTS_PREFERRED_DEFAULT_VOICES:
        if preferred_voice in available_voice_names:
            return preferred_voice

    for voice_name in available_voice_names:
        if voice_name.startswith("en-US-"):
            return voice_name

    if available_voice_names:
        return available_voice_names[0]

    return TTS_BACKUP_VOICES[0]["name"]


def _is_unsupported_tts_voice_error(error_details):
    """Detect Azure Speech unsupported-voice cancellations."""
    normalized_error = str(error_details or "").lower()
    return "unsupported voice" in normalized_error or (
        "unsupported" in normalized_error and "voice" in normalized_error
    )


def _normalize_tts_speed(speed_value):
    """Parse and clamp a user-supplied TTS speed multiplier."""
    try:
        speed = float(speed_value)
    except (TypeError, ValueError) as ex:
        raise ValueError("speed must be a number") from ex

    if not math.isfinite(speed):
        raise ValueError("speed must be a finite number")

    return max(0.5, min(2.0, speed))


def _format_tts_prosody_rate(speed):
    """Return Azure Speech SSML rate as a relative change from normal speed."""
    normalized_speed = _normalize_tts_speed(speed)
    rate_delta_percent = (normalized_speed - 1.0) * 100

    if math.isclose(rate_delta_percent, 0.0, abs_tol=0.005):
        return "default"

    return f"{rate_delta_percent:+.2f}%"


def _build_tts_synthesizer(settings, speech_endpoint, speech_region, voice):
    """Create a Speech synthesizer configured for the selected output voice."""
    speech_config = get_speech_synthesis_config(settings, speech_endpoint, speech_region)
    speech_config.speech_synthesis_voice_name = voice
    speech_config.set_speech_synthesis_output_format(
        speechsdk.SpeechSynthesisOutputFormat.Audio48Khz192KBitRateMonoMp3
    )
    return speechsdk.SpeechSynthesizer(speech_config=speech_config, audio_config=None)


def register_route_backend_tts(bp):
    """
    Text-to-speech API routes using Azure Speech Services
    """

    @bp.route("/api/chat/tts", methods=["POST"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def synthesize_speech():
        """
        Synthesize text to speech using Azure Speech Service.
        Expects JSON: {
            "text": "Text to synthesize",
            "voice": "en-US-AndrewMultilingualNeural",  # optional, falls back to a supported voice
            "speed": 1.0  # optional, 0.5-2.0 range
        }
        Returns an audio/mpeg stream
        """
        try:
            debug_print("[TTS] Synthesize speech request received")
            
            # Get settings
            settings = get_settings()
            
            # Check if TTS is enabled
            if not settings.get('enable_text_to_speech', False):
                debug_print("[TTS] Text-to-speech is not enabled in settings")
                return jsonify({"error": "Text-to-speech is not enabled"}), 403
            
            # Validate speech service configuration
            speech_endpoint, speech_region, speech_auth_type, config_error = _get_speech_service_settings(settings)
            if config_error:
                debug_print(f"[TTS] Speech service configuration invalid: {config_error}")
                return jsonify({"error": config_error}), 500
            
            debug_print(
                f"[TTS] Speech service configured - auth_type: {speech_auth_type}, "
                f"endpoint: {speech_endpoint}, location: {speech_region or 'n/a'}"
            )
            
            # Parse request data
            data = request.get_json()
            if not data or 'text' not in data:
                debug_print("[TTS] Invalid request - missing 'text' field")
                return jsonify({"error": "Missing 'text' field in request"}), 400
            
            text = data.get('text', '').strip()
            if not text:
                debug_print("[TTS] Invalid request - text is empty")
                return jsonify({"error": "Text cannot be empty"}), 400
            
            # Get voice and speed settings
            requested_voice = str(data.get('voice') or '').strip()
            speed = _normalize_tts_speed(data.get('speed', 1.0))
            available_voices = _get_tts_voices_for_synthesis(settings, speech_endpoint, speech_region)
            voice = _select_supported_tts_voice(requested_voice, available_voices)
            if requested_voice and requested_voice != voice:
                debug_print(f"[TTS] Requested voice '{requested_voice}' unavailable; using fallback '{voice}'")
                log_event(
                    "[TTS] Requested voice unavailable; using fallback voice",
                    extra={"requested_voice": requested_voice, "fallback_voice": voice},
                    level=logging.WARNING,
                )
            
            debug_print(
                f"[TTS] Request params - requested_voice: {requested_voice or 'default'}, "
                f"selected_voice: {voice}, speed: {speed}, text_length: {len(text)}"
            )
            
            # Configure speech service
            try:
                speech_synthesizer = _build_tts_synthesizer(settings, speech_endpoint, speech_region, voice)
            except ValueError as config_error:
                debug_print(f"[TTS] Speech service configuration invalid: {str(config_error)}")
                log_event(
                    "[TTS] Speech service configuration invalid.",
                    extra={"error": str(config_error)},
                    level=logging.ERROR,
                )
                return jsonify({"error": TTS_CONFIG_ERROR_MESSAGE}), 500
            
            # Perform synthesis with retry logic for rate limiting (429 errors)
            max_retries = 3
            retry_count = 0
            last_error = None
            unsupported_voice_retry_used = False
            
            while retry_count <= max_retries:
                try:
                    # Build SSML if speed adjustment needed
                    if not math.isclose(speed, 1.0, abs_tol=0.001):
                        prosody_rate = _format_tts_prosody_rate(speed)
                        debug_print(
                            f"[TTS] Using SSML with speed adjustment: {speed}x, "
                            f"prosody_rate: {prosody_rate} "
                            f"(attempt {retry_count + 1}/{max_retries + 1})"
                        )
                        escaped_text = html.escape(text, quote=False)
                        escaped_voice = html.escape(voice, quote=True)
                        ssml = f"""
                        <speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="en-US">
                            <voice name="{escaped_voice}">
                                <prosody rate="{prosody_rate}">
                                    {escaped_text}
                                </prosody>
                            </voice>
                        </speak>
                        """
                        result = speech_synthesizer.speak_ssml_async(ssml).get()
                    else:
                        debug_print(f"[TTS] Using plain text synthesis (attempt {retry_count + 1}/{max_retries + 1})")
                        result = speech_synthesizer.speak_text_async(text).get()
                    
                    # Check for rate limiting or capacity issues
                    if result.reason == speechsdk.ResultReason.Canceled:
                        cancellation_details = result.cancellation_details
                        if cancellation_details.reason == speechsdk.CancellationReason.Error:
                            error_details = cancellation_details.error_details
                            
                            # Check if it's a rate limit error (429 or similar)
                            if "429" in error_details or "rate" in error_details.lower() or "quota" in error_details.lower() or "throttl" in error_details.lower():
                                if retry_count < max_retries:
                                    # Randomized delay between 50-800ms with exponential backoff
                                    base_delay = 0.05 + (retry_count * 0.1)  # 50ms, 150ms, 250ms base
                                    jitter = random.uniform(0, 0.75)  # Up to 750ms jitter
                                    delay = base_delay + jitter
                                    debug_print(f"[TTS] Rate limit detected (429), retrying in {delay*1000:.0f}ms (attempt {retry_count + 1}/{max_retries})")
                                    time.sleep(delay)
                                    retry_count += 1
                                    last_error = error_details
                                    continue  # Retry
                                else:
                                    debug_print(f"[TTS] ERROR - Rate limit exceeded after {max_retries} retries")
                                    return jsonify({"error": "Service temporarily unavailable due to high load. Please try again."}), 429
                            elif _is_unsupported_tts_voice_error(error_details) and not unsupported_voice_retry_used:
                                unsupported_voice_retry_used = True
                                refreshed_voices = _get_tts_voices_for_synthesis(
                                    settings,
                                    speech_endpoint,
                                    speech_region,
                                    refresh=True,
                                )
                                fallback_voice = _select_supported_tts_voice(
                                    None,
                                    refreshed_voices,
                                    excluded_voice_names={voice},
                                )

                                if fallback_voice and fallback_voice != voice:
                                    debug_print(
                                        f"[TTS] Voice '{voice}' rejected by Azure; retrying with '{fallback_voice}'"
                                    )
                                    log_event(
                                        "[TTS] Azure rejected requested voice; retrying with fallback voice",
                                        extra={"rejected_voice": voice, "fallback_voice": fallback_voice},
                                        level=logging.WARNING,
                                    )
                                    voice = fallback_voice
                                    speech_synthesizer = _build_tts_synthesizer(
                                        settings,
                                        speech_endpoint,
                                        speech_region,
                                        voice,
                                    )
                                    retry_count = 0
                                    continue

                                error_msg = f"Speech synthesis canceled: {cancellation_details.reason} - {error_details}"
                                debug_print(f"[TTS] ERROR - No fallback voice available after unsupported voice error: {error_msg}")
                                return jsonify({"error": "No supported text-to-speech voice is available"}), 500
                            else:
                                # Other error, don't retry
                                error_msg = f"Speech synthesis canceled: {cancellation_details.reason} - {error_details}"
                                debug_print(f"[TTS] ERROR - Synthesis failed: {error_msg}")
                                log_event(
                                    "[TTS] Speech synthesis canceled with Azure error details.",
                                    extra={"reason": str(cancellation_details.reason), "error_details": str(error_details)},
                                    level=logging.ERROR,
                                )
                                return jsonify({"error": TTS_SYNTHESIS_ERROR_MESSAGE}), 500
                    
                    # Success - break out of retry loop
                    break
                    
                except Exception as e:
                    # Network or other transient errors
                    if retry_count < max_retries and ("timeout" in str(e).lower() or "connection" in str(e).lower()):
                        delay = 0.05 + (retry_count * 0.1) + random.uniform(0, 0.75)
                        debug_print(f"[TTS] Transient error, retrying in {delay*1000:.0f}ms: {str(e)}")
                        log_event(f"TTS transient error, retrying: {str(e)}", level=logging.WARNING)
                        time.sleep(delay)
                        retry_count += 1
                        last_error = str(e)
                        continue
                    else:
                        raise  # Re-raise if not retryable or out of retries
            
            # Check result after retries
            if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
                debug_print(f"[TTS] Synthesis completed successfully - audio_size: {len(result.audio_data)} bytes")
                if retry_count > 0:
                    debug_print(f"[TTS] Success after {retry_count} retries")
                # Get audio data
                audio_data = result.audio_data
                
                # Return audio stream
                return send_file(
                    io.BytesIO(audio_data),
                    mimetype='audio/mpeg',
                    as_attachment=False,
                    download_name='speech.mp3'
                )
                
            elif result.reason == speechsdk.ResultReason.Canceled:
                cancellation_details = result.cancellation_details
                error_msg = f"Speech synthesis canceled: {cancellation_details.reason}"
                if cancellation_details.reason == speechsdk.CancellationReason.Error:
                    error_msg += f" - {cancellation_details.error_details}"
                debug_print(f"[TTS] ERROR - Synthesis failed: {error_msg}")
                log_event(
                    "[TTS] Speech synthesis canceled.",
                    extra={"reason": str(cancellation_details.reason), "error_details": str(getattr(cancellation_details, 'error_details', ''))},
                    level=logging.ERROR,
                )
                return jsonify({"error": TTS_SYNTHESIS_ERROR_MESSAGE}), 500
            else:
                debug_print(f"[TTS] ERROR - Unknown synthesis error, reason: {result.reason}")
                return jsonify({"error": "Unknown synthesis error"}), 500
                
        except ValueError as e:
            debug_print(f"[TTS] ERROR - Invalid parameter: {str(e)}")
            log_event("[TTS] Invalid request parameter.", extra={"error": str(e)}, level=logging.WARNING)
            return jsonify({"error": "Invalid text-to-speech request parameter."}), 400
        except Exception as e:
            debug_print(f"[TTS] ERROR - Exception: {str(e)}")
            log_event("[TTS] Speech synthesis failed.", extra={"error": str(e)}, level=logging.ERROR, exceptionTraceback=True)
            return jsonify({"error": TTS_SYNTHESIS_ERROR_MESSAGE}), 500

    @bp.route("/api/chat/tts/voices", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def get_available_voices():
        """
        Returns the configured Speech resource's available voices for TTS.
        """
        debug_print("[TTS] Get available voices request received")
        settings = get_settings()
        speech_endpoint, speech_region, speech_auth_type, config_error = _get_speech_service_settings(settings)
        refresh = str(request.args.get('refresh', '')).lower() in {'1', 'true', 'yes'}
        source = "azure"
        warning = None

        if config_error:
            debug_print(f"[TTS] Voice list using fallback due to configuration issue: {config_error}")
            voices = _get_backup_tts_voices()
            source = "fallback"
            warning = config_error
        else:
            debug_print(
                f"[TTS] Loading voices - auth_type: {speech_auth_type}, "
                f"endpoint: {speech_endpoint}, location: {speech_region or 'n/a'}, refresh: {refresh}"
            )
            try:
                voices = _get_live_tts_voices(settings, speech_endpoint, speech_region, refresh=refresh)
            except Exception as ex:
                debug_print(f"[TTS] ERROR - Azure voice list lookup failed, using fallback voices: {str(ex)}")
                log_event(
                    "[TTS] Azure voice list lookup failed; using fallback voices",
                    extra={"error": str(ex)},
                    level=logging.WARNING,
                )
                voices = _get_backup_tts_voices()
                source = "fallback"
                warning = "Live voice lookup failed; fallback voices returned."

        default_voice = _select_supported_tts_voice(None, voices)
        return jsonify({
            "voices": voices,
            "default_voice": default_voice,
            "source": source,
            "warning": warning,
        }), 200

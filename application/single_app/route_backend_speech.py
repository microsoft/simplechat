# route_backend_speech.py
"""
Backend routes for speech-to-text functionality.
"""
from config import *
from functions_appinsights import log_event
from functions_authentication import login_required, user_required, get_current_user_id
from functions_debug import debug_print
from functions_documents import _get_speech_config, _transcribe_audio_with_fast_api
from functions_settings import get_settings
from swagger_wrapper import swagger_route, get_auth_security
import azure.cognitiveservices.speech as speechsdk
import logging
import os
import tempfile
import time
import traceback

try:
    from pydub import AudioSegment
    PYDUB_AVAILABLE = True
except ImportError:
    PYDUB_AVAILABLE = False
    log_event("[SPEECH] pydub not available; audio conversion may fail for non-WAV formats.", debug_only=True)


def _transcribe_wav_with_speech_sdk(temp_audio_path, settings, speech_endpoint, speech_locale):
    """Fallback transcription using Azure Speech SDK continuous recognition."""
    speech_config = _get_speech_config(settings, speech_endpoint, speech_locale)
    audio_config = speechsdk.AudioConfig(filename=temp_audio_path)
    speech_recognizer = speechsdk.SpeechRecognizer(
        speech_config=speech_config,
        audio_config=audio_config,
    )

    audio_file_size = os.path.getsize(temp_audio_path)
    debug_print(f"[SPEECH] Audio file size: {audio_file_size} bytes")

    try:
        debug_print("[SPEECH] Starting continuous recognition for longer audio...")

        all_results = []
        done = False

        def handle_recognized(evt):
            """Handle recognized speech events"""
            if evt.result.reason == speechsdk.ResultReason.RecognizedSpeech and evt.result.text:
                debug_print(f"[SPEECH] Recognized: {evt.result.text}")
                all_results.append(evt.result.text.strip())

        def handle_canceled(evt):
            """Handle cancellation events"""
            nonlocal done
            debug_print(f"[SPEECH] Canceled: {evt}")
            if evt.reason == speechsdk.CancellationReason.Error:
                debug_print(f"[SPEECH] Error details: {evt.error_details}")
            done = True

        def handle_session_stopped(evt):
            """Handle session stopped events"""
            nonlocal done
            debug_print("[SPEECH] Session stopped")
            done = True

        speech_recognizer.recognized.connect(handle_recognized)
        speech_recognizer.canceled.connect(handle_canceled)
        speech_recognizer.session_stopped.connect(handle_session_stopped)

        speech_recognizer.start_continuous_recognition()

        timeout = 120
        elapsed = 0.0
        while not done and elapsed < timeout:
            time.sleep(0.05)
            elapsed += 0.05

        speech_recognizer.stop_continuous_recognition()
        debug_print(f"[SPEECH] Recognition complete. Recognized {len(all_results)} segments")
        return [segment for segment in all_results if segment]
    finally:
        try:
            if speech_recognizer:
                speech_recognizer.recognized.disconnect_all()
                speech_recognizer.canceled.disconnect_all()
                speech_recognizer.session_stopped.disconnect_all()
                time.sleep(0.1)
                debug_print("[SPEECH] Speech recognizer cleanup complete")
        except Exception as recognizer_cleanup_error:
            log_event(
                "[SPEECH] Error during Speech SDK recognizer cleanup.",
                extra={"error_type": type(recognizer_cleanup_error).__name__},
                debug_only=True,
            )


def _transcribe_chat_wav(temp_audio_path, settings, speech_endpoint, speech_locale):
    """
    Transcribe a chat/dictation WAV clip using Azure Speech Fast Transcription API
    on the configured endpoint when available, falling back to Speech SDK.
    """
    normalized_endpoint = (speech_endpoint or "").strip().rstrip("/")
    if AZURE_ENVIRONMENT not in ("usgovernment", "custom"):
        try:
            log_event(
                "[SPEECH] Attempting Fast Transcription API for voice dictation.",
                extra={"locale": speech_locale},
                debug_only=True,
            )
            phrases = _transcribe_audio_with_fast_api(
                temp_audio_path,
                "recording.wav",
                "audio/wav",
                settings,
                normalized_endpoint,
                speech_locale,
            )
            return [phrase for phrase in phrases if phrase]
        except Exception as fast_err:
            log_event(
                "[SPEECH] Fast Transcription API unavailable for voice dictation; falling back to Speech SDK.",
                extra={"error_type": type(fast_err).__name__},
                debug_only=True,
            )

    return _transcribe_wav_with_speech_sdk(
        temp_audio_path,
        settings,
        normalized_endpoint,
        speech_locale,
    )


def register_route_backend_speech(bp):
    """Register speech-to-text routes"""
    
    @bp.route('/api/speech/transcribe-chat', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def transcribe_chat_audio():
        """
        Transcribe audio from chat speech input.
        Expects audio blob in 'audio' field of FormData.
        Returns JSON with transcribed text or error.
        """
        user_id = get_current_user_id()
        
        # Get settings
        settings = get_settings()
        
        # Check if speech-to-text chat input is enabled
        if not settings.get('enable_speech_to_text_input', False):
            return jsonify({
                'success': False,
                'error': 'Speech-to-text chat input is not enabled'
            }), 403
        
        # Check if audio file was provided
        if 'audio' not in request.files:
            return jsonify({
                'success': False,
                'error': 'No audio file provided'
            }), 400
        
        audio_file = request.files['audio']
        
        if audio_file.filename == '':
            return jsonify({
                'success': False,
                'error': 'Empty audio file'
            }), 400
        
        # Save audio to temporary WAV file
        temp_audio_path = None
        
        try:
            # Create temporary file for uploaded audio (always WAV from frontend)
            with tempfile.NamedTemporaryFile(delete=False, suffix='.wav') as temp_audio:
                audio_file.save(temp_audio.name)
                temp_audio_path = temp_audio.name
            
            speech_endpoint = (settings.get('speech_service_endpoint') or '').strip()
            speech_locale = settings.get('speech_service_locale', 'en-US')
            
            if not speech_endpoint:
                return jsonify({
                    'success': False,
                    'error': 'Speech service endpoint not configured'
                }), 500
            
            all_results = _transcribe_chat_wav(
                temp_audio_path,
                settings,
                speech_endpoint,
                speech_locale,
            )
            
            if all_results:
                combined_text = ' '.join(all_results).strip()
                debug_print(f"[SPEECH] Combined text length: {len(combined_text)} characters")
                return jsonify({
                    'success': True,
                    'text': combined_text
                })
            else:
                debug_print("[SPEECH] No speech recognized")
                return jsonify({
                    'success': False,
                    'error': 'No speech could be recognized'
                })
                
        except Exception as e:
            log_event(
                "[SPEECH] Error transcribing chat audio.",
                extra={"user_id": user_id, "error_type": type(e).__name__},
                level=logging.ERROR,
            )
            traceback.print_exc()
            return jsonify({
                'success': False,
                'error': 'Failed to transcribe audio. Please try again.'
            }), 500
            
        finally:
            # Clean up temporary files
            if temp_audio_path and os.path.exists(temp_audio_path):
                try:
                    os.remove(temp_audio_path)
                except PermissionError:
                    try:
                        time.sleep(0.2)
                        os.remove(temp_audio_path)
                    except Exception:
                        log_event(
                            "[SPEECH] Temp audio file still locked; OS will clean up.",
                            debug_only=True,
                        )
                except Exception as cleanup_error:
                    log_event(
                        "[SPEECH] Error cleaning up temporary audio file.",
                        extra={"error_type": type(cleanup_error).__name__},
                        debug_only=True,
                    )

# route_backend_speech.py
"""
Backend routes for speech-to-text functionality.
"""
from config import *
from functions_authentication import login_required, get_current_user_id
from functions_settings import get_settings
import azure.cognitiveservices.speech as speechsdk
import os
import tempfile

try:
    from pydub import AudioSegment
    PYDUB_AVAILABLE = True
except ImportError:
    PYDUB_AVAILABLE = False
    print("Warning: pydub not available. Audio conversion may fail for non-WAV formats.")

def register_route_backend_speech(app):
    """Register speech-to-text routes"""
    
    @app.route('/api/speech/transcribe-chat', methods=['POST'])
    @login_required
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
        
        print(f"[Debug] Received audio file: {audio_file.filename}")
        
        # Save audio to temporary WAV file
        temp_audio_path = None
        
        try:
            # Create temporary file for uploaded audio (always WAV from frontend)
            with tempfile.NamedTemporaryFile(delete=False, suffix='.wav') as temp_audio:
                audio_file.save(temp_audio.name)
                temp_audio_path = temp_audio.name
            
            print(f"[Debug] Audio saved to: {temp_audio_path}")
            
            # Get speech configuration using existing helper
            from functions_documents import _get_speech_config
            
            speech_endpoint = settings.get('speech_service_endpoint', '')
            speech_locale = settings.get('speech_service_locale', 'en-US')
            
            if not speech_endpoint:
                return jsonify({
                    'success': False,
                    'error': 'Speech service endpoint not configured'
                }), 500
            
            # Get speech config
            speech_config = _get_speech_config(settings, speech_endpoint, speech_locale)
            
            print("[Debug] Speech config obtained successfully")
            
            # WAV files can use direct file input
            print(f"[Debug] Using WAV file directly: {temp_audio_path}")
            audio_config = speechsdk.AudioConfig(filename=temp_audio_path)
            
            # Create speech recognizer
            speech_recognizer = speechsdk.SpeechRecognizer(
                speech_config=speech_config,
                audio_config=audio_config
            )
            
            try:
                # Perform recognition
                result = speech_recognizer.recognize_once()
                
                # Check result
                if result.reason == speechsdk.ResultReason.RecognizedSpeech:
                    return jsonify({
                        'success': True,
                        'text': result.text
                    })
                elif result.reason == speechsdk.ResultReason.NoMatch:
                    return jsonify({
                        'success': False,
                        'error': 'No speech could be recognized'
                    })
                elif result.reason == speechsdk.ResultReason.Canceled:
                    cancellation = result.cancellation_details
                    error_message = f"Speech recognition canceled: {cancellation.reason}"
                    if cancellation.reason == speechsdk.CancellationReason.Error:
                        error_message = f"Error: {cancellation.error_details}"
                    return jsonify({
                        'success': False,
                        'error': error_message
                    }), 500
                else:
                    return jsonify({
                        'success': False,
                        'error': 'Unknown recognition result'
                    }), 500
            finally:
                # Close the recognizer to release file handle
                if speech_recognizer:
                    speech_recognizer.__del__()
                    print("[Debug] Speech recognizer closed")
                
        except Exception as e:
            print(f"Error transcribing audio: {e}")
            import traceback
            traceback.print_exc()
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500
            
        finally:
            # Clean up temporary files
            try:
                if temp_audio_path and os.path.exists(temp_audio_path):
                    # Small delay to ensure file handle is released
                    import time
                    time.sleep(0.1)
                    os.remove(temp_audio_path)
                    print(f"[Debug] Cleaned up temp file: {temp_audio_path}")
            except Exception as cleanup_error:
                print(f"Error cleaning up temporary files: {cleanup_error}")

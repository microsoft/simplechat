# route_backend_speech.py
"""
Backend routes for speech-to-text functionality.
"""
from config import *
from functions_authentication import login_required, get_current_user_id
from functions_settings import get_settings
from functions_debug import debug_print
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
            
            # Get audio file size for debugging
            audio_file_size = os.path.getsize(temp_audio_path)
            debug_print(f"[Speech] Audio file size: {audio_file_size} bytes")
            
            try:
                debug_print("[Speech] Starting continuous recognition for longer audio...")
                
                # Use continuous recognition for longer audio files
                all_results = []
                done = False
                
                def handle_recognized(evt):
                    """Handle recognized speech events"""
                    if evt.result.reason == speechsdk.ResultReason.RecognizedSpeech:
                        debug_print(f"[Speech] Recognized: {evt.result.text}")
                        all_results.append(evt.result.text)
                
                def handle_canceled(evt):
                    """Handle cancellation events"""
                    nonlocal done
                    debug_print(f"[Speech] Canceled: {evt}")
                    if evt.reason == speechsdk.CancellationReason.Error:
                        debug_print(f"[Speech] Error details: {evt.error_details}")
                    done = True
                
                def handle_session_stopped(evt):
                    """Handle session stopped events"""
                    nonlocal done
                    debug_print("[Speech] Session stopped")
                    done = True
                
                # Connect callbacks
                speech_recognizer.recognized.connect(handle_recognized)
                speech_recognizer.canceled.connect(handle_canceled)
                speech_recognizer.session_stopped.connect(handle_session_stopped)
                
                # Start continuous recognition
                speech_recognizer.start_continuous_recognition()
                
                # Wait for completion (timeout after 120 seconds)
                import time
                timeout = 120
                elapsed = 0
                while not done and elapsed < timeout:
                    time.sleep(0.1)
                    elapsed += 0.1
                
                # Stop recognition
                speech_recognizer.stop_continuous_recognition()
                
                debug_print(f"[Speech] Recognition complete. Recognized {len(all_results)} segments")
                
                # Combine all recognized text
                if all_results:
                    combined_text = ' '.join(all_results)
                    debug_print(f"[Speech] Combined text length: {len(combined_text)} characters")
                    return jsonify({
                        'success': True,
                        'text': combined_text
                    })
                else:
                    debug_print("[Speech] No speech recognized")
                    return jsonify({
                        'success': False,
                        'error': 'No speech could be recognized'
                    })
            finally:
                # Properly close the recognizer to release file handles
                try:
                    if speech_recognizer:
                        # Disconnect all callbacks
                        speech_recognizer.recognized.disconnect_all()
                        speech_recognizer.canceled.disconnect_all()
                        speech_recognizer.session_stopped.disconnect_all()
                        debug_print("[Speech] Disconnected recognizer callbacks")
                        
                        # Give the recognizer time to release resources
                        import time
                        time.sleep(0.2)
                        
                        debug_print("[Speech] Speech recognizer cleanup complete")
                except Exception as recognizer_cleanup_error:
                    print(f"[Debug] Error during recognizer cleanup: {recognizer_cleanup_error}")
                
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
            if temp_audio_path and os.path.exists(temp_audio_path):
                try:
                    # Longer delay to ensure file handle is fully released on Windows
                    import time
                    time.sleep(0.3)
                    os.remove(temp_audio_path)
                    print(f"[Debug] Cleaned up temp file: {temp_audio_path}")
                except PermissionError as perm_error:
                    # If still locked, schedule for deletion on next boot or ignore
                    print(f"[Debug] Temp file still locked, will be cleaned by OS: {temp_audio_path}")
                except Exception as cleanup_error:
                    print(f"[Debug] Error cleaning up temporary files: {cleanup_error}")

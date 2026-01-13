# route_backend_tts.py

from config import *
from functions_authentication import *
from functions_settings import *
from functions_debug import debug_print
from swagger_wrapper import swagger_route, get_auth_security
import azure.cognitiveservices.speech as speechsdk
import io
import time
import random

def register_route_backend_tts(app):
    """
    Text-to-speech API routes using Azure Speech Services
    """

    @app.route("/api/chat/tts", methods=["POST"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def synthesize_speech():
        """
        Synthesize text to speech using Azure Speech Service.
        Expects JSON: {
            "text": "Text to synthesize",
            "voice": "en-US-Andrew:DragonHDLatestNeural",  # optional, defaults to Andrew
            "speed": 1.0  # optional, 0.5-2.0 range
        }
        Returns audio/wav stream
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
            speech_key = settings.get('speech_service_key', '')
            speech_region = settings.get('speech_service_location', '')
            
            if not speech_key or not speech_region:
                debug_print("[TTS] Speech service not configured - missing key or region")
                return jsonify({"error": "Speech service not configured"}), 500
            
            debug_print(f"[TTS] Speech service configured - region: {speech_region}")
            
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
            voice = data.get('voice', 'en-US-Andrew:DragonHDLatestNeural')
            speed = float(data.get('speed', 1.0))
            
            # Clamp speed to valid range
            speed = max(0.5, min(2.0, speed))
            
            debug_print(f"[TTS] Request params - voice: {voice}, speed: {speed}, text_length: {len(text)}")
            
            # Configure speech service
            speech_config = speechsdk.SpeechConfig(
                subscription=speech_key, 
                region=speech_region
            )
            speech_config.speech_synthesis_voice_name = voice
            
            # Set output format to high quality
            speech_config.set_speech_synthesis_output_format(
                speechsdk.SpeechSynthesisOutputFormat.Audio48Khz192KBitRateMonoMp3
            )
            
            # Create synthesizer with no audio output config (returns audio data in result)
            speech_synthesizer = speechsdk.SpeechSynthesizer(
                speech_config=speech_config, 
                audio_config=None
            )
            
            # Perform synthesis with retry logic for rate limiting (429 errors)
            max_retries = 3
            retry_count = 0
            last_error = None
            
            while retry_count <= max_retries:
                try:
                    # Build SSML if speed adjustment needed
                    if speed != 1.0:
                        debug_print(f"[TTS] Using SSML with speed adjustment: {speed}x (attempt {retry_count + 1}/{max_retries + 1})")
                        speed_percent = int(speed * 100)
                        ssml = f"""
                        <speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="en-US">
                            <voice name="{voice}">
                                <prosody rate="{speed_percent}%">
                                    {text}
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
                            else:
                                # Other error, don't retry
                                error_msg = f"Speech synthesis canceled: {cancellation_details.reason} - {error_details}"
                                debug_print(f"[TTS] ERROR - Synthesis failed: {error_msg}")
                                return jsonify({"error": error_msg}), 500
                    
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
                print(f"[ERROR] TTS synthesis failed: {error_msg}")
                return jsonify({"error": error_msg}), 500
            else:
                debug_print(f"[TTS] ERROR - Unknown synthesis error, reason: {result.reason}")
                return jsonify({"error": "Unknown synthesis error"}), 500
                
        except ValueError as e:
            debug_print(f"[TTS] ERROR - Invalid parameter: {str(e)}")
            return jsonify({"error": f"Invalid parameter: {str(e)}"}), 400
        except Exception as e:
            debug_print(f"[TTS] ERROR - Exception: {str(e)}")
            log_event(f"TTS synthesis failed: {str(e)}", level=logging.ERROR)
            print(f"[ERROR] TTS synthesis exception: {str(e)}")
            import traceback
            traceback.print_exc()
            return jsonify({"error": f"TTS synthesis failed: {str(e)}"}), 500

    @app.route("/api/chat/tts/voices", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def get_available_voices():
        """
        Returns list of available DragonHD voices for TTS
        """
        debug_print("[TTS] Get available voices request received")
        voices = [
            {"name": "de-DE-Florian:DragonHDLatestNeural", "gender": "Male", "language": "German", "status": "GA"},
            {"name": "de-DE-Seraphina:DragonHDLatestNeural", "gender": "Female", "language": "German", "status": "GA"},
            {"name": "en-US-Adam:DragonHDLatestNeural", "gender": "Male", "language": "English (US)", "status": "GA"},
            {"name": "en-US-Alloy:DragonHDLatestNeural", "gender": "Male", "language": "English (US)", "status": "Preview"},
            {"name": "en-US-Andrew:DragonHDLatestNeural", "gender": "Male", "language": "English (US)", "status": "GA", "note": ""},
            {"name": "en-US-Andrew2:DragonHDLatestNeural", "gender": "Male", "language": "English (US)", "status": "GA", "note": "Optimized for conversational content"},
            {"name": "en-US-Andrew3:DragonHDLatestNeural", "gender": "Male", "language": "English (US)", "status": "Preview", "note": "Optimized for podcast content"},
            {"name": "en-US-Aria:DragonHDLatestNeural", "gender": "Female", "language": "English (US)", "status": "Preview"},
            {"name": "en-US-Ava:DragonHDLatestNeural", "gender": "Female", "language": "English (US)", "status": "GA"},
            {"name": "en-US-Ava3:DragonHDLatestNeural", "gender": "Female", "language": "English (US)", "status": "Preview", "note": "Optimized for podcast content"},
            {"name": "en-US-Brian:DragonHDLatestNeural", "gender": "Male", "language": "English (US)", "status": "GA"},
            {"name": "en-US-Davis:DragonHDLatestNeural", "gender": "Male", "language": "English (US)", "status": "GA"},
            {"name": "en-US-Emma:DragonHDLatestNeural", "gender": "Female", "language": "English (US)", "status": "GA"},
            {"name": "en-US-Emma2:DragonHDLatestNeural", "gender": "Female", "language": "English (US)", "status": "GA", "note": "Optimized for conversational content"},
            {"name": "en-US-Jenny:DragonHDLatestNeural", "gender": "Female", "language": "English (US)", "status": "Preview"},
            {"name": "en-US-MultiTalker-Ava-Andrew:DragonHDLatestNeural", "gender": "Multi", "language": "English (US)", "status": "Preview", "note": "Multiple speakers"},
            {"name": "en-US-Nova:DragonHDLatestNeural", "gender": "Female", "language": "English (US)", "status": "Preview"},
            {"name": "en-US-Phoebe:DragonHDLatestNeural", "gender": "Female", "language": "English (US)", "status": "Preview"},
            {"name": "en-US-Serena:DragonHDLatestNeural", "gender": "Female", "language": "English (US)", "status": "Preview"},
            {"name": "en-US-Steffan:DragonHDLatestNeural", "gender": "Male", "language": "English (US)", "status": "GA"},
            {"name": "es-ES-Tristan:DragonHDLatestNeural", "gender": "Male", "language": "Spanish (Spain)", "status": "GA"},
            {"name": "es-ES-Ximena:DragonHDLatestNeural", "gender": "Female", "language": "Spanish (Spain)", "status": "GA"},
            {"name": "fr-FR-Remy:DragonHDLatestNeural", "gender": "Male", "language": "French", "status": "GA"},
            {"name": "fr-FR-Vivienne:DragonHDLatestNeural", "gender": "Female", "language": "French", "status": "GA"},
            {"name": "ja-JP-Masaru:DragonHDLatestNeural", "gender": "Male", "language": "Japanese", "status": "GA"},
            {"name": "ja-JP-Nanami:DragonHDLatestNeural", "gender": "Female", "language": "Japanese", "status": "GA"},
            {"name": "zh-CN-Xiaochen:DragonHDLatestNeural", "gender": "Female", "language": "Chinese (Simplified)", "status": "GA"},
            {"name": "zh-CN-Yunfan:DragonHDLatestNeural", "gender": "Male", "language": "Chinese (Simplified)", "status": "GA"}
        ]
        
        return jsonify({"voices": voices}), 200

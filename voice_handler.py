# voice_handler.py

import speech_recognition as sr
import threading
from faster_whisper import WhisperModel
import io
import os
import simpleaudio as sa
from TTS.api import TTS
import re

# --- Initialize Coqui TTS ---
print("Initializing Coqui TTS engine...")
tts = TTS("tts_models/en/ljspeech/vits", gpu=False)
print("Coqui TTS engine initialized.")
# -----------------------------

class VoiceHandler:
    def __init__(self):
        print("Initializing Voice Handler with Faster Whisper...")
        model_size = "base.en"
        self.stt_model = WhisperModel(model_size, device="cpu", compute_type="int8")
        self.recognizer = sr.Recognizer()
        print("Voice Handler initialized.")

    def _clean_text_for_tts(self, text):
        """Removes emojis and other non-speech characters to prevent errors."""
        # This regex is now more comprehensive
        emoji_pattern = re.compile(
            "["
            "\U0001F600-\U0001F64F"  # emoticons
            "\U0001F300-\U0001F5FF"  # symbols & pictographs
            "\U0001F680-\U0001F6FF"  # transport & map symbols
            "\U0001F900-\U0001F9FF"  # <-- ADDED: Supplemental Symbols and Pictographs
            "\U0001FA00-\U0001FAFF"  # Extended-A
            "\U00002702-\U000027B0"  # Dingbats
            "\U000024C2-\U0001F251" 
            "]+",
            flags=re.UNICODE,
        )
        cleaned_text = emoji_pattern.sub(r'', text)
        cleaned_text = re.sub(r'[\*#]', '', cleaned_text)
        return cleaned_text.strip()

    def speak(self, text):
        """Converts text to an audio file and plays it in a separate thread."""
        threading.Thread(target=self._speak_thread, args=(text,), daemon=True).start()

    def _speak_thread(self, text):
        """Private method to generate and play speech."""
        try:
            cleaned_text = self._clean_text_for_tts(text)
            if not cleaned_text:
                print("[TTS] No speakable text after cleaning.")
                return

            output_wav_path = "temp_speech.wav"
            tts.tts_to_file(text=cleaned_text, file_path=output_wav_path)
            
            wave_obj = sa.WaveObject.from_wave_file(output_wav_path)
            play_obj = wave_obj.play()
            play_obj.wait_done()
            
            os.remove(output_wav_path)
        except Exception as e:
            print(f"Error in TTS engine: {e}")

    def listen(self, callback):
        threading.Thread(target=self._listen_thread, args=(callback,), daemon=True).start()

    def _listen_thread(self, callback):
        """Private method for the listening thread."""
        recognized_text = ""
        with sr.Microphone() as source:
            print("Listening...")
            self.recognizer.adjust_for_ambient_noise(source, duration=0.5)
            try:
                audio = self.recognizer.listen(source, timeout=5, phrase_time_limit=15)
                print("Recognizing offline...")
                audio_data = io.BytesIO(audio.get_wav_data())
                segments, _ = self.stt_model.transcribe(audio_data)
                recognized_text = "".join(segment.text for segment in segments).strip()
                print(f"You said: {recognized_text}")
            except Exception as e:
                recognized_text = f"[ERROR] Could not recognize: {e}"
        
        callback(recognized_text)
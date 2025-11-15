# voice_handler.py

import threading
from faster_whisper import WhisperModel
import io
import os
import simpleaudio as sa
from TTS.api import TTS
import re
import time

# --- NEW Imports ---
import sounddevice as sd
import numpy as np
import soundfile as sf
# ---------------------

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
        
        self.sample_rate = 22050
        self.block_duration_ms = 50
        self.block_size = int(self.sample_rate * (self.block_duration_ms / 1000.0))
        self.vad_threshold = 0.01
        self.silence_duration_s = 1.5
        
        # --- MODIFIED: Buffer is now just a fallback ---
        self.interrupted_text_buffer = None
        # --- NEW: Callback for immediate interruption handling ---
        self.interruption_callback = None
        # -----------------------------------------------------
        
        print("Voice Handler initialized.")

    # --- NEW: Function to receive the callback from the UI ---
    def set_interruption_callback(self, callback):
        """Sets the callback function for UI updates on interruption."""
        self.interruption_callback = callback
    # -------------------------------------------------------

    def _clean_text_for_tts(self, text):
        """Removes emojis and other non-speech characters to prevent errors."""
        emoji_pattern = re.compile(
            "["
            "\U0001F600-\U0001F64F"  # emoticons
            "\U0001F300-\U0001F5FF"  # symbols & pictographs
            "\U0001F680-\U0001F6FF"  # transport & map symbols
            "\U0001F900-\U0001F9FF"
            "\U0001FA00-\U0001FAFF"
            "\U00002702-\U000027B0"
            "\U000024C2-\U0001F251" 
            "]+",
            flags=re.UNICODE,
        )
        cleaned_text = emoji_pattern.sub(r'', text)
        cleaned_text = re.sub(r'[\*#]', '', cleaned_text)
        return cleaned_text.strip()

    def speak(self, text):
        """
        Converts text to speech and plays it.
        Starts a thread to play audio and listen for barge-in.
        """
        # Clear any previous interruption *just in case*
        self.interrupted_text_buffer = None 
        
        # Start the speak-and-listen thread
        threading.Thread(target=self._speak_with_barge_in, args=(text,), daemon=True).start()

    def _speak_with_barge_in(self, text):
        """
        The private thread for speaking and listening.
        """
        stream = None
        play_obj = None
        
        try:
            cleaned_text = self._clean_text_for_tts(text)
            if not cleaned_text:
                print("[TTS] No speakable text after cleaning.")
                return

            output_wav_path = "temp_speech.wav"
            tts.tts_to_file(text=cleaned_text, file_path=output_wav_path)
            
            wave_obj = sa.WaveObject.from_wave_file(output_wav_path)
            play_obj = wave_obj.play()
            
            stream = sd.InputStream(
                samplerate=self.sample_rate,
                channels=1,
                dtype='float32',
                blocksize=self.block_size
            )
            stream.start()
            print("[TTS] Speaking... (Listening for barge-in)")

            audio_buffer = []
            interruption_started = False
            silence_blocks = 0
            max_silence_blocks = int(self.silence_duration_s * 1000 / self.block_duration_ms)

            while play_obj.is_playing() or interruption_started:
                audio_chunk, overflowed = stream.read(self.block_size)
                if overflowed:
                    print("[WARN] Audio buffer overflowed")

                rms = np.sqrt(np.mean(audio_chunk**2))

                if not interruption_started:
                    if rms > self.vad_threshold:
                        print("[TTS] Interruption detected!")
                        interruption_started = True
                        play_obj.stop()  # Stop TTS playback
                        audio_buffer.append(audio_chunk)
                else:
                    audio_buffer.append(audio_chunk)
                    
                    if rms < self.vad_threshold:
                        silence_blocks += 1
                    else:
                        silence_blocks = 0
                    
                    if silence_blocks > max_silence_blocks:
                        print("[TTS] Interruption recording complete (silence).")
                        break
            
            stream.stop()
            stream.close()
            
            if os.path.exists(output_wav_path):
                os.remove(output_wav_path)
                
            # --- MODIFIED: Use the callback instead of the buffer ---
            if interruption_started and audio_buffer:
                print("[TTS] Transcribing interruption...")
                full_audio = np.concatenate(audio_buffer)
                text = self._transcribe_audio_data(full_audio)
                
                if self.interruption_callback:
                    # Immediately send the text to the UI handler
                    print(f"[TTS] Sending interruption to UI: {text}")
                    self.interruption_callback(text)
                else:
                    # Fallback if no callback is set
                    print(f"[TTS] Storing interruption in buffer: {text}")
                    self.interrupted_text_buffer = text
            # -----------------------------------------------------

            print("[TTS] Speak thread finished.")

        except Exception as e:
            print(f"Error in speak_with_barge_in: {e}")
            if stream:
                stream.stop()
                stream.close()
            if play_obj and play_obj.is_playing():
                play_obj.stop()

    def listen(self, callback):
        """
        Listens for user speech and calls the callback with the text.
        """
        # 1. Check for buffered interruption text (as a fallback)
        if self.interrupted_text_buffer:
            print(f"[Listen] Using buffered interruption: {self.interrupted_text_buffer}")
            text_to_send = self.interrupted_text_buffer
            self.interrupted_text_buffer = None # Clear buffer
            callback(text_to_send)
        else:
            # 2. No buffer, so do a normal listen
            threading.Thread(target=self._listen_thread, args=(callback,), daemon=True).start()

    def _listen_thread(self, callback):
        """
        Private thread for a normal listen (no TTS playing).
        """
        stream = None
        try:
            stream = sd.InputStream(
                samplerate=self.sample_rate,
                channels=1,
                dtype='float32',
                blocksize=self.block_size
            )
            stream.start()

            print("Listening... (Waiting for speech)")
            
            while True:
                audio_chunk, _ = stream.read(self.block_size)
                rms = np.sqrt(np.mean(audio_chunk**2))
                if rms > self.vad_threshold:
                    print("Recognizing... (Speech detected)")
                    break
            
            audio_buffer = [audio_chunk]
            silence_blocks = 0
            max_silence_blocks = int(self.silence_duration_s * 1000 / self.block_duration_ms)

            while silence_blocks < max_silence_blocks:
                audio_chunk, _ = stream.read(self.block_size)
                audio_buffer.append(audio_chunk)
                
                rms = np.sqrt(np.mean(audio_chunk**2))
                if rms < self.vad_threshold:
                    silence_blocks += 1
                else:
                    silence_blocks = 0
            
            print("Recognizing... (Recording complete)")
            stream.stop()
            stream.close()

            full_audio = np.concatenate(audio_buffer)
            recognized_text = self._transcribe_audio_data(full_audio)
            print(f"You said: {recognized_text}")

            callback(recognized_text) # Send text to the UI handler

        except Exception as e:
            recognized_text = f"[ERROR] Could not recognize: {e}"
            if stream:
                stream.stop()
                stream.close()
            callback(recognized_text)
    
    def _transcribe_audio_data(self, audio_data):
        """
        Takes a numpy array of audio data, converts it to a WAV in memory,
        and transcribes it using Faster Whisper.
        """
        try:
            bytes_io = io.BytesIO()
            sf.write(
                bytes_io, 
                audio_data, 
                self.sample_rate, 
                format='WAV', 
                subtype='PCM_16'
            )
            bytes_io.seek(0)
            
            segments, _ = self.stt_model.transcribe(bytes_io)
            recognized_text = "".join(segment.text for segment in segments).strip()
            
            return recognized_text
        except Exception as e:
            print(f"Error during transcription: {e}")
            return f"[ERROR] Transcription failed: {e}"
# voice_handler.py

import threading
from faster_whisper import WhisperModel
import io
import os
import simpleaudio as sa
from TTS.api import TTS
import re
import time

import sounddevice as sd
import numpy as np
import soundfile as sf

print("Initializing Coqui TTS engine...")
tts = TTS("tts_models/en/ljspeech/vits", gpu=False)
print("Coqui TTS engine initialized.")

class VoiceHandler:
    def __init__(self):
        print("Initializing Voice Handler with Faster Whisper...")
        model_size = "base.en"
        self.stt_model = WhisperModel(model_size, device="cpu", compute_type="int8")
        
        self.sample_rate = 22050
        self.block_duration_ms = 50
        self.block_size = int(self.sample_rate * (self.block_duration_ms / 1000.0))
        self.vad_threshold = 0.15 # Your tuned value
        self.silence_duration_s = 1.5
        
        self.interrupted_text_buffer = None
        self.interruption_callback = None
        self.speech_end_callback = None
        
        print("Voice Handler initialized.")

    def set_interruption_callback(self, callback):
        self.interruption_callback = callback
        
    def set_speech_end_callback(self, callback):
        self.speech_end_callback = callback

    def _clean_text_for_tts(self, text):
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

    # --- 1. THIS IS THE "VOICE MODE" SPEAK (Old 'speak' function) ---
    def speak_with_barge_in(self, text):
        """
        Starts a thread to play audio AND listen for barge-in.
        """
        self.interrupted_text_buffer = None 
        # --- RENAMED THREAD TARGET ---
        threading.Thread(target=self._speak_with_barge_in_thread, args=(text,), daemon=True).start()

    # --- 2. NEW: THIS IS THE "TEXT MODE" SPEAK ---
    def speak_silently(self, text):
        """
        Starts a thread to play audio but does NOT listen for barge-in.
        """
        threading.Thread(target=self._speak_silently_thread, args=(text,), daemon=True).start()

    def _speak_silently_thread(self, text):
        """
        Private thread for "deaf" speaking. Just plays audio.
        """
        try:
            cleaned_text = self._clean_text_for_tts(text)
            if not cleaned_text:
                print("[TTS-Silent] No speakable text after cleaning.")
                return

            # Use a different temp file name to avoid conflicts
            output_wav_path = "temp_speech_silent.wav" 
            tts.tts_to_file(text=cleaned_text, file_path=output_wav_path)
            
            wave_obj = sa.WaveObject.from_wave_file(output_wav_path)
            play_obj = wave_obj.play()
            play_obj.wait_done()
            
            os.remove(output_wav_path)
            print("[TTS-Silent] Speak thread finished.")
        except Exception as e:
            print(f"Error in _speak_silently_thread: {e}")

    # --- 3. RENAMED from _speak_with_barge_in ---
    def _speak_with_barge_in_thread(self, text):
        """
        The private thread for speaking and listening.
        (This is your old _speak_with_barge_in function, unchanged)
        """
        stream = None
        play_obj = None
        interruption_started = False 
        
        try:
            cleaned_text = self._clean_text_for_tts(text)
            if not cleaned_text:
                print("[TTS] No speakable text after cleaning.")
                if self.speech_end_callback:
                    self.speech_end_callback()
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
                rms = np.sqrt(np.mean(audio_chunk**2))

                if not interruption_started:
                    if rms > self.vad_threshold:
                        print("[TTS] Interruption detected!")
                        interruption_started = True
                        play_obj.stop()
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
                
            if interruption_started and audio_buffer:
                print("[TTS] Transcribing interruption...")
                full_audio = np.concatenate(audio_buffer)
                text = self._transcribe_audio_data(full_audio)
                
                if self.interruption_callback:
                    print(f"[TTS] Sending interruption to UI: {text}")
                    self.interruption_callback(text)
                else:
                    self.interrupted_text_buffer = text
            
            if not interruption_started and self.speech_end_callback:
                print("[TTS] Speech finished, calling end callback.")
                self.speech_end_callback()

            print("[TTS] Speak thread finished.")

        except Exception as e:
            print(f"Error in _speak_with_barge_in_thread: {e}")
            if stream: stream.stop(); stream.close()
            if play_obj and play_obj.is_playing(): play_obj.stop()
            if not interruption_started and self.speech_end_callback:
                self.speech_end_callback()

    # --- (listen, _listen_thread, and _transcribe_audio_data are unchanged) ---
    def listen(self, callback):
        if self.interrupted_text_buffer:
            print(f"[Listen] Using buffered interruption: {self.interrupted_text_buffer}")
            text_to_send = self.interrupted_text_buffer
            self.interrupted_text_buffer = None
            callback(text_to_send)
        else:
            threading.Thread(target=self._listen_thread, args=(callback,), daemon=True).start()

    def _listen_thread(self, callback):
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

            callback(recognized_text)

        except Exception as e:
            recognized_text = f"[ERROR] Could not recognize: {e}"
            if stream:
                stream.stop()
                stream.close()
            callback(recognized_text)
    
    def _transcribe_audio_data(self, audio_data):
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
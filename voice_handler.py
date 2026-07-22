import threading
from faster_whisper import WhisperModel
import io
import os
import simpleaudio as sa
from TTS.api import TTS
import re
import time
import queue 

import sounddevice as sd
import numpy as np
import soundfile as sf
import nltk

# --- NLTK Download (unchanged) ---
try:
    nltk.data.find('tokenizers/punkt_tab')
    print("NLTK 'punkt_tab' model found.")
except LookupError:
    print("NLTK 'punkt_tab' model not found. Downloading...")
    nltk.download('punkt_tab')
# -----------------------------------

print("Initializing Coqui TTS engine...")
tts = TTS("tts_models/en/ljspeech/vits", gpu=False)
print("Coqui TTS engine initialized.")

class VoiceHandler:
    def __init__(self):
        print("Initializing Voice Handler with Faster Whisper...")
        model_size = "base.en"
        self.stt_model = WhisperModel(model_size, device="cpu", compute_type="int8")
        
        # --- COMPATIBILITY SETTINGS ---
        self.sample_rate = 44100 
        self.block_duration_ms = 50
        self.block_size = int(self.sample_rate * (self.block_duration_ms / 1000.0))
        self.vad_threshold = 0.15
        self.silence_duration_s = 1.5
        
        self.interrupted_text_buffer = None
        self.interruption_callback = None
        self.speech_end_callback = None
        
        # --- INITIAL DEVICE CHECK ---
        try:
            device_info = sd.query_devices(kind='input')
            print(f"\n[Audio] 🎤 Connected to: {device_info['name']}")
        except Exception as e:
            print(f"[Audio] Warning: No default input device found on startup ({e}).")

        print("Voice Handler initialized.")

    def set_interruption_callback(self, callback):
        self.interruption_callback = callback
        
    def set_speech_end_callback(self, callback):
        self.speech_end_callback = callback

    def _clean_text_for_tts(self, text):
        emoji_pattern = re.compile(
            "["
            "\U0001F600-\U0001F64F"
            "\U0001F300-\U0001F5FF"
            "\U0001F680-\U0001F6FF"
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

    # --- TTS Producer Thread ---
    def _tts_producer_thread(self, sentences, audio_queue, stop_event, temp_file_prefix):
        """Generates audio files in a separate thread."""
        try:
            for i, sentence in enumerate(sentences):
                if stop_event.is_set():
                    return
                
                if not sentence.strip():
                    continue
                
                output_wav_path = f"{temp_file_prefix}_{i}.wav"
                tts.tts_to_file(text=sentence, file_path=output_wav_path)
                
                audio_queue.put(output_wav_path)
            
            audio_queue.put(None) # End signal
            
        except Exception as e:
            print(f"Error in TTS producer thread: {e}")
            audio_queue.put(None)

    # --- Speak Silently (Text Mode) ---
    def speak_silently(self, text):
        threading.Thread(target=self._speak_silently_thread, args=(text,), daemon=True).start()

    def _speak_silently_thread(self, text):
        try:
            cleaned_text = self._clean_text_for_tts(text)
            if not cleaned_text: return

            sentences = nltk.sent_tokenize(cleaned_text)
            audio_queue = queue.Queue()
            stop_event = threading.Event()
            temp_file_prefix = "temp_speech_silent"

            producer_thread = threading.Thread(
                target=self._tts_producer_thread,
                args=(sentences, audio_queue, stop_event, temp_file_prefix),
                daemon=True
            )
            producer_thread.start()

            while True:
                try:
                    output_wav_path = audio_queue.get(timeout=10)
                    if output_wav_path is None: break
                    
                    wave_obj = sa.WaveObject.from_wave_file(output_wav_path)
                    play_obj = wave_obj.play()
                    play_obj.wait_done()
                    
                    os.remove(output_wav_path)
                except queue.Empty:
                    break
            
        except Exception as e:
            print(f"Error in _speak_silently_thread: {e}")

    # --- Speak with Barge-in (Voice Mode) ---
    def speak_with_barge_in(self, text):
        self.interrupted_text_buffer = None 
        threading.Thread(target=self._speak_with_barge_in_thread, args=(text,), daemon=True).start()

    def _speak_with_barge_in_thread(self, text):
        stream = None
        play_obj = None
        interruption_started = False 
        audio_buffer = []
        current_wav_file = None
        
        # --- SAFE BARGE-IN FLAG ---
        # If true, we listen for interruptions. If false, we just speak (like silent mode).
        barge_in_enabled = False

        audio_queue = queue.Queue()
        stop_producer_event = threading.Event()
        temp_file_prefix = "temp_speech_barge_in"

        try:
            cleaned_text = self._clean_text_for_tts(text)
            if not cleaned_text:
                if self.speech_end_callback: self.speech_end_callback()
                return

            sentences = nltk.sent_tokenize(cleaned_text)

            producer_thread = threading.Thread(
                target=self._tts_producer_thread,
                args=(sentences, audio_queue, stop_producer_event, temp_file_prefix),
                daemon=True
            )
            producer_thread.start()

            # --- DYNAMIC MIC CONNECTION ---
            # Try to connect to the mic. If it fails (no mic/wrong device), 
            # we just log it and continue speaking WITHOUT barge-in.
            try:
                stream = sd.InputStream(
                    samplerate=self.sample_rate,
                    channels=1,
                    dtype='float32',
                    blocksize=self.block_size
                )
                stream.start()
                barge_in_enabled = True
                print("[TTS] Speaking... (Listening for barge-in)")
            except Exception as e:
                print(f"[TTS] Warning: Could not open microphone for interruption ({e}). Barge-in disabled.")
                barge_in_enabled = False

            while producer_thread.is_alive() or not audio_queue.empty() or (play_obj and play_obj.is_playing()):
                
                # 1. Check for barge-in (ONLY if mic works)
                if barge_in_enabled and stream and stream.active:
                    try:
                        audio_chunk, _ = stream.read(self.block_size)
                        rms = np.sqrt(np.mean(audio_chunk**2))

                        if rms > self.vad_threshold:
                            print(f"[TTS] Interruption detected! (Vol: {rms:.4f})")
                            interruption_started = True
                            stop_producer_event.set()
                            if play_obj: play_obj.stop()
                            audio_buffer.append(audio_chunk)
                            break 
                    except Exception as e:
                        print(f"[TTS] Mic lost during playback: {e}. Disabling barge-in.")
                        barge_in_enabled = False
                        if stream: 
                            try: stream.stop(); stream.close()
                            except: pass

                # 2. Play Audio
                if not (play_obj and play_obj.is_playing()):
                    try:
                        next_file = audio_queue.get(block=False)
                        if current_wav_file: os.remove(current_wav_file)
                        if next_file is None: break 
                        
                        current_wav_file = next_file
                        wave_obj = sa.WaveObject.from_wave_file(current_wav_file)
                        play_obj = wave_obj.play()
                        print(f"[TTS] Playing chunk {current_wav_file}")

                    except queue.Empty:
                        pass

            # --- Interruption Logic ---
            if interruption_started and barge_in_enabled:
                print("[TTS] Recording interruption...")
                silence_blocks = 0
                max_silence_blocks = int(self.silence_duration_s * 1000 / self.block_duration_ms)
                
                try:
                    while silence_blocks < max_silence_blocks:
                        audio_chunk, _ = stream.read(self.block_size)
                        audio_buffer.append(audio_chunk)
                        rms = np.sqrt(np.mean(audio_chunk**2))
                        if rms < self.vad_threshold: silence_blocks += 1
                        else: silence_blocks = 0
                except Exception as e:
                    print(f"[TTS] Mic lost during interruption recording: {e}")

            if stream and barge_in_enabled:
                try: stream.stop(); stream.close()
                except: pass

            if current_wav_file and os.path.exists(current_wav_file): os.remove(current_wav_file)
            while not audio_queue.empty():
                try:
                    f = audio_queue.get(block=False)
                    if f and isinstance(f, str) and os.path.exists(f): os.remove(f)
                except queue.Empty: break

            if interruption_started and audio_buffer:
                print("[TTS] Transcribing interruption...")
                full_audio = np.concatenate(audio_buffer)
                text = self._transcribe_audio_data(full_audio)
                if self.interruption_callback: self.interruption_callback(text)
            elif not interruption_started and self.speech_end_callback:
                print("[TTS] Speech finished, calling end callback.")
                self.speech_end_callback()

            print("[TTS] Speak thread finished.")

        except Exception as e:
            print(f"Error in _speak_with_barge_in_thread: {e}")
            if stream: 
                try: stream.stop(); stream.close()
                except: pass
            if play_obj: play_obj.stop()
            if not interruption_started and self.speech_end_callback: self.speech_end_callback()

    # --- Listen (Standard) ---
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
            # --- SAFE STREAM START ---
            # We try to open the stream. If it fails (no mic), we inform the user via chat.
            try:
                stream = sd.InputStream(
                    samplerate=self.sample_rate,
                    channels=1,
                    dtype='float32',
                    blocksize=self.block_size
                )
                stream.start()
            except Exception as e:
                print(f"[Audio Error] Could not open microphone: {e}")
                # Send this special message to the chat window
                callback("[SYSTEM] No microphone detected. Please connect a device or type to chat.")
                return

            print("Listening... (Waiting for speech)")
            
            while True:
                # Watch out for disconnection mid-loop
                try:
                    audio_chunk, _ = stream.read(self.block_size)
                except Exception as e:
                    print(f"[Audio Error] Device disconnected: {e}")
                    callback("[SYSTEM] Microphone disconnected during listening.")
                    return

                rms = np.sqrt(np.mean(audio_chunk**2))
                print(f"\rLevel: {rms:.4f} (Threshold: {self.vad_threshold})", end="", flush=True)

                if rms > self.vad_threshold:
                    print(f"\nRecognizing... (Speech detected, Vol: {rms:.4f})")
                    break
            
            audio_buffer = [audio_chunk]
            silence_blocks = 0
            max_silence_blocks = int(self.silence_duration_s * 1000 / self.block_duration_ms)

            while silence_blocks < max_silence_blocks:
                try:
                    audio_chunk, _ = stream.read(self.block_size)
                    audio_buffer.append(audio_chunk)
                    rms = np.sqrt(np.mean(audio_chunk**2))
                    if rms < self.vad_threshold: silence_blocks += 1
                    else: silence_blocks = 0
                except Exception as e:
                    print(f"\n[Audio Error] Mic lost during recording: {e}")
                    break # Try to transcribe what we have
            
            print("Recognizing... (Recording complete)")
            stream.stop()
            stream.close()

            full_audio = np.concatenate(audio_buffer)
            recognized_text = self._transcribe_audio_data(full_audio)
            print(f"You said: {recognized_text}")

            callback(recognized_text)

        except Exception as e:
            # Catch-all for other errors
            print(f"\n[ERROR] Listen Thread: {e}")
            if stream: 
                try: stream.stop(); stream.close()
                except: pass
            callback(f"[ERROR] Audio System Error: {e}")
    
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
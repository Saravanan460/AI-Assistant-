import threading
from faster_whisper import WhisperModel
import io
import os
import simpleaudio as sa
import re
import time
import queue 
import wave

import sounddevice as sd
import numpy as np
import soundfile as sf
import nltk

try:
    from piper.voice import PiperVoice
except ImportError:
    print("[Error] piper-tts not installed. Please run: pip install piper-tts")
    exit(1)

# --- NLTK Download (unchanged) ---
try:
    nltk.data.find('tokenizers/punkt_tab')
    print("NLTK 'punkt_tab' model found.")
except LookupError:
    print("NLTK 'punkt_tab' model not found. Downloading...")
    nltk.download('punkt_tab')
# -----------------------------------


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
        
        # --- PIPER TTS SETUP ---
        print("Initializing Piper TTS engine...")
        piper_dir = os.path.abspath(os.path.join("models", "piper"))
        os.makedirs(piper_dir, exist_ok=True)
        model_name = "en_US-amy-medium"
        model_path = os.path.join(piper_dir, f"{model_name}.onnx")
        
        if not os.path.exists(model_path):
            print(f"[TTS] Downloading Piper voice model ({model_name}). This only happens once...")
            import urllib.request
            # Dynamically build URL based on model name (e.g., en_US-amy-medium -> amy)
            parts = model_name.split('-')
            lang_code = parts[0]
            speaker = parts[1]
            quality = parts[2]
            
            # The root language folder is usually just 'en' for 'en_US', 'en_GB' etc.
            base_lang = lang_code.split('_')[0]
            
            model_url = f"https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/{base_lang}/{lang_code}/{speaker}/{quality}/{model_name}.onnx"
            try:
                urllib.request.urlretrieve(model_url, model_path)
                urllib.request.urlretrieve(model_url + ".json", model_path + ".json")
            except Exception as e:
                print(f"[TTS] Error downloading model from {model_url}: {e}")
                if os.path.exists(model_path): os.remove(model_path)
                raise
            
        self.tts = PiperVoice.load(model_path)
        print("Piper TTS engine initialized.")
        
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

    def _parse_speech_chunks(self, text):
        """
        Parses text and returns a list of (type, data) tuples:
        [('text', "Oh, you actually did it?"), ('pause', 0.6), ('text', "I'm shocked.")]
        """
        chunks = []
        
        # Convert explicit actions and emojis into pauses for natural human pacing
        text = re.sub(r'\(dramatic pause\)', ' <PAUSE:0.8> ', text, flags=re.IGNORECASE)
        text = re.sub(r'\*slow clap\*', ' <PAUSE:0.6> ', text, flags=re.IGNORECASE)
        text = re.sub(r'\*.*?\*', ' <PAUSE:0.3> ', text) # Other actions
        text = re.sub(r'[😂🤣]', ' <PAUSE:0.4> ', text)
        text = re.sub(r'[🤔🙄]', ' <PAUSE:0.3> ', text)
        
        # Clean remaining emojis so TTS doesn't choke on them
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
        text = emoji_pattern.sub(r'', text)
        text = text.replace('#', '')
        
        # Split text by <PAUSE:X> markers
        parts = re.split(r'(<PAUSE:[0-9.]+>)', text)
        
        current_text = ""
        for p in parts:
            p = p.strip()
            if not p:
                continue
            if p.startswith('<PAUSE:') and p.endswith('>'):
                # Push accumulated text first
                if current_text.strip():
                    chunks.append(('text', current_text.strip()))
                    current_text = ""
                # Push the pause
                duration = float(p[7:-1])
                chunks.append(('pause', duration))
            else:
                current_text += p + " "
                
        if current_text.strip():
            chunks.append(('text', current_text.strip()))
            
        # Group sentences to preserve cross-sentence prosody
        final_chunks = []
        for ctype, data in chunks:
            if ctype == 'pause':
                final_chunks.append((ctype, data))
            else:
                sentences = nltk.sent_tokenize(data)
                # Group every 2 sentences to give Piper context for better intonation
                for i in range(0, len(sentences), 2):
                    group = " ".join(sentences[i:i+2])
                    final_chunks.append(('text', group))
                    # Add a very small natural breath pause between generated chunks
                    final_chunks.append(('pause', 0.2)) 
                    
        return final_chunks

    # --- TTS Producer Thread ---
    def _tts_producer_thread(self, chunks, audio_queue, stop_event, temp_file_prefix):
        """Generates audio files in a separate thread."""
        try:
            for i, (ctype, data) in enumerate(chunks):
                if stop_event.is_set():
                    return
                
                if ctype == 'pause':
                    audio_queue.put(('pause', data))
                elif ctype == 'text':
                    output_wav_path = f"{temp_file_prefix}_{i}.wav"
                    # Synthesize with Piper directly to WAV
                    with wave.open(output_wav_path, "wb") as wav_file:
                        self.tts.synthesize_wav(data, wav_file)
                    audio_queue.put(('file', output_wav_path))
            
            audio_queue.put(None) # End signal
            
        except Exception as e:
            print(f"Error in TTS producer thread: {e}")
            audio_queue.put(None)

    # --- Speak Silently (Text Mode) ---
    def speak_silently(self, text):
        threading.Thread(target=self._speak_silently_thread, args=(text,), daemon=True).start()

    def _speak_silently_thread(self, text):
        try:
            chunks = self._parse_speech_chunks(text)
            if not chunks: return

            audio_queue = queue.Queue()
            stop_event = threading.Event()
            temp_file_prefix = "temp_speech_silent"

            producer_thread = threading.Thread(
                target=self._tts_producer_thread,
                args=(chunks, audio_queue, stop_event, temp_file_prefix),
                daemon=True
            )
            producer_thread.start()

            while True:
                try:
                    next_item = audio_queue.get(timeout=10)
                    if next_item is None: break
                    
                    ctype, data = next_item
                    if ctype == 'pause':
                        time.sleep(data)
                    elif ctype == 'file':
                        wave_obj = sa.WaveObject.from_wave_file(data)
                        play_obj = wave_obj.play()
                        play_obj.wait_done()
                        if os.path.exists(data):
                            os.remove(data)
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
        
        is_paused = False
        pause_end_time = 0
        
        barge_in_enabled = False

        audio_queue = queue.Queue()
        stop_producer_event = threading.Event()
        temp_file_prefix = "temp_speech_barge_in"

        try:
            chunks = self._parse_speech_chunks(text)
            if not chunks:
                if self.speech_end_callback: self.speech_end_callback()
                return

            producer_thread = threading.Thread(
                target=self._tts_producer_thread,
                args=(chunks, audio_queue, stop_producer_event, temp_file_prefix),
                daemon=True
            )
            producer_thread.start()

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

            while producer_thread.is_alive() or not audio_queue.empty() or (play_obj and play_obj.is_playing()) or is_paused:
                
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

                # 2. Handle programmatic pausing (emotions/breath)
                if is_paused:
                    if time.time() >= pause_end_time:
                        is_paused = False
                    else:
                        time.sleep(0.01)
                        continue

                # 3. Play Audio
                if not (play_obj and play_obj.is_playing()) and not is_paused:
                    try:
                        next_item = audio_queue.get(block=False)
                        if current_wav_file and os.path.exists(current_wav_file):
                            os.remove(current_wav_file)
                            current_wav_file = None
                            
                        if next_item is None: break 
                        
                        ctype, data = next_item
                        if ctype == 'pause':
                            is_paused = True
                            pause_end_time = time.time() + data
                        elif ctype == 'file':
                            current_wav_file = data
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
                    if f and isinstance(f, tuple) and f[0] == 'file' and os.path.exists(f[1]): 
                        os.remove(f[1])
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
                callback("[SYSTEM] No microphone detected. Please connect a device or type to chat.")
                return

            print("Listening... (Waiting for speech)")
            
            while True:
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
                    break
            
            print("Recognizing... (Recording complete)")
            stream.stop()
            stream.close()

            full_audio = np.concatenate(audio_buffer)
            recognized_text = self._transcribe_audio_data(full_audio)
            print(f"You said: {recognized_text}")

            callback(recognized_text)

        except Exception as e:
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
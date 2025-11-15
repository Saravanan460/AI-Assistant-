# voice_handler.py

import threading
from faster_whisper import WhisperModel
import io
import os
import simpleaudio as sa
from TTS.api import TTS
import re
import time
import queue # --- NEW: For pipelining ---

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
        # ... (unchanged) ...
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
        # ... (unchanged) ...
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

    # --- NEW: TTS Producer Thread ---
    def _tts_producer_thread(self, sentences, audio_queue, stop_event, temp_file_prefix):
        """
        Generates audio files in a separate thread and puts their paths into a queue.
        """
        try:
            for i, sentence in enumerate(sentences):
                # Check if the main thread told us to stop (e.g., interruption)
                if stop_event.is_set():
                    print("[TTS-Producer] Stop event received. Halting generation.")
                    return
                
                if not sentence.strip():
                    continue
                
                output_wav_path = f"{temp_file_prefix}_{i}.wav"
                tts.tts_to_file(text=sentence, file_path=output_wav_path)
                
                # Add the generated file path to the queue for the consumer
                audio_queue.put(output_wav_path)
            
            # Put a "sentinel" value to signal the end
            audio_queue.put(None)
            print("[TTS-Producer] Finished generation.")
            
        except Exception as e:
            print(f"Error in TTS producer thread: {e}")
            audio_queue.put(None) # Signal end even on error

    # --- MODIFIED: "TEXT MODE" speak, now pipelined ---
    def speak_silently(self, text):
        threading.Thread(target=self._speak_silently_thread, args=(text,), daemon=True).start()

    def _speak_silently_thread(self, text):
        try:
            cleaned_text = self._clean_text_for_tts(text)
            if not cleaned_text:
                return

            sentences = nltk.sent_tokenize(cleaned_text)
            
            audio_queue = queue.Queue()
            stop_event = threading.Event() # We don't use this, but producer needs it
            temp_file_prefix = "temp_speech_silent"

            # Start the producer thread
            producer_thread = threading.Thread(
                target=self._tts_producer_thread,
                args=(sentences, audio_queue, stop_event, temp_file_prefix),
                daemon=True
            )
            producer_thread.start()

            # --- Consumer Loop ---
            while True:
                try:
                    # Wait for the next audio file
                    output_wav_path = audio_queue.get(timeout=10) # 10s timeout
                    
                    if output_wav_path is None:
                        # Producer is done
                        break
                    
                    wave_obj = sa.WaveObject.from_wave_file(output_wav_path)
                    play_obj = wave_obj.play()
                    play_obj.wait_done()
                    
                    os.remove(output_wav_path)
                
                except queue.Empty:
                    print("[TTS-Silent] Waited 10s, no new audio. Ending.")
                    break
            
            print("[TTS-Silent] Speak thread finished.")

        except Exception as e:
            print(f"Error in _speak_silently_thread: {e}")

    # --- MODIFIED: "VOICE MODE" speak, now pipelined with barge-in ---
    def speak_with_barge_in(self, text):
        self.interrupted_text_buffer = None 
        threading.Thread(target=self._speak_with_barge_in_thread, args=(text,), daemon=True).start()

    def _speak_with_barge_in_thread(self, text):
        stream = None
        play_obj = None
        interruption_started = False 
        audio_buffer = []
        current_wav_file = None
        
        audio_queue = queue.Queue()
        stop_producer_event = threading.Event()
        temp_file_prefix = "temp_speech_barge_in"

        try:
            cleaned_text = self._clean_text_for_tts(text)
            if not cleaned_text:
                if self.speech_end_callback:
                    self.speech_end_callback()
                return

            sentences = nltk.sent_tokenize(cleaned_text)

            # Start the producer thread
            producer_thread = threading.Thread(
                target=self._tts_producer_thread,
                args=(sentences, audio_queue, stop_producer_event, temp_file_prefix),
                daemon=True
            )
            producer_thread.start()

            stream = sd.InputStream(
                samplerate=self.sample_rate,
                channels=1,
                dtype='float32',
                blocksize=self.block_size
            )
            stream.start()
            print("[TTS] Speaking... (Listening for barge-in)")

            # --- Main Consumer & Barge-In Loop ---
            # We loop as long as the producer *might* still be working
            while producer_thread.is_alive() or not audio_queue.empty() or (play_obj and play_obj.is_playing()):
                
                # 1. Check for barge-in
                audio_chunk, _ = stream.read(self.block_size)
                rms = np.sqrt(np.mean(audio_chunk**2))

                if rms > self.vad_threshold:
                    print("[TTS] Interruption detected!")
                    interruption_started = True
                    stop_producer_event.set() # Tell producer to stop
                    if play_obj:
                        play_obj.stop()
                    audio_buffer.append(audio_chunk)
                    break # Exit main loop

                # 2. Check if we need to play the next audio chunk
                if not (play_obj and play_obj.is_playing()):
                    # Player is free. Do we have a new file?
                    try:
                        next_file = audio_queue.get(block=False)
                        
                        if current_wav_file:
                            os.remove(current_wav_file) # Clean up previous file
                        
                        if next_file is None:
                            # Producer is done, and queue is empty
                            break # Exit main loop
                        
                        # We have a new file to play
                        current_wav_file = next_file
                        wave_obj = sa.WaveObject.from_wave_file(current_wav_file)
                        play_obj = wave_obj.play()
                        print(f"[TTS] Playing chunk {current_wav_file}")

                    except queue.Empty:
                        # No new file yet, just keep looping VAD
                        pass
            
            # --- End of Main Loop ---

            if interruption_started:
                # We were interrupted, record the rest of the speech
                print("[TTS] Recording interruption...")
                silence_blocks = 0
                max_silence_blocks = int(self.silence_duration_s * 1000 / self.block_duration_ms)
                while silence_blocks < max_silence_blocks:
                    audio_chunk, _ = stream.read(self.block_size)
                    audio_buffer.append(audio_chunk)
                    rms = np.sqrt(np.mean(audio_chunk**2))
                    if rms < self.vad_threshold: silence_blocks += 1
                    else: silence_blocks = 0
                print("[TTS] Interruption recording complete.")
            
            stream.stop()
            stream.close()

            # --- Final Cleanup & Callbacks ---
            if current_wav_file and os.path.exists(current_wav_file):
                os.remove(current_wav_file)
            
            # Clean out the queue in case producer was killed mid-work
            while not audio_queue.empty():
                try:
                    f = audio_queue.get(block=False)
                    if f and os.path.exists(f): os.remove(f)
                except queue.Empty:
                    break

            if interruption_started and audio_buffer:
                print("[TTS] Transcribing interruption...")
                full_audio = np.concatenate(audio_buffer)
                text = self._transcribe_audio_data(full_audio)
                if self.interruption_callback:
                    self.interruption_callback(text)
            
            elif not interruption_started and self.speech_end_callback:
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
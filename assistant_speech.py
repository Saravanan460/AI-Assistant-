"""
assistant_no_pyaudio.py

Interruptible assistant WITHOUT PyAudio.

Features:
- Coqui TTS for synthesis (tts_models/en/ljspeech/vits)
- faster-whisper for ASR (base.en by default)
- sounddevice for mic capture (no PyAudio)
- simpleaudio for playback (interruptible)
- energy-based interrupt detection during playback

Usage:
    python assistant_no_pyaudio.py
"""

import io
import os
import uuid
import time
import threading
import numpy as np
import sounddevice as sd
import soundfile as sf
import simpleaudio as sa
from faster_whisper import WhisperModel
from TTS.api import TTS
import re
from collections import deque

# ---------------- CONFIG ----------------
SAMPLE_RATE = 16000               # microphone & ASR sample rate
FRAME_DURATION_MS = 30            # frame duration for processing (10 / 20 / 30 ms acceptable)
FRAME_SAMPLES = int(SAMPLE_RATE * FRAME_DURATION_MS / 1000)
ASR_MODEL_SIZE = "base.en"        # faster-whisper model; change to tiny.en/small.en if needed
TTS_MODEL = "tts_models/en/ljspeech/vits"
DEVICE = "cpu"
# Interrupt detection tuning (RMS on float32 audio [-1,1])
INTERRUPT_RMS_THRESHOLD = 0.02    # raise to reduce false positives, lower to be more sensitive
INTERRUPT_CONSECUTIVE = 2         # need this many consecutive frames above threshold
RING_BUFFER_SECONDS = 3.0         # how many seconds to keep as context for captured audio
# -----------------------------------------

# Initialize TTS
print("Initializing Coqui TTS...")
tts = TTS(TTS_MODEL, gpu=False)
print("Coqui TTS ready.")

class VoiceHandler:
    def __init__(self,
                 asr_model_name=ASR_MODEL_SIZE,
                 sr=SAMPLE_RATE,
                 frame_samples=FRAME_SAMPLES):
        print("Loading ASR model (faster-whisper)... this may take a moment.")
        self.stt_model = WhisperModel(asr_model_name, device=DEVICE, compute_type="int8")
        print("ASR ready.")
        self.sr = sr
        self.frame_samples = frame_samples

        # ring buffer for recent frames (float32 numpy arrays)
        max_frames = int((RING_BUFFER_SECONDS * self.sr) / self.frame_samples)
        self._ring = deque(maxlen=max_frames)

        # background listening control
        self._bg_stream = None
        self._bg_lock = threading.Lock()
        self._interrupt_event = threading.Event()
        self._captured_frames_snapshot = None  # list of numpy arrays (float32)
        self._rms_history = deque(maxlen=INTERRUPT_CONSECUTIVE)

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
        cleaned = emoji_pattern.sub("", text)
        cleaned = re.sub(r"[\*#]", "", cleaned)
        return cleaned.strip()

    # ---------------- TTS + interruptible playback ----------------
    def speak_and_wait_for_interrupt(self, text, device=None, poll_interval=0.05):
        """
        Synthesize text to WAV file, play it, open mic stream and monitor RMS;
        if user speaks while TTS plays, stop playback and return WAV bytes of captured user audio.
        If no interruption occurs, return None.
        """
        cleaned = self._clean_text_for_tts(text)
        if not cleaned:
            return None

        tmpfile = f"tmp_tts_{uuid.uuid4().hex}.wav"
        try:
            tts.tts_to_file(text=cleaned, file_path=tmpfile)
        except Exception as e:
            print("TTS synthesis error:", e)
            return None

        # prepare ring buffer and state
        with self._bg_lock:
            self._ring.clear()
            self._rms_history.clear()
            self._interrupt_event.clear()
            self._captured_frames_snapshot = None

        # start mic input stream to fill ring buffer and detect speech
        try:
            self._bg_stream = sd.InputStream(samplerate=self.sr, channels=1, dtype='float32',
                                             blocksize=self.frame_samples, callback=self._bg_callback,
                                             device=device)
            self._bg_stream.start()
        except Exception as e:
            print("Could not start microphone input stream:", e)
            # still play TTS but interruption won't work
            self._bg_stream = None

        # play TTS
        play_obj = None
        try:
            wave_obj = sa.WaveObject.from_wave_file(tmpfile)
            play_obj = wave_obj.play()

            # monitor playback and interruption
            while True:
                if play_obj is None:
                    break
                if not play_obj.is_playing():
                    break
                if self._interrupt_event.is_set():
                    try:
                        play_obj.stop()
                    except Exception:
                        pass
                    break
                time.sleep(poll_interval)
        finally:
            # stop microphone stream
            if self._bg_stream is not None:
                try:
                    self._bg_stream.stop()
                    self._bg_stream.close()
                except Exception:
                    pass
                self._bg_stream = None

            # remove tmp TTS file
            try:
                os.remove(tmpfile)
            except Exception:
                pass

        # if interrupt occurred, we have _captured_frames_snapshot (float32 frames)
        if self._captured_frames_snapshot:
            # write snapshot frames into WAV bytes
            wav_bytes = self._frames_to_wav_bytes(self._captured_frames_snapshot, self.sr)
            return wav_bytes
        return None

    def _bg_callback(self, indata, frames, time_info, status):
        """sounddevice callback while speaking: store frames into ring and check RMS"""
        try:
            # indata shape: (frames, channels); dtype float32 in [-1,1]
            mono = indata[:, 0] if indata.ndim > 1 else indata
            # push frame copy to ring
            with self._bg_lock:
                self._ring.append(mono.copy())
            # compute rms
            rms = float(np.sqrt(np.mean(mono * mono)))
            with self._bg_lock:
                self._rms_history.append(rms)
                # check consecutive RMS above threshold
                if len(self._rms_history) >= INTERRUPT_CONSECUTIVE and all(r >= INTERRUPT_RMS_THRESHOLD for r in list(self._rms_history)[-INTERRUPT_CONSECUTIVE:]):
                    # mark interrupt and snapshot current ring
                    self._interrupt_event.set()
                    # snapshot ring frames (copy)
                    with self._bg_lock:
                        self._captured_frames_snapshot = list(self._ring)
        except Exception:
            # ignore callback exceptions to avoid killing stream
            pass

    def _frames_to_wav_bytes(self, frames_list, sr):
        """frames_list: list of float32 1D arrays in [-1,1]"""
        if not frames_list:
            return None
        arr = np.concatenate(frames_list, axis=0)
        bio = io.BytesIO()
        sf.write(bio, arr, sr, format='WAV', subtype='PCM_16')
        bio.seek(0)
        return bio.read()

    # ---------------- Blocking listen (record until silence) ----------------
    def listen_blocking(self, device=None, timeout=8.0, silence_timeout=0.7):
        """
        Record until silence_timeout seconds of low energy occurs after speech starts,
        or until timeout (no speech).
        Returns WAV bytes or None.
        """
        print("Listening (sounddevice) ...")
        frames = []
        speaking = False
        last_voice_time = None
        start_time = time.time()

        try:
            stream = sd.InputStream(samplerate=self.sr, channels=1, dtype='float32',
                                    blocksize=self.frame_samples, device=device)
            stream.start()
        except Exception as e:
            print("Could not open mic for listening:", e)
            return None

        try:
            while True:
                block, _ = stream.read(self.frame_samples)
                mono = block[:, 0] if block.ndim > 1 else block
                frames.append(mono.copy())
                rms = float(np.sqrt(np.mean(mono * mono)))
                now = time.time()
                if rms >= INTERRUPT_RMS_THRESHOLD:
                    if not speaking:
                        speaking = True
                        # print("speech started")
                    last_voice_time = now
                if speaking:
                    if last_voice_time is not None and (now - last_voice_time) > silence_timeout:
                        # end of utterance
                        break
                else:
                    if (now - start_time) > timeout:
                        # timed out without speech
                        break
        finally:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass

        if not frames:
            return None
        return self._frames_to_wav_bytes(frames, self.sr)

    # ---------------- ASR helper ----------------
    def transcribe_wav_bytes(self, wav_bytes):
        try:
            bio = io.BytesIO(wav_bytes)
            segments, _ = self.stt_model.transcribe(bio)
            text = "".join(seg.text for seg in segments).strip()
            return text
        except Exception as e:
            return f"[ERROR] ASR failed: {e}"

# ---------------- Assistant wrapper ----------------
class Assistant:
    def __init__(self):
        self.vh = VoiceHandler()

    def say_and_listen_for_interrupt(self, text):
        user_wav = self.vh.speak_and_wait_for_interrupt(text)
        if user_wav:
            return self.vh.transcribe_wav_bytes(user_wav)
        return None

    def speak(self, text):
        # async speak
        threading.Thread(target=self._speak_async, args=(text,), daemon=True).start()

    def _speak_async(self, text):
        tmpfile = f"tmp_tts_{uuid.uuid4().hex}.wav"
        cleaned = self.vh._clean_text_for_tts(text)
        if not cleaned:
            return
        try:
            tts.tts_to_file(text=cleaned, file_path=tmpfile)
            wave_obj = sa.WaveObject.from_wave_file(tmpfile)
            play_obj = wave_obj.play()
            play_obj.wait_done()
        except Exception as e:
            print("TTS play error:", e)
        finally:
            try:
                os.remove(tmpfile)
            except Exception:
                pass

    def listen_once(self):
        wav = self.vh.listen_blocking()
        if wav:
            return self.vh.transcribe_wav_bytes(wav)
        return None

# ---------------- Demo ----------------
if __name__ == "__main__":
    assistant = Assistant()
    try:
        print("Assistant speaking. Try interrupting by talking while it speaks.")
        user_transcript = assistant.say_and_listen_for_interrupt(
            "Hello! I'm your assistant. I will speak now. If you say anything while I speak, I will stop and listen."
        )
        if user_transcript:
            print("Interrupted! You said (transcribed):", user_transcript)
            assistant.speak(f"You interrupted me and said: {user_transcript}")
        else:
            print("No interruption detected during speech.")
            text = assistant.listen_once()
            print("Heard (blocking listen):", text)

        print("Demo finished. Press Ctrl+C to exit.")
        while True:
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("Exiting.")
        pass

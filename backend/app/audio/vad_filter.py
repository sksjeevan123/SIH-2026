import torch
import numpy as np

try:
    import noisereduce as nr
    _HAS_NOISEREDUCE = True
except ImportError:
    _HAS_NOISEREDUCE = False


class VADFilter:
    """
    Voice-activity gating + residual noise reduction.

    Notes on what changed vs. a naive VAD-only approach:
      - VAD (Silero) only decides which *time ranges* are speech vs. silence.
        It does NOT remove noise that overlaps with speech itself (background
        hum, hiss, fan noise, etc. that's present while someone is talking).
      - To actually clean up "noise" in the sense most people mean, you need
        a second pass: spectral noise reduction on the kept speech, using a
        noise fingerprint sampled from a silent stretch of the same recording.
    """

    def __init__(self, use_onnx: bool = True, device: str = "cpu"):
        self.use_onnx = use_onnx
        self.device = torch.device(device)

        self.model, self.utils = torch.hub.load(
            repo_or_dir="snakers4/silero-vad",
            model="silero_vad",
            force_reload=False,
            onnx=use_onnx,  # ONNX runtime is noticeably faster than the raw torch model on CPU
        )
        if not use_onnx:
            self.model.to(self.device)

        (self.get_speech_timestamps, *_rest) = self.utils

    @staticmethod
    def _to_float32(audio_array: np.ndarray) -> np.ndarray:
        """
        Normalize integer PCM (int16/int32) to float32 in [-1, 1].
        Silero expects float32 audio -- feeding it raw int16 without
        normalizing is a common silent bug that hurts VAD accuracy.
        """
        if audio_array.dtype == np.float32:
            return audio_array
        if np.issubdtype(audio_array.dtype, np.integer):
            max_val = np.iinfo(audio_array.dtype).max
            return audio_array.astype(np.float32) / max_val
        return audio_array.astype(np.float32)

    @staticmethod
    def _get_noise_profile(audio_array, first_start, samplerate, max_len_ms=1000):
        """
        Grab a short chunk of non-speech audio to use as the noise
        fingerprint for spectral gating. Prefers the lead-in silence
        before the first detected speech segment.
        """
        max_len = int(samplerate * max_len_ms / 1000)
        min_lead_in = int(samplerate * 0.05)  # need at least ~50ms of silence to be useful

        if first_start > min_lead_in:
            return audio_array[max(0, first_start - max_len):first_start]
        # Fallback: just use the very start of the clip as an approximation
        return audio_array[:min(max_len, len(audio_array))]

    def extract_speech_and_metrics(
        self,
        audio_array: np.ndarray,
        samplerate: int = 16000,
        threshold: float = 0.5,
        min_speech_duration_ms: int = 250,
        min_silence_duration_ms: int = 100,
        speech_pad_ms: int = 30,
        denoise: bool = True,
    ):
        audio_array = self._to_float32(np.ascontiguousarray(audio_array))
        tensor_audio = torch.from_numpy(audio_array)
        if not self.use_onnx:
            tensor_audio = tensor_audio.to(self.device)

        with torch.inference_mode():
            timestamps = self.get_speech_timestamps(
                tensor_audio,
                self.model,
                sampling_rate=samplerate,
                threshold=threshold,
                min_speech_duration_ms=min_speech_duration_ms,
                # Merges speech chunks separated by short gaps -> less choppy
                # output and fewer segments triggered by brief noise bursts.
                min_silence_duration_ms=min_silence_duration_ms,
                # Pads segment edges so word onsets/offsets aren't clipped.
                speech_pad_ms=speech_pad_ms,
            )

        if not timestamps:
            return None, None

        # --- Vectorized speech/pause accounting (replaces the python loop) ---
        starts = np.fromiter((t["start"] for t in timestamps), dtype=np.int64, count=len(timestamps))
        ends = np.fromiter((t["end"] for t in timestamps), dtype=np.int64, count=len(timestamps))

        total_speech_samples = int(np.sum(ends - starts))
        total_pause_samples = int(np.sum(starts[1:] - ends[:-1])) if len(timestamps) > 1 else 0

        total_speech_ms = (total_speech_samples / samplerate) * 1000
        total_pause_ms = (total_pause_samples / samplerate) * 1000
        rhythm_ratio = total_speech_ms / (total_pause_ms + 1)  # +1 avoids div-by-zero

        prosody_metadata = {
            "speech_duration_ms": round(total_speech_ms, 2),
            "pause_duration_ms": round(total_pause_ms, 2),
            "rhythm_ratio": round(rhythm_ratio, 4),
            "segment_count": len(timestamps),
        }

        # --- Preallocated output buffer instead of list + np.concatenate ---
        # Avoids holding a python list of arrays plus a second full copy in
        # memory at concatenation time.
        clean_audio = np.empty(total_speech_samples, dtype=audio_array.dtype)
        cursor = 0
        for s, e in zip(starts, ends):
            seg_len = e - s
            clean_audio[cursor:cursor + seg_len] = audio_array[s:e]
            cursor += seg_len

        # --- Residual noise reduction on the kept speech itself ---
        if denoise:
            if _HAS_NOISEREDUCE:
                noise_profile = self._get_noise_profile(audio_array, int(starts[0]), samplerate)
                clean_audio = nr.reduce_noise(
                    y=clean_audio,
                    sr=samplerate,
                    y_noise=noise_profile,
                    stationary=False,  # better for noise that drifts over the recording
                )
            else:
                # noisereduce isn't installed -- VAD-only output is still returned,
                # but background noise within speech segments won't be cleaned.
                pass

        return clean_audio, prosody_metadata
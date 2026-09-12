import torch
import numpy as np
import soundfile as sf
from scipy import signal

try:
    import noisereduce as nr
    _HAS_NOISEREDUCE = True
except ImportError:
    _HAS_NOISEREDUCE = False


class RobustAudioCleaner:
    """
    Full front-end for audio that may come from inconsistent sources
    (direct TTS output vs. a phone/recorder mic across a room).

    Pipeline:
        load -> mono -> resample to target rate -> DC offset removal ->
        high-pass filter (rumble/hum) -> loudness normalization ->
        noise reduction -> VAD gating -> metrics

    The key insight: a mismatched sample rate or wildly different signal
    level will break ASR accuracy far more than residual background noise.
    Those get normalized away here BEFORE denoising/VAD ever run, so both
    stages see audio in a consistent, expected range regardless of source.
    """

    def __init__(self, target_samplerate: int = 16000, use_onnx: bool = True, device: str = "cpu"):
        self.target_sr = target_samplerate
        self.use_onnx = use_onnx
        self.device = torch.device(device)

        self.model, self.utils = torch.hub.load(
            repo_or_dir="snakers4/silero-vad",
            model="silero_vad",
            force_reload=False,
            onnx=use_onnx,
        )
        if not use_onnx:
            self.model.to(self.device)
        (self.get_speech_timestamps, *_rest) = self.utils

    # ---------------- Loading & normalization ----------------

    def load_audio(self, path: str) -> np.ndarray:
        """Load any file, force mono, resample to target rate."""
        audio, sr = sf.read(path, dtype="float32", always_2d=False)

        if audio.ndim > 1:
            audio = audio.mean(axis=1)  # downmix to mono

        if sr != self.target_sr:
            # resample_poly gives cleaner results than naive decimation,
            # important because samplerate mismatch is the #1 cause of
            # "TTS audio works, recorded audio doesn't" symptoms
            gcd = np.gcd(sr, self.target_sr)
            audio = signal.resample_poly(audio, self.target_sr // gcd, sr // gcd)
            audio = audio.astype(np.float32)

        return audio

    @staticmethod
    def remove_dc_offset(audio: np.ndarray) -> np.ndarray:
        return audio - np.mean(audio)

    @staticmethod
    def high_pass_filter(audio: np.ndarray, samplerate: int, cutoff_hz: float = 80.0) -> np.ndarray:
        """
        Removes rumble, mic handling noise, and AC hum (50/60Hz region)
        that direct TTS audio never has but a recorded mic almost always does.
        """
        sos = signal.butter(4, cutoff_hz, btype="highpass", fs=samplerate, output="sos")
        return signal.sosfiltfilt(sos, audio).astype(np.float32)

    @staticmethod
    def normalize_loudness(audio: np.ndarray, target_peak_db: float = -1.0) -> np.ndarray:
        """
        Peak-normalizes so recordings at very different input levels
        (quiet phone mic vs. hot TTS output) land in the same range
        before VAD thresholds and denoising are applied.
        """
        peak = np.max(np.abs(audio)) + 1e-9
        target_peak_linear = 10 ** (target_peak_db / 20)
        return (audio * (target_peak_linear / peak)).astype(np.float32)

    # ---------------- Core pipeline ----------------

    def clean(
        self,
        audio_array: np.ndarray,
        samplerate: int = None,
        vad_threshold: float = 0.5,
        min_speech_duration_ms: int = 250,
        min_silence_duration_ms: int = 100,
        speech_pad_ms: int = 30,
        denoise_strength: float = 0.9,  # prop_decrease for noisereduce, 0-1
    ):
        samplerate = samplerate or self.target_sr

        # If caller passes raw audio not already resampled via load_audio,
        # still guard against the mismatch here.
        if samplerate != self.target_sr:
            gcd = np.gcd(samplerate, self.target_sr)
            audio_array = signal.resample_poly(audio_array, self.target_sr // gcd, samplerate // gcd)
            samplerate = self.target_sr

        audio_array = self.remove_dc_offset(audio_array)
        audio_array = self.high_pass_filter(audio_array, samplerate)
        audio_array = self.normalize_loudness(audio_array)

        tensor_audio = torch.from_numpy(audio_array)
        if not self.use_onnx:
            tensor_audio = tensor_audio.to(self.device)

        with torch.inference_mode():
            timestamps = self.get_speech_timestamps(
                tensor_audio,
                self.model,
                sampling_rate=samplerate,
                threshold=vad_threshold,
                min_speech_duration_ms=min_speech_duration_ms,
                min_silence_duration_ms=min_silence_duration_ms,
                speech_pad_ms=speech_pad_ms,
            )

        if not timestamps:
            return None, None

        starts = np.fromiter((t["start"] for t in timestamps), dtype=np.int64, count=len(timestamps))
        ends = np.fromiter((t["end"] for t in timestamps), dtype=np.int64, count=len(timestamps))

        total_speech_samples = int(np.sum(ends - starts))
        total_pause_samples = int(np.sum(starts[1:] - ends[:-1])) if len(timestamps) > 1 else 0
        total_speech_ms = (total_speech_samples / samplerate) * 1000
        total_pause_ms = (total_pause_samples / samplerate) * 1000
        rhythm_ratio = total_speech_ms / (total_pause_ms + 1)

        prosody_metadata = {
            "speech_duration_ms": round(total_speech_ms, 2),
            "pause_duration_ms": round(total_pause_ms, 2),
            "rhythm_ratio": round(rhythm_ratio, 4),
            "segment_count": len(timestamps),
        }

        clean_audio = np.empty(total_speech_samples, dtype=audio_array.dtype)
        cursor = 0
        for s, e in zip(starts, ends):
            seg_len = e - s
            clean_audio[cursor:cursor + seg_len] = audio_array[s:e]
            cursor += seg_len

        if _HAS_NOISEREDUCE:
            noise_profile = self._get_noise_profile(audio_array, int(starts[0]), samplerate)
            clean_audio = nr.reduce_noise(
                y=clean_audio,
                sr=samplerate,
                y_noise=noise_profile,
                stationary=False,
                prop_decrease=denoise_strength,
            )
            # Re-normalize after denoising -- spectral gating can shift levels
            clean_audio = self.normalize_loudness(clean_audio)

        return clean_audio, prosody_metadata

    @staticmethod
    def _get_noise_profile(audio_array, first_start, samplerate, max_len_ms=1000):
        max_len = int(samplerate * max_len_ms / 1000)
        min_lead_in = int(samplerate * 0.05)
        if first_start > min_lead_in:
            return audio_array[max(0, first_start - max_len):first_start]
        return audio_array[:min(max_len, len(audio_array))]


if __name__ == "__main__":
    # Example usage
    cleaner = RobustAudioCleaner(target_samplerate=16000, use_onnx=True)
    audio = cleaner.load_audio("test_voiceai1.wav")
    clean_audio, metrics = cleaner.clean(audio, samplerate=16000)
    print(metrics)
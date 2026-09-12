import numpy as np
import librosa

class FeatureExtractor:
    def __init__(self, samplerate=16000):
        self.sr = samplerate
        self.hop_length = 512

    def extract_components(self, clean_audio_array: np.ndarray) -> dict:
        """
        Computes MFCC, F0, and CQT separately (before stacking) so downstream
        consumers (heuristic scorer, ML model) can reuse them without
        recomputing the same librosa transforms twice.
        """
        # 1. Extract MFCCs (Shape: 20 x frames)
        mfccs = librosa.feature.mfcc(
            y=clean_audio_array,
            sr=self.sr,
            n_mfcc=20,
            hop_length=self.hop_length
        )

        # 2. Extract F0 (Shape: frames,)
        f0 = librosa.yin(
            y=clean_audio_array,
            fmin=50,
            fmax=500,
            sr=self.sr,
            hop_length=self.hop_length
        )

        # 3. Extract CQT (Shape: 84 x frames)
        cqt = np.abs(librosa.cqt(
            y=clean_audio_array,
            sr=self.sr,
            hop_length=self.hop_length
        ))

        return {"mfccs": mfccs, "f0": f0, "cqt": cqt}

    def extract_and_stack(self, clean_audio_array: np.ndarray, components: dict = None):
        """
        Returns a single 2D feature matrix (MFCCs + F0 + CQT stacked vertically).
        Pass `components` (from extract_components) if you already computed
        them, to avoid doing it twice.
        """
        if components is None:
            components = self.extract_components(clean_audio_array)

        mfccs = components["mfccs"]
        f0 = components["f0"].reshape(1, -1)
        cqt = components["cqt"]

        feature_matrix = np.vstack((mfccs, f0, cqt))
        return feature_matrix
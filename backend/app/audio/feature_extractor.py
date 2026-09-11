import numpy as np
import librosa

class FeatureExtractor:
    def __init__(self, samplerate=16000):
        self.sr = samplerate
        self.hop_length = 512 

    def extract_and_stack(self, clean_audio_array: np.ndarray):
        """
        Takes a 1D audio array and returns a single 2D feature matrix
        containing MFCCs, F0, and CQT stacked vertically.
        """
        # 1. Extract MFCCs (Shape: 20 x frames)
        mfccs = librosa.feature.mfcc(
            y=clean_audio_array, 
            sr=self.sr, 
            n_mfcc=20, 
            hop_length=self.hop_length
        )
        
        # 2. Extract F0 (Shape: 1 x frames)
        f0 = librosa.yin(
            y=clean_audio_array, 
            fmin=50, 
            fmax=500, 
            sr=self.sr, 
            hop_length=self.hop_length
        )
        f0 = f0.reshape(1, -1)
        
        # 3. Extract CQT (Shape: 84 x frames)
        # librosa.cqt defaults to 84 frequency bins
        cqt = np.abs(librosa.cqt(
            y=clean_audio_array, 
            sr=self.sr, 
            hop_length=self.hop_length
        ))

        # 4. The Master Stack
        # Vertically stack all arrays along the feature axis
        feature_matrix = np.vstack((mfccs, f0, cqt))

        return feature_matrix
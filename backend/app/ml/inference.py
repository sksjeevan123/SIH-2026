import torch
import torch.nn.functional as F
import numpy as np
import librosa
from app.ml.model_loader import ml_singleton

def preprocess_2d_input(data_array: np.ndarray) -> tuple[np.ndarray, dict]:
    """
    Extracts 1D PCM audio array from a 2D input structure and isolates parameters.
    Handles shapes like (2, N), (N, 2), or (1, N).
    """
    if data_array.ndim == 1:
        return data_array.astype(np.float32), {}

    if data_array.ndim == 2:
        # Case A: Shape is (2, N) -> Row 0 is Audio Time Series, Row 1 is Parameters
        if data_array.shape[0] == 2:
            audio_series = data_array[0]
            param_series = data_array[1]
            
        # Case B: Shape is (N, 2) -> Column 0 is Audio Time Series, Column 1 is Parameters
        elif data_array.shape[1] == 2:
            audio_series = data_array[:, 0]
            param_series = data_array[:, 1]
            
        # Case C: Shape is (1, N) -> Squeezed single audio channel
        else:
            audio_series = np.squeeze(data_array)
            param_series = None

        audio_series = np.ascontiguousarray(audio_series, dtype=np.float32)
        params = {"raw_parameters": param_series.tolist()} if param_series is not None else {}
        return audio_series, params

    raise ValueError(f"Unsupported array dimension: {data_array.ndim}D")


def extract_acoustic_features(audio_array: np.ndarray, sample_rate: int = 16000) -> dict:
    spectral_centroids = librosa.feature.spectral_centroid(y=audio_array, sr=sample_rate)[0]
    zero_crossing_rate = librosa.feature.zero_crossing_rate(y=audio_array)[0]
    
    return {
        "mean_spectral_centroid": float(np.mean(spectral_centroids)),
        "mean_zero_crossing_rate": float(np.mean(zero_crossing_rate))
    }


async def analyze_voice_authenticity(input_array: np.ndarray, sample_rate: int = 16000) -> dict:
    """Accepts 1D or 2D NumPy array, extracts audio signal, and computes authenticity score."""
    if len(input_array) == 0:
        return {"error": "Empty audio input"}

    # Step 1: Unpack 2D array into 1D PCM audio and parameter dict
    audio_array, extra_params = preprocess_2d_input(input_array)

    # Step 2: Feature extraction for Wav2Vec2 neural net
    inputs = ml_singleton.feature_extractor(
        audio_array, 
        sampling_rate=sample_rate, 
        return_tensors="pt"
    ).to(ml_singleton.device)

    # Step 3: Deep learning inference
    with torch.no_grad():
        logits = ml_singleton.model(**inputs).logits
        probabilities = F.softmax(logits, dim=-1)[0]

    real_prob = float(probabilities[0])
    fake_prob = float(probabilities[1])
    risk_score = round(fake_prob * 100, 2)

    # Step 4: Risk level assignment
    if risk_score > 75:
        risk_level = "HIGH_RISK_CLONE"
    elif risk_score > 45:
        risk_level = "SUSPICIOUS"
    else:
        risk_level = "AUTHENTIC_HUMAN"

    # Step 5: Signal processing features
    acoustic_data = extract_acoustic_features(audio_array, sample_rate)

    return {
        "risk_score": risk_score,
        "fake_probability": fake_prob,
        "real_probability": real_prob,
        "risk_level": risk_level,
        "is_fake": fake_prob >= 0.50,
        "acoustic_analysis": acoustic_data,
        "received_parameters": extra_params
    }
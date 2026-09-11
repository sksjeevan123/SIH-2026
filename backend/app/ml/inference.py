import torch
import torch.nn.functional as F
import numpy as np
import librosa
from app.ml.model_loader import ml_singleton

def extract_acoustic_features(audio_array: np.ndarray, sample_rate: int = 16000) -> dict:
    """Calculates physical frequency properties from raw PCM data."""
    spectral_centroids = librosa.feature.spectral_centroid(y=audio_array, sr=sample_rate)[0]
    zero_crossing_rate = librosa.feature.zero_crossing_rate(y=audio_array)[0]
    
    return {
        "mean_spectral_centroid": float(np.mean(spectral_centroids)),
        "mean_zero_crossing_rate": float(np.mean(zero_crossing_rate))
    }

async def analyze_voice_authenticity(audio_array: np.ndarray, sample_rate: int = 16000) -> dict:
    """Runs combined deep learning and signal processing detection pipeline."""
    if len(audio_array) == 0:
        return {"error": "Empty audio chunk"}

    # Pre-process raw 16kHz float array
    inputs = ml_singleton.feature_extractor(
        audio_array, 
        sampling_rate=sample_rate, 
        return_tensors="pt"
    ).to(ml_singleton.device)

    # Neural network inference
    with torch.no_grad():
        logits = ml_singleton.model(**inputs).logits
        probabilities = F.softmax(logits, dim=-1)[0]

    real_prob = float(probabilities[0])
    fake_prob = float(probabilities[1])
    risk_score = round(fake_prob * 100, 2)

    # Threshold classification
    if risk_score > 75:
        risk_level = "HIGH_RISK_CLONE"
    elif risk_score > 45:
        risk_level = "SUSPICIOUS"
    else:
        risk_level = "AUTHENTIC_HUMAN"

    acoustic_data = extract_acoustic_features(audio_array, sample_rate)

    return {
        "risk_score": risk_score,
        "fake_probability": fake_prob,
        "real_probability": real_prob,
        "risk_level": risk_level,
        "is_fake": fake_prob >= 0.50,
        "acoustic_analysis": acoustic_data
    }
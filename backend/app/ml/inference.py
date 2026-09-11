import torch
import torch.nn.functional as F
import numpy as np
import librosa
from app.ml.model_loader import ml_singleton

def extract_acoustic_features(audio_array: np.ndarray, sample_rate: int = 16000) -> dict:
    """Calculates physical sound properties using signal processing."""
    spectral_centroids = librosa.feature.spectral_centroid(y=audio_array, sr=sample_rate)[0]
    zero_crossing_rate = librosa.feature.zero_crossing_rate(y=audio_array)[0]
    
    return {
        "mean_spectral_centroid": float(np.mean(spectral_centroids)),
        "mean_zero_crossing_rate": float(np.mean(zero_crossing_rate))
    }

async def analyze_voice_authenticity(audio_array: np.ndarray, sample_rate: int = 16000) -> dict:
    """Main pipeline combining Deep Learning and Acoustic Feature Analysis."""
    if len(audio_array) == 0:
        return {"error": "Empty audio chunk"}

    # 1. Pre-process audio waveform for neural network
    inputs = ml_singleton.feature_extractor(
        audio_array, 
        sampling_rate=sample_rate, 
        return_tensors="pt"
    ).to(ml_singleton.device)

    # 2. Run Deep Learning Model (Wav2Vec2)
    with torch.no_grad():
        logits = ml_singleton.model(**inputs).logits
        probabilities = F.softmax(logits, dim=-1)[0]

    real_prob = float(probabilities[0])
    fake_prob = float(probabilities[1])
    risk_score = round(fake_prob * 100, 2)

    # 3. Determine Risk Classification
    if risk_score > 75:
        risk_level = "HIGH_RISK_CLONE"
    elif risk_score > 45:
        risk_level = "SUSPICIOUS"
    else:
        risk_level = "AUTHENTIC_HUMAN"

    # 4. Run Secondary Acoustic Analysis (Step 4)
    acoustic_data = extract_acoustic_features(audio_array, sample_rate)

    # 5. Return Consolidated Results to Task 2 / FastAPI
    return {
        "risk_score": risk_score,
        "fake_probability": fake_prob,
        "real_probability": real_prob,
        "risk_level": risk_level,
        "is_fake": fake_prob >= 0.50,
        "acoustic_analysis": acoustic_data  # Step 4 features included here
    }
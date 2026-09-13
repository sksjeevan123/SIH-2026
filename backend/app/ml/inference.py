import os
import torch
import torch.nn.functional as F
import numpy as np
import librosa
import joblib
from app.ml.model_loader import ml_singleton
from app.audio.acoustic_authenticity import HeuristicAuthenticityScorer

heuristic_scorer = HeuristicAuthenticityScorer()

# Ensemble weights used ONLY as a fallback when no fitted fusion model exists yet.
# Wav2Vec2 is a trained deep model, so it leads; the heuristic is a supporting/
# sanity-check signal. Once fusion_model.joblib exists (see fit_fusion.py),
# these fixed weights are bypassed in favor of learned weights.
WAV2VEC_WEIGHT = 0.65
HEURISTIC_WEIGHT = 0.35

FUSION_MODEL_PATH = os.path.join(os.path.dirname(__file__), "fusion_model.joblib")
fusion_model = joblib.load(FUSION_MODEL_PATH) if os.path.exists(FUSION_MODEL_PATH) else None


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


def _fuse_scores(wav2vec_risk_score: float, heuristic_result: dict, fake_prob: float) -> tuple[float, bool]:
    """
    Combines the Wav2Vec2 score and the heuristic acoustic score into a
    final risk_score. Uses the fitted logistic-regression fusion model if
    one has been trained (see fit_fusion.py); otherwise falls back to a
    fixed weighted average.
    """
    signals_agree = (wav2vec_risk_score > 50) == (heuristic_result["heuristic_risk_score"] > 50)

    if fusion_model is not None:
        m = heuristic_result["raw_metrics"]
        x = [[
            fake_prob,
            m["cqt_highband_ratio"] or 0.0,
            m["f0_jitter"] or 0.0,
            m["mfcc_delta_mag"] or 0.0,
        ]]
        risk_score = round(float(fusion_model.predict_proba(x)[0][1]) * 100, 2)
    else:
        risk_score = round(
            WAV2VEC_WEIGHT * wav2vec_risk_score
            + HEURISTIC_WEIGHT * heuristic_result["heuristic_risk_score"],
            2,
        )

    return risk_score, signals_agree


async def analyze_voice_authenticity(
    input_array: np.ndarray,
    sample_rate: int = 16000,
    feature_components: dict = None,
) -> dict:
    """
    Accepts 1D or 2D NumPy array, extracts audio signal, and computes an
    ensemble authenticity score combining:
      - Wav2Vec2 deepfake classifier probability (deep, learned signal)
      - HeuristicAuthenticityScorer on MFCC/F0/CQT (rule-based, no training
        required -- catches vocoder artifacts and acts as a cross-check)

    Pass `feature_components` (dict with "mfccs"/"f0"/"cqt", from
    FeatureExtractor.extract_components) to enable the heuristic component.
    If omitted, falls back to Wav2Vec2-only scoring.

    If app/ml/fusion_model.joblib exists (trained via fit_fusion.py), it is
    used to combine the two signals with learned weights instead of the
    fixed WAV2VEC_WEIGHT / HEURISTIC_WEIGHT split.
    """
    if len(input_array) == 0:
        return {"error": "Empty audio input"}

    # Step 1: Unpack 2D array into 1D PCM audio and parameter dict
    audio_array, extra_params = preprocess_2d_input(input_array)

    # Step 2: Feature extraction for Wav2Vec2 neural net
    inputs = ml_singleton.feature_extractor(
        audio_array,
        sampling_rate=sample_rate,
        return_tensors="pt",
        padding=True,
    ).to(ml_singleton.device)

    # Step 3: Deep learning inference
    with torch.no_grad():
        logits = ml_singleton.model(**inputs).logits
        probabilities = F.softmax(logits, dim=-1)[0]

    real_prob = float(probabilities[0])
    fake_prob = float(probabilities[1])
    wav2vec_risk_score = round(fake_prob * 100, 2)

    # Step 4: Heuristic acoustic scorer on MFCC/F0/CQT
    heuristic_result = None
    if feature_components is not None:
        heuristic_result = heuristic_scorer.score(feature_components)

    # Step 5: Fuse into the final ensemble score
    if heuristic_result is not None:
        risk_score, signals_agree = _fuse_scores(wav2vec_risk_score, heuristic_result, fake_prob)
    else:
        risk_score = wav2vec_risk_score
        signals_agree = None

    # Step 6: Risk level assignment
    if risk_score > 75:
        risk_level = "HIGH_RISK_CLONE"
    elif risk_score > 32:
        risk_level = "SUSPICIOUS"
    else:
        risk_level = "AUTHENTIC_HUMAN"

    # Step 7: Legacy summary stats, kept for the response
    acoustic_data = extract_acoustic_features(audio_array, sample_rate)

    return {
        "risk_score": risk_score,
        "fake_probability": fake_prob,
        "real_probability": real_prob,
        "risk_level": risk_level,
        "is_fake": risk_score >= 50,
        "acoustic_analysis": acoustic_data,
        "wav2vec_component": {"risk_score": wav2vec_risk_score},
        "heuristic_component": heuristic_result,
        "signals_agree": signals_agree,
        "fusion_mode": "learned" if fusion_model is not None else "fixed_weights",
        "received_parameters": extra_params,
    }
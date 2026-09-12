import glob
import numpy as np
import librosa
import joblib
import torch
import torch.nn.functional as F
from sklearn.linear_model import LogisticRegression

from app.audio.vad_filter import VADFilter
from app.audio.feature_extractor import FeatureExtractor
from app.audio.acoustic_authenticity import HeuristicAuthenticityScorer
from app.ml.model_loader import ml_singleton

vad = VADFilter()
fe = FeatureExtractor(samplerate=16000)
scorer = HeuristicAuthenticityScorer()

def build_feature_vector(path):
    audio, sr = librosa.load(path, sr=16000, mono=True)
    clean, _ = vad.extract_speech_and_metrics(audio, samplerate=sr)
    if clean is None:
        return None

    comps = fe.extract_components(clean)
    heur = scorer.score(comps)

    inputs = ml_singleton.feature_extractor(
        clean, sampling_rate=sr, return_tensors="pt", padding=True
    ).to(ml_singleton.device)
    with torch.no_grad():
        logits = ml_singleton.model(**inputs).logits
        fake_prob = float(F.softmax(logits, dim=-1)[0][1])

    m = heur["raw_metrics"]
    return [
        fake_prob,
        m["cqt_highband_ratio"] or 0.0,
        m["f0_jitter"] or 0.0,
        m["mfcc_delta_mag"] or 0.0,
    ]

X, y = [], []
for path in glob.glob("dataset/real/*.wav"):
    v = build_feature_vector(path)
    if v: X.append(v); y.append(0)
for path in glob.glob("dataset/fake/*.wav"):
    v = build_feature_vector(path)
    if v: X.append(v); y.append(1)

X, y = np.array(X), np.array(y)
print(f"Training on {len(y)} samples ({int(sum(y))} fake, {len(y)-int(sum(y))} real)")

clf = LogisticRegression(class_weight="balanced")
clf.fit(X, y)
joblib.dump(clf, "app/ml/fusion_model.joblib")

names = ["wav2vec_fake_prob", "cqt_highband_ratio", "f0_jitter", "mfcc_delta_mag"]
print("Learned weights:", dict(zip(names, clf.coef_[0])))
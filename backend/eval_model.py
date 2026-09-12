import librosa
import torch
import torch.nn.functional as F
from transformers import AutoFeatureExtractor, AutoModelForAudioClassification

TEST_FILES = {
    "test_voiceai1.wav": 1,  # 1 = fake
    "test_voiceai2.wav": 1,
    "test_voiceai3.wav": 1,
    "test_voiceh1.wav": 0,   # 0 = real
    "test_voiceh2.wav": 0,
    "test_voiceh3.wav": 0,
}

def evaluate(model_name: str):
    print(f"\n=== Evaluating {model_name} ===")
    device = "cuda" if torch.cuda.is_available() else "cpu"
    feature_extractor = AutoFeatureExtractor.from_pretrained(model_name)
    model = AutoModelForAudioClassification.from_pretrained(model_name).to(device)
    model.eval()

    correct = 0
    for fname, true_label in TEST_FILES.items():
        audio, sr = librosa.load(fname, sr=16000, mono=True)
        inputs = feature_extractor(audio, sampling_rate=16000, return_tensors="pt", padding=True).to(device)
        with torch.no_grad():
            logits = model(**inputs).logits
            probs = F.softmax(logits, dim=-1)[0]
        fake_prob = float(probs[1])
        pred_label = 1 if fake_prob >= 0.5 else 0
        correct += int(pred_label == true_label)
        status = "OK" if pred_label == true_label else "WRONG"
        print(f"  {fname:20s} true={true_label} pred={pred_label} fake_prob={fake_prob:.4f}  [{status}]")

    acc = correct / len(TEST_FILES)
    print(f"  Accuracy: {acc*100:.1f}% ({correct}/{len(TEST_FILES)})")
    return acc

if __name__ == "__main__":
    candidates = [
     #    "garystafford/wav2vec2-deepfake-voice-detector",
     #    "Gustking/wav2vec2-large-xlsr-deepfake-audio-classification",
        "mo-thecreator/Deepfake-audio-detection",
    ]
    for name in candidates:
        try:
            evaluate(name)
        except Exception as e:
            print(f"  Failed to evaluate {name}: {e}")
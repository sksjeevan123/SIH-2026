import torch
from transformers import AutoFeatureExtractor, AutoModelForAudioClassification

MODEL_NAME = "garystafford/wav2vec2-deepfake-voice-detector"

class VoiceAuthenticityModel:
    def __init__(self):
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"Loading ML Model onto {self.device}...")
        
        self.feature_extractor = AutoFeatureExtractor.from_pretrained(MODEL_NAME)
        self.model = AutoModelForAudioClassification.from_pretrained(MODEL_NAME).to(self.device)
        self.model.eval()

# Global single instance
ml_singleton = VoiceAuthenticityModel()
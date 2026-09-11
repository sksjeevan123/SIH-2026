import torch
from transformers import AutoFeatureExtractor, AutoModelForAudioClassification

MODEL_NAME = "garystafford/wav2vec2-deepfake-voice-detector"

class VoiceAuthenticityModel:
    def __init__(self):
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.feature_extractor = AutoFeatureExtractor.from_pretrained(MODEL_NAME)
        
        raw_model = AutoModelForAudioClassification.from_pretrained(MODEL_NAME)
        if self.device == "cpu":
            # Apply dynamic quantization to boost CPU inference speed
            self.model = torch.quantization.quantize_dynamic(
                raw_model, {torch.nn.Linear}, dtype=torch.qint8
            )
        else:
            self.model = raw_model.to(self.device)
            
        self.model.eval()

# Global single instance initialized on app start
ml_singleton = VoiceAuthenticityModel()
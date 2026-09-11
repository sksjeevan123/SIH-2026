import asyncio
import librosa
import numpy as np
import os
from app.audio.feature_extractor import FeatureExtractor
from app.ml.inference import analyze_voice_authenticity

async def test_custom_audio_pipeline():
    print("--- Initializing Custom Audio Pipeline Test ---")
    
    # Use an absolute or correct relative path to your audio file
    audio_path = r"D:\Voice\SIH-2026\backend\app\audio\test_voice.wav"
    target_sr = 16000
    
    print(f"Loading audio file: {audio_path}...")
    try:
        audio_array, sample_rate = librosa.load(audio_path, sr=target_sr, mono=True)
        print(f"Audio loaded successfully! Length: {len(audio_array)} samples ({len(audio_array) / sample_rate:.2f} seconds at {sample_rate}Hz).")
    except Exception as e:
        print(f"Error loading audio file: {e}")
        return

    # 1. Test Feature Extractor
    print("\n[Step 1/2] Running Feature Extractor (MFCC, F0, CQT)...")
    extractor = FeatureExtractor(samplerate=sample_rate)
    feature_matrix = extractor.extract_and_stack(audio_array)
    print(f"Feature extraction successful! Output shape: {feature_matrix.shape}")

    # 2. Test ML Inference Module
    print("\n[Step 2/2] Running ML Inference on Custom Audio...")
    try:
        result = await analyze_voice_authenticity(audio_array, sample_rate=sample_rate)
        print("ML Inference Results:")
        for key, value in result.items():
            print(f"  - {key}: {value}")
    except Exception as e:
        print(f"Error during ML inference: {e}")

    print("\n--- Custom Pipeline Test Complete ---")

if __name__ == "__main__":
    asyncio.run(test_custom_audio_pipeline())
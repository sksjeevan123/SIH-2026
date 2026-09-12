import asyncio
import librosa
import numpy as np
import os
from app.audio.feature_extractor import FeatureExtractor
from app.audio.vad_filter import VADFilter
from app.ml.inference import analyze_voice_authenticity
from RobustAudioCleaner import RobustAudioCleaner

async def test_custom_audio_pipeline():
    print("--- Initializing Custom Audio Pipeline Test ---")

    audio_path = r"D:\Voice\SIH-2026\backend\test_voiceai1.wav"
    target_sr = 16000

    print(f"Loading audio file: {audio_path}...")
    audio_array, sample_rate = librosa.load(audio_path, sr=target_sr, mono=True)
    print(f"Loaded {len(audio_array)} samples ({len(audio_array)/sample_rate:.2f}s at {sample_rate}Hz)")

    # Run VAD first, same as production
    print("\n[Step 1/3] Running VAD...")
    cleaner = RobustAudioCleaner(target_samplerate=16000)
    clean_audio, prosody = cleaner.clean(audio_array, samplerate=16000)
    #clean_audio, prosody = vad.extract_speech_and_metrics(audio_array, samplerate=sample_rate)
    if clean_audio is None:
        print("No speech detected.")
        return
    print(f"Speech-only audio: {clean_audio.shape}, prosody={prosody}")

    # Extract components ONCE, reuse for both matrix + ensemble
    print("\n[Step 2/3] Running Feature Extractor (MFCC, F0, CQT)...")
    extractor = FeatureExtractor(samplerate=sample_rate)
    components = extractor.extract_components(clean_audio)
    feature_matrix = extractor.extract_and_stack(clean_audio, components=components)
    print(f"Feature extraction successful! Output shape: {feature_matrix.shape}")

    print("\n[Step 3/3] Running ML Inference (ensemble)...")
    result = await analyze_voice_authenticity(
        clean_audio, sample_rate=sample_rate, feature_components=components
    )
    for key, value in result.items():
        print(f"  - {key}: {value}")

if __name__ == "__main__":
    asyncio.run(test_custom_audio_pipeline())
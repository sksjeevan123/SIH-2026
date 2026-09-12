import base64
import sys
import numpy as np

# Import your Task 2 pipeline classes
from stream_buffer import StreamBuffer
from vad_filter import VADFilter
from feature_extractor import FeatureExtractor

# 1. Set the path to your test file
WAV_FILE_PATH = r"app\audio\test_voiceai1.wav"

try:
    print("Loading file and simulating frontend Base64 encoding...")
    with open(WAV_FILE_PATH, "rb") as f:
        wav_bytes = f.read()
    b64_audio = base64.b64encode(wav_bytes).decode('utf-8')

    mock_payload = {
        "audio": b64_audio,
        "call_id": "real_test_001"
    }

    print("\n--- RUNNING TASK 2 PIPELINE ---")
    
    # Step A: Buffer & Decode
    buffer = StreamBuffer()
    raw_audio, sr = buffer.ingest_chunk(mock_payload)
    print(f"1. StreamBuffer Output: Raw audio shape {raw_audio.shape} at {sr}Hz")

    # Step B: VAD (Silence Removal)
    vad = VADFilter()
    clean_audio, metrics = vad.extract_speech_and_metrics(raw_audio, sr)
    
    # --- VAD BYPASS FOR TESTING ---
    if clean_audio is None:
        print("\n[WARNING] VAD detected no human speech. Bypassing VAD and forcing raw_audio to show the matrix!")
        clean_audio = raw_audio 
    else:
        print(f"2. VAD Output: Clean audio shape {clean_audio.shape}")
        print(f"   Prosody Metrics: {metrics}")

    # Step C: Feature Extraction (Cleaned up the duplicate code)
    extractor = FeatureExtractor(samplerate=sr)
    feature_matrix = extractor.extract_and_stack(clean_audio)
    
    # Display the Final Numpy Array
    print("\n--- FINAL NUMPY MATRIX (HANDOFF TO TASK 3) ---")
    print(f"Matrix Shape: {feature_matrix.shape} -> (Features x Time Frames)")
    print(f"Data Type: {feature_matrix.dtype}")
    print(f"Min Value: {np.min(feature_matrix):.2f}, Max Value: {np.max(feature_matrix):.2f}\n")
    
    print("--- PRINTING FULL ARRAY ---")
    np.set_printoptions(threshold=sys.maxsize, linewidth=sys.maxsize, precision=3, suppress=True)
    print(feature_matrix)

    # Cleanup memory
    buffer.clear_session("real_test_001")
    print("\n[SUCCESS] Pipeline completed and memory cleared.")

except FileNotFoundError:
    print(f"\n[ERROR] Could not find '{WAV_FILE_PATH}'. Please place a valid WAV file in the directory.")
except Exception as e:
    print(f"\n[ERROR] Pipeline crashed: {e}")
import numpy as np
import soundfile as sf
import base64
import io

# Import your newly created classes
from stream_buffer import StreamBuffer
from vad_filter import VADFilter

print("1. Generating 4 seconds of dummy audio (440Hz sine wave)...")
samplerate = 16000
duration = 4.0
t = np.linspace(0, duration, int(samplerate * duration), endpoint=False)
# Create a 440Hz tone (float32, range -0.5 to 0.5)
dummy_audio = 0.5 * np.sin(2 * np.pi * 440 * t) 

print("2. Converting to in-memory WAV and encoding to Base64...")
with io.BytesIO() as wav_io:
    sf.write(wav_io, dummy_audio, samplerate, format='WAV', subtype='PCM_16')
    wav_bytes = wav_io.getvalue()

b64_audio = base64.b64encode(wav_bytes).decode('utf-8')

print("3. Creating mock frontend JSON payload...")
mock_payload = {
    "audio": b64_audio,
    "call_id": "test_call_001",
    "chunk_id": 1,
    "start_ms": 0,
    "duration_ms": 4000
}

print("\n--- INITIATING PIPELINE TEST ---")

try:
    # Test 1: Buffer Ingestion
    buffer = StreamBuffer()
    continuous_audio, sr = buffer.ingest_chunk(mock_payload)
    print(f"[SUCCESS] StreamBuffer extracted array of shape {continuous_audio.shape} at {sr}Hz")

    # Test 2: VAD Extraction
    print("Loading Silero VAD model (this may take a few seconds on first run)...")
    vad = VADFilter()
    speech_only = vad.extract_speech(continuous_audio, sr)

    if speech_only is not None:
        print(f"[SUCCESS] VAD processed audio and returned array of shape {speech_only.shape}")
    else:
        print("[SUCCESS] VAD pipeline ran without crashing! (Note: It detected no human speech, which is expected since we fed it a pure robotic sine wave tone).")

    # Test 3: Cleanup
    buffer.clear_session(mock_payload["call_id"])
    print("[SUCCESS] Memory buffer successfully cleared.")

except Exception as e:
    print(f"\n[FAILED] Pipeline crashed with error: {e}")
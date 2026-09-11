from fastapi import FastAPI, UploadFile, File, Form, HTTPException
import json
import numpy as np
import soundfile as sf
import io

# Import your Task 2 components
from app.audio.stream_buffer import StreamBuffer
from app.audio.vad_filter import VADFilter
from app.audio.feature_extractor import FeatureExtractor

app = FastAPI()

# Initialize pipeline modules globally to keep models loaded in memory
stream_buffer = StreamBuffer()
vad_filter = VADFilter()
feature_extractor = FeatureExtractor(samplerate=16000)

@app.post("/analyze-audio")
async def analyze_audio_chunk(
    audio: UploadFile = File(...),
    call_id: str = Form(...),
    chunk_id: int = Form(...),
    start_ms: int = Form(...),
    duration_ms: int = Form(...)
):
    try:
        # 1. Read the incoming WAV audio file bytes directly from memory
        audio_bytes = await audio.read()
        
        with io.BytesIO(audio_bytes) as wav_io:
            data, sr = sf.read(wav_io, dtype='float32')

        if len(data.shape) > 1:
            data = data.mean(axis=1) # Convert stereo to mono if needed

        # 2. Simulate or handle payload structure for your StreamBuffer
        mock_payload = {
            "audio_array": data,
            "call_id": call_id,
            "chunk_id": chunk_id,
            "start_ms": start_ms
        }

        # 3. Run Task 2 Pipeline (Buffer -> VAD -> Feature Extraction)
        # Ingest into buffer tracking
        continuous_audio, _ = stream_buffer.ingest_chunk_direct(mock_payload)
        
        # Extract speech and prosody metrics
        clean_audio, prosody_metrics = vad_filter.extract_speech_and_metrics(continuous_audio, samplerate=sr)

        if clean_audio is None:
            feature_matrix_shape = None
            speech_detected = False
            prosody_metrics = {"message": "No active speech detected in this chunk."}
        else:
            speech_detected = True
            # Extract the massive 2D feature matrix (MFCC + F0 + CQT)
            feature_matrix = feature_extractor.extract_and_stack(clean_audio)
            feature_matrix_shape = list(feature_matrix.shape)

            # NOTE: Here is where you hand off `feature_matrix` to Task 3's inference module!
            # e.g., ml_verdict = run_inference(feature_matrix)

        # 4. Construct the comprehensive JSON response
        response_payload = {
            "status": "success",
            "analysis_window": {
                "call_id": call_id,
                "chunk_id": chunk_id,
                "start_ms": start_ms,
                "end_ms": start_ms + duration_ms
            },
            "task_2_preprocessing": {
                "speech_detected": speech_detected,
                "prosody_metrics": prosody_metrics,
                "feature_matrix_shape": feature_matrix_shape
            },
            "task_3_ml_inference": {
                "status": "ready_for_inference",
                "note": "Feature matrix successfully generated and structured."
            }
        }

        # 5. Clean up RAM buffer if call has ended (optional trigger point)
        # stream_buffer.clear_session(call_id)

        return response_payload

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Header  # 1. Import Header
import soundfile as sf
import io

from app.audio.stream_buffer import StreamBuffer
from app.audio.vad_filter import VADFilter
from app.audio.feature_extractor import FeatureExtractor

router = APIRouter(prefix="/api", tags=["Audio Channeling"])

# 2. Define your master API key here
SHARED_API_KEY = "voice_sih_2026_secure_key_99"

stream_buffer = StreamBuffer()
vad_filter = VADFilter()
feature_extractor = FeatureExtractor(samplerate=16000)

@router.post("/analyze-audio")
async def channel_audio_to_ml(
    audio: UploadFile = File(...),
    call_id: str = Form(...),
    chunk_id: int = Form(...),
    start_ms: int = Form(...),
    duration_ms: int = Form(...),
    x_api_key: str = Header(None)  # 3. Capture the incoming header from the requester
):
    # 4. Validate the key before processing any audio
    if x_api_key != SHARED_API_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized: Invalid or missing API key.")

    try:
        # Your existing audio processing code...
        audio_bytes = await audio.read()
        with io.BytesIO(audio_bytes) as wav_io:
            data, sr = sf.read(wav_io, dtype='float32')

        if len(data.shape) > 1:
            data = data.mean(axis=1)

        if call_id not in stream_buffer.active_buffers:
            stream_buffer.active_buffers[call_id] = []
        stream_buffer.active_buffers[call_id].append(data)
        continuous_audio = stream_buffer.active_buffers[call_id][-1]

        clean_audio, prosody_metrics = vad_filter.extract_speech_and_metrics(continuous_audio, samplerate=sr)

        if clean_audio is None:
            return {"status": "filtered", "message": "No active speech detected."}

        feature_matrix = feature_extractor.extract_and_stack(clean_audio)

        return {
            "status": "success",
            "message": "Authenticated and processed successfully.",
            "feature_matrix_shape": list(feature_matrix.shape)
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
from fastapi import (
    APIRouter,
    UploadFile,
    File,
    Form,
    HTTPException,
    Header,
    WebSocket,
    WebSocketDisconnect,
    Query,
)
from typing import Optional
import soundfile as sf
import io
import json
import uuid
import numpy as np

from app.audio.stream_buffer import StreamBuffer
from app.audio.vad_filter import VADFilter
from app.audio.feature_extractor import FeatureExtractor
from app.ml.inference import analyze_voice_authenticity

router = APIRouter(prefix="/api", tags=["Audio Channeling"])

# 2. Define your master API key here
SHARED_API_KEY = "voice_sih_2026_secure_key_99"

stream_buffer = StreamBuffer()
vad_filter = VADFilter()
feature_extractor = FeatureExtractor(samplerate=16000)


async def process_audio_chunk(call_id: str, data: np.ndarray, sr: int):
    if len(data.shape) > 1:
        data = data.mean(axis=1)

    if call_id not in stream_buffer.active_buffers:
        stream_buffer.active_buffers[call_id] = []
    stream_buffer.active_buffers[call_id].append(data)
    continuous_audio = stream_buffer.active_buffers[call_id][-1]

    clean_audio, prosody_metrics = vad_filter.extract_speech_and_metrics(
        continuous_audio, samplerate=sr
    )

    if clean_audio is None:
        return {"status": "filtered", "message": "No active speech detected."}

    feature_matrix = feature_extractor.extract_and_stack(clean_audio)
    ml_result = await analyze_voice_authenticity(clean_audio, sample_rate=sr)

    return {
        "status": "success",
        "message": "Authenticated and processed successfully.",
        "feature_matrix_shape": list(feature_matrix.shape),
        "prosody_metrics": prosody_metrics,
        "ml_inference": ml_result,
    }


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
        audio_bytes = await audio.read()
        with io.BytesIO(audio_bytes) as wav_io:
            data, sr = sf.read(wav_io, dtype="float32")

        return await process_audio_chunk(call_id, data, sr)

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.websocket("/ws/audio")
async def audio_websocket(
    websocket: WebSocket,
    x_api_key: Optional[str] = Query(default=None),
):
    await websocket.accept()

    if x_api_key != SHARED_API_KEY:
        await websocket.send_json(
            {"type": "error", "message": "Unauthorized: Invalid or missing API key."}
        )
        await websocket.close(code=1008)
        return

    call_id = str(uuid.uuid4())
    pending_meta = None
    sample_rate = 16000

    try:
        while True:
            message = await websocket.receive()

            if message["type"] == "websocket.disconnect":
                break

            if "text" in message:
                payload = json.loads(message["text"])
                message_type = payload.get("type")

                if message_type == "start":
                    sample_rate = int(payload.get("sample_rate") or sample_rate)
                    call_id = payload.get("call_id") or call_id
                    pending_meta = None
                    stream_buffer.active_buffers[call_id] = []
                    await websocket.send_json(
                        {
                            "type": "result",
                            "status": "started",
                            "call_id": call_id,
                            "sample_rate": sample_rate,
                        }
                    )
                    continue

                if message_type == "audio":
                    pending_meta = payload
                    continue

                if message_type == "stop":
                    stream_buffer.clear_session(call_id)
                    pending_meta = None
                    await websocket.send_json(
                        {
                            "type": "result",
                            "status": "stopped",
                            "call_id": call_id,
                        }
                    )
                    break

                continue

            if "bytes" in message:
                if pending_meta is None:
                    continue

                meta = pending_meta
                pending_meta = None

                data = np.frombuffer(message["bytes"], dtype="<f4").copy()
                sr = int(meta.get("sample_rate") or sample_rate)

                result = await process_audio_chunk(call_id, data, sr)
                result["type"] = "result"
                result["chunk_id"] = meta.get("chunk_id")
                result["timestamp_ms"] = meta.get("timestamp_ms")
                result["duration_ms"] = meta.get("duration_ms")
                result["call_id"] = call_id

                await websocket.send_json(result)

    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass
    finally:
        stream_buffer.clear_session(call_id)

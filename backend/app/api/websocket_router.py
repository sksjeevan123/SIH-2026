from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
import logging
import json
import numpy as np

from app.audio.feature_extractor import FeatureExtractor
from app.ml.inference import analyze_voice_authenticity

router = APIRouter()
logger = logging.getLogger(__name__)

SECURE_API_KEY = "voice_sih_2026_secure_key_99"

@router.websocket("/api/ws/audio")
async def audio_websocket(
    websocket: WebSocket,
    x_api_key: str = Query(None)
):
    if x_api_key != SECURE_API_KEY:
        await websocket.close(code=4003, reason="Unauthorized API Key")
        logger.warning("Rejected WebSocket connection due to invalid API key.")
        return

    await websocket.accept()
    logger.info("connection open - initializing pipeline components...")

    extractor = FeatureExtractor(samplerate=16000)
    logger.info("Pipeline components ready (VAD bypassed).")

    try:
        # Send initial ready state
        await websocket.send_text(json.dumps({
            "status": "success",
            "ml_inference": {
                "is_ai": False,
                "label": "Ready - Speak Now",
                "risk_score": 0.0
            }
        }))

        while True:
            message = await websocket.receive()
            
            audio_array = None
            if "bytes" in message and message["bytes"]:
                raw_bytes = message["bytes"]
                logger.info(f"Received binary chunk: {len(raw_bytes)} bytes. Forcing analysis...")
                audio_array = np.frombuffer(raw_bytes, dtype=np.int16).astype(np.float32) / 32768.0
            elif "text" in message and message["text"]:
                logger.info(f"Received text message: {message['text']}")
                continue

            if audio_array is None or len(audio_array) == 0:
                continue

            # Bypassed VAD: Send raw audio directly into feature extraction and ML model
            components = extractor.extract_components(audio_array)
            result = await analyze_voice_authenticity(
                audio_array, sample_rate=16000, feature_components=components
            )

            score = float(result.get("risk_score", result.get("score", 0.0)))
            is_ai = score > 32.0
            label = "AI Generated" if is_ai else "Real Human"

            response_payload = {
                "status": "success",
                "ml_inference": {
                    "is_ai": is_ai,
                    "label": label,
                    "risk_score": score
                }
            }

            logger.info(f"Inference complete! Result: {label} (Score: {score})")
            await websocket.send_text(json.dumps(response_payload))

    except WebSocketDisconnect:
        logger.info("connection closed by client")
    except Exception as e:
        logger.error(f"WebSocket error: {str(e)}")
    finally:
        logger.info("WebSocket session terminated.")
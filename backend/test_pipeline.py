from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
import logging
import json
import numpy as np

from app.audio.feature_extractor import FeatureExtractor
from app.ml.inference import analyze_voice_authenticity
from RobustAudioCleaner import RobustAudioCleaner

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
    logger.info("connection open")

    # Initialize components
    cleaner = RobustAudioCleaner(target_samplerate=16000)
    extractor = FeatureExtractor(samplerate=16000)

    try:
        while True:
            # 1. Receive raw PCM16 bytes from Android app chunk stream
            audio_bytes = await websocket.receive_bytes()
            
            # 2. Convert raw PCM16 bytes to numpy float array (matching librosa/audio pipeline input)
            audio_array = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0

            if len(audio_array) == 0:
                continue

            # 3. Run VAD / Audio Cleaner
            clean_audio, prosody = cleaner.clean(audio_array, samplerate=16000)
            if clean_audio is None or len(clean_audio) == 0:
                response_payload = {"status": "filtered"}
                await websocket.send_text(json.dumps(response_payload))
                continue

            # 4. Extract Feature Components
            components = extractor.extract_components(clean_audio)

            # 5. Run ML Inference
            result = await analyze_voice_authenticity(
                clean_audio, sample_rate=16000, feature_components=components
            )

            # Map the result keys to match CallActivity's formatRiskText parser
            # Adjust keys here if your `analyze_voice_authenticity` output keys differ
            score = result.get("risk_score", result.get("score", 0.0))
            level = result.get("risk_level", result.get("level", "LOW"))

            response_payload = {
                "status": "success",
                "ml_inference": {
                    "risk_score": float(score),
                    "risk_level": str(level)
                }
            }

            await websocket.send_text(json.dumps(response_payload))

    except WebSocketDisconnect:
        logger.info("connection closed by client")
    except Exception as e:
        logger.error(f"WebSocket error: {str(e)}")
    finally:
        logger.info("WebSocket session terminated.")
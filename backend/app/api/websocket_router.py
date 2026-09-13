from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
import logging
import json

router = APIRouter()
logger = logging.getLogger(__name__)

# Security API key match configured in your app
SECURE_API_KEY = "voice_sih_2026_secure_key_99"

@router.websocket("/api/ws/audio")
async def audio_websocket(
    websocket: WebSocket,
    x_api_key: str = Query(None)
):
    # 1. Validate API Key
    if x_api_key != SECURE_API_KEY:
        await websocket.close(code=4003, reason="Unauthorized API Key")
        logger.warning("Rejected WebSocket connection due to invalid API key.")
        return

    await websocket.accept()
    logger.info("connection open")

    try:
        while True:
            # 2. Receive binary PCM16 audio chunks streamed from the Android app
            try:
                audio_bytes = await websocket.receive_bytes()
                logger.info(f"Received audio chunk of size: {len(audio_bytes)} bytes")
            except Exception as e:
                # Fallback if text/json frame is sent instead of binary bytes
                text_data = await websocket.receive_text()
                logger.info(f"Received text data: {text_data}")
                continue

            # 3. TODO: Pass 'audio_bytes' to your streamrunner / VAD / feature extractor here.
            # Example integration with your pipeline:
            # result = streamrunner.process_chunk(audio_bytes)

            # 4. Mock/Actual response structure expected by your CallActivity formatRiskText()
            # If speech is filtered out by VAD, return status filtered:
            # response_payload = {"status": "filtered"}
            
            # If inference completes successfully, return the risk score structure:
            response_payload = {
                "status": "success",
                "ml_inference": {
                    "risk_score": 15.5,  # Replace with actual inference value from your ML model
                    "risk_level": "LOW"   # Replace with actual risk category string
                }
            }

            # 5. Send result back to the Android app
            await websocket.send_text(json.dumps(response_payload))

    except WebSocketDisconnect:
        logger.info("connection closed by client")
    except Exception as e:
        logger.error(f"WebSocket error: {str(e)}")
    finally:
        logger.info("WebSocket session terminated.")
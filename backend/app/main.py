from fastapi import FastAPI
from app.api.websocket_router import router

app = FastAPI(title="Voice Anti-Spoofing API")

# Mount your routing channel
app.include_router(router)
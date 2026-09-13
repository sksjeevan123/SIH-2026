from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.websocket_router import router  # Changed back to app.api

app = FastAPI(title="Voice Anti-Spoofing API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)
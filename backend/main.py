import asyncio
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api.jobs import router as jobs_router
from api.transcripts import router as transcripts_router
from api.speakers import router as speakers_router
from api.audio import router as audio_router
from api.stats import router as stats_router
from api.semantic import router as semantic_router
from api.settings import router as settings_router
from api.search import router as search_router

app = FastAPI(title="VoiceStack3", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(jobs_router)
app.include_router(transcripts_router)
app.include_router(speakers_router)
app.include_router(audio_router)
app.include_router(stats_router)
app.include_router(semantic_router)
app.include_router(settings_router)
app.include_router(search_router)


# Shutdown event that SSE streams check
shutdown_event = asyncio.Event()


@app.on_event("startup")
async def startup():
    from services.file_watcher import start_watcher
    start_watcher()


@app.on_event("shutdown")
async def shutdown():
    shutdown_event.set()


@app.get("/health")
async def health():
    return {"status": "ok", "version": "0.1.0"}

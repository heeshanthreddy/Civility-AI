"""
main.py — FastAPI entry point for Civility.ai
Wires HTTP endpoints to the Gemini moderation logic from
chatbot_moderation_gemini_new_2.py (Station-S / Agentia 2.0).
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware

from core import ModerationDB, SessionStats, get_client
from services.text_moderation import analyze_text
from services.image_moderation import analyze_image
from services.video_moderation import analyze_video
from services.voice_moderation import analyze_voice
from services.decision import verdict_to_status, verdict_to_confidence

import uvicorn

app = FastAPI(title="Civility.ai API — Gemini Edition", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Shared DB instance (fire-and-forget; won't crash if MySQL is absent)
db    = ModerationDB()
stats = SessionStats()
db.open_session()


def _build_response(result, filename: str = None) -> dict:
    """Converts a ModerationResult into the JSON shape the frontend expects."""
    top_cat, top_prob = result.scores.top_category()
    return {
        "content_type":    result.content_type.capitalize(),
        "status":          verdict_to_status(result.verdict),
        "verdict":         result.verdict,                          # raw: safe/warn/block
        "category":        top_cat.replace("_", " ").title(),
        "confidence":      verdict_to_confidence(result.scores),
        "reason":          result.reason,
        "detail":          result.detail or "",
        "blocked_by_api":  result.blocked_by_api,
        "scores": result.scores.as_dict(),                         # per-category breakdown
        **({"filename": filename} if filename else {}),
    }


@app.get("/")
def root():
    return {"message": "Civility.ai Moderation API — Gemini 2.0 Flash", "status": "running"}


@app.post("/moderate/text")
def moderate_text_endpoint(text: str = Form(...)):
    result = analyze_text(text)

    # Update stats + DB
    stats.total += 1
    setattr(stats, result.verdict, getattr(stats, result.verdict) + 1)
    stats.texts += 1
    db.log_event(result, text)

    return _build_response(result)


@app.post("/moderate/image")
async def moderate_image_endpoint(file: UploadFile = File(...)):
    content = await file.read()
    result  = analyze_image(content, file.filename)

    stats.total  += 1
    setattr(stats, result.verdict, getattr(stats, result.verdict) + 1)
    stats.images += 1
    db.log_event(result, file.filename)

    return _build_response(result, filename=file.filename)


@app.post("/moderate/video")
async def moderate_video_endpoint(file: UploadFile = File(...)):
    content = await file.read()
    result  = analyze_video(content, file.filename)

    stats.total  += 1
    setattr(stats, result.verdict, getattr(stats, result.verdict) + 1)
    stats.videos += 1
    db.log_event(result, file.filename)

    return _build_response(result, filename=file.filename)


@app.get("/stats")
def get_stats():
    """Returns current session moderation statistics."""
    rate = (stats.block / stats.total * 100) if stats.total else 0
    return {
        "total":       stats.total,
        "safe":        stats.safe,
        "warned":      stats.warn,
        "blocked":     stats.block,
        "block_rate":  round(rate, 1),
        "by_type": {
            "text":  stats.texts,
            "image": stats.images,
            "video": stats.videos,
            "voice": stats.voices,
        },
        "session_id": db.session_id,
    }


@app.post("/moderate/voice")
async def moderate_voice_endpoint(file: UploadFile = File(...)):
    content = await file.read()
    result  = analyze_voice(content, file.filename)

    stats.total  += 1
    setattr(stats, result.verdict, getattr(stats, result.verdict) + 1)
    stats.voices += 1
    db.log_event(result, file.filename)

    return _build_response(result, filename=file.filename)


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)

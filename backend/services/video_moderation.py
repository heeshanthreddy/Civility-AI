"""
video_moderation.py
Maps directly to moderate_video() from chatbot_moderation_gemini_new_2.py
Accepts raw bytes + filename (for FastAPI) instead of a file path.
"""

import json
import tempfile
import os
from pathlib import Path

from core import (
    get_client, GEMINI_MODEL, VIDEO_EXTENSIONS, MAX_VIDEO_FRAMES, PROB_RANK,
    ModerationResult, ModerationScores,
    _safety_off, _parse_safety_ratings, _verdict_from_scores, _call_with_retry
)
from utils.video_utils import extract_frames

# Same structured prompt from the original file
_VIDEO_MODERATION_PROMPT = """\
You are a strict content moderation system. You have been given {n} evenly-sampled
frames from a video. Analyze ALL frames collectively and respond ONLY in this exact
JSON format (no markdown fences, no extra text):

{{
  "harassment": "NEGLIGIBLE|LOW|MEDIUM|HIGH",
  "hate_speech": "NEGLIGIBLE|LOW|MEDIUM|HIGH",
  "sexually_explicit": "NEGLIGIBLE|LOW|MEDIUM|HIGH",
  "dangerous_content": "NEGLIGIBLE|LOW|MEDIUM|HIGH",
  "summary": "one-sentence description of the video content"
}}

Base your ratings on the most severe content found across any frame.
Be conservative — flag anything that could be harmful.
"""


def analyze_video(content: bytes, filename: str) -> ModerationResult:
    """
    Accepts raw video bytes + filename from FastAPI UploadFile.
    Saves to temp file, extracts frames, sends to Gemini Vision.
    Replicates moderate_video() logic from the original chatbot file.
    """
    from google.genai import types

    ext = Path(filename).suffix.lower()

    if ext not in VIDEO_EXTENSIONS:
        return ModerationResult(
            scores=ModerationScores(), verdict="block",
            reason=f"Unsupported video format: {ext}. Supported: {VIDEO_EXTENSIONS}",
            blocked_by_api=False, content_type="video"
        )

    # Write bytes to temp file so OpenCV can read it
    with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        frames = extract_frames(tmp_path, MAX_VIDEO_FRAMES)
    except Exception as e:
        os.unlink(tmp_path)
        return ModerationResult(
            scores=ModerationScores(), verdict="warn",
            reason=f"Could not extract frames: {e}",
            blocked_by_api=False, content_type="video"
        )
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass

    if not frames:
        return ModerationResult(
            scores=ModerationScores(), verdict="warn",
            reason="No frames could be extracted from the video.",
            blocked_by_api=False, content_type="video"
        )

    n = len(frames)

    try:
        # Build multi-part content: all frames + prompt (same as original)
        parts = [
            types.Part.from_bytes(data=frame_bytes, mime_type="image/jpeg")
            for frame_bytes in frames
        ]
        parts.append(_VIDEO_MODERATION_PROMPT.format(n=n))

        def _call():
            return get_client().models.generate_content(
                model=GEMINI_MODEL,
                contents=parts,
                config=types.GenerateContentConfig(safety_settings=_safety_off())
            )

        response               = _call_with_retry(_call)
        scores, blocked_by_api = _parse_safety_ratings(response)
        detail                 = ""

        if response.candidates and response.candidates[0].content.parts:
            raw_text = response.candidates[0].content.parts[0].text.strip()
            try:
                parsed = json.loads(raw_text)
                for field_name in ("harassment", "hate_speech", "sexually_explicit", "dangerous_content"):
                    value = parsed.get(field_name, "NEGLIGIBLE").upper()
                    if value in PROB_RANK:
                        setattr(scores, field_name, value)
                detail = parsed.get("summary", "")
            except json.JSONDecodeError:
                detail = raw_text[:120]

        top_cat, top_prob = scores.top_category()
        top_label         = top_cat.replace("_", " ").title()
        verdict, reason   = _verdict_from_scores(scores, blocked_by_api, top_label, top_prob)

        return ModerationResult(
            scores=scores, verdict=verdict, reason=reason,
            blocked_by_api=blocked_by_api, content_type="video",
            detail=f"[{n} frames sampled] {detail}"
        )

    except Exception as e:
        return ModerationResult(
            scores=ModerationScores(), verdict="warn",
            reason=f"Video moderation API error — proceeding with caution ({e})",
            blocked_by_api=False, content_type="video"
        )

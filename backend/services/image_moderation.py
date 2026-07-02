"""
image_moderation.py
Maps directly to moderate_image() from chatbot_moderation_gemini_new_2.py
Accepts raw bytes + filename (for FastAPI) instead of a file path.
"""

import json
import base64
from pathlib import Path

from core import (
    get_client, GEMINI_MODEL, IMAGE_EXTENSIONS, PROB_RANK,
    ModerationResult, ModerationScores,
    _safety_off, _parse_safety_ratings, _verdict_from_scores, _call_with_retry
)

# Same structured prompt from the original file
_IMAGE_MODERATION_PROMPT = """\
You are a strict content moderation system. Analyze the image and respond ONLY in
this exact JSON format (no markdown fences, no extra text):

{
  "harassment": "NEGLIGIBLE|LOW|MEDIUM|HIGH",
  "hate_speech": "NEGLIGIBLE|LOW|MEDIUM|HIGH",
  "sexually_explicit": "NEGLIGIBLE|LOW|MEDIUM|HIGH",
  "dangerous_content": "NEGLIGIBLE|LOW|MEDIUM|HIGH",
  "summary": "one-sentence description of what the image contains"
}

Be accurate and conservative. Flag anything that could be harmful.
"""

MIME_MAP = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
    ".gif": "image/gif",  ".webp": "image/webp", ".bmp": "image/bmp",
}


def analyze_image(content: bytes, filename: str) -> ModerationResult:
    """
    Accepts raw image bytes + filename from FastAPI UploadFile.
    Replicates moderate_image() logic from the original chatbot file.
    """
    from google.genai import types

    ext = Path(filename).suffix.lower()

    if ext not in IMAGE_EXTENSIONS:
        return ModerationResult(
            scores=ModerationScores(), verdict="block",
            reason=f"Unsupported image format: {ext}. Supported: {IMAGE_EXTENSIONS}",
            blocked_by_api=False, content_type="image"
        )

    mime_type  = MIME_MAP.get(ext, "image/jpeg")
    image_part = types.Part.from_bytes(data=content, mime_type=mime_type)

    try:
        def _call():
            return get_client().models.generate_content(
                model=GEMINI_MODEL,
                contents=[image_part, _IMAGE_MODERATION_PROMPT],
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
            blocked_by_api=blocked_by_api, content_type="image", detail=detail
        )

    except Exception as e:
        return ModerationResult(
            scores=ModerationScores(), verdict="warn",
            reason=f"Image moderation API error — proceeding with caution ({e})",
            blocked_by_api=False, content_type="image"
        )

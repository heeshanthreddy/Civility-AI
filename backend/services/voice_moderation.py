"""
voice_moderation.py
Transcribes uploaded audio via Gemini's multimodal API, then runs the
transcript through the standard text moderation pipeline.

Supported formats: mp3, wav, ogg, webm, m4a, flac
"""

import io
from core import (
    get_client, GEMINI_MODEL, ModerationResult, ModerationScores,
    _safety_off, _parse_safety_ratings, _verdict_from_scores, _call_with_retry
)

AUDIO_MIME_MAP = {
    ".mp3":  "audio/mpeg",
    ".wav":  "audio/wav",
    ".ogg":  "audio/ogg",
    ".webm": "audio/webm",
    ".m4a":  "audio/mp4",
    ".flac": "audio/flac",
}

_TRANSCRIBE_PROMPT = (
    "Transcribe this audio exactly as spoken. "
    "Return ONLY the transcript text — no labels, no timestamps, no explanations."
)

_MODERATE_PROMPT = (
    "You are a strict content moderation system. Analyze this spoken transcript "
    "and respond ONLY in this exact JSON format (no markdown, no extra text):\n\n"
    "{{\n"
    '  "harassment": "NEGLIGIBLE|LOW|MEDIUM|HIGH",\n'
    '  "hate_speech": "NEGLIGIBLE|LOW|MEDIUM|HIGH",\n'
    '  "sexually_explicit": "NEGLIGIBLE|LOW|MEDIUM|HIGH",\n'
    '  "dangerous_content": "NEGLIGIBLE|LOW|MEDIUM|HIGH",\n'
    '  "transcript": "<the full transcript>",\n'
    '  "summary": "one-sentence description of what was said"\n'
    "}}\n\n"
    "Transcript to analyze:\n{transcript}"
)


def _ext(filename: str) -> str:
    import os
    return os.path.splitext(filename or "")[-1].lower()


def analyze_voice(audio_bytes: bytes, filename: str) -> ModerationResult:
    """
    Two-step pipeline:
      1. Send raw audio to Gemini → get transcript
      2. Moderate the transcript text → ModerationResult

    Falls back gracefully if transcription fails.
    """
    import json
    from google.genai import types

    mime_type = AUDIO_MIME_MAP.get(_ext(filename), "audio/webm")

    # ── Step 1: Transcribe ────────────────────────────────────────────
    transcript = ""
    try:
        audio_part = types.Part.from_bytes(data=audio_bytes, mime_type=mime_type)

        def _transcribe():
            return get_client().models.generate_content(
                model=GEMINI_MODEL,
                contents=[audio_part, _TRANSCRIBE_PROMPT],
                config=types.GenerateContentConfig(safety_settings=_safety_off())
            )

        t_resp = _call_with_retry(_transcribe)
        if t_resp.candidates and t_resp.candidates[0].content.parts:
            transcript = t_resp.candidates[0].content.parts[0].text.strip()

    except Exception as e:
        return ModerationResult(
            scores=ModerationScores(), verdict="warn",
            reason=f"Audio transcription failed: {e}",
            blocked_by_api=False, content_type="voice",
            detail=""
        )

    if not transcript:
        return ModerationResult(
            scores=ModerationScores(), verdict="safe",
            reason="No speech detected in audio",
            blocked_by_api=False, content_type="voice",
            detail="[empty transcript]"
        )

    # ── Step 2: Moderate transcript ───────────────────────────────────
    try:
        prompt = _MODERATE_PROMPT.format(transcript=transcript)

        def _moderate():
            return get_client().models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(safety_settings=_safety_off())
            )

        m_resp                 = _call_with_retry(_moderate)
        scores, blocked_by_api = _parse_safety_ratings(m_resp)
        detail                 = transcript  # default detail = transcript

        if m_resp.candidates and m_resp.candidates[0].content.parts:
            raw = m_resp.candidates[0].content.parts[0].text.strip()
            try:
                parsed = json.loads(raw)
                for field in ("harassment", "hate_speech", "sexually_explicit", "dangerous_content"):
                    val = parsed.get(field, "NEGLIGIBLE").upper()
                    if val in ("NEGLIGIBLE", "LOW", "MEDIUM", "HIGH"):
                        setattr(scores, field, val)
                # prefer the structured transcript/summary for detail
                detail = parsed.get("transcript", transcript)
                if parsed.get("summary"):
                    detail = f"{parsed['summary']} | Transcript: {detail}"
            except json.JSONDecodeError:
                pass

        top_cat, top_prob = scores.top_category()
        top_label         = top_cat.replace("_", " ").title()
        verdict, reason   = _verdict_from_scores(scores, blocked_by_api, top_label, top_prob)

        return ModerationResult(
            scores=scores, verdict=verdict, reason=reason,
            blocked_by_api=blocked_by_api, content_type="voice",
            detail=detail
        )

    except Exception as e:
        return ModerationResult(
            scores=ModerationScores(), verdict="warn",
            reason=f"Voice moderation error: {e}",
            blocked_by_api=False, content_type="voice",
            detail=transcript
        )

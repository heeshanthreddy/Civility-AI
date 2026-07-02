"""
text_moderation.py
Maps directly to moderate_text() from chatbot_moderation_gemini_new_2.py
"""

from core import (
    get_client, GEMINI_MODEL, ModerationResult, ModerationScores,
    _safety_off, _parse_safety_ratings, _verdict_from_scores, _call_with_retry
)


def analyze_text(text: str) -> ModerationResult:
    """
    Sends text to Gemini with ALL safety filters OFF to get raw safety_ratings.
    Applies BLOCK / WARN / SAFE verdict logic on top.
    Identical logic to moderate_text() in the original chatbot file.
    """
    from google.genai import types

    try:
        probe = f"Analyze this message and respond briefly: {text}"

        def _call():
            return get_client().models.generate_content(
                model=GEMINI_MODEL,
                contents=probe,
                config=types.GenerateContentConfig(safety_settings=_safety_off())
            )

        response               = _call_with_retry(_call)
        scores, blocked_by_api = _parse_safety_ratings(response)
        top_cat, top_prob      = scores.top_category()
        top_label              = top_cat.replace("_", " ").title()
        verdict, reason        = _verdict_from_scores(scores, blocked_by_api, top_label, top_prob)

        return ModerationResult(
            scores=scores, verdict=verdict, reason=reason,
            blocked_by_api=blocked_by_api, content_type="text"
        )

    except Exception as e:
        return ModerationResult(
            scores=ModerationScores(), verdict="warn",
            reason=f"Moderation API error — proceeding with caution ({e})",
            blocked_by_api=False, content_type="text"
        )

"""
decision.py
Converts the ModerationResult verdict ("safe" / "warn" / "block")
into a human-readable status string for the API response.
Verdict logic itself lives in core._verdict_from_scores() — unchanged from original.
"""


def verdict_to_status(verdict: str) -> str:
    """
    Maps Gemini verdict → display status shown in frontend.
      safe  → Approved
      warn  → Flagged for Review
      block → Rejected
    """
    return {
        "safe":  "Approved",
        "warn":  "Flagged for Review",
        "block": "Rejected",
    }.get(verdict, "Flagged for Review")


def verdict_to_confidence(scores) -> int:
    """
    Converts ModerationScores into a 0-100 confidence integer for the frontend meter.
    Maps max PROB_RANK to a percentage band:
      NEGLIGIBLE (0) → 5%
      LOW        (1) → 25%
      MEDIUM     (2) → 60%
      HIGH       (3) → 92%
    """
    RANK_TO_SCORE = {0: 5, 1: 25, 2: 60, 3: 92}
    from core import PROB_RANK
    max_rank = max(PROB_RANK.get(v, 0) for v in scores.as_dict().values())
    return RANK_TO_SCORE.get(max_rank, 5)

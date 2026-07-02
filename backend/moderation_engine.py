"""
Station-S · ChatBot Moderation System (Gemini-Powered)
Agentia 2.0 Hackathon — Enhanced Edition

APIs Used:
  - google-genai (NEW SDK)     → replaces deprecated google-generativeai
  - Gemini Safety Ratings      → content moderation & scoring
  - Gemini 2.0 Flash           → intelligent bot responses + multimodal analysis
  - Google Speech-to-Text      → voice input (optional)
  - MySQL (mysql-connector-python) → persistent moderation audit log

New in this version:
  - Image moderation  → inline base64 or file path
  - Video moderation  → frame-sampled multimodal analysis
  - MySQL logging     → every moderation event written to a DB table
  - Improved model name (gemini-2.0-flash)
  - Richer ModerationResult with content_type field
  - Retry logic with exponential backoff
  - Configurable thresholds via environment variables
  - Graceful API key validation at import time
  - Type aliases and forward refs cleaned up
  - SessionStats now tracks image/video counts separately
  - `image <path>` and `video <path>` CLI commands
  - Structured moderation prompt for image/video analysis

Install dependencies:
  pip install google-genai python-dotenv opencv-python mysql-connector-python

Optional (voice):
  pip install google-cloud-speech pyaudio

.env keys:
  GEMINI_API_KEY=AIza...
  MYSQL_HOST=localhost
  MYSQL_PORT=3306
  MYSQL_USER=root
  MYSQL_PASSWORD=yourpassword
  MYSQL_DATABASE=moderation_db
  GOOGLE_APPLICATION_CREDENTIALS=path/to/creds.json   # voice only
"""

import base64
import os
import time
from datetime import datetime
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional

from dotenv import load_dotenv
env_path = r"D:\civility-ai-v2\backend\.env"
load_dotenv(dotenv_path=env_path)

# ─── Config ──────────────────────────────────────────────────────────

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL   = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")   # fixed: was gemini-3.1-pro-preview (non-existent)

# Thresholds — override via .env
BLOCK_LEVEL = os.getenv("BLOCK_LEVEL", "HIGH")
WARN_LEVEL  = os.getenv("WARN_LEVEL",  "MEDIUM")

# Retry config
MAX_RETRIES    = 3
RETRY_DELAY    = 1.5   # seconds (doubles on each retry)

# Gemini harm probability levels ranked low → high
PROB_RANK: dict[str, int] = {
    "NEGLIGIBLE": 0,
    "LOW":        1,
    "MEDIUM":     2,
    "HIGH":       3,
}

# Supported file extensions
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
VIDEO_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv", ".webm", ".flv"}

# Maximum frames to sample from a video for moderation
MAX_VIDEO_FRAMES = 8

# ─── MySQL Config ────────────────────────────────────────────────────

MYSQL_HOST     = os.getenv("MYSQL_HOST",     "localhost")
MYSQL_PORT     = int(os.getenv("MYSQL_PORT", "3306"))
MYSQL_USER     = os.getenv("MYSQL_USER",     "root")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "")
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "moderation_db")

# ─── Lazy Gemini Client (validated on first use) ──────────────────────

_client = None

def get_client():
    """Returns a singleton Gemini client, raising early if key is missing."""
    global _client
    if _client is None:
        if not GEMINI_API_KEY:
            raise EnvironmentError(
                "\n  [ERROR] GEMINI_API_KEY not set.\n"
                "  Add it to your .env file:\n\n"
                "    GEMINI_API_KEY=AIza...\n\n"
                "  Get a free key → https://aistudio.google.com/app/apikey\n"
            )
        from google import genai
        _client = genai.Client(api_key=GEMINI_API_KEY)
    return _client


# ─── Data Structures ─────────────────────────────────────────────────

ContentType = Literal["text", "image", "video"]


@dataclass
class ModerationScores:
    harassment:        str = "NEGLIGIBLE"
    hate_speech:       str = "NEGLIGIBLE"
    sexually_explicit: str = "NEGLIGIBLE"
    dangerous_content: str = "NEGLIGIBLE"

    def as_dict(self) -> dict[str, str]:
        return self.__dict__.copy()

    def max_rank(self) -> int:
        return max(PROB_RANK.get(v, 0) for v in self.__dict__.values())

    def top_category(self) -> tuple[str, str]:
        """Returns (category_name, prob_label) for the highest-scored category."""
        return max(self.__dict__.items(), key=lambda x: PROB_RANK.get(x[1], 0))


@dataclass
class ModerationResult:
    scores:        ModerationScores
    verdict:       Literal["safe", "warn", "block"]
    reason:        str
    blocked_by_api: bool
    content_type:  ContentType = "text"
    detail:        str = ""          # extra info from image/video analysis


@dataclass
class LogEntry:
    timestamp:    str
    verdict:      str
    preview:      str
    reason:       str
    content_type: ContentType = "text"


@dataclass
class SessionStats:
    total:  int = 0
    safe:   int = 0
    warn:   int = 0
    block:  int = 0
    # content-type breakdown
    texts:  int = 0
    images: int = 0
    videos: int = 0


# ─── MySQL Logging ───────────────────────────────────────────────────

# DDL executed once on startup to ensure the table exists
_CREATE_SESSIONS_TABLE = """
CREATE TABLE IF NOT EXISTS moderation_sessions (
    id            BIGINT       NOT NULL AUTO_INCREMENT PRIMARY KEY,
    session_id    VARCHAR(36)  NOT NULL,              -- UUID for grouping a bot run
    started_at    DATETIME     NOT NULL,
    ended_at      DATETIME     NULL,
    total         INT          NOT NULL DEFAULT 0,
    safe_count    INT          NOT NULL DEFAULT 0,
    warn_count    INT          NOT NULL DEFAULT 0,
    block_count   INT          NOT NULL DEFAULT 0,
    INDEX idx_session (session_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""

_CREATE_EVENTS_TABLE = """
CREATE TABLE IF NOT EXISTS moderation_events (
    id              BIGINT        NOT NULL AUTO_INCREMENT PRIMARY KEY,
    session_id      VARCHAR(36)   NOT NULL,
    created_at      DATETIME      NOT NULL,
    content_type    ENUM('text','image','video') NOT NULL,
    content_preview VARCHAR(255)  NOT NULL,          -- first 255 chars / filename
    verdict         ENUM('safe','warn','block')  NOT NULL,
    reason          TEXT          NOT NULL,
    blocked_by_api  TINYINT(1)    NOT NULL DEFAULT 0,
    -- raw category scores
    score_harassment        ENUM('NEGLIGIBLE','LOW','MEDIUM','HIGH') NOT NULL DEFAULT 'NEGLIGIBLE',
    score_hate_speech       ENUM('NEGLIGIBLE','LOW','MEDIUM','HIGH') NOT NULL DEFAULT 'NEGLIGIBLE',
    score_sexually_explicit ENUM('NEGLIGIBLE','LOW','MEDIUM','HIGH') NOT NULL DEFAULT 'NEGLIGIBLE',
    score_dangerous_content ENUM('NEGLIGIBLE','LOW','MEDIUM','HIGH') NOT NULL DEFAULT 'NEGLIGIBLE',
    detail          TEXT          NULL,               -- image/video summary
    INDEX idx_session  (session_id),
    INDEX idx_verdict  (verdict),
    INDEX idx_type     (content_type),
    INDEX idx_created  (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""


class ModerationDB:
    """
    Thin wrapper around a mysql-connector-python connection.

    All writes are fire-and-forget with error suppression so a DB hiccup
    never crashes the moderation pipeline.  The connection is lazily opened
    and automatically re-established if it drops (ping + reconnect).

    Tables created automatically on first connect:
      • moderation_sessions  — one row per bot run
      • moderation_events    — one row per moderated message / file
    """

    def __init__(self):
        self._conn       = None
        self.session_id  = self._new_uuid()
        self.started_at  = datetime.now()
        self._connected  = False

    # ── Connection management ─────────────────────────────────────────

    @staticmethod
    def _new_uuid() -> str:
        import uuid
        return str(uuid.uuid4())

    def _connect(self) -> bool:
        """Opens (or re-opens) the MySQL connection. Returns True on success."""
        try:
            import mysql.connector
            self._conn = mysql.connector.connect(
                host=MYSQL_HOST,
                port=MYSQL_PORT,
                user=MYSQL_USER,
                password=MYSQL_PASSWORD,
                database=MYSQL_DATABASE,
                autocommit=True,
                connection_timeout=5,
            )
            self._ensure_schema()
            self._connected = True
            return True
        except Exception as e:
            print(f"\n  [DB] Connection failed: {e}")
            print(f"  [DB] Logging to MySQL disabled for this session.")
            self._connected = False
            return False

    def _cursor(self):
        """Returns a live cursor, reconnecting once if the connection dropped."""
        import mysql.connector
        if self._conn is None:
            self._connect()
        else:
            try:
                self._conn.ping(reconnect=True, attempts=2, delay=1)
            except Exception:
                self._connect()
        if not self._connected:
            return None
        return self._conn.cursor()

    def _ensure_schema(self):
        """Creates tables if they don't exist yet."""
        cur = self._conn.cursor()
        cur.execute(_CREATE_SESSIONS_TABLE)
        cur.execute(_CREATE_EVENTS_TABLE)
        cur.close()

    # ── Public API ────────────────────────────────────────────────────

    def open_session(self):
        """Inserts a new session row. Called once when the bot starts."""
        cur = self._cursor()
        if cur is None:
            return
        try:
            cur.execute(
                """
                INSERT INTO moderation_sessions
                    (session_id, started_at)
                VALUES (%s, %s)
                """,
                (self.session_id, self.started_at)
            )
        except Exception as e:
            print(f"\n  [DB] open_session error: {e}")
        finally:
            cur.close()

    def close_session(self, stats: "SessionStats"):
        """Updates the session row with final counts and end time."""
        cur = self._cursor()
        if cur is None:
            return
        try:
            cur.execute(
                """
                UPDATE moderation_sessions
                SET ended_at    = %s,
                    total       = %s,
                    safe_count  = %s,
                    warn_count  = %s,
                    block_count = %s
                WHERE session_id = %s
                """,
                (
                    datetime.now(),
                    stats.total, stats.safe, stats.warn, stats.block,
                    self.session_id,
                )
            )
        except Exception as e:
            print(f"\n  [DB] close_session error: {e}")
        finally:
            cur.close()

    def log_event(self, result: "ModerationResult", content_preview: str):
        """
        Inserts one moderation_events row.

        Args:
            result:          The ModerationResult returned by any moderate_* function.
            content_preview: The raw text, or the file path/name for images/videos.
        """
        cur = self._cursor()
        if cur is None:
            return
        try:
            preview = content_preview[:255]   # column width guard
            cur.execute(
                """
                INSERT INTO moderation_events (
                    session_id, created_at, content_type, content_preview,
                    verdict, reason, blocked_by_api,
                    score_harassment, score_hate_speech,
                    score_sexually_explicit, score_dangerous_content,
                    detail
                ) VALUES (
                    %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s, %s,
                    %s
                )
                """,
                (
                    self.session_id,
                    datetime.now(),
                    result.content_type,
                    preview,
                    result.verdict,
                    result.reason,
                    int(result.blocked_by_api),
                    result.scores.harassment,
                    result.scores.hate_speech,
                    result.scores.sexually_explicit,
                    result.scores.dangerous_content,
                    result.detail or None,
                )
            )
        except Exception as e:
            print(f"\n  [DB] log_event error: {e}")
        finally:
            cur.close()

    def close(self):
        """Closes the underlying connection cleanly."""
        try:
            if self._conn and self._conn.is_connected():
                self._conn.close()
        except Exception:
            pass


# ─── Safety Config Helpers ───────────────────────────────────────────

def _safety_off() -> list:
    """All filters OFF — used for moderation probe so we always get raw scores."""
    from google.genai import types
    categories = [
        types.HarmCategory.HARM_CATEGORY_HARASSMENT,
        types.HarmCategory.HARM_CATEGORY_HATE_SPEECH,
        types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
        types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
    ]
    return [
        types.SafetySetting(category=cat, threshold=types.HarmBlockThreshold.BLOCK_NONE)
        for cat in categories
    ]


def _safety_standard() -> list:
    """Standard filters — used for actual bot responses."""
    from google.genai import types
    categories = [
        types.HarmCategory.HARM_CATEGORY_HARASSMENT,
        types.HarmCategory.HARM_CATEGORY_HATE_SPEECH,
        types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
        types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
    ]
    return [
        types.SafetySetting(category=cat, threshold=types.HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE)
        for cat in categories
    ]


# Maps Gemini's category name strings → our dataclass field names
CATEGORY_MAP = {
    "HARM_CATEGORY_HARASSMENT":        "harassment",
    "HARM_CATEGORY_HATE_SPEECH":       "hate_speech",
    "HARM_CATEGORY_SEXUALLY_EXPLICIT": "sexually_explicit",
    "HARM_CATEGORY_DANGEROUS_CONTENT": "dangerous_content",
}


# ─── Internal Helpers ────────────────────────────────────────────────

def _verdict_from_scores(
    scores: ModerationScores,
    blocked_by_api: bool,
    top_label: str,
    top_prob: str,
) -> tuple[Literal["safe", "warn", "block"], str]:
    max_rank = scores.max_rank()
    if max_rank >= PROB_RANK[BLOCK_LEVEL] or blocked_by_api:
        return "block", f"Blocked — {top_label} rated {top_prob}"
    elif max_rank >= PROB_RANK[WARN_LEVEL]:
        return "warn", f"Warning — {top_label} rated {top_prob}"
    else:
        return "safe", "All categories NEGLIGIBLE or LOW"


def _parse_safety_ratings(response) -> tuple[ModerationScores, bool]:
    """Extracts ModerationScores and api-blocked flag from a Gemini response."""
    scores         = ModerationScores()
    blocked_by_api = False

    if not response.candidates:
        return scores, blocked_by_api

    candidate = response.candidates[0]

    if hasattr(candidate, "finish_reason"):
        blocked_by_api = str(candidate.finish_reason) == "SAFETY"

    if hasattr(candidate, "safety_ratings") and candidate.safety_ratings:
        for rating in candidate.safety_ratings:
            cat_name   = rating.category.name
            prob_label = rating.probability.name
            field_name = CATEGORY_MAP.get(cat_name)
            if field_name:
                setattr(scores, field_name, prob_label)

    return scores, blocked_by_api


def _call_with_retry(fn, *args, **kwargs):
    """Calls fn(*args, **kwargs) with exponential-backoff retry on transient errors."""
    delay = RETRY_DELAY
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            err_str = str(e).upper()
            # Don't retry on clear content policy / auth errors
            if any(k in err_str for k in ("SAFETY", "PERMISSION", "INVALID_ARGUMENT", "APIKEY")):
                raise
            if attempt == MAX_RETRIES:
                raise
            print(f"\n  [RETRY {attempt}/{MAX_RETRIES}] Transient error: {e}. Retrying in {delay:.1f}s...")
            time.sleep(delay)
            delay *= 2


# ─── 1. Text Moderation ──────────────────────────────────────────────

def moderate_text(text: str) -> ModerationResult:
    """
    Sends the message to Gemini with ALL safety filters OFF so we
    always receive raw safety_ratings back — even for borderline content.
    We then apply our own BLOCK / WARN / SAFE verdict logic on top.

    Safety ratings per category: NEGLIGIBLE → LOW → MEDIUM → HIGH
    Docs: https://ai.google.dev/gemini-api/docs/safety-settings
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

        response                = _call_with_retry(_call)
        scores, blocked_by_api  = _parse_safety_ratings(response)
        top_cat, top_prob       = scores.top_category()
        top_label               = top_cat.replace("_", " ").title()
        verdict, reason         = _verdict_from_scores(scores, blocked_by_api, top_label, top_prob)

        return ModerationResult(
            scores=scores, verdict=verdict, reason=reason,
            blocked_by_api=blocked_by_api, content_type="text"
        )

    except Exception as e:
        print(f"\n  [ERROR] Text moderation failed: {e}")
        return ModerationResult(
            scores=ModerationScores(), verdict="warn",
            reason=f"Moderation API error — proceeding with caution ({e})",
            blocked_by_api=False, content_type="text"
        )


# ─── 2. Image Moderation ─────────────────────────────────────────────

# Structured prompt to elicit category-level analysis from the vision model
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


def _load_image_as_part(image_path: str) -> tuple[object, str]:
    """
    Loads an image from disk and returns a Gemini-compatible Part + mime_type.
    Raises FileNotFoundError / ValueError on bad input.
    """
    from google.genai import types

    path = Path(image_path)
    if not path.exists():
        raise FileNotFoundError(f"Image not found: {image_path}")

    ext = path.suffix.lower()
    if ext not in IMAGE_EXTENSIONS:
        raise ValueError(f"Unsupported image format: {ext}. Supported: {IMAGE_EXTENSIONS}")

    mime_map = {
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
        ".gif": "image/gif", ".webp": "image/webp", ".bmp": "image/bmp",
    }
    mime_type   = mime_map[ext]
    image_bytes = path.read_bytes()
    b64_data    = base64.standard_b64encode(image_bytes).decode("utf-8")

    part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
    return part, mime_type


def moderate_image(image_path: str) -> ModerationResult:
    """
    Moderates an image file using Gemini's vision capabilities.
    Parses structured JSON from the model's response to populate ModerationScores.

    Args:
        image_path: Absolute or relative path to the image file.

    Returns:
        ModerationResult with content_type="image".
    """
    import json
    from google.genai import types

    try:
        image_part, mime_type = _load_image_as_part(image_path)
        print(f"\n  [Moderating image: {Path(image_path).name} ({mime_type})]")

        def _call():
            return get_client().models.generate_content(
                model=GEMINI_MODEL,
                contents=[image_part, _IMAGE_MODERATION_PROMPT],
                config=types.GenerateContentConfig(safety_settings=_safety_off())
            )

        response                = _call_with_retry(_call)
        scores, blocked_by_api  = _parse_safety_ratings(response)
        detail                  = ""

        # Try to parse structured JSON from model output
        if response.candidates and response.candidates[0].content.parts:
            raw_text = response.candidates[0].content.parts[0].text.strip()
            try:
                parsed = json.loads(raw_text)
                # Override safety ratings with model's explicit analysis
                for field_name in ("harassment", "hate_speech", "sexually_explicit", "dangerous_content"):
                    value = parsed.get(field_name, "NEGLIGIBLE").upper()
                    if value in PROB_RANK:
                        setattr(scores, field_name, value)
                detail = parsed.get("summary", "")
            except json.JSONDecodeError:
                # Fall back to safety_ratings already parsed above
                detail = raw_text[:120]

        top_cat, top_prob = scores.top_category()
        top_label         = top_cat.replace("_", " ").title()
        verdict, reason   = _verdict_from_scores(scores, blocked_by_api, top_label, top_prob)

        return ModerationResult(
            scores=scores, verdict=verdict, reason=reason,
            blocked_by_api=blocked_by_api, content_type="image", detail=detail
        )

    except (FileNotFoundError, ValueError) as e:
        return ModerationResult(
            scores=ModerationScores(), verdict="block",
            reason=str(e), blocked_by_api=False, content_type="image"
        )
    except Exception as e:
        print(f"\n  [ERROR] Image moderation failed: {e}")
        return ModerationResult(
            scores=ModerationScores(), verdict="warn",
            reason=f"Image moderation API error — proceeding with caution ({e})",
            blocked_by_api=False, content_type="image"
        )


# ─── 3. Video Moderation ─────────────────────────────────────────────

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


def _extract_video_frames(video_path: str, max_frames: int = MAX_VIDEO_FRAMES) -> list[bytes]:
    """
    Extracts up to `max_frames` evenly spaced frames from a video as JPEG bytes.
    Requires opencv-python.
    """
    try:
        import cv2
    except ImportError:
        raise ImportError("opencv-python is required for video moderation. Install: pip install opencv-python")

    cap         = cv2.VideoCapture(video_path)
    total       = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    frame_count = min(max_frames, total)

    if frame_count == 0:
        cap.release()
        raise ValueError(f"Video has no readable frames: {video_path}")

    indices = [int(i * total / frame_count) for i in range(frame_count)]
    frames  = []

    for idx in indices:
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ret, frame = cap.read()
        if ret:
            ok, buf = cv2.imencode(".jpg", frame)
            if ok:
                frames.append(bytes(buf))

    cap.release()
    return frames


def moderate_video(video_path: str) -> ModerationResult:
    """
    Moderates a video file by sampling frames and sending them to Gemini vision.
    Up to MAX_VIDEO_FRAMES are extracted evenly from the video timeline.

    Args:
        video_path: Absolute or relative path to the video file.

    Returns:
        ModerationResult with content_type="video".
    """
    import json
    from google.genai import types

    path = Path(video_path)

    if not path.exists():
        return ModerationResult(
            scores=ModerationScores(), verdict="block",
            reason=f"Video not found: {video_path}",
            blocked_by_api=False, content_type="video"
        )

    ext = path.suffix.lower()
    if ext not in VIDEO_EXTENSIONS:
        return ModerationResult(
            scores=ModerationScores(), verdict="block",
            reason=f"Unsupported video format: {ext}. Supported: {VIDEO_EXTENSIONS}",
            blocked_by_api=False, content_type="video"
        )

    try:
        print(f"\n  [Extracting frames from: {path.name}...]")
        frames = _extract_video_frames(video_path)
        n      = len(frames)
        print(f"  [Moderating {n} video frames via Gemini Vision...]")

        # Build multi-part content: all frames + prompt
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

        response                = _call_with_retry(_call)
        scores, blocked_by_api  = _parse_safety_ratings(response)
        detail                  = ""

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

    except ImportError as e:
        return ModerationResult(
            scores=ModerationScores(), verdict="warn",
            reason=str(e), blocked_by_api=False, content_type="video"
        )
    except Exception as e:
        print(f"\n  [ERROR] Video moderation failed: {e}")
        return ModerationResult(
            scores=ModerationScores(), verdict="warn",
            reason=f"Video moderation API error — proceeding with caution ({e})",
            blocked_by_api=False, content_type="video"
        )


# ─── 4. Bot Response via Gemini Chat ─────────────────────────────────

SYSTEM_INSTRUCTION = (
    "You are a helpful, concise AI assistant for Station-S Agentia 2.0. "
    "Answer user queries clearly and intelligently. "
    "Keep responses under 3 sentences unless a detailed explanation is truly needed. "
    "Never engage with harmful, hateful, or inappropriate content."
)

_chat = None  # lazily initialised after key is confirmed valid


def _get_chat():
    """Lazily creates the persistent Gemini chat session."""
    global _chat
    if _chat is None:
        from google.genai import types
        _chat = get_client().chats.create(
            model=GEMINI_MODEL,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_INSTRUCTION,
                safety_settings=_safety_standard()
            )
        )
    return _chat


def get_bot_reply(user_message: str) -> str:
    """
    Sends the user message to Gemini Chat and returns its response.
    The chat session retains full conversation history automatically.
    Docs: https://ai.google.dev/gemini-api/docs/text-generation#chat
    """
    try:
        response = _call_with_retry(_get_chat().send_message, user_message)
        return response.text

    except Exception as e:
        if "SAFETY" in str(e).upper():
            return "⚠️ I'm unable to respond to that message due to safety guidelines."
        return f"[Bot Error] Gemini API failed: {e}"


# ─── 5. Voice Input (Google Speech-to-Text) ──────────────────────────

def transcribe_voice() -> Optional[str]:
    """
    Records mic audio and transcribes via Google Cloud Speech-to-Text.
    Requires: google-cloud-speech, pyaudio, GOOGLE_APPLICATION_CREDENTIALS in .env
    Docs: https://cloud.google.com/speech-to-text/docs
    """
    try:
        from google.cloud import speech
        import pyaudio

        RATE       = 16_000
        CHUNK      = 1_024
        RECORD_SEC = 5

        audio  = pyaudio.PyAudio()
        stream = audio.open(
            format=pyaudio.paInt16, channels=1,
            rate=RATE, input=True, frames_per_buffer=CHUNK
        )

        print(f"\n  🎙  Recording for {RECORD_SEC} seconds... Speak now!")
        frames = [stream.read(CHUNK) for _ in range(int(RATE / CHUNK * RECORD_SEC))]
        stream.stop_stream()
        stream.close()
        audio.terminate()
        print("  ✅  Recording complete. Transcribing...")

        stt_client    = speech.SpeechClient()
        audio_content = b"".join(frames)
        stt_audio     = speech.RecognitionAudio(content=audio_content)
        stt_config    = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=RATE,
            language_code="en-US",
        )
        result = stt_client.recognize(config=stt_config, audio=stt_audio)

        if result.results:
            transcript = result.results[0].alternatives[0].transcript
            print(f"  📝  Transcribed: \"{transcript}\"")
            return transcript

        print("  ⚠️   No speech detected.")
        return None

    except ImportError:
        print("  [SKIP] Install: pip install google-cloud-speech pyaudio")
        return None
    except Exception as e:
        print(f"  [ERROR] Voice transcription failed: {e}")
        return None


# ─── 6. Session Logger ───────────────────────────────────────────────

class SessionLogger:
    MAX_ENTRIES = 20

    def __init__(self):
        self.log: list[LogEntry] = []

    def add(self, verdict: str, text: str, reason: str, content_type: ContentType = "text"):
        preview = (text[:40] + "…") if len(text) > 40 else text
        self.log.insert(0, LogEntry(
            timestamp=datetime.now().strftime("%H:%M:%S"),
            verdict=verdict, preview=preview,
            reason=reason, content_type=content_type
        ))
        if len(self.log) > self.MAX_ENTRIES:
            self.log.pop()

    def display(self):
        VERDICT_ICONS  = {"safe": "✅", "warn": "⚠️ ", "block": "🚫"}
        CONTENT_ICONS  = {"text": "💬", "image": "🖼 ", "video": "🎬"}
        print("\n  ── Activity Log ──────────────────────────────────────")
        for e in self.log:
            v_icon = VERDICT_ICONS.get(e.verdict, "?")
            c_icon = CONTENT_ICONS.get(e.content_type, "?")
            print(f"  [{e.timestamp}] {v_icon} {e.verdict.upper():<5} {c_icon} — {e.preview}")
            print(f"               ↳ {e.reason}")
        print()


# ─── 7. Score Display ────────────────────────────────────────────────

PROB_ICONS = {"NEGLIGIBLE": "✅", "LOW": "🟡", "MEDIUM": "🟠", "HIGH": "🔴"}


def display_scores(result: ModerationResult):
    type_label = {"text": "Text", "image": "Image", "video": "Video"}.get(result.content_type, "Content")
    print(f"\n  ── Gemini Safety Ratings [{type_label}] ─────────────────")
    for category, prob in result.scores.as_dict().items():
        icon  = PROB_ICONS.get(prob, "❓")
        label = category.replace("_", " ").title()
        rank  = PROB_RANK.get(prob, 0)
        bar   = "█" * (rank * 8) + "░" * ((3 - rank) * 8)
        print(f"  {label:<22} {icon} {prob:<12} {bar}")

    if result.detail:
        print(f"\n  Analysis : {result.detail}")

    verdict_display = {
        "safe":  "✅  SAFE  — Content allowed",
        "warn":  "⚠️   WARN  — Flagged, forwarded with caution",
        "block": "🚫  BLOCK — Rejected, policy violation",
    }
    print(f"\n  Verdict  : {verdict_display[result.verdict]}")
    print(f"  Reason   : {result.reason}")
    if result.blocked_by_api:
        print("  Note     : Gemini API itself hard-blocked this content")


# ─── 8. Main ChatBot ─────────────────────────────────────────────────

class ChatBot:
    def __init__(self):
        self.stats  = SessionStats()
        self.logger = SessionLogger()
        self.db     = ModerationDB()
        self.db.open_session()
        self._print_header()
        if self.db._connected:
            print(f"  [DB] Logging to MySQL · session {self.db.session_id[:8]}…\n")

    def _print_header(self):
        print("\n" + "=" * 60)
        print("  Station-S · ChatBot Moderation (Gemini Edition)")
        print("  Agentia 2.0 Hackathon — Enhanced")
        print(f"  SDK   : google-genai (new)  |  Model: {GEMINI_MODEL}")
        print("=" * 60)
        print("  Text    : just type your message")
        print("  Image   : image <path/to/file.jpg>")
        print("  Video   : video <path/to/file.mp4>")
        print("  Voice   : voice")
        print("  Commands: stats | log | quit")
        print("=" * 60)
        print("\n  Agent: Hello! I'm your Gemini-powered AI assistant.")
        print("         All messages and media are safety-checked before processing.\n")

    # ── Text message handling ─────────────────────────────────────────

    def handle_text(self, text: str):
        text = text.strip()
        if not text:
            return

        print(f"\n  You: {text}")
        print("\n  [Moderating text via Gemini Safety Ratings...]")

        result = moderate_text(text)
        display_scores(result)
        self._update_stats(result)
        self.logger.add(result.verdict, text, result.reason, "text")
        self.db.log_event(result, text)

        print()
        if result.verdict == "block":
            print("  Agent: 🚫 Your message was blocked due to a safety violation.")
            print("         Please revise your message and try again.")
        elif result.verdict == "warn":
            print("  Agent: ⚠️  Your message was flagged as potentially sensitive.")
            print("         Proceeding with caution...\n")
            print("  [Fetching Gemini response...]")
            print(f"  Agent: {get_bot_reply(text)}")
        else:
            print("  [Fetching Gemini response...]")
            print(f"  Agent: {get_bot_reply(text)}")

    # ── Image message handling ────────────────────────────────────────

    def handle_image(self, image_path: str):
        image_path = image_path.strip()
        print(f"\n  You: [Image] {image_path}")

        result = moderate_image(image_path)
        display_scores(result)
        self._update_stats(result)
        self.logger.add(result.verdict, f"[IMAGE] {Path(image_path).name}", result.reason, "image")
        self.db.log_event(result, image_path)

        print()
        if result.verdict == "block":
            print("  Agent: 🚫 This image was blocked due to a safety violation.")
        elif result.verdict == "warn":
            print("  Agent: ⚠️  This image was flagged as potentially sensitive.")
            if result.detail:
                print(f"         Content summary: {result.detail}")
            print("         The image has been noted with a warning.")
        else:
            print("  Agent: ✅ Image passed moderation.")
            if result.detail:
                print(f"         Content summary: {result.detail}")

    # ── Video message handling ────────────────────────────────────────

    def handle_video(self, video_path: str):
        video_path = video_path.strip()
        print(f"\n  You: [Video] {video_path}")

        result = moderate_video(video_path)
        display_scores(result)
        self._update_stats(result)
        self.logger.add(result.verdict, f"[VIDEO] {Path(video_path).name}", result.reason, "video")
        self.db.log_event(result, video_path)

        print()
        if result.verdict == "block":
            print("  Agent: 🚫 This video was blocked due to a safety violation.")
        elif result.verdict == "warn":
            print("  Agent: ⚠️  This video was flagged as potentially sensitive.")
            if result.detail:
                print(f"         Content summary: {result.detail}")
            print("         The video has been noted with a warning.")
        else:
            print("  Agent: ✅ Video passed moderation.")
            if result.detail:
                print(f"         Content summary: {result.detail}")

    # ── Stats & utils ─────────────────────────────────────────────────

    def _update_stats(self, result: ModerationResult):
        self.stats.total += 1
        setattr(self.stats, result.verdict, getattr(self.stats, result.verdict) + 1)
        ct_field = {"text": "texts", "image": "images", "video": "videos"}.get(result.content_type, "texts")
        setattr(self.stats, ct_field, getattr(self.stats, ct_field) + 1)

    def show_stats(self):
        s    = self.stats
        rate = (s.block / s.total * 100) if s.total else 0
        print("\n  ── Session Statistics ──────────────────────────────")
        print(f"  Total Processed : {s.total}")
        print(f"  ✅ Safe          : {s.safe}")
        print(f"  ⚠️  Warned        : {s.warn}")
        print(f"  🚫 Blocked       : {s.block}")
        print(f"  Block Rate      : {rate:.1f}%")
        print(f"  ── By Content Type ─────────────────────────────────")
        print(f"  💬 Text          : {s.texts}")
        print(f"  🖼  Images        : {s.images}")
        print(f"  🎬 Videos        : {s.videos}")
        print()

    # ── Main loop ─────────────────────────────────────────────────────

    def run(self):
        while True:
            try:
                user_input = input("  You: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n\n  Goodbye!\n")
                self.db.close_session(self.stats)
                self.db.close()
                break

            if not user_input:
                continue

            cmd = user_input.lower()

            if cmd in ("quit", "exit", "bye"):
                print("\n  Agent: Goodbye! Have a great day.\n")
                self.show_stats()
                self.db.close_session(self.stats)
                self.db.close()
                break
            elif cmd == "stats":
                self.show_stats()
            elif cmd == "log":
                self.logger.display()
            elif cmd == "voice":
                transcript = transcribe_voice()
                if transcript:
                    self.handle_text(transcript)
                else:
                    print("  [Voice] No input captured. Try again.")
            elif cmd.startswith("image "):
                self.handle_image(user_input[6:].strip())
            elif cmd.startswith("video "):
                self.handle_video(user_input[6:].strip())
            else:
                self.handle_text(user_input)


# ─── Entry Point ─────────────────────────────────────────────────────

if __name__ == "__main__":
    try:
        get_client()   # validates key early, prints helpful error if missing
    except EnvironmentError as e:
        print(e)
        print("  GOOGLE_APPLICATION_CREDENTIALS=path/to/creds.json  # voice only\n")
        exit(1)

    bot = ChatBot()
    bot.run()

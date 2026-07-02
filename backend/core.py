"""
core.py — Shared config, data structures, DB, Gemini client, and helpers.
Extracted directly from chatbot_moderation_gemini_new_2.py (Station-S / Agentia 2.0).
"""

import base64
import os
import time
from datetime import datetime
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional

from dotenv import load_dotenv

load_dotenv()

# ─── Config ──────────────────────────────────────────────────────────

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

BLOCK_LEVEL = os.getenv("BLOCK_LEVEL", "HIGH")
WARN_LEVEL  = os.getenv("WARN_LEVEL",  "MEDIUM")

MAX_RETRIES    = 3
RETRY_DELAY    = 1.5

PROB_RANK: dict[str, int] = {
    "NEGLIGIBLE": 0,
    "LOW":        1,
    "MEDIUM":     2,
    "HIGH":       3,
}

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
VIDEO_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv", ".webm", ".flv"}
MAX_VIDEO_FRAMES = 8

# ─── MySQL Config ────────────────────────────────────────────────────

MYSQL_HOST     = os.getenv("MYSQL_HOST",     "localhost")
MYSQL_PORT     = int(os.getenv("MYSQL_PORT", "3306"))
MYSQL_USER     = os.getenv("MYSQL_USER",     "root")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "")
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "moderation_db")

# ─── Lazy Gemini Client ───────────────────────────────────────────────

_client = None

def get_client():
    global _client
    if _client is None:
        if not GEMINI_API_KEY:
            raise EnvironmentError("GEMINI_API_KEY not set in .env")
        from google import genai
        _client = genai.Client(api_key=GEMINI_API_KEY)
    return _client

# ─── Data Structures ─────────────────────────────────────────────────

ContentType = Literal["text", "image", "video", "voice"]


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
        return max(self.__dict__.items(), key=lambda x: PROB_RANK.get(x[1], 0))


@dataclass
class ModerationResult:
    scores:         ModerationScores
    verdict:        Literal["safe", "warn", "block"]
    reason:         str
    blocked_by_api: bool
    content_type:   ContentType = "text"
    detail:         str = ""


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
    texts:  int = 0
    images: int = 0
    videos: int = 0
    voices: int = 0

# ─── MySQL DDL ────────────────────────────────────────────────────────

_CREATE_SESSIONS_TABLE = """
CREATE TABLE IF NOT EXISTS moderation_sessions (
    id            BIGINT       NOT NULL AUTO_INCREMENT PRIMARY KEY,
    session_id    VARCHAR(36)  NOT NULL,
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
    content_type    ENUM('text','image','video','voice') NOT NULL,
    content_preview VARCHAR(255)  NOT NULL,
    verdict         ENUM('safe','warn','block')  NOT NULL,
    reason          TEXT          NOT NULL,
    blocked_by_api  TINYINT(1)    NOT NULL DEFAULT 0,
    score_harassment        ENUM('NEGLIGIBLE','LOW','MEDIUM','HIGH') NOT NULL DEFAULT 'NEGLIGIBLE',
    score_hate_speech       ENUM('NEGLIGIBLE','LOW','MEDIUM','HIGH') NOT NULL DEFAULT 'NEGLIGIBLE',
    score_sexually_explicit ENUM('NEGLIGIBLE','LOW','MEDIUM','HIGH') NOT NULL DEFAULT 'NEGLIGIBLE',
    score_dangerous_content ENUM('NEGLIGIBLE','LOW','MEDIUM','HIGH') NOT NULL DEFAULT 'NEGLIGIBLE',
    detail          TEXT          NULL,
    INDEX idx_session  (session_id),
    INDEX idx_verdict  (verdict),
    INDEX idx_type     (content_type),
    INDEX idx_created  (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""


class ModerationDB:
    def __init__(self):
        self._conn      = None
        self.session_id = self._new_uuid()
        self.started_at = datetime.now()
        self._connected = False

    @staticmethod
    def _new_uuid() -> str:
        import uuid
        return str(uuid.uuid4())

    def _connect(self) -> bool:
        try:
            import mysql.connector
            self._conn = mysql.connector.connect(
                host=MYSQL_HOST, port=MYSQL_PORT,
                user=MYSQL_USER, password=MYSQL_PASSWORD,
                database=MYSQL_DATABASE,
                autocommit=True, connection_timeout=5,
            )
            self._ensure_schema()
            self._connected = True
            return True
        except Exception as e:
            print(f"[DB] Connection failed: {e} — MySQL logging disabled.")
            self._connected = False
            return False

    def _cursor(self):
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
        cur = self._conn.cursor()
        cur.execute(_CREATE_SESSIONS_TABLE)
        cur.execute(_CREATE_EVENTS_TABLE)
        cur.close()

    def open_session(self):
        cur = self._cursor()
        if cur is None:
            return
        try:
            cur.execute(
                "INSERT INTO moderation_sessions (session_id, started_at) VALUES (%s, %s)",
                (self.session_id, self.started_at)
            )
        except Exception as e:
            print(f"[DB] open_session error: {e}")
        finally:
            cur.close()

    def close_session(self, stats: "SessionStats"):
        cur = self._cursor()
        if cur is None:
            return
        try:
            cur.execute(
                """UPDATE moderation_sessions
                   SET ended_at=%s, total=%s, safe_count=%s, warn_count=%s, block_count=%s
                   WHERE session_id=%s""",
                (datetime.now(), stats.total, stats.safe, stats.warn, stats.block, self.session_id)
            )
        except Exception as e:
            print(f"[DB] close_session error: {e}")
        finally:
            cur.close()

    def log_event(self, result: "ModerationResult", content_preview: str):
        cur = self._cursor()
        if cur is None:
            return
        try:
            cur.execute(
                """INSERT INTO moderation_events (
                    session_id, created_at, content_type, content_preview,
                    verdict, reason, blocked_by_api,
                    score_harassment, score_hate_speech,
                    score_sexually_explicit, score_dangerous_content, detail
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    self.session_id, datetime.now(),
                    result.content_type, content_preview[:255],
                    result.verdict, result.reason, int(result.blocked_by_api),
                    result.scores.harassment, result.scores.hate_speech,
                    result.scores.sexually_explicit, result.scores.dangerous_content,
                    result.detail or None,
                )
            )
        except Exception as e:
            print(f"[DB] log_event error: {e}")
        finally:
            cur.close()

    def close(self):
        try:
            if self._conn and self._conn.is_connected():
                self._conn.close()
        except Exception:
            pass

# ─── Safety Config ────────────────────────────────────────────────────

def _safety_off() -> list:
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


CATEGORY_MAP = {
    "HARM_CATEGORY_HARASSMENT":        "harassment",
    "HARM_CATEGORY_HATE_SPEECH":       "hate_speech",
    "HARM_CATEGORY_SEXUALLY_EXPLICIT": "sexually_explicit",
    "HARM_CATEGORY_DANGEROUS_CONTENT": "dangerous_content",
}

# ─── Internal Helpers ────────────────────────────────────────────────

def _verdict_from_scores(scores, blocked_by_api, top_label, top_prob):
    max_rank = scores.max_rank()
    if max_rank >= PROB_RANK[BLOCK_LEVEL] or blocked_by_api:
        return "block", f"Blocked — {top_label} rated {top_prob}"
    elif max_rank >= PROB_RANK[WARN_LEVEL]:
        return "warn", f"Warning — {top_label} rated {top_prob}"
    else:
        return "safe", "All categories NEGLIGIBLE or LOW"


def _parse_safety_ratings(response) -> tuple:
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
    delay = RETRY_DELAY
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            err_str = str(e).upper()
            if any(k in err_str for k in ("SAFETY", "PERMISSION", "INVALID_ARGUMENT", "APIKEY")):
                raise
            if attempt == MAX_RETRIES:
                raise
            time.sleep(delay)
            delay *= 2

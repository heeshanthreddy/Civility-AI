
# 🛡️ Civility.ai v2 — Gemini 2.0 Flash Moderation

> **Agentica 2.0 Hackathon** — Backend powered by `chatbot_moderation_gemini_new_2.py` (Station-S)

---

## 📁 Project Structure

```
civility-ai/
├── backend/
│   ├── main.py                        # FastAPI — 3 routes wired to Gemini logic
│   ├── core.py                        # ← FROM YOUR FILE: config, dataclasses, ModerationDB,
│   │                                  #   Gemini client, _safety_off, _parse_safety_ratings,
│   │                                  #   _verdict_from_scores, _call_with_retry
│   ├── services/
│   │   ├── text_moderation.py         # ← moderate_text() from your file
│   │   ├── image_moderation.py        # ← moderate_image() from your file
│   │   ├── video_moderation.py        # ← moderate_video() from your file
│   │   └── decision.py                # verdict → status label + confidence %
│   ├── utils/
│   │   └── video_utils.py             # ← _extract_video_frames() from your file
│   ├── .env                           # GEMINI_API_KEY + MySQL config
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── App.jsx
│   │   ├── components/
│   │   │   ├── ChatBox.jsx
│   │   │   ├── UploadBox.jsx
│   │   │   └── Dashboard.jsx          # Shows per-category Gemini Safety Ratings
│   │   ├── api.js
│   │   ├── main.jsx
│   │   └── index.css
│   ├── index.html
│   ├── package.json
│   └── vite.config.js
├── k8s/
├── docker-compose.yml
└── README.md
```

---

## 🔁 Mapping — Your File → Project Structure

| Original function | Lives in |
|------------------|----------|
| `GEMINI_API_KEY`, `GEMINI_MODEL`, `PROB_RANK`, thresholds | `core.py` |
| `ModerationScores`, `ModerationResult`, `SessionStats` | `core.py` |
| `ModerationDB` (MySQL logging) | `core.py` |
| `get_client()`, `_safety_off()`, `_parse_safety_ratings()` | `core.py` |
| `_verdict_from_scores()`, `_call_with_retry()` | `core.py` |
| `moderate_text()` | `services/text_moderation.py` |
| `moderate_image()` | `services/image_moderation.py` |
| `moderate_video()` | `services/video_moderation.py` |
| `_extract_video_frames()` | `utils/video_utils.py` |
| FastAPI HTTP layer (new) | `main.py` |

---

## 🚀 Running the Project

### Backend
```bash
cd backend
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```
API docs: **http://localhost:8000/docs**

### Frontend
```bash
cd frontend
npm install
npm run dev
```
App: **http://localhost:3000**

---

## 📡 API Response Example

```json
{
  "content_type": "Text",
  "status": "Rejected",
  "verdict": "block",
  "category": "Dangerous Content",
  "confidence": 92,
  "reason": "Blocked — Dangerous Content rated HIGH",
  "detail": "",
  "blocked_by_api": false,
  "scores": {
    "harassment": "NEGLIGIBLE",
    "hate_speech": "NEGLIGIBLE",
    "sexually_explicit": "NEGLIGIBLE",
    "dangerous_content": "HIGH"
  }
}
```

---

## 🗄️ MySQL (Optional)

If MySQL is running, every moderation event is automatically logged to:
- `moderation_sessions` — one row per server run
- `moderation_events` — one row per moderated item

Tables are auto-created on first connection. No setup needed beyond `.env` credentials.

---

## 📦 Dependencies

```
fastapi, uvicorn          — HTTP server
google-genai              — NEW Gemini SDK (not deprecated google-generativeai)
python-dotenv             — .env loading
python-multipart          — FastAPI file upload support
opencv-python-headless    — Video frame extraction
mysql-connector-python    — Optional DB logging
```

# team32


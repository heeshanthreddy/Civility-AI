const STATUS_CONFIG = {
  Approved:             { color: "#22c55e", bg: "#052e16", icon: "✅" },
  "Flagged for Review": { color: "#f59e0b", bg: "#2d1b00", icon: "⚠️" },
  Rejected:             { color: "#ef4444", bg: "#2d0a0a", icon: "🚫" },
};

const PROB_COLOR = {
  NEGLIGIBLE: "#22c55e",
  LOW:        "#84cc16",
  MEDIUM:     "#f59e0b",
  HIGH:       "#ef4444",
};
const PROB_WIDTH = { NEGLIGIBLE: "8%", LOW: "30%", MEDIUM: "65%", HIGH: "95%" };

const CONTENT_ICON = { Text: "💬", Image: "🖼️", Video: "🎬", Voice: "🎙️" };

function ConfidenceMeter({ score }) {
  const color = score >= 60 ? "#ef4444" : score >= 30 ? "#f59e0b" : "#22c55e";
  return (
    <div className="confidence-wrap">
      <div className="confidence-bar-bg">
        <div className="confidence-bar-fill" style={{ width: `${score}%`, background: color }} />
      </div>
      <span className="confidence-label" style={{ color }}>{score}%</span>
    </div>
  );
}

function ScoresBreakdown({ scores }) {
  if (!scores) return null;
  const labels = {
    harassment:        "Harassment",
    hate_speech:       "Hate Speech",
    sexually_explicit: "Sexually Explicit",
    dangerous_content: "Dangerous Content",
  };
  return (
    <div className="scores-breakdown">
      {Object.entries(scores).map(([key, val]) => (
        <div key={key} className="score-row">
          <span className="score-label">{labels[key] || key}</span>
          <div className="score-bar-bg">
            <div className="score-bar-fill"
              style={{ width: PROB_WIDTH[val] || "5%", background: PROB_COLOR[val] || "#6b7280" }} />
          </div>
          <span className="score-val" style={{ color: PROB_COLOR[val] || "#9ca3af" }}>{val}</span>
        </div>
      ))}
    </div>
  );
}

export default function Dashboard({ results }) {
  if (!results.length) {
    return (
      <div className="dashboard empty-state">
        <div className="empty-icon">🛡️</div>
        <p>No moderation results yet.</p>
        <p className="empty-sub">Submit text, upload a file, or record your voice.</p>
      </div>
    );
  }

  return (
    <div className="dashboard">
      <h3 className="section-title"><span className="icon">📊</span> Moderation Results</h3>

      {results.map((r, i) => {
        if (r.error) {
          return (
            <div key={i} className="result-card error-card">
              <span className="icon">❌</span> Error: {r.error}
            </div>
          );
        }

        const cfg       = STATUS_CONFIG[r.status] || STATUS_CONFIG["Flagged for Review"];
        const ctIcon    = CONTENT_ICON[r.content_type] || "📄";
        const isVoice   = r.content_type === "Voice";

        // For voice, detail often contains "summary | Transcript: ..."
        let transcript  = "";
        let summary     = r.detail || "";
        if (isVoice && r.detail && r.detail.includes("| Transcript:")) {
          const parts = r.detail.split("| Transcript:");
          summary     = parts[0].trim();
          transcript  = parts[1]?.trim() || "";
        }

        return (
          <div key={i} className="result-card" style={{ borderColor: cfg.color }}>
            <div className="result-header">
              <div className="result-type">{ctIcon} {r.content_type}</div>
              <div className="result-badge"
                style={{ background: cfg.bg, color: cfg.color, border: `1px solid ${cfg.color}` }}>
                {cfg.icon} {r.status}
              </div>
            </div>

            <div className="result-body">
              <div className="result-row">
                <span className="label">Top Category</span>
                <span className="value category-tag">{r.category}</span>
              </div>
              <div className="result-row">
                <span className="label">Confidence</span>
                <ConfidenceMeter score={r.confidence} />
              </div>

              {r.filename && (
                <div className="result-row">
                  <span className="label">File</span>
                  <span className="value">{r.filename}</span>
                </div>
              )}

              {r.reason && (
                <div className="result-row details-row">
                  <span className="label">Reason</span>
                  <span className="value details-text">{r.reason}</span>
                </div>
              )}

              {/* Voice: show summary + transcript separately */}
              {isVoice && summary && (
                <div className="result-row details-row">
                  <span className="label">Summary</span>
                  <span className="value details-text">{summary}</span>
                </div>
              )}
              {isVoice && transcript && (
                <div className="result-row details-row" style={{ flexDirection: "column", alignItems: "stretch", gap: 4 }}>
                  <span className="label">Transcript</span>
                  <div className="transcript-box">{transcript}</div>
                </div>
              )}

              {/* Non-voice detail */}
              {!isVoice && r.detail && (
                <div className="result-row details-row">
                  <span className="label">Detail</span>
                  <span className="value details-text">{r.detail}</span>
                </div>
              )}

              {r.scores && (
                <div className="scores-section">
                  <div className="scores-title">Gemini Safety Ratings</div>
                  <ScoresBreakdown scores={r.scores} />
                </div>
              )}

              {r.blocked_by_api && (
                <div className="api-blocked-note">⚡ Gemini API hard-blocked this content</div>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

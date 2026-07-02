import { useState } from "react";
import { moderateText } from "../api";

export default function ChatBox({ onResult }) {
  const [text, setText] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async () => {
    if (!text.trim()) return;
    setLoading(true);
    try {
      const result = await moderateText(text);
      onResult(result);
    } catch (e) {
      onResult({ error: e.message });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="chat-box">
      <h3 className="section-title">
        <span className="icon">💬</span> Text Moderation
      </h3>
      <textarea
        className="text-input"
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="Type or paste your comment here..."
        rows={5}
      />
      <button
        className="submit-btn"
        onClick={handleSubmit}
        disabled={loading || !text.trim()}
      >
        {loading ? (
          <span className="spinner">Analyzing…</span>
        ) : (
          "Analyze Text"
        )}
      </button>
    </div>
  );
}

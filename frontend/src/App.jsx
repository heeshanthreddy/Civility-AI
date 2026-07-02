import { useState } from "react";
import ChatBox from "./components/ChatBox";
import UploadBox from "./components/UploadBox";
import VoiceBox from "./components/VoiceBox";
import Dashboard from "./components/Dashboard";
import "./index.css";

const TABS = [
  { id: "text",  label: "Text",        icon: "💬" },
  { id: "media", label: "Image/Video", icon: "📁" },
  { id: "voice", label: "Voice",       icon: "🎙️" },
];

export default function App() {
  const [results, setResults]     = useState([]);
  const [activeTab, setActiveTab] = useState("text");

  const handleResult = (result) => setResults((prev) => [result, ...prev]);
  const clearHistory  = () => setResults([]);

  return (
    <div className="app">
      <header className="header">
        <div className="header-inner">
          <div className="logo">
            <span className="logo-icon">🛡️</span>
            <span className="logo-text">Civility<span className="logo-dot">.ai</span></span>
          </div>
          <div className="header-divider" />
          <p className="tagline">AI-Powered Content Moderation</p>
          <div className="header-pills">
            <span className="header-pill">Gemini 2.0</span>
            <span className="header-pill header-pill--live">● Live</span>
          </div>
        </div>
      </header>

      <main className="main">
        <div className="left-panel">
          <div className="tab-bar">
            {TABS.map((t) => (
              <button
                key={t.id}
                className={`tab-btn ${activeTab === t.id ? "active" : ""}`}
                onClick={() => setActiveTab(t.id)}
              >
                <span className="tab-icon">{t.icon}</span>
                <span className="tab-label">{t.label}</span>
              </button>
            ))}
          </div>

          <div className="panel-content">
            {activeTab === "text"  && <ChatBox   onResult={handleResult} />}
            {activeTab === "media" && <UploadBox  onResult={handleResult} />}
            {activeTab === "voice" && <VoiceBox   onResult={handleResult} />}
          </div>

          <div className="how-it-works">
            <h4>How It Works</h4>
            <ol>
              <li>Submit text, image, video, or voice content</li>
              <li>Gemini AI analyzes for harmful patterns</li>
              <li>Receive an instant moderation verdict</li>
              <li>Unsafe content is blocked or flagged</li>
            </ol>
          </div>
        </div>

        <div className="right-panel">
          <div className="dashboard-header">
            <div className="results-count">
              {results.length > 0 && (
                <span className="results-badge">{results.length} result{results.length !== 1 ? "s" : ""}</span>
              )}
            </div>
            {results.length > 0 && (
              <button className="clear-history-btn" onClick={clearHistory}>Clear History</button>
            )}
          </div>
          <Dashboard results={results} />
        </div>
      </main>

      <footer className="footer">
        <p>Civility.ai — Agentica 2.0 Hackathon &nbsp;|&nbsp; Powered by Gemini AI &nbsp;|&nbsp; Station-S Team 32</p>
      </footer>
    </div>
  );
}

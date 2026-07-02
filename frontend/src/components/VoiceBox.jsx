import { useState, useRef, useEffect } from "react";
import { moderateVoice } from "../api";

const SUPPORTED_MIME = ["audio/webm", "audio/ogg", "audio/mp4"].find(
  (m) => typeof MediaRecorder !== "undefined" && MediaRecorder.isTypeSupported(m)
) || "audio/webm";

export default function VoiceBox({ onResult }) {
  const [phase, setPhase]       = useState("idle"); // idle | recording | analyzing
  const [seconds, setSeconds]   = useState(0);
  const [error, setError]       = useState("");
  const [audioURL, setAudioURL] = useState(null);
  const [bars, setBars]         = useState(Array(28).fill(4));

  const mediaRef    = useRef(null);
  const chunksRef   = useRef([]);
  const timerRef    = useRef(null);
  const analyserRef = useRef(null);
  const animRef     = useRef(null);
  const audioCtxRef = useRef(null);

  useEffect(() => () => stopEverything(), []);

  const stopEverything = () => {
    clearInterval(timerRef.current);
    cancelAnimationFrame(animRef.current);
    if (mediaRef.current?.state === "recording") mediaRef.current.stop();
    audioCtxRef.current?.close().catch(() => {});
  };

  const animateWave = () => {
    if (!analyserRef.current) return;
    const data = new Uint8Array(analyserRef.current.frequencyBinCount);
    analyserRef.current.getByteFrequencyData(data);
    const step = Math.floor(data.length / 28);
    setBars(Array.from({ length: 28 }, (_, i) => {
      const v = data[i * step] / 255;
      return Math.max(4, Math.round(v * 56));
    }));
    animRef.current = requestAnimationFrame(animateWave);
  };

  const startRecording = async () => {
    setError("");
    setAudioURL(null);
    setSeconds(0);
    setBars(Array(28).fill(4));
    chunksRef.current = [];

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });

      // Visualiser setup
      audioCtxRef.current   = new (window.AudioContext || window.webkitAudioContext)();
      const source          = audioCtxRef.current.createMediaStreamSource(stream);
      analyserRef.current   = audioCtxRef.current.createAnalyser();
      analyserRef.current.fftSize = 64;
      source.connect(analyserRef.current);
      animRef.current = requestAnimationFrame(animateWave);

      const recorder = new MediaRecorder(stream, { mimeType: SUPPORTED_MIME });
      recorder.ondataavailable = (e) => e.data.size > 0 && chunksRef.current.push(e.data);
      recorder.onstop = () => {
        stream.getTracks().forEach((t) => t.stop());
        cancelAnimationFrame(animRef.current);
        setBars(Array(28).fill(4));
        const blob = new Blob(chunksRef.current, { type: SUPPORTED_MIME });
        const url  = URL.createObjectURL(blob);
        setAudioURL(url);
        submitBlob(blob);
      };

      recorder.start(100);
      mediaRef.current = recorder;
      setPhase("recording");

      timerRef.current = setInterval(() => {
        setSeconds((s) => {
          if (s + 1 >= 60) { stopRecording(); return s; }
          return s + 1;
        });
      }, 1000);

    } catch (e) {
      setError("Microphone access denied. Please allow microphone permissions.");
    }
  };

  const stopRecording = () => {
    clearInterval(timerRef.current);
    if (mediaRef.current?.state === "recording") {
      mediaRef.current.stop();
    }
    setPhase("analyzing");
  };

  const submitBlob = async (blob) => {
    try {
      const ext    = SUPPORTED_MIME.split("/")[1].split(";")[0];
      const result = await moderateVoice(blob, `recording.${ext}`);
      onResult(result);
    } catch (e) {
      onResult({ error: e.message });
    } finally {
      setPhase("idle");
    }
  };

  const fmt = (s) => `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;

  return (
    <div className="voice-box">
      <h3 className="section-title">
        <span className="icon">🎙️</span> Voice Moderation
      </h3>

      <div className="voice-visualizer">
        {phase === "recording" ? (
          <>
            <div className="waveform">
              {bars.map((h, i) => (
                <div key={i} className="wave-bar" style={{ height: `${h}px` }} />
              ))}
            </div>
            <div className="rec-indicator">
              <span className="rec-dot" />
              <span className="rec-label">REC {fmt(seconds)}</span>
            </div>
          </>
        ) : phase === "analyzing" ? (
          <div className="analyzing-state">
            <div className="pulse-ring" />
            <span className="analyzing-text">Transcribing &amp; analyzing…</span>
          </div>
        ) : (
          <div className="idle-state">
            <div className="mic-icon-wrap">🎙️</div>
            <p className="idle-hint">Press record and speak clearly</p>
            <p className="idle-sub">Max 60 seconds · MP3, WAV, OGG, WEBM supported</p>
          </div>
        )}
      </div>

      {error && <div className="voice-error">{error}</div>}

      <div className="voice-controls">
        {phase === "idle" && (
          <button className="submit-btn voice-record-btn" onClick={startRecording}>
            ⏺ Start Recording
          </button>
        )}
        {phase === "recording" && (
          <button className="submit-btn voice-stop-btn" onClick={stopRecording}>
            ⏹ Stop &amp; Analyze
          </button>
        )}
        {phase === "analyzing" && (
          <button className="submit-btn" disabled>
            Analyzing…
          </button>
        )}
      </div>

      {audioURL && phase === "idle" && (
        <div className="audio-playback">
          <p className="playback-label">Last recording:</p>
          <audio controls src={audioURL} className="audio-player" />
        </div>
      )}

      <div className="voice-upload-section">
        <p className="upload-or">— or upload an audio file —</p>
        <label className="upload-audio-label">
          <input
            type="file"
            accept="audio/*"
            style={{ display: "none" }}
            onChange={async (e) => {
              const f = e.target.files[0];
              if (!f) return;
              setPhase("analyzing");
              setError("");
              try {
                const result = await moderateVoice(f, f.name);
                onResult(result);
              } catch (err) {
                onResult({ error: err.message });
              } finally {
                setPhase("idle");
                e.target.value = "";
              }
            }}
          />
          📂 Upload Audio File
        </label>
      </div>
    </div>
  );
}

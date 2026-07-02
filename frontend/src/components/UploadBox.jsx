import { useState, useRef } from "react";
import { moderateImage, moderateVideo } from "../api";

export default function UploadBox({ onResult }) {
  const [dragging, setDragging] = useState(false);
  const [file, setFile] = useState(null);
  const [loading, setLoading] = useState(false);
  const inputRef = useRef();

  const isVideo = (f) => f?.type?.startsWith("video/");
  const isImage = (f) => f?.type?.startsWith("image/");

  const handleFile = (f) => {
    if (!f) return;
    setFile(f);
  };

  const handleDrop = (e) => {
    e.preventDefault();
    setDragging(false);
    const f = e.dataTransfer.files[0];
    handleFile(f);
  };

  const handleAnalyze = async () => {
    if (!file) return;
    setLoading(true);
    try {
      let result;
      if (isVideo(file)) result = await moderateVideo(file);
      else if (isImage(file)) result = await moderateImage(file);
      else result = { error: "Unsupported file type." };
      onResult(result);
    } catch (e) {
      onResult({ error: e.message });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="upload-box">
      <h3 className="section-title">
        <span className="icon">📁</span> Image / Video Moderation
      </h3>

      <div
        className={`drop-zone ${dragging ? "dragging" : ""} ${file ? "has-file" : ""}`}
        onClick={() => inputRef.current.click()}
        onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={handleDrop}
      >
        {file ? (
          <div className="file-preview">
            {isImage(file) && (
              <img src={URL.createObjectURL(file)} alt="preview" className="img-preview" />
            )}
            <p className="file-name">{file.name}</p>
            <p className="file-size">{(file.size / 1024).toFixed(1)} KB</p>
          </div>
        ) : (
          <div className="drop-prompt">
            <div className="drop-icon">⬆️</div>
            <p>Drag & drop or click to upload</p>
            <p className="drop-sub">Images: JPG, PNG, WEBP &nbsp;|&nbsp; Videos: MP4, MOV, AVI</p>
          </div>
        )}
        <input
          ref={inputRef}
          type="file"
          accept="image/*,video/*"
          style={{ display: "none" }}
          onChange={(e) => handleFile(e.target.files[0])}
        />
      </div>

      <button
        className="submit-btn"
        onClick={handleAnalyze}
        disabled={loading || !file}
      >
        {loading ? "Analyzing…" : "Analyze File"}
      </button>

      {file && (
        <button
          className="clear-btn"
          onClick={() => setFile(null)}
        >
          Clear
        </button>
      )}
    </div>
  );
}

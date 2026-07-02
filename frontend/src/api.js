const BASE_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

export async function moderateText(text) {
  const form = new FormData();
  form.append("text", text);
  const res = await fetch(`${BASE_URL}/moderate/text`, { method: "POST", body: form });
  if (!res.ok) throw new Error(`Server error: ${res.status}`);
  return res.json();
}

export async function moderateImage(file) {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${BASE_URL}/moderate/image`, { method: "POST", body: form });
  if (!res.ok) throw new Error(`Server error: ${res.status}`);
  return res.json();
}

export async function moderateVideo(file) {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${BASE_URL}/moderate/video`, { method: "POST", body: form });
  if (!res.ok) throw new Error(`Server error: ${res.status}`);
  return res.json();
}

export async function moderateVoice(blob, filename = "recording.webm") {
  const form = new FormData();
  form.append("file", blob, filename);
  const res = await fetch(`${BASE_URL}/moderate/voice`, { method: "POST", body: form });
  if (!res.ok) throw new Error(`Server error: ${res.status}`);
  return res.json();
}

"""
video_utils.py
Frame extractor — same logic as _extract_video_frames() in the original chatbot file.
"""


def extract_frames(video_path: str, max_frames: int = 8) -> list[bytes]:
    """
    Extracts up to `max_frames` evenly-spaced frames from a video as JPEG bytes.
    Identical to _extract_video_frames() in chatbot_moderation_gemini_new_2.py.
    """
    try:
        import cv2
    except ImportError:
        raise ImportError("opencv-python is required. Install: pip install opencv-python")

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

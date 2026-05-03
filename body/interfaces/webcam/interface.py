# interfaces/webcam/interface.py
# ============================================================
# Interface Plugin: Webcam (Sensor)
#
# Captures a frame at a configurable interval, describes it
# using the LLM vision model, and pushes an "observation"
# into the inbox_queue as if the character noticed something.
#
# TYPE: sensor — no send() function. Observations flow in only.
#
# REQUIRES: opencv-python  (pip install opencv-python)
# Enable in interface.toml once installed.
#
# This plugin demonstrates the SENSOR pattern:
#   - start() launches a background asyncio task
#   - The task captures frames and pushes to inbox_queue
#   - stop() cancels the background task cleanly
# ============================================================

import asyncio
import base64
import logging
import time
from collections import deque
from typing import Optional

log = logging.getLogger(__name__)

MANIFEST = {
    "name":        "webcam",
    "description": "Capture frames periodically and push observations to inbox",
    "type":        "sensor",
    "requires":    [],  # No env vars needed; opencv-python must be installed
}

_task:     Optional[asyncio.Task] = None
_inbox:    Optional[deque]        = None
_settings: dict = {}
_running:  bool = False


async def start(inbox_queue: deque) -> None:
    global _task, _inbox, _running

    # Fail loudly if opencv is missing so the loader can catch it
    try:
        import cv2  # noqa: F401
    except ImportError:
        raise ImportError(
            "opencv-python is required for the webcam interface. "
            "Install with: pip install opencv-python"
        )

    _inbox   = inbox_queue
    _running = True

    interval = _settings.get("capture_interval_seconds", 1800)
    log.info("[webcam] Starting | interval=%ds | device=%d",
             interval, _settings.get("device_index", 0))

    _task = asyncio.create_task(_capture_loop())


async def stop() -> None:
    global _running, _task
    _running = False
    if _task and not _task.done():
        _task.cancel()
        try:
            await _task
        except asyncio.CancelledError:
            pass
    log.info("[webcam] Stopped.")


# ── No send() function — this is a sensor only ───────────────


# ── Background Capture Loop ──────────────────────────────────

async def _capture_loop() -> None:
    """
    Runs in the background, capturing a frame every N seconds
    and pushing it as an observation inbox item.
    """
    import cv2

    interval   = _settings.get("capture_interval_seconds", 1800)
    device_idx = _settings.get("device_index", 0)
    prompt     = _settings.get(
        "description_prompt",
        "Describe what you see in 1–2 sentences, as a quiet observation."
    )

    while _running:
        await asyncio.sleep(interval)

        log.debug("[webcam] Capturing frame...")
        frame_b64 = _capture_frame(cv2, device_idx)

        if frame_b64 is None:
            log.warning("[webcam] Frame capture failed — skipping this cycle.")
            continue

        log.info("[webcam] Frame captured — pushing observation to inbox.")
        _inbox.append({
            "source":     "webcam",
            "sender":     "environment",
            "text":       prompt,       # Engine will process this as a "message"
            "raw":        frame_b64,    # Base64 JPEG; available if LLM supports vision
            "ts":         time.time(),
            "is_visual":  True,         # Flag so reply pipeline can handle differently
        })


def _capture_frame(cv2, device_index: int) -> Optional[str]:
    """
    Capture one frame from the camera and return it as a base64 JPEG string.
    Returns None on failure.
    """
    cap = cv2.VideoCapture(device_index)
    if not cap.isOpened():
        log.error("[webcam] Cannot open camera device %d", device_index)
        return None

    try:
        ret, frame = cap.read()
        if not ret:
            log.error("[webcam] Failed to read frame from camera.")
            return None
        _, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        return base64.b64encode(buffer).decode("utf-8")
    finally:
        cap.release()

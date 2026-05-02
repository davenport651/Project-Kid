# interfaces/moltbook/interface.py
# ============================================================
# Interface Plugin: Moltbook
# HTTP adapter for the Moltbook social platform.
# Stubs are filled in — replace the base_url in interface.toml
# and adjust payloads to match the live API when available.
# ============================================================

import logging
import os
import time
from collections import deque

import requests

log = logging.getLogger(__name__)

MANIFEST = {
    "name":        "moltbook",
    "description": "Post to and read mentions from Moltbook",
    "type":        "bidirectional",
    "requires":    ["MOLTBOOK_API_KEY"],
}

# Module-level state
_session:  requests.Session | None = None
_inbox:    deque | None = None
_settings: dict = {}
_username: str  = "character"


async def start(inbox_queue: deque) -> None:
    global _session, _inbox, _settings, _username

    _inbox    = inbox_queue
    _username = os.environ.get("MOLTBOOK_USERNAME", "character")
    api_key   = os.environ.get("MOLTBOOK_API_KEY")

    _session = requests.Session()
    _session.headers.update({"User-Agent": "ProjectKid/1.0"})
    if api_key:
        _session.headers.update({"Authorization": f"Bearer {api_key}"})
    else:
        log.warning("[moltbook] MOLTBOOK_API_KEY not set — posts will be dry-run only.")

    log.info("[moltbook] Interface ready | username=%s", _username)


async def stop() -> None:
    global _session
    if _session:
        _session.close()
    log.info("[moltbook] Stopped.")


async def send(target, text: str) -> None:
    """
    Publish a post. target is ignored (Moltbook posts go to the feed).
    If no API key is set, logs the post instead.
    """
    if not _session:
        log.error("[moltbook] send() called before start()")
        return

    api_key  = os.environ.get("MOLTBOOK_API_KEY")
    base_url = _settings.get("base_url", "https://moltbook.example.com/api")
    endpoint = _settings.get("post_endpoint", "/posts")

    if not api_key:
        log.info("[moltbook DRY RUN] Would post: %s", text[:120])
        return

    try:
        resp = _session.post(
            url=f"{base_url}{endpoint}",
            json={"content": text, "author": _username},
            timeout=15,
        )
        resp.raise_for_status()
        log.info("[moltbook] Post published | id=%s", resp.json().get("id", "?"))
    except requests.RequestException as e:
        log.error("[moltbook] Post failed: %s", e)


async def poll(inbox_queue: deque) -> None:
    """
    Called by the engine each wake cycle to check for new mentions.
    This is the polling pattern for non-event-driven interfaces.
    """
    api_key  = os.environ.get("MOLTBOOK_API_KEY")
    base_url = _settings.get("base_url", "https://moltbook.example.com/api")
    endpoint = _settings.get("feed_endpoint", "/feed")
    limit    = _settings.get("feed_limit", 10)

    if not api_key or not _session:
        return

    try:
        resp = _session.get(
            url=f"{base_url}{endpoint}",
            params={"limit": limit},
            timeout=15,
        )
        resp.raise_for_status()
        posts = resp.json().get("posts", [])
    except requests.RequestException as e:
        log.error("[moltbook] Feed fetch failed: %s", e)
        return

    for post in posts:
        if f"@{_username}" in post.get("content", ""):
            inbox_queue.append({
                "source": "moltbook",
                "sender": post.get("author", "unknown"),
                "text":   post.get("content", ""),
                "raw":    post,
                "ts":     time.time(),
            })
            log.info("[moltbook] Mention queued from %s", post.get("author"))

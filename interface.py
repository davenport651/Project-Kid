# interfaces/telegram/interface.py
# ============================================================
# Interface Plugin: Telegram
#
# CONTRACT (all interface plugins must implement):
#   MANIFEST  dict
#   start(inbox_queue)  async
#   stop()              async
#   send(target, text)  async   ← optional for sensors; required here
#
# This plugin uses python-telegram-bot v20 (async polling).
# Messages from the allowed user are pushed onto inbox_queue.
# The engine calls send() when a reply needs to go out.
#
# REQUIRED ENV VARS (set in .env):
#   TELEGRAM_BOT_TOKEN
#   TELEGRAM_ALLOWED_USER_ID   (get yours from @userinfobot)
# ============================================================

import logging
import os
import time
from collections import deque

from telegram import Update
from telegram.ext import Application, MessageHandler, filters

log = logging.getLogger(__name__)

# ── Plugin Contract ──────────────────────────────────────────
MANIFEST = {
    "name":        "telegram",
    "description": "Receive and reply to messages via Telegram Bot API",
    "type":        "bidirectional",
    "requires":    ["TELEGRAM_BOT_TOKEN", "TELEGRAM_ALLOWED_USER_ID"],
}

# Module-level application reference (set during start())
_app: Application | None = None
_inbox: deque | None = None
_allowed_uid: str | None = None


# ── Lifecycle ────────────────────────────────────────────────

async def start(inbox_queue: deque) -> None:
    """
    Initialise the Telegram bot and begin async polling.
    Messages land in inbox_queue as dicts.
    """
    global _app, _inbox, _allowed_uid

    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise EnvironmentError("TELEGRAM_BOT_TOKEN not set in .env")

    _allowed_uid = os.environ.get("TELEGRAM_ALLOWED_USER_ID")
    _inbox       = inbox_queue

    _app = Application.builder().token(token).build()
    _app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, _on_message)
    )

    await _app.initialize()
    await _app.start()
    await _app.updater.start_polling(poll_interval=1.0)

    log.info("[telegram] Polling started | allowed_uid=%s", _allowed_uid or "ALL")


async def stop() -> None:
    """Gracefully shut down the Telegram bot."""
    global _app
    if _app:
        await _app.updater.stop()
        await _app.stop()
        await _app.shutdown()
        log.info("[telegram] Stopped.")


# ── Send ────────────────────────────────────────────────────

async def send(target, text: str) -> None:
    """
    Send a message. target can be:
        - A telegram.Message object (to reply_text)
        - An int/str chat_id (to send_message)
        - None (no-op — log a warning)
    """
    if _app is None:
        log.error("[telegram] send() called but bot is not running.")
        return

    max_len = 4096
    chunks  = [text[i:i + max_len] for i in range(0, len(text), max_len)]

    for chunk in chunks:
        try:
            if hasattr(target, "reply_text"):
                # telegram.Message object
                await target.reply_text(chunk)
            elif target is not None:
                # Numeric chat_id
                await _app.bot.send_message(chat_id=int(target), text=chunk)
            else:
                log.warning("[telegram] send() called with target=None — nowhere to send.")
                return
        except Exception as e:
            log.error("[telegram] send() failed: %s", e)

    log.info("[telegram] Sent %d chunk(s) | preview='%s...'", len(chunks), text[:60])


# ── Internal Handler ─────────────────────────────────────────

async def _on_message(update: Update, context) -> None:
    """
    Called by python-telegram-bot when a text message arrives.
    Validates sender, then pushes to inbox_queue.
    """
    msg       = update.message
    sender_id = str(msg.from_user.id)

    # Security: allowlist check
    if _allowed_uid and sender_id != str(_allowed_uid):
        log.warning("[telegram] Blocked message from unauthorised user %s", sender_id)
        return

    log.info("[telegram] Message received | from=%s | text='%s...'",
             msg.from_user.username or sender_id, msg.text[:60])

    _inbox.append({
        "source": "telegram",
        "sender": msg.from_user.username or sender_id,
        "text":   msg.text,
        "raw":    msg,        # Stored so send() can call reply_text()
        "ts":     time.time(),
    })

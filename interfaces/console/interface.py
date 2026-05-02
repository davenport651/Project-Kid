#!/usr/bin/env python3
# interfaces/console/interface.py
# ============================================================
# Console Interface Plugin — Terminal REPL for interactive chat
# ============================================================
# Runs input() in a background thread, pushes messages to inbox_queue.
# Provides a modular COMMANDS registry for extensible slash commands.
# ============================================================

import asyncio
import logging
import threading
import time
from collections import deque

# Priority level for interactive console messages (highest)
CONSOLE_PRIORITY = 100

# Shared Event: set by console input to wake the engine from sleep
console_wake = threading.Event()

log = logging.getLogger(__name__)

MANIFEST = {
    "name": "console",
    "description": "Terminal REPL for interactive chat with the persona",
    "type": "bidirectional",
    "requires": [],
}

# ── Command Registry ───────────────────────────────────────────
# Modular structure: add new commands by adding entries to COMMANDS.
# Each handler: Callable[[text: str, inbox_queue: deque], None]
# Return True to suppress pushing to inbox, False to push after.

COMMANDS = {}

def register_command(name: str):
    """Decorator to register a command handler."""
    def decorator(fn):
        COMMANDS[name] = fn
        return fn
    return decorator

@register_command("/quit")
def _cmd_quit(text: str, inbox_queue: deque) -> bool:
    """Shut down the engine."""
    global _stop_event, _input_thread
    log.info("Console: /quit received — shutting down.")
    print("\n[Console] Shutting down...")
    if _stop_event:
        _stop_event.set()
    return True  # suppress inbox push

@register_command("/help")
def _cmd_help(text: str, inbox_queue: deque) -> bool:
    """List available commands."""
    print("\n[Console] Available commands:")
    for cmd, fn in sorted(COMMANDS.items()):
        doc = (fn.__doc__ or "No description").strip().split("\n")[0]
        print(f"  {cmd:15} — {doc}")
    print()
    return True

@register_command("/act")
def _cmd_act(text: str, inbox_queue: deque) -> bool:
    """Trigger an autonomous action immediately."""
    inbox_queue.append({
        "source": "console",
        "sender": "system",
        "text": "TRIGGER_AUTONOMOUS_ACTION",
        "raw": None,
        "ts": time.time(),
        "priority": CONSOLE_PRIORITY,
        "is_command": True,
    })
    console_wake.set()
    print("[Console] Autonomous action triggered.\n> ", end="", flush=True)
    return True

# ── State ────────────────────────────────────────────────────────
_stop_event: threading.Event = None
_input_thread: threading.Thread = None
_inbox_queue: deque = None
_active_interfaces: dict = None  # reference for console reply routing

def _read_loop():
    """Background thread: reads stdin, parses commands, pushes to inbox."""
    global _inbox_queue
    while not _stop_event.is_set():
        try:
            line = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if not line:
            continue

        # Parse slash command
        parts = line.split(None, 1)
        cmd = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        if cmd in COMMANDS:
            suppress = COMMANDS[cmd](args, _inbox_queue)
            if suppress:
                continue

        # Push to inbox queue
        _inbox_queue.append({
            "source": "console",
            "sender": "user",
            "text": line,
            "raw": None,
            "ts": time.time(),
            "priority": CONSOLE_PRIORITY,
        })
        console_wake.set()

# ── Plugin Entrypoints ─────────────────────────────────────────
async def start(inbox_queue: deque) -> None:
    """Start the console input reader."""
    global _stop_event, _input_thread, _inbox_queue
    _inbox_queue = inbox_queue
    _stop_event = threading.Event()

    print("\n[Console] Interactive chat enabled. Type /help for commands.")
    print("Type /quit to exit, or just type a message to chat.\n")

    _input_thread = threading.Thread(target=_read_loop, daemon=True, name="console-input")
    _input_thread.start()

async def stop() -> None:
    """Stop the console input reader."""
    global _stop_event, _input_thread
    if _stop_event:
        _stop_event.set()
    if _input_thread and _input_thread.is_alive():
        _input_thread.join(timeout=2.0)
    log.info("Console interface stopped.")

async def send(target, text: str) -> None:
    """Print reply to terminal."""
    print(f"\n{text}\n> ", end="", flush=True)

async def poll(inbox_queue: deque) -> None:
    """No polling needed — input thread handles it."""
    pass

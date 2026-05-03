# core/logging_setup.py
# ============================================================
# Project Kid — Centralised Logging
#
# Every module in the project calls:
#   import logging
#   log = logging.getLogger(__name__)
#
# This file configures the root logger once at startup.
# The result is a unified log where every line is prefixed
# with its module path, making it obvious which plugin
# produced which output.
#
# Example output:
#   2024-01-15 14:23:01 | core.engine       | INFO  | Wake cycle 42
#   2024-01-15 14:23:02 | actions.wikipedia | INFO  | Fetched: "Mycology"
#   2024-01-15 14:23:04 | interfaces.telegram | INFO | Message from davenport
# ============================================================

import logging
import sys
from pathlib import Path

from rich.logging import RichHandler


def setup(log_level: str = "INFO", log_file: Path | None = None) -> None:
    """
    Configure the root logger. Call once at process startup (in kid.py).
    Subsequent calls are no-ops due to the guard below.

    Args:
        log_level: "DEBUG" | "INFO" | "WARNING" | "ERROR"
        log_file:  Optional path to write logs to (in addition to stdout).
                   Typically personas/<name>/kid.log
    """
    root = logging.getLogger()

    # Guard: don't configure twice (e.g. during tests)
    if root.handlers:
        return

    level = getattr(logging, log_level.upper(), logging.INFO)
    root.setLevel(level)

    # ── Console handler — Rich for pretty terminal output ────
    console_handler = RichHandler(
        rich_tracebacks=True,
        markup=True,
        show_time=True,
        show_path=True,
    )
    console_handler.setLevel(level)
    root.addHandler(console_handler)

    # ── File handler — plain text for tail/grep ──────────────
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(level)
        file_handler.setFormatter(logging.Formatter(
            fmt="%(asctime)s | %(name)-30s | %(levelname)-7s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))
        root.addHandler(file_handler)

    # Quieten noisy third-party loggers
    for noisy in ("httpx", "httpcore", "telegram", "apscheduler", "chromadb"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    logging.getLogger("core.logging_setup").info(
        "Logging initialised | level=%s | file=%s", log_level, log_file or "none"
    )

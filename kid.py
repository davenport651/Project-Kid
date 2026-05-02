#!/usr/bin/env python3
# kid.py
# ============================================================
# Project Kid — Entry Point
#
# Usage:
#   python kid.py --persona william
#   python kid.py --persona william --dry-run
#   python kid.py --persona william --once
#
# First time? Run the configurator first:
#   python configurator.py
#
# tmux quickstart:
#   tmux new-session -s kid
#   source venv/bin/activate
#   python kid.py --persona william
#   [Ctrl+B D to detach]
#   tmux attach -t kid
# ============================================================

import argparse
import asyncio
import sys
from pathlib import Path

if sys.stdout and getattr(sys.stdout, 'encoding', '').lower() != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')
if sys.stderr and getattr(sys.stderr, 'encoding', '').lower() != 'utf-8':
    sys.stderr.reconfigure(encoding='utf-8')

try:
    import tomllib
except ImportError:
    try:
        import tomli as tomllib
    except ImportError:
        print("ERROR: tomli is required on Python < 3.11. Run: pip install tomli")
        sys.exit(1)

from dotenv import load_dotenv


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Project Kid — AI character engine",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  python kid.py --persona william
  python kid.py --persona seraphina --dry-run
  python kid.py --persona william --once
  python configurator.py          (interactive setup)
        """,
    )
    p.add_argument("--persona", required=True,
                   help="Name of the persona folder under personas/")
    p.add_argument("--dry-run", action="store_true",
                   help="Simulate all external posts — nothing is actually sent")
    p.add_argument("--once", action="store_true",
                   help="Run one wake cycle then exit (useful for testing)")
    p.add_argument("--log-level", default=None,
                   choices=["DEBUG", "INFO", "WARNING", "ERROR"],
                   help="Override log level from config.toml")
    return p.parse_args()


async def main() -> None:
    load_dotenv()
    args     = parse_args()
    base_dir = Path(__file__).parent.resolve()

    # ── Resolve persona dir ───────────────────────────────────
    persona_dir = base_dir / "personas" / args.persona
    if not persona_dir.exists():
        print(f"ERROR: Persona directory not found: {persona_dir}")
        print(f"       Create it and add soul files, or run: python configurator.py")
        sys.exit(1)

    # ── Load config.toml ──────────────────────────────────────
    config_file = base_dir / "config.toml"
    if not config_file.exists():
        print("ERROR: config.toml not found.")
        print("       Run: python configurator.py  to generate it.")
        sys.exit(1)

    with open(config_file, "rb") as f:
        config = tomllib.load(f)

    # ── Setup logging ─────────────────────────────────────────
    from logging_setup import setup as setup_logging

    log_level = args.log_level or config.get("logging", {}).get("level", "INFO")
    log_file  = (
        persona_dir / "kid.log"
        if config.get("logging", {}).get("log_to_file", True)
        else None
    )
    setup_logging(log_level=log_level, log_file=log_file)

    import logging
    log = logging.getLogger("kid")

    log.info("=" * 60)
    log.info("Project Kid starting")
    log.info("Persona:  %s", args.persona)
    log.info("Dry run:  %s", args.dry_run)
    log.info("One shot: %s", args.once)
    log.info("=" * 60)

    # ── One-shot: collapse sleep window to zero ───────────────
    if args.once:
        config.setdefault("loop", {})
        config["loop"]["sleep_min"] = 0
        config["loop"]["sleep_max"] = 0
        # The engine will complete one cycle and then sleep 0 seconds.
        # We cancel the task from outside after the first cycle.
        # TODO: add a cleaner one-shot flag to the engine itself.

    # ── Start engine ──────────────────────────────────────────
    from engine import Engine

    engine = Engine(
        persona_dir=persona_dir,
        config=config,
        dry_run=args.dry_run,
    )

    try:
        if args.once:
            # Run one cycle with a timeout so it doesn't loop forever
            await asyncio.wait_for(engine.run(), timeout=600)
        else:
            await engine.run()
    except asyncio.TimeoutError:
        log.info("One-shot cycle complete.")
    except KeyboardInterrupt:
        log.info("Keyboard interrupt — shutting down...")
    finally:
        log.info("Project Kid shut down.")


if __name__ == "__main__":
    asyncio.run(main())

# core/engine.py
# ============================================================
# Project Kid — The Engine (Thin Orchestrator)
#
# This file should RARELY need to change. All interesting
# behaviour lives in plugins. The engine's only jobs are:
#
#   1. Load soul files and build the PluginContext
#   2. Start/stop all loaded interface plugins
#   3. Run the Triune Loop:
#       a. Drain inbox_queue → Reply Pipeline
#       b. Idle too long?   → roll for an Autonomous Action
#   4. After each action: summarise → store in memory
#   5. Persist state.json
#
# If you find yourself editing engine.py for a new feature,
# that feature should probably be a plugin instead.
# ============================================================

import asyncio
import json
import logging
import os
import random
import time
from collections import deque
from pathlib import Path
from typing import Optional

from context import PluginContext
from llm_bridge import LLMBridge
from memory_manager import MemoryManager
from plugin_loader import LoadedAction, LoadedInterface, PluginLoader

log = logging.getLogger(__name__)

# Shared inbox queue. Interface plugins push to this;
# the engine drains it each wake cycle.
inbox_queue: deque[dict] = deque()


class Engine:
    """
    The Triune Engine. Instantiated once by kid.py, run via engine.run().
    """

    def __init__(self, persona_dir: Path, config: dict, dry_run: bool = False):
        """
        Args:
            persona_dir: Resolved path to the active persona folder.
            config:      Parsed config dict (from config.toml at project root).
            dry_run:     If True, external posts are logged but not sent.
        """
        self.persona_dir  = persona_dir
        self.persona_name = persona_dir.name
        self.config       = config
        self.dry_run      = dry_run
        self._running     = False

        # ── Core services ────────────────────────────────────
        llm_cfg   = config.get("llm", {})
        self.llm  = LLMBridge(
            host=llm_cfg.get("host", "http://localhost:11434"),
            neocortex_model=llm_cfg.get("neocortex_model", "gemma2:27b"),
            embed_model=llm_cfg.get("embed_model", "nomic-embed-text"),
            default_params=llm_cfg.get("defaults", {}),
            backend=llm_cfg.get("backend", "ollama"),
            api_key=os.environ.get("LLM_API_KEY", ""),
            embed_strategy=llm_cfg.get("embed_strategy", "api"),
        )
        self.memory = MemoryManager(persona_dir)

        # ── Plugin loader ────────────────────────────────────
        base_dir = Path(__file__).parent
        self.loader = PluginLoader(
            actions_dir=base_dir / "actions",
            interfaces_dir=base_dir / "interfaces",
            persona_toml=persona_dir / "persona.toml",
        )
        self.loader.load_all()
        log.info("\n%s", self.loader.summary())

        # ── Soul files ───────────────────────────────────────
        self._persona_files = self._load_soul_files()

        # ── Active interfaces registry ───────────────────────
        # Populated in start(). Maps interface name → LoadedInterface.
        self._active_interfaces: dict[str, LoadedInterface] = {}

        log.info("Engine initialised | persona=%s | dry_run=%s",
                 self.persona_name, dry_run)

    # ── Lifecycle ────────────────────────────────────────────

    async def run(self) -> None:
        """Start interfaces, enter the main loop. Called by kid.py."""
        await self._start_interfaces()
        self._running = True
        try:
            await self._main_loop()
        finally:
            await self._stop_interfaces()

    async def _start_interfaces(self) -> None:
        """Call start() on every loaded interface plugin."""
        for iface in self.loader.get_interfaces():
            log.info("Starting interface: %s", iface.name)
            try:
                await iface.start(inbox_queue)
                self._active_interfaces[iface.name] = iface
            except Exception as e:
                log.error("Interface %s failed to start: %s", iface.name, e, exc_info=True)

    async def _stop_interfaces(self) -> None:
        """Call stop() on every active interface plugin."""
        for name, iface in self._active_interfaces.items():
            log.info("Stopping interface: %s", name)
            try:
                await iface.stop()
            except Exception as e:
                log.error("Interface %s failed to stop cleanly: %s", name, e)

    # ── Main Loop ────────────────────────────────────────────

    async def _main_loop(self) -> None:
        """
        The Reptilian Wake & Check loop.
        Sleeps between cycles; interval configurable in config.toml.
        """
        loop_cfg  = self.config.get("loop", {})
        sleep_min = loop_cfg.get("sleep_min", 300)
        sleep_max = loop_cfg.get("sleep_max", 3600)
        idle_thresh = loop_cfg.get("idle_action_threshold", 7200)

        cycle = 0
        while self._running:
            cycle += 1
            log.info("─── Wake cycle %d ─────────────────────────────────", cycle)

            state = self._load_state()

            # ── Step 1: Poll interface-specific inboxes ──────
            # (Interfaces push asynchronously; Moltbook-style
            #  polling interfaces check here)
            await self._poll_interfaces(state)

            # ── Step 2: Drain inbox or take autonomous action ─
            if len(inbox_queue) > 0:
                log.info("Inbox has %d item(s) — sorting by priority", len(inbox_queue))
                # Sort inbox: highest priority first
                sorted_items = sorted(inbox_queue, key=lambda i: i.get("priority", 0), reverse=True)
                inbox_queue.clear()
                inbox_queue.extend(sorted_items)

                while inbox_queue:
                    item = inbox_queue.popleft()
                    priority = item.get("priority", 0)
                    log.info("Processing item | source=%s | priority=%d", item.get("source"), priority)

                    # Console command: TRIGGER_AUTONOMOUS_ACTION
                    if item.get("is_command") and item.get("text") == "TRIGGER_AUTONOMOUS_ACTION":
                        await self._autonomous_pipeline(state)
                        continue

                    await self._reply_pipeline(item, state)

                    # After processing high-priority (interactive) items,
                    # skip autonomous actions this cycle.
                    if priority >= 100:
                        log.info("Interactive message processed — skipping autonomous action this cycle.")
                        state["last_interaction_ts"] = int(time.time())
                        self._save_state(state)
                        # Fall through to sleep, but wake on new input
                        break

                # Only enter autonomous/idle if we processed the full inbox
                # without hitting a high-priority break above
                if len(inbox_queue) == 0 and priority < 100:
                    await self._maybe_autonomous(state, idle_thresh)
            else:
                await self._maybe_autonomous(state, idle_thresh)

            self._save_state(state)

            sleep_for = random.randint(sleep_min, sleep_max)
            log.info("Sleeping %ds until next cycle.", sleep_for)
            await self._interruptible_sleep(sleep_for)

    async def _interruptible_sleep(self, seconds: int) -> None:
        """Sleep that can be interrupted by console input."""
        try:
            from interfaces.console.interface import console_wake
            end = time.time() + seconds
            while time.time() < end:
                remaining = end - time.time()
                console_wake.wait(timeout=min(remaining, 1.0))
                if console_wake.is_set():
                    console_wake.clear()
                    log.info("Console input interrupted sleep — waking early.")
                    return
        except ImportError:
            await asyncio.sleep(seconds)

    async def _maybe_autonomous(self, state: dict, idle_thresh: int) -> None:
        """Decide whether to run autonomous action based on idle time."""
        idle = time.time() - state.get("last_action_ts", 0)
        if idle >= idle_thresh:
            log.info("Idle %.0fs ≥ threshold %ds — autonomous action", idle, idle_thresh)
            await self._autonomous_pipeline(state)
        else:
            log.info("Idle %.0fs — below threshold (%ds), resting", idle, idle_thresh)

    # ── Autonomous Action Pipeline ───────────────────────────

    async def _autonomous_pipeline(self, state: dict) -> None:
        """
        Roll for an action, run it, summarise, and store the result in memory.
        The action is chosen by weighted random selection from loaded plugins.
        """
        actions = self.loader.get_actions()
        if not actions:
            log.warning("No action plugins loaded — nothing to do autonomously.")
            return

        # Normalise weights to sum to 1.0
        total  = sum(a.weight for a in actions)
        action: LoadedAction = random.choices(
            population=actions,
            weights=[a.weight / total for a in actions],
            k=1
        )[0]

        log.info("Autonomous action selected: %s (weight=%.2f)", action.name, action.weight)

        ctx = self._build_context(state, incoming_text="")

        try:
            result_text: str = await action.run(ctx)
        except Exception as e:
            log.error("Action '%s' raised an exception: %s", action.name, e, exc_info=True)
            return

        if result_text:
            # Summarise and store in memory
            summary = self.llm.summarise_as_memory(result_text)
            log.info("Action memory: %s", summary)
            self.memory.add_auto(
                text=summary,
                llm=self.llm,
                importance=0.5,
                source="autonomous",
            )

        state["last_action_ts"]   = int(time.time())
        state["last_action_type"] = action.name

    # ── Reply Pipeline ────────────────────────────────────────

    async def _reply_pipeline(self, inbox_item: dict, state: dict) -> None:
        """
        Process one inbox item and send a reply via the originating interface.

        inbox_item keys:
            source   str   — interface plugin name
            sender   str   — username / user ID
            text     str   — message body
            raw      any   — original object (for replying)
            ts       float — arrival timestamp
        """
        source    = inbox_item.get("source", "unknown")
        sender    = inbox_item.get("sender", "unknown")
        user_text = inbox_item.get("text", "")

        log.info("Reply pipeline | source=%s | sender=%s | text='%s...'",
                 source, sender, user_text[:60])

        ctx = self._build_context(
            state=state,
            incoming_text=user_text,
            extra={"inbox_item": inbox_item},
        )

        # Build full system prompt with semantic + recent memories
        system_prompt = self._assemble_system_prompt(ctx, query=user_text)

        # Generate reply
        reply = self.llm.generate(prompt=user_text, system=system_prompt)
        log.info("Reply generated | len=%d | '%s...'", len(reply), reply[:80])

        # Send reply back through the originating interface
        iface = self._active_interfaces.get(source)
        if iface and iface.send and not self.dry_run:
            try:
                await iface.send(inbox_item.get("raw"), reply)
            except Exception as e:
                log.error("Failed to send reply via %s: %s", source, e)
        elif self.dry_run:
            log.info("[DRY RUN] Would send via %s: %s", source, reply[:80])
        else:
            log.warning("No send() capability for interface '%s' — reply not delivered", source)

        # Store exchange as memory
        summary = f"Replied to {sender}: '{user_text[:60]}' → '{reply[:80]}'"
        self.memory.add_auto(text=summary, llm=self.llm, importance=0.7, source="reply")

        state["last_interaction_ts"] = int(time.time())

    # ── Interface Polling ────────────────────────────────────

    async def _poll_interfaces(self, state: dict) -> None:
        """
        Some interfaces (e.g., Moltbook) are polled rather than event-driven.
        Call their poll() function if they expose one.
        """
        for name, iface in self._active_interfaces.items():
            poll_fn = getattr(
                self.loader.get_interface(name), "_module_poll", None
            )
            # Interfaces can also expose a poll() at module level
            # The loader attaches it if found; optional
            if poll_fn and callable(poll_fn):
                try:
                    await poll_fn(inbox_queue)
                except Exception as e:
                    log.error("Polling interface '%s' failed: %s", name, e)

    # ── Context Assembly ─────────────────────────────────────

    def _build_context(
        self, state: dict, incoming_text: str, extra: dict = None
    ) -> PluginContext:
        """Build a PluginContext for a single action or reply call."""
        return PluginContext(
            persona_dir=self.persona_dir,
            persona_name=self.persona_name,
            state=state,
            memory=self.memory,
            llm=self.llm,
            persona_files=self._persona_files,
            send=self._send_dispatch,
            dry_run=self.dry_run,
            extra=extra or {},
        )

    def _assemble_system_prompt(self, ctx: PluginContext, query: str = "") -> str:
        """
        Retrieve memories, inject lorebook, and assemble the full system prompt.
        """
        # Semantic memory retrieval
        if query:
            semantic = self.memory.retrieve(
                query_embedding=self.llm.embed(query),
                k=self.config.get("memory", {}).get("retrieval_k", 5),
            )
        else:
            semantic = []

        recent = self.memory.retrieve_recent(
            k=self.config.get("memory", {}).get("recent_k", 3)
        )

        # Deduplicate
        seen = set(m["id"] for m in semantic)
        combined = semantic + [m for m in recent if m["id"] not in seen]
        memories_block = self.memory.format_for_prompt(combined)

        # Lorebook injection
        lore = ctx.get_lorebook_injection(query) if query else ""
        if lore:
            memories_block = f"[WORLD INFO]\n{lore}\n\n[MEMORIES]\n{memories_block}"

        # State as natural language
        state_text = (
            f"You are currently at: {ctx.state.get('current_location', 'unknown')}. "
            f"Mood: {ctx.state.get('current_mood', 'neutral')}."
        )

        return self.llm.build_system_prompt(
            character_block=ctx.get_soul("character"),
            style_block=ctx.get_soul("style"),
            values_block=ctx.get_soul("values"),
            state_block=state_text,
            memories_block=memories_block,
        )

    # ── Dispatch send() to interfaces ────────────────────────

    async def _send_dispatch(
        self, interface_name: Optional[str], target: any, text: str
    ) -> None:
        """
        ctx.send() implementation — routes outgoing messages.

        Args:
            interface_name: Name of the interface to use, or None to broadcast.
            target:         Interface-specific target (chat_id, message object, etc.)
            text:           Message to send.
        """
        if self.dry_run:
            log.info("[DRY RUN] send | via=%s | '%s...'", interface_name or "broadcast", text[:60])
            return

        if interface_name:
            iface = self._active_interfaces.get(interface_name)
            if iface and iface.send:
                await iface.send(target, text)
            else:
                log.warning("send() called for '%s' but no send capability.", interface_name)
        else:
            # Broadcast to all bidirectional interfaces
            for name, iface in self._active_interfaces.items():
                if iface.itype == "bidirectional" and iface.send:
                    await iface.send(target, text)

    # ── Soul Files ───────────────────────────────────────────

    def _load_soul_files(self) -> dict:
        """Load all static persona files into a dict for PluginContext."""
        files = {}

        # character.json → rendered text block
        char_file = self.persona_dir / "character.json"
        if char_file.exists():
            data = json.loads(char_file.read_text(encoding="utf-8"))
            cd   = data.get("char_data", data)
            files["character"] = (
                f"Name: {cd.get('name', '')}\n"
                f"Description: {cd.get('description', '')}\n"
                f"Personality: {cd.get('personality', '')}\n"
                f"Voice example: {cd.get('first_mes', '')}"
            )
        else:
            files["character"] = "(No character.json found)"

        for key, filename in [("style", "style.md"), ("values", "values.md")]:
            p = self.persona_dir / filename
            files[key] = p.read_text(encoding="utf-8") if p.exists() else ""

        lore_file = self.persona_dir / "lorebook.json"
        files["lorebook"] = (
            json.loads(lore_file.read_text(encoding="utf-8"))
            if lore_file.exists() else {}
        )

        log.info("Soul files loaded | keys=%s", list(files.keys()))
        return files

    # ── State I/O ────────────────────────────────────────────

    def _load_state(self) -> dict:
        state_file = self.persona_dir / "state.json"
        defaults = {
            "current_location":   "home",
            "current_mood":       "neutral",
            "last_interaction_ts": 0,
            "last_action_ts":     0,
            "last_action_type":   None,
        }
        if not state_file.exists():
            return defaults
        try:
            data = json.loads(state_file.read_text(encoding="utf-8"))
            return {**defaults, **data}
        except Exception as e:
            log.warning("Could not read state.json: %s — using defaults", e)
            return defaults

    def _save_state(self, state: dict) -> None:
        state_file = self.persona_dir / "state.json"
        try:
            state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")
        except Exception as e:
            log.error("Could not save state.json: %s", e)

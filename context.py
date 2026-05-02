# core/context.py
# ============================================================
# Project Kid — Plugin Context Object
#
# This is the single object that the engine passes to every
# action plugin's run() function. It contains everything a
# plugin could ever need — the LLM, memory, state, persona
# files, and a send() callback for replying via any interface.
#
# WHY A CONTEXT OBJECT?
# ---------------------
# Instead of each plugin importing modules directly (which
# creates hidden dependencies and makes testing hard), we
# inject everything through this context. A plugin declares
# what it needs via its MANIFEST["requires"] and the engine
# verifies it's available before calling run().
#
# This also means you can unit-test a plugin by constructing
# a fake context — no real Ollama or ChromaDB needed.
# ============================================================

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

log = logging.getLogger(__name__)


@dataclass
class PluginContext:
    """
    Standard context bundle passed to every action plugin.

    Attributes:
        persona_dir:    Path to the active persona's folder.
        persona_name:   Short name (e.g. "william").
        state:          Current state dict (loaded from state.json).
                        Mutate this freely — engine saves it after run().
        memory:         The MemoryManager instance for this persona.
        llm:            The LLMBridge instance (call llm.generate(), llm.embed()).
        persona_files:  Dict of loaded soul file contents:
                            "character" → str block
                            "style"     → str (style.md)
                            "values"    → str (values.md)
                            "lorebook"  → dict (parsed lorebook.json)
        send:           Async callable to send a message back through any interface.
                        Signature: await ctx.send(interface_name, target, text)
                        Pass None for interface_name to broadcast to all bidirectional.
        dry_run:        If True, plugins should log but not make external calls.
        extra:          Arbitrary dict for plugin-specific data not covered above.
                        Used by interface reply pipeline to pass the original message.
    """

    persona_dir:    Path
    persona_name:   str
    state:          dict
    memory:         Any   # MemoryManager — typed as Any to avoid circular import
    llm:            Any   # LLMBridge     — typed as Any to avoid circular import
    persona_files:  dict  = field(default_factory=dict)
    send:           Optional[Callable[..., Awaitable[None]]] = None
    dry_run:        bool  = False
    extra:          dict  = field(default_factory=dict)

    def get_soul(self, key: str, fallback: str = "") -> str:
        """
        Convenience: retrieve a soul file string by key.

        Args:
            key:      "character" | "style" | "values"
            fallback: Return this if the key is missing.
        """
        return self.persona_files.get(key, fallback)

    def get_lorebook_injection(self, text: str) -> str:
        """
        Scan text against lorebook keywords and return matching entries.
        Useful for actions that receive user-facing text.

        Args:
            text: Incoming message or content to scan.

        Returns:
            Concatenated lorebook entries whose keywords appear in text.
            Empty string if no matches.
        """
        lorebook   = self.persona_files.get("lorebook", {})
        injections = []

        for entry in lorebook.get("entries", []):
            keywords = entry.get("keywords", [])
            if any(kw.lower() in text.lower() for kw in keywords):
                injections.append(entry.get("content", ""))

        result = "\n\n".join(injections)
        if result:
            log.debug("Lorebook injection triggered | matches=%d", len(injections))
        return result

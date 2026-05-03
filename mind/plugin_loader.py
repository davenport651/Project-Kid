# core/plugin_loader.py
# ============================================================
# Project Kid — Plugin Loader
#
# This is the heart of the modular architecture. On startup,
# it scans the /actions/ and /interfaces/ directories,
# imports each plugin, validates it against the required
# contract, and registers it for use by the engine.
#
# PLUGIN CONTRACTS
# ────────────────
# ACTION PLUGIN  (actions/<name>/action.py)
#   Required:
#     MANIFEST  dict  — see ActionManifest below
#     run(ctx)  async fn  — receives PluginContext, returns str
#
# INTERFACE PLUGIN  (interfaces/<name>/interface.py)
#   Required:
#     MANIFEST  dict  — see InterfaceManifest below
#     start(inbox_queue)  async fn  — begin listening
#     stop()              async fn  — clean shutdown
#   Optional:
#     send(target, text)  async fn  — only for bidirectional interfaces
#
# HOW ENABLING/DISABLING WORKS
# ────────────────────────────
# Each plugin has a <name>.toml sidecar with enabled = true/false.
# The persona folder has a persona.toml that can further restrict
# which plugins are active for that persona.
# The loader respects both: a plugin must be enabled globally
# AND enabled (or not listed) in the persona config.
#
# ADDING A NEW PLUGIN
# ───────────────────
# 1. Create actions/<your_name>/  (or interfaces/<your_name>/)
# 2. Add action.toml  (copy any existing one as a template)
# 3. Add action.py with MANIFEST dict and async run(ctx) function
# 4. Done. The loader finds it automatically on next startup.
# ============================================================

import importlib
import importlib.util
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

try:
    import tomllib          # Python 3.11+
except ImportError:
    import tomli as tomllib  # pip install tomli  (Python 3.10)

log = logging.getLogger(__name__)


# ── Manifest Schemas ─────────────────────────────────────────
# These are the keys each plugin's MANIFEST dict must contain.
# The loader validates against these at import time so you get
# a clear error on startup rather than a cryptic failure later.

REQUIRED_ACTION_MANIFEST_KEYS = {
    "name",         # str  — machine-readable ID, e.g. "research_wikipedia"
    "description",  # str  — human-readable one-liner shown in configurator
    "weight",       # float — default probability weight (0.0–1.0)
}

REQUIRED_INTERFACE_MANIFEST_KEYS = {
    "name",         # str  — machine-readable ID, e.g. "telegram"
    "description",  # str  — human-readable one-liner
    "type",         # str  — "bidirectional" | "sensor" | "output-only"
    "requires",     # list[str] — env var names this plugin needs
}


# ── Loaded Plugin Containers ─────────────────────────────────

@dataclass
class LoadedAction:
    """A successfully loaded and validated action plugin."""
    name:        str
    description: str
    weight:      float
    run:         Callable          # async (ctx: PluginContext) -> str
    toml_config: dict = field(default_factory=dict)
    plugin_dir:  Optional[Path] = None

    def __repr__(self):
        return f"<Action '{self.name}' weight={self.weight:.2f}>"


@dataclass
class LoadedInterface:
    """A successfully loaded and validated interface plugin."""
    name:        str
    description: str
    itype:       str               # "bidirectional" | "sensor" | "output-only"
    requires:    list[str]
    start:       Callable          # async (inbox_queue) -> None
    stop:        Callable          # async () -> None
    send:        Optional[Callable] = None  # async (target, text) -> None
    toml_config: dict = field(default_factory=dict)
    plugin_dir:  Optional[Path] = None

    def __repr__(self):
        return f"<Interface '{self.name}' type={self.itype}>"


# ── Loader ───────────────────────────────────────────────────

class PluginLoader:
    """
    Discovers, validates, and registers all plugins.

    Usage:
        loader = PluginLoader(
            actions_dir=Path("body/actions"),
            interfaces_dir=Path("body/interfaces"),
            persona_toml=Path("personas/william/persona.toml"),
        )
        loader.load_all()

        actions    = loader.get_actions()    # List[LoadedAction]
        interfaces = loader.get_interfaces() # List[LoadedInterface]
    """

    def __init__(
        self,
        actions_dir:    Path,
        interfaces_dir: Path,
        persona_toml:   Optional[Path] = None,
    ):
        self.actions_dir    = actions_dir
        self.interfaces_dir = interfaces_dir
        self.persona_toml   = persona_toml

        self._actions:    list[LoadedAction]    = []
        self._interfaces: list[LoadedInterface] = []

        # Load persona-level overrides (may not exist for all personas)
        self._persona_cfg = self._load_toml_safe(persona_toml) if persona_toml else {}

    # ── Public API ───────────────────────────────────────────

    def load_all(self) -> None:
        """Discover and load all enabled plugins. Call once at startup."""
        log.info("══ Plugin loader starting ══════════════════════════════")
        self._load_actions()
        self._load_interfaces()
        log.info(
            "══ Plugin loader complete | actions=%d | interfaces=%d ══",
            len(self._actions), len(self._interfaces)
        )

    def get_actions(self) -> list[LoadedAction]:
        """Return all successfully loaded action plugins."""
        return list(self._actions)

    def get_interfaces(self) -> list[LoadedInterface]:
        """Return all successfully loaded interface plugins."""
        return list(self._interfaces)

    def get_action(self, name: str) -> Optional[LoadedAction]:
        """Look up a specific action by name."""
        return next((a for a in self._actions if a.name == name), None)

    def get_interface(self, name: str) -> Optional[LoadedInterface]:
        """Look up a specific interface by name."""
        return next((i for i in self._interfaces if i.name == name), None)

    def summary(self) -> str:
        """Return a human-readable summary of loaded plugins for the startup log."""
        lines = ["Loaded plugins:"]
        lines.append("  Actions:")
        for a in self._actions:
            lines.append(f"    ✓ {a.name:<25} weight={a.weight:.2f}  — {a.description}")
        lines.append("  Interfaces:")
        for i in self._interfaces:
            lines.append(f"    ✓ {i.name:<25} type={i.itype:<15} — {i.description}")
        return "\n".join(lines)

    # ── Action Loading ───────────────────────────────────────

    def _load_actions(self) -> None:
        """Scan the actions directory and load all enabled action plugins."""
        if not self.actions_dir.exists():
            log.warning("Actions directory not found: %s", self.actions_dir)
            return

        # Persona-level enabled list (if specified, only these load)
        persona_enabled = self._persona_cfg.get("actions", {}).get("enabled", None)

        for plugin_dir in sorted(self.actions_dir.iterdir()):
            if not plugin_dir.is_dir():
                continue

            plugin_name = plugin_dir.name
            log.debug("Examining action plugin: %s", plugin_name)

            # Check persona-level filter
            if persona_enabled is not None and plugin_name not in persona_enabled:
                log.info("  ↷ %s — skipped (not in persona.toml enabled list)", plugin_name)
                continue

            # Load toml config
            toml_path = plugin_dir / "action.toml"
            toml_cfg  = self._load_toml_safe(toml_path)

            # Check enabled flag in toml
            if not toml_cfg.get("action", {}).get("enabled", True):
                log.info("  ↷ %s — disabled in action.toml", plugin_name)
                continue

            # Import the Python module
            module = self._import_plugin_module(plugin_dir / "action.py", plugin_name)
            if module is None:
                continue

            # Validate manifest
            manifest = getattr(module, "MANIFEST", None)
            if not self._validate_manifest(manifest, REQUIRED_ACTION_MANIFEST_KEYS, plugin_name):
                continue

            # Validate run() function
            run_fn = getattr(module, "run", None)
            if run_fn is None or not callable(run_fn):
                log.error("  ✗ %s — missing 'run' function in action.py", plugin_name)
                continue

            # Merge toml settings into manifest (toml overrides code defaults)
            toml_action_cfg = toml_cfg.get("action", {})
            weight = toml_action_cfg.get("weight", manifest.get("weight", 0.1))

            action = LoadedAction(
                name=manifest["name"],
                description=toml_action_cfg.get("description", manifest.get("description", "")),
                weight=float(weight),
                run=run_fn,
                toml_config=toml_cfg,
                plugin_dir=plugin_dir,
            )
            self._actions.append(action)
            log.info("  ✓ Action loaded: %-25s weight=%.2f", action.name, action.weight)

    # ── Interface Loading ────────────────────────────────────

    def _load_interfaces(self) -> None:
        """Scan the interfaces directory and load all enabled interface plugins."""
        if not self.interfaces_dir.exists():
            log.warning("Interfaces directory not found: %s", self.interfaces_dir)
            return

        persona_enabled = self._persona_cfg.get("interfaces", {}).get("enabled", None)

        for plugin_dir in sorted(self.interfaces_dir.iterdir()):
            if not plugin_dir.is_dir():
                continue

            plugin_name = plugin_dir.name
            log.debug("Examining interface plugin: %s", plugin_name)

            if persona_enabled is not None and plugin_name not in persona_enabled:
                log.info("  ↷ %s — skipped (not in persona.toml enabled list)", plugin_name)
                continue

            toml_path = plugin_dir / "interface.toml"
            toml_cfg  = self._load_toml_safe(toml_path)

            if not toml_cfg.get("interface", {}).get("enabled", True):
                log.info("  ↷ %s — disabled in interface.toml", plugin_name)
                continue

            module = self._import_plugin_module(plugin_dir / "interface.py", plugin_name)
            if module is None:
                continue

            manifest = getattr(module, "MANIFEST", None)
            if not self._validate_manifest(manifest, REQUIRED_INTERFACE_MANIFEST_KEYS, plugin_name):
                continue

            # Validate required functions
            start_fn = getattr(module, "start", None)
            stop_fn  = getattr(module, "stop", None)
            send_fn  = getattr(module, "send", None)  # Optional

            if not callable(start_fn) or not callable(stop_fn):
                log.error("  ✗ %s — missing start() or stop() in interface.py", plugin_name)
                continue

            # Check required env vars are present (warn, don't block)
            self._check_env_vars(manifest.get("requires", []), plugin_name)

            iface = LoadedInterface(
                name=manifest["name"],
                description=toml_cfg.get("interface", {}).get("description", manifest.get("description", "")),
                itype=manifest["type"],
                requires=manifest.get("requires", []),
                start=start_fn,
                stop=stop_fn,
                send=send_fn if callable(send_fn) else None,
                toml_config=toml_cfg,
                plugin_dir=plugin_dir,
            )
            self._interfaces.append(iface)
            log.info(
                "  ✓ Interface loaded: %-20s type=%-15s send=%s",
                iface.name, iface.itype, "yes" if iface.send else "no"
            )

    # ── Helpers ──────────────────────────────────────────────

    @staticmethod
    def _import_plugin_module(py_path: Path, plugin_name: str) -> Any:
        """
        Dynamically import a plugin Python file.
        Returns the module object, or None if import failed.
        """
        if not py_path.exists():
            log.error("  ✗ %s — Python file not found: %s", plugin_name, py_path)
            return None

        try:
            spec   = importlib.util.spec_from_file_location(
                f"plugins.{plugin_name}", str(py_path)
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module
        except Exception as e:
            log.error("  ✗ %s — import failed: %s", plugin_name, e, exc_info=True)
            return None

    @staticmethod
    def _validate_manifest(manifest: Any, required_keys: set, plugin_name: str) -> bool:
        """
        Verify a plugin's MANIFEST dict contains all required keys.
        Returns True if valid, False otherwise.
        """
        if not isinstance(manifest, dict):
            log.error("  ✗ %s — MANIFEST missing or not a dict", plugin_name)
            return False

        missing = required_keys - manifest.keys()
        if missing:
            log.error("  ✗ %s — MANIFEST missing keys: %s", plugin_name, missing)
            return False

        return True

    @staticmethod
    def _load_toml_safe(toml_path: Optional[Path]) -> dict:
        """
        Load a TOML file, returning an empty dict if missing or malformed.
        Never raises — plugins with broken TOML fall back to defaults.
        """
        if not toml_path or not toml_path.exists():
            return {}
        try:
            with open(toml_path, "rb") as f:
                return tomllib.load(f)
        except Exception as e:
            log.warning("Failed to parse TOML: %s — %s", toml_path, e)
            return {}

    @staticmethod
    def _check_env_vars(required: list[str], plugin_name: str) -> None:
        """
        Warn if required environment variables are not set.
        Does not block loading — lets the plugin decide how to handle absence.
        """
        import os
        missing = [v for v in required if not os.environ.get(v)]
        if missing:
            log.warning(
                "  ⚠ %s — env vars not set (plugin may not work): %s",
                plugin_name, ", ".join(missing)
            )

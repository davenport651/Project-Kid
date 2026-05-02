#!/usr/bin/env python3
# configurator.py
# ============================================================
# Project Kid — Interactive Configurator
#
# A standalone terminal UI that wraps all config files into
# one place. Run this on first install, or any time you want
# to change settings without hunting through TOML files.
#
# Usage:
#   python configurator.py
#
# What it does:
#   - Guides first-time setup (.env, config.toml)
#   - Shows all loaded plugins and lets you enable/disable them
#   - Sets per-persona plugin lists (persona.toml)
#   - Edits action weights interactively
#   - Verifies Ollama is reachable and models are pulled
#   - Verifies env vars for each active interface
#   - Runs a one-shot test cycle so you can see output before
#     committing to the full loop
# ============================================================

import base64
import json
import os
import re
import sys
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import URLError

# ── Dependency check before anything else ────────────────────
def _check_deps():
    missing = []
    for pkg in ("rich", "dotenv"):
        try:
            __import__(pkg.replace("-", "_"))
        except ImportError:
            missing.append(pkg)
    if missing:
        print(f"Missing packages: {', '.join(missing)}")
        print("Run: pip install -r requirements.txt")
        sys.exit(1)

_check_deps()

import subprocess

try:
    import tomllib
except ImportError:
    try:
        import tomli as tomllib
    except ImportError:
        print("Install tomli: pip install tomli")
        sys.exit(1)

# tomli_w for writing toml (tomllib is read-only)
try:
    import tomli_w
    _CAN_WRITE_TOML = True
except ImportError:
    _CAN_WRITE_TOML = False

from dotenv import dotenv_values, set_key
from rich import print as rprint
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table
from rich import box

console = Console()
BASE_DIR = Path(__file__).parent.resolve()


# ── Entry Point ───────────────────────────────────────────────

def main():
    console.clear()
    _header()

    while True:
        choice = _main_menu()

        if choice == "1":
            setup_env()
        elif choice == "2":
            setup_llm_backend()
        elif choice == "3":
            manage_plugins()
        elif choice == "4":
            manage_personas()
        elif choice == "5":
            edit_loop_settings()
        elif choice == "6":
            run_health_check()
        elif choice == "7":
            run_test_cycle()
        elif choice == "8":
            import_persona()
        elif choice == "q":
            rprint("\n[dim]Goodbye.[/dim]\n")
            break
        else:
            rprint("[yellow]Unknown option.[/yellow]")


# ── Header ────────────────────────────────────────────────────

def _header():
    console.print(Panel.fit(
        "[bold cyan]Project Kid — Configurator[/bold cyan]\n"
        "[dim]Interactive setup and management tool[/dim]",
        border_style="cyan",
    ))


def _main_menu() -> str:
    console.print()
    console.print("[bold]Main Menu[/bold]")
    console.print("  [cyan]1[/cyan]  Set up .env secrets (API tokens)")
    console.print("  [cyan]2[/cyan]  Set up LLM backend (Ollama / KoboldCpp / custom)")
    console.print("  [cyan]3[/cyan]  Manage plugins (enable/disable, set weights)")
    console.print("  [cyan]4[/cyan]  Manage personas (which plugins each persona uses)")
    console.print("  [cyan]5[/cyan]  Edit loop timing settings")
    console.print("  [cyan]6[/cyan]  Run health check (env vars, connectivity)")
    console.print("  [cyan]7[/cyan]  Run a single test cycle for a persona")
    console.print("  [cyan]8[/cyan]  Import Persona (SillyTavern Card)")
    console.print("  [cyan]q[/cyan]  Quit")
    console.print()
    return Prompt.ask("[cyan]>[/cyan]").strip().lower()


# ── 1. .env Setup ─────────────────────────────────────────────

def setup_env():
    console.print()
    console.print(Panel("[bold]Secrets Setup[/bold] (.env file)", border_style="blue"))

    env_file = BASE_DIR / ".env"
    current  = dotenv_values(env_file) if env_file.exists() else {}

    def _set(key: str, description: str, secret: bool = True):
        existing = current.get(key, "")
        display  = f"[set: {'*' * min(len(existing), 8)}]" if existing else "[not set]"
        rprint(f"\n[bold]{key}[/bold] — {description}")
        rprint(f"  Current: [dim]{display}[/dim]")

        if existing and not Confirm.ask("  Update?", default=False):
            return

        value = Prompt.ask(f"  Enter {key}", password=secret)
        if value.strip():
            if not env_file.exists():
                env_file.touch()
            set_key(str(env_file), key, value.strip())
            rprint(f"  [green]✓ {key} saved.[/green]")

    _set("LLM_API_KEY",             "API key for cloud LLM provider (leave blank for local servers)")
    _set("TELEGRAM_BOT_TOKEN",      "Get from @BotFather on Telegram")
    _set("TELEGRAM_ALLOWED_USER_ID","Your Telegram user ID — get from @userinfobot", secret=False)
    _set("MOLTBOOK_API_KEY",        "Your Moltbook API key")
    _set("MOLTBOOK_USERNAME",       "Your Moltbook username/handle", secret=False)

    console.print()
    rprint("[green]✓ .env update complete.[/green]")


# ── 2. LLM Backend Setup ──────────────────────────────────────

def _probe_backend(url: str, timeout: int = 3) -> bool:
    """Check if a server is responding at the given URL."""
    import requests as _req
    try:
        r = _req.get(url, timeout=timeout)
        return r.status_code < 500
    except Exception:
        return False


def _probe_ollama(host: str) -> bool:
    """Check Ollama by hitting its native /api/tags endpoint."""
    import requests as _req
    try:
        r = _req.get(f"{host}/api/tags", timeout=3)
        r.raise_for_status()
        return True
    except Exception:
        return False


def _probe_kobold(host: str) -> bool:
    """Check KoboldCpp by hitting its /api/v1/info endpoint."""
    import requests as _req
    try:
        r = _req.get(f"{host}/api/v1/info", timeout=3)
        return r.status_code < 500
    except Exception:
        return False


def setup_llm_backend():
    console.print()
    console.print(Panel(
        "[bold]LLM Backend Setup[/bold]\n"
        "[dim]Auto-detects Ollama and KoboldCpp, or enter a custom URL[/dim]",
        border_style="blue",
    ))

    cfg     = _load_config_toml()
    llm_cfg = cfg.get("llm", {})

    # ── Auto-detect backends ─────────────────────────────────
    rprint("\n[bold]Scanning for local LLM servers...[/bold]")

    ollama_host = "http://localhost:11434"
    kobold_host = "http://localhost:5001"

    found_ollama = _probe_ollama(ollama_host)
    found_kobold = _probe_kobold(kobold_host)

    rprint(f"  Ollama   (port 11434)  {'[green]✓ detected[/green]' if found_ollama else '[red]✗ not found[/red]'}")
    rprint(f"  KoboldCpp (port 5001)  {'[green]✓ detected[/green]' if found_kobold else '[red]✗ not found[/red]'}")

    # ── Let user choose ──────────────────────────────────────
    console.print()
    options = []
    if found_ollama:
        options.append(("ollama", ollama_host, "Ollama (localhost:11434)"))
    if found_kobold:
        options.append(("kobold", kobold_host, "KoboldCpp (localhost:5001)"))
    options.append(("custom", "", "Enter a custom URL (cloud API, remote server, etc.)"))

    for i, (_, _, label) in enumerate(options, 1):
        rprint(f"  [cyan]{i}[/cyan]  {label}")

    idx_str = Prompt.ask("\nSelect backend", default="1")
    try:
        idx = int(idx_str) - 1
        backend_type, host, _ = options[idx]
    except (ValueError, IndexError):
        rprint("[red]Invalid selection.[/red]")
        return

    # ── Custom URL entry ─────────────────────────────────────
    if backend_type == "custom":
        host = Prompt.ask("  Enter LLM API base URL (e.g. http://192.168.1.5:11434)")
        if not host.strip():
            rprint("[red]No URL entered — aborting.[/red]")
            return
        host = host.strip().rstrip("/")

        # Try to identify what's running there
        if _probe_ollama(host):
            backend_type = "ollama"
            rprint(f"  [green]✓ Detected Ollama at {host}[/green]")
        elif _probe_kobold(host):
            backend_type = "kobold"
            rprint(f"  [green]✓ Detected KoboldCpp at {host}[/green]")
        elif _probe_backend(host):
            backend_type = "openai_compatible"
            rprint(f"  [green]✓ Server responding at {host}[/green]")
        else:
            rprint(f"  [yellow]⚠ Could not reach {host} — saving anyway[/yellow]")
            backend_type = "openai_compatible"

    # ── Embedding strategy ───────────────────────────────────
    if backend_type == "kobold":
        embed_strategy = "local"
        rprint("\n  [dim]KoboldCpp doesn't serve embeddings — using local CPU embedder.[/dim]")
    elif backend_type == "ollama":
        embed_strategy = "api"
        rprint("\n  [dim]Using Ollama's embeddings API.[/dim]")
    else:
        rprint("\n  Does this server support /v1/embeddings?")
        if Confirm.ask("  Use server for embeddings?", default=True):
            embed_strategy = "api"
        else:
            embed_strategy = "local"
            rprint("  [dim]Using local CPU embedder instead.[/dim]")

    # ── Model names ──────────────────────────────────────────
    current_model = llm_cfg.get("neocortex_model", "gemma2:27b")
    current_embed = llm_cfg.get("embed_model", "nomic-embed-text")

    console.print()
    model = Prompt.ask("  Chat model name", default=current_model)
    if embed_strategy == "api":
        embed_model = Prompt.ask("  Embedding model name", default=current_embed)
    else:
        embed_model = current_embed  # Not used, but keep the config value

    # ── API key hint ─────────────────────────────────────────
    if backend_type == "openai_compatible":
        rprint("\n  [dim]If this server requires an API key, set it in .env:[/dim]")
        rprint("  [dim]  LLM_API_KEY=your-key-here[/dim]")
        rprint("  [dim]  (or use menu option 1 to set secrets)[/dim]")

    # ── Save to config.toml ──────────────────────────────────
    cfg.setdefault("llm", {})
    cfg["llm"]["backend"]        = backend_type
    cfg["llm"]["host"]           = host
    cfg["llm"]["neocortex_model"] = model
    cfg["llm"]["embed_model"]    = embed_model
    cfg["llm"]["embed_strategy"] = embed_strategy

    if _CAN_WRITE_TOML:
        _write_toml_file(BASE_DIR / "config.toml", cfg)
        rprint(f"\n[green]✓ LLM backend configured:[/green]")
        rprint(f"  Backend:    [cyan]{backend_type}[/cyan]")
        rprint(f"  Host:       [cyan]{host}[/cyan]")
        rprint(f"  Model:      [cyan]{model}[/cyan]")
        rprint(f"  Embeddings: [cyan]{embed_strategy}[/cyan]")
    else:
        rprint("[yellow]Install tomli-w to save: pip install tomli-w[/yellow]")

    # ── If Ollama, offer to check models ─────────────────────
    if backend_type == "ollama" and found_ollama:
        console.print()
        if Confirm.ask("Check if required models are pulled?", default=True):
            _check_ollama_models(host, [model, embed_model])


def _check_ollama_models(host: str, models: list):
    """Check and optionally pull Ollama models."""
    import requests as _req
    try:
        r = _req.get(f"{host}/api/tags", timeout=5)
        r.raise_for_status()
        pulled = {m["name"] for m in r.json().get("models", [])}
    except Exception as e:
        rprint(f"[red]✗ Cannot reach Ollama: {e}[/red]")
        return

    for model in models:
        base_name = model.split(":")[0]
        is_pulled = any(base_name in m for m in pulled)
        status    = "[green]✓ pulled[/green]" if is_pulled else "[red]✗ not found[/red]"
        rprint(f"  {model:<35} {status}")
        if not is_pulled:
            if Confirm.ask(f"  Pull {model} now?", default=True):
                rprint(f"  [dim]Running: ollama pull {model}[/dim]")
                subprocess.run(["ollama", "pull", model], check=False)


# ── 3. Plugin Management ──────────────────────────────────────

def manage_plugins():
    console.print()
    console.print(Panel("[bold]Plugin Management[/bold]", border_style="blue"))

    choice = Prompt.ask(
        "  [cyan]a[/cyan] Actions  |  [cyan]i[/cyan] Interfaces  |  [cyan]b[/cyan] Back",
    ).strip().lower()

    if choice == "a":
        _manage_action_plugins()
    elif choice == "i":
        _manage_interface_plugins()


def _manage_action_plugins():
    actions_dir = BASE_DIR / "actions"
    if not actions_dir.exists():
        rprint("[yellow]No actions directory found.[/yellow]")
        return

    plugins = sorted(d for d in actions_dir.iterdir() if d.is_dir())
    if not plugins:
        rprint("[yellow]No action plugins found.[/yellow]")
        return

    table = Table(title="Action Plugins", box=box.ROUNDED, show_lines=True)
    table.add_column("Name", style="cyan")
    table.add_column("Enabled", justify="center")
    table.add_column("Weight", justify="right")
    table.add_column("Description")

    plugin_data = []
    for p in plugins:
        toml  = _load_toml_file(p / "action.toml")
        act   = toml.get("action", {})
        enabled  = act.get("enabled", True)
        weight   = act.get("weight", "?")
        desc     = act.get("description", "")
        name     = act.get("name", p.name)
        table.add_row(
            name,
            "[green]✓[/green]" if enabled else "[red]✗[/red]",
            str(weight),
            desc,
        )
        plugin_data.append((p, toml, act))

    console.print(table)

    if not _CAN_WRITE_TOML:
        rprint("[yellow]Install tomli-w to enable editing: pip install tomli-w[/yellow]")
        return

    if not Confirm.ask("\nEdit a plugin?", default=False):
        return

    idx_str = Prompt.ask("Enter plugin number (1-based)")
    try:
        idx = int(idx_str) - 1
        p, toml, act = plugin_data[idx]
    except (ValueError, IndexError):
        rprint("[red]Invalid selection.[/red]")
        return

    toml_path = p / "action.toml"
    current_enabled = act.get("enabled", True)
    current_weight  = float(act.get("weight", 0.1))

    new_enabled = Confirm.ask("  Enabled?", default=current_enabled)
    new_weight  = float(Prompt.ask("  Weight (0.0–1.0)", default=str(current_weight)))

    toml.setdefault("action", {})
    toml["action"]["enabled"] = new_enabled
    toml["action"]["weight"]  = new_weight

    _write_toml_file(toml_path, toml)
    rprint(f"[green]✓ {p.name} updated.[/green]")


def _manage_interface_plugins():
    ifaces_dir = BASE_DIR / "interfaces"
    if not ifaces_dir.exists():
        rprint("[yellow]No interfaces directory found.[/yellow]")
        return

    plugins = sorted(d for d in ifaces_dir.iterdir() if d.is_dir())
    table = Table(title="Interface Plugins", box=box.ROUNDED, show_lines=True)
    table.add_column("Name", style="cyan")
    table.add_column("Enabled", justify="center")
    table.add_column("Type")
    table.add_column("Requires")
    table.add_column("Description")

    plugin_data = []
    for p in plugins:
        toml  = _load_toml_file(p / "interface.toml")
        iface = toml.get("interface", {})
        enabled = iface.get("enabled", True)
        table.add_row(
            iface.get("name", p.name),
            "[green]✓[/green]" if enabled else "[red]✗[/red]",
            iface.get("type", "?"),
            ", ".join(_get_manifest_requires(p / "interface.py")),
            iface.get("description", ""),
        )
        plugin_data.append((p, toml, iface))

    console.print(table)

    if not _CAN_WRITE_TOML:
        rprint("[yellow]Install tomli-w to enable editing: pip install tomli-w[/yellow]")
        return

    if not Confirm.ask("\nToggle a plugin?", default=False):
        return

    idx_str = Prompt.ask("Enter plugin number (1-based)")
    try:
        idx = int(idx_str) - 1
        p, toml, iface = plugin_data[idx]
    except (ValueError, IndexError):
        rprint("[red]Invalid selection.[/red]")
        return

    toml_path = p / "interface.toml"
    current = iface.get("enabled", True)
    new_val = Confirm.ask("  Enabled?", default=current)
    toml.setdefault("interface", {})
    toml["interface"]["enabled"] = new_val
    _write_toml_file(toml_path, toml)
    rprint(f"[green]✓ {p.name} updated.[/green]")


# ── 4. Persona Management ─────────────────────────────────────

def manage_personas():
    console.print()
    console.print(Panel("[bold]Persona Plugin Configuration[/bold]", border_style="blue"))

    personas_dir = BASE_DIR / "personas"
    personas     = [d for d in personas_dir.iterdir() if d.is_dir()] if personas_dir.exists() else []

    if not personas:
        rprint("[yellow]No personas found in /personas/[/yellow]")
        return

    rprint("Available personas:")
    for i, p in enumerate(personas, 1):
        rprint(f"  [cyan]{i}[/cyan]  {p.name}")

    idx_str = Prompt.ask("Select persona (number)")
    try:
        persona_dir = personas[int(idx_str) - 1]
    except (ValueError, IndexError):
        rprint("[red]Invalid.[/red]")
        return

    toml_path = persona_dir / "persona.toml"
    toml      = _load_toml_file(toml_path)

    # Show current config
    rprint(f"\n[bold]Persona:[/bold] {persona_dir.name}")

    # Actions
    all_actions     = _list_plugins(BASE_DIR / "actions")
    enabled_actions = toml.get("actions", {}).get("enabled", all_actions)
    rprint(f"\n[bold]Actions enabled:[/bold] {enabled_actions}")

    if Confirm.ask("  Edit enabled actions?", default=False):
        rprint("Available actions: " + ", ".join(all_actions))
        raw = Prompt.ask("  Enter enabled action names (comma-separated)")
        enabled_actions = [x.strip() for x in raw.split(",") if x.strip()]
        toml.setdefault("actions", {})["enabled"] = enabled_actions

    # Interfaces
    all_ifaces     = _list_plugins(BASE_DIR / "interfaces")
    enabled_ifaces = toml.get("interfaces", {}).get("enabled", all_ifaces)
    rprint(f"\n[bold]Interfaces enabled:[/bold] {enabled_ifaces}")

    if Confirm.ask("  Edit enabled interfaces?", default=False):
        rprint("Available interfaces: " + ", ".join(all_ifaces))
        raw = Prompt.ask("  Enter enabled interface names (comma-separated)")
        enabled_ifaces = [x.strip() for x in raw.split(",") if x.strip()]
        toml.setdefault("interfaces", {})["enabled"] = enabled_ifaces

    if _CAN_WRITE_TOML:
        _write_toml_file(toml_path, toml)
        rprint(f"[green]✓ {persona_dir.name}/persona.toml updated.[/green]")
    else:
        rprint("[yellow]Install tomli-w to save: pip install tomli-w[/yellow]")
        rprint("Manual changes needed in persona.toml.")


# ── 5. Loop Settings ──────────────────────────────────────────

def edit_loop_settings():
    console.print()
    console.print(Panel("[bold]Loop Timing Settings[/bold]", border_style="blue"))

    cfg      = _load_config_toml()
    loop_cfg = cfg.get("loop", {})

    rprint(f"  sleep_min              = {loop_cfg.get('sleep_min', 300)} seconds")
    rprint(f"  sleep_max              = {loop_cfg.get('sleep_max', 3600)} seconds")
    rprint(f"  idle_action_threshold  = {loop_cfg.get('idle_action_threshold', 7200)} seconds")

    if not Confirm.ask("\nEdit?", default=False):
        return

    sleep_min  = int(Prompt.ask("  sleep_min (seconds)",  default=str(loop_cfg.get("sleep_min", 300))))
    sleep_max  = int(Prompt.ask("  sleep_max (seconds)",  default=str(loop_cfg.get("sleep_max", 3600))))
    idle_thresh = int(Prompt.ask("  idle_action_threshold (seconds)", default=str(loop_cfg.get("idle_action_threshold", 7200))))

    cfg.setdefault("loop", {})
    cfg["loop"]["sleep_min"]              = sleep_min
    cfg["loop"]["sleep_max"]              = sleep_max
    cfg["loop"]["idle_action_threshold"]  = idle_thresh

    if _CAN_WRITE_TOML:
        _write_toml_file(BASE_DIR / "config.toml", cfg)
        rprint("[green]✓ config.toml updated.[/green]")
    else:
        rprint("[yellow]Install tomli-w to save: pip install tomli-w[/yellow]")


# ── 6. Health Check ───────────────────────────────────────────

def run_health_check():
    console.print()
    console.print(Panel("[bold]Health Check[/bold]", border_style="blue"))

    env_file = BASE_DIR / ".env"
    env_vals = dotenv_values(env_file) if env_file.exists() else {}

    all_ok = True

    # Check LLM backend connectivity
    cfg     = _load_config_toml()
    llm_cfg = cfg.get("llm", {})
    backend = llm_cfg.get("backend", "ollama")
    host    = llm_cfg.get("host", "http://localhost:11434")
    embed_strategy = llm_cfg.get("embed_strategy", "api")

    rprint(f"\n[bold]LLM Backend:[/bold] {backend} @ {host}")
    rprint(f"[bold]Embeddings:[/bold]  {embed_strategy}")

    if _probe_backend(host):
        rprint(f"[green]✓[/green] LLM server reachable at {host}")
    else:
        rprint(f"[red]✗[/red] LLM server not reachable at {host}")
        all_ok = False

    # Check embedding strategy
    if embed_strategy == "local":
        try:
            from chromadb.utils.embedding_functions import (
                ONNXMiniLM_L6_V2,
            )
            rprint("[green]✓[/green] Local CPU embedder available (ONNX)")
        except ImportError:
            try:
                from chromadb.utils.embedding_functions import (
                    DefaultEmbeddingFunction,
                )
                rprint("[green]✓[/green] Local CPU embedder available (ChromaDB default)")
            except ImportError:
                rprint("[red]✗[/red] Local CPU embedder not available — install chromadb + onnxruntime")
                all_ok = False

    # Check LLM API key if using cloud backend
    if backend == "openai_compatible":
        if env_vals.get("LLM_API_KEY") or os.environ.get("LLM_API_KEY"):
            rprint("[green]✓[/green] LLM_API_KEY")
        else:
            rprint("[yellow]⚠[/yellow] LLM_API_KEY — not set (may be needed for cloud APIs)")

    # Check env vars for each enabled interface
    ifaces_dir = BASE_DIR / "interfaces"
    if ifaces_dir.exists():
        for iface_dir in sorted(ifaces_dir.iterdir()):
            if not iface_dir.is_dir():
                continue
            toml = _load_toml_file(iface_dir / "interface.toml")
            if not toml.get("interface", {}).get("enabled", True):
                continue
            requires = _get_manifest_requires(iface_dir / "interface.py")
            for var in requires:
                if env_vals.get(var) or os.environ.get(var):
                    rprint(f"[green]✓[/green] {var}")
                else:
                    rprint(f"[red]✗[/red] {var} — not set (needed by {iface_dir.name})")
                    all_ok = False

    # Check personas have required files
    personas_dir = BASE_DIR / "personas"
    if personas_dir.exists():
        for persona_dir in personas_dir.iterdir():
            if not persona_dir.is_dir():
                continue
            for fname in ["character.json", "style.md", "values.md", "lorebook.json"]:
                fpath = persona_dir / fname
                if fpath.exists():
                    rprint(f"[green]✓[/green] personas/{persona_dir.name}/{fname}")
                else:
                    rprint(f"[yellow]⚠[/yellow] personas/{persona_dir.name}/{fname} — missing")

    console.print()
    if all_ok:
        rprint("[bold green]All checks passed.[/bold green]")
    else:
        rprint("[bold yellow]Some checks failed — see above.[/bold yellow]")


# ── 7. Test Cycle ────────────────────────────────────────────

def run_test_cycle():
    console.print()
    console.print(Panel("[bold]Test Cycle[/bold]\nRuns a single autonomous action and exits.", border_style="blue"))

    personas_dir = BASE_DIR / "personas"
    personas     = [d.name for d in personas_dir.iterdir() if d.is_dir()] if personas_dir.exists() else []

    if not personas:
        rprint("[yellow]No personas found.[/yellow]")
        return

    persona = Prompt.ask("Persona to test", choices=personas)
    rprint(f"\n[dim]Running: python kid.py --persona {persona} --once --dry-run[/dim]\n")

    subprocess.run(
        [sys.executable, "kid.py", "--persona", persona, "--once", "--dry-run"],
        cwd=BASE_DIR,
    )


# ── 8. Import Persona ────────────────────────────────────────

def _parse_sillytavern_card(data_bytes: bytes) -> dict:
    # Try as JSON
    try:
        data = json.loads(data_bytes.decode('utf-8'))
        return data
    except Exception:
        pass

    # Try as PNG
    try:
        if not data_bytes.startswith(b'\x89PNG\r\n\x1a\n'):
            return {}
        
        idx = 8
        while idx < len(data_bytes):
            length = int.from_bytes(data_bytes[idx:idx+4], 'big')
            chunk_type = data_bytes[idx+4:idx+8].decode('ascii', errors='ignore')
            chunk_data = data_bytes[idx+8:idx+8+length]
            if chunk_type == 'tEXt':
                try:
                    keyword, text = chunk_data.split(b'\0', 1)
                    if keyword == b'chara':
                        return json.loads(base64.b64decode(text))
                except Exception:
                    pass
            idx += 12 + length
    except Exception:
        pass

    return {}

def import_persona():
    console.print()
    console.print(Panel("[bold]Import Persona (SillyTavern Card)[/bold]", border_style="blue"))
    
    path_or_url = Prompt.ask("Enter local file path or URL to .png/.json card")
    path_or_url = path_or_url.strip().strip('"').strip("'")
    
    if not path_or_url:
        return

    data_bytes = None
    if path_or_url.startswith("http://") or path_or_url.startswith("https://"):
        rprint("[dim]Downloading card...[/dim]")
        try:
            req = Request(path_or_url, headers={'User-Agent': 'Mozilla/5.0'})
            with urlopen(req, timeout=15) as resp:
                data_bytes = resp.read()
        except Exception as e:
            rprint(f"[red]✗ Failed to download URL: {e}[/red]")
            return
    else:
        p = Path(path_or_url)
        if not p.exists() or not p.is_file():
            rprint("[red]✗ File not found.[/red]")
            return
        try:
            with open(p, "rb") as f:
                data_bytes = f.read()
        except Exception as e:
            rprint(f"[red]✗ Could not read file: {e}[/red]")
            return

    card_json = _parse_sillytavern_card(data_bytes)
    if not card_json:
        rprint("[red]✗ Could not parse SillyTavern character data from file.[/red]")
        return

    # Extract character dictionary (V1 vs V2)
    char_data = card_json.get("data", card_json)
    
    name = char_data.get("name", "UnknownCharacter")
    safe_name = re.sub(r'[^a-zA-Z0-9_-]', '', name.lower().replace(' ', '_'))
    if not safe_name:
        safe_name = "imported_persona"
        
    persona_dir = BASE_DIR / "personas" / safe_name
    if persona_dir.exists():
        if not Confirm.ask(f"\nPersona directory [cyan]personas/{safe_name}[/cyan] already exists. Overwrite?", default=False):
            return

    persona_dir.mkdir(parents=True, exist_ok=True)
    
    rprint(f"\n[green]✓ Read character:[/green] {name}")
    
    # character.json
    char_file = persona_dir / "character.json"
    with open(char_file, "w", encoding="utf-8") as f:
        json.dump(card_json, f, indent=2)
        
    # lorebook.json
    lorebook = char_data.get("character_book", {})
    lore_file = persona_dir / "lorebook.json"
    with open(lore_file, "w", encoding="utf-8") as f:
        json.dump(lorebook, f, indent=2)
        
    # Build string of text details
    text_details = f"Name: {char_data.get('name', '')}\n"
    text_details += f"Description: {char_data.get('description', '')}\n"
    text_details += f"Personality: {char_data.get('personality', '')}\n"
    text_details += f"System Prompt: {char_data.get('system_prompt', '')}\n"
    text_details += f"Creator Notes: {char_data.get('creator_notes', '')}\n"

    rprint("\n[dim]Initializing LLM Bridge to generate style.md and values.md...[/dim]")
    cfg = _load_config_toml()
    llm_cfg = cfg.get("llm", {})
    env_file = BASE_DIR / ".env"
    env_vals = dotenv_values(env_file) if env_file.exists() else {}
    api_key = env_vals.get("LLM_API_KEY", os.environ.get("LLM_API_KEY", ""))

    try:
        from llm_bridge import LLMBridge
        llm = LLMBridge(
            host=llm_cfg.get("host", "http://localhost:11434"),
            neocortex_model=llm_cfg.get("neocortex_model", "gemma2:27b"),
            embed_model=llm_cfg.get("embed_model", "nomic-embed-text"),
            default_params=llm_cfg.get("defaults", {}),
            backend=llm_cfg.get("backend", "ollama"),
            api_key=api_key,
            embed_strategy="local", # Prevent unnecessary remote embedding calls for this
        )
        
        # generate style.md
        rprint(f"[dim]Prompting {llm.neocortex_model} for style.md...[/dim]")
        style_prompt = f"You are a technical writer. Create a style.md file for an AI persona. Do NOT think out loud. Do NOT include any reasoning or planning steps. Output ONLY the final markdown text.\n\nWrite out a descriptive style.md for ingestion by an AI assistant based on these character traits.\n\n[text details from character card]:\n{text_details}"
        style_md = llm.generate(prompt=style_prompt, num_predict=1024, timeout=600)
        
        # generate values.md
        rprint(f"[dim]Prompting {llm.neocortex_model} for values.md...[/dim]")
        values_prompt = f"You are a technical writer. Create a values.md file for an AI persona. Do NOT think out loud. Do NOT include any reasoning or planning steps. Output ONLY the final markdown text.\n\nWrite out a descriptive values.md for ingestion by an AI assistant based on these character traits. The AI should also have compassion (attempt to empathize with diverse people of the world), integrity (upholds the highest scientific, historical, and personal truth), and adaptability (looks for innovative ways to solve problems if it gets stuck).\n\n[text details from character card]:\n{text_details}"
        values_md = llm.generate(prompt=values_prompt, num_predict=1024, timeout=600)
        
    except Exception as e:
        rprint(f"[yellow]⚠ Failed to use LLM to generate files ({e}). Using raw fallbacks.[/yellow]")
        style_md = char_data.get('system_prompt', char_data.get('description', ''))
        values_md = char_data.get('creator_notes', 'Be compassionate, have integrity, and be adaptable.')

    # Clean up markdown output
    style_md = style_md.strip()
    if style_md.startswith('```') and style_md.endswith('```'):
        style_md = '\n'.join(style_md.split('\n')[1:-1]).strip()
        
    values_md = values_md.strip()
    if values_md.startswith('```') and values_md.endswith('```'):
        values_md = '\n'.join(values_md.split('\n')[1:-1]).strip()

    with open(persona_dir / "style.md", "w", encoding="utf-8") as f:
        f.write(style_md)
        
    with open(persona_dir / "values.md", "w", encoding="utf-8") as f:
        f.write(values_md)

    # persona.toml
    all_actions = _list_plugins(BASE_DIR / "actions")
    all_ifaces = _list_plugins(BASE_DIR / "interfaces")
    
    toml_data = {
        "actions": {"enabled": all_actions},
        "interfaces": {"enabled": all_ifaces}
    }
    _write_toml_file(persona_dir / "persona.toml", toml_data)

    rprint(f"\n[bold green]Successfully imported persona {name} into personas/{safe_name}![/bold green]")


# ── TOML Helpers ─────────────────────────────────────────────

def _load_config_toml() -> dict:
    p = BASE_DIR / "config.toml"
    return _load_toml_file(p)

def _load_toml_file(path: Path) -> dict:
    if not path or not path.exists():
        return {}
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except Exception:
        return {}

def _write_toml_file(path: Path, data: dict) -> None:
    if not _CAN_WRITE_TOML:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        tomli_w.dump(data, f)

def _list_plugins(directory: Path) -> list[str]:
    if not directory.exists():
        return []
    return sorted(d.name for d in directory.iterdir() if d.is_dir())

def _get_manifest_requires(py_path: Path) -> list[str]:
    """Quick parse of MANIFEST['requires'] without fully importing the module."""
    if not py_path.exists():
        return []
    try:
        import importlib.util
        spec   = importlib.util.spec_from_file_location("_tmp", str(py_path))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        manifest = getattr(module, "MANIFEST", {})
        return manifest.get("requires", [])
    except Exception:
        return []


if __name__ == "__main__":
    main()

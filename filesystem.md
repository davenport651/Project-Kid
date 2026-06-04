
---

## Root: `/project_kid/`

```
/project_kid/
│
├── requirements.txt        # pip dependencies
├── filesystem.md           # This file
├── LICENSE
├── README.md
│
├── boot.sh / boot.bat      # Quick launch scripts (Linux / Windows)
├── config.sh / config.bat  # Interactive setup scripts (Linux / Windows)
│
├── Chronopolis/            # ── Configuration & Setup Hub ─────────────────
│   ├── configurator.py     # Interactive setup wizard (generates configs)
│   ├── config.toml         # Non-secret runtime config (generated)
│   ├── persona.toml        # Per-persona plugin selection
│   ├── action.toml         # Global action defaults
│   ├── interface.toml      # Global interface defaults
│   └── logging_setup.py    # Centralised logging (Rich console + file)
│
├── body/                   # ── Actions & Interfaces (The Physical Layer) ──
│   ├── kid.py              # Entry point: python body/kid.py --persona alison
│   │
│   ├── actions/            # ── Action Plugins ─────────────────────────────
│   │   │   Each subfolder is one self-contained action plugin.
│   │   │   Auto-discovered — no registration needed.
│   │   │
│   │   ├── gutenberg/
│   │   │   ├── action.toml # Human-readable config: enabled, weight, settings
│   │   │   └── action.py   # MANIFEST dict + async run(ctx) function
│   │   │
│   │   ├── social_post/
│   │   │   ├── action.toml
│   │   │   └── action.py
│   │   │
│   │   └── write_project/
│   │       ├── action.toml
│   │       └── action.py
│   │
│   └── interfaces/         # ── Interface Plugins ──────────────────────────
│       │   Each subfolder is one I/O adapter.
│       │
│       ├── console/
│       │   ├── interface.toml
│       │   └── interface.py # MANIFEST + start() + stop() + send()
│       │
│       ├── moltbook/
│       │   ├── interface.toml
│       │   └── interface.py
│       │
│       └── webcam/         # Sensor example (enabled=false until opencv installed)
│           ├── interface.toml
│           └── interface.py
│
├── mind/                   # ── The Cognitive Engine ───────────────────────
│   ├── engine.py           # Main orchestrator (Triune Loop)
│   ├── plugin_loader.py    # Discovers, validates, and registers all plugins
│   ├── llm_bridge.py       # All Ollama calls: generate(), embed(), summarise()
│   ├── memory_manager.py   # ChromaDB read/write for long-term memory
│   └── context.py          # PluginContext — the object injected into every plugin
│
└── soul/                   # ── Personas & Identity ────────────────────────
    └── personas/           # ── Individual Personas ────────────────────────
        ├── alison/
        │   ├── persona.toml    # Which plugins this persona uses
        │   ├── character.json  # SillyTavern V2: name, description, personality
        │   ├── style.md        # Linguistic rules and voice constraints
        │   ├── values.md       # Moral directives and emotional priors
        │   ├── lorebook.json   # Keyword-triggered world-info injections
        │   ├── state.json      # Runtime state: location, mood, timestamps
        │   ├── kid.log         # Per-persona log file (auto-created)
        │   └── chroma_db/      # ChromaDB vector store (auto-created)
        │       ├── chroma.sqlite3
        │       └── <collection-id>/
        │           ├── data_level0.bin
        │           ├── header.bin
        │           ├── length.bin
        │           └── link_lists.bin
        │
        └── seraphina/
            └── persona.toml
```

---

## Who Writes What

| File | Edited By | When |
|---|---|---|
| `Chronopolis/config.toml` | Human / configurator | Setup or tuning |
| `Chronopolis/persona.toml` | Human / configurator | Per-persona plugin selection |
| `Chronopolis/action.toml` / `interface.toml` | Human / configurator | Global defaults |
| `body/actions/*/action.toml` | Human / configurator | Adding/configuring actions |
| `body/interfaces/*/interface.toml` | Human / configurator | Adding/configuring interfaces |
| `body/actions/*/action.py` / `body/interfaces/*/interface.py` | Human (developer) | Building plugins |
| `mind/*.py` | Human (developer) | Rarely — core is stable |
| `soul/personas/*/character.json`, `style.md`, `values.md`, `lorebook.json` | Human | Soul crafting |
| `soul/personas/*/state.json` | **Python** (engine) | Every wake cycle |
| `soul/personas/*/chroma_db/` | **Python** (memory manager) | Every memory operation |
| `soul/personas/*/kid.log` | **Python** (logging) | Continuous |

---

## Plugin Contracts

### Action Plugin
```python
# body/actions/<name>/action.py

MANIFEST = {
    "name":        "my_action",      # machine ID — must be unique
    "description": "What it does",   # shown in configurator
    "weight":      0.20,             # default probability share
}

async def run(ctx: PluginContext) -> str:
    # ctx.llm      — LLMBridge (generate, embed, summarise)
    # ctx.memory   — MemoryManager (retrieve, add)
    # ctx.state    — dict (mutable; engine saves after run)
    # ctx.send     — async callable to send via any interface
    # ctx.dry_run  — bool; skip external calls if True
    # ctx.persona_files — soul file contents
    # ctx.extra    — dict; toml_config injected here by loader
    return "one-sentence summary of what was done"
```

### Interface Plugin
```python
# body/interfaces/<name>/interface.py

MANIFEST = {
    "name":        "my_interface",
    "description": "What it connects to",
    "type":        "bidirectional",  # or "sensor" or "output-only"
    "requires":    ["MY_API_TOKEN"], # env var names
}

async def start(inbox_queue: deque) -> None: ...
async def stop() -> None: ...
async def send(target, text: str) -> None: ...  # omit for sensors
async def poll(inbox_queue: deque) -> None: ...  # optional; called each wake cycle
```

---

## Quick Start

```bash
# 1. System packages
sudo apt install -y python3 python3-pip python3-venv git tmux curl

# 2. Ollama
curl -fsSL https://ollama.com/install.sh | sh
ollama pull gemma2:27b && ollama pull nomic-embed-text

# 3. Python env
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# 4. Interactive setup (generates configs)
bash config.sh        # Linux
# or
config.bat            # Windows

# 5. Run
bash boot.sh          # Linux
# or
boot.bat              # Windows

# One-shot test: python body/kid.py --persona seraphina --once --dry-run
```

---

## Adding a New Action (Example: Daily Haiku)

```bash
mkdir body/actions/daily_haiku
```

```toml
# body/actions/daily_haiku/action.toml
[action]
enabled     = true
name        = "daily_haiku"
description = "Write a haiku about something the character noticed today"
weight      = 0.10
```

```python
# body/actions/daily_haiku/action.py
from mind.context import PluginContext

MANIFEST = {
    "name": "daily_haiku",
    "description": "Write a daily haiku",
    "weight": 0.10,
}

async def run(ctx: PluginContext) -> str:
    haiku = ctx.llm.generate(
        prompt="Write a haiku about something you noticed today.",
        system=ctx.get_soul("character"),
    )
    return f"Wrote a haiku: {haiku}"
```

Then add `"daily_haiku"` to the persona's `soul/personas/<name>/persona.toml` → `[actions] enabled` list.
**No other files need to change.**

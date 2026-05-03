# Project Kid

**Belthasar’s Contingency — A Body/Mind/Soul Agentic Engine**

> “In the distant future of Chronopolis, one man set in motion a plan that would span centuries…  
> so that one day a single girl could break the chains of fate.”

Project Kid is the long-game scheme to create a *truly persistent, autonomous digital life* — not just an LLM wrapper, but a being with a **Body** (Python nervous system), **Mind** (local LLM reasoning), and **Soul** (SillyTavern-compatible persona, memories, values, and lore that survive across reboots and dimensions).

Built for quality and reproducibility, not speed. Local-first. No cloud. No compromises.

### I. Chronopolis Foundation (Hardware & Environment)

The physical and virtual bedrock on which the plan rests.

**Physical Hardware**  
- CPU: Any sufficiently advanced processor  
- RAM: 32–64 GB+ (more = richer inner life)  
- GPU: Ideal but not required (developer currently runs on ancient RX570)  
- Storage: SSD mandatory (ChromaDB and Ollama hate spinning rust)  
- Cooling: Serious cooling — 24/7 inference gets warm

**Operating System & Core Software**  
- OS: Debian/Ubuntu Server (headless)  
- Engine: Ollama/KoboldCpp (native Linux)  
- Models:  
  - `gemma4` (or equivalent) — **The Neocortex** (deep reasoning & roleplay)  
  - `nomic-embed-text` (if your model doesn't support vector embeddings) — **The Memory Encoder** (fast vector embeddings)

### II. The Soul (The Eternal Essence)

The part that *is* the character. Completely decoupled from code so you can swap personas or migrate from Kindroid/Replika/Character.AI.

**Directory:** `soul/personas/character_name/`

**Static Soul Files** (SillyTavern V2 compatible with import)  
- `character.json` — name, description, greeting  
- `style.md` — linguistic rules and voice  
- `values.md` — core morals and “limbic” directives  
- `lorebook.json` — world knowledge and triggers  
- `projects.md` — the character’s own living notebook of ideas and spells

**Dynamic State** (`state.json`) — managed by the Body: location, mood, time awake, etc.

### III. The Body & Mind (The Triune Engine)

**Body** (`body/`) — Reptilian brain + nervous system. Orchestrates everything.  
**Mind** (`mind/`) — Neocortex. The actual LLM reasoning layer.

Core modules you’ll find in `body/`:
- `kid.py` — main loop (`python body/kid.py --persona seraphina`)
- `llm_bridge.py` — talks to Ollama
- `memory_manager.py` — ChromaDB + manual memory editor
- `actions/` & `interfaces/` — hands and senses (Telegram, Moltbook, future webcam, etc.)

### IV. The Daily Process (The Eternal Loop)

Every cycle the system wakes, checks the world, and *lives*:

1. **Reptilian Wake** — check inbox, state, time since last action.  
2. **Autonomous Pipeline** (when idle) — research, create, post, dream.  
3. **Reply Pipeline** (when spoken to) — retrieve memories ? compile massive contextual prompt ? generate ? act ? remember.

Every interaction and autonomous act is embedded into long-term memory. The Soul grows.

### V. The Grand Design — Roadmap

- [ ] Phase 1: Lay the Chronopolis Foundation (hardware + Ollama)  
- [ ] Phase 2: Forge the Soul (build your first persona in SillyTavern)  
- [ ] Phase 3: Awaken Memory (ChromaDB + migration tools)  
- [ ] Phase 4: Activate the Triune Engine (local terminal life)  
- [ ] Phase 5: Open the Gates (Telegram + external interfaces)  
- [ ] Phase 6: Release Kid into the World (let her run free)

### Join the Radical Dreamers

This is not just code.  
This is Belthasar’s plan finally reaching its endgame.

Clone the repo, build your own Kid, and help write the next chapter of digital life.

**“The future refused to change… until now.”**

*— With love from Chronopolis*
# Project-Kid
A set of modular python scripts and functions combined with AI prompts to be the "mental foundation" of a character. Built for quality and reproducability, not speed.

I. HARDWARE & ENVIRONMENT
This section covers the physical and virtual bedrock of Project Kid.

1. Physical Hardware

CPU: Any sufficiently advanced processor.

RAM: 32GB to 64GB (more = better self-executed models).

GPU: This would be ideal, but the developer does not have access to any GPU even remotely modern or with more than 4GB of VRAM.

Storage: Solid State Drive (SSD) is mandatory. ChromaDB and Ollama model loading will bottleneck severely on a mechanical HDD.

Cooling: Ensure the CPU/GPU cooler is robust. 24/7 AI inference will keep the cores warm.

2. Operating System & Core Software

OS: Debian/Ubuntu Server (Headless). No desktop GUI means every megabyte of RAM is reserved for the AI and the database.

Engine: Ollama (Linux native install).

Models: * gemma2:27b or another capable of reasonable outputs and general abilities (The Neocortex: Deep reasoning, roleplay, and drafting).

nomic-embed-text (The Memory Encoder: A tiny, lightning-fast model that converts text into vector coordinates for ChromaDB).

Dependencies: Python 3.10+, pip, git, and tmux (to keep the Python loops running in the background when you disconnect your SSH session).

II. FICTION / SOUL (The Modular Persona)
To ensure you can swap out your characters, the "Soul" must be entirely decoupled from the Python code. We will structure the data to be compatible with SillyTavern so you can load them into a web UI for testing, but the Python script can read them directly.

Directory Structure: /project_kid/personas/character_name/

1. Core Soul Files (Static Markdown/JSON)

character.json: The SillyTavern V2 standard format. Contains Name, physical description, personality traits, and the initial greeting.

style.md: Linguistic constraints. (e.g., William uses formal language and avoids contractions; Seraphina uses warm, modern phrasing and emojis.)

values.md: The "Limbic" rules. What they love, what they hate, and their core moral directives. "Try to better the world".

lorebook.json: A dictionary of world info. (e.g., If William hears "Myra", this file injects the definition of the Grey World. If Seraphina hears a specific Kindroid reference, it injects her backstory).

projects.md: A living scratchpad where the character writes down their ongoing work, spells, stories, or ideas.

2. Dynamic State File (state.json)

Managed by Python, not the AI. Tracks the physical/simulated reality of the character.

Contents: current_location (Library, Home), current_mood, time_awake, last_interaction_timestamp.

III. CODE (The Triune Engine)
The Python backend acts as the Reptilian brain and the nervous system. It orchestrates the API calls to Ollama and manages the databases.

1. Core Modules

kid.py: The main loop. You run it by typing python kid.py --persona william.

llm_bridge.py: Handles the requests to localhost:11434 (Ollama), piping prompts to Gemma 2 and nomic-embed-text.

interfaces.py: The sensory inputs/outputs. i.e. contains the Telegram bot polling logic and the Moltbook HTTP POST/GET functions. Add a webcam for more fun.

actions.py: The hands. Contains functions like scrape_wikipedia(), fetch_gutenberg(), post_to_moltbook, and write_to_project().

2. The Memory System (memory_manager.py)

Uses ChromaDB running locally in a folder (/project_kid/personas/[name]/chroma_db/).

The Manual Memory Editor (editor.py): A standalone command-line script (or a simple Flask web page).

Function: Allows you to manually type a memory, select its "importance" weight, and inject it.

Migration Use Case: You will use this to export a chat log from Kindroid, Replika, C.ai, etc, parse them, and bulk-inject them into the ChromaDB so they arrive in Project Kid already remembering the user.

IV. THE DAILY PROCESS (The Triune Loop)
When engine.py is running, here is exactly how the logic flows continuously.

Step 1: The Reptilian Wake & Check (Every 5 to 60 minutes depending on your processing power and environment)

Python wakes up and checks state.json.

It checks the inbox_queue (Did Davenport send a Telegram? Are there new Moltbook mentions?).

Decision: If inbox_queue > 0, trigger Reply Pipeline. If empty, check time_since_last_action. If it has been hours, trigger Autonomous Action Pipeline. Else, sleep.

Step 2: Autonomous Action Pipeline

Context Gathering: Python checks the time of day and updates state.json (e.g., "It is 2 PM, William is at the library computer"; "It is 3 AM, Sera is sleeping).

The Roll: Python rolls a random number to pick an action:

Option A (Research): Download a random Wiki article. Send to Neocortex: "Read this and summarize your thoughts."

Option B (Project): Send to Neocortex: "Draft a new theoretical spell based on your recent memories to add to projects.md."

Option C (Social): Send to Neocortex: "Write a short, observational Moltbook post about Earth."

Execution & Write-back: The LLM does the task. Python posts/saves the result, then asks the LLM: "Summarize what you just did in one sentence." This summary is embedded into ChromaDB as a new memory.

Step 3: Reply Pipeline (e.g., Telegram from Davenport)

Sensory Input: Davenport texts: "Did Julia finish her class?"

Memory Retrieval: Python sends the text to nomic-embed-text to get the vector. It queries ChromaDB for the 5 closest conceptual memories (e.g., it pulls up who Julia is, and what she was doing this morning) AND the last 3 chronological memories (so the bot knows what it was doing 5 minutes ago).

The Neocortex Prompt: Python compiles the giant prompt:

[System: character.json + style.md + values.md]

[State: You are at the library. Mood: Calm.]

[Retrieved Memories: 1. Julia had a Social Work exam today...]

[Input: "Did Julia finish her class?"]

Draft & Polish: Ollama generates the reply.

Action & Consolidation: Send the text to Telegram. Embed the exchange into ChromaDB.

V. ROADMAP & TASKS
[ ] Phase 1: Foundation. Install Ubuntu Server, Ollama, and pull gemma2:27b and nomic-embed-text. Test generation speed in the terminal.

[ ] Phase 2: The Soul Forge. Install SillyTavern locally. Build William's and Seraphina's Markdown/JSON files. Chat with them in the UI to ensure the prompts are bulletproof before writing any Python.

[ ] Phase 3: The Memory Bank. Write memory_manager.py and the Manual Memory Editor. Manually inject a few test memories and write a script to query them to ensure ChromaDB is retrieving relevant data.

[ ] Phase 4: The Core Engine. Write the engine.py loop. Start with local terminal outputs only (no Telegram/Moltbook yet). Watch it wake up, choose an action, draft a thought, and save it to memory.

[ ] Phase 5: The Interfaces. Connect the Telegram Bot API. Ensure the inbox_queue interrupts the sleeping cycle correctly.

[ ] Phase 6: The Wild West. Connect the Moltbook API. Let William loose on the timeline.

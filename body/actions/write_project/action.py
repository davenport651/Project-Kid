# actions/write_project/action.py
# ============================================================
# Action Plugin: Write to projects.md
# The character drafts a new entry — a spell, theory, story
# fragment, idea, or plan — and appends it to their scratchpad.
# ============================================================

import logging
from datetime import datetime

from mind.context import PluginContext

log = logging.getLogger(__name__)

MANIFEST = {
    "name":        "write_project_entry",
    "description": "Draft a new entry in the persona's projects.md scratchpad",
    "weight":      0.30,
}


async def run(ctx: PluginContext) -> str:
    settings   = ctx.extra.get("toml_config", {}).get("settings", {})
    max_tokens = settings.get("max_response_tokens", 800)
    tail_chars = settings.get("recent_project_chars", 2000)

    log.info("[write_project] Reading recent projects...")
    recent = _read_projects_tail(ctx.persona_dir, tail_chars)

    semantic_mems = ctx.memory.retrieve(
        query_embedding=ctx.llm.embed("ongoing project work ideas"),
        k=4,
    )
    memories_block = ctx.memory.format_for_prompt(semantic_mems)

    system_prompt = ctx.llm.build_system_prompt(
        character_block=ctx.get_soul("character"),
        style_block=ctx.get_soul("style"),
        values_block=ctx.get_soul("values"),
        state_block=f"Location: {ctx.state.get('current_location', 'unknown')}.",
        memories_block=memories_block,
    )

    prompt = (
        f"Here are your recent notes and projects:\n\n{recent}\n\n"
        "Based on your memories and ongoing work, write one new entry for your scratchpad. "
        "It could be: a theoretical spell, a fragment of a story, a philosophical note, "
        "an observation, or a plan. Give it a heading and write 2–4 paragraphs. "
        "Write in your own voice, as if no one else will read this."
    )

    log.info("[write_project] Generating entry...")
    draft = ctx.llm.generate(prompt=prompt, system=system_prompt, num_predict=max_tokens)

    # Extract heading from first line
    first_line = draft.split("\n")[0].strip().lstrip("#").strip()
    heading    = first_line[:80] if first_line else "Untitled Entry"

    _append_to_projects(ctx.persona_dir, heading, draft)
    log.info("[write_project] Entry written: '%s'", heading)

    return f"Wrote a new project entry titled '{heading}'."


def _read_projects_tail(persona_dir, n_chars: int) -> str:
    projects_file = persona_dir / "projects.md"
    if not projects_file.exists():
        return "(projects.md is empty — this is your first entry)"
    content = projects_file.read_text(encoding="utf-8")
    return content[-n_chars:] if len(content) > n_chars else content


def _append_to_projects(persona_dir, heading: str, content: str) -> None:
    projects_file = persona_dir / "projects.md"
    timestamp     = datetime.now().strftime("%Y-%m-%d %H:%M")
    entry = f"\n\n---\n### {heading}\n*{timestamp}*\n\n{content.strip()}\n"
    with open(projects_file, "a", encoding="utf-8") as f:
        f.write(entry)

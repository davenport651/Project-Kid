# actions/gutenberg/action.py
# ============================================================
# Action Plugin: Project Gutenberg Reading
# ============================================================

import logging
import random
import re

import requests

from mind.context import PluginContext

log = logging.getLogger(__name__)

MANIFEST = {
    "name":        "read_gutenberg",
    "description": "Read a Gutenberg classic excerpt and reflect on it",
    "weight":      0.15,
}


async def run(ctx: PluginContext) -> str:
    settings    = ctx.extra.get("toml_config", {}).get("settings", {})
    book_ids    = settings.get("book_ids", [1342, 11, 1661, 84])
    excerpt_len = settings.get("excerpt_length", 1000)
    max_tokens  = settings.get("max_response_tokens", 350)

    book_id = random.choice(book_ids)
    log.info("[gutenberg] Fetching book id=%d...", book_id)

    excerpt, title = _fetch_excerpt(book_id, excerpt_len)
    log.info("[gutenberg] Got excerpt from '%s'", title)

    system_prompt = ctx.llm.build_system_prompt(
        character_block=ctx.get_soul("character"),
        style_block=ctx.get_soul("style"),
        values_block=ctx.get_soul("values"),
        state_block=f"Location: {ctx.state.get('current_location', 'unknown')}.",
        memories_block=ctx.memory.format_for_prompt(ctx.memory.retrieve_recent(k=2)),
    )

    prompt = (
        f"You just read a passage from '{title}' (Project Gutenberg, book #{book_id}):\n\n"
        f"---\n{excerpt}\n---\n\n"
        "What does this passage make you think about? Respond in your own voice, "
        "2–4 sentences. You don't need to summarise it — just react."
    )

    reaction = ctx.llm.generate(prompt=prompt, system=system_prompt, num_predict=max_tokens)
    log.info("[gutenberg] Reaction: %s...", reaction[:80])

    return f"Read a passage from '{title}'. Thoughts: {reaction}"


def _fetch_excerpt(book_id: int, length: int) -> tuple[str, str]:
    url = f"https://www.gutenberg.org/cache/epub/{book_id}/pg{book_id}.txt"
    try:
        resp = requests.get(url, timeout=20, headers={"User-Agent": "ProjectKid/1.0"})
        resp.raise_for_status()
    except requests.RequestException as e:
        log.error("[gutenberg] Fetch failed: %s", e)
        raise

    raw = resp.text

    # Strip header/footer
    for marker in ["*** START OF", "***START OF"]:
        idx = raw.find(marker)
        if idx != -1:
            raw = raw[idx:]
            raw = raw[raw.find("\n"):].strip()
            break
    for marker in ["*** END OF", "***END OF"]:
        idx = raw.find(marker)
        if idx != -1:
            raw = raw[:idx].strip()
            break

    # Extract title
    title_m = re.search(r"Title:\s*(.+)", raw[:400])
    title   = title_m.group(1).strip() if title_m else f"Gutenberg #{book_id}"

    # Random window
    if len(raw) > length * 2:
        start   = random.randint(len(raw) // 4, len(raw) - length - 100)
        excerpt = raw[start:start + length].strip()
    else:
        excerpt = raw[:length].strip()

    return excerpt, title

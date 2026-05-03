# actions/wikipedia/action.py
# ============================================================
# Action Plugin: Wikipedia Research
#
# CONTRACT:
#   MANIFEST  — dict with required keys (validated by plugin_loader)
#   run(ctx)  — async function, receives PluginContext, returns str
#
# This plugin fetches a Wikipedia article and asks the
# character to react to it in their own voice. The resulting
# thoughts are summarised by the engine and stored as memory.
#
# ADDING TOPICS: Edit action.toml — no Python changes needed.
# DISABLING:     Set enabled = false in action.toml.
# ============================================================

import logging
import random

import requests
from bs4 import BeautifulSoup

from mind.context import PluginContext

log = logging.getLogger(__name__)

# ── Plugin Contract ──────────────────────────────────────────
MANIFEST = {
    "name":        "research_wikipedia",
    "description": "Fetch and react to a random Wikipedia article",
    "weight":      0.40,  # Default; overridden by action.toml
}


# ── Main Entry Point ─────────────────────────────────────────

async def run(ctx: PluginContext) -> str:
    """
    Fetch a Wikipedia article, then ask the LLM to react to it.

    Args:
        ctx: Standard PluginContext from the engine.

    Returns:
        A string summarising what was read and thought, suitable
        for the engine to store as a memory.
    """
    toml_cfg  = ctx.extra.get("toml_config", {})  # Injected by loader if needed
    settings  = toml_cfg.get("settings", {})

    # ── Step 1: Fetch article ────────────────────────────────
    log.info("[wikipedia] Fetching article...")
    article = _fetch_article(settings)
    log.info("[wikipedia] Got article: '%s' (%d paragraphs)", article["title"], article["para_count"])

    # ── Step 2: Build prompt ─────────────────────────────────
    system_prompt = _build_system_prompt(ctx)
    max_tokens    = settings.get("max_response_tokens", 400)

    prompt = (
        f"You just read the following Wikipedia article:\n\n"
        f"Title: {article['title']}\n"
        f"URL:   {article['url']}\n\n"
        f"{article['summary']}\n\n"
        "React to this in your own voice. What do you find interesting, "
        "surprising, or worth thinking about further? 2–4 sentences."
    )

    # ── Step 3: Generate reaction ────────────────────────────
    log.info("[wikipedia] Generating reaction...")
    reaction = ctx.llm.generate(prompt=prompt, system=system_prompt, num_predict=max_tokens)
    log.info("[wikipedia] Reaction: %s...", reaction[:80])

    return f"Read about '{article['title']}'. Thoughts: {reaction}"


# ── Helpers ──────────────────────────────────────────────────

def _fetch_article(settings: dict) -> dict:
    """
    Fetch and parse a Wikipedia article.
    Returns dict: title, url, summary, para_count.
    """
    lang        = settings.get("language", "en")
    use_random  = settings.get("use_random_article", True)
    topic_list  = settings.get("topic_list", [])
    n_paras     = settings.get("summary_paragraphs", 3)

    if use_random or not topic_list:
        url = f"https://{lang}.wikipedia.org/wiki/Special:Random"
    else:
        topic = random.choice(topic_list)
        url   = f"https://{lang}.wikipedia.org/wiki/{topic.replace(' ', '_')}"

    try:
        resp = requests.get(url, timeout=15, allow_redirects=True,
                            headers={"User-Agent": "ProjectKid/1.0"})
        resp.raise_for_status()
    except requests.RequestException as e:
        log.error("[wikipedia] HTTP error: %s", e)
        raise

    soup  = BeautifulSoup(resp.text, "lxml")
    title = (soup.find("h1", {"id": "firstHeading"}) or soup.find("h1"))
    title = title.get_text(strip=True) if title else "Unknown"

    content = soup.find("div", {"id": "mw-content-text"})
    paras   = []
    if content:
        for p in content.find_all("p", recursive=True):
            text = p.get_text(strip=True)
            if len(text) > 80:
                paras.append(text)

    summary = "\n\n".join(paras[:n_paras])
    return {"title": title, "url": resp.url, "summary": summary, "para_count": len(paras)}


def _build_system_prompt(ctx: PluginContext) -> str:
    """Build a minimal system prompt for the reaction generation."""
    return ctx.llm.build_system_prompt(
        character_block=ctx.get_soul("character"),
        style_block=ctx.get_soul("style"),
        values_block=ctx.get_soul("values"),
        state_block=(
            f"Location: {ctx.state.get('current_location', 'unknown')}. "
            f"Mood: {ctx.state.get('current_mood', 'neutral')}."
        ),
        memories_block=ctx.memory.format_for_prompt(
            ctx.memory.retrieve_recent(k=2)
        ),
    )

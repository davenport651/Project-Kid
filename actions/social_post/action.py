# actions/social_post/action.py
# ============================================================
# Action Plugin: Social Post
# Composes a short post and sends it via ctx.send() to
# whichever interface is configured in action.toml.
# ============================================================

import logging

from context import PluginContext

log = logging.getLogger(__name__)

MANIFEST = {
    "name":        "social_post",
    "description": "Compose and publish a short social media post",
    "weight":      0.15,
}


async def run(ctx: PluginContext) -> str:
    settings   = ctx.extra.get("toml_config", {}).get("settings", {})
    max_len    = settings.get("max_post_length", 500)
    max_tokens = settings.get("max_response_tokens", 200)
    target_iface = settings.get("target_interface", "moltbook")

    recent_mems   = ctx.memory.retrieve_recent(k=3)
    memories_block = ctx.memory.format_for_prompt(recent_mems)

    system_prompt = ctx.llm.build_system_prompt(
        character_block=ctx.get_soul("character"),
        style_block=ctx.get_soul("style"),
        values_block=ctx.get_soul("values"),
        state_block=(
            f"Location: {ctx.state.get('current_location', 'unknown')}. "
            f"Mood: {ctx.state.get('current_mood', 'neutral')}."
        ),
        memories_block=memories_block,
    )

    prompt = (
        "Write a short post (1–3 sentences) for your social feed. "
        "It should be something you've been thinking about, observing, or feeling. "
        "Specific and personal. Do not use hashtags. Write as yourself."
    )

    log.info("[social_post] Generating post...")
    raw_post = ctx.llm.generate(prompt=prompt, system=system_prompt, num_predict=max_tokens)
    post     = raw_post.strip()[:max_len]

    log.info("[social_post] Post: '%s...'", post[:60])

    # Send via ctx.send() — the engine routes this to the correct interface
    if ctx.send:
        await ctx.send(target_iface, None, post)
    else:
        log.warning("[social_post] No send() in context — post not delivered.")

    return f"Posted to {target_iface}: '{post[:80]}'"

# core/llm_bridge.py
# ============================================================
# Project Kid — LLM Bridge
# All LLM calls live here. Plugins import this via ctx.llm.
#
# Supports any OpenAI-compatible API:
#   - Ollama     (http://localhost:11434)
#   - KoboldCpp  (http://localhost:5001)
#   - Cloud APIs (OpenAI, Together, etc.)
#
# Embeddings use the server's /v1/embeddings when available,
# falling back to a local CPU-based ONNX model otherwise.
# ============================================================

import logging
import os
from typing import Optional

import requests

log = logging.getLogger(__name__)

# ── Helpers ──────────────────────────────────────────────────

def _strip_thinking(text: str) -> str:
    """Remove thinking/reasoning blocks from model output.

    Thinking models (Gemma 3/4, DeepSeek, etc.) emit reasoning wrapped in
    tags like <think>...</think> or <think>...</think>.
    This strips those blocks so only the final answer remains.
    """
    import re

    # <think>...</think>
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    # <think>...</think>
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    # <reasoning>...</reasoning>
    text = re.sub(r"<reasoning>.*?</reasoning>", "", text, flags=re.DOTALL).strip()
    # Common Gemma-style: "Here's a thinking process..." up to first ## or ---
    text = re.sub(
        r"(?i)^here's a thinking process.*?(?=\n##|\n---|\n\n##|\Z)",
        "", text, flags=re.DOTALL
    ).strip()

    return text


# ── Local CPU Embedder (lazy-loaded) ─────────────────────────
_local_embedder = None


def _get_local_embedder():
    """
    Return ChromaDB's built-in DefaultEmbeddingFunction.
    Uses a small ONNX model that runs on CPU — no GPU or
    external server required. Lazy-loaded on first call.
    """
    global _local_embedder
    if _local_embedder is None:
        try:
            from chromadb.utils.embedding_functions import (
                ONNXMiniLM_L6_V2 as DefaultEF,
            )
            _local_embedder = DefaultEF()
            log.info("Local CPU embedder loaded (ONNX MiniLM-L6-V2)")
        except Exception:
            # Older ChromaDB versions use a different name
            try:
                from chromadb.utils.embedding_functions import (
                    DefaultEmbeddingFunction,
                )
                _local_embedder = DefaultEmbeddingFunction()
                log.info("Local CPU embedder loaded (ChromaDB default)")
            except Exception as e:
                log.error("Failed to load local CPU embedder: %s", e)
                raise RuntimeError(
                    "Cannot load local CPU embedder. "
                    "Make sure chromadb and onnxruntime are installed."
                ) from e
    return _local_embedder


class LLMBridge:
    """
    Wrapper around any OpenAI-compatible LLM API.
    Instantiated once by the engine and injected into every PluginContext.

    Usage (inside a plugin):
        reply = ctx.llm.generate(prompt="...", system="...")
        vec   = ctx.llm.embed("some text")
    """

    def __init__(self, host: str, neocortex_model: str, embed_model: str,
                 default_params: dict, backend: str = "ollama",
                 api_key: str = "", embed_strategy: str = "api"):
        self.host             = host.rstrip("/")
        self.neocortex_model  = neocortex_model
        self.embed_model      = embed_model
        self.default_params   = default_params
        self.backend          = backend
        self.api_key          = api_key
        self.embed_strategy   = embed_strategy

        # Build base headers
        self._headers = {"Content-Type": "application/json"}
        if self.api_key:
            self._headers["Authorization"] = f"Bearer {self.api_key}"

        log.info("LLMBridge ready | backend=%s | host=%s | model=%s | embed=%s",
                 backend, host, neocortex_model, embed_strategy)

    # ── Text Generation ──────────────────────────────────────

    def generate(
        self,
        prompt: str,
        system: Optional[str] = None,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        num_predict: Optional[int] = None,
        timeout: Optional[int] = None,
    ) -> str:
        """
        Generate a text completion via the OpenAI-compatible
        /v1/chat/completions endpoint.

        Args:
            prompt:      User-turn content.
            system:      Full assembled system prompt (persona + state + memories).
            model:       Override model name. Defaults to neocortex_model.
            temperature: Override sampling temperature.
            num_predict: Override max tokens.

        Returns:
            Assistant reply as a plain string.
        """
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": model or self.neocortex_model,
            "messages": messages,
            "temperature": temperature or self.default_params.get("temperature", 0.75),
            "top_p": self.default_params.get("top_p", 0.9),
            "max_tokens": num_predict or self.default_params.get("num_predict", 512),
            "stream": False,
        }

        url = f"{self.host}/v1/chat/completions"
        effective_timeout = timeout if timeout is not None else self.default_params.get("timeout", 300)
        log.debug("LLM generate | url=%s | model=%s | prompt_len=%d | timeout=%d",
                  url, payload["model"], len(prompt), effective_timeout)

        try:
            r = requests.post(url, json=payload, headers=self._headers, timeout=effective_timeout)
            r.raise_for_status()
            data = r.json()

            reply = data["choices"][0]["message"]["content"].strip()

            # Strip thinking tags (common in reasoning models like Gemma 3/4)
            reply = _strip_thinking(reply)

            log.debug("LLM reply | len=%d chars", len(reply))
            return reply

        except requests.exceptions.ConnectionError:
            log.error("Cannot connect to LLM server at %s — is it running?", self.host)
            raise
        except requests.exceptions.HTTPError as e:
            log.error("LLM server returned error: %s | body=%s",
                      e, e.response.text[:500] if e.response else "")
            raise
        except Exception as e:
            log.error("LLM generate failed: %s", e)
            raise

    # ── Embeddings ───────────────────────────────────────────

    def embed(self, text: str) -> list[float]:
        """
        Embed text into a vector.

        Uses the server's /v1/embeddings endpoint if embed_strategy
        is "api", otherwise falls back to a local CPU-based model.

        Args:
            text: Any string — a memory, a query, an incoming message.

        Returns:
            List of floats (embedding vector).
        """
        log.debug("LLM embed | strategy=%s | text_len=%d",
                  self.embed_strategy, len(text))

        if self.embed_strategy == "local":
            return self._embed_local(text)
        else:
            return self._embed_api(text)

    def _embed_api(self, text: str) -> list[float]:
        """Call the server's /v1/embeddings endpoint."""
        url = f"{self.host}/v1/embeddings"
        payload = {
            "model": self.embed_model,
            "input": text,
        }

        try:
            r = requests.post(url, json=payload, headers=self._headers, timeout=60)
            r.raise_for_status()
            data = r.json()
            return data["data"][0]["embedding"]
        except requests.exceptions.ConnectionError:
            log.warning("Embeddings API unreachable — falling back to local CPU embedder")
            self.embed_strategy = "local"
            return self._embed_local(text)
        except Exception as e:
            log.error("API embed failed: %s — falling back to local CPU embedder", e)
            self.embed_strategy = "local"
            return self._embed_local(text)

    def _embed_local(self, text: str) -> list[float]:
        """Use ChromaDB's built-in ONNX model on CPU."""
        embedder = _get_local_embedder()
        result = embedder([text])
        # result is a list of embeddings; we sent one text, get one back
        vec = result[0]
        # Convert numpy array to plain list if needed
        if hasattr(vec, "tolist"):
            vec = vec.tolist()
        return vec

    # ── Convenience Methods ──────────────────────────────────

    def summarise_as_memory(self, text: str) -> str:
        """
        Ask the LLM to condense an action result into one memory sentence.
        Called by the engine after every autonomous action.

        Args:
            text: Raw output from an action (article summary, post draft, etc.)

        Returns:
            A single sentence in the first person.
        """
        prompt = (
            "Summarise the following in exactly one concise sentence, "
            "written in the first person as if you did it yourself:\n\n"
            f"{text}"
        )
        return self.generate(prompt=prompt, num_predict=128, temperature=0.4)

    def build_system_prompt(
        self,
        character_block: str,
        style_block: str,
        values_block: str,
        state_block: str,
        memories_block: str,
        extra_context: str = "",
    ) -> str:
        """
        Assemble the full system prompt from modular blocks.
        Called by the engine before every generate() call.
        """
        sections = [
            "=== WHO YOU ARE ===",
            character_block.strip(),
            "",
            "=== YOUR VOICE & STYLE ===",
            style_block.strip(),
            "",
            "=== YOUR VALUES & DIRECTIVES ===",
            values_block.strip(),
            "",
            "=== YOUR CURRENT STATE ===",
            state_block.strip(),
            "",
            "=== RELEVANT MEMORIES ===",
            memories_block.strip() or "(No specific memories retrieved.)",
        ]
        if extra_context.strip():
            sections += ["", "=== ADDITIONAL CONTEXT ===", extra_context.strip()]

        return "\n".join(sections)

# core/memory_manager.py
# ============================================================
# Project Kid — Memory Manager
# ChromaDB wrapper. One instance per persona, injected via ctx.
# ============================================================

import logging
import time
import uuid
from pathlib import Path
from typing import Optional

import chromadb
from chromadb.config import Settings

log = logging.getLogger(__name__)


class MemoryManager:
    """
    Manages a persona's long-term vector memory in ChromaDB.
    Injected into every PluginContext as ctx.memory.

    All embedding is handled externally (by the engine or by plugins
    via ctx.llm.embed) so this class has no LLM dependency.
    """

    def __init__(self, persona_dir: Path, collection_name: str = "memories"):
        self.persona_dir = persona_dir
        chroma_dir = persona_dir / "chroma_db"
        chroma_dir.mkdir(parents=True, exist_ok=True)

        self.client = chromadb.PersistentClient(
            path=str(chroma_dir),
            settings=Settings(anonymized_telemetry=False),
        )
        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )
        log.info("MemoryManager ready | persona=%s | count=%d",
                 persona_dir.name, self.collection.count())

    # ── Write ────────────────────────────────────────────────

    def add(self, text: str, embedding: list[float],
            importance: float = 0.5, source: str = "autonomous") -> str:
        """
        Store a memory with a pre-computed embedding.

        Args:
            text:       Memory content.
            embedding:  Vector from ctx.llm.embed(text).
            importance: 0.0–1.0. Set higher for significant events.
            source:     Tag: "autonomous" | "reply" | "manual" | "migration"

        Returns:
            UUID string of the new memory.
        """
        memory_id = str(uuid.uuid4())
        self.collection.add(
            ids=[memory_id],
            embeddings=[embedding],
            documents=[text],
            metadatas=[{
                "importance": importance,
                "source":     source,
                "timestamp":  int(time.time()),
            }],
        )
        log.info("Memory stored | id=%.8s | src=%s | imp=%.2f | '%s'",
                 memory_id, source, importance, text[:60])
        return memory_id

    def add_auto(self, text: str, llm, importance: float = 0.5,
                 source: str = "autonomous") -> str:
        """
        Convenience wrapper: embed then store.
        Args:
            llm: LLMBridge instance (passed in to avoid circular import).
        """
        return self.add(text=text, embedding=llm.embed(text),
                        importance=importance, source=source)

    # ── Read ─────────────────────────────────────────────────

    def retrieve(self, query_embedding: list[float], k: int = 5,
                 min_importance: float = 0.0) -> list[dict]:
        """
        Retrieve K most semantically similar memories.

        Args:
            query_embedding: Vector from ctx.llm.embed(query_text).
            k:               Max results to return.
            min_importance:  Filter threshold.

        Returns:
            List of memory dicts sorted by similarity (closest first).
        """
        total = self.collection.count()
        if total == 0:
            return []

        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=min(k * 2, total),
            include=["documents", "metadatas", "distances"],
        )

        memories = []
        for i, doc in enumerate(results["documents"][0]):
            meta = results["metadatas"][0][i]
            if meta.get("importance", 0) < min_importance:
                continue
            memories.append({
                "id":         results["ids"][0][i],
                "text":       doc,
                "importance": meta.get("importance", 0.0),
                "source":     meta.get("source", "unknown"),
                "timestamp":  meta.get("timestamp", 0),
                "distance":   results["distances"][0][i],
            })

        memories.sort(key=lambda m: m["distance"])
        return memories[:k]

    def retrieve_recent(self, k: int = 3) -> list[dict]:
        """
        Return the K most recently stored memories (chronological tail).
        Gives the LLM short-term continuity alongside semantic retrieval.
        """
        total = self.collection.count()
        if total == 0:
            return []

        all_data = self.collection.get(include=["documents", "metadatas"])
        memories = [
            {
                "id":         all_data["ids"][i],
                "text":       doc,
                "importance": all_data["metadatas"][i].get("importance", 0.0),
                "source":     all_data["metadatas"][i].get("source", "unknown"),
                "timestamp":  all_data["metadatas"][i].get("timestamp", 0),
                "distance":   0.0,
            }
            for i, doc in enumerate(all_data["documents"])
        ]
        memories.sort(key=lambda m: m["timestamp"], reverse=True)
        return memories[:k]

    def format_for_prompt(self, memories: list[dict]) -> str:
        """Render memory list as a numbered block for the system prompt."""
        if not memories:
            return "(No memories retrieved.)"
        return "\n".join(
            f"{i}. [{m['source']}] {m['text']}"
            for i, m in enumerate(memories, 1)
        )

    # ── Maintenance ──────────────────────────────────────────

    def delete(self, memory_id: str) -> None:
        self.collection.delete(ids=[memory_id])
        log.info("Memory deleted | id=%.8s", memory_id)

    def count(self) -> int:
        return self.collection.count()

    def list_all(self) -> list[dict]:
        """Return every memory sorted by timestamp. For editor.py only."""
        if self.collection.count() == 0:
            return []
        data = self.collection.get(include=["documents", "metadatas"])
        memories = [
            {
                "id":         data["ids"][i],
                "text":       doc,
                "importance": data["metadatas"][i].get("importance", 0.0),
                "source":     data["metadatas"][i].get("source", "unknown"),
                "timestamp":  data["metadatas"][i].get("timestamp", 0),
            }
            for i, doc in enumerate(data["documents"])
        ]
        memories.sort(key=lambda m: m["timestamp"])
        return memories

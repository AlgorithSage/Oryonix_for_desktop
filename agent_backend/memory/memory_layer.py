"""
Memory Layer — L0-L3 tiered memory (TencentDB-Agent-Memory inspired).

L0  raw trace     every step, action, outcome, screenshot hash
L1  atomic facts  distilled from L0 after task completion
L2  scenarios     recurring task patterns (same app, same workflow)
L3  persona       user preferences and long-term context

save_to_knowledge() writes to L0 and replaces Agent-S3's dropped notes buffer.
get_context_for_task() retrieves relevant L1-L3 facts to pre-populate SandboxACI context.
"""
from __future__ import annotations

import time
import uuid
import json
import sqlite3
import logging
from dataclasses import dataclass, field
from enum import IntEnum
from typing import TYPE_CHECKING, Any, Optional

# Configure logger
logger = logging.getLogger("desktopenv.agent")

if TYPE_CHECKING:
    from core.config import Config


class MemoryTier(IntEnum):
    L0_RAW = 0
    L1_FACTS = 1
    L2_SCENARIOS = 2
    L3_PERSONA = 3


@dataclass
class MemoryEntry:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    tier: MemoryTier = MemoryTier.L0_RAW
    task_id: str = ""
    content: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


class MemoryLayer:
    """Manages all 4 memory tiers. Backed by sqlite3 for resilient persistence."""

    def __init__(self, config: "Config") -> None:
        self.config = config
        self._db_path: str = "oryonix_memory.db"   # configurable in future

    async def init(self) -> None:
        """Create DB tables if they don't exist. Called once at startup."""
        logger.info(f"Initializing MemoryLayer SQLite database: {self._db_path}")
        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS memories (
                        id TEXT PRIMARY KEY,
                        tier INTEGER,
                        task_id TEXT,
                        content TEXT,
                        metadata TEXT,
                        timestamp REAL
                    )
                """)
                conn.commit()
            logger.info("Memory database tables created successfully.")
        except Exception as e:
            logger.error(f"Failed to initialize memory SQLite database: {e}")
            raise

    def save_to_knowledge(self, task_id: str, content: str, metadata: dict | None = None) -> None:
        """
        Write a raw fact to L0.
        Called by SandboxACI.save_to_knowledge() — replaces Agent-S3 notes buffer.
        """
        logger.info(f"MemoryLayer: Saving raw fact to L0 raw trace database for task_id: {task_id}")
        meta_str = json.dumps(metadata or {})
        entry_id = str(uuid.uuid4())
        timestamp = time.time()
        
        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.execute(
                    "INSERT INTO memories (id, tier, task_id, content, metadata, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
                    (entry_id, int(MemoryTier.L0_RAW), task_id, content, meta_str, timestamp)
                )
                conn.commit()
        except Exception as e:
            logger.error(f"Failed to save raw L0 memory: {e}")

    def get_context_for_task(self, goal: str, session_id: str) -> str:
        """
        Retrieve relevant L1-L3 memories to inject into SandboxACI context at task start.
        Returns a formatted string ready for system prompt injection.
        """
        logger.info(f"MemoryLayer: Retrieving semantic L1-L3 context for goal: '{goal}'")
        
        l1_facts = []
        l2_scenarios = []
        l3_persona = []

        try:
            # Query L1-L3 memories ordered by timestamp
            with sqlite3.connect(self._db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT tier, content FROM memories WHERE tier IN (?, ?, ?) ORDER BY timestamp DESC LIMIT 50",
                    (int(MemoryTier.L1_FACTS), int(MemoryTier.L2_SCENARIOS), int(MemoryTier.L3_PERSONA))
                )
                rows = cursor.fetchall()

            for tier, content in rows:
                if tier == int(MemoryTier.L1_FACTS):
                    l1_facts.append(content)
                elif tier == int(MemoryTier.L2_SCENARIOS):
                    l2_scenarios.append(content)
                elif tier == int(MemoryTier.L3_PERSONA):
                    l3_persona.append(content)
        except Exception as e:
            logger.error(f"Failed to query memories for context: {e}")
            return "No relevant memories found in database (query failed)."

        # Format context segments
        context_parts = []
        if l1_facts:
            context_parts.append("### Relevant Atomic Facts (L1):\n" + "\n".join([f"- {f}" for f in l1_facts]))
        if l2_scenarios:
            context_parts.append("### Relevant Scenario Workflows (L2):\n" + "\n".join([f"- {s}" for s in l2_scenarios]))
        if l3_persona:
            context_parts.append("### User Persona Context (L3):\n" + "\n".join([f"- {p}" for p in l3_persona]))

        return "\n\n".join(context_parts) if context_parts else "No relevant memories found in database."

    def distill_l0_to_l1(self, task_id: str) -> None:
        """
        After a task completes, promote key L0 entries to L1 atomic facts.
        Called by Orchestrator on SUCCEEDED or FAILED.
        """
        logger.info(f"MemoryLayer: Distilling L0 traces to L1 atomic facts for task_id: {task_id}")
        try:
            with sqlite3.connect(self._db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT content, metadata FROM memories WHERE task_id = ? AND tier = ?",
                    (task_id, int(MemoryTier.L0_RAW))
                )
                rows = cursor.fetchall()
                
                # Promote each L0 raw note to L1 atomic fact
                for content, metadata in rows:
                    entry_id = str(uuid.uuid4())
                    timestamp = time.time()
                    conn.execute(
                        "INSERT INTO memories (id, tier, task_id, content, metadata, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
                        (entry_id, int(MemoryTier.L1_FACTS), task_id, content, metadata, timestamp)
                    )
                conn.commit()
            logger.info(f"Distillation complete. L0 traces promoted for task_id {task_id}")
        except Exception as e:
            logger.error(f"Failed to distill memories: {e}")

    def store(self, entry: MemoryEntry) -> None:
        """Persist a MemoryEntry to the SQLite store."""
        meta_str = json.dumps(entry.metadata)
        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO memories (id, tier, task_id, content, metadata, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
                    (entry.id, int(entry.tier), entry.task_id, entry.content, meta_str, entry.timestamp)
                )
                conn.commit()
        except Exception as e:
            logger.error(f"Failed to store memory entry {entry.id}: {e}")

    def query(self, tier: MemoryTier, query: str, limit: int = 10) -> list[MemoryEntry]:
        """Retrieve up to `limit` entries from `tier` semantically related to `query`."""
        # Clean query keywords for local air-gapped matching
        words = [w.lower() for w in query.split() if len(w) > 3]
        
        if words:
            like_clauses = " OR ".join(["content LIKE ?"] * len(words))
            like_params = [f"%{w}%" for w in words]
            sql = f"SELECT id, tier, task_id, content, metadata, timestamp FROM memories WHERE tier = ? AND ({like_clauses}) ORDER BY timestamp DESC LIMIT ?"
            params = [int(tier)] + like_params + [limit]
        else:
            sql = "SELECT id, tier, task_id, content, metadata, timestamp FROM memories WHERE tier = ? ORDER BY timestamp DESC LIMIT ?"
            params = [int(tier), limit]

        entries = []
        try:
            with sqlite3.connect(self._db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(sql, params)
                rows = cursor.fetchall()

            for rid, rtier, rtask_id, rcontent, rmetadata, rtimestamp in rows:
                try:
                    meta = json.loads(rmetadata)
                except Exception:
                    meta = {}
                entries.append(MemoryEntry(
                    id=rid,
                    tier=MemoryTier(rtier),
                    task_id=rtask_id,
                    content=rcontent,
                    metadata=meta,
                    timestamp=rtimestamp
                ))
        except Exception as e:
            logger.error(f"Failed to query memories from SQLite: {e}")
            
        return entries

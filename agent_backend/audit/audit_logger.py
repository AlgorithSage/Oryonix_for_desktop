"""
Audit Logger — append-only hash-chained event log.

Each entry:  SHA-256(prev_hash || event_data_json)
First entry: prev_hash = GENESIS_HASH ("000...0")

Designed for WORM storage (ZFS readonly snapshot or S3 Object Lock).
Chain can be verified offline with verify_chain().
"""
from __future__ import annotations

import hashlib
import json
import time
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

# Configure logger
logger = logging.getLogger("desktopenv.agent")

if TYPE_CHECKING:
    from core.config import Config


@dataclass
class AuditEntry:
    event_type: str
    task_id: str
    data: dict[str, Any]
    timestamp: float = field(default_factory=time.time)
    prev_hash: str = ""
    hash: str = ""


class AuditLogger:
    """Append-only hash-chained audit log. Streams to SIEM on flush."""

    GENESIS_HASH = "0" * 64   # placeholder for the very first entry

    def __init__(self, config: "Config") -> None:
        self.config = config
        self._chain: list[AuditEntry] = []
        self._last_hash: str = self.GENESIS_HASH

    def log(self, event_type: str, task_id: str, data: dict[str, Any]) -> None:
        """
        Append a new entry to the chain.
        Computes: hash = SHA-256(prev_hash || json(event_type + timestamp + data))
        """
        timestamp = time.time()
        
        # Ensure json string is sorted and deterministic
        serialized_data = json.dumps({
            "event_type": event_type,
            "task_id": task_id,
            "timestamp": timestamp,
            "data": data
        }, sort_keys=True)
        
        entry_hash = self._compute_hash(self._last_hash, serialized_data)
        
        entry = AuditEntry(
            event_type=event_type,
            task_id=task_id,
            data=data,
            timestamp=timestamp,
            prev_hash=self._last_hash,
            hash=entry_hash
        )
        self._chain.append(entry)
        self._last_hash = entry_hash
        logger.info(f"Audit log appended: {event_type} | Hash: {entry_hash[:8]}... | Prev: {entry.prev_hash[:8]}...")

    def verify_chain(self) -> bool:
        """
        Walk the entire chain and recompute each hash.
        Returns True if unbroken, False if any hash mismatches.
        """
        logger.info("Verifying audit log integrity...")
        current_prev_hash = self.GENESIS_HASH
        
        for index, entry in enumerate(self._chain):
            # Re-serialize deterministically
            serialized_data = json.dumps({
                "event_type": entry.event_type,
                "task_id": entry.task_id,
                "timestamp": entry.timestamp,
                "data": entry.data
            }, sort_keys=True)
            
            recalculated_hash = self._compute_hash(current_prev_hash, serialized_data)
            
            if recalculated_hash != entry.hash:
                logger.error(
                    f"Audit chain corruption detected at index {index}! Entry hash mismatch.\n"
                    f"Expected: {entry.hash}\n"
                    f"Calculated: {recalculated_hash}"
                )
                return False
            
            if entry.prev_hash != current_prev_hash:
                logger.error(
                    f"Audit chain link mismatch at index {index}! Entry prev_hash '{entry.prev_hash[:8]}' "
                    f"does not match expected previous hash '{current_prev_hash[:8]}'."
                )
                return False
                
            current_prev_hash = entry.hash
            
        logger.info(f"Audit log integrity check passed. Chain unbroken. Total blocks: {len(self._chain)}")
        return True

    def flush_to_disk(self, path: str) -> None:
        """Write all entries as NDJSON to the given path (WORM volume)."""
        import os
        logger.info(f"Flushing audit log to WORM path: {path}")
        try:
            directory = os.path.dirname(path)
            if directory:
                os.makedirs(directory, exist_ok=True)
                
            with open(path, "w", encoding="utf-8") as f:
                for entry in self._chain:
                    entry_dict = {
                        "event_type": entry.event_type,
                        "task_id": entry.task_id,
                        "timestamp": entry.timestamp,
                        "prev_hash": entry.prev_hash,
                        "hash": entry.hash,
                        "data": entry.data
                    }
                    f.write(json.dumps(entry_dict) + "\n")
            logger.info("Audit log flushed to disk successfully.")
        except Exception as e:
            logger.error(f"Failed to flush audit log to disk: {e}")

    def _compute_hash(self, prev_hash: str, entry_data: str) -> str:
        """SHA-256(prev_hash + entry_data). Deterministic, no salt."""
        return hashlib.sha256(f"{prev_hash}{entry_data}".encode()).hexdigest()

"""
Context Compressor — maintains a Mermaid symbolic graph of all agent steps.
Replaces Agent-S3's flush_messages() entirely (flush_messages() is a no-op).

Target: ≤ 5 000 tokens.

Pruning strategy (Gap G):
  - Steps N-10 to N  →  kept as full nodes (recent context, full detail)
  - Steps 1 to N-10  →  collapsed into phase summaries grouped by sub-goal
    Each summary: "Phase: <goal> | Steps: <n> | Outcome: <x> | Facts: [...]"
  - Failed attempts survive as: "tried X, failed because Y"
  - Discovered element IDs / state facts survive into the summary's key_facts

On cloud escalation (Gap B):
  to_mermaid() output = the handoff package injected into the fresh Worker's
  first user message. Old Worker is discarded after serialization.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

# Configure logger
logger = logging.getLogger("desktopenv.agent")


@dataclass
class StepNode:
    step_id: int
    sub_goal: str
    action_taken: str
    outcome: str                              # "success" | "failed" | "retried"
    key_facts: list[str] = field(default_factory=list)
    element_ids_discovered: list[str] = field(default_factory=list)
    failed_reason: Optional[str] = None


@dataclass
class PhaseSummary:
    phase_label: str
    steps_count: int
    outcome: str                              # "success" | "partial" | "failed"
    key_facts: list[str] = field(default_factory=list)


class ContextCompressor:
    """Builds, prunes, and serializes the Mermaid task graph."""

    RECENT_WINDOW = 10  # keep last N steps as full nodes before pruning

    def __init__(self) -> None:
        self._steps: list[StepNode] = []
        self._phase_summaries: list[PhaseSummary] = []
        self._current_sub_goal: str = ""

    def add_step(self, node: StepNode) -> None:
        """Append a completed step and trigger pruning if needed."""
        self._steps.append(node)
        self.prune()

    def set_sub_goal(self, sub_goal: str) -> None:
        """Update the current sub-goal label used when grouping phase summaries."""
        self._current_sub_goal = sub_goal

    def prune(self) -> None:
        """
        Collapse steps older than RECENT_WINDOW into phase summaries.
        Preserves key_facts, failed reasons, and element_ids_discovered.
        """
        if len(self._steps) <= self.RECENT_WINDOW:
            return

        # Split older steps for compaction
        collapse_limit = len(self._steps) - self.RECENT_WINDOW
        steps_to_collapse = self._steps[:collapse_limit]
        self._steps = self._steps[collapse_limit:]

        # Group steps sequentially by sub_goal
        groups: list[list[StepNode]] = []
        current_group: list[StepNode] = []
        for step in steps_to_collapse:
            if not current_group or current_group[0].sub_goal == step.sub_goal:
                current_group.append(step)
            else:
                groups.append(current_group)
                current_group = [step]
        if current_group:
            groups.append(current_group)

        # Build Phase Summaries
        for group in groups:
            sub_goal = group[0].sub_goal
            steps_count = len(group)
            
            # Phase outcome maps to the last step's outcome
            last_outcome = group[-1].outcome
            phase_outcome = "success" if last_outcome == "success" else "failed"

            # Gather facts
            key_facts = []
            for step in group:
                # Element IDs
                if step.element_ids_discovered:
                    key_facts.append(f"Discovered elements: {', '.join(step.element_ids_discovered)}")
                
                # Failed attempts survive (Gap G: "tried X, failed because Y")
                if step.outcome in ("failed", "retried") and step.failed_reason:
                    key_facts.append(f"tried {step.action_taken}, failed because {step.failed_reason}")
                
                # Custom key facts
                if step.key_facts:
                    key_facts.extend(step.key_facts)

            # Check if summary for this sub_goal already exists
            merged = False
            for existing in self._phase_summaries:
                if existing.phase_label == sub_goal:
                    existing.steps_count += steps_count
                    existing.outcome = phase_outcome
                    existing.key_facts = list(set(existing.key_facts + key_facts))
                    merged = True
                    break

            if not merged:
                self._phase_summaries.append(PhaseSummary(
                    phase_label=sub_goal,
                    steps_count=steps_count,
                    outcome=phase_outcome,
                    key_facts=list(set(key_facts))
                ))

    def to_mermaid(self) -> str:
        """
        Serialize the full graph (summaries + recent full nodes) as a
        Mermaid flowchart string suitable for LLM context injection.
        """
        lines = ["flowchart TD"]
        node_ids = []

        # 1. Add Phase Summaries
        for i, summary in enumerate(self._phase_summaries):
            node_id = f"P{i}"
            node_ids.append(node_id)
            facts_str = "<br>".join([f"- {f}" for f in summary.key_facts]) if summary.key_facts else "None"
            label = f"Phase: {summary.phase_label} (Steps: {summary.steps_count})<br>Outcome: {summary.outcome}<br>Facts:<br>{facts_str}"
            label_escaped = label.replace('"', '\\"').replace('[', '(').replace(']', ')')
            lines.append(f'    {node_id}["{label_escaped}"]')

        # 2. Add Recent Steps
        for step in self._steps:
            node_id = f"S{step.step_id}"
            node_ids.append(node_id)
            facts_str = "<br>".join([f"- {f}" for f in step.key_facts]) if step.key_facts else "None"
            label = f"Step {step.step_id}: {step.sub_goal}<br>Action: {step.action_taken}<br>Outcome: {step.outcome}<br>Facts:<br>{facts_str}"
            label_escaped = label.replace('"', '\\"').replace('[', '(').replace(']', ')')
            lines.append(f'    {node_id}["{label_escaped}"]')

        # Fallback if empty graph
        if not node_ids:
            return "flowchart TD\n    Start[Start Task]"

        # 3. Add sequence connections
        for i in range(len(node_ids) - 1):
            lines.append(f"    {node_ids[i]} --> {node_ids[i+1]}")

        return "\n".join(lines)

    def token_estimate(self) -> int:
        """Rough token count for the current serialized graph."""
        return len(self.to_mermaid()) // 4

    def reset(self) -> None:
        """Clear all state — called at task start."""
        self._steps = []
        self._phase_summaries = []
        self._current_sub_goal = ""

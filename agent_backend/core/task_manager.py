"""
Task Manager — manages task lifecycle via a state machine.

States:
  IDLE → PLANNING → EXECUTING → VERIFYING
                              → PAUSED_FOR_APPROVAL
                              → PAUSED_FOR_HUMAN_TAKEOVER
       → REPLANNING → EXECUTING
       → ESCALATED  → PLANNING (fresh Worker on cloud)
       → ROLLING_BACK → FAILED
       → FAILED
       → SUCCEEDED
"""
from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional, TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.config import Config


class TaskState(str, Enum):
    IDLE = "IDLE"
    PLANNING = "PLANNING"
    EXECUTING = "EXECUTING"
    VERIFYING = "VERIFYING"
    PAUSED_FOR_APPROVAL = "PAUSED_FOR_APPROVAL"
    PAUSED_FOR_HUMAN_TAKEOVER = "PAUSED_FOR_HUMAN_TAKEOVER"
    REPLANNING = "REPLANNING"
    ROLLING_BACK = "ROLLING_BACK"
    ESCALATED = "ESCALATED"
    FAILED = "FAILED"
    SUCCEEDED = "SUCCEEDED"


@dataclass
class Task:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    goal: str = ""
    state: TaskState = TaskState.IDLE
    session_id: str = ""
    steps_executed: int = 0
    consecutive_failures: int = 0
    tokens_used: int = 0
    is_escalated: bool = False
    is_cloud_forced: bool = False
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


class TaskManager:
    """Manages a single active task's state machine."""

    # Valid state transitions — guards prevent invalid moves
    _TRANSITIONS: dict[TaskState, frozenset[TaskState]] = {
        TaskState.IDLE: frozenset({TaskState.PLANNING}),
        TaskState.PLANNING: frozenset({TaskState.EXECUTING, TaskState.FAILED}),
        TaskState.EXECUTING: frozenset({
            TaskState.VERIFYING,
            TaskState.PAUSED_FOR_APPROVAL,
            TaskState.PAUSED_FOR_HUMAN_TAKEOVER,
            TaskState.FAILED,
        }),
        TaskState.VERIFYING: frozenset({
            TaskState.EXECUTING,
            TaskState.REPLANNING,
            TaskState.ESCALATED,
            TaskState.SUCCEEDED,
            TaskState.FAILED,
        }),
        TaskState.PAUSED_FOR_APPROVAL: frozenset({TaskState.EXECUTING, TaskState.FAILED}),
        TaskState.PAUSED_FOR_HUMAN_TAKEOVER: frozenset({TaskState.EXECUTING, TaskState.FAILED}),
        TaskState.REPLANNING: frozenset({TaskState.EXECUTING, TaskState.FAILED}),
        TaskState.ROLLING_BACK: frozenset({TaskState.FAILED}),
        TaskState.ESCALATED: frozenset({TaskState.PLANNING, TaskState.FAILED}),
        TaskState.FAILED: frozenset(),
        TaskState.SUCCEEDED: frozenset(),
    }

    # How many consecutive Verifier failures trigger cloud escalation
    ESCALATION_THRESHOLD = 2

    def __init__(self, config: "Config", on_state_change: Optional[Callable[[Task], Any]] = None):
        self.config = config
        self.task: Optional[Task] = None
        self._on_state_change = on_state_change

    async def start_task(self, goal: str, session_id: str) -> Task:
        """Create a new Task and move it to PLANNING state."""
        self.task = Task(goal=goal, session_id=session_id, state=TaskState.IDLE)
        await self.transition(TaskState.PLANNING)
        return self.task

    async def transition(self, new_state: TaskState) -> None:
        """
        Move the active task to new_state.
        Raises ValueError if the transition is not allowed.
        Fires on_state_change callback after every valid transition.
        """
        if self.task is None:
            raise ValueError("No active task to transition.")

        current = self.task.state
        if new_state not in self._TRANSITIONS.get(current, frozenset()):
            raise ValueError(f"Transition from {current} to {new_state} is not allowed.")

        self.task.state = new_state
        self.task.updated_at = time.time()

        if self._on_state_change:
            if asyncio.iscoroutinefunction(self._on_state_change):
                await self._on_state_change(self.task)
            else:
                self._on_state_change(self.task)

    def record_failure(self) -> bool:
        """
        Increment consecutive_failures.
        Returns True if the escalation threshold is reached.
        """
        if self.task is None:
            raise ValueError("No active task.")
        self.task.consecutive_failures += 1
        return self.task.consecutive_failures >= self.ESCALATION_THRESHOLD

    def reset_failure_count(self) -> None:
        """Called after a successful Verifier result — resets consecutive_failures."""
        if self.task is None:
            raise ValueError("No active task.")
        self.task.consecutive_failures = 0

    def record_tokens(self, count: int) -> bool:
        """
        Accumulate token usage.
        Returns True if the per-task budget is exhausted (Gap I).
        """
        if self.task is None:
            raise ValueError("No active task.")

        self.task.tokens_used += count

        # Determine budget limit based on task status
        if self.task.is_escalated:
            budget = self.config.escalated_task_token_budget
        elif self.task.is_cloud_forced:
            budget = self.config.cloud_task_token_budget
        else:
            budget = self.config.local_task_token_budget

        return self.task.tokens_used > budget

    def get_state(self) -> Optional[TaskState]:
        return self.task.state if self.task else None

    def is_terminal(self) -> bool:
        """Returns True if the current task has reached a terminal state."""
        if self.task is None:
            return True
        return self.task.state in (TaskState.FAILED, TaskState.SUCCEEDED)

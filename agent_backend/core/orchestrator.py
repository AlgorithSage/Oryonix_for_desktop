"""
Orchestrator — main agent loop.
Replaces Agent-S3's cli_app.py run_agent() loop entirely.

Flow per task:
  start_task
  → Recipe Engine (fast path)
    → HIT: run deterministic recipe, verify, done
    → MISS: enter Worker loop
  → Worker loop (max MAX_STEPS):
      screenshot → Worker.generate_next_action()
      → Action Normalizer → SandboxACI.execute()
      → Verifier cascade
        → SUCCESS: next step
        → FAILURE ×2: escalate to cloud or FAILED
        → BUDGET: FAILED
  → SUCCEEDED / FAILED
"""
from __future__ import annotations

import logging
import asyncio
from typing import TYPE_CHECKING, Any

from core.task_manager import TaskState
from llm.router import ModelTier
from llm.action_normalizer import ActionNormalizer
from verifier.verifier import VerificationResult

if TYPE_CHECKING:
    from audit.audit_logger import AuditLogger
    from bridge.ws_server import WebSocketServer
    from context.compressor import ContextCompressor
    from core.config import Config
    from core.task_manager import TaskManager
    from llm.router import LLMRouter
    from memory.memory_layer import MemoryLayer
    from recipe.recipe_engine import RecipeEngine
    from sandbox.sandbox_aci import SandboxACI
    from verifier.verifier import Verifier

# Configure logger
logger = logging.getLogger("desktopenv.agent")

_BRAIN_SYSTEM = """You are the high-level planning "Brain" of an advanced computer-use agent. 
Your job is to guide a local GUI execution "Actor" to achieve a user's main goal.
You do this by decomposing the main goal into small, concrete, step-by-step sub-goals.

Main Goal: {main_goal}

At each step, you will be shown:
1. A screenshot of the current screen.
2. The chronological history of actions taken and their outcomes.

Based on the screen and history, you must output exactly one of the following formats:
- If the main goal has not yet been achieved:
  SUB-GOAL: <Provide a single, clear, extremely focused 1-step sub-goal for the Actor to execute next. Examples: "Click the Chrome icon on the desktop", "Type 'python' in the terminal", "Click the 'Login' button">
  
- If the main goal is fully and successfully achieved:
  SUB-GOAL: DONE

Keep the sub-goals simple, precise, and direct. The Actor is a local grounding model that performs best with single, clear instructions."""


class Orchestrator:
    """Drives the full per-task agent loop end-to-end."""

    MAX_STEPS = 50

    def __init__(
        self,
        config: "Config",
        task_manager: "TaskManager",
        router: "LLMRouter",
        sandbox: "SandboxACI",
        verifier: "Verifier",
        compressor: "ContextCompressor",
        memory: "MemoryLayer",
        recipe_engine: "RecipeEngine",
        audit: "AuditLogger",
        ws_server: "WebSocketServer",
    ) -> None:
        self.config = config
        self.task_manager = task_manager
        self.router = router
        self.sandbox = sandbox
        self.verifier = verifier
        self.compressor = compressor
        self.memory = memory
        self.recipe_engine = recipe_engine
        self.audit = audit
        self.ws = ws_server
        self._action_normalizer = ActionNormalizer()
        self._escalation_context: str = ""   # Gap B: Mermaid graph stored after escalation
        self._task_messages: list[dict] = []  # Per-task conversation history (Fara-7B fallback path)
        self._action_history: list[str] = []  # ShowUI-format step history (ShowUI primary path)
        self._last_parse_mode: str = "claude_gpt"
        self._showui = None                   # Lazy-loaded ShowUIAgent instance
        self._showui_load_attempted: bool = False
        self._current_sub_goal: str | None = None
        self._sub_goal_failure_count: int = 0

    def _log_audit(self, event_type: str, data: dict[str, Any]) -> None:
        """Helper to write to the hash-chained append-only AuditLogger."""
        task_id = self.task_manager.task.id if self.task_manager.task else "system"
        self.audit.log(event_type, task_id, data)

    async def run(self, goal: str, session_id: str) -> None:
        """
        Entry point: run a complete task from natural-language goal to
        SUCCEEDED or FAILED. Emits state-change events to WebSocket.
        """
        logger.info(f"Orchestrator: running task with goal='{goal}', session_id='{session_id}'")
        try:
            # 1. Start task in PLANNING state
            task = await self.task_manager.start_task(goal, session_id)
            await self._emit("state_change", {"state": task.state, "task_id": task.id})

            # Reset per-task state
            self.compressor.reset()
            self._task_messages = []
            self._action_history = []
            self._last_parse_mode = "claude_gpt"
            if hasattr(self.sandbox, "reset_session"):
                await self.sandbox.reset_session()
            await self.sandbox.init_dimensions()

            # Save genesis audit event
            self._log_audit("task_start", {"goal": goal, "session_id": session_id})

            # 2. Get screenshot
            screenshot = await self.sandbox.take_screenshot()

            # 3. Try Recipe Fast Path
            recipe_hit = await self._try_recipe_fast_path(screenshot)
            if recipe_hit:
                # Successfully matched and executed deterministic sequence!
                await self.task_manager.transition(TaskState.SUCCEEDED)
                await self._emit("state_change", {"state": TaskState.SUCCEEDED, "task_id": task.id})
                await self._emit("task_done", {
                    "success": True,
                    "message": "Task achieved successfully via deterministic fast-path recipe bypass.",
                    "task_id": task.id
                })
                self._log_audit("task_end", {"success": True, "message": "Fast-path SUCCESS"})
                return

            # 4. Fall back to Worker Loop
            # _try_recipe_fast_path() may leave task in PLANNING, VERIFYING, or EXECUTING
            # depending on which failure path was hit — normalize to EXECUTING
            current_state = self.task_manager.get_state()
            if current_state != TaskState.EXECUTING:
                await self.task_manager.transition(TaskState.EXECUTING)
                await self._emit("state_change", {"state": TaskState.EXECUTING, "task_id": task.id})

            await self._worker_loop(goal)

        except Exception as e:
            logger.exception(f"Exception during orchestrator execution: {e}")
            if self.task_manager.task and not self.task_manager.is_terminal():
                try:
                    await self.task_manager.transition(TaskState.FAILED)
                except Exception:
                    pass
                await self._emit("state_change", {
                    "state": TaskState.FAILED,
                    "task_id": self.task_manager.task.id
                })
                await self._emit("task_done", {
                    "success": False,
                    "message": f"Task execution failed with error: {e}",
                    "task_id": self.task_manager.task.id
                })

    async def _try_recipe_fast_path(self, screenshot: bytes) -> bool:
        """
        Check Recipe Engine before entering the Worker loop.
        Returns True if a recipe HIT was found and executed successfully.
        """
        task = self.task_manager.task
        if task is None:
            return False

        logger.info("Checking recipe engine fast path...")
        match_res = self.recipe_engine.match(screenshot)
        if not match_res or not match_res.is_hit:
            logger.info("Recipe engine MISS. Proceeding to active worker loop.")
            return False

        recipe = match_res.recipe
        logger.info(f"Recipe engine HIT: '{recipe.name}' (ID: {recipe.recipe_id}). Bypassing Worker Loop!")
        self._log_audit("recipe_hit", {"recipe_id": recipe.recipe_id, "recipe_name": recipe.name})

        # Transition task to EXECUTING
        await self.task_manager.transition(TaskState.EXECUTING)
        await self._emit("state_change", {"state": TaskState.EXECUTING, "task_id": task.id})

        # Execute actions in sandbox
        success = await self.recipe_engine.execute_recipe(recipe, self.sandbox)
        if not success:
            logger.error("Recipe execution failed. Falling back to planning loop.")
            self._log_audit("recipe_execution_failed", {"recipe_id": recipe.recipe_id})
            # Advance to VERIFYING so run() can uniformly do VERIFYING → EXECUTING
            await self.task_manager.transition(TaskState.VERIFYING)
            await self._emit("state_change", {"state": TaskState.VERIFYING, "task_id": task.id})
            return False

        # Transition to VERIFYING
        await self.task_manager.transition(TaskState.VERIFYING)
        await self._emit("state_change", {"state": TaskState.VERIFYING, "task_id": task.id})

        # Capture post-screenshot
        after_screenshot = await self.sandbox.take_screenshot()

        # Run Verifier cascade
        ver_out = await self.verifier.verify(
            sub_goal=task.goal,
            action_taken="Deterministic Recipe Execution",
            before_screenshot=screenshot,
            after_screenshot=after_screenshot,
            accessibility_before=None,
            accessibility_after=None
        )

        if ver_out.result == VerificationResult.SUCCESS:
            logger.info("Fast path recipe successfully verified.")
            self.recipe_engine.update_verified_success(recipe.recipe_id)
            
            # Promote memory trace (distill)
            self.memory.save_to_knowledge(
                task_id=task.id,
                content=f"Recipe '{recipe.name}' execution successful.",
                metadata={"step_number": 0, "sub_goal": task.goal, "action_executed": "recipe_bypass", "verified_success": True}
            )
            self.memory.distill_l0_to_l1(task.id)
            return True
        else:
            logger.warning(f"Fast path recipe execution failed verification: {ver_out.reason}. Falling back to planning loop.")
            return False

    async def _get_next_sub_goal(self, main_goal: str, screenshot: bytes, history: list[str]) -> str:
        """
        Formulate a sub-goal planning request to the Cloud Brain (Claude).
        Inject the main user goal, current screenshot, and chronological step history.
        """
        import re
        if self.config.air_gap:
            logger.warning("[Brain-Actor] Air-gapped mode active. Brain call blocked; defaulting to main goal.")
            return main_goal

        brain_system_prompt = _BRAIN_SYSTEM.format(main_goal=main_goal)
        
        history_str = "\n".join(history) if history else "No actions taken yet."
        user_message_content = (
            f"Here is the history of actions taken so far:\n"
            f"{history_str}\n\n"
            f"Please inspect the current screen and output the next sub-goal."
        )

        try:
            task_type = "desktop"
            if "web" in main_goal.lower() or "browser" in main_goal.lower() or "http" in main_goal.lower():
                task_type = "web"
                
            agent = self.router.get_agent(task_type, is_escalated=True)
            agent.add_system_prompt(brain_system_prompt)
            agent.add_message(
                text_content=user_message_content,
                image_content=screenshot if screenshot else None,
                role="user"
            )
            
            logger.info("[Brain-Actor] Calling Cloud Brain (Claude) for next sub-goal...")
            loop = asyncio.get_running_loop()
            response_text = await loop.run_in_executor(
                None,
                lambda: agent.get_response(temperature=0.0, max_new_tokens=1024)
            )
            
            response_text = response_text.strip()
            logger.info(f"[Brain-Actor] Brain Response: {response_text}")
            
            match = re.search(r"SUB-GOAL:\s*(.*)", response_text, re.IGNORECASE)
            if match:
                sub_goal = match.group(1).strip()
            else:
                if "done" in response_text.lower() and len(response_text) < 15:
                    sub_goal = "DONE"
                else:
                    sub_goal = response_text
                    
            if sub_goal.upper() == "DONE" or "SUB-GOAL: DONE" in response_text.upper():
                return "DONE"
                
            return sub_goal
            
        except Exception as e:
            logger.warning(f"[Brain-Actor] Failed to call Cloud Brain: {e}. Falling back to main goal.")
            return main_goal

    async def _worker_loop(self, goal: str) -> None:
        """
        Core step loop: screenshot → Worker → Normalizer → SandboxACI → Verifier.
        Handles failure counting, escalation, token budget, and state transitions.
        """
        task = self.task_manager.task
        if task is None:
            return

        self._current_sub_goal = None
        self._sub_goal_failure_count = 0

        step = 0
        while step < self.MAX_STEPS:
            step += 1
            task.steps_executed = step
            logger.info(f"Worker Loop Step {step}/{self.MAX_STEPS}")

            # 1. Budget checking (simulated token depletion of 500 tokens per planning choice)
            budget_exhausted = self.task_manager.record_tokens(500)
            if budget_exhausted:
                logger.error("Token budget exhausted. Failing task.")
                await self.task_manager.transition(TaskState.FAILED)
                await self._emit("state_change", {"state": TaskState.FAILED, "task_id": task.id})
                await self._emit("task_done", {
                    "success": False,
                    "message": "Token budget exhausted.",
                    "task_id": task.id
                })
                self._log_audit("task_budget_exhausted", {"tokens_used": task.tokens_used})
                return

            # 2. Capture observation
            before_screenshot = await self.sandbox.take_screenshot()
            acc_before = None
            if hasattr(self.sandbox, "get_accessibility_tree"):
                acc_before = await self.sandbox.get_accessibility_tree()

            # 2.b Brain-Actor Mode Sub-Goal generation
            if self.config.brain_actor_mode:
                if not self._current_sub_goal:
                    logger.info(f"[Brain-Actor] Current sub-goal is empty. Fetching next sub-goal from Brain...")
                    self._current_sub_goal = await self._get_next_sub_goal(goal, before_screenshot, self._action_history)
                    self._sub_goal_failure_count = 0
                    logger.info(f"[Brain-Actor] Active sub-goal set to: '{self._current_sub_goal}'")
                
                # Check for overall completion
                if self._current_sub_goal == "DONE":
                    logger.info("[Brain-Actor] Brain returned DONE. Performing final goal verification...")
                    await self.task_manager.transition(TaskState.VERIFYING)
                    await self._emit("state_change", {"state": TaskState.VERIFYING, "task_id": task.id})

                    after_screenshot = await self.sandbox.take_screenshot()
                    acc_after = None
                    if hasattr(self.sandbox, "get_accessibility_tree"):
                        acc_after = await self.sandbox.get_accessibility_tree()

                    ver_out = await self.verifier.verify(
                        sub_goal=goal,
                        action_taken="Brain Plan Completed",
                        before_screenshot=before_screenshot,
                        after_screenshot=after_screenshot,
                        accessibility_before=acc_before,
                        accessibility_after=acc_after
                    )

                    if ver_out.result == VerificationResult.SUCCESS:
                        self.task_manager.reset_failure_count()
                        self.memory.save_to_knowledge(
                            task_id=task.id,
                            content=f"Brain completed task successfully: {ver_out.reason}",
                            metadata={"step": step, "sub_goal": goal, "action_executed": "brain_done", "verified_success": True}
                        )
                        self.memory.distill_l0_to_l1(task.id)

                        await self.task_manager.transition(TaskState.SUCCEEDED)
                        await self._emit("state_change", {"state": TaskState.SUCCEEDED, "task_id": task.id})
                        await self._emit("task_done", {
                            "success": True,
                            "message": "Task achieved successfully via Brain-Actor separation.",
                            "task_id": task.id
                        })
                        self._log_audit("task_end", {"success": True, "message": "Brain verification SUCCESS."})
                        return
                    else:
                        logger.warning("Brain verification cascade failed. Forcing replan...")
                        self._current_sub_goal = None
                        self._sub_goal_failure_count = 0
                        continue

                # Use sub-goal to drive the local actor instead of the main goal
                active_instruction = self._current_sub_goal
            else:
                active_instruction = goal

            # 3. Call _execute_step to retrieve next action and reflection
            step_info, actions = await self._execute_step(active_instruction, {"screenshot": before_screenshot, "acc": acc_before})

            if not actions:
                logger.warning("No action generated by prediction. Retrying planning...")
                continue

            action_str = actions[0]
            parse_mode = self._last_parse_mode
            try:
                action = self._action_normalizer.normalize(action_str, parse_mode)
            except Exception as norm_err:
                logger.warning(f"Action normalization failed ({norm_err}). Raw output: {action_str[:200]!r}. Retrying step.")
                if self._last_parse_mode == "showui":
                    # ShowUI sees fresh screenshot each step — record failure in history so it knows not to repeat
                    self._action_history.append(
                        f"Step {step}: PARSE FAILURE — output was not a valid action dict, must retry"
                    )
                else:
                    self._task_messages.append({
                        "role": "user",
                        "content": (
                            f"Your previous output could not be parsed as a valid action: {norm_err}. "
                            f"Output a valid JSON object with an 'action' field. "
                            f"Example: {{\"action\": \"click\", \"element_id\": \"address bar\"}}"
                        )
                    })
                continue
            logger.info(f"Parsed Action: Type={action.type} | Target={action.target_description} | Element={action.element_id}")

            # ── Coordinate Verification & Refinement (Phase P0-b) ─────────────────
            if action.type in ("click", "type", "scroll", "drag_and_drop") and (
                "x_norm" in action.params or "x" in action.params or "x1_norm" in action.params
            ):
                original_coords = {
                    "x_norm": action.params.get("x_norm"),
                    "y_norm": action.params.get("y_norm"),
                    "x1_norm": action.params.get("x1_norm"),
                    "y1_norm": action.params.get("y1_norm"),
                    "x": action.params.get("x"),
                    "y": action.params.get("y"),
                }
                
                action = await self.verifier.verify_coordinate(
                    action=action,
                    screenshot=before_screenshot,
                    task=active_instruction,
                )
                
                new_coords = {
                    "x_norm": action.params.get("x_norm"),
                    "y_norm": action.params.get("y_norm"),
                    "x1_norm": action.params.get("x1_norm"),
                    "y1_norm": action.params.get("y1_norm"),
                }
                
                if (original_coords["x_norm"] != new_coords["x_norm"] or 
                    original_coords["y_norm"] != new_coords["y_norm"] or
                    original_coords["x1_norm"] != new_coords["x1_norm"] or
                    original_coords["y1_norm"] != new_coords["y1_norm"]):
                    self._log_audit("coordinate_refinement", {
                        "action_type": action.type,
                        "original": original_coords,
                        "refined": new_coords
                    })

            # Emit step update to Tauri WebSocket
            await self._emit("step_update", {
                "step": step,
                "plan": step_info.get("reflection", f"Executing step for goal: {active_instruction}"),
                "action": f"{action.type} on {action.target_description or action.element_id or 'screen'}",
                "task_id": task.id
            })

            # 4. Handle early done/fail exits
            if action.type == "done":
                if self.config.brain_actor_mode:
                    logger.info(f"[Brain-Actor] Local actor predicted 'done' for sub-goal: '{self._current_sub_goal}'. Verifying sub-goal...")
                    await self.task_manager.transition(TaskState.VERIFYING)
                    await self._emit("state_change", {"state": TaskState.VERIFYING, "task_id": task.id})

                    after_screenshot = await self.sandbox.take_screenshot()
                    acc_after = None
                    if hasattr(self.sandbox, "get_accessibility_tree"):
                        acc_after = await self.sandbox.get_accessibility_tree()

                    ver_out = await self.verifier.verify(
                        sub_goal=self._current_sub_goal,
                        action_taken=action_str,
                        before_screenshot=before_screenshot,
                        after_screenshot=after_screenshot,
                        accessibility_before=acc_before,
                        accessibility_after=acc_after
                    )

                    if ver_out.result == VerificationResult.SUCCESS:
                        logger.info(f"[Brain-Actor] Sub-goal '{self._current_sub_goal}' verified successfully via actor 'done'.")
                        self.task_manager.reset_failure_count()
                        self._action_history.append(
                            f"Step {step}: completed sub-goal '{self._current_sub_goal}'"
                        )
                        self._current_sub_goal = None
                        self._sub_goal_failure_count = 0
                        await self.task_manager.transition(TaskState.EXECUTING)
                        await self._emit("state_change", {"state": TaskState.EXECUTING, "task_id": task.id})
                        continue
                    else:
                        logger.warning(f"[Brain-Actor] Sub-goal '{self._current_sub_goal}' verification failed on actor 'done'.")
                        action.type = "fail"
                else:
                    logger.info("Done action received. Performing final goal verification...")
                    await self.task_manager.transition(TaskState.VERIFYING)
                    await self._emit("state_change", {"state": TaskState.VERIFYING, "task_id": task.id})

                    after_screenshot = await self.sandbox.take_screenshot()
                    acc_after = None
                    if hasattr(self.sandbox, "get_accessibility_tree"):
                        acc_after = await self.sandbox.get_accessibility_tree()

                    ver_out = await self.verifier.verify(
                        sub_goal=goal,
                        action_taken=action_str,
                        before_screenshot=before_screenshot,
                        after_screenshot=after_screenshot,
                        accessibility_before=acc_before,
                        accessibility_after=acc_after
                    )

                    if ver_out.result == VerificationResult.SUCCESS:
                        self.task_manager.reset_failure_count()
                        self.memory.save_to_knowledge(
                            task_id=task.id,
                            content=f"Done action verified successfully: {ver_out.reason}",
                            metadata={"step": step, "sub_goal": goal, "action_executed": action_str, "verified_success": True}
                        )
                        self.memory.distill_l0_to_l1(task.id)

                        await self.task_manager.transition(TaskState.SUCCEEDED)
                        await self._emit("state_change", {"state": TaskState.SUCCEEDED, "task_id": task.id})
                        await self._emit("task_done", {
                            "success": True,
                            "message": "Task achieved successfully.",
                            "task_id": task.id
                        })
                        self._log_audit("task_end", {"success": True, "message": "Goal verified SUCCESS."})
                        return
                    else:
                        logger.warning("Done action failed verification cascade. Redirecting to failed step handler.")
                        action.type = "fail"

            if action.type == "fail":
                logger.error(f"Fail action received. Goal unachievable. Reason: {action.params.get('reason', 'None')}")
                await self.task_manager.transition(TaskState.FAILED)
                await self._emit("state_change", {"state": TaskState.FAILED, "task_id": task.id})
                await self._emit("task_done", {
                    "success": False,
                    "message": f"Task failed: {action.params.get('reason', 'Goal unachievable')}",
                    "task_id": task.id
                })
                self._log_audit("task_end", {"success": False, "message": "Fail action executed."})
                return

            # 5. Log step action cryptographically
            self._log_audit("execute_action", {
                "step": step,
                "action_type": action.type,
                "target": action.target_description or action.element_id,
                "params": action.params
            })

            # ── Human-in-the-Loop Stateful Approval Gate (Gap K) ──────────────────
            if getattr(action, "is_stateful", False):
                logger.warning(f"[Approval Flow] Stateful action detected: {action.type} on {action.target_description or action.element_id or 'screen'}. Pausing for human approval...")
                
                # 1. Suspend the sandbox execution state
                if hasattr(self.sandbox, "suspend"):
                    await self.sandbox.suspend()
                
                # 2. Transition task to PAUSED_FOR_APPROVAL
                await self.task_manager.transition(TaskState.PAUSED_FOR_APPROVAL)
                await self._emit("state_change", {"state": TaskState.PAUSED_FOR_APPROVAL, "task_id": task.id})
                
                # 3. Wait for websocket client (Tauri) to send approval grant or deny
                approved = await self.ws.wait_for_approval(task.id, self.config.approval_timeout_seconds)
                
                if approved:
                    logger.info("[Approval Flow] User GRANTED approval. Resuming execution...")
                    # Resume sandbox state
                    if hasattr(self.sandbox, "resume"):
                        await self.sandbox.resume()
                    # Transition back to EXECUTING
                    await self.task_manager.transition(TaskState.EXECUTING)
                    await self._emit("state_change", {"state": TaskState.EXECUTING, "task_id": task.id})
                else:
                    logger.error("[Approval Flow] User DENIED approval or request timed out. Terminating task.")
                    # Destroy sandbox VM state
                    if hasattr(self.sandbox, "destroy"):
                        await self.sandbox.destroy()
                    # Transition to FAILED
                    await self.task_manager.transition(TaskState.FAILED)
                    await self._emit("state_change", {"state": TaskState.FAILED, "task_id": task.id})
                    await self._emit("task_done", {
                        "success": False,
                        "message": "Task rejected by user or approval request timed out.",
                        "task_id": task.id
                    })
                    self._log_audit("task_end", {"success": False, "message": "User denied approval (Gap K)."})
                    return

            # 6. Execute action in SandboxACI
            await self.sandbox.execute(action)
            await asyncio.sleep(0.5)

            # 7. Verification Cascade
            await self.task_manager.transition(TaskState.VERIFYING)
            await self._emit("state_change", {"state": TaskState.VERIFYING, "task_id": task.id})

            after_screenshot = await self.sandbox.take_screenshot()
            acc_after = None
            if hasattr(self.sandbox, "get_accessibility_tree"):
                acc_after = await self.sandbox.get_accessibility_tree()

            sub_goal_label = step_info.get("reflection", active_instruction)
            ver_out = await self.verifier.verify(
                sub_goal=sub_goal_label,
                action_taken=action_str,
                before_screenshot=before_screenshot,
                after_screenshot=after_screenshot,
                accessibility_before=acc_before,
                accessibility_after=acc_after
            )

            # Record raw trace to L0 SQLite memory
            self.memory.save_to_knowledge(
                task_id=task.id,
                content=f"Step {step}: {action_str} - verified success: {ver_out.result == VerificationResult.SUCCESS} - outcome: {ver_out.reason}",
                metadata={
                    "step": step,
                    "sub_goal": sub_goal_label,
                    "action_executed": action_str,
                    "verified_success": (ver_out.result == VerificationResult.SUCCESS)
                }
            )

            # Track every step in the context compressor (builds Gap B Mermaid graph)
            from context.compressor import StepNode
            self.compressor.add_step(StepNode(
                step_id=step,
                sub_goal=sub_goal_label,
                action_taken=action_str,
                outcome="success" if ver_out.result == VerificationResult.SUCCESS else "failed",
                failed_reason=ver_out.reason if ver_out.result != VerificationResult.SUCCESS else None,
            ))

            if ver_out.result == VerificationResult.SUCCESS:
                logger.info("Step action verified successfully.")
                self.task_manager.reset_failure_count()
                self.router.reset_sub_goal(active_instruction)
                # ShowUI path: record step in action history (passed to model next iteration)
                self._action_history.append(
                    f"Step {step}: {action.type}({action.target_description or str(action.params)[:60]}) — succeeded"
                )
                
                if self.config.brain_actor_mode:
                    # Successfully completed this sub-goal! Clear it to request the next one from the Brain
                    logger.info(f"[Brain-Actor] Sub-goal '{self._current_sub_goal}' achieved successfully.")
                    self._current_sub_goal = None
                    self._sub_goal_failure_count = 0

                # Fara-7B fallback path: feed screen description as next user message
                if self._last_parse_mode == "fara":
                    after_desc = await self._describe_screen_with_claude(after_screenshot)
                    self._task_messages.append({
                        "role": "user",
                        "content": (
                            f"Step {step}: action '{action.type}' executed and verified successfully.\n"
                            f"Current screen after action:\n{after_desc}\n\n"
                            f"Continue working on goal: {goal}. Output your next action as a JSON object."
                        )
                    })
                await self.task_manager.transition(TaskState.EXECUTING)
                await self._emit("state_change", {"state": TaskState.EXECUTING, "task_id": task.id})
            else:
                logger.warning(f"Step action verification failed: {ver_out.reason}")
                is_threshold_reached = self.task_manager.record_failure()
                self.router.record_sub_goal_failure(active_instruction)
                # Record failed attempt in ShowUI history
                self._action_history.append(
                    f"Step {step}: {action.type}({action.target_description or str(action.params)[:60]}) — FAILED: {ver_out.reason[:60]}"
                )

                if self.config.brain_actor_mode:
                    self._sub_goal_failure_count += 1
                    if self._sub_goal_failure_count >= 2:
                        logger.warning(f"[Brain-Actor] Sub-goal '{self._current_sub_goal}' failed consecutively. Clearing sub-goal to force Brain replan.")
                        self._current_sub_goal = None
                        self._sub_goal_failure_count = 0

                if self.router.should_escalate(active_instruction) or is_threshold_reached:
                    if self.config.air_gap:
                        logger.error("Step failed and cloud escalation blocked due to air_gap. Failing task.")
                        await self.task_manager.transition(TaskState.FAILED)
                        await self._emit("state_change", {"state": TaskState.FAILED, "task_id": task.id})
                        await self._emit("task_done", {
                            "success": False,
                            "message": f"Task failed after multiple verification failures (air-gap prevents cloud escalation): {ver_out.reason}",
                            "task_id": task.id
                        })
                        return
                    else:
                        # Cloud escalation triggered — cloud tier uses its own message history
                        logger.warning("Consecutive failures threshold reached. Triggering cloud model escalation!")
                        mermaid_graph = self.compressor.to_mermaid()
                        await self._handle_escalation(mermaid_graph)
                else:
                    # Fara-7B fallback path: inject screen description as replanning prompt
                    if self._last_parse_mode == "fara":
                        after_desc = await self._describe_screen_with_claude(after_screenshot)
                        self._task_messages.append({
                            "role": "user",
                            "content": (
                                f"Step {step}: action '{action.type}' failed verification: {ver_out.reason}.\n"
                                f"Current screen:\n{after_desc}\n\n"
                                f"Try a different approach to achieve goal: {goal}. Output your next action."
                            )
                        })
                    logger.info("Entering replanning state...")
                    await self.task_manager.transition(TaskState.REPLANNING)
                    await self._emit("state_change", {"state": TaskState.REPLANNING, "task_id": task.id})
                    await asyncio.sleep(0.2)
                    await self.task_manager.transition(TaskState.EXECUTING)
                    await self._emit("state_change", {"state": TaskState.EXECUTING, "task_id": task.id})

        # Max steps exceeded
        logger.error("Max execution steps reached without success.")
        await self.task_manager.transition(TaskState.FAILED)
        await self._emit("state_change", {"state": TaskState.FAILED, "task_id": task.id})
        await self._emit("task_done", {
            "success": False,
            "message": "Max execution steps budget reached.",
            "task_id": task.id
        })

    async def _execute_step(self, instruction: str, obs: dict) -> tuple[dict, list[str]]:
        """
        Single agent step.
        Returns: (step_info dict, list of executable action strings).
        """
        task = self.task_manager.task
        if task is None:
            return {}, []

        task_type = "desktop"
        if "web" in instruction.lower() or "browser" in instruction.lower() or "http" in instruction.lower():
            task_type = "web"

        is_escalated = task.is_escalated or self.router.current_tier == ModelTier.CLOUD

        # Build system prompt with task description injected + memory context
        from sandbox.sandbox_aci import SandboxACI
        system_prompt = self.router.get_system_prompt(task_type, SandboxACI).replace(
            "TASK_DESCRIPTION", instruction
        )
        facts = self.memory.get_context_for_task(instruction, task.session_id)
        if facts and "No relevant memories" not in facts:
            system_prompt += f"\n\nHistorical Facts / Working Memory:\n{facts}"
        # Gap B: inject Mermaid context graph on first call after escalation
        if self._escalation_context:
            system_prompt += f"\n\nContext from previous attempts (Mermaid task graph):\n{self._escalation_context}"
            self._escalation_context = ""  # consumed — inject only once

        screenshot = obs.get("screenshot", b"")

        try:
            if is_escalated or self.router.current_tier == ModelTier.CLOUD:
                # Cloud tier — use LMMAgent with Anthropic API
                self._last_parse_mode = "claude_gpt"
                agent = self.router.get_agent(task_type, is_escalated=True)
                agent.add_system_prompt(system_prompt)
                agent.add_message(
                    text_content=f"Task: {instruction}\n\nAnalyze the current screen and output your next action.",
                    image_content=screenshot if screenshot else None,
                    role="user",
                )
                loop = asyncio.get_running_loop()
                response_text = await loop.run_in_executor(
                    None,
                    lambda: agent.get_response(temperature=0.0, max_new_tokens=1024)
                )
            else:
                # Local tier — ShowUI-2B (primary VLA) → Fara-7B+Haiku (fallback).
                # Lazy-load ShowUI on first call; falls back gracefully if unavailable.
                if self._showui is None and not self._showui_load_attempted:
                    try:
                        from llm.showui_agent import ShowUIAgent
                        self._showui = ShowUIAgent(self.config.showui_model_path)
                        self._showui_load_attempted = True
                        logger.info("[ShowUI] Agent instantiated — will load weights on first inference call.")
                    except Exception as showui_import_err:
                        logger.warning(f"[ShowUI] Could not import ShowUIAgent: {showui_import_err}. Falling back to Fara-7B.")
                        self._showui_load_attempted = True

                if self._showui is not None:
                    # Primary path: ShowUI sees the screenshot directly
                    self._last_parse_mode = "showui"
                    response_text = await self._showui.get_action(
                        screenshot=screenshot,
                        task=instruction,
                        task_type=task_type,
                        history=list(self._action_history),
                    )
                else:
                    # Fallback: Fara-7B (text-only) + Claude Haiku (vision bridge)
                    self._last_parse_mode = "fara"
                    if not self._task_messages:
                        screen_desc = await self._describe_screen_with_claude(screenshot)
                        self._task_messages.append({
                            "role": "user",
                            "content": (
                                f"Task: {instruction}\n\n"
                                f"Current screen:\n{screen_desc}\n\n"
                                "Analyze the screen and output your next action as a JSON object."
                            )
                        })
                    response_text = await self._call_local_llm(system_prompt, self._task_messages)
                    self._task_messages.append({"role": "assistant", "content": response_text})

            if not response_text:
                raise ValueError("Empty response from LLM")

            logger.info(f"LLM response (first 300 chars): {response_text[:300]}")
            info = {"reflection": response_text[:300]}
            return info, [response_text]

        except Exception as e:
            logger.warning(f"LLM inference failed: {e}. Using safe fallback.")
            err_msg = str(e)[:120].replace('"', "'")
            return (
                {"reflection": f"Inference failed: {e}"},
                [f'{{"action": "fail", "reason": "LLM unavailable: {err_msg}"}}'],
            )

    async def _describe_screen_with_claude(self, screenshot: bytes) -> str:
        """Use Claude Haiku vision to describe what is currently on screen.

        This is the 'eyes' for Fara-7B which runs as a text-only GGUF.
        Claude only reads the screen — Fara-7B still decides the action.
        Cost: ~$0.0001 per call (Haiku pricing, ~100 token description).
        """
        if not screenshot or not self.config.claude_api_key:
            return "Screen state unknown — no screenshot available."
        try:
            import anthropic
            import base64

            client = anthropic.Anthropic(api_key=self.config.claude_api_key)
            b64 = base64.standard_b64encode(screenshot).decode("utf-8")
            response = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=300,
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {"type": "base64", "media_type": "image/png", "data": b64},
                        },
                        {
                            "type": "text",
                            "text": (
                                "Describe this computer screen in 3-5 sentences for a computer-use agent. "
                                "Include: which application is in focus, key UI elements and their approximate "
                                "screen positions (top-left, top-center, etc.), any text visible in the address "
                                "bar, title bar, or active input field. Be specific. Do not suggest actions."
                            ),
                        },
                    ],
                }],
            )
            description = response.content[0].text
            logger.info(f"[VLM] Screen description: {description[:150]}")
            return description
        except Exception as e:
            logger.warning(f"Claude screen description failed: {e}")
            return f"Screen state unknown (vision call failed: {e})"

    async def _call_local_llm_raw(self, system_prompt: str, messages: list[dict], max_tokens: int = 512) -> str:
        """Direct HTTP call to LM Studio (OpenAI-compatible endpoint)."""
        import json
        import urllib.request
        import http.client

        payload = {
            "model": self.config.fara_model_id,
            "messages": [{"role": "system", "content": system_prompt}] + messages,
            "temperature": 0.0,
            "max_tokens": max_tokens,
        }
        data_bytes = json.dumps(payload).encode("utf-8")
        url = f"{self.config.local_vllm_url.rstrip('/')}/chat/completions"

        def _do_request() -> str:
            import urllib.error
            for attempt in range(2):   # one retry on RemoteDisconnected
                req = urllib.request.Request(
                    url,
                    data=data_bytes,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                try:
                    with urllib.request.urlopen(req, timeout=20.0) as res:
                        return res.read().decode("utf-8")
                except urllib.error.HTTPError as http_err:
                    body = http_err.read().decode("utf-8", errors="replace")
                    raise RuntimeError(f"HTTP {http_err.code} from LM Studio: {body[:400]}")
                except (http.client.RemoteDisconnected, ConnectionResetError) as conn_err:
                    if attempt == 0:
                        logger.warning(f"LM Studio dropped connection (attempt {attempt+1}), retrying in 3s: {conn_err}")
                        import time; time.sleep(3)
                        continue
                    raise RuntimeError(f"LM Studio dropped connection after retry: {conn_err}")
            raise RuntimeError("LM Studio request failed after all attempts")

        loop = asyncio.get_event_loop()
        res_str = await loop.run_in_executor(None, _do_request)
        data = json.loads(res_str)
        return data["choices"][0]["message"]["content"]

    async def _call_local_llm(self, system_prompt: str, messages: list[dict]) -> str:
        """Direct HTTP call to LM Studio (OpenAI-compatible endpoint) with progressive token budget compression.

        Sends text-only: Fara-7B GGUF has no mmproj vision encoder.
        Accepts the full per-task conversation history so the model sees
        what it already tried and can plan a genuinely different next step.
        Compresses intermediate conversation when token usage approaches 70% threshold.
        """
        # 1. Estimate token counts (characters / 4)
        def estimate_tokens(msgs: list[dict], sys_prompt: str) -> int:
            return (sum(len(m["content"]) for m in msgs) + len(sys_prompt)) // 4

        estimated = estimate_tokens(messages, system_prompt)
        budget = min(self.config.local_task_token_budget, 4096)
        
        # If estimated tokens exceed 70% of the budget and we have enough messages to compress
        if estimated > int(budget * 0.70) and len(messages) > 6:
            logger.info(f"[History Compression] Context size {estimated} exceeds 70% of budget {budget}. Summarizing history...")
            
            # Keep first task prompt (messages[0]) and last 4 messages
            first_msg = messages[0]
            recent_msgs = messages[-4:]
            middle_msgs = messages[1:-4]
            
            # Formulate a prompt to summarize the middle messages
            summary_payload = ""
            for m in middle_msgs:
                role = "Agent" if m["role"] == "assistant" else "User/Screen"
                summary_payload += f"{role}: {m['content']}\n\n"
                
            summarize_prompt = (
                "You are an assistant. Summarize the following sequential steps taken by a computer automation agent "
                "in 3 sentences or less, listing what was attempted, what succeeded, and what failed:\n\n"
                f"{summary_payload}"
            )
            
            try:
                # Call local LLM to get the summary
                summary = await self._call_local_llm_raw(
                    system_prompt="You are a precise summarization assistant.",
                    messages=[{"role": "user", "content": summarize_prompt}],
                    max_tokens=150
                )
                logger.info(f"[History Compression] Compression summary: {summary}")
                
                # Reconstruct messages list
                compressed_messages = [
                    first_msg,
                    {"role": "user", "content": f"Recap of previous attempts:\n{summary}"}
                ] + recent_msgs
                
                # Update the orchestrator's task message history in place
                messages[:] = compressed_messages
            except Exception as comp_err:
                logger.warning(f"[History Compression] History summarization failed: {comp_err}. Falling back to standard slicing.")
                # Fallback to slicing
                first_msg = messages[0]
                recent_msgs = messages[-4:]
                messages[:] = [first_msg] + recent_msgs
        elif len(messages) > 10:
            # Fallback to keep last 10 messages if token count isn't over limit but array is long
            messages[:] = [messages[0]] + messages[-9:]

        return await self._call_local_llm_raw(system_prompt, messages, max_tokens=512)

    async def _handle_escalation(self, context_graph: str) -> None:
        """
        Escalate to cloud: swap model tier, store Mermaid graph for Gap B injection,
        reset failure counters, and return with task in EXECUTING state so the
        worker loop can continue seamlessly with the cloud model.
        """
        task = self.task_manager.task
        if task is None:
            return

        logger.info("Executing cloud model escalation process...")
        await self.task_manager.transition(TaskState.ESCALATED)
        await self._emit("state_change", {"state": TaskState.ESCALATED, "task_id": task.id})

        task.is_escalated = True
        self.router.force_cloud()
        self.router.reset_all_failures()   # prevent immediate re-escalation on next step

        # Gap B: store graph — injected as first message in next _execute_step() call
        self._escalation_context = context_graph
        self._log_audit("escalation_to_cloud", {"mermaid_flowchart": context_graph})
        self.task_manager.reset_failure_count()

        await asyncio.sleep(0.3)
        # ESCALATED → PLANNING (announce fresh cloud Worker)
        await self.task_manager.transition(TaskState.PLANNING)
        await self._emit("state_change", {"state": TaskState.PLANNING, "task_id": task.id})
        # PLANNING → EXECUTING so the worker loop iteration can proceed normally
        await self.task_manager.transition(TaskState.EXECUTING)
        await self._emit("state_change", {"state": TaskState.EXECUTING, "task_id": task.id})

    async def _emit(self, event_type: str, data: dict) -> None:
        """Send a JSON event to the connected Tauri WebSocket client."""
        if self.ws is None:
            return
        payload = {"type": event_type}
        payload.update(data)
        await self.ws.send(payload)

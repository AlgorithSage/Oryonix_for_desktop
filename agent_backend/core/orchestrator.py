"""
Orchestrator — main agent loop.
Replaces Agent-S3's cli_app.py run_agent() loop entirely.
Coordinates the PlannerAgent, ExecutorAgent, VerifierAgent, and DebuggerAgent.
"""
from __future__ import annotations

import logging
import asyncio
from typing import TYPE_CHECKING, Any, Optional

from core.task_manager import TaskState
from verifier.verifier import VerificationResult
from core.agents import PlannerAgent, ExecutorAgent, VerifierAgent, DebuggerAgent

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

# Configure logger
logger = logging.getLogger("desktopenv.agent")


class Orchestrator:
    """Drives the full per-task agent loop end-to-end coordinating modular agents."""

    MAX_STEPS = 50

    def __init__(
        self,
        config: "Config",
        task_manager: "TaskManager",
        router: "LLMRouter",
        sandbox: "SandboxACI",
        verifier: Any, # Verifier
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
        self.compressor = compressor
        self.memory = memory
        self.recipe_engine = recipe_engine
        self.audit = audit
        self.ws = ws_server
        
        from core.intent_executor import IntentExecutor
        self._intent_executor = IntentExecutor()
        
        self._paused_event = asyncio.Event()
        self._paused_event.set()
        self._active_task = None

        # Instantiate the 4 modular base agents
        self.verifier_agent = VerifierAgent(config)
        self.planner_agent = PlannerAgent(config, router)
        self.executor_agent = ExecutorAgent(config, router, memory, compressor, self.verifier_agent)
        self.debugger_agent = DebuggerAgent(config, router, task_manager, compressor)

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

            # ── Tier 0: instant OS dispatch — no LLM, no screenshot ──────────
            tier0 = self._intent_executor.execute(goal)
            if tier0 is not None:
                logger.info(f"[Tier0] {'OK' if tier0.success else 'FAIL'}: {tier0.message}")
                self._log_audit("task_start", {"goal": goal, "session_id": session_id})
                # PLANNING → EXECUTING → VERIFYING → SUCCEEDED/FAILED
                await self.task_manager.transition(TaskState.EXECUTING)
                await self._emit("state_change", {"state": TaskState.EXECUTING, "task_id": task.id})
                await self.task_manager.transition(TaskState.VERIFYING)
                await self._emit("state_change", {"state": TaskState.VERIFYING, "task_id": task.id})
                final_state = TaskState.SUCCEEDED if tier0.success else TaskState.FAILED
                await self.task_manager.transition(final_state)
                await self._emit("state_change", {"state": final_state, "task_id": task.id})
                await self._emit("task_done", {
                    "success": tier0.success,
                    "message": tier0.message,
                    "task_id": task.id,
                })
                self._log_audit("task_end", {"success": tier0.success,
                                             "message": f"[Tier0] {tier0.message}"})
                return
            # ─────────────────────────────────────────────────────────────────

            # Reset per-task state of agents
            self.compressor.reset()
            self.planner_agent.reset()
            self.executor_agent.reset()
            if hasattr(self.sandbox, "reset_session"):
                await self.sandbox.reset_session()
            await self.sandbox.init_dimensions()

            # Save genesis audit event
            self._log_audit("task_start", {"goal": goal, "session_id": session_id})

            # Minimize all windows so screenshots show the real desktop, not the Oryonix UI
            try:
                import pyautogui as _pag
                _pag.hotkey('win', 'd')
                await asyncio.sleep(0.8)
                logger.info("[Orchestrator] Minimized all windows (Win+D) before first screenshot.")
            except Exception:
                pass

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
            current_state = self.task_manager.get_state()
            if current_state != TaskState.EXECUTING:
                await self.task_manager.transition(TaskState.EXECUTING)
                await self._emit("state_change", {"state": TaskState.EXECUTING, "task_id": task.id})

            await self._worker_loop(goal)

        except asyncio.CancelledError:
            logger.warning("[Execution Controls] Task was cancelled via active user request.")
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
                    "message": "Task killed by user.",
                    "task_id": self.task_manager.task.id
                })
                self._log_audit("task_cancelled", {"message": "Killed by user"})
            raise
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
        match_res = self.recipe_engine.match(screenshot, goal=task.goal)
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
        ver_out = await self.verifier_agent.verify(
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

    async def _worker_loop(self, goal: str) -> None:
        """
        Core step loop: coordinates PlannerAgent, ExecutorAgent, VerifierAgent, and DebuggerAgent.
        """
        task = self.task_manager.task
        if task is None:
            return

        print(f"[Orchestrator] Starting worker loop for task: active_task={self._active_task}, paused={not self._paused_event.is_set()}", flush=True)

        step = 0
        while step < self.MAX_STEPS:
            # Wait if paused by user (Execution Controls)
            if not self._paused_event.is_set():
                logger.info("Orchestrator worker loop paused. Entering PAUSED_FOR_HUMAN_TAKEOVER...")
                old_state = self.task_manager.get_state()
                if old_state == TaskState.EXECUTING:
                    await self.task_manager.transition(TaskState.PAUSED_FOR_HUMAN_TAKEOVER)
                    await self._emit("state_change", {
                        "state": TaskState.PAUSED_FOR_HUMAN_TAKEOVER,
                        "task_id": task.id
                    })
                
                await self._paused_event.wait()
                logger.info("Orchestrator worker loop resumed.")
                
                if self.task_manager.get_state() == TaskState.PAUSED_FOR_HUMAN_TAKEOVER:
                    await self.task_manager.transition(TaskState.EXECUTING)
                    await self._emit("state_change", {
                        "state": TaskState.EXECUTING,
                        "task_id": task.id
                    })

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

            # 3. Planner Agent - Determine sub-goal
            if self.config.brain_actor_mode:
                if not self.planner_agent.current_sub_goal:
                    logger.info(f"[Orchestrator] Current sub-goal is empty. Fetching next sub-goal from Planner...")
                    self.planner_agent.current_sub_goal = await self.planner_agent.plan(goal, before_screenshot)
                    self.planner_agent.sub_goal_failure_count = 0
                    logger.info(f"[Orchestrator] Active sub-goal set to: '{self.planner_agent.current_sub_goal}'")
                
                # Check for overall completion
                if self.planner_agent.current_sub_goal == "DONE":
                    logger.info("[Orchestrator] Planner returned DONE. Performing final goal verification...")
                    await self.task_manager.transition(TaskState.VERIFYING)
                    await self._emit("state_change", {"state": TaskState.VERIFYING, "task_id": task.id})

                    after_screenshot = await self.sandbox.take_screenshot()
                    acc_after = None
                    if hasattr(self.sandbox, "get_accessibility_tree"):
                        acc_after = await self.sandbox.get_accessibility_tree()

                    ver_out = await self.verifier_agent.verify(
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
                            content=f"Planner completed task successfully: {ver_out.reason}",
                            metadata={"step": step, "sub_goal": goal, "action_executed": "brain_done", "verified_success": True}
                        )
                        self.memory.distill_l0_to_l1(task.id)

                        await self.task_manager.transition(TaskState.SUCCEEDED)
                        await self._emit("state_change", {"state": TaskState.SUCCEEDED, "task_id": task.id})
                        await self._emit("task_done", {
                            "success": True,
                            "message": "Task achieved successfully.",
                            "task_id": task.id
                        })
                        self._log_audit("task_end", {"success": True, "message": "Planner verification SUCCESS."})
                        return
                    else:
                        logger.warning("Planner verification cascade failed. Forcing replan...")
                        self.planner_agent.clear_sub_goal()
                        continue

                active_instruction = self.planner_agent.current_sub_goal
            else:
                active_instruction = goal

            # 4. Executor Agent - Predict action, normalize, refine coordinates
            try:
                step_info, action_str, action = await self.executor_agent.execute(
                    sub_goal=active_instruction,
                    screenshot=before_screenshot,
                    acc_before=acc_before,
                    step=step,
                    task=task,
                    action_history=self.planner_agent.action_history
                )
            except Exception as norm_err:
                logger.warning(f"Action prediction or normalization failed: {norm_err}. Retrying step.")
                if self.executor_agent.last_parse_mode in ("showui", "groq"):
                    self.planner_agent.action_history.append(
                        f"Step {step}: PARSE FAILURE — output was not a valid action dict, must retry"
                    )
                else:
                    self.executor_agent.task_messages.append({
                        "role": "user",
                        "content": (
                            f"Your previous output could not be parsed as a valid action: {norm_err}. "
                            f"Output a valid JSON object with an 'action' field. "
                            f"Example: {{\"action\": \"click\", \"element_id\": \"address bar\"}}"
                        )
                    })
                continue

            # Emit step update to Tauri WebSocket
            await self._emit("step_update", {
                "step": step,
                "plan": step_info.get("reflection", f"Executing step for goal: {active_instruction}"),
                "action": f"{action.type} on {action.target_description or action.element_id or 'screen'}",
                "task_id": task.id
            })

            # 5. Handle early done/fail exits from Executor
            if action.type == "done":
                if self.config.brain_actor_mode:
                    logger.info(f"[Orchestrator] Actor predicted 'done' for sub-goal: '{active_instruction}'. Verifying...")
                    await self.task_manager.transition(TaskState.VERIFYING)
                    await self._emit("state_change", {"state": TaskState.VERIFYING, "task_id": task.id})

                    after_screenshot = await self.sandbox.take_screenshot()
                    acc_after = None
                    if hasattr(self.sandbox, "get_accessibility_tree"):
                        acc_after = await self.sandbox.get_accessibility_tree()

                    ver_out = await self.verifier_agent.verify(
                        sub_goal=active_instruction,
                        action_taken=action_str,
                        before_screenshot=before_screenshot,
                        after_screenshot=after_screenshot,
                        accessibility_before=acc_before,
                        accessibility_after=acc_after
                    )

                    if ver_out.result == VerificationResult.SUCCESS:
                        logger.info(f"[Orchestrator] Sub-goal '{active_instruction}' verified successfully.")
                        self.task_manager.reset_failure_count()
                        self.planner_agent.action_history.append(
                            f"Step {step}: completed sub-goal '{active_instruction}'"
                        )
                        self.planner_agent.clear_sub_goal()
                        await self.task_manager.transition(TaskState.EXECUTING)
                        await self._emit("state_change", {"state": TaskState.EXECUTING, "task_id": task.id})
                        continue
                    else:
                        logger.warning(f"[Orchestrator] Sub-goal '{active_instruction}' verification failed on actor 'done'.")
                        action.type = "fail"
                else:
                    logger.info("Done action received. Performing final goal verification...")
                    await self.task_manager.transition(TaskState.VERIFYING)
                    await self._emit("state_change", {"state": TaskState.VERIFYING, "task_id": task.id})

                    after_screenshot = await self.sandbox.take_screenshot()
                    acc_after = None
                    if hasattr(self.sandbox, "get_accessibility_tree"):
                        acc_after = await self.sandbox.get_accessibility_tree()

                    ver_out = await self.verifier_agent.verify(
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

            # 6. Log step action cryptographically
            self._log_audit("execute_action", {
                "step": step,
                "action_type": action.type,
                "target": action.target_description or action.element_id,
                "params": action.params
            })

            # Stateful Action Approval Gate
            if getattr(action, "is_stateful", False):
                logger.warning(f"[Approval Flow] Stateful action detected: {action.type}. Pausing for human approval...")
                if hasattr(self.sandbox, "suspend"):
                    await self.sandbox.suspend()
                
                await self.task_manager.transition(TaskState.PAUSED_FOR_APPROVAL)
                await self._emit("state_change", {"state": TaskState.PAUSED_FOR_APPROVAL, "task_id": task.id})
                
                approved = await self.ws.wait_for_approval(task.id, self.config.approval_timeout_seconds)
                
                if approved:
                    logger.info("[Approval Flow] User GRANTED approval. Resuming...")
                    if hasattr(self.sandbox, "resume"):
                        await self.sandbox.resume()
                    await self.task_manager.transition(TaskState.EXECUTING)
                    await self._emit("state_change", {"state": TaskState.EXECUTING, "task_id": task.id})
                else:
                    logger.error("[Approval Flow] User DENIED approval or request timed out. Terminating task.")
                    if hasattr(self.sandbox, "destroy"):
                        await self.sandbox.destroy()
                    await self.task_manager.transition(TaskState.FAILED)
                    await self._emit("state_change", {"state": TaskState.FAILED, "task_id": task.id})
                    await self._emit("task_done", {
                        "success": False,
                        "message": "Task rejected by user or approval request timed out.",
                        "task_id": task.id
                    })
                    self._log_audit("task_end", {"success": False, "message": "User denied approval."})
                    return

            # 7. Executor Agent - Execute action in Sandbox
            await self.executor_agent.run_in_sandbox(action, self.sandbox)
            await asyncio.sleep(0.5)

            # 8. Verifier Agent - Run Verification Cascade
            await self.task_manager.transition(TaskState.VERIFYING)
            await self._emit("state_change", {"state": TaskState.VERIFYING, "task_id": task.id})

            after_screenshot = await self.sandbox.take_screenshot()
            acc_after = None
            if hasattr(self.sandbox, "get_accessibility_tree"):
                acc_after = await self.sandbox.get_accessibility_tree()

            sub_goal_label = step_info.get("reflection", active_instruction)
            ver_out = await self.verifier_agent.verify(
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

            # Track in compressor
            from context.compressor import StepNode
            self.compressor.add_step(StepNode(
                step_id=step,
                sub_goal=sub_goal_label,
                action_taken=action_str,
                outcome="success" if ver_out.result == VerificationResult.SUCCESS else "failed",
                failed_reason=ver_out.reason if ver_out.result != VerificationResult.SUCCESS else None,
            ))

            if ver_out.result == VerificationResult.SUCCESS:
                # 9. Handle Success
                logger.info("Step action verified successfully.")
                self.task_manager.reset_failure_count()
                self.router.reset_sub_goal(active_instruction)
                
                # Append success to Planner Agent history
                self.planner_agent.action_history.append(
                    f"Step {step}: {action.type}({action.target_description or str(action.params)[:60]}) — succeeded"
                )
                
                if self.config.brain_actor_mode:
                    logger.info(f"[Orchestrator] Sub-goal '{active_instruction}' achieved successfully.")
                    self.planner_agent.clear_sub_goal()

                if self.executor_agent.last_parse_mode == "fara":
                    after_desc = await self.executor_agent._describe_screen_with_claude(after_screenshot)
                    self.executor_agent.task_messages.append({
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
                # 10. Debugger Agent - Handle failure diagnosis and recovery
                recovery = await self.debugger_agent.debug(
                    sub_goal=active_instruction,
                    action=action,
                    action_str=action_str,
                    verdict=ver_out,
                    step=step,
                    planner_agent=self.planner_agent,
                    executor_agent=self.executor_agent,
                    before_screenshot=before_screenshot,
                    after_screenshot=after_screenshot
                )

                if recovery == "FAIL":
                    await self.task_manager.transition(TaskState.FAILED)
                    await self._emit("state_change", {"state": TaskState.FAILED, "task_id": task.id})
                    await self._emit("task_done", {
                        "success": False,
                        "message": f"Task failed after verification failures: {ver_out.reason}",
                        "task_id": task.id
                    })
                    return
                elif recovery == "ESCALATE":
                    mermaid_graph = self.compressor.to_mermaid()
                    await self._handle_escalation(mermaid_graph)
                elif recovery == "REPLAN" or recovery == "RETRY":
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
        self.executor_agent.escalation_context = context_graph
        self._log_audit("escalation_to_cloud", {"mermaid_flowchart": context_graph})
        self.task_manager.reset_failure_count()

        await asyncio.sleep(0.3)
        # ESCALATED → PLANNING (announce fresh cloud Worker)
        await self.task_manager.transition(TaskState.PLANNING)
        await self._emit("state_change", {"state": TaskState.PLANNING, "task_id": task.id})
        # PLANNING → EXECUTING so the worker loop iteration can proceed normally
        await self.task_manager.transition(TaskState.EXECUTING)
        await self._emit("state_change", {"state": TaskState.EXECUTING, "task_id": task.id})

    def set_active_task(self, task: asyncio.Task) -> None:
        print(f"[Orchestrator] set_active_task called: task={task}", flush=True)
        self._active_task = task
        self._paused_event.set()  # Ensure new tasks start unpaused

    def pause_task(self) -> None:
        print("[Orchestrator] pause_task called. Clearing _paused_event.", flush=True)
        logger.info("[Execution Controls] Pausing active task execution...")
        self._paused_event.clear()

    def resume_task(self) -> None:
        print("[Orchestrator] resume_task called. Setting _paused_event.", flush=True)
        logger.info("[Execution Controls] Resuming active task execution...")
        self._paused_event.set()

    async def kill_task(self) -> None:
        print(f"[Orchestrator] kill_task called. active_task={self._active_task}", flush=True)
        logger.info("[Execution Controls] Kill task request received.")
        if self._active_task and not self._active_task.done():
            self._active_task.cancel()
            print("[Orchestrator] Active task cancellation requested (cancel() invoked).", flush=True)
            logger.info("[Execution Controls] Active task cancellation requested.")
        else:
            print(f"[Orchestrator] Active task cannot be cancelled: active_task={self._active_task}", flush=True)

    async def _emit(self, event_type: str, data: dict) -> None:
        """Send a JSON event to the connected Tauri WebSocket client."""
        if self.ws is None:
            return
        payload = {"type": event_type}
        payload.update(data)
        await self.ws.send(payload)

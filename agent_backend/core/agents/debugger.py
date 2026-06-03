import logging
import asyncio
from llm.action_normalizer import Action

logger = logging.getLogger("desktopenv.agent")

class DebuggerAgent:
    """Diagnoses execution and verification failures, manages failure counts and thresholds,

    and determines the appropriate recovery path (re-execution, replanning, escalation, or task failure).
    """

    def __init__(self, config, router, task_manager, compressor) -> None:
        self.config = config
        self.router = router
        self.task_manager = task_manager
        self.compressor = compressor

    async def debug(
        self,
        sub_goal: str,
        action: Action,
        action_str: str,
        verdict,  # VerifierOutput
        step: int,
        planner_agent,  # PlannerAgent
        executor_agent,  # ExecutorAgent
        before_screenshot: bytes,
        after_screenshot: bytes,
    ) -> str:
        """
        Diagnose the failure, update history/messages, and return the recovery action.
        Returns: "RETRY" (re-execute/continue), "REPLAN" (force planning), "ESCALATE" (cloud model), or "FAIL" (task abort)
        """
        logger.warning(f"[DebuggerAgent] Step action verification failed: {verdict.reason}")

        # 1. Record failure in task manager and router
        is_threshold_reached = self.task_manager.record_failure()
        self.router.record_sub_goal_failure(sub_goal)

        # 2. Record failed attempt in history
        planner_agent.action_history.append(
            f"Step {step}: {action.type}({action.target_description or str(action.params)[:60]}) — FAILED: {verdict.reason[:60]}"
        )

        # 3. Check for consecutive failures of the active sub-goal (only in brain_actor_mode)
        if self.config.brain_actor_mode:
            planner_agent.sub_goal_failure_count += 1
            if planner_agent.sub_goal_failure_count >= 2:
                logger.warning(
                    f"[DebuggerAgent] Sub-goal '{sub_goal}' failed consecutively. Clearing sub-goal to force replan."
                )
                planner_agent.clear_sub_goal()

        # 4. Check for cloud model escalation trigger
        if self.router.should_escalate(sub_goal) or is_threshold_reached:
            if self.config.air_gap:
                logger.error("[DebuggerAgent] Cloud escalation blocked due to air_gap. Failing task.")
                return "FAIL"
            else:
                logger.warning("[DebuggerAgent] Consecutives/total failure threshold reached. Escalating to cloud model.")
                return "ESCALATE"

        # 5. Fara text-only fallback path: inject screen description and prompt for different approach
        if executor_agent.last_parse_mode == "fara":
            try:
                after_desc = await executor_agent._describe_screen_with_claude(after_screenshot)
                executor_agent.task_messages.append({
                    "role": "user",
                    "content": (
                        f"Step {step}: action '{action.type}' failed verification: {verdict.reason}.\n"
                        f"Current screen:\n{after_desc}\n\n"
                        f"Try a different approach to achieve goal: {sub_goal}. Output your next action."
                    )
                })
            except Exception as e:
                logger.warning(f"[DebuggerAgent] Screen description failed: {e}")

        # If sub-goal was cleared due to consecutive failures, force replan
        if self.config.brain_actor_mode and planner_agent.current_sub_goal is None:
            return "REPLAN"

        # Default recovery path is to keep going (re-execute or retry)
        return "RETRY"

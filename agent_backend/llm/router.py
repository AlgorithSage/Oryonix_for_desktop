"""
LLM Router — selects the model + system prompt for every agent step.

Routing rules (Gap 5 / Gap A):
  1. All tasks start on local model.
     - task_type "web"     → Fara-7B     + FARA_PROCEDURAL_MEMORY
     - task_type "desktop" → OpenCUA-7B  + OPENCUA_PROCEDURAL_MEMORY
  2. Verifier FAILURE × ESCALATION_THRESHOLD on same sub-goal → escalate to cloud.
  3. Local model cannot decompose multi-step plan → escalate to cloud.
  4. User forces cloud via UI toggle → force_cloud() called.
  Cloud: Claude/GPT-5 + construct_simple_worker_procedural_memory()

air_gap=True: cloud escalation never happens — task FAILs instead.
"""
from __future__ import annotations

import logging
from enum import Enum
from typing import TYPE_CHECKING, Any

# Configure logger
logger = logging.getLogger("desktopenv.agent")

if TYPE_CHECKING:
    from core.config import Config

class ModelTier(str, Enum):
    LOCAL_WEB = "local_web"          # Fara-7B
    LOCAL_DESKTOP = "local_desktop"  # OpenCUA-7B
    CLOUD = "cloud"                  # Claude / GPT-5


# ── Fara-7B and OpenCUA-7B Specific Prompts ───────────────────────────────

FARA_PROCEDURAL_MEMORY = """You are Fara-7B, an expert web computer use agent. Your task is to plan and execute actions on a web interface to accomplish the user goal: TASK_DESCRIPTION.

You must output your reasoning and next action in a single JSON object.

Output format:
{
  "thoughts": "Your detailed reasoning here",
  "action": "click" | "type" | "scroll" | "hotkey" | "wait" | "done" | "fail",
  "element_id": "The target element id or short description",
  "text": "The text to type (if action is type)",
  "key": "The hotkey combination (if action is hotkey)",
  "direction": "up" | "down" (if action is scroll),
  "amount": 3 (if action is scroll)
}

Guidelines:
- Choose the correct action to proceed.
- Respond with action "done" when the goal is achieved, or "fail" if impossible.
"""

OPENCUA_PROCEDURAL_MEMORY = """You are OpenCUA-7B, an expert desktop computer use agent. Your task is to plan and execute actions on a desktop operating system to accomplish the user goal: TASK_DESCRIPTION.

You must output your reasoning and next action in a single JSON object.

Output format:
{
  "thoughts": "Your detailed reasoning here",
  "action": "click" | "type" | "scroll" | "hotkey" | "wait" | "done" | "fail",
  "element_id": "The target element id or short description",
  "text": "The text to type (if action is type)",
  "key": "The hotkey combination (if action is hotkey)",
  "direction": "up" | "down" (if action is scroll),
  "amount": 3 (if action is scroll)
}

Guidelines:
- Choose the correct action to proceed.
- To launch or search for local apps/tools, use the "hotkey" action with key "win" to open the Start menu, then "type" the name of the app, and send "hotkey" key "enter".
- Respond with action "done" when the goal is achieved, or "fail" if impossible.
"""


class LLMRouter:
    """Routes each agent step to the appropriate model + system prompt."""

    def __init__(self, config: "Config") -> None:
        self.config = config
        self._current_tier: ModelTier = ModelTier.LOCAL_WEB
        self._sub_goal_failures: dict[str, int] = {}

    def get_agent(self, task_type: str, is_escalated: bool = False) -> Any:
        """
        Return a configured LMMAgent (Agent-S3 core/mllm.py) for the given
        task_type ("web" | "desktop") and escalation state.
        Implements Gap A: swaps both model AND system prompt together.
        """
        from gui_agents.s3.core.mllm import LMMAgent
        from sandbox.sandbox_aci import SandboxACI

        # Determine Model Tier & Configuration
        if is_escalated or self._current_tier == ModelTier.CLOUD:
            if self.config.air_gap:
                logger.warning("Cloud escalation blocked: air_gap=True. Retaining local model.")
                # Retain local path instead of crashing
                if task_type == "web":
                    self._current_tier = ModelTier.LOCAL_WEB
                else:
                    self._current_tier = ModelTier.LOCAL_DESKTOP
            else:
                self._current_tier = ModelTier.CLOUD

        if self._current_tier == ModelTier.CLOUD:
            logger.info(f"Routing to CLOUD tier (Groq {self.config.groq_brain_model})")
            engine_params = {
                "engine_type": "openai",
                "model": self.config.groq_brain_model,
                "api_key": self.config.groq_api_key,
                "base_url": "https://api.groq.com/openai/v1",
            }
            prompt = self.get_system_prompt(task_type, SandboxACI)
            return LMMAgent(engine_params=engine_params, system_prompt=prompt)

        elif task_type == "web":
            logger.info(f"Routing to LOCAL_WEB tier ({self.config.fara_model_id})")
            self._current_tier = ModelTier.LOCAL_WEB
            engine_params = {
                "engine_type": "vllm",
                "model": self.config.fara_model_id,
                "base_url": self.config.local_vllm_url,
                "api_key": "lmstudio",  # LM Studio ignores this but SDK requires non-empty
            }
            prompt = self.get_system_prompt(task_type, SandboxACI)
            return LMMAgent(engine_params=engine_params, system_prompt=prompt)

        else:
            logger.info(f"Routing to LOCAL_DESKTOP tier ({self.config.opencua_model_id})")
            self._current_tier = ModelTier.LOCAL_DESKTOP
            engine_params = {
                "engine_type": "vllm",
                "model": self.config.opencua_model_id,
                "base_url": self.config.local_vllm_url,
                "api_key": "lmstudio",
            }
            prompt = self.get_system_prompt(task_type, SandboxACI)
            return LMMAgent(engine_params=engine_params, system_prompt=prompt)

    def get_system_prompt(self, task_type: str, aci_class: type) -> str:
        """
        Return the correct PROCEDURAL_MEMORY prompt string for the active tier.
        - LOCAL_WEB     → FARA_PROCEDURAL_MEMORY (ChatML, JSON output)
        - LOCAL_DESKTOP → OPENCUA_PROCEDURAL_MEMORY (1D-RoPE, JSON output)
        - CLOUD         → construct_simple_worker_procedural_memory(aci_class)
        """
        if self._current_tier == ModelTier.CLOUD:
            try:
                from gui_agents.s3.memory.procedural_memory import PROCEDURAL_MEMORY
                # Reflectively auto-construct prompt with available @agent_action methods
                return PROCEDURAL_MEMORY.construct_simple_worker_procedural_memory(
                    aci_class, skipped_actions=[]
                )
            except Exception as e:
                logger.error(f"Error calling construct_simple_worker_procedural_memory: {e}. Using fallback.")
                return "You are a helpful cloud computer use agent. Output python code blocks like ```python\nagent.click(...)\n```"

        elif self._current_tier == ModelTier.LOCAL_WEB:
            return FARA_PROCEDURAL_MEMORY

        else:
            return OPENCUA_PROCEDURAL_MEMORY

    def should_escalate(self, sub_goal_id: str) -> bool:
        """
        Return True when failures on sub_goal_id reach ESCALATION_THRESHOLD.
        Always returns False when air_gap=True (escalation blocked).
        """
        if self.config.air_gap:
            return False
        
        failures = self._sub_goal_failures.get(sub_goal_id, 0)
        return failures >= 2

    def record_sub_goal_failure(self, sub_goal_id: str) -> None:
        """Increment failure count for a sub-goal. Called by Orchestrator."""
        self._sub_goal_failures[sub_goal_id] = self._sub_goal_failures.get(sub_goal_id, 0) + 1

    def reset_sub_goal(self, sub_goal_id: str) -> None:
        """Clear failure count after sub-goal succeeds or task escalates."""
        if sub_goal_id in self._sub_goal_failures:
            del self._sub_goal_failures[sub_goal_id]

    def force_cloud(self) -> None:
        """User toggled cloud mode in Tauri UI — override to cloud for this task."""
        if not self.config.air_gap:
            self._current_tier = ModelTier.CLOUD

    def reset_all_failures(self) -> None:
        """Clear all sub-goal failure counts after cloud escalation — prevents immediate re-escalation."""
        self._sub_goal_failures.clear()

    @property
    def current_tier(self) -> ModelTier:
        return self._current_tier

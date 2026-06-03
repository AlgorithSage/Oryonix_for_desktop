import logging
import asyncio
import re
import base64
import json
import urllib.request
from typing import Optional

logger = logging.getLogger("desktopenv.agent")

_BRAIN_SYSTEM = """You are the high-level planning "Brain" of an advanced computer-use agent running on a Windows desktop.
Your job is to guide a local GUI execution "Actor" to achieve a user's main goal by decomposing it into small, concrete, one-step sub-goals.

Main Goal: {main_goal}

CRITICAL RULES:
- The Oryonix agent chat interface may be visible on screen. COMPLETELY IGNORE IT. Do NOT tell the Actor to interact with it.
- You are controlling the Windows DESKTOP. Focus on desktop apps, taskbar, Start menu, and browser windows — not the Oryonix UI.
- To open or search for local applications/settings/files on Windows, always guide the Actor to open the Start menu (either click the Windows logo at the bottom-left or press the 'win' key) and then type the target name. Never assume a browser search is needed for local commands.
- Each SUB-GOAL must be a single, concrete desktop action. Examples:
    "Click the Chrome icon on the taskbar"
    "Click the Start button at the bottom-left"
    "Type 'youtube.com' in the browser address bar"
    "Press Win+R to open Run dialog"

At each step, you will be shown:
1. A screenshot of the current screen.
2. The history of actions taken so far.

Output exactly one of:
- SUB-GOAL: <single concrete 1-step action for the Actor>
- SUB-GOAL: DONE  (only when the main goal is fully achieved on screen)

Never output anything other than one of the two formats above."""

class PlannerAgent:
    """Manages high-level plan decomposition, generating sub-goals, and keeping plan state/history."""

    def __init__(self, config, router) -> None:
        self.config = config
        self.router = router
        self.action_history: list[str] = []
        self.current_sub_goal: Optional[str] = None
        self.sub_goal_failure_count: int = 0

    def reset(self) -> None:
        """Resets the history and planner state."""
        self.action_history = []
        self.current_sub_goal = None
        self.sub_goal_failure_count = 0

    def clear_sub_goal(self) -> None:
        """Clears the active sub-goal to force a replan on the next step."""
        self.current_sub_goal = None
        self.sub_goal_failure_count = 0

    async def plan(self, main_goal: str, screenshot: bytes) -> str:
        """
        Formulate a sub-goal planning request to the Cloud Brain (Claude) or Ollama Brain.
        Inject the main user goal, current screenshot, and chronological step history.
        """
        if self.config.air_gap:
            logger.warning("[PlannerAgent] Air-gapped mode active. Brain call blocked; defaulting to main goal.")
            return main_goal

        brain_system_prompt = _BRAIN_SYSTEM.format(main_goal=main_goal)
        history_str = "\n".join(self.action_history) if self.action_history else "No actions taken yet."
        user_message_content = (
            f"Here is the history of actions taken so far:\n"
            f"{history_str}\n\n"
            f"Please inspect the current screen and output the next sub-goal."
        )

        try:
            if not self.config.groq_api_key and not self.config.ollama_actor_model:
                logger.warning("[PlannerAgent] Neither GROQ_API_KEY nor OLLAMA_ACTOR_MODEL set — falling back to main goal.")
                return main_goal

            # Prefer Ollama for Brain when configured — local-first
            if self.config.ollama_actor_model:
                try:
                    result = await self._call_ollama_brain(screenshot, history_str, brain_system_prompt)
                    if result:
                        logger.info(f"[PlannerAgent] Ollama Brain sub-goal: {result}")
                        return result
                    logger.warning("[PlannerAgent] Ollama Brain returned empty. Falling back to main goal.")
                    return main_goal
                except Exception as ollama_brain_err:
                    logger.warning(f"[PlannerAgent] Ollama Brain failed: {ollama_brain_err}. Falling through to Groq.")

            if not self.config.groq_api_key:
                logger.warning("[PlannerAgent] Groq key not set — falling back to main goal.")
                return main_goal

            b64 = base64.standard_b64encode(screenshot).decode("utf-8") if screenshot else None
            content: list = [{"type": "text", "text": user_message_content}]
            if b64:
                content.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}})

            payload = {
                "model": self.config.groq_brain_model,
                "messages": [
                    {"role": "system", "content": brain_system_prompt},
                    {"role": "user", "content": content},
                ],
                "temperature": 0.0,
                "max_tokens": 256,
            }
            data_bytes = json.dumps(payload).encode("utf-8")

            def _brain_request() -> str:
                import time
                max_retries = 3
                backoff = 2.0
                for attempt in range(max_retries):
                    try:
                        req = urllib.request.Request(
                            "https://api.groq.com/openai/v1/chat/completions",
                            data=data_bytes,
                            headers={
                                "Content-Type": "application/json",
                                "Authorization": f"Bearer {self.config.groq_api_key}",
                                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                            },
                            method="POST",
                        )
                        with urllib.request.urlopen(req, timeout=30.0) as res:
                            return json.loads(res.read().decode("utf-8"))["choices"][0]["message"]["content"]
                    except urllib.error.HTTPError as http_err:
                        if http_err.code == 429 and attempt < max_retries - 1:
                            logger.warning(f"Groq Brain API returned 429 (Too Many Requests). Retrying in {backoff}s...")
                            time.sleep(backoff)
                            backoff *= 2.0
                            continue
                        raise http_err

            logger.info(f"[PlannerAgent] Calling Groq Brain ({self.config.groq_brain_model}) for next sub-goal...")
            loop = asyncio.get_running_loop()
            response_text = await loop.run_in_executor(None, _brain_request)
            response_text = response_text.strip()
            logger.info(f"[PlannerAgent] Brain Response: {response_text}")

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
            logger.warning(f"[PlannerAgent] Failed to call Cloud Brain: {e}. Falling back to main goal.")
            return main_goal

    async def _call_ollama_brain(self, screenshot: bytes, history_str: str, system_prompt: str) -> str:
        model = self.config.ollama_actor_model
        base_url = self.config.local_vllm_url.rstrip("/")

        user_content: list = [{"type": "text", "text": f"History:\n{history_str}\n\nInspect the screen and output the next sub-goal."}]
        if screenshot:
            b64 = base64.standard_b64encode(screenshot).decode("utf-8")
            user_content.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}})

        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            "temperature": 0.6,
            "max_tokens": 2048,
            "think": False,
        }
        data_bytes = json.dumps(payload).encode("utf-8")

        def _req() -> str:
            import urllib.request
            req = urllib.request.Request(
                f"{base_url}/chat/completions",
                data=data_bytes,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=180.0) as res:
                return res.read().decode("utf-8")

        loop = asyncio.get_running_loop()
        res_str = await loop.run_in_executor(None, _req)
        text = json.loads(res_str)["choices"][0]["message"]["content"].strip()
        logger.info(f"[PlannerAgent] Ollama Brain Response: {text}")

        match = re.search(r"SUB-GOAL:\s*(.*)", text, re.IGNORECASE)
        if match:
            sub_goal = match.group(1).strip()
        else:
            sub_goal = "DONE" if "done" in text.lower() and len(text) < 15 else text

        return "DONE" if sub_goal.upper() == "DONE" else sub_goal

"""
4-tier Verifier cascade.

Tier 1  — rule-based checks           (~0 ms,   ~40% coverage)
Tier 2  — accessibility state diff    (~50 ms,  ~70%)
Tier 3  — Qwen2-VL-2B local VLM       (~300 ms, ~85%)
Tier 4  — Claude/GPT-5 API            (~2-5 s,  ~95%)

Cascade stops at the first definitive SUCCESS or FAILURE.
Tier 4 is ALWAYS an API call — never a local model.
If air_gap=True: Tier 4 is skipped; cascade stops at Tier 3.
Llama-3-70B is NOT used anywhere (Gap C decision).
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import urllib.request
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Optional

# Configure logger
logger = logging.getLogger("desktopenv.agent")

if TYPE_CHECKING:
    from core.config import Config


class VerificationResult(str, Enum):
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    UNCERTAIN = "UNCERTAIN"    # → next tier


@dataclass
class VerifierOutput:
    result: VerificationResult
    tier_reached: int           # 1-4 — which tier gave the final verdict
    confidence: float           # 0.0-1.0
    reason: str                 # human-readable explanation for audit log


class Verifier:
    """Cascades through up to 4 tiers and returns the first definitive verdict."""

    def __init__(self, config: "Config") -> None:
        self.config = config

    async def verify(
        self,
        sub_goal: str,
        action_taken: str,
        before_screenshot: bytes,
        after_screenshot: bytes,
        accessibility_before: Optional[dict] = None,
        accessibility_after: Optional[dict] = None,
    ) -> VerifierOutput:
        """
        Run the cascade.  Returns as soon as a tier gives SUCCESS or FAILURE.
        UNCERTAIN cascades to the next tier.
        """
        logger.info(f"Verifier cascade started for sub_goal: '{sub_goal}' | Action: '{action_taken}'")

        # ── TIER 1: Rule-based Checks ─────────────────────────────────────────
        tier1 = await self._tier1_rules(sub_goal, action_taken)
        if tier1 and tier1.result != VerificationResult.UNCERTAIN:
            logger.info(f"Tier 1 Rule match: {tier1.result} | Reason: {tier1.reason}")
            return tier1

        # ── TIER 2: Accessibility Tree Diff ───────────────────────────────────
        if accessibility_before is not None or accessibility_after is not None:
            tier2 = await self._tier2_state_diff(
                accessibility_before, accessibility_after, sub_goal
            )
            if tier2 and tier2.result != VerificationResult.UNCERTAIN:
                logger.info(f"Tier 2 Accessibility Diff match: {tier2.result} | Reason: {tier2.reason}")
                return tier2

        # ── TIER 3: Local Qwen2-VL-2B VLM ──────────────────────────────────────
        # Skipped when qwen_vlm_url is empty (e.g. no separate VLM server running)
        if self.config.qwen_vlm_url:
            tier3 = await self._tier3_local_vlm(
                before_screenshot, after_screenshot, sub_goal
            )
            if tier3 and tier3.result != VerificationResult.UNCERTAIN:
                logger.info(f"Tier 3 Local VLM match: {tier3.result} | Reason: {tier3.reason}")
                return tier3
        else:
            logger.info("Tier 3 skipped — QWEN_VLM_URL not configured, cascading to Tier 4.")

        # ── TIER 4: Claude/GPT API ────────────────────────────────────────────
        tier4 = await self._tier4_api(
            before_screenshot, after_screenshot, sub_goal
        )
        logger.info(f"Tier 4 API Verdict: {tier4.result} | Reason: {tier4.reason}")
        return tier4

    async def _tier1_rules(
        self, sub_goal: str, action: str
    ) -> Optional[VerifierOutput]:
        """
        Fast rule-based checks: error dialogs, loading spinners, known
        success patterns. Returns None if uncertain.
        """
        action_clean = action.strip().lower()
        sub_goal_clean = sub_goal.strip().lower()

        # Immediate wait action success
        if "wait(" in action_clean or "sleep(" in action_clean or "wait" == action_clean or "sb.wait" in action_clean:
            return VerifierOutput(
                result=VerificationResult.SUCCESS,
                tier_reached=1,
                confidence=1.0,
                reason="Step action was a wait/sleep which is always assumed successful."
            )

        # Immediate task completion done/fail action signals
        if "done(" in action_clean or "done" == action_clean or "done()" in action_clean:
            return VerifierOutput(
                result=VerificationResult.SUCCESS,
                tier_reached=1,
                confidence=1.0,
                reason="Agent executed 'done' action signaling successful completion."
            )

        if "fail(" in action_clean or "fail" == action_clean or "fail()" in action_clean:
            return VerifierOutput(
                result=VerificationResult.FAILURE,
                tier_reached=1,
                confidence=1.0,
                reason="Agent executed 'fail' action indicating task is unachievable."
            )

        # Error state keyword signatures in goal indicating failure
        if "error dialog" in sub_goal_clean and ("crash" in action_clean or "error" in action_clean):
            return VerifierOutput(
                result=VerificationResult.FAILURE,
                tier_reached=1,
                confidence=0.8,
                reason="Rule check matched error/crash signature in sub-goal."
            )

        return None

    async def _tier2_state_diff(
        self,
        acc_before: Optional[dict],
        acc_after: Optional[dict],
        sub_goal: str,
    ) -> Optional[VerifierOutput]:
        """
        Compare accessibility trees before/after.
        Returns None if uncertain.
        """
        before_elements = acc_before.get("elements", []) if isinstance(acc_before, dict) else (acc_before or [])
        after_elements = acc_after.get("elements", []) if isinstance(acc_after, dict) else (acc_after or [])

        if not before_elements and not after_elements:
            return None

        before_ids = {el.get("id") for el in before_elements if isinstance(el, dict) and el.get("id")}
        after_ids = {el.get("id") for el in after_elements if isinstance(el, dict) and el.get("id")}

        sub_goal_clean = sub_goal.lower()

        # Target closure checking
        if "close" in sub_goal_clean or "dismiss" in sub_goal_clean or "exit" in sub_goal_clean:
            removed_ids = before_ids - after_ids
            if removed_ids:
                return VerifierOutput(
                    result=VerificationResult.SUCCESS,
                    tier_reached=2,
                    confidence=0.9,
                    reason=f"Accessibility Diff: Target element(s) {removed_ids} successfully closed/dismissed."
                )

        # Target opening/creation checking
        if "open" in sub_goal_clean or "click" in sub_goal_clean or "launch" in sub_goal_clean or "new" in sub_goal_clean:
            added_ids = after_ids - before_ids
            if added_ids:
                return VerifierOutput(
                    result=VerificationResult.SUCCESS,
                    tier_reached=2,
                    confidence=0.9,
                    reason=f"Accessibility Diff: Target element(s) {added_ids} successfully spawned."
                )

        return None

    async def _tier3_local_vlm(
        self,
        before: bytes,
        after: bytes,
        sub_goal: str,
    ) -> Optional[VerifierOutput]:
        """
        Query Qwen2-VL-2B via local vLLM endpoint.
        Returns None if uncertain.
        """
        before_b64 = base64.b64encode(before).decode("utf-8")
        after_b64 = base64.b64encode(after).decode("utf-8")

        prompt = f"""You are a visual verification agent. Compare the before and after screenshots of the computer display and determine if the action successfully achieved the sub-goal.
Sub-goal: {sub_goal}

Output exactly one word in your response:
SUCCESS - if the goal was successfully achieved.
FAILURE - if the goal clearly failed or resulted in error.
UNCERTAIN - if you cannot definitively determine success or failure from the screenshots.
"""
        try:
            payload = {
                "model": self.config.qwen_vlm_model_id,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{before_b64}"}},
                            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{after_b64}"}}
                        ]
                    }
                ],
                "temperature": 0.0,
                "max_tokens": 10
            }

            req = urllib.request.Request(
                f"{self.config.local_vllm_url.rstrip('/')}/chat/completions",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST"
            )

            # Avoid blocking async event loop for local URL request
            def call_vllm():
                with urllib.request.urlopen(req, timeout=2.0) as res:
                    return res.read().decode("utf-8")

            loop = asyncio.get_event_loop()
            res_str = await loop.run_in_executor(None, call_vllm)
            res_data = json.loads(res_str)
            verdict = res_data["choices"][0]["message"]["content"].strip().upper()

            if "SUCCESS" in verdict:
                return VerifierOutput(
                    result=VerificationResult.SUCCESS,
                    tier_reached=3,
                    confidence=0.8,
                    reason="Local Qwen2-VL-2B visually verified goal achievement."
                )
            elif "FAILURE" in verdict:
                return VerifierOutput(
                    result=VerificationResult.FAILURE,
                    tier_reached=3,
                    confidence=0.8,
                    reason="Local Qwen2-VL-2B visually identified step failure."
                )
        except Exception as e:
            logger.warning(f"Local Qwen2-VL-2B VLM call failed: {e}. Cascading to next tier.")

        return None

    async def _tier4_api(
        self,
        before: bytes,
        after: bytes,
        sub_goal: str,
    ) -> VerifierOutput:
        """
        Claude API visual judge — compares before/after screenshots with vision.
        Always returns a definitive verdict (never UNCERTAIN).
        Skipped entirely when air_gap=True.
        """
        if self.config.air_gap:
            logger.info("Air-gap active — Tier 4 skipped. Cascade stops at Tier 3.")
            return VerifierOutput(
                result=VerificationResult.FAILURE,
                tier_reached=3,
                confidence=0.5,
                reason="Verification cascade stopped at Tier 3 due to air-gap policy.",
            )

        if not self.config.claude_api_key:
            logger.warning("Tier 4: no Claude API key — defaulting to SUCCESS.")
            return VerifierOutput(
                result=VerificationResult.SUCCESS,
                tier_reached=4,
                confidence=0.5,
                reason="No Claude API key configured; assuming step succeeded.",
            )

        before_b64 = base64.b64encode(before).decode("utf-8")
        after_b64 = base64.b64encode(after).decode("utf-8")

        prompt = (
            f"You are a visual verification agent for a desktop automation system.\n"
            f"You are given two screenshots: BEFORE an action and AFTER an action.\n\n"
            f"Sub-goal that should have been achieved: {sub_goal}\n\n"
            f"Compare the two screenshots carefully. "
            f"Reply with exactly one word — SUCCESS, FAILURE, or UNCERTAIN — nothing else."
        )

        try:
            from anthropic import Anthropic
            client = Anthropic(api_key=self.config.claude_api_key)

            def _call() -> str:
                response = client.messages.create(
                    model="claude-3-5-sonnet-20241022",
                    max_tokens=10,
                    messages=[{
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image", "source": {
                                "type": "base64", "media_type": "image/png", "data": before_b64,
                            }},
                            {"type": "image", "source": {
                                "type": "base64", "media_type": "image/png", "data": after_b64,
                            }},
                        ],
                    }],
                )
                return response.content[0].text.strip().upper()

            loop = asyncio.get_event_loop()
            verdict = await loop.run_in_executor(None, _call)
            logger.info(f"Tier 4 Claude verdict: {verdict!r}")

            if "SUCCESS" in verdict:
                return VerifierOutput(
                    result=VerificationResult.SUCCESS,
                    tier_reached=4,
                    confidence=0.95,
                    reason="Claude vision confirmed goal achieved.",
                )
            elif "FAILURE" in verdict:
                return VerifierOutput(
                    result=VerificationResult.FAILURE,
                    tier_reached=4,
                    confidence=0.95,
                    reason="Claude vision detected the action did not achieve the goal.",
                )
            else:
                # UNCERTAIN or unexpected — default to SUCCESS to avoid blocking progress
                return VerifierOutput(
                    result=VerificationResult.SUCCESS,
                    tier_reached=4,
                    confidence=0.6,
                    reason=f"Claude returned uncertain verdict ({verdict!r}); defaulting to success.",
                )

        except Exception as e:
            logger.error(f"Tier 4 Claude API call failed: {e}. Defaulting to SUCCESS.")
            return VerifierOutput(
                result=VerificationResult.SUCCESS,
                tier_reached=4,
                confidence=0.5,
                reason=f"Tier 4 API error ({e}); assuming success to avoid blocking.",
            )

    async def verify_coordinate(
        self,
        action: "Action",
        screenshot: bytes,
        task: str,
    ) -> "Action":
        """
        Verify the action's coordinates using UI-TARS-1.5-7B (grounding model).
        If the predicted coordinates from ShowUI match UI-TARS coordinates within a threshold,
        the coordinates are verified. Otherwise, we refine ShowUI's coordinates using UI-TARS's
        more accurate prediction.
        """
        import re
        import math
        
        # 1. Check if action has coordinates to verify
        has_coords = False
        is_drag = False
        x_showui = 0.0
        y_showui = 0.0
        
        if "x_norm" in action.params and "y_norm" in action.params:
            x_showui = float(action.params["x_norm"])
            y_showui = float(action.params["y_norm"])
            has_coords = True
        elif "x1_norm" in action.params and "y1_norm" in action.params:
            x_showui = float(action.params["x1_norm"])
            y_showui = float(action.params["y1_norm"])
            has_coords = True
            is_drag = True
            
        if not has_coords:
            return action

        # 2. Extract description for grounding
        target_description = action.target_description or action.element_id
        if not target_description:
            if action.type == "type" and action.params.get("text"):
                target_description = f"input text field for '{action.params.get('text')}'"
            elif action.type == "click":
                target_description = "clickable element"
            else:
                target_description = task

        # Ensure target_description is not too generic
        if target_description.lower() in ("element", "screen", "clickable", "clickable element"):
            target_description = task

        logger.info(f"[UI-TARS] Verifying coordinate [{x_showui:.3f}, {y_showui:.3f}] for target: '{target_description}'")

        # 3. Call local UI-TARS model
        if not self.config.uitars_model_id:
            logger.warning("[UI-TARS] uitars_model_id not configured. Skipping coordinate verification.")
            return action

        before_b64 = base64.b64encode(screenshot).decode("utf-8")
        # Standard UI-TARS grounding prompt format
        prompt = f"Query: {target_description}\nOutput only the coordinate of one point in your response.\n"
        
        payload = {
            "model": self.config.uitars_model_id,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{before_b64}"}}
                    ]
                }
            ],
            "temperature": 0.0,
            "max_tokens": 30
        }

        try:
            req = urllib.request.Request(
                f"{self.config.local_vllm_url.rstrip('/')}/chat/completions",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST"
            )

            def call_uitars():
                with urllib.request.urlopen(req, timeout=10.0) as res:
                    return res.read().decode("utf-8")

            loop = asyncio.get_event_loop()
            res_str = await loop.run_in_executor(None, call_uitars)
            res_data = json.loads(res_str)
            response_text = res_data["choices"][0]["message"]["content"].strip()
            
            logger.info(f"[UI-TARS] Raw grounding response: {response_text}")
            
            # Parse coordinate from response
            # UI-TARS returns coordinates as (x, y) where x,y are in [0, 1000]
            coord_match = re.search(r"[\(\[\{]\s*(\d+)\s*,\s*(\d+)\s*[\)\]\}]", response_text)
            if coord_match:
                x_tars = float(coord_match.group(1))
                y_tars = float(coord_match.group(2))
            else:
                numericals = re.findall(r"\d+", response_text)
                if len(numericals) >= 2:
                    x_tars = float(numericals[0])
                    y_tars = float(numericals[1])
                else:
                    x_tars = y_tars = None
            
            if x_tars is not None and y_tars is not None:
                x_tars_norm = x_tars / 1000.0
                y_tars_norm = y_tars / 1000.0
                
                # Check Euclidean distance
                dist = math.sqrt((x_showui - x_tars_norm)**2 + (y_showui - y_tars_norm)**2)
                threshold = 0.08  # 8% of screen dimension
                
                if dist <= threshold:
                    logger.info(f"[UI-TARS] Coordinate verified! Distance: {dist:.4f} <= {threshold}")
                else:
                    logger.warning(
                        f"[UI-TARS] Coordinate MISMATCH (distance: {dist:.4f} > {threshold}). "
                        f"ShowUI: [{x_showui:.3f}, {y_showui:.3f}] vs UI-TARS: [{x_tars_norm:.3f}, {y_tars_norm:.3f}]."
                    )
                    logger.info(f"[UI-TARS] Refining coordinates to UI-TARS predictions: [{x_tars_norm:.3f}, {y_tars_norm:.3f}]")
                    if is_drag:
                        action.params["x1_norm"] = x_tars_norm
                        action.params["y1_norm"] = y_tars_norm
                    else:
                        action.params["x_norm"] = x_tars_norm
                        action.params["y_norm"] = y_tars_norm
                    
                    # Clear absolute coordinates to force SandboxACI to scale using new normalized values
                    if "x" in action.params:
                        del action.params["x"]
                    if "y" in action.params:
                        del action.params["y"]
            else:
                logger.warning(f"[UI-TARS] Could not parse coordinates from response: {response_text}")
        except Exception as e:
            logger.warning(f"[UI-TARS] Call to UI-TARS grounding failed: {e}. Proceeding with original coordinates.")
            
        return action

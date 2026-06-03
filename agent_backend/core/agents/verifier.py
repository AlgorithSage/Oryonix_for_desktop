import logging
from verifier.verifier import Verifier, VerificationResult, VerifierOutput
from llm.action_normalizer import Action

logger = logging.getLogger("desktopenv.agent")

class VerifierAgent:
    """Wraps the existing 4-tier verifier cascade (rules, accessibility state, local VLM, and cloud vision models)."""

    def __init__(self, config) -> None:
        self._verifier = Verifier(config)

    async def verify(
        self,
        sub_goal: str,
        action_taken: str,
        before_screenshot: bytes,
        after_screenshot: bytes,
        accessibility_before=None,
        accessibility_after=None,
    ) -> VerifierOutput:
        """
        Evaluate if the step/action successfully achieved the sub-goal.
        """
        return await self._verifier.verify(
            sub_goal=sub_goal,
            action_taken=action_taken,
            before_screenshot=before_screenshot,
            after_screenshot=after_screenshot,
            accessibility_before=accessibility_before,
            accessibility_after=accessibility_after,
        )

    async def verify_coordinate(
        self,
        action: Action,
        screenshot: bytes,
        task: str,
    ) -> Action:
        """
        Grind and verify coordinates against the grounding model (UI-TARS).
        """
        return await self._verifier.verify_coordinate(
            action=action,
            screenshot=screenshot,
            task=task,
        )

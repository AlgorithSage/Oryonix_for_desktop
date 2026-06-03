"""
Windows UIA Layer — additive automation strategy for Oryonix.

This module dynamically loads Microsoft UFO's UIA infrastructure
(pywinauto, ControlInspectorFacade, AppPuppeteer, ExecuteAgent)
and exposes a high-level interface that the Orchestrator can call
*before* falling back to visual ShowUI coordinate grounding.

Design Principles:
  1. ADDITIVE — never replaces existing ShowUI / Groq execution paths.
  2. GRACEFUL — every public method returns a success/failure result
     so the caller can seamlessly fall through to the next tier.
  3. ISOLATED — all UFO imports are gated behind _setup_ufo_imports()
     and only run on Windows + when USE_WINDOWS_UIA=true.
"""

from __future__ import annotations

import logging
import os
import platform
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("oryonix.windows_uia")

# ── Result container ──────────────────────────────────────────────────────────
@dataclass
class UIAStepResult:
    """Outcome of a single UIA execution attempt."""
    success: bool = False
    action_taken: str = ""
    control_text: str = ""
    error: str = ""
    controls_found: int = 0


# ── Dynamic UFO import helper ────────────────────────────────────────────────
_ufo_imported = False


def _setup_ufo_imports() -> bool:
    """
    Insert the cloned UFO repository root into sys.path so that
    `from ufo.automator.ui_control.inspector import ControlInspectorFacade`
    and related imports resolve correctly.

    Returns True if imports succeeded, False otherwise.
    """
    global _ufo_imported
    if _ufo_imported:
        return True

    if platform.system() != "Windows":
        logger.warning("UIA layer is only available on Windows.")
        return False

    # Resolve UFO repo root relative to this file:
    #   agent_backend/windows_only/uia_layer.py  →  ../../UFO
    ufo_root = os.path.normpath(
        os.path.join(os.path.dirname(__file__), "..", "..", "UFO")
    )
    if not os.path.isdir(ufo_root):
        logger.error(f"UFO repository not found at {ufo_root}. UIA layer disabled.")
        return False

    # Add UFO root so `ufo.*` and `dataflow.*` and `config.*` resolve
    if ufo_root not in sys.path:
        sys.path.insert(0, ufo_root)
        logger.info(f"[UIA Layer] Injected UFO root into sys.path: {ufo_root}")

    try:
        # Initialize UFO's ConfigLoader with the correct config directory path
        from config.config_loader import ConfigLoader
        ConfigLoader.get_instance(os.path.join(ufo_root, "config"))
        logger.info(f"[UIA Layer] Initialized UFO ConfigLoader with path: {os.path.join(ufo_root, 'config')}")

        # Verify critical imports
        from ufo.automator.ui_control.inspector import ControlInspectorFacade  # noqa: F401
        from ufo.automator.puppeteer import AppPuppeteer  # noqa: F401
        logger.info("[UIA Layer] UFO imports verified successfully.")
        _ufo_imported = True
        return True
    except (ImportError, FileNotFoundError) as e:
        logger.error(f"[UIA Layer] Failed to import/initialize UFO modules: {e}")
        return False


# ── Main UIA Layer class ─────────────────────────────────────────────────────

class WindowsUIALayer:
    """
    High-level bridge between Oryonix Orchestrator and UFO's UIA automation.

    Usage in Orchestrator._worker_loop():
        uia = WindowsUIALayer()
        if uia.is_available():
            result = await uia.attempt_uia_step(sub_goal, screenshot)
            if result.success:
                # UIA executed the action directly — skip ShowUI
                ...
            else:
                # Fall through to ShowUI coordinate path
                ...
    """

    def __init__(self) -> None:
        self._available: Optional[bool] = None
        self._inspector = None  # ControlInspectorFacade (lazy)

    def is_available(self) -> bool:
        """Check if UIA layer can be used (Windows + imports OK)."""
        if self._available is None:
            self._available = _setup_ufo_imports()
        return self._available

    def _get_inspector(self):
        """Lazy-load the ControlInspectorFacade singleton."""
        if self._inspector is None:
            from ufo.automator.ui_control.inspector import ControlInspectorFacade
            self._inspector = ControlInspectorFacade(backend="uia")
        return self._inspector

    # ── Public: enumerate visible desktop windows ────────────────────────────
    def get_desktop_windows(self) -> List[Dict[str, str]]:
        """
        Return a list of visible desktop windows with their
        process names and titles.
        """
        if not self.is_available():
            return []
        try:
            inspector = self._get_inspector()
            windows = inspector.get_desktop_windows(remove_empty=True)
            result = []
            for win in windows:
                try:
                    app_name = inspector.get_application_root_name(win)
                    title = win.window_text() if hasattr(win, "window_text") else ""
                    result.append({
                        "process_name": app_name,
                        "title": title,
                    })
                except Exception:
                    continue
            return result
        except Exception as e:
            logger.warning(f"[UIA Layer] Failed to enumerate desktop windows: {e}")
            return []

    # ── Public: find a target window by process name or title ────────────────
    def find_window(self, *, process_name: str = "", title_contains: str = ""):
        """
        Find the first visible window matching the given criteria.
        Returns the UIAWrapper or None.
        """
        if not self.is_available():
            return None
        try:
            inspector = self._get_inspector()
            windows = inspector.get_desktop_windows(remove_empty=True)
            for win in windows:
                try:
                    app_name = inspector.get_application_root_name(win)
                    win_title = win.window_text() if hasattr(win, "window_text") else ""

                    if process_name and process_name.lower() not in app_name.lower():
                        continue
                    if title_contains and title_contains.lower() not in win_title.lower():
                        continue
                    return win
                except Exception:
                    continue
            return None
        except Exception as e:
            logger.warning(f"[UIA Layer] Window search failed: {e}")
            return None

    # ── Public: crawl controls in a window ───────────────────────────────────
    def crawl_controls(
        self,
        window,
        control_types: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Use the UIA inspector to enumerate all actionable controls
        in the given window.

        Returns a list of dicts with keys:
          control_type, control_text, control_name, control_rect
        """
        if not self.is_available() or window is None:
            return []
        try:
            inspector = self._get_inspector()
            # Default to the most common interactive control types
            if control_types is None:
                control_types = [
                    "Button", "Edit", "ComboBox", "CheckBox",
                    "RadioButton", "MenuItem", "TabItem",
                    "Hyperlink", "ListItem", "TreeItem",
                    "DataItem", "Text", "Document",
                ]

            controls = inspector.find_control_elements_in_descendants(
                window=window,
                control_type_list=control_types,
                is_visible=True,
                is_enabled=True,
            )
            info_list = inspector.get_control_info_batch(
                controls,
                field_list=["control_type", "control_text", "control_name", "control_rect"],
            )
            return info_list
        except Exception as e:
            logger.warning(f"[UIA Layer] Control crawling failed: {e}")
            return []

    # ── Public: execute a UIA action on a matched control ────────────────────
    def execute_on_control(
        self,
        window,
        control_text: str,
        action: str = "click",
        input_text: str = "",
    ) -> UIAStepResult:
        """
        Find a control by its text/name in the given window and perform
        a UIA action on it (click, set_text, etc.).

        Args:
            window: UIAWrapper of the target application window.
            control_text: The visible text/name of the target control.
            action: One of 'click', 'set_text', 'double_click', 'right_click'.
            input_text: Text to type (only used when action='set_text').

        Returns:
            UIAStepResult with success/failure details.
        """
        if not self.is_available() or window is None:
            return UIAStepResult(error="UIA not available or window is None")

        try:
            inspector = self._get_inspector()
            controls = inspector.find_control_elements_in_descendants(
                window=window,
                control_type_list=[],  # all types
                is_visible=True,
                is_enabled=True,
            )

            # Find the best matching control by text/name
            target = None
            for ctrl in controls:
                try:
                    name = ctrl.element_info.name or ""
                    if control_text.lower() in name.lower():
                        target = ctrl
                        break
                except Exception:
                    continue

            if target is None:
                return UIAStepResult(
                    success=False,
                    error=f"No control found matching '{control_text}'",
                    controls_found=len(controls),
                )

            # Set focus on the target control first, just like UFO's ControlReceiver
            try:
                target.set_focus()
            except Exception as fe:
                logger.warning(f"[UIA Layer] Failed to set focus on control: {fe}")

            # Execute the action
            target_name = target.element_info.name or control_text
            if action == "click":
                target.click_input()
                action_desc = f"Clicked '{target_name}'"
            elif action == "set_text":
                try:
                    target.set_text(input_text)
                except Exception as se:
                    logger.info(f"[UIA Layer] set_text failed ({se}); falling back to type_keys...")
                    # fallback to type_keys which works across general control types
                    target.type_keys(input_text, with_spaces=True)
                action_desc = f"Set text '{input_text}' on '{target_name}'"
            elif action == "double_click":
                target.double_click_input()
                action_desc = f"Double-clicked '{target_name}'"
            elif action == "right_click":
                target.right_click_input()
                action_desc = f"Right-clicked '{target_name}'"
            else:
                return UIAStepResult(
                    success=False,
                    error=f"Unknown action '{action}'",
                )

            logger.info(f"[UIA Layer] {action_desc}")
            return UIAStepResult(
                success=True,
                action_taken=action_desc,
                control_text=target_name,
                controls_found=len(controls),
            )

        except Exception as e:
            logger.warning(f"[UIA Layer] execute_on_control failed: {e}")
            return UIAStepResult(success=False, error=str(e))

    # ── Public: high-level attempt for the orchestrator ──────────────────────
    async def attempt_uia_step(
        self,
        sub_goal: str,
        screenshot: bytes,
        groq_api_key: str = "",
        groq_model: str = "",
    ) -> UIAStepResult:
        """
        High-level integration point for the Orchestrator.

        Given a sub-goal (from the Brain), this method:
          1. Enumerates visible desktop windows.
          2. Crawls UIA controls in the foreground window.
          3. Uses the Groq Brain to select the best control + action.
          4. Executes the chosen UIA action directly.

        If any step fails, returns UIAStepResult(success=False) so the
        orchestrator can gracefully fall through to ShowUI.
        """
        import asyncio

        if not self.is_available():
            return UIAStepResult(error="UIA layer not available")

        try:
            # 1. Get foreground window (the window user is most likely interacting with)
            inspector = self._get_inspector()
            desktop_windows = inspector.get_desktop_windows(remove_empty=True)

            if not desktop_windows:
                return UIAStepResult(error="No desktop windows found")

            # Try to use the foreground window
            import ctypes
            user32 = ctypes.windll.user32
            fg_hwnd = user32.GetForegroundWindow()

            target_window = None
            for win in desktop_windows:
                try:
                    if hasattr(win, "handle") and win.handle == fg_hwnd:
                        target_window = win
                        break
                except Exception:
                    continue

            # Fallback: use the first window
            if target_window is None and desktop_windows:
                target_window = desktop_windows[0]

            if target_window is None:
                return UIAStepResult(error="No target window found")

            # 2. Crawl controls
            controls = self.crawl_controls(target_window)
            if not controls:
                return UIAStepResult(
                    error="No actionable UIA controls found in target window",
                    controls_found=0,
                )

            # 3. Ask the Brain (Groq) to pick the best control + action
            if not groq_api_key:
                return UIAStepResult(
                    error="No Groq API key for UIA control selection",
                    controls_found=len(controls),
                )

            # Build a compact control list for the LLM
            control_descriptions = []
            for i, ctrl in enumerate(controls[:50]):  # Cap at 50 to fit token window
                ctrl_type = ctrl.get("control_type", "")
                ctrl_text = ctrl.get("control_text", "") or ctrl.get("control_name", "")
                if ctrl_text:
                    control_descriptions.append(f"[{i}] {ctrl_type}: \"{ctrl_text}\"")

            if not control_descriptions:
                return UIAStepResult(
                    error="No named controls found for LLM selection",
                    controls_found=len(controls),
                )

            controls_str = "\n".join(control_descriptions)

            uia_prompt = (
                f"You are a Windows desktop automation agent. "
                f"The user wants to: {sub_goal}\n\n"
                f"Here are the available UI controls in the active window:\n"
                f"{controls_str}\n\n"
                f"Select the BEST control to interact with and the action to perform.\n"
                f"Respond with EXACTLY this JSON format (no markdown, no extra text):\n"
                f'{{"index": <number>, "action": "click"|"set_text"|"double_click", "text": "<text to type if set_text, else empty>"}}\n\n'
                f"If no control matches the goal, respond with:\n"
                f'{{"index": -1, "action": "none", "text": ""}}'
            )

            # Call Groq API to decide
            import json
            import urllib.request

            payload = {
                "model": groq_model or "meta-llama/llama-4-scout-17b-16e-instruct",
                "messages": [
                    {"role": "user", "content": uia_prompt},
                ],
                "temperature": 0.0,
                "max_tokens": 128,
            }
            data_bytes = json.dumps(payload).encode("utf-8")

            loop = asyncio.get_running_loop()

            def _groq_request() -> str:
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
                                "Authorization": f"Bearer {groq_api_key}",
                                "User-Agent": "Mozilla/5.0",
                            },
                            method="POST",
                        )
                        with urllib.request.urlopen(req, timeout=15.0) as res:
                            return json.loads(res.read().decode("utf-8"))["choices"][0]["message"]["content"]
                    except urllib.error.HTTPError as http_err:
                        if http_err.code == 429 and attempt < max_retries - 1:
                            time.sleep(backoff)
                            backoff *= 2.0
                            continue
                        raise

            raw_response = await loop.run_in_executor(None, _groq_request)

            # Parse the LLM response
            raw_response = raw_response.strip()
            # Strip markdown fences if present
            if raw_response.startswith("```"):
                raw_response = raw_response.split("\n", 1)[-1]
            if raw_response.endswith("```"):
                raw_response = raw_response.rsplit("```", 1)[0]
            raw_response = raw_response.strip()

            try:
                decision = json.loads(raw_response)
            except json.JSONDecodeError:
                return UIAStepResult(
                    success=False,
                    error=f"LLM returned unparseable response: {raw_response[:200]}",
                    controls_found=len(controls),
                )

            chosen_idx = decision.get("index", -1)
            chosen_action = decision.get("action", "none")
            chosen_text = decision.get("text", "")

            if chosen_idx < 0 or chosen_action == "none":
                return UIAStepResult(
                    success=False,
                    error="LLM decided no suitable UIA control matches the sub-goal",
                    controls_found=len(controls),
                )

            if chosen_idx >= len(controls):
                return UIAStepResult(
                    success=False,
                    error=f"LLM chose index {chosen_idx} but only {len(controls)} controls available",
                    controls_found=len(controls),
                )

            # 4. Execute the UIA action
            chosen_ctrl_text = controls[chosen_idx].get("control_text", "") or controls[chosen_idx].get("control_name", "")

            result = self.execute_on_control(
                window=target_window,
                control_text=chosen_ctrl_text,
                action=chosen_action,
                input_text=chosen_text,
            )

            return result

        except Exception as e:
            logger.warning(f"[UIA Layer] attempt_uia_step failed: {e}")
            return UIAStepResult(success=False, error=str(e))

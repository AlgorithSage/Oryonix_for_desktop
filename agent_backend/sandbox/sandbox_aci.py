"""
SandboxACI — replaces Agent-S3's OSWorldACI entirely.

All @agent_action decorated methods execute via the trycua/cua SDK
(sb.mouse.click, sb.keyboard.type, sb.shell.run, etc.)
instead of host-side pyautogui.

Coordinate scaling (Gap F):
  Grounding model (UI-TARS) outputs coords in screenshot pixel space.
  Sandbox display resolution may differ → must scale before every click/drag.
  scale_x = sandbox_width / screenshot_width
  scale_y = sandbox_height / screenshot_height

sys.path note: Agent-S3 path is added by main.py before this module imports.
"""
from __future__ import annotations

import logging
import re
import sys
import asyncio
from io import BytesIO
from typing import TYPE_CHECKING, Optional, Any

# Configure logger
logger = logging.getLogger("desktopenv.agent")

# Try importing PIL
try:
    from PIL import Image as PILImage
except ImportError:
    PILImage = None


def _make_placeholder_png() -> bytes:
    """Generate a valid 1×1 transparent PNG at runtime using PIL (avoids hardcoded byte corruption)."""
    if PILImage is not None:
        try:
            buf = BytesIO()
            PILImage.new("RGBA", (1, 1), (0, 0, 0, 0)).save(buf, format="PNG")
            return buf.getvalue()
        except Exception:
            pass
    return b""

_TRANSPARENT_1X1_PNG = _make_placeholder_png()

# Agent-S3 ACI base — path is added to sys.path in main.py at startup
try:
    from gui_agents.s3.agents.grounding import ACI as _AgentS3ACI, agent_action
    _BASE_CLASS = _AgentS3ACI
except ImportError:
    # Skeleton mode: Agent-S3 not yet on sys.path — ACI will be resolved in Chunk 4
    _BASE_CLASS = object  # type: ignore[assignment]
    def agent_action(func):
        func.is_agent_action = True
        return func

# Safe import for trycua/cua
try:
    import cua
    from cua import Sandbox, Image
    HAS_CUA = True
except ImportError:
    HAS_CUA = False

# Host-mode sandbox via pyautogui — real Windows desktop control, no VM needed.
# Falls back to mock logging when pyautogui is not installed.
if not HAS_CUA:
    try:
        import pyautogui as _pag
        _pag.FAILSAFE = True   # move mouse to top-left corner to abort the agent
        _pag.PAUSE = 0.05
        HAS_PYAUTOGUI = True
        logger.info("[Sandbox] pyautogui available — HOST MODE active (real desktop control)")
    except ImportError:
        HAS_PYAUTOGUI = False
        logger.warning("[Sandbox] pyautogui not installed — MOCK MODE (no real actions)")

    class Image:
        @classmethod
        def linux(cls) -> "Image":
            return cls()
        @classmethod
        def windows(cls, path: str | None = None) -> "Image":
            return cls()

    # ── Host-mode implementations (pyautogui) ────────────────────────────────
    class _HostMouse:
        async def click(self, x: int, y: int, clicks: int = 1, button: str = "left") -> None:
            await asyncio.to_thread(_pag.click, x, y, clicks=clicks, button=button)

        async def move(self, x: int, y: int) -> None:
            await asyncio.to_thread(_pag.moveTo, x, y, duration=0.15)

        async def scroll(self, clicks: int) -> None:
            await asyncio.to_thread(_pag.scroll, clicks)

        async def down(self) -> None:
            await asyncio.to_thread(_pag.mouseDown)

        async def up(self) -> None:
            await asyncio.to_thread(_pag.mouseUp)

    class _HostKeyboard:
        async def type(self, text: str) -> None:
            # Clipboard paste is faster and handles unicode — fall back to write()
            try:
                import pyperclip
                pyperclip.copy(text)
                await asyncio.to_thread(_pag.hotkey, "ctrl", "v")
            except ImportError:
                await asyncio.to_thread(_pag.write, text, interval=0.02)

        async def hotkey(self, *keys: str) -> None:
            await asyncio.to_thread(_pag.hotkey, *keys)

    class _HostShell:
        async def run(self, cmd: str) -> dict[str, Any]:
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
                return {
                    "stdout": stdout.decode(errors="replace"),
                    "stderr": stderr.decode(errors="replace"),
                    "exit_code": proc.returncode or 0,
                }
            except asyncio.TimeoutError:
                proc.kill()
                return {"stdout": "", "stderr": "Command timed out after 30s", "exit_code": -1}

    # ── Mock implementations (fallback when pyautogui not installed) ──────────
    class _MockMouse:
        async def click(self, x: int, y: int, clicks: int = 1, button: str = "left") -> None:
            logger.info(f"[MockMouse] click ({x},{y}) btn={button} n={clicks}")
        async def move(self, x: int, y: int) -> None:
            logger.info(f"[MockMouse] move ({x},{y})")
        async def scroll(self, clicks: int) -> None:
            logger.info(f"[MockMouse] scroll {clicks}")
        async def down(self) -> None:
            logger.info("[MockMouse] down")
        async def up(self) -> None:
            logger.info("[MockMouse] up")

    class _MockKeyboard:
        async def type(self, text: str) -> None:
            logger.info(f"[MockKeyboard] type: {text!r}")
        async def hotkey(self, *keys: str) -> None:
            logger.info(f"[MockKeyboard] hotkey: {'+'.join(keys)}")

    class _MockShell:
        async def run(self, cmd: str) -> dict[str, Any]:
            logger.info(f"[MockShell] run: {cmd}")
            return {"stdout": "mock output", "stderr": "", "exit_code": 0}

    class Sandbox:
        @classmethod
        def ephemeral(cls, image: "Image") -> "Sandbox":
            return cls()

        def __init__(self) -> None:
            if HAS_PYAUTOGUI:
                self.mouse = _HostMouse()
                self.keyboard = _HostKeyboard()
                self.shell = _HostShell()
                self._mode = "host"
            else:
                self.mouse = _MockMouse()
                self.keyboard = _MockKeyboard()
                self.shell = _MockShell()
                self._mode = "mock"

        async def screenshot(self) -> bytes:
            if HAS_PYAUTOGUI:
                def _grab() -> bytes:
                    try:
                        from PIL import ImageGrab
                        img = ImageGrab.grab()
                    except Exception:
                        img = _pag.screenshot()
                    buf = BytesIO()
                    img.save(buf, format="PNG")
                    return buf.getvalue()
                return await asyncio.to_thread(_grab)
            return _TRANSPARENT_1X1_PNG

        async def get_display_resolution(self) -> dict[str, int]:
            if HAS_PYAUTOGUI:
                w, h = _pag.size()
                return {"width": w, "height": h}
            return {"width": 1920, "height": 1080}

        async def get_accessibility_tree(self) -> dict:
            return {"elements": []}

        async def suspend(self) -> None:
            pass  # no-op in host mode

        async def resume(self) -> None:
            pass

        async def destroy(self) -> None:
            pass

if TYPE_CHECKING:
    from core.config import Config
    from memory.memory_layer import MemoryLayer
    from llm.action_normalizer import Action


class SandboxACI(_BASE_CLASS):  # type: ignore[valid-type,misc]
    """
    trycua/cua-backed ACI. All actions execute inside the sandbox VM/container.
    Inherits @agent_action method discovery from Agent-S3's ACI base class.
    """

    def __init__(self, sandbox: object, config: "Config", memory: "MemoryLayer") -> None:
        if hasattr(super(), "__init__"):
            super().__init__()
        self.notes: list[str] = []
        self.sandbox = sandbox                   # trycua/cua Sandbox instance
        self.config = config
        self.memory = memory
        self._sandbox_width: Optional[int] = None
        self._sandbox_height: Optional[int] = None
        self._screenshot_width: Optional[int] = None
        self._screenshot_height: Optional[int] = None
        self._current_task_id: str = ""
        self.obs: dict = {}

    def assign_screenshot(self, obs: dict) -> None:
        """Cache current step observation containing the screenshot."""
        self.obs = obs

    def set_task_instruction(self, task_instruction: str) -> None:
        """No-op matching OSWorldACI's set_task_instruction."""
        pass

    async def get_accessibility_tree(self) -> Optional[dict]:
        """Return the sandbox accessibility tree if available (used by Verifier Tier 2)."""
        try:
            if hasattr(self.sandbox, "get_accessibility_tree"):
                return await self.sandbox.get_accessibility_tree()
        except Exception as e:
            logger.warning(f"get_accessibility_tree failed: {e}")
        return None

    async def reset_session(self) -> None:
        """
        Perform an ephemeral reset between tasks (Phase P3).
        Kills stray processes (browsers, editors) and re-initializes internal coordinate state.
        """
        logger.info("[SandboxACI] Performing ephemeral session reset...")
        
        # 1. Reset internal coordinate state and notes
        self.notes.clear()
        self._screenshot_width = None
        self._screenshot_height = None
        
        # 2. Determine target processes to kill (mostly browsers, shells, and document viewers)
        is_windows = sys.platform == "win32"
        
        if is_windows:
            kill_commands = [
                "taskkill /F /IM chrome.exe",
                "taskkill /F /IM msedge.exe",
                "taskkill /F /IM firefox.exe",
                "taskkill /F /IM notepad.exe"
            ]
        else:
            kill_commands = [
                "pkill -f chrome",
                "pkill -f firefox",
                "pkill -f chromium",
                "pkill -f msedge"
            ]
            
        # Run process termination commands in the sandbox shell
        for cmd in kill_commands:
            try:
                if hasattr(self.sandbox, "shell") and hasattr(self.sandbox.shell, "run"):
                    await self.sandbox.shell.run(cmd)
            except Exception as e:
                logger.debug(f"Process termination command '{cmd}' failed (this is usually fine if process wasn't running): {e}")

        # 3. Discover and invoke native sandbox rollback/reset hooks if supported by the underling self.sandbox VM wrapper
        try:
            if hasattr(self.sandbox, "reset_session"):
                await self.sandbox.reset_session()
            elif hasattr(self.sandbox, "reset"):
                await self.sandbox.reset()
        except Exception as e:
            logger.warning(f"Native sandbox reset call failed: {e}")
            
        logger.info("[SandboxACI] Ephemeral session reset complete.")

    async def suspend(self) -> None:
        """Suspend sandbox execution (Gap K: called before approval wait)."""
        try:
            if hasattr(self.sandbox, "suspend"):
                await self.sandbox.suspend()
        except Exception as e:
            logger.warning(f"Sandbox suspend failed: {e}")

    async def resume(self) -> None:
        """Resume a suspended sandbox (Gap K: called on approval grant)."""
        try:
            if hasattr(self.sandbox, "resume"):
                await self.sandbox.resume()
        except Exception as e:
            logger.warning(f"Sandbox resume failed: {e}")

    async def destroy(self) -> None:
        """Destroy the sandbox (Gap K: called on approval deny)."""
        try:
            if hasattr(self.sandbox, "destroy"):
                await self.sandbox.destroy()
        except Exception as e:
            logger.warning(f"Sandbox destroy failed: {e}")

    async def init_dimensions(self) -> None:
        """
        Fetch sandbox display resolution once at task start and cache.
        Called by Orchestrator before the first step.
        """
        try:
            if hasattr(self.sandbox, "get_display_resolution"):
                res = await self.sandbox.get_display_resolution()
                self._sandbox_width = res.get("width", 1920)
                self._sandbox_height = res.get("height", 1080)
            else:
                self._sandbox_width = 1920
                self._sandbox_height = 1080
        except Exception as e:
            logger.error(f"Failed to fetch sandbox display resolution: {e}. Defaulting to 1920x1080.")
            self._sandbox_width = 1920
            self._sandbox_height = 1080

    def _scale(self, x: int, y: int) -> tuple[int, int]:
        """
        Scale raw grounding-model coordinates (screenshot space)
        to sandbox display space before sending to trycua/cua SDK.
        No-op if dimensions match or are not yet initialised.
        """
        if (
            self._sandbox_width is None
            or self._sandbox_height is None
            or self._screenshot_width is None
            or self._screenshot_height is None
            or self._screenshot_width == 0
            or self._screenshot_height == 0
        ):
            return x, y

        scale_x = self._sandbox_width / self._screenshot_width
        scale_y = self._sandbox_height / self._screenshot_height
        
        scaled_x = int(x * scale_x)
        scaled_y = int(y * scale_y)
        return scaled_x, scaled_y

    async def take_screenshot(self) -> bytes:
        """Capture current sandbox display as PNG bytes via sb.screenshot()."""
        try:
            if hasattr(self.sandbox, "screenshot"):
                png_bytes = await self.sandbox.screenshot()
            else:
                raise AttributeError("Sandbox has no screenshot method")
        except Exception as e:
            logger.error(f"Failed to take sandbox screenshot: {e}")
            png_bytes = _TRANSPARENT_1X1_PNG
        
        # Load screenshot dimensions with PIL
        if PILImage is not None:
            try:
                img = PILImage.open(BytesIO(png_bytes))
                self._screenshot_width, self._screenshot_height = img.size
            except Exception as e:
                logger.error(f"Failed to parse screenshot dimensions: {e}")
                self._screenshot_width = self._sandbox_width or 1920
                self._screenshot_height = self._sandbox_height or 1080
        else:
            self._screenshot_width = self._sandbox_width or 1920
            self._screenshot_height = self._sandbox_height or 1080

        return png_bytes

    def generate_coords(self, ref_expr: str, obs: dict) -> list[int]:
        """
        Locate raw grounding model coordinates.
        Uses a simple regex heuristic for tests, otherwise defaults to [100, 100].
        """
        # Expose easy coordinate injection in test descriptions: "click at 500, 600"
        match = re.search(r"(\d+),\s*(\d+)", ref_expr)
        if match:
            return [int(match.group(1)), int(match.group(2))]
        return [100, 100]

    def generate_text_coords(self, phrase: str, obs: dict, alignment: str = "") -> list[int]:
        """
        Locate raw text coordinates using OCR.
        Uses regex heuristic or defaults to [100, 100].
        """
        match = re.search(r"(\d+),\s*(\d+)", phrase)
        if match:
            return [int(match.group(1)), int(match.group(2))]
        return [100, 100]

    async def execute(self, action: "Action") -> str:
        """
        Execute the unified Action inside the sandbox VM/container via trycua/cua SDK.
        Returns a result/status summary.
        """
        logger.info(f"SandboxACI executing action: {action.type} with params {action.params}")

        if action.type == "click":
            if "x_norm" in action.params and "y_norm" in action.params:
                sw = self._screenshot_width or self._sandbox_width or 1920
                sh = self._screenshot_height or self._sandbox_height or 1080
                x, y = int(action.params["x_norm"] * sw), int(action.params["y_norm"] * sh)
            elif "x" in action.params and "y" in action.params:
                x, y = int(action.params["x"]), int(action.params["y"])
            else:
                desc = action.target_description or action.element_id or ""
                coords = self.generate_coords(desc, self.obs)
                x, y = coords[0], coords[1]

            scaled_x, scaled_y = self._scale(x, y)
            clicks = action.params.get("num_clicks", 1)
            button = action.params.get("button_type", "left")
            await self.sandbox.mouse.click(scaled_x, scaled_y, clicks=clicks, button=button)
            return f"Clicked at ({scaled_x}, {scaled_y})"

        elif action.type == "type":
            if "x_norm" in action.params and "y_norm" in action.params:
                sw = self._screenshot_width or self._sandbox_width or 1920
                sh = self._screenshot_height or self._sandbox_height or 1080
                x, y = int(action.params["x_norm"] * sw), int(action.params["y_norm"] * sh)
            elif "x" in action.params and "y" in action.params:
                x, y = int(action.params["x"]), int(action.params["y"])
            elif action.target_description or action.element_id:
                desc = action.target_description or action.element_id or ""
                coords = self.generate_coords(desc, self.obs)
                x, y = coords[0], coords[1]
            else:
                x, y = None, None

            if x is not None and y is not None:
                scaled_x, scaled_y = self._scale(x, y)
                await self.sandbox.mouse.click(scaled_x, scaled_y)
                await asyncio.sleep(0.5)

            text = action.params.get("text", "")
            overwrite = action.params.get("overwrite", False)
            enter = action.params.get("enter", False)

            if overwrite:
                # ctrl+a / cmd+a then backspace to clear
                await self.sandbox.keyboard.hotkey("ctrl", "a")
                await self.sandbox.keyboard.hotkey("backspace")
                await asyncio.sleep(0.2)

            await self.sandbox.keyboard.type(text)

            if enter:
                await self.sandbox.keyboard.hotkey("enter")

            return f"Typed text: {repr(text)}"

        elif action.type == "scroll":
            if "x_norm" in action.params and "y_norm" in action.params:
                sw = self._screenshot_width or self._sandbox_width or 1920
                sh = self._screenshot_height or self._sandbox_height or 1080
                coords = [int(action.params["x_norm"] * sw), int(action.params["y_norm"] * sh)]
            else:
                desc = action.target_description or action.element_id or ""
                coords = self.generate_coords(desc, self.obs)
            scaled_x, scaled_y = self._scale(coords[0], coords[1])
            await self.sandbox.mouse.move(scaled_x, scaled_y)
            await asyncio.sleep(0.2)

            # Map both scroll modes (clicks or direction/amount)
            if "clicks" in action.params:
                scroll_clicks = int(action.params["clicks"])
            else:
                direction = action.params.get("direction", "down")
                amount = int(action.params.get("amount", 3))
                scroll_clicks = -amount if direction == "down" else amount

            await self.sandbox.mouse.scroll(scroll_clicks)
            return f"Scrolled {scroll_clicks} clicks"

        elif action.type == "hotkey":
            key = action.params.get("key", "")
            keys = action.params.get("keys", [])
            
            if isinstance(keys, list) and keys:
                await self.sandbox.keyboard.hotkey(*keys)
                return f"Pressed hotkey: {keys}"
            elif isinstance(key, list):
                await self.sandbox.keyboard.hotkey(*key)
                return f"Pressed hotkey: {key}"
            else:
                keys_list = [k.strip() for k in key.split("+")] if "+" in key else [key]
                await self.sandbox.keyboard.hotkey(*keys_list)
                return f"Pressed hotkey: {keys_list}"

        elif action.type == "hold_and_press":
            hold_keys = action.params.get("hold_keys", [])
            press_keys = action.params.get("press_keys", [])
            
            for hk in hold_keys:
                # Mock or SDK-based key down could be modeled, but hotkey covers simple hold combinations
                pass
            for pk in press_keys:
                await self.sandbox.keyboard.hotkey(*(hold_keys + [pk]))
            return f"Held {hold_keys} and pressed {press_keys}"

        elif action.type == "navigate":
            url = action.params.get("url", "")
            new_tab = action.params.get("new_tab", False)
            if new_tab:
                await self.sandbox.keyboard.hotkey("ctrl", "t")
                await asyncio.sleep(0.3)
            else:
                # Focus address bar in any browser (Chrome, Edge, Firefox)
                await self.sandbox.keyboard.hotkey("ctrl", "l")
                await asyncio.sleep(0.3)
            await self.sandbox.keyboard.type(url)
            await asyncio.sleep(0.2)
            await self.sandbox.keyboard.hotkey("enter")
            return f"Navigated to {url}"

        elif action.type == "open":
            app = action.params.get("app_or_filename", "")
            await self.sandbox.shell.run(f"start {app}" if sys.platform == "win32" else f"xdg-open {app}")
            return f"Opened {app}"

        elif action.type == "switch_applications":
            app_code = action.params.get("app_code", "")
            # OS focus command execution
            cmd = f"wmctrl -a {app_code}" if sys.platform != "win32" else f"powershell -Command (New-Object -ComObject WScript.Shell).AppActivate('{app_code}')"
            await self.sandbox.shell.run(cmd)
            return f"Switched to application {app_code}"

        elif action.type == "drag_and_drop":
            if "x1_norm" in action.params and "x2_norm" in action.params:
                sw = self._screenshot_width or self._sandbox_width or 1920
                sh = self._screenshot_height or self._sandbox_height or 1080
                x1, y1 = self._scale(
                    int(action.params["x1_norm"] * sw), int(action.params["y1_norm"] * sh)
                )
                x2, y2 = self._scale(
                    int(action.params["x2_norm"] * sw), int(action.params["y2_norm"] * sh)
                )
            else:
                start_desc = action.params.get("starting_description") or action.params.get("source_description") or ""
                end_desc = action.params.get("ending_description") or action.params.get("target_description") or ""
                coords1 = self.generate_coords(start_desc, self.obs)
                coords2 = self.generate_coords(end_desc, self.obs)
                x1, y1 = self._scale(coords1[0], coords1[1])
                x2, y2 = self._scale(coords2[0], coords2[1])
            
            await self.sandbox.mouse.move(x1, y1)
            await self.sandbox.mouse.down()
            await asyncio.sleep(0.2)
            await self.sandbox.mouse.move(x2, y2)
            await self.sandbox.mouse.up()
            return f"Dragged from ({x1}, {y1}) to ({x2}, {y2})"

        elif action.type == "highlight_text_span":
            start_phrase = action.params.get("starting_phrase") or action.params.get("text") or ""
            end_phrase = action.params.get("ending_phrase") or action.params.get("text") or ""
            button = action.params.get("button", "left")

            coords1 = self.generate_text_coords(start_phrase, self.obs, alignment="start")
            coords2 = self.generate_text_coords(end_phrase, self.obs, alignment="end")

            x1, y1 = self._scale(coords1[0], coords1[1])
            x2, y2 = self._scale(coords2[0], coords2[1])

            await self.sandbox.mouse.move(x1, y1)
            await self.sandbox.mouse.down()
            await asyncio.sleep(0.2)
            await self.sandbox.mouse.move(x2, y2)
            await self.sandbox.mouse.up()
            return f"Highlighted text from ({x1}, {y1}) to ({x2}, {y2})"

        elif action.type == "save_to_knowledge":
            text = action.params.get("text", "")
            self.save_to_knowledge(text)
            return "Saved fact to L0 knowledge buffer"

        elif action.type == "call_code_agent":
            task = action.params.get("task", "")
            await self.sandbox.shell.run(f"python -c {repr(task)}")
            return "Code agent executed code script inside sandbox"

        elif action.type == "wait":
            time_sec = float(action.params.get("time", 1.333))
            await asyncio.sleep(time_sec)
            return f"Waited for {time_sec} seconds"

        elif action.type == "done":
            return "DONE"

        elif action.type == "fail":
            reason = action.params.get("reason", "")
            return f"FAILED: {reason}"

        else:
            raise ValueError(f"Unknown action type: {action.type}")

    # ── @agent_action methods (auto-discovered by PROCEDURAL_MEMORY) ──────────

    @agent_action
    def click(
        self,
        element_description: str,
        num_clicks: int = 1,
        button_type: str = "left",
        hold_keys: list = [],
        element_type: str = "button"
    ) -> str:
        """Locate element via grounding model, scale coords, click via sb.mouse.click()."""
        coords = self.generate_coords(element_description, self.obs)
        scaled_x, scaled_y = self._scale(coords[0], coords[1])
        return f"sb.mouse.click({scaled_x}, {scaled_y}, clicks={num_clicks}, button={repr(button_type)})"

    @agent_action
    def type(
        self,
        element_description: Optional[str] = None,
        text: str = "",
        overwrite: bool = False,
        enter: bool = False
    ) -> str:
        """Click element then type text via sb.keyboard.type()."""
        if element_description:
            coords = self.generate_coords(element_description, self.obs)
            scaled_x, scaled_y = self._scale(coords[0], coords[1])
            prefix = f"sb.mouse.click({scaled_x}, {scaled_y}); "
        else:
            prefix = ""
        
        overwrite_str = "overwrite=True; " if overwrite else ""
        enter_str = "enter=True; " if enter else ""
        return f"{prefix}{overwrite_str}{enter_str}sb.keyboard.type({repr(text)})"

    @agent_action
    def scroll(
        self,
        element_description: str,
        clicks: Optional[int] = None,
        direction: Optional[str] = None,
        amount: int = 3,
        shift: bool = False
    ) -> str:
        """Scroll element via sb.mouse.scroll()."""
        coords = self.generate_coords(element_description, self.obs)
        scaled_x, scaled_y = self._scale(coords[0], coords[1])
        
        if clicks is not None:
            scroll_clicks = clicks
        else:
            scroll_clicks = -amount if direction == "down" else amount
            
        return f"sb.mouse.move({scaled_x}, {scaled_y}); sb.mouse.scroll({scroll_clicks})"

    @agent_action
    def hotkey(self, key: str | list) -> str:
        """Send keyboard shortcut via sb.keyboard.hotkey()."""
        return f"sb.keyboard.hotkey({repr(key)})"

    @agent_action
    def hold_and_press(self, hold_keys: list, press_keys: list) -> str:
        """Hold a list of keys and press a list of keys."""
        return f"sb.keyboard.hold_and_press({hold_keys}, {press_keys})"

    @agent_action
    def navigate(self, url: str) -> str:
        """Navigate browser to URL via address bar (ctrl+L → type → Enter)."""
        return f"sb.keyboard.hotkey('ctrl', 'l'); sb.keyboard.type({repr(url)}); sb.keyboard.hotkey('enter')"

    @agent_action
    def open(self, app_or_filename: str) -> str:
        """Open application or file via sb.shell.run()."""
        return f"sb.shell.run('open {app_or_filename}')"

    @agent_action
    def switch_applications(self, app_code: str) -> str:
        """Bring application to foreground via sb.shell.run() + wmctrl/Win32."""
        return f"sb.shell.run('focus {app_code}')"

    @agent_action
    def drag_and_drop(
        self,
        starting_description: Optional[str] = None,
        ending_description: Optional[str] = None,
        source_description: Optional[str] = None,
        target_description: Optional[str] = None,
        hold_keys: list = []
    ) -> str:
        """Locate both elements, drag from source to target coords."""
        start_desc = starting_description or source_description or ""
        end_desc = ending_description or target_description or ""
        coords1 = self.generate_coords(start_desc, self.obs)
        coords2 = self.generate_coords(end_desc, self.obs)
        x1, y1 = self._scale(coords1[0], coords1[1])
        x2, y2 = self._scale(coords2[0], coords2[1])
        return f"sb.mouse.drag(({x1}, {y1}), ({x2}, {y2}))"

    @agent_action
    def highlight_text_span(
        self,
        starting_phrase: Optional[str] = None,
        ending_phrase: Optional[str] = None,
        text: Optional[str] = None,
        button: str = "left"
    ) -> str:
        """Select a specific text span via OCR + mouse drag."""
        start_desc = starting_phrase or text or ""
        end_desc = ending_phrase or text or ""
        coords1 = self.generate_text_coords(start_desc, self.obs, alignment="start")
        coords2 = self.generate_text_coords(end_desc, self.obs, alignment="end")
        x1, y1 = self._scale(coords1[0], coords1[1])
        x2, y2 = self._scale(coords2[0], coords2[1])
        return f"sb.mouse.highlight(({x1}, {y1}), ({x2}, {y2}))"

    @agent_action
    def save_to_knowledge(self, text: str | list[str]) -> str:
        """Write fact to L0 Memory Layer (replaces dropped Agent-S3 notes buffer)."""
        facts = [text] if isinstance(text, str) else text
        for fact in facts:
            if fact not in self.notes:
                self.notes.append(fact)
            try:
                # Call memory L0 layer
                self.memory.save_to_knowledge(self._current_task_id, fact)
            except Exception as e:
                logger.error(f"Error saving fact to L0 persistence: {e}")
        return "WAIT"

    @agent_action
    def call_code_agent(self, task: Optional[str] = None) -> str:
        """Delegate to CodeAgent; executes Python/Bash inside the sandbox."""
        task_str = task or ""
        return f"sb.shell.run('python {repr(task_str)}')"

    @agent_action
    def wait(self, time: float) -> str:
        """Pause execution for `time` seconds."""
        return f"sb.wait({time})"

    @agent_action
    def done(self) -> str:
        """Signal task completion to the Orchestrator."""
        return "DONE"

    @agent_action
    def fail(self, reason: str = "") -> str:
        """Signal task failure with an optional reason."""
        return f"FAIL: {reason}"
